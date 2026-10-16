"""Database schema extraction by replaying migrations.

The replay is the point: a column added in migration 5 and dropped in
migration 9 does not exist, and reading only ``CREATE TABLE`` would claim it
does.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.extractors.db_schema import (
    DbColumn,
    DbSchema,
    DbTable,
    canonical_type,
    extract_db_schema,
)


def write(root: Path, files: dict[str, str]) -> Path:
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def table_of(schema: DbSchema, name: str) -> DbTable:
    """Fetch a table, failing the test if it was not extracted.

    A narrowing helper: without it every assertion below has to re-prove that
    the table is not None, which buries what is actually being tested.
    """
    table = schema.table(name)
    assert table is not None, f"table {name!r} was not extracted"
    return table


def column_of(schema: DbSchema, table: str, column: str) -> DbColumn:
    """Fetch a column, failing the test if it was not extracted."""
    found = table_of(schema, table).column(column)
    assert found is not None, f"column {table}.{column} was not extracted"
    return found


class TestCanonicalType:
    @pytest.mark.parametrize(
        ("sql_type", "family"),
        [
            ("INTEGER", "integer"),
            ("INT", "integer"),
            ("BIGINT", "integer"),
            ("SERIAL", "integer"),
            ("SMALLSERIAL", "integer"),
            ("VARCHAR(64)", "string"),
            ("TEXT", "string"),
            ("CHAR(2)", "string"),
            ("NUMERIC(10,2)", "decimal"),
            ("DECIMAL", "decimal"),
            ("MONEY", "decimal"),
            ("REAL", "float"),
            ("DOUBLE PRECISION", "float"),
            ("BOOLEAN", "boolean"),
            ("BOOL", "boolean"),
            ("TIMESTAMPTZ", "datetime"),
            ("TIMESTAMP WITH TIME ZONE", "datetime"),
            ("DATE", "date"),
            ("JSONB", "json"),
            ("UUID", "uuid"),
            ("BYTEA", "binary"),
        ],
    )
    def test_reduces_to_a_family(self, sql_type: str, family: str) -> None:
        assert canonical_type(sql_type) == family

    def test_integer_and_decimal_are_different_families(self) -> None:
        """This distinction is the whole MX-DB-002 finding."""
        assert canonical_type("INTEGER") != canonical_type("NUMERIC(10,2)")

    def test_length_differences_do_not_change_the_family(self) -> None:
        """VARCHAR(64) vs VARCHAR(200) is a length issue, not a type mismatch."""
        assert canonical_type("VARCHAR(64)") == canonical_type("VARCHAR(200)")

    def test_an_unknown_type_falls_back_to_its_text(self) -> None:
        assert canonical_type("MY_CUSTOM_TYPE") == "my_custom_type"

    def test_none_is_unknown(self) -> None:
        assert canonical_type(None) == "unknown"


class TestCreateTable:
    def test_extracts_columns_with_their_lines(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "m/001.sql": (
                    "CREATE TABLE products (\n"
                    "  id SERIAL PRIMARY KEY,\n"
                    "  sku VARCHAR(64) NOT NULL UNIQUE,\n"
                    "  price NUMERIC(10,2) NOT NULL\n"
                    ");\n"
                )
            },
        )

        schema = extract_db_schema(tmp_path)
        table = table_of(schema, "products")

        assert sorted(table.columns) == ["id", "price", "sku"]
        assert column_of(schema, "products", "sku").location.line_start == 3
        assert column_of(schema, "products", "price").location.line_start == 4

    def test_reads_inline_constraints(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "m/001.sql": (
                    "CREATE TABLE t (\n"
                    "  id SERIAL PRIMARY KEY,\n"
                    "  sku VARCHAR(64) NOT NULL UNIQUE,\n"
                    "  note TEXT,\n"
                    "  created_at TIMESTAMPTZ DEFAULT now()\n"
                    ");\n"
                )
            },
        )

        schema = extract_db_schema(tmp_path)

        assert column_of(schema, "t", "id").is_primary_key
        assert column_of(schema, "t", "id").nullable is False
        assert column_of(schema, "t", "sku").is_unique
        assert column_of(schema, "t", "sku").nullable is False
        assert column_of(schema, "t", "note").nullable is True
        assert column_of(schema, "t", "created_at").has_default

    def test_an_explicit_null_is_nullable(self, tmp_path: Path) -> None:
        write(tmp_path, {"m/001.sql": "CREATE TABLE t (a INT NULL);\n"})

        assert column_of(extract_db_schema(tmp_path), "t", "a").nullable is True

    def test_reads_a_table_level_primary_key(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {"m/001.sql": ("CREATE TABLE t (\n  a INT,\n  b INT,\n  PRIMARY KEY (a, b)\n);\n")},
        )

        table = table_of(extract_db_schema(tmp_path), "t")

        assert sorted(table.primary_key_columns) == ["a", "b"]

    def test_reads_an_inline_foreign_key(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "m/001.sql": (
                    "CREATE TABLE suppliers (id SERIAL PRIMARY KEY);\n"
                    "CREATE TABLE products (\n"
                    "  id SERIAL PRIMARY KEY,\n"
                    "  supplier_id INTEGER REFERENCES suppliers(id)\n"
                    ");\n"
                )
            },
        )

        table = table_of(extract_db_schema(tmp_path), "products")

        assert len(table.foreign_keys) == 1
        foreign_key = table.foreign_keys[0]
        assert foreign_key.columns == ("supplier_id",)
        assert foreign_key.referenced_table == "suppliers"
        assert foreign_key.location.line_start == 4

    def test_reads_a_table_level_foreign_key(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "m/001.sql": (
                    "CREATE TABLE suppliers (id SERIAL PRIMARY KEY);\n"
                    "CREATE TABLE products (\n"
                    "  id SERIAL PRIMARY KEY,\n"
                    "  supplier_id INTEGER,\n"
                    "  FOREIGN KEY (supplier_id) REFERENCES suppliers(id)\n"
                    ");\n"
                )
            },
        )

        table = table_of(extract_db_schema(tmp_path), "products")

        assert table.foreign_keys[0].referenced_table == "suppliers"

    def test_a_column_without_references_has_no_foreign_key(self, tmp_path: Path) -> None:
        """The MX-DB-004 shape: a plain integer that merely looks like a key."""
        write(
            tmp_path,
            {"m/001.sql": "CREATE TABLE products (id SERIAL, supplier_id INTEGER);\n"},
        )

        assert table_of(extract_db_schema(tmp_path), "products").foreign_keys == []


class TestIndexes:
    def test_reads_a_create_index(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "m/001.sql": (
                    "CREATE TABLE t (id SERIAL, name TEXT);\n"
                    "CREATE INDEX idx_t_name ON t (name);\n"
                )
            },
        )

        table = table_of(extract_db_schema(tmp_path), "t")

        assert len(table.indexes) == 1
        assert table.indexes[0].name == "idx_t_name"
        assert table.indexes[0].columns == ("name",)
        assert table.indexes[0].is_unique is False

    def test_reads_a_unique_index(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "m/001.sql": (
                    "CREATE TABLE t (id SERIAL, email TEXT);\n"
                    "CREATE UNIQUE INDEX idx_t_email ON t (email);\n"
                )
            },
        )

        assert table_of(extract_db_schema(tmp_path), "t").indexes[0].is_unique is True

    def test_indexed_columns_includes_keys_and_uniques(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "m/001.sql": (
                    "CREATE TABLE t (\n"
                    "  id SERIAL PRIMARY KEY,\n"
                    "  sku TEXT UNIQUE,\n"
                    "  name TEXT,\n"
                    "  other TEXT\n"
                    ");\n"
                    "CREATE INDEX idx_t_name ON t (name);\n"
                )
            },
        )

        covered = table_of(extract_db_schema(tmp_path), "t").indexed_columns()

        assert {"id", "sku", "name"} <= covered
        assert "other" not in covered


class TestMigrationReplay:
    def test_applies_files_in_sorted_order(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "m/002_add.sql": "ALTER TABLE t ADD COLUMN added TEXT;\n",
                "m/001_create.sql": "CREATE TABLE t (id SERIAL);\n",
            },
        )

        schema = extract_db_schema(tmp_path)
        table = table_of(schema, "t")

        assert schema.migration_files == ["m/001_create.sql", "m/002_add.sql"]
        assert table.column("added") is not None

    def test_a_dropped_column_does_not_exist(self, tmp_path: Path) -> None:
        """Reading only CREATE TABLE would wrongly report this column."""
        write(
            tmp_path,
            {
                "m/001.sql": "CREATE TABLE t (id SERIAL, legacy TEXT);\n",
                "m/002.sql": "ALTER TABLE t DROP COLUMN legacy;\n",
            },
        )

        table = table_of(extract_db_schema(tmp_path), "t")

        assert table.column("legacy") is None
        assert table.column("id") is not None

    def test_an_altered_type_is_the_final_type(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "m/001.sql": "CREATE TABLE t (price INTEGER);\n",
                "m/002.sql": "ALTER TABLE t ALTER COLUMN price TYPE NUMERIC(10,2);\n",
            },
        )

        assert column_of(extract_db_schema(tmp_path), "t", "price").type_family == "decimal"

    def test_a_dropped_table_does_not_exist(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "m/001.sql": "CREATE TABLE t (id SERIAL);\nCREATE TABLE u (id SERIAL);\n",
                "m/002.sql": "DROP TABLE t;\n",
            },
        )

        schema = extract_db_schema(tmp_path)

        assert schema.table("t") is None
        assert schema.table("u") is not None

    def test_an_added_constraint_is_applied(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "m/001.sql": (
                    "CREATE TABLE suppliers (id SERIAL PRIMARY KEY);\n"
                    "CREATE TABLE products (id SERIAL, supplier_id INTEGER);\n"
                ),
                "m/002.sql": (
                    "ALTER TABLE products ADD CONSTRAINT fk_supplier\n"
                    "  FOREIGN KEY (supplier_id) REFERENCES suppliers(id);\n"
                ),
            },
        )

        table = table_of(extract_db_schema(tmp_path), "products")

        assert any(fk.referenced_table == "suppliers" for fk in table.foreign_keys)


class TestLookupAndRobustness:
    def test_lookups_are_case_insensitive(self, tmp_path: Path) -> None:
        """SQL resolves unquoted names case-insensitively."""
        write(tmp_path, {"m/001.sql": "CREATE TABLE Products (SKU TEXT);\n"})

        schema = extract_db_schema(tmp_path)

        assert schema.table("products") is not None
        assert table_of(schema, "PRODUCTS").column("sku") is not None

    def test_an_alter_on_an_unknown_table_is_skipped(self, tmp_path: Path) -> None:
        write(tmp_path, {"m/001.sql": "ALTER TABLE ghost ADD COLUMN x TEXT;\n"})

        schema = extract_db_schema(tmp_path)

        assert schema.is_empty
        assert schema.statements_skipped == 1

    def test_non_sql_files_are_ignored(self, tmp_path: Path) -> None:
        write(tmp_path, {"app.py": "CREATE TABLE t (id INT);\n"})

        assert extract_db_schema(tmp_path).is_empty

    def test_an_empty_tree_yields_an_empty_schema(self, tmp_path: Path) -> None:
        schema = extract_db_schema(tmp_path)

        assert schema.is_empty
        assert schema.migration_files == []

    def test_a_subdirectory_restriction_is_honoured(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "backend/m/001.sql": "CREATE TABLE a (id INT);\n",
                "other/m/001.sql": "CREATE TABLE b (id INT);\n",
            },
        )

        schema = extract_db_schema(tmp_path, subdirectories=("backend",))

        assert schema.table("a") is not None
        assert schema.table("b") is None

    def test_paths_are_relative_to_the_repository_root(self, tmp_path: Path) -> None:
        write(tmp_path, {"backend/m/001.sql": "CREATE TABLE a (id INT);\n"})

        schema = extract_db_schema(tmp_path, subdirectories=("backend",))

        assert schema.migration_files == ["backend/m/001.sql"]
        assert table_of(schema, "a").location.file_path == "backend/m/001.sql"
