"""Extract the database schema from migration files.

The schema is built by **replaying migrations in order**, not by reading the
latest ``CREATE TABLE``. That distinction is the whole point: a column added
in migration 5 and dropped in migration 9 does not exist, and a tool that only
looked at ``CREATE TABLE`` would claim it does.

Statements understood:

* ``CREATE TABLE`` -- columns, types, inline constraints, table constraints
* ``ALTER TABLE ... ADD COLUMN`` / ``DROP COLUMN`` / ``ALTER COLUMN TYPE``
* ``ALTER TABLE ... ADD CONSTRAINT`` (foreign keys, uniques, primary keys)
* ``CREATE INDEX`` / ``CREATE UNIQUE INDEX``
* ``DROP TABLE`` / ``ALTER TABLE ... RENAME``

Types are reduced to a canonical family (``integer``, ``decimal``, ``string``,
…) so that ``NUMERIC(10,2)`` against ``INTEGER`` reads as a mismatch while
``VARCHAR(200)`` against ``VARCHAR(64)`` does not -- the latter is a length
difference, which is a different and much weaker finding.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from sqlglot import exp

from app.core.logging import get_logger
from app.services.parsers.base import SourceFile, SourceLocation, iter_source_files
from app.services.parsers.sql_parser import SQL_SUFFIXES, ParsedStatement, parse_sql_file

__all__ = [
    "DbColumn",
    "DbForeignKey",
    "DbIndex",
    "DbSchema",
    "DbTable",
    "canonical_type",
    "extract_db_schema",
]

log = get_logger("app.extractors.db_schema")

# SQL type -> canonical family. Compared on the family, never on the raw text.
_TYPE_FAMILIES: Final[dict[str, str]] = {
    # integers
    "INT": "integer",
    "INTEGER": "integer",
    "SMALLINT": "integer",
    "BIGINT": "integer",
    "TINYINT": "integer",
    "SERIAL": "integer",
    "BIGSERIAL": "integer",
    "SMALLSERIAL": "integer",
    "INT2": "integer",
    "INT4": "integer",
    "INT8": "integer",
    # exact numerics -- deliberately NOT the same family as integer
    "DECIMAL": "decimal",
    "NUMERIC": "decimal",
    "MONEY": "decimal",
    # approximate numerics
    "FLOAT": "float",
    "REAL": "float",
    "DOUBLE": "float",
    "DOUBLE PRECISION": "float",
    # text
    "VARCHAR": "string",
    "CHAR": "string",
    "TEXT": "string",
    "NVARCHAR": "string",
    "NCHAR": "string",
    "CHARACTER VARYING": "string",
    "CITEXT": "string",
    "NAME": "string",
    # boolean
    "BOOLEAN": "boolean",
    "BOOL": "boolean",
    # temporal
    "TIMESTAMP": "datetime",
    "TIMESTAMPTZ": "datetime",
    "DATETIME": "datetime",
    "TIMESTAMPLTZ": "datetime",
    "DATE": "date",
    "TIME": "time",
    "TIMETZ": "time",
    "INTERVAL": "interval",
    # structured
    "JSON": "json",
    "JSONB": "json",
    "UUID": "uuid",
    "BYTEA": "binary",
    "BLOB": "binary",
    "VARBINARY": "binary",
    "ARRAY": "array",
    "ENUM": "enum",
}

_TYPE_PARAMS_RE: Final[re.Pattern[str]] = re.compile(r"\s*\(.*\)\s*$")


def canonical_type(sql_type: str | None) -> str:
    """Reduce a SQL type to its comparable family.

    ``VARCHAR(64)`` -> ``string``; ``NUMERIC(10,2)`` -> ``decimal``;
    ``SERIAL`` -> ``integer``. An unrecognised type returns lower-cased text,
    so a comparison still works between two spellings of the same thing.
    """
    if not sql_type:
        return "unknown"
    base = _TYPE_PARAMS_RE.sub("", sql_type).strip().upper()
    base = base.removesuffix("[]")
    if base.endswith(" WITH TIME ZONE") or base.endswith(" WITHOUT TIME ZONE"):
        base = base.split(" WITH")[0].strip()
    return _TYPE_FAMILIES.get(base, base.lower())


@dataclass(frozen=True, slots=True)
class DbForeignKey:
    """A foreign-key constraint as the database has it."""

    columns: tuple[str, ...]
    referenced_table: str
    referenced_columns: tuple[str, ...]
    location: SourceLocation
    on_delete: str | None = None
    constraint_name: str | None = None


@dataclass(frozen=True, slots=True)
class DbIndex:
    """An index, including the implicit one a UNIQUE constraint creates."""

    name: str | None
    columns: tuple[str, ...]
    is_unique: bool
    location: SourceLocation


@dataclass(slots=True)
class DbColumn:
    """One column that exists in the database."""

    name: str
    sql_type: str | None
    location: SourceLocation
    nullable: bool = True
    is_primary_key: bool = False
    is_unique: bool = False
    has_default: bool = False
    default_sql: str | None = None

    @property
    def type_family(self) -> str:
        return canonical_type(self.sql_type)


@dataclass(slots=True)
class DbTable:
    """One table that exists in the database."""

    name: str
    location: SourceLocation
    columns: dict[str, DbColumn] = field(default_factory=dict)
    foreign_keys: list[DbForeignKey] = field(default_factory=list)
    indexes: list[DbIndex] = field(default_factory=list)

    def column(self, name: str) -> DbColumn | None:
        """Look up a column case-insensitively, as SQL resolves names."""
        return self.columns.get(name.lower())

    @property
    def primary_key_columns(self) -> tuple[str, ...]:
        return tuple(name for name, column in self.columns.items() if column.is_primary_key)

    def indexed_columns(self) -> set[str]:
        """Columns covered by any index, including as a leading column."""
        covered: set[str] = set()
        for index in self.indexes:
            covered.update(column.lower() for column in index.columns)
        covered.update(self.primary_key_columns)
        covered.update(name for name, column in self.columns.items() if column.is_unique)
        return covered


@dataclass(slots=True)
class DbSchema:
    """The schema that the migrations, replayed in order, actually produce."""

    tables: dict[str, DbTable] = field(default_factory=dict)
    migration_files: list[str] = field(default_factory=list)
    statements_applied: int = 0
    statements_skipped: int = 0

    def table(self, name: str) -> DbTable | None:
        return self.tables.get(name.lower())

    @property
    def is_empty(self) -> bool:
        return not self.tables

    def all_columns(self) -> list[tuple[str, DbColumn]]:
        return [
            (table_name, column)
            for table_name, table in sorted(self.tables.items())
            for column in table.columns.values()
        ]


def extract_db_schema(
    root: Path,
    *,
    subdirectories: tuple[str, ...] = (),
) -> DbSchema:
    """Build the schema from every ``.sql`` file under ``root``.

    Files are applied in sorted path order, which matches the numeric or
    timestamp prefixes every migration tool uses.
    """
    schema = DbSchema()
    search_roots = [root / sub for sub in subdirectories] if subdirectories else [root]

    sources: list[SourceFile] = []
    for search_root in search_roots:
        if not search_root.is_dir():
            continue
        for source in iter_source_files(search_root, SQL_SUFFIXES):
            sources.append(_rebase(source, root, search_root))

    for source in sorted(sources, key=lambda s: s.relative_path):
        schema.migration_files.append(source.relative_path)
        for statement in parse_sql_file(source):
            if _apply(schema, statement):
                schema.statements_applied += 1
            else:
                schema.statements_skipped += 1

    log.info(
        "db_schema_extracted",
        tables=len(schema.tables),
        files=len(schema.migration_files),
        applied=schema.statements_applied,
        skipped=schema.statements_skipped,
    )
    return schema


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


def _apply(schema: DbSchema, statement: ParsedStatement) -> bool:
    """Apply one statement to the schema. Returns False if it was ignored."""
    expression = statement.expression

    if isinstance(expression, exp.Create):
        kind = (expression.args.get("kind") or "").upper()
        if kind == "TABLE":
            return _apply_create_table(schema, statement, expression)
        if kind == "INDEX":
            return _apply_create_index(schema, statement, expression)
        return False

    if isinstance(expression, exp.Alter):
        return _apply_alter(schema, statement, expression)

    if isinstance(expression, exp.Drop):
        kind = (expression.args.get("kind") or "").upper()
        if kind == "TABLE":
            table = expression.find(exp.Table)
            if table is not None:
                schema.tables.pop(table.name.lower(), None)
                return True
        return False

    return False


def _apply_create_table(
    schema: DbSchema, statement: ParsedStatement, expression: exp.Create
) -> bool:
    table_expression = expression.find(exp.Table)
    if table_expression is None or not table_expression.name:
        return False

    name = table_expression.name
    table = DbTable(name=name, location=statement.location)

    for column_def in expression.find_all(exp.ColumnDef):
        column = _column_from_def(column_def, statement)
        table.columns[column.name.lower()] = column

    _apply_table_constraints(table, statement, expression)

    schema.tables[name.lower()] = table
    return True


def _column_from_def(column_def: exp.ColumnDef, statement: ParsedStatement) -> DbColumn:
    kind = column_def.args.get("kind")
    sql_type = kind.sql(dialect="postgres") if kind is not None else None
    line = statement.line_of(column_def.name)

    column = DbColumn(
        name=column_def.name,
        sql_type=sql_type,
        # The location is the column's own line, not the statement's, so the
        # evidence snippet points at the column a finding is about.
        location=SourceLocation(
            file_path=statement.location.file_path,
            line_start=line,
            line_end=line,
            snippet=_line_snippet(statement, line),
        ),
    )

    # SERIAL implies NOT NULL and a default, even with no explicit constraint.
    if canonical_type(sql_type) == "integer" and (sql_type or "").upper().endswith("SERIAL"):
        column.nullable = False
        column.has_default = True

    for constraint in column_def.constraints:
        kind_node = constraint.args.get("kind")
        if isinstance(kind_node, exp.NotNullColumnConstraint):
            # sqlglot uses one node for both spellings: `allow_null` is set for
            # an explicit `NULL` and absent for `NOT NULL`, so the flag *is*
            # nullability rather than its negation.
            column.nullable = bool(kind_node.args.get("allow_null"))
        elif isinstance(kind_node, exp.PrimaryKeyColumnConstraint):
            column.is_primary_key = True
            column.nullable = False
        elif isinstance(kind_node, exp.UniqueColumnConstraint):
            column.is_unique = True
        elif isinstance(kind_node, exp.DefaultColumnConstraint):
            column.has_default = True
            default = kind_node.this
            column.default_sql = default.sql(dialect="postgres") if default else None
        elif isinstance(kind_node, exp.GeneratedAsIdentityColumnConstraint):
            column.has_default = True
            column.nullable = False

    return column


def _apply_table_constraints(
    table: DbTable, statement: ParsedStatement, expression: exp.Expression
) -> None:
    """Record table-level PRIMARY KEY, UNIQUE and FOREIGN KEY clauses."""
    for primary_key in expression.find_all(exp.PrimaryKey):
        for column_ref in primary_key.expressions:
            existing = table.column(_name_of(column_ref))
            if existing is not None:
                existing.is_primary_key = True
                existing.nullable = False

    for unique in expression.find_all(exp.UniqueColumnConstraint):
        columns = tuple(_name_of(ref) for ref in getattr(unique.this, "expressions", []) or [])
        if columns:
            table.indexes.append(
                DbIndex(
                    name=None,
                    columns=columns,
                    is_unique=True,
                    location=statement.location,
                )
            )

    for foreign_key in expression.find_all(exp.ForeignKey):
        local = tuple(_name_of(ref) for ref in foreign_key.expressions)
        reference = foreign_key.args.get("reference")
        referenced_table, referenced_columns = _reference_target(reference)
        if not referenced_table:
            continue
        line = statement.line_of(local[0]) if local else statement.location.line_start
        table.foreign_keys.append(
            DbForeignKey(
                columns=local,
                referenced_table=referenced_table,
                referenced_columns=referenced_columns,
                on_delete=_on_delete(foreign_key),
                location=SourceLocation(
                    file_path=statement.location.file_path,
                    line_start=line,
                    line_end=line,
                    snippet=_line_snippet(statement, line),
                ),
            )
        )

    # An inline `REFERENCES` on a column definition.
    for column_def in expression.find_all(exp.ColumnDef):
        for constraint in column_def.constraints:
            kind_node = constraint.args.get("kind")
            if not isinstance(kind_node, exp.Reference):
                continue
            referenced_table, referenced_columns = _reference_target(kind_node)
            if not referenced_table:
                continue
            line = statement.line_of(column_def.name)
            table.foreign_keys.append(
                DbForeignKey(
                    columns=(column_def.name,),
                    referenced_table=referenced_table,
                    referenced_columns=referenced_columns,
                    location=SourceLocation(
                        file_path=statement.location.file_path,
                        line_start=line,
                        line_end=line,
                        snippet=_line_snippet(statement, line),
                    ),
                )
            )


def _reference_target(reference: exp.Expression | None) -> tuple[str, tuple[str, ...]]:
    """The table and columns a REFERENCES clause points at."""
    if reference is None:
        return ("", ())
    schema_node = reference.this if isinstance(reference, exp.Reference) else reference
    table_node = schema_node.find(exp.Table) if schema_node is not None else None
    if table_node is None or not table_node.name:
        return ("", ())
    columns = tuple(_name_of(ref) for ref in getattr(schema_node, "expressions", []) or [])
    return (table_node.name, columns)


def _on_delete(foreign_key: exp.Expression) -> str | None:
    options = foreign_key.args.get("options")
    if not options:
        return None
    for option in options:
        text = str(option).upper()
        if "DELETE" in text:
            return text
    return None


def _apply_create_index(
    schema: DbSchema, statement: ParsedStatement, expression: exp.Create
) -> bool:
    index = expression.this
    if index is None:
        return False

    table_node = index.find(exp.Table)
    if table_node is None:
        return False
    table = schema.table(table_node.name)
    if table is None:
        return False

    # Only exp.Column: searching for Ordered as well returns the sort wrapper
    # *and* the column inside it, which duplicated every entry.
    columns = _unique(_name_of(column) for column in index.find_all(exp.Column))
    if not columns:
        columns = _unique(_name_of(part) for part in index.find_all(exp.Identifier))

    name_node = index.args.get("this")
    table.indexes.append(
        DbIndex(
            name=_name_of(name_node) or None,
            columns=columns,
            is_unique=bool(expression.args.get("unique")),
            location=statement.location,
        )
    )
    return True


def _apply_alter(schema: DbSchema, statement: ParsedStatement, expression: exp.Alter) -> bool:
    table_node = expression.find(exp.Table)
    if table_node is None:
        return False
    table = schema.table(table_node.name)
    if table is None:
        # ALTER on a table this scan never saw created.
        return False

    applied = False
    for action in expression.args.get("actions") or []:
        if isinstance(action, exp.ColumnDef):
            column = _column_from_def(action, statement)
            table.columns[column.name.lower()] = column
            applied = True
        elif isinstance(action, exp.Drop):
            kind = (action.args.get("kind") or "").upper()
            if kind == "COLUMN":
                target = action.find(exp.Column) or action.find(exp.Identifier)
                name = _name_of(target)
                if name:
                    table.columns.pop(name.lower(), None)
                    applied = True
        elif isinstance(action, exp.AlterColumn):
            name = _name_of(action.this)
            existing = table.column(name) if name else None
            if existing is not None:
                new_type = action.args.get("dtype")
                if new_type is not None:
                    existing.sql_type = new_type.sql(dialect="postgres")
                if action.args.get("drop"):
                    existing.nullable = True
                if action.args.get("not_null") is not None:
                    existing.nullable = not action.args["not_null"]
                applied = True
        elif isinstance(action, (exp.ForeignKey, exp.PrimaryKey, exp.UniqueColumnConstraint)):
            _apply_table_constraints(table, statement, action)
            applied = True
        elif isinstance(action, exp.AddConstraint):
            for constraint in action.expressions:
                _apply_table_constraints(table, statement, constraint)
            applied = True
    return applied


def _unique(names: Iterable[str]) -> tuple[str, ...]:
    """Drop blanks and duplicates while preserving order."""
    return tuple(dict.fromkeys(name for name in names if name))


def _name_of(node: exp.Expression | None) -> str:
    """The identifier text of a node, or empty string."""
    if node is None:
        return ""
    if isinstance(node, exp.Identifier):
        return node.name
    name = getattr(node, "name", "")
    if name:
        return str(name)
    identifier = node.find(exp.Identifier) if isinstance(node, exp.Expression) else None
    return identifier.name if identifier is not None else ""


def _line_snippet(statement: ParsedStatement, line: int) -> str:
    """One line of evidence, relative to the statement's own snippet."""
    offset = line - statement.location.line_start
    lines = statement.location.snippet.splitlines()
    if 0 <= offset < len(lines):
        return lines[offset].strip()
    return statement.location.snippet.splitlines()[0].strip() if lines else ""
