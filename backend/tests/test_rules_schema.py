"""Schema drift rules.

The silence conditions carry the weight. A project whose migrations this scan
never found looks identical to one whose every column is missing, and
reporting the second when it is the first would bury a working application in
critical findings.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.analysis.findings import Finding
from app.analysis.rules.schema import SchemaInput, run_schema_rules
from app.services.extractors.db_schema import extract_db_schema
from app.services.extractors.orm_models import extract_orm_models
from app.services.extractors.sql_queries import extract_sql_queries


def write(root: Path, files: dict[str, str]) -> Path:
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def findings_of(root: Path) -> list[Finding]:
    return run_schema_rules(
        SchemaInput(
            schema=extract_db_schema(root),
            orm=extract_orm_models(root),
            queries=extract_sql_queries(root),
        )
    )


def analyse(root: Path) -> list[str]:
    return sorted(finding.rule_id for finding in findings_of(root))


def model(fields: str, *, table: str = "products", class_name: str = "Product") -> str:
    return (
        "from sqlalchemy import Column, ForeignKey, Integer, Numeric, String, Text\n"
        "from sqlalchemy.orm import relationship\n"
        f"class {class_name}(Base):\n"
        f'    __tablename__ = "{table}"\n'
        f"{fields}"
    )


class TestMissingColumn:
    def test_reports_a_field_with_no_column(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "migrations/001.sql": "CREATE TABLE products (id SERIAL PRIMARY KEY);\n",
                "models.py": model(
                    "    id = Column(Integer, primary_key=True)\n"
                    "    warehouse_code = Column(String(16))\n"
                ),
            },
        )

        assert analyse(tmp_path) == ["MX-DB-001"]

    def test_the_finding_points_at_the_model_line(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "migrations/001.sql": "CREATE TABLE products (id SERIAL PRIMARY KEY);\n",
                "models.py": model(
                    "    id = Column(Integer, primary_key=True)\n"
                    "    warehouse_code = Column(String(16))\n"
                ),
            },
        )

        finding = findings_of(tmp_path)[0]

        assert finding.primary_location.file_path == "models.py"
        assert "warehouse_code" in finding.primary_location.snippet
        assert finding.metadata["column"] == "warehouse_code"

    def test_a_matching_column_is_silent(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "migrations/001.sql": (
                    "CREATE TABLE products (id SERIAL PRIMARY KEY, sku VARCHAR(64));\n"
                ),
                "models.py": model(
                    "    id = Column(Integer, primary_key=True)\n" "    sku = Column(String(64))\n"
                ),
            },
        )

        assert analyse(tmp_path) == []

    def test_a_renamed_column_is_compared_by_its_database_name(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "migrations/001.sql": (
                    "CREATE TABLE products (id SERIAL, warehouse_code VARCHAR(16));\n"
                ),
                "models.py": model(
                    "    id = Column(Integer, primary_key=True)\n"
                    '    code = Column("warehouse_code", String(16))\n'
                ),
            },
        )

        assert analyse(tmp_path) == []


class TestSilenceConditions:
    def test_no_migrations_reports_nothing(self, tmp_path: Path) -> None:
        """Otherwise every field of every model looks missing."""
        write(
            tmp_path,
            {"models.py": model("    sku = Column(String(64))\n")},
        )

        assert analyse(tmp_path) == []

    def test_a_table_absent_from_the_migrations_is_skipped(self, tmp_path: Path) -> None:
        """One missing table, not twelve missing columns."""
        write(
            tmp_path,
            {
                "migrations/001.sql": "CREATE TABLE other (id SERIAL);\n",
                "models.py": model(
                    "    id = Column(Integer, primary_key=True)\n"
                    "    sku = Column(String(64))\n"
                    "    name = Column(String(200))\n"
                ),
            },
        )

        assert analyse(tmp_path) == []

    def test_no_models_reports_nothing(self, tmp_path: Path) -> None:
        write(tmp_path, {"migrations/001.sql": "CREATE TABLE products (id SERIAL);\n"})

        assert analyse(tmp_path) == []


class TestTypeMismatch:
    def test_reports_decimal_against_integer(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "migrations/001.sql": (
                    "CREATE TABLE products (id SERIAL, unit_price INTEGER NOT NULL);\n"
                ),
                "models.py": model(
                    "    id = Column(Integer, primary_key=True)\n"
                    "    unit_price = Column(Numeric(10, 2), nullable=False)\n"
                ),
            },
        )

        findings = findings_of(tmp_path)

        assert [finding.rule_id for finding in findings] == ["MX-DB-002"]
        assert findings[0].metadata["model_family"] == "decimal"
        assert findings[0].metadata["database_family"] == "integer"

    def test_the_description_explains_the_silent_truncation(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "migrations/001.sql": "CREATE TABLE products (unit_price INTEGER);\n",
                "models.py": model("    unit_price = Column(Numeric(10, 2))\n"),
            },
        )

        assert "truncated" in findings_of(tmp_path)[0].description

    def test_a_length_difference_is_not_a_mismatch(self, tmp_path: Path) -> None:
        """VARCHAR(64) against VARCHAR(200) is a different, weaker finding."""
        write(
            tmp_path,
            {
                "migrations/001.sql": "CREATE TABLE products (sku VARCHAR(64));\n",
                "models.py": model("    sku = Column(String(200))\n"),
            },
        )

        assert analyse(tmp_path) == []

    @pytest.mark.parametrize(
        ("sql_type", "model_type"),
        [
            ("TIMESTAMPTZ", "Date"),
            ("VARCHAR(10)", "Enum"),
            ("UUID", "String"),
            ("JSONB", "Text"),
        ],
    )
    def test_benign_differences_are_not_reported(
        self, tmp_path: Path, sql_type: str, model_type: str
    ) -> None:
        """The ORM and the database routinely disagree in these harmless ways."""
        write(
            tmp_path,
            {
                "migrations/001.sql": f"CREATE TABLE products (value {sql_type});\n",
                "models.py": model(f"    value = Column({model_type})\n"),
            },
        )

        assert analyse(tmp_path) == []

    def test_an_unclassifiable_type_is_not_reported(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "migrations/001.sql": "CREATE TABLE products (value MY_CUSTOM_TYPE);\n",
                "models.py": model("    value = Column(SomeVendorType)\n"),
            },
        )

        assert analyse(tmp_path) == []


class TestForeignKeys:
    def test_reports_a_model_key_missing_from_the_database(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "migrations/001.sql": (
                    "CREATE TABLE suppliers (id SERIAL PRIMARY KEY);\n"
                    "CREATE TABLE products (id SERIAL, supplier_id INTEGER);\n"
                ),
                "models.py": model(
                    "    id = Column(Integer, primary_key=True)\n"
                    '    supplier_id = Column(Integer, ForeignKey("suppliers.id"))\n'
                ),
            },
        )

        assert analyse(tmp_path) == ["MX-DB-004", "MX-DB-005"]

    def test_a_declared_foreign_key_is_silent(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "migrations/001.sql": (
                    "CREATE TABLE suppliers (id SERIAL PRIMARY KEY);\n"
                    "CREATE TABLE products (\n"
                    "  id SERIAL,\n"
                    "  supplier_id INTEGER REFERENCES suppliers(id)\n"
                    ");\n"
                    "CREATE INDEX idx_products_supplier ON products (supplier_id);\n"
                ),
                "models.py": model(
                    "    id = Column(Integer, primary_key=True)\n"
                    '    supplier_id = Column(Integer, ForeignKey("suppliers.id"))\n'
                ),
            },
        )

        assert analyse(tmp_path) == []

    def test_an_indexed_key_reports_only_the_missing_constraint(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "migrations/001.sql": (
                    "CREATE TABLE suppliers (id SERIAL PRIMARY KEY);\n"
                    "CREATE TABLE products (id SERIAL, supplier_id INTEGER);\n"
                    "CREATE INDEX idx_products_supplier ON products (supplier_id);\n"
                ),
                "models.py": model(
                    "    id = Column(Integer, primary_key=True)\n"
                    '    supplier_id = Column(Integer, ForeignKey("suppliers.id"))\n'
                ),
            },
        )

        assert analyse(tmp_path) == ["MX-DB-004"]

    def test_a_non_key_column_is_not_checked_for_an_index(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "migrations/001.sql": "CREATE TABLE products (id SERIAL, note TEXT);\n",
                "models.py": model(
                    "    id = Column(Integer, primary_key=True)\n" "    note = Column(Text)\n"
                ),
            },
        )

        assert analyse(tmp_path) == []


class TestQueryColumns:
    def test_reports_a_column_that_exists_nowhere(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "migrations/001.sql": "CREATE TABLE products (id SERIAL, sku VARCHAR(64));\n",
                "models.py": model(
                    "    id = Column(Integer, primary_key=True)\n" "    sku = Column(String(64))\n"
                ),
                "queries.py": ('session.execute("SELECT id, last_counted_at FROM products")\n'),
            },
        )

        findings = findings_of(tmp_path)

        assert [finding.rule_id for finding in findings] == ["MX-DB-003"]
        assert findings[0].metadata["column"] == "last_counted_at"

    def test_a_valid_query_is_silent(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "migrations/001.sql": "CREATE TABLE products (id SERIAL, sku VARCHAR(64));\n",
                "models.py": model(
                    "    id = Column(Integer, primary_key=True)\n" "    sku = Column(String(64))\n"
                ),
                "queries.py": 'session.execute("SELECT id, sku FROM products")\n',
            },
        )

        assert analyse(tmp_path) == []

    def test_a_column_in_the_model_but_not_the_database_is_not_double_reported(
        self, tmp_path: Path
    ) -> None:
        """That is MX-DB-001 against the model: one root cause, one finding."""
        write(
            tmp_path,
            {
                "migrations/001.sql": "CREATE TABLE products (id SERIAL);\n",
                "models.py": model(
                    "    id = Column(Integer, primary_key=True)\n"
                    "    warehouse_code = Column(String(16))\n"
                ),
                "queries.py": ('session.execute("SELECT id, warehouse_code FROM products")\n'),
            },
        )

        assert analyse(tmp_path) == ["MX-DB-001"]

    def test_an_unqualified_column_in_a_join_is_skipped(self, tmp_path: Path) -> None:
        """Ambiguous: guessing the table would invent findings."""
        write(
            tmp_path,
            {
                "migrations/001.sql": (
                    "CREATE TABLE products (id SERIAL);\n" "CREATE TABLE suppliers (id SERIAL);\n"
                ),
                "models.py": model("    id = Column(Integer, primary_key=True)\n"),
                "queries.py": (
                    'session.execute("SELECT mystery FROM products JOIN suppliers ON 1=1")\n'
                ),
            },
        )

        assert analyse(tmp_path) == []

    def test_an_aliased_qualifier_is_skipped(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "migrations/001.sql": "CREATE TABLE products (id SERIAL);\n",
                "models.py": model("    id = Column(Integer, primary_key=True)\n"),
                "queries.py": 'session.execute("SELECT p.mystery FROM products p")\n',
            },
        )

        assert analyse(tmp_path) == []

    def test_a_query_on_an_unknown_table_is_skipped(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "migrations/001.sql": "CREATE TABLE products (id SERIAL);\n",
                "models.py": model("    id = Column(Integer, primary_key=True)\n"),
                "queries.py": 'session.execute("SELECT anything FROM external_view")\n',
            },
        )

        assert analyse(tmp_path) == []


class TestFindingShape:
    def test_findings_carry_everything_the_issue_schema_needs(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "migrations/001.sql": "CREATE TABLE products (id SERIAL);\n",
                "models.py": model(
                    "    id = Column(Integer, primary_key=True)\n"
                    "    warehouse_code = Column(String(16))\n"
                ),
            },
        )

        finding = findings_of(tmp_path)[0]

        assert finding.primary_location.snippet.strip()
        assert finding.evidence.strip()
        assert finding.expected and finding.actual
        assert finding.occurrence_count >= 1
        assert 0.0 < finding.confidence <= 1.0

    @pytest.mark.parametrize(
        "rule_id", ["MX-DB-001", "MX-DB-002", "MX-DB-003", "MX-DB-004", "MX-DB-005"]
    )
    def test_every_rule_is_registered(self, rule_id: str) -> None:
        from app.analysis.taxonomy import REGISTRY

        assert rule_id in REGISTRY
