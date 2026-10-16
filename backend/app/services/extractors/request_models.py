"""Extract request/response schema classes -- the field names a layer expects.

Needed by ``MX-API-004``: to know that a frontend sending ``fullName`` is
wrong, you have to know the backend model declares ``full_name``. Without the
model there is nothing to compare against and the rule cannot run.

Pydantic only for now. A TypeScript ``interface`` describes what the frontend
*believes*, which is a different and weaker signal than what the server
actually validates, so it is not used for this comparison.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from app.core.logging import get_logger
from app.services.parsers.base import SourceFile, SourceLocation, iter_source_files
from app.services.parsers.python_parser import (
    PYTHON_SUFFIXES,
    ParsedPythonModule,
    call_keyword,
    dotted_name,
    literal_value,
    parse_source as parse_python,
)

__all__ = [
    "RequestModel",
    "RequestModelField",
    "extract_request_models",
    "to_snake_case",
]

log = get_logger("app.extractors.request_models")

# Base classes that mean "this class validates incoming data".
_SCHEMA_BASES: Final[frozenset[str]] = frozenset(
    {"BaseModel", "BaseSettings", "Schema", "ModelSchema"}
)

_CAMEL_BOUNDARY: Final[re.Pattern[str]] = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def to_snake_case(name: str) -> str:
    """``fullName`` -> ``full_name``. Used to recognise casing drift."""
    return _CAMEL_BOUNDARY.sub("_", name).lower()


@dataclass(frozen=True, slots=True)
class RequestModelField:
    """One declared field of a schema class."""

    name: str
    location: SourceLocation
    annotation: str | None = None
    alias: str | None = None
    """A ``Field(alias=...)`` or ``serialization_alias``.

    Important for precision: a model with ``alias="fullName"`` accepts the
    camelCase name, so sending it is *correct* and must not be reported.
    """
    required: bool = True

    @property
    def accepted_names(self) -> frozenset[str]:
        """Every name this field will accept from a request body."""
        names = {self.name}
        if self.alias:
            names.add(self.alias)
        return frozenset(names)


@dataclass(slots=True)
class RequestModel:
    """A schema class and its fields."""

    class_name: str
    location: SourceLocation
    fields: dict[str, RequestModelField] = field(default_factory=dict)
    populate_by_name: bool = False
    """True when ``model_config`` allows either the field name or its alias."""
    alias_generator: bool = False
    """True when an alias generator is configured.

    A generator (``alias_generator=to_camel``) means the model accepts names
    this extractor cannot enumerate, so field-name comparison must be skipped
    entirely rather than guessed at.
    """
    allows_extra: bool = False
    """True when ``extra="allow"``: unknown fields are accepted, not dropped."""

    @property
    def accepted_names(self) -> frozenset[str]:
        """Every body key this model accepts."""
        names: set[str] = set()
        for model_field in self.fields.values():
            names |= model_field.accepted_names
        return frozenset(names)

    @property
    def is_comparable(self) -> bool:
        """False when the model's accepted names cannot be enumerated."""
        return bool(self.fields) and not self.alias_generator and not self.allows_extra

    def field_for(self, name: str) -> RequestModelField | None:
        """Find a field by any name it accepts, then by snake_case equivalence."""
        for model_field in self.fields.values():
            if name in model_field.accepted_names:
                return model_field
        target = to_snake_case(name)
        for model_field in self.fields.values():
            if to_snake_case(model_field.name) == target:
                return model_field
        return None


