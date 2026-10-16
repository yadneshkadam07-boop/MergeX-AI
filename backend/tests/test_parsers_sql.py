"""SQL parsing: statement splitting, column-to-line mapping, references."""

from __future__ import annotations

import pytest
from sqlglot import exp

from app.services.parsers.base import SourceFile
from app.services.parsers.sql_parser import (
    parse_sql_file,
    parse_sql_text,
    query_column_references,
    query_table_names,
)


def make_file(text: str, path: str = "migrations/0001_init.sql") -> SourceFile:
    return SourceFile(relative_path=path, text=text, lines=tuple(text.splitlines()))


class TestStatementSplitting:
    def test_splits_on_semicolons(self) -> None:
        source = make_file("CREATE TABLE a (id INT);\nCREATE TABLE b (id INT);\nDROP TABLE a;\n")

        statements = parse_sql_file(source)

        assert len(statements) == 3

    def test_ignores_a_trailing_semicolon(self) -> None:
        statements = parse_sql_file(make_file("CREATE TABLE a (id INT);\n"))

        assert len(statements) == 1

    def test_handles_a_statement_with_no_semicolon(self) -> None:
        statements = parse_sql_file(make_file("CREATE TABLE a (id INT)\n"))

        assert len(statements) == 1

    def test_returns_nothing_for_a_non_sql_file(self) -> None:
        assert parse_sql_file(make_file("SELECT 1", "app.py")) == []

    def test_comments_do_not_become_statements(self) -> None:
        source = make_file("-- a comment\nCREATE TABLE a (id INT);\n")

        assert len(parse_sql_file(source)) == 1

    def test_unparseable_sql_is_skipped_not_raised(self) -> None:
        source = make_file("CREATE TABLE a (id INT);\n??? not sql at all ???;\n")

        statements = parse_sql_file(source)

        assert len(statements) >= 1


class TestStatementLocations:
    def test_a_statement_spans_its_lines(self) -> None:
        source = make_file("-- header\nCREATE TABLE a (\n  id INT\n);\n")

        statement = parse_sql_file(source)[0]

        assert statement.location.line_start == 2
        assert statement.location.line_end == 4

    def test_the_second_statement_starts_after_the_first(self) -> None:
        source = make_file("CREATE TABLE a (id INT);\n\nCREATE TABLE b (id INT);\n")

        statements = parse_sql_file(source)

        assert statements[1].location.line_start == 3

    def test_line_offset_shifts_positions(self) -> None:
        """Used when SQL was embedded in another language.

        The host file must be the one passed in, since locations are clamped
        to it -- that clamp is what stops an off-by-one in a parser from
        producing a line number the file does not have.
        """
        host = make_file("\n".join(f"line {n}" for n in range(1, 21)), "app/db.py")

        statement = parse_sql_text(host, "CREATE TABLE a (id INT)", line_offset=10)[0]

        assert statement.location.line_start == 11

    def test_locations_are_clamped_to_the_host_file(self) -> None:
        """A bad offset must not yield a line the file does not contain."""
        host = make_file("one\ntwo\n", "app/db.py")

        statement = parse_sql_text(host, "CREATE TABLE a (id INT)", line_offset=500)[0]

        assert statement.location.line_start <= 2


