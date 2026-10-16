"""SQL front-end, built on sqlglot.

Two jobs:

1. **DDL** -- read ``CREATE TABLE`` / ``ALTER TABLE`` / ``CREATE INDEX`` from
   migration files into table and column facts.
2. **Queries** -- read the column and table references out of a ``SELECT`` or
   ``UPDATE``, so a query against a column that does not exist can be caught.

**Line numbers.** sqlglot's expression tree carries no source positions, but
its *tokenizer* does. Columns are therefore located by walking the token
stream and recording the line of each column name at the top level of a
``CREATE TABLE`` body, which is deterministic rather than a text search. Where
a name cannot be located the statement's own first line is used, so a fact
always has a usable range.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError
from sqlglot.tokens import Token, TokenType

from app.core.logging import get_logger
from app.services.parsers.base import SourceFile, SourceLocation

__all__ = [
    "SQL_SUFFIXES",
    "ParsedStatement",
    "parse_sql_file",
    "parse_sql_text",
    "query_column_references",
]

log = get_logger("app.parsers.sql")

SQL_SUFFIXES: Final[frozenset[str]] = frozenset({".sql"})

# Migrations are overwhelmingly PostgreSQL in this product's target stack, and
# the Postgres dialect is also the most permissive about types we care about
# (SERIAL, TIMESTAMPTZ, JSONB). Parsing falls back to the generic dialect.
_PRIMARY_DIALECT: Final[str] = "postgres"


@dataclass(frozen=True, slots=True)
class ParsedStatement:
    """One SQL statement, with where it starts and its name-to-line index."""

    expression: exp.Expression
    location: SourceLocation
    # Lower-cased identifier -> 1-based line, for names declared in this
    # statement (column definitions, index targets).
    name_lines: dict[str, int] = field(default_factory=dict)

    def line_of(self, name: str) -> int:
        """The line a declared name appears on, else the statement's start."""
        return self.name_lines.get(name.lower(), self.location.line_start)


def parse_sql_file(source: SourceFile) -> list[ParsedStatement]:
    """Parse every statement in a ``.sql`` file."""
    if source.suffix not in SQL_SUFFIXES:
        return []
    return parse_sql_text(source, source.text)


def parse_sql_text(source: SourceFile, sql: str, *, line_offset: int = 0) -> list[ParsedStatement]:
    """Parse ``sql`` and attribute each statement to a line in ``source``.

    Args:
        source: The file the SQL came from, used to build locations.
        sql: The SQL text. May contain several statements.
        line_offset: Added to every line number. Non-zero when the SQL was
            embedded in another language, so positions stay relative to the
            host file rather than to the extracted string.
    """
    tokens = _tokenize(sql)
    if tokens is None:
        return []

    statements: list[ParsedStatement] = []
    for token_group in _split_statements(tokens):
        if not token_group:
            continue
        expression = _parse_tokens(token_group, sql)
        if expression is None:
            continue

        start_line = token_group[0].line + line_offset
        end_line = token_group[-1].line + line_offset
        statements.append(
            ParsedStatement(
                expression=expression,
                location=source.location(start_line, end_line),
                name_lines=_column_name_lines(token_group, line_offset),
            )
        )
    return statements


def _tokenize(sql: str) -> list[Token] | None:
    try:
        return sqlglot.tokenize(sql, dialect=_PRIMARY_DIALECT)
    except (TokenError, ParseError) as exc:
        log.debug("sql_tokenize_failed", error=str(exc)[:200])
        return None


def _split_statements(tokens: list[Token]) -> list[list[Token]]:
    """Split a token stream on top-level semicolons."""
    groups: list[list[Token]] = []
    current: list[Token] = []
    for token in tokens:
        if token.token_type is TokenType.SEMICOLON:
            if current:
                groups.append(current)
                current = []
            continue
        current.append(token)
    if current:
        groups.append(current)
    return groups


def _parse_tokens(tokens: list[Token], sql: str) -> exp.Expression | None:
    """Parse one statement's tokens, tolerating unsupported syntax."""
    for dialect in (_PRIMARY_DIALECT, None):
        try:
            parsed = sqlglot.parse(_token_span(tokens, sql), dialect=dialect)
        except (ParseError, TokenError, RecursionError):
            continue
        for expression in parsed:
            if expression is not None:
                return expression
    log.debug("sql_statement_unparseable", preview=_token_span(tokens, sql)[:120])
    return None


