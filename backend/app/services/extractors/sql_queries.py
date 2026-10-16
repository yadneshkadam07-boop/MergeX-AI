"""Extract raw SQL embedded in application source.

Why this exists as its own extractor: an ORM protects you from referring to a
column that does not exist, and raw SQL does not. ``session.execute(text(...))``
bypasses every check the ORM would have made, so a ``SELECT`` naming a dropped
column fails only in production. That is the ``MX-DB-003`` case in the
``react_fastapi_schema_drift`` fixture.

A string is treated as SQL when it *looks* like SQL -- it begins with a DML or
DDL keyword -- and confidence is raised when it is also passed to a known
execution function (``text()``, ``execute()``, ``raw()``, ``query()``). Shape
first, context second: a query assigned to a variable and executed three lines
later is still a query.

Column references are reported with their own line numbers, computed from
sqlglot's token stream offset by the literal's position in the host file, so a
finding can point at the offending column rather than the whole statement.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from app.core.logging import get_logger
from app.services.parsers.base import SourceFile, SourceLocation, iter_source_files
from app.services.parsers.js_ts_parser import (
    JS_TS_SUFFIXES,
    ParsedModule,
    node_text,
    parse_source as parse_js,
    string_literal_value,
)
from app.services.parsers.python_parser import (
    PYTHON_SUFFIXES,
    ParsedPythonModule,
    dotted_name,
    parse_source as parse_python,
)

__all__ = [
    "SqlQuery",
    "extract_sql_queries",
    "looks_like_sql",
]

log = get_logger("app.extractors.sql_queries")

# A string must start with one of these to be considered SQL. Anchoring at the
# start keeps prose that merely mentions "select" from matching.
_SQL_START_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:--[^\n]*\n\s*)*"
    r"(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|WITH|CREATE\s+(TABLE|INDEX|VIEW)"
    r"|ALTER\s+TABLE|DROP\s+(TABLE|INDEX|VIEW)|TRUNCATE)\b",
    re.IGNORECASE,
)

# Functions whose string argument is definitely executed as SQL.
_EXECUTOR_NAMES: Final[frozenset[str]] = frozenset(
    {
        "text",
        "execute",
        "executemany",
        "exec_driver_sql",
        "raw",
        "query",
        "fetch",
        "fetchall",
        "fetchone",
        "fetchval",
        "fetchrow",
        "scalar",
        "run",
        "unsafe",
        "sql",
        "$queryRaw",
        "$executeRaw",
        "queryRaw",
        "executeRaw",
    }
)

# Placeholders that must be neutralised before parsing: a bind marker is not
# valid SQL on its own and would make the statement unparseable.
_PLACEHOLDER_RE: Final[re.Pattern[str]] = re.compile(
    r":\w+"  # :named (SQLAlchemy)
    r"|%\((\w+)\)s"  # %(named)s (psycopg)
    r"|%s"  # %s positional
    r"|\?"  # ? positional
    r"|\$\d+"  # $1 (asyncpg)
    r"|\$\{[^}]*\}"  # ${x} (JS template)
)


@dataclass(frozen=True, slots=True)
class SqlQuery:
    """One SQL statement found embedded in application code."""

    location: SourceLocation
    sql: str
    statement_kind: str
    """``select``, ``insert``, ``update``, ``delete``, ``ddl`` or ``unknown``."""
    tables: tuple[str, ...] = ()
    column_references: tuple[tuple[str | None, str], ...] = ()
    """``(qualifier, column)`` pairs. Qualifier is None when unqualified."""
    column_locations: dict[str, SourceLocation] = field(default_factory=dict)
    """Column name -> where it appears, for precise evidence."""
    callee: str | None = None
    confidence: float = 1.0
    is_parseable: bool = True

    @property
    def columns(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(column for _, column in self.column_references))

    def __str__(self) -> str:
        return f"{self.statement_kind} on {','.join(self.tables) or '?'} ({self.location})"


def looks_like_sql(value: str) -> bool:
    """True when a string's shape is that of a SQL statement."""
    return bool(value) and _SQL_START_RE.match(value) is not None


def extract_sql_queries(
    root: Path,
    *,
    subdirectories: tuple[str, ...] = (),
) -> list[SqlQuery]:
    """Extract embedded SQL from Python and JS/TS sources under ``root``."""
    queries: list[SqlQuery] = []
    search_roots = [root / sub for sub in subdirectories] if subdirectories else [root]

    for search_root in search_roots:
        if not search_root.is_dir():
            continue
        for source in iter_source_files(search_root, PYTHON_SUFFIXES | JS_TS_SUFFIXES):
            rebased = _rebase(source, root, search_root)
            if rebased.suffix in PYTHON_SUFFIXES:
                parsed = parse_python(rebased)
                if isinstance(parsed, ParsedPythonModule):
                    queries.extend(_from_python(parsed))
            else:
                module = parse_js(rebased)
                if module is not None:
                    queries.extend(_from_js(module))

    queries.sort(key=lambda q: (q.location.file_path, q.location.line_start))
    log.info("sql_queries_extracted", count=len(queries))
    return queries


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