class TestColumnLineMapping:
    """Every column needs its own line so evidence points at the right row."""

    def test_maps_each_column_to_its_line(self) -> None:
        source = make_file(
            "CREATE TABLE products (\n"
            "  id SERIAL PRIMARY KEY,\n"
            "  sku VARCHAR(64),\n"
            "  price NUMERIC(10,2)\n"
            ");\n"
        )

        statement = parse_sql_file(source)[0]

        assert statement.line_of("id") == 2
        assert statement.line_of("sku") == 3
        assert statement.line_of("price") == 4

    @pytest.mark.parametrize("name", ["name", "key", "order", "type", "value", "start", "end"])
    def test_maps_columns_whose_names_are_sql_keywords(self, name: str) -> None:
        """sqlglot gives these dedicated token types, not VAR.

        Enumerating accepted token types silently loses whichever was
        forgotten, and `name` is one of the most common column names there is.
        """
        source = make_file(f"CREATE TABLE t (\n  id INT,\n  {name} VARCHAR(10)\n);\n")

        statement = parse_sql_file(source)[0]

        assert statement.line_of(name) == 3

    def test_quoted_identifiers_are_mapped(self) -> None:
        source = make_file('CREATE TABLE t (\n  id INT,\n  "my col" VARCHAR(10)\n);\n')

        assert parse_sql_file(source)[0].line_of("my col") == 3

    def test_table_constraints_are_not_mistaken_for_columns(self) -> None:
        source = make_file(
            "CREATE TABLE t (\n"
            "  id INT,\n"
            "  other INT,\n"
            "  PRIMARY KEY (id),\n"
            "  FOREIGN KEY (other) REFERENCES o(id)\n"
            ");\n"
        )

        statement = parse_sql_file(source)[0]

        assert statement.line_of("id") == 2
        assert "primary" not in statement.name_lines
        assert "foreign" not in statement.name_lines

    def test_check_constraints_are_not_mistaken_for_columns(self) -> None:
        source = make_file("CREATE TABLE t (\n  id INT,\n  CHECK (id > 0)\n);\n")

        assert "check" not in parse_sql_file(source)[0].name_lines

    def test_unknown_name_falls_back_to_the_statement_start(self) -> None:
        source = make_file("CREATE TABLE t (\n  id INT\n);\n")

        assert parse_sql_file(source)[0].line_of("nope") == 1

    def test_a_single_line_table_maps_every_column_to_that_line(self) -> None:
        source = make_file("CREATE TABLE t (id INT, sku TEXT);\n")

        statement = parse_sql_file(source)[0]

        assert statement.line_of("id") == 1
        assert statement.line_of("sku") == 1


class TestQueryReferences:
    def test_groups_columns_by_qualifier(self) -> None:
        statement = parse_sql_text(
            make_file("x"), "SELECT p.sku, s.name FROM products p JOIN suppliers s ON 1=1"
        )[0]

        references = query_column_references(statement.expression)

        assert references["p"] == {"sku"}
        assert references["s"] == {"name"}

    def test_unqualified_columns_group_under_none(self) -> None:
        statement = parse_sql_text(make_file("x"), "SELECT sku, name FROM products")[0]

        references = query_column_references(statement.expression)

        assert references[None] == {"sku", "name"}

    def test_a_star_contributes_nothing(self) -> None:
        """`SELECT *` cannot name a missing column."""
        statement = parse_sql_text(make_file("x"), "SELECT * FROM products")[0]

        assert query_column_references(statement.expression) == {}

    def test_finds_columns_in_a_where_clause(self) -> None:
        statement = parse_sql_text(
            make_file("x"), "SELECT id FROM products WHERE last_counted_at > now()"
        )[0]

        assert "last_counted_at" in query_column_references(statement.expression)[None]

    def test_finds_columns_in_an_order_by(self) -> None:
        statement = parse_sql_text(
            make_file("x"), "SELECT id FROM products ORDER BY last_counted_at DESC"
        )[0]

        assert "last_counted_at" in query_column_references(statement.expression)[None]

    def test_reports_table_names(self) -> None:
        statement = parse_sql_text(make_file("x"), "SELECT 1 FROM products JOIN suppliers ON 1=1")[
            0
        ]

        assert query_table_names(statement.expression) == {"products", "suppliers"}


class TestDdlShapes:
    def test_reads_an_alter_table_add_column(self) -> None:
        statement = parse_sql_text(
            make_file("x"), "ALTER TABLE products ADD COLUMN warehouse_code VARCHAR(16)"
        )[0]

        assert isinstance(statement.expression, exp.Alter)

    def test_reads_a_create_index(self) -> None:
        statement = parse_sql_text(
            make_file("x"), "CREATE INDEX idx_products_sku ON products (sku)"
        )[0]

        assert isinstance(statement.expression, exp.Create)

    def test_reads_postgres_specific_types(self) -> None:
        source = make_file(
            "CREATE TABLE t (\n"
            "  id UUID,\n"
            "  payload JSONB,\n"
            "  created_at TIMESTAMPTZ\n"
            ");\n"
        )

        statement = parse_sql_file(source)[0]
        kinds = {
            column.name: column.args["kind"].sql(dialect="postgres")
            for column in statement.expression.find_all(exp.ColumnDef)
        }

        assert kinds == {"id": "UUID", "payload": "JSONB", "created_at": "TIMESTAMPTZ"}