def extract_request_models(
    root: Path,
    *,
    subdirectories: tuple[str, ...] = (),
) -> dict[str, RequestModel]:
    """Extract schema classes under ``root``, keyed by class name.

    A name declared twice is dropped rather than guessed at: comparing against
    the wrong model would produce false findings, which is worse than not
    running the rule.
    """
    seen: dict[str, list[RequestModel]] = {}
    search_roots = [root / sub for sub in subdirectories] if subdirectories else [root]

    for search_root in search_roots:
        if not search_root.is_dir():
            continue
        for source in iter_source_files(search_root, PYTHON_SUFFIXES):
            rebased = _rebase(source, root, search_root)
            parsed = parse_python(rebased)
            if not isinstance(parsed, ParsedPythonModule):
                continue
            for model in _models_in(parsed):
                seen.setdefault(model.class_name, []).append(model)

    models = {name: group[0] for name, group in seen.items() if len(group) == 1}
    ambiguous = [name for name, group in seen.items() if len(group) > 1]
    if ambiguous:
        log.debug("request_models_ambiguous", names=ambiguous)
    log.info("request_models_extracted", count=len(models), ambiguous=len(ambiguous))
    return models


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


def _models_in(module: ParsedPythonModule) -> list[RequestModel]:
    models: list[RequestModel] = []

    for class_def in module.classes():
        if not _is_schema_class(class_def):
            continue

        model = RequestModel(
            class_name=class_def.name,
            location=module.location_of(class_def),
        )
        _read_model_config(module, class_def, model)

        for statement in class_def.body:
            if not isinstance(statement, ast.AnnAssign) or not isinstance(
                statement.target, ast.Name
            ):
                continue
            name = statement.target.id
            if name.startswith("_") or name == "model_config":
                continue
            model.fields[name] = RequestModelField(
                name=name,
                location=module.location_of(statement),
                annotation=_annotation_text(statement.annotation),
                alias=_field_alias(statement.value),
                required=statement.value is None,
            )

        models.append(model)

    return models


def _is_schema_class(class_def: ast.ClassDef) -> bool:
    """True when a class inherits from a schema base.

    Matched on the base's short name so ``pydantic.BaseModel``, an imported
    ``BaseModel`` and a project's own ``class Base(BaseModel)`` subclass of a
    schema all qualify.
    """
    for base in class_def.bases:
        name = dotted_name(base)
        if name is not None and name.rpartition(".")[2] in _SCHEMA_BASES:
            return True
    return False


def _read_model_config(
    module: ParsedPythonModule, class_def: ast.ClassDef, model: RequestModel
) -> None:
    """Read ``model_config``, which decides whether comparison is even valid."""
    for statement in class_def.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(statement, ast.Assign):
            targets = list(statement.targets)
            value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
            value = statement.value

        is_config = any(
            isinstance(target, ast.Name) and target.id == "model_config" for target in targets
        )
        if not is_config or not isinstance(value, ast.Call):
            continue

        if literal_value(call_keyword(value, "populate_by_name")) is True:
            model.populate_by_name = True
        if call_keyword(value, "alias_generator") is not None:
            model.alias_generator = True
        if literal_value(call_keyword(value, "extra")) == "allow":
            model.allows_extra = True

    # Pydantic v1 style: `class Config: allow_population_by_field_name = True`
    for statement in class_def.body:
        if not isinstance(statement, ast.ClassDef) or statement.name != "Config":
            continue
        for inner in statement.body:
            if not isinstance(inner, ast.Assign):
                continue
            for target in inner.targets:
                if not isinstance(target, ast.Name):
                    continue
                if target.id == "alias_generator":
                    model.alias_generator = True
                if target.id == "extra" and literal_value(inner.value) == "allow":
                    model.allows_extra = True
    _ = module  # locations for config are not reported


def _field_alias(value: ast.expr | None) -> str | None:
    """The alias from ``Field(alias="fullName")``, if there is one."""
    if not isinstance(value, ast.Call):
        return None
    callee = dotted_name(value.func)
    if callee is None or callee.rpartition(".")[2] != "Field":
        return None
    for keyword in ("alias", "validation_alias", "serialization_alias"):
        alias = literal_value(call_keyword(value, keyword))
        if isinstance(alias, str):
            return alias
    return None


def _annotation_text(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Subscript):
        return _annotation_text(node.value)
    return dotted_name(node)