def _token_span(tokens: list[Token], sql: str) -> str:
    """The original text covered by a token group."""
    return sql[tokens[0].start : tokens[-1].end + 1]


def _column_name_lines(tokens: list[Token], line_offset: int) -> dict[str, int]:
    """Map each declared column name to its line.

    Walks the token stream tracking parenthesis depth. Inside the single
    top-level ``(...)`` of a ``CREATE TABLE``, the first identifier after
    ``(`` or ``,`` is a column name. Constraint clauses (``PRIMARY KEY (a, b)``,
    ``FOREIGN KEY ...``) are skipped, since they name existing columns rather
    than declaring new ones.
    """
    lines: dict[str, int] = {}
    depth = 0
    expecting_name = False

    for token in tokens:
        if token.token_type is TokenType.L_PAREN:
            depth += 1
            # Entering the column list of a CREATE TABLE.
            expecting_name = depth == 1
            continue
        if token.token_type is TokenType.R_PAREN:
            depth -= 1
            expecting_name = False
            continue
        if token.token_type is TokenType.COMMA:
            expecting_name = depth == 1
            continue

        if not expecting_name or depth != 1:
            continue

        # A table-level constraint, not a column definition.
        if token.token_type in _CONSTRAINT_STARTERS:
            expecting_name = False
            continue

        name = token.text.strip('"`[]').lower()
        # A quoted identifier is accepted as written -- `"my col"` is a legal
        # column name and its shape tells us nothing. sqlglot strips the quote
        # characters but records the token as IDENTIFIER, which is the only
        # reliable signal that quoting was used. An unquoted token must look
        # like an identifier, which is what filters out type keywords and
        # punctuation.
        was_quoted = token.token_type is TokenType.IDENTIFIER
        if name and name not in _CONSTRAINT_WORDS and (was_quoted or _IDENTIFIER_RE.match(name)):
            lines.setdefault(name, token.line + line_offset)
        expecting_name = False

    return lines


# Tokens that can begin a table-level constraint rather than a column.
# Note: sqlglot has no CHECK token type -- `CHECK` arrives as a plain
# identifier -- so it is filtered by text in _CONSTRAINT_WORDS instead.
_CONSTRAINT_STARTERS: Final[frozenset[TokenType]] = frozenset(
    {
        TokenType.PRIMARY_KEY,
        TokenType.FOREIGN_KEY,
        TokenType.KEY,
        TokenType.UNIQUE,
        TokenType.CONSTRAINT,
    }
)

# Words that start a table-level constraint but tokenize as identifiers.
_CONSTRAINT_WORDS: Final[frozenset[str]] = frozenset({"check", "exclude", "like", "inherits"})

# A column name is recognised by shape, not by token type. sqlglot assigns a
# dedicated token type to every word that is a keyword in some dialect, so
# `name` is NAME, `key` is KEY, `order` is ORDER -- and all of them are common
# column names. Enumerating the accepted token types means silently losing
# whichever one was forgotten, so anything identifier-shaped is accepted and
# only constraint keywords are excluded.
_IDENTIFIER_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z_][a-z0-9_$]*$")


def query_column_references(expression: exp.Expression) -> dict[str | None, set[str]]:
    """Columns referenced by a query, grouped by the table they belong to.

    The key is the table or alias a column was qualified with, or None when
    the reference is unqualified (``SELECT name FROM products``). Resolving an
    unqualified name to a table is the rule engine's job, since it needs the
    schema to do it.

    ``SELECT *`` contributes nothing: a star reference cannot name a missing
    column.
    """
    references: dict[str | None, set[str]] = {}
    for column in expression.find_all(exp.Column):
        name = column.name
        if not name or name == "*":
            continue
        qualifier = column.table or None
        references.setdefault(qualifier, set()).add(name)
    return references


def query_table_names(expression: exp.Expression) -> set[str]:
    """Tables a query reads from or writes to, by name."""
    return {table.name for table in expression.find_all(exp.Table) if table.name}
