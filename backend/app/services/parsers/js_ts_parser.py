"""Tree-sitter front-end for JavaScript, TypeScript and TSX.

A syntax layer only: it parses, runs queries and reads literals. It makes no
judgement about whether the code is correct — that is the rule engine's job in
Phase 3.

Three things worth knowing:

* **Grammars are per-dialect.** ``.ts`` and ``.tsx`` are *different* grammars,
  not a flag. Parsing ``.tsx`` with the TypeScript grammar silently mangles
  every JSX element, and parsing ``.ts`` with the TSX grammar misreads type
  assertions (``<T>x``) as JSX. The mapping is by file extension.
* **Parsers are not thread-safe**, so one is created per dialect per call site
  rather than shared across the thread pool.
* **Tree-sitter never fails.** A syntax error produces an ``ERROR`` node and a
  usable tree for the rest of the file, which is exactly right here: an
  AI-generated project with one broken file should still be analysed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Final

import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser, Query, QueryCursor, Tree

from app.core.logging import get_logger
from app.services.parsers.base import SourceFile, SourceLocation

__all__ = [
    "JS_TS_SUFFIXES",
    "Dialect",
    "ParsedModule",
    "node_location",
    "node_text",
    "parse_source",
    "run_query",
    "string_literal_value",
]

log = get_logger("app.parsers.js_ts")


class Dialect(StrEnum):
    """Which grammar a file needs."""

    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    TSX = "tsx"


# Extension -> grammar. `.jsx` uses the JavaScript grammar, which already
# includes JSX; only TypeScript splits JSX into a separate grammar.
_SUFFIX_DIALECTS: Final[dict[str, Dialect]] = {
    ".js": Dialect.JAVASCRIPT,
    ".jsx": Dialect.JAVASCRIPT,
    ".mjs": Dialect.JAVASCRIPT,
    ".cjs": Dialect.JAVASCRIPT,
    ".ts": Dialect.TYPESCRIPT,
    ".mts": Dialect.TYPESCRIPT,
    ".cts": Dialect.TYPESCRIPT,
    ".tsx": Dialect.TSX,
}

JS_TS_SUFFIXES: Final[frozenset[str]] = frozenset(_SUFFIX_DIALECTS)


@lru_cache(maxsize=4)
def _language(dialect: Dialect) -> Language:
    """Load and cache a grammar. Loading is relatively expensive."""
    if dialect is Dialect.JAVASCRIPT:
        return Language(tree_sitter_javascript.language())
    if dialect is Dialect.TYPESCRIPT:
        return Language(tree_sitter_typescript.language_typescript())
    return Language(tree_sitter_typescript.language_tsx())


@lru_cache(maxsize=64)
def _compiled_query(dialect: Dialect, pattern: str) -> Query:
    """Compile and cache a query.

    Compilation is the expensive part of running one, and the extractors reuse
    a small fixed set of patterns across every file in a repository.
    """
    return Query(_language(dialect), pattern)


def dialect_for(relative_path: str) -> Dialect | None:
    """The grammar for a path, or None if it is not JS/TS."""
    from pathlib import PurePosixPath

    return _SUFFIX_DIALECTS.get(PurePosixPath(relative_path).suffix.lower())


@dataclass(frozen=True, slots=True)
class ParsedModule:
    """A parsed JS/TS file, kept together with the text it came from."""

    source: SourceFile
    dialect: Dialect
    tree: Tree

    @property
    def root(self) -> Node:
        return self.tree.root_node

    @property
    def has_syntax_errors(self) -> bool:
        """True when the file did not parse cleanly.

        Not a failure: the tree is still usable. Findings from a file with
        syntax errors should carry lower confidence.
        """
        return self.root.has_error

    def text_of(self, node: Node) -> str:
        return node_text(self.source, node)

    def location_of(self, node: Node) -> SourceLocation:
        return node_location(self.source, node)

    def query(self, pattern: str) -> list[dict[str, list[Node]]]:
        """Run a query and return one dict of captures per match."""
        return run_query(self, pattern)


def parse_source(source: SourceFile) -> ParsedModule | None:
    """Parse a JS/TS file. Returns None if it is not a JS/TS file."""
    dialect = dialect_for(source.relative_path)
    if dialect is None:
        return None

    parser = Parser(_language(dialect))
    tree = parser.parse(source.data)
    module = ParsedModule(source=source, dialect=dialect, tree=tree)

    if module.has_syntax_errors:
        log.debug("syntax_errors_in_file", file=source.relative_path, dialect=dialect.value)
    return module


def run_query(module: ParsedModule, pattern: str) -> list[dict[str, list[Node]]]:
    """Run a Tree-sitter query over a module.

    Returns the captures of each match, in source order, so a caller can rely
    on the order of results being stable.
    """
    query = _compiled_query(module.dialect, pattern)
    matches = QueryCursor(query).matches(module.root)
    ordered = sorted(matches, key=lambda match: _match_start(match[1]))
    return [captures for _, captures in ordered]


def _match_start(captures: dict[str, list[Node]]) -> tuple[int, int]:
    """Earliest byte position in a match, for stable ordering."""
    starts = [node.start_byte for nodes in captures.values() for node in nodes]
    return (min(starts) if starts else 0, 0)


def node_text(source: SourceFile, node: Node) -> str:
    """The exact source text of a node."""
    return source.data[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def node_location(source: SourceFile, node: Node) -> SourceLocation:
    """Convert a node's span to a :class:`SourceLocation`.

    Tree-sitter rows are 0-based; :class:`SourceLocation` is 1-based.
    """
    return source.location(
        node.start_point[0] + 1,
        node.end_point[0] + 1,
        col_start=node.start_point[1],
        col_end=node.end_point[1],
    )


def string_literal_value(source: SourceFile, node: Node) -> str | None:
    """Read a string-ish node as text, or None if it is not statically known.

    Handles the four forms that appear in real API call sites:

    ``"/api/users"``            a plain string
    ``'/api/users'``            single-quoted
    ``` `/api/users` ```        a template with no substitutions
    ``` `/api/users/${id}` ```  a template *with* substitutions, where the
                                interpolations are preserved verbatim so a
                                path normaliser can turn them into parameters

    Anything else -- a bare identifier, a concatenation, a function call --
    returns None, because its value is not knowable without executing code.
    """
    if node.type in {"string", "string_fragment"}:
        return _unquote(node_text(source, node))

    if node.type == "template_string":
        return _template_text(source, node)

    return None


def _unquote(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'", "`"}:
        return text[1:-1]
    return text


def _template_text(source: SourceFile, node: Node) -> str:
    """Render a template literal, keeping ``${...}`` markers intact.

    The substitution text is retained rather than dropped so that
    ``/api/user/${id}`` can be normalised to ``/api/user/{param}`` and compared
    against a backend route, instead of collapsing to ``/api/user/``.
    """
    parts: list[str] = []
    for child in node.children:
        if child.type in {"`", "template_chars"}:
            if child.type == "template_chars":
                parts.append(node_text(source, child))
        elif (
            child.type == "string_fragment"
            or child.type == "template_substitution"
            or child.type == "escape_sequence"
        ):
            parts.append(node_text(source, child))
    return "".join(parts)
