"""Extract ORM model definitions -- the schema the *application* believes in.

Comparing this against :mod:`app.services.extractors.db_schema` is what finds
drift: a field the code reads that the database never created, a type the two
disagree about, a relationship with no foreign key behind it.

Supported:

* **SQLAlchemy**, both dialects of declarative mapping:

  .. code-block:: python

     name = Column(String(200), nullable=False)          # classic
     name: Mapped[str] = mapped_column(String(200))      # 2.0 style

* **Prisma** ``schema.prisma`` models.

SQLAlchemy types are reduced to the same canonical families as SQL types, so
``Numeric(10, 2)`` and ``NUMERIC(10,2)`` compare equal while ``Numeric`` and
``Integer`` do not.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from app.core.logging import get_logger
from app.services.extractors.db_schema import canonical_type
from app.services.parsers.base import SourceFile, SourceLocation, iter_source_files
from app.services.parsers.python_parser import (
    PYTHON_SUFFIXES,
    ParsedPythonModule,
    SyntaxErrorInfo,
    call_keyword,
    call_positional,
    dotted_name,
    literal_value,
    parse_source as parse_python,
)

__all__ = [
    "OrmField",
    "OrmModel",
    "OrmRelationship",
    "OrmExtraction",
    "extract_orm_models",
    "sqlalchemy_type_family",
]

log = get_logger("app.extractors.orm_models")

# SQLAlchemy type constructor -> canonical family. Mirrors the SQL families in
# db_schema so the two sides are directly comparable.
_SA_TYPE_FAMILIES: Final[dict[str, str]] = {
    "Integer": "integer",
    "BigInteger": "integer",
    "SmallInteger": "integer",
    "INTEGER": "integer",
    "BIGINT": "integer",
    "SMALLINT": "integer",
    "Numeric": "decimal",
    "DECIMAL": "decimal",
    "NUMERIC": "decimal",
    "Float": "float",
    "REAL": "float",
    "DOUBLE": "float",
    "Double": "float",
    "String": "string",
    "Unicode": "string",
    "Text": "string",
    "UnicodeText": "string",
    "VARCHAR": "string",
    "CHAR": "string",
    "TEXT": "string",
    "Boolean": "boolean",
    "BOOLEAN": "boolean",
    "DateTime": "datetime",
    "TIMESTAMP": "datetime",
    "Date": "date",
    "Time": "time",
    "Interval": "interval",
    "JSON": "json",
    "JSONB": "json",
    "Uuid": "uuid",
    "UUID": "uuid",
    "LargeBinary": "binary",
    "BLOB": "binary",
    "ARRAY": "array",
    "Enum": "enum",
}

# Python annotation -> canonical family, for `Mapped[...]` with no explicit
# SQLAlchemy type.
_PY_TYPE_FAMILIES: Final[dict[str, str]] = {
    "int": "integer",
    "str": "string",
    "bool": "boolean",
    "float": "float",
    "Decimal": "decimal",
    "datetime": "datetime",
    "date": "date",
    "time": "time",
    "UUID": "uuid",
    "uuid.UUID": "uuid",
    "bytes": "binary",
    "dict": "json",
    "list": "array",
}

# Prisma scalar -> canonical family.
_PRISMA_TYPE_FAMILIES: Final[dict[str, str]] = {
    "Int": "integer",
    "BigInt": "integer",
    "Float": "float",
    "Decimal": "decimal",
    "String": "string",
    "Boolean": "boolean",
    "DateTime": "datetime",
    "Json": "json",
    "Bytes": "binary",
}

_SA_COLUMN_FACTORIES: Final[frozenset[str]] = frozenset({"Column", "mapped_column"})


def sqlalchemy_type_family(type_name: str | None) -> str:
    """Reduce a SQLAlchemy type name to its canonical family."""
    if not type_name:
        return "unknown"
    base = type_name.split("(")[0].rpartition(".")[2].strip()
    if base in _SA_TYPE_FAMILIES:
        return _SA_TYPE_FAMILIES[base]
    # Fall back to the SQL table, which covers dialect types spelled in SQL.
    return canonical_type(base)


@dataclass(frozen=True, slots=True)
class OrmRelationship:
    """A ``relationship()`` declaration, which implies a foreign key."""

    name: str
    target_model: str | None
    location: SourceLocation
    back_populates: str | None = None
    foreign_keys_declared: bool = False
    """True when the model also declares a ForeignKey for this link.

    A relationship with no foreign key anywhere is the signature of
    schema drift, so this distinction matters.
    """


@dataclass(slots=True)
class OrmField:
    """One field the application expects the database to have."""

    name: str
    column_name: str
    """The database column, which may differ from the attribute name."""
    location: SourceLocation
    type_name: str | None = None
    type_family: str = "unknown"
    nullable: bool = True
    is_primary_key: bool = False
    is_unique: bool = False
    has_default: bool = False
    foreign_key: str | None = None
    """Target as written, e.g. ``suppliers.id``."""


@dataclass(slots=True)
class OrmModel:
    """One mapped class."""

    class_name: str
    table_name: str
    location: SourceLocation
    orm: str
    fields: dict[str, OrmField] = field(default_factory=dict)
    relationships: list[OrmRelationship] = field(default_factory=list)

    def field_by_column(self, column_name: str) -> OrmField | None:
        for value in self.fields.values():
            if value.column_name.lower() == column_name.lower():
                return value
        return None


@dataclass(slots=True)
class OrmExtraction:
    """Every model found, plus files that could not be parsed."""

    models: list[OrmModel] = field(default_factory=list)
    unparseable_files: list[SyntaxErrorInfo] = field(default_factory=list)

    def by_table(self) -> dict[str, OrmModel]:
        return {model.table_name.lower(): model for model in self.models}


def extract_orm_models(
    root: Path,
    *,
    subdirectories: tuple[str, ...] = (),
) -> OrmExtraction:
    """Extract ORM models under ``root``."""
    extraction = OrmExtraction()
    search_roots = [root / sub for sub in subdirectories] if subdirectories else [root]

    for search_root in search_roots:
        if not search_root.is_dir():
            continue
        for source in iter_source_files(search_root, PYTHON_SUFFIXES | {".prisma"}):
            rebased = _rebase(source, root, search_root)
            if rebased.suffix == ".prisma":
                extraction.models.extend(_extract_prisma(rebased))
                continue
            parsed = parse_python(rebased)
            if isinstance(parsed, SyntaxErrorInfo):
                extraction.unparseable_files.append(parsed)
            elif parsed is not None:
                extraction.models.extend(_extract_sqlalchemy(parsed))

    extraction.models.sort(key=lambda m: (m.location.file_path, m.location.line_start))
    log.info("orm_models_extracted", count=len(extraction.models))
    return extraction


def _rebase(source: SourceFile, root: Path, search_root: Path) -> SourceFile:
    if search_root == root:
        return source
    try:
        prefix = search_root.relative_to(root).as_posix()
    except ValueError:  # pragma: no cover - defensive
        return source
    return SourceFile(
        relative_path=f"{prefix}/{source.relative_path}",
        text=source.text,
        lines=source.lines,
    )


# ---------------------------------------------------------------------------
# SQLAlchemy
# ---------------------------------------------------------------------------


def _extract_sqlalchemy(module: ParsedPythonModule) -> list[OrmModel]:
    """Find mapped classes in a Python module.

    A class is mapped if it declares ``__tablename__``. That is a stronger
    signal than inheriting from something called ``Base``, which may be
    aliased, imported through several modules, or a mixin.
    """
    models: list[OrmModel] = []

    for class_def in module.classes():
        table_name = _tablename_of(class_def)
        if table_name is None:
            continue

        model = OrmModel(
            class_name=class_def.name,
            table_name=table_name,
            location=module.location_of(class_def),
            orm="sqlalchemy",
        )

        for statement in class_def.body:
            _collect_sqlalchemy_member(module, model, statement)

        _mark_relationship_foreign_keys(model)
        models.append(model)

    return models


def _tablename_of(class_def: ast.ClassDef) -> str | None:
    for statement in class_def.body:
        targets: list[ast.expr] = []
        # `AnnAssign.value` is optional (`x: int` with no assignment), so the
        # declared type has to admit None.
        value: ast.expr | None
        if isinstance(statement, ast.Assign):
            targets = list(statement.targets)
            value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
            value = statement.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "__tablename__":
                name = literal_value(value)
                if isinstance(name, str):
                    return name
    return None


def _collect_sqlalchemy_member(
    module: ParsedPythonModule, model: OrmModel, statement: ast.stmt
) -> None:
    """Read one class-body statement as a field or a relationship."""
    if isinstance(statement, ast.AnnAssign):
        if not isinstance(statement.target, ast.Name):
            return
        name = statement.target.id
        annotation = _mapped_annotation(statement.annotation)
        call = statement.value if isinstance(statement.value, ast.Call) else None
    elif isinstance(statement, ast.Assign):
        if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
            return
        name = statement.targets[0].id
        annotation = None
        call = statement.value if isinstance(statement.value, ast.Call) else None
    else:
        return

    if name.startswith("__"):
        return

    # `dotted_name` returns None for a dynamic callee such as
    # `getattr(mod, name)(...)`, so it cannot be dereferenced directly.
    factory_path = dotted_name(call.func) if call is not None else None
    factory = factory_path.rpartition(".")[2] if factory_path is not None else None

    if factory == "relationship":
        model.relationships.append(
            OrmRelationship(
                name=name,
                target_model=_relationship_target(call) if call else None,
                location=module.location_of(statement),
                back_populates=_string_kwarg(call, "back_populates") if call else None,
            )
        )
        return

    # `Mapped[str]` with no call at all is still a mapped column in 2.0 style.
    if factory is None and annotation is None:
        return
    if factory is not None and factory not in _SA_COLUMN_FACTORIES:
        return

    model.fields[name] = _build_field(module, name, statement, call, annotation)


def _build_field(
    module: ParsedPythonModule,
    name: str,
    statement: ast.stmt,
    call: ast.Call | None,
    annotation: _MappedAnnotation | None,
) -> OrmField:
    column_name = name
    type_name: str | None = None
    nullable: bool | None = None
    is_primary_key = False
    is_unique = False
    has_default = False
    foreign_key: str | None = None

    if call is not None:
        # A leading string argument renames the column: Column("col", String).
        first = call_positional(call, 0)
        literal_first = literal_value(first)
        if isinstance(literal_first, str):
            column_name = literal_first

        type_name = _column_type_name(call)
        foreign_key = _foreign_key_target(call)

        explicit_nullable = literal_value(call_keyword(call, "nullable"))
        if isinstance(explicit_nullable, bool):
            nullable = explicit_nullable
        is_primary_key = literal_value(call_keyword(call, "primary_key")) is True
        is_unique = literal_value(call_keyword(call, "unique")) is True
        has_default = any(
            call_keyword(call, keyword) is not None
            for keyword in ("default", "server_default", "default_factory")
        )

    if annotation is not None:
        if nullable is None:
            nullable = annotation.optional
        if type_name is None:
            type_name = annotation.inner

    if is_primary_key:
        nullable = False

    family = (
        sqlalchemy_type_family(type_name)
        if type_name and type_name not in _PY_TYPE_FAMILIES
        else _PY_TYPE_FAMILIES.get(type_name or "", sqlalchemy_type_family(type_name))
    )

    return OrmField(
        name=name,
        column_name=column_name,
        location=module.location_of(statement),
        type_name=type_name,
        type_family=family,
        nullable=True if nullable is None else nullable,
        is_primary_key=is_primary_key,
        is_unique=is_unique,
        has_default=has_default,
        foreign_key=foreign_key,
    )


@dataclass(frozen=True, slots=True)
class _MappedAnnotation:
    """The parts of a ``Mapped[...]`` annotation that matter."""

    inner: str | None
    optional: bool


def _mapped_annotation(annotation: ast.expr | None) -> _MappedAnnotation | None:
    """Decompose ``Mapped[str | None]`` into its type and nullability.

    In SQLAlchemy 2.0 the annotation is authoritative for nullability unless
    ``nullable=`` says otherwise, so ``Mapped[str | None]`` means NULL is
    allowed.
    """
    if not isinstance(annotation, ast.Subscript):
        return None
    base = dotted_name(annotation.value)
    if base is None or base.rpartition(".")[2] != "Mapped":
        return None

    inner = annotation.slice
    optional = False

    if isinstance(inner, ast.BinOp) and isinstance(inner.op, ast.BitOr):
        left, right = inner.left, inner.right
        for side in (left, right):
            if isinstance(side, ast.Constant) and side.value is None:
                optional = True
        non_none = [
            side
            for side in (left, right)
            if not (isinstance(side, ast.Constant) and side.value is None)
        ]
        inner = non_none[0] if non_none else inner
    elif isinstance(inner, ast.Subscript):
        base_inner = dotted_name(inner.value)
        if base_inner is not None and base_inner.rpartition(".")[2] == "Optional":
            optional = True
            inner = inner.slice

    return _MappedAnnotation(inner=_type_text(inner), optional=optional)


def _type_text(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Subscript):
        return _type_text(node.value)
    return dotted_name(node)


def _column_type_name(call: ast.Call) -> str | None:
    """The SQLAlchemy type passed to ``Column`` / ``mapped_column``.

    Accepts both ``Column(String(200))`` and ``Column(String)``, and skips a
    leading column-name string.
    """
    for index in (0, 1):
        argument = call_positional(call, index)
        if argument is None:
            continue
        if isinstance(argument, ast.Constant):
            continue  # the column-name string
        if isinstance(argument, ast.Call):
            name = dotted_name(argument.func)
            if name is not None and name.rpartition(".")[2] != "ForeignKey":
                return name.rpartition(".")[2]
            continue
        name = dotted_name(argument)
        if name is not None:
            return name.rpartition(".")[2]
    type_keyword = call_keyword(call, "type_")
    if type_keyword is not None:
        if isinstance(type_keyword, ast.Call):
            inner = dotted_name(type_keyword.func)
            return inner.rpartition(".")[2] if inner else None
        name = dotted_name(type_keyword)
        return name.rpartition(".")[2] if name else None
    return None


def _foreign_key_target(call: ast.Call) -> str | None:
    """The target of a ``ForeignKey("table.column")`` argument."""
    for argument in [*call.args, *(keyword.value for keyword in call.keywords)]:
        if not isinstance(argument, ast.Call):
            continue
        name = dotted_name(argument.func)
        if name is None or name.rpartition(".")[2] != "ForeignKey":
            continue
        target = literal_value(call_positional(argument, 0))
        if isinstance(target, str):
            return target
    return None


def _relationship_target(call: ast.Call) -> str | None:
    """The model a ``relationship()`` points at."""
    first = call_positional(call, 0)
    target = literal_value(first)
    if isinstance(target, str):
        return target
    if first is not None:
        return dotted_name(first)
    argument = call_keyword(call, "argument")
    value = literal_value(argument)
    return value if isinstance(value, str) else None


def _string_kwarg(call: ast.Call, name: str) -> str | None:
    value = literal_value(call_keyword(call, name))
    return value if isinstance(value, str) else None


def _mark_relationship_foreign_keys(model: OrmModel) -> None:
    """Note whether each relationship has a foreign key behind it.

    A ``relationship()`` with no ``ForeignKey`` on any field of the model is
    exactly the pattern that produces an orphanable row, so the fact is
    recorded here where both halves are in view.
    """
    has_any_fk = any(field_.foreign_key for field_ in model.fields.values())
    model.relationships[:] = [
        OrmRelationship(
            name=relationship.name,
            target_model=relationship.target_model,
            location=relationship.location,
            back_populates=relationship.back_populates,
            foreign_keys_declared=has_any_fk,
        )
        for relationship in model.relationships
    ]


# ---------------------------------------------------------------------------
# Prisma
# ---------------------------------------------------------------------------

_PRISMA_MODEL_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*model\s+(?P<name>\w+)\s*\{", re.MULTILINE
)
_PRISMA_FIELD_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?P<name>\w+)\s+(?P<type>[\w\[\]]+)(?P<optional>\?)?(?P<rest>.*)$"
)
_PRISMA_MAP_RE: Final[re.Pattern[str]] = re.compile(r'@map\(\s*"(?P<name>[^"]+)"\s*\)')
_PRISMA_TABLE_MAP_RE: Final[re.Pattern[str]] = re.compile(r'@@map\(\s*"(?P<name>[^"]+)"\s*\)')
_PRISMA_RELATION_RE: Final[re.Pattern[str]] = re.compile(
    r"@relation\([^)]*fields:\s*\[(?P<fields>[^\]]*)\][^)]*references:\s*\[(?P<refs>[^\]]*)\]"
)


def _extract_prisma(source: SourceFile) -> list[OrmModel]:
    """Parse ``schema.prisma`` models.

    Prisma's schema language is small and regular enough to read line by line;
    there is no Python parser for it, and pulling in a grammar for a format
    this simple is not worth the dependency.
    """
    models: list[OrmModel] = []

    for match in _PRISMA_MODEL_RE.finditer(source.text):
        class_name = match.group("name")
        start_line = source.text.count("\n", 0, match.start()) + 1
        body_lines, end_line = _prisma_block(source, start_line)

        model = OrmModel(
            class_name=class_name,
            table_name=class_name,
            location=source.location(start_line, end_line),
            orm="prisma",
        )

        for offset, line in body_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            table_map = _PRISMA_TABLE_MAP_RE.search(stripped)
            if table_map is not None:
                model.table_name = table_map.group("name")
                continue
            if stripped.startswith("@@"):
                continue
            field_match = _PRISMA_FIELD_RE.match(line)
            if field_match is None:
                continue
            _add_prisma_field(model, source, field_match, offset)

        models.append(model)

    return models


def _prisma_block(source: SourceFile, start_line: int) -> tuple[list[tuple[int, str]], int]:
    """The lines inside a ``model { ... }`` block, with 1-based line numbers."""
    collected: list[tuple[int, str]] = []
    depth = 0
    for index in range(start_line - 1, len(source.lines)):
        line = source.lines[index]
        depth += line.count("{") - line.count("}")
        if index > start_line - 1:
            collected.append((index + 1, line))
        if depth <= 0 and index > start_line - 1:
            return (collected[:-1], index + 1)
    return (collected, len(source.lines))


def _add_prisma_field(model: OrmModel, source: SourceFile, match: re.Match[str], line: int) -> None:
    name = match.group("name")
    raw_type = match.group("type")
    rest = match.group("rest") or ""
    optional = bool(match.group("optional"))

    base_type = raw_type.removesuffix("[]")
    # A field whose type is another model is a relation, not a column.
    if base_type not in _PRISMA_TYPE_FAMILIES and base_type[:1].isupper():
        relation = _PRISMA_RELATION_RE.search(rest)
        model.relationships.append(
            OrmRelationship(
                name=name,
                target_model=base_type,
                location=source.location(line),
                foreign_keys_declared=relation is not None,
            )
        )
        return

    column_map = _PRISMA_MAP_RE.search(rest)
    model.fields[name] = OrmField(
        name=name,
        column_name=column_map.group("name") if column_map else name,
        location=source.location(line),
        type_name=raw_type,
        type_family=_PRISMA_TYPE_FAMILIES.get(base_type, base_type.lower()),
        nullable=optional,
        is_primary_key="@id" in rest,
        is_unique="@unique" in rest,
        has_default="@default" in rest,
    )
