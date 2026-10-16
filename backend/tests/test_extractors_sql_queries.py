"""Embedded SQL extraction.

The false-positive tests carry the weight here. A string that merely mentions
"select" is not a query, and reporting one would send the schema rules looking
for columns that were never referenced.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.extractors.sql_queries import extract_sql_queries, looks_like_sql


def write(root: Path, files: dict[str, str]) -> Path:
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


class TestLooksLikeSql:
    @pytest.mark.parametrize(
        "value",
        [
            "SELECT 1",
            "select id from t",
            "  SELECT id FROM t",
            "INSERT INTO t VALUES (1)",
            "UPDATE t SET a = 1",
            "DELETE FROM t",
            "WITH cte AS (SELECT 1) SELECT * FROM cte",
            "CREATE TABLE t (id INT)",
            "ALTER TABLE t ADD COLUMN x INT",
            "-- a comment\nSELECT 1",
        ],
    )
    def test_accepts_sql(self, value: str) -> None:
        assert looks_like_sql(value)

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "hello world",
            "please select an option",
            "/api/users",
            "The user will select a plan",
            "selected",
            "deleted",
            "updates available",
        ],
    )
    def test_rejects_prose_and_paths(self, value: str) -> None:
        """Anchoring at the start is what keeps prose out."""
        assert not looks_like_sql(value)


class TestPythonExtraction:
    def test_extracts_a_query_from_text(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "queries.py": (
                    "from sqlalchemy import text\n"
                    "def run(session):\n"
                    '    return session.execute(text("SELECT id FROM products"))\n'
                )
            },
        )

        query = extract_sql_queries(tmp_path)[0]

        assert query.statement_kind == "select"
        assert query.tables == ("products",)
        assert query.columns == ("id",)
        assert query.location.line_start == 3

    def test_merges_an_implicitly_concatenated_statement(self, tmp_path: Path) -> None:
        """Multi-line SQL arrives as one literal spanning its lines."""
        write(
            tmp_path,
            {
                "queries.py": (
                    "def run(session):\n"
                    "    return session.execute(\n"
                    '        "SELECT id, last_counted_at "\n'
                    '        "FROM products "\n'
                    '        "ORDER BY last_counted_at DESC"\n'
                    "    )\n"
                )
            },
        )

        query = extract_sql_queries(tmp_path)[0]

        assert "last_counted_at" in query.columns
        assert query.tables == ("products",)
        assert query.location.line_start == 3
        assert query.location.line_end == 5

    def test_neutralises_bind_parameters(self, tmp_path: Path) -> None:
        """A placeholder is not valid SQL and would fail to parse."""
        write(
            tmp_path,
            {
                "queries.py": (
                    "def run(session):\n"
                    '    session.execute("SELECT id FROM t WHERE id = :user_id")\n'
                )
            },
        )

        query = extract_sql_queries(tmp_path)[0]

        assert query.is_parseable
        assert query.tables == ("t",)

    @pytest.mark.parametrize("placeholder", [":name", "%s", "%(name)s", "?", "$1"])
    def test_handles_every_placeholder_style(self, tmp_path: Path, placeholder: str) -> None:
        write(
            tmp_path,
            {
                "queries.py": (
                    "def run(session):\n"
                    # Builds SQL *text* containing a placeholder; nothing runs it.
                    f'    session.execute("SELECT id FROM t WHERE a = {placeholder}")\n'  # noqa: S608
                )
            },
        )

        assert extract_sql_queries(tmp_path)[0].is_parseable

    def test_records_the_executor_for_confidence(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "a.py": 'session.execute("SELECT 1 FROM t")\n',
                "b.py": 'QUERY = "SELECT 1 FROM t"\n',
            },
        )

        queries = {query.location.file_path: query for query in extract_sql_queries(tmp_path)}

        assert queries["a.py"].callee == "execute"
        assert queries["a.py"].confidence == 1.0
        # A query assigned to a constant is still a query, with less certainty.
        assert queries["b.py"].confidence < 1.0

    def test_finds_columns_in_clauses(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {"q.py": ('session.execute("SELECT a FROM t WHERE b = 1 ORDER BY c LIMIT 2")\n')},
        )

        assert set(extract_sql_queries(tmp_path)[0].columns) == {"a", "b", "c"}

    def test_a_star_select_reports_no_columns(self, tmp_path: Path) -> None:
        write(tmp_path, {"q.py": 'session.execute("SELECT * FROM t")\n'})

        query = extract_sql_queries(tmp_path)[0]

        assert query.columns == ()
        assert query.tables == ("t",)

    def test_an_unparseable_query_is_still_recorded(self, tmp_path: Path) -> None:
        write(tmp_path, {"q.py": 'session.execute("SELECT FROM WHERE GROUP")\n'})

        queries = extract_sql_queries(tmp_path)

        assert len(queries) == 1
        assert queries[0].columns == () or not queries[0].is_parseable


class TestNotSql:
    def test_an_orm_query_is_not_extracted(self, tmp_path: Path) -> None:
        """`session.query(Product)` contains no SQL string."""
        write(
            tmp_path,
            {
                "q.py": (
                    "def run(session):\n"
                    "    return session.query(Product).filter(Product.id == 1).all()\n"
                )
            },
        )

        assert extract_sql_queries(tmp_path) == []

    def test_a_url_is_not_extracted(self, tmp_path: Path) -> None:
        write(tmp_path, {"api.ts": 'fetch("/api/users");\n'})

        assert extract_sql_queries(tmp_path) == []

    def test_prose_mentioning_select_is_not_extracted(self, tmp_path: Path) -> None:
        write(tmp_path, {"q.py": 'MESSAGE = "Please select a product to delete from the list"\n'})

        assert extract_sql_queries(tmp_path) == []

    def test_a_docstring_is_not_extracted(self, tmp_path: Path) -> None:
        write(tmp_path, {"q.py": 'def run():\n    """Fetch the products."""\n    pass\n'})

        assert extract_sql_queries(tmp_path) == []


class TestJavaScriptExtraction:
    def test_extracts_from_a_template_literal(self, tmp_path: Path) -> None:
        write(tmp_path, {"db.ts": "await db.query(`SELECT id FROM products`);\n"})

        query = extract_sql_queries(tmp_path)[0]

        assert query.tables == ("products",)
        assert query.callee == "query"

    def test_extracts_from_a_plain_string(self, tmp_path: Path) -> None:
        write(tmp_path, {"db.js": 'db.query("SELECT id FROM products");\n'})

        assert extract_sql_queries(tmp_path)[0].tables == ("products",)

    def test_handles_an_interpolated_value(self, tmp_path: Path) -> None:
        write(tmp_path, {"db.ts": "db.query(`SELECT id FROM t WHERE id = ${id}`);\n"})

        query = extract_sql_queries(tmp_path)[0]

        assert query.is_parseable
        assert query.tables == ("t",)


class TestLocationsAndOrdering:
    def test_column_locations_are_within_the_statement(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {"q.py": ("x = 1\n" "y = 2\n" 'session.execute("SELECT sku FROM products")\n')},
        )

        query = extract_sql_queries(tmp_path)[0]
        location = query.column_locations["sku"]

        assert location.line_start == 3
        assert location.file_path == "q.py"

    def test_results_are_sorted(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "b.py": 'session.execute("SELECT 1 FROM t")\n',
                "a.py": (
                    'session.execute("SELECT 1 FROM t")\n' 'session.execute("SELECT 2 FROM u")\n'
                ),
            },
        )

        found = extract_sql_queries(tmp_path)

        assert [(q.location.file_path, q.location.line_start) for q in found] == [
            ("a.py", 1),
            ("a.py", 2),
            ("b.py", 1),
        ]

    def test_paths_are_relative_to_the_repository_root(self, tmp_path: Path) -> None:
        write(tmp_path, {"backend/q.py": 'session.execute("SELECT 1 FROM t")\n'})

        found = extract_sql_queries(tmp_path, subdirectories=("backend",))

        assert found[0].location.file_path == "backend/q.py"

    def test_an_empty_tree_yields_nothing(self, tmp_path: Path) -> None:
        assert extract_sql_queries(tmp_path) == []
