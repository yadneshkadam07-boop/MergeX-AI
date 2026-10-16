"""Python front-end, built on the standard library's :mod:`ast`.

No Tree-sitter here. CPython's own parser is exact, carries precise line and
column spans including ``end_lineno``, and cannot drift from the language. The
only thing it will not do is parse a file with a syntax error, which is
handled by reporting the failure and moving on.

Like the JS/TS parser this is a syntax layer: it answers "what is written
here", never "is this right".
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Final

from app.core.logging import get_logger
from app.services.parsers.base import SourceFile, SourceLocation

__all__ = [
    "PYTHON_SUFFIXES",
    "ParsedPythonModule",
    "SyntaxErrorInfo",
    "call_keyword",
    "dotted_name",
    "literal_value",
    "parse_source",
]

log = get_logger("app.parsers.python")

PYTHON_SUFFIXES: Final[frozenset[str]] = frozenset({".py", ".pyi"})


@dataclass(frozen=True, slots=True)
class SyntaxErrorInfo:
    """A file that could not be parsed at all."""

    location: SourceLocation
    message: str


@dataclass(frozen=True, slots=True)
class ParsedPythonModule:
    """A parsed Python file, kept with the text it came from."""

    source: SourceFile
    tree: ast.Module

    def location_of(self, node: ast.AST) -> SourceLocation:
        """Convert a node's span to a :class:`SourceLocation`.

        ``ast`` line numbers are already 1-based. ``end_lineno`` is absent on
        a few node types, in which case the range collapses to one line.
        """
        line_start = getattr(node, "lineno", 1)
        line_end = getattr(node, "end_lineno", None) or line_start
        return self.source.location(
            line_start,
            line_end,
            col_start=getattr(node, "col_offset", None),
            col_end=getattr(node, "end_col_offset", None),
        )

    def walk(self) -> list[ast.AST]:
        return list(ast.walk(self.tree))

    def functions(self) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
        """Every function and coroutine, at any nesting depth."""
        return [
            node
            for node in ast.walk(self.tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]

    def classes(self) -> list[ast.ClassDef]:
        return [node for node in ast.walk(self.tree) if isinstance(node, ast.ClassDef)]

    def calls(self) -> list[ast.Call]:
        return [node for node in ast.walk(self.tree) if isinstance(node, ast.Call)]

    def imported_names(self) -> dict[str, str]:
        """Map local name -> fully-qualified origin.

        ``from fastapi import APIRouter as R`` yields ``{"R": "fastapi.APIRouter"}``.
        Needed to tell a local ``Column`` apart from ``sqlalchemy.Column``.
        """
        names: dict[str, str] = {}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    names[alias.asname or alias.name.split(".")[0]] = alias.name
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    local = alias.asname or alias.name
                    names[local] = f"{module}.{alias.name}" if module else alias.name
        return names


def parse_source(source: SourceFile) -> ParsedPythonModule | SyntaxErrorInfo | None:
    """Parse a Python file.

    Returns:
        A :class:`ParsedPythonModule` on success, :class:`SyntaxErrorInfo` if
        the file does not parse, or None if it is not a Python file.

    A syntax error is returned rather than raised because one unparseable file
    must not abort the analysis of a repository -- and "this file does not
    parse" is itself worth reporting.
    """
    if source.suffix not in PYTHON_SUFFIXES:
        return None

    try:
        tree = ast.parse(source.text, filename=source.relative_path)
    except SyntaxError as exc:
        line = exc.lineno or 1
        log.debug("python_syntax_error", file=source.relative_path, line=line)
        return SyntaxErrorInfo(
            location=source.location(line),
            message=exc.msg,
        )
    except ValueError as exc:
        # Source containing NUL bytes, or a recursion limit on pathological
        # nesting.
        log.debug("python_unparseable", file=source.relative_path, error=str(exc))
        return SyntaxErrorInfo(location=source.location(1), message=str(exc))

    return ParsedPythonModule(source=source, tree=tree)


def dotted_name(node: ast.AST | None) -> str | None:
    """Render an attribute/name chain as a dotted string.

    ``router.get`` -> ``"router.get"``; ``app.routers.users.router.get`` ->
    the full chain. Returns None when the chain contains anything dynamic,
    such as ``getattr(x, y)`` or a subscript.
    """
    parts: list[str] = []
    current = node
    while True:
        if isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        elif isinstance(current, ast.Name):
            parts.append(current.id)
            return ".".join(reversed(parts))
        elif isinstance(current, ast.Call):
            # `APIRouter().get` -- keep the callee's name and stop.
            inner = dotted_name(current.func)
            if inner is None:
                return None
            parts.append(inner)
            return ".".join(reversed(parts))
        else:
            return None


def literal_value(node: ast.AST | None) -> str | int | float | bool | None:
    """Return a statically known literal, or None.

    Adjacent string literals are already merged by CPython's parser, so an SQL
    statement written across several lines arrives here as one value. A
    runtime expression (an f-string with substitutions, a name, a call)
    returns None, because its value is not knowable without execution.
    """
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, (str, int, float, bool)):
            return value
        return None
    return None


def call_keyword(call: ast.Call, name: str) -> ast.expr | None:
    """The value of a keyword argument, or None if it is not passed."""
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def call_positional(call: ast.Call, index: int) -> ast.expr | None:
    """The nth positional argument, or None."""
    if index < len(call.args):
        argument = call.args[index]
        # `f(*args)` -- position is not knowable.
        if isinstance(argument, ast.Starred):
            return None
        return argument
    return None


def decorator_calls(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[tuple[str, ast.Call | None, ast.expr]]:
    """Every decorator on a function, as ``(dotted_name, call, node)``.

    ``call`` is None for a bare decorator such as ``@login_required``, and set
    for an invoked one such as ``@router.get("/users")``.
    """
    results: list[tuple[str, ast.Call | None, ast.expr]] = []
    for decorator in function.decorator_list:
        if isinstance(decorator, ast.Call):
            name = dotted_name(decorator.func)
            if name is not None:
                results.append((name, decorator, decorator))
        else:
            name = dotted_name(decorator)
            if name is not None:
                results.append((name, None, decorator))
    return results


def string_items(node: ast.AST | None) -> list[str]:
    """Read a list/tuple/set of string literals, skipping non-literals.

    Used for things like ``allow_origins=["*"]`` and
    ``dependencies=[Depends(x)]``, where only the literal members matter.
    """
    if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return []
    values: list[str] = []
    for element in node.elts:
        value = literal_value(element)
        if isinstance(value, str):
            values.append(value)
    return values