def _from_python(module: ParsedPythonModule) -> list[SqlQuery]:
    """Find SQL string literals in a Python module.

    Adjacent string literals are merged by CPython's own parser, so a
    statement split across several source lines arrives as a single
    ``Constant`` whose ``lineno``/``end_lineno`` already span all of them.
    """
    # Map a string node to the call that encloses it, for the callee hint.
    enclosing: dict[int, str] = {}
    for call in module.calls():
        callee = dotted_name(call.func)
        if callee is None:
            continue
        member = callee.rpartition(".")[2]
        for argument in [*call.args, *(keyword.value for keyword in call.keywords)]:
            for node in ast.walk(argument):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    enclosing.setdefault(id(node), member)

    queries: list[SqlQuery] = []
    for node in ast.walk(module.tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if not looks_like_sql(node.value):
            continue
        callee = enclosing.get(id(node))
        queries.append(
            _build_query(
                source=module.source,
                sql=node.value,
                location=module.location_of(node),
                callee=callee,
            )
        )
    return queries


def _from_js(module: ParsedModule) -> list[SqlQuery]:
    """Find SQL string and template literals in a JS/TS module."""
    pattern = """
    [(string) (template_string)] @literal
    """
    queries: list[SqlQuery] = []
    for captures in module.query(pattern):
        for node in captures.get("literal", []):
            value = string_literal_value(module.source, node)
            if value is None or not looks_like_sql(value):
                continue
            parent = node.parent
            callee = None
            while parent is not None:
                if parent.type == "call_expression":
                    function_node = parent.child_by_field_name("function")
                    if function_node is not None:
                        callee = node_text(module.source, function_node).rpartition(".")[2]
                    break
                parent = parent.parent
            queries.append(
                _build_query(
                    source=module.source,
                    sql=value,
                    location=module.location_of(node),
                    callee=callee,
                )
            )
    return queries


def _build_query(
    *,
    source: SourceFile,
    sql: str,
    location: SourceLocation,
    callee: str | None,
) -> SqlQuery:
    """Parse one SQL string into a :class:`SqlQuery`."""
    sanitised = _PLACEHOLDER_RE.sub("1", sql)
    confidence = 1.0 if callee in _EXECUTOR_NAMES else 0.7

    expression = _parse(sanitised)
    if expression is None:
        return SqlQuery(
            location=location,
            sql=sql.strip(),
            statement_kind=_kind_from_text(sql),
            callee=callee,
            confidence=min(confidence, 0.5),
            is_parseable=False,
        )

    references: list[tuple[str | None, str]] = []
    for column in expression.find_all(exp.Column):
        name = column.name
        if not name or name == "*":
            continue
        references.append((column.table or None, name))

    tables = tuple(
        dict.fromkeys(table.name for table in expression.find_all(exp.Table) if table.name)
    )

    return SqlQuery(
        location=location,
        sql=sql.strip(),
        statement_kind=_kind_from_expression(expression),
        tables=tables,
        column_references=tuple(dict.fromkeys(references)),
        column_locations=_column_locations(source, sanitised, location),
        callee=callee,
        confidence=confidence,
    )


def _parse(sql: str) -> exp.Expression | None:
    for dialect in ("postgres", None):
        try:
            parsed = sqlglot.parse(sql, dialect=dialect)
        except (ParseError, TokenError, RecursionError):
            continue
        for expression in parsed:
            if expression is not None:
                return expression
    return None


def _column_locations(
    source: SourceFile, sql: str, location: SourceLocation
) -> dict[str, SourceLocation]:
    """Map each identifier in the SQL to a line in the *host* file.

    sqlglot reports lines relative to the SQL string; adding the literal's
    start line (less one, since both are 1-based) converts them to host-file
    lines. A query written on one line gives every column that same line,
    which is correct.
    """
    try:
        tokens = sqlglot.tokenize(sql, dialect="postgres")
    except (TokenError, ParseError):
        return {}

    offset = location.line_start - 1
    locations: dict[str, SourceLocation] = {}
    for token in tokens:
        text = token.text.strip('"`[]')
        if not text or not text.replace("_", "").isalnum():
            continue
        line = min(max(token.line + offset, location.line_start), location.line_end)
        locations.setdefault(
            text.lower(),
            source.location(line, line),
        )
    return locations


def _kind_from_expression(expression: exp.Expression) -> str:
    if isinstance(expression, exp.Select):
        return "select"
    if isinstance(expression, exp.Insert):
        return "insert"
    if isinstance(expression, exp.Update):
        return "update"
    if isinstance(expression, exp.Delete):
        return "delete"
    if isinstance(expression, (exp.Create, exp.Alter, exp.Drop)):
        return "ddl"
    return "unknown"


def _kind_from_text(sql: str) -> str:
    match = _SQL_START_RE.match(sql)
    if match is None:
        return "unknown"
    keyword = match.group(1).split()[0].upper()
    return {
        "SELECT": "select",
        "INSERT": "insert",
        "UPDATE": "update",
        "DELETE": "delete",
        "WITH": "select",
    }.get(keyword, "ddl")
