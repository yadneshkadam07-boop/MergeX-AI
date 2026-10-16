"""Backend ↔ database schema rules (``MX-DB-001`` … ``MX-DB-005``).

Compares what the application believes (ORM models, raw SQL) against what the
migrations actually built.

**The silence conditions matter more than the detections.** A project whose
migrations this scan never found looks identical to a project whose every
column is missing, and reporting the second when it is the first would flood a
working application with critical findings. So:

* Nothing is reported if no migrations were found at all.
* Nothing is reported for a table the migrations never create -- that is one
  missing table, not twelve missing columns, and more often means the schema
  lives somewhere this scan cannot see (a managed service, a separate repo).
* An unparseable migration file disables the absence checks for its tables.
* Unqualified columns in a multi-table query are ambiguous, so they are
  skipped rather than resolved by guesswork.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.analysis.findings import Finding, make_finding
from app.core.logging import get_logger
from app.services.extractors.db_schema import DbSchema, DbTable, is_known_family
from app.services.extractors.orm_models import OrmExtraction, OrmField, OrmModel
from app.services.extractors.sql_queries import SqlQuery

__all__ = ["SchemaInput", "run_schema_rules"]

log = get_logger("app.analysis.schema")

# Columns an ORM or framework adds without declaring, which therefore appear
# in queries without existing in a model.
_IMPLICIT_COLUMNS = frozenset({"rowid", "oid", "ctid", "xmin", "tableoid"})


@dataclass(frozen=True, slots=True)
class SchemaInput:
    """Everything the schema rules compare."""

    schema: DbSchema
    orm: OrmExtraction
    queries: list[SqlQuery]


def run_schema_rules(data: SchemaInput) -> list[Finding]:
    """Run every schema rule."""
    if data.schema.is_empty:
        # No migrations were found. Every model field would look missing.
        log.info("schema_rules_skipped", reason="no_migrations_found")
        return []

    findings: list[Finding] = []
    tables_by_name = data.orm.by_table()

    for table_name, model in sorted(tables_by_name.items()):
        table = data.schema.table(table_name)
        if table is None:
            # The migrations do not create this table at all. See module note.
            log.debug("schema_table_absent", table=table_name, model=model.class_name)
            continue
        findings.extend(_compare_model_to_table(model, table))

    findings.extend(_check_queries(data))
    return findings


# ---------------------------------------------------------------------------
# Model vs table
# ---------------------------------------------------------------------------


def _compare_model_to_table(model: OrmModel, table: DbTable) -> list[Finding]:
    findings: list[Finding] = []

    for orm_field in model.fields.values():
        column = table.column(orm_field.column_name)

        if column is None:
            findings.append(_missing_column(model, orm_field, table))
            continue

        type_finding = _type_mismatch(model, orm_field, table, column.type_family)
        if type_finding is not None:
            findings.append(type_finding)

        if orm_field.foreign_key:
            findings.extend(_foreign_key_findings(model, orm_field, table))

    return findings


def _missing_column(model: OrmModel, orm_field: OrmField, table: DbTable) -> Finding:
    """MX-DB-001: the model maps a column the migrations never created."""
    return make_finding(
        "MX-DB-001",
        identity=(table.name, orm_field.column_name),
        locations=[orm_field.location, table.location],
        description=(
            f"{model.class_name}.{orm_field.name} maps column "
            f"{table.name}.{orm_field.column_name}, which no migration creates. "
            f"Every query against {table.name} names this column in its SELECT list, "
            f"so reads fail too, not only writes."
        ),
        expected=(
            f"{table.name}.{orm_field.column_name} "
            f"({orm_field.type_name or orm_field.type_family}) in the migrations"
        ),
        actual=f"{table.name} has: {', '.join(sorted(table.columns))}",
        metadata={
            "table": table.name,
            "column": orm_field.column_name,
            "model": model.class_name,
            "field": orm_field.name,
            "expected_type": orm_field.type_name,
            "existing_columns": sorted(table.columns),
        },
    )


def _type_mismatch(
    model: OrmModel, orm_field: OrmField, table: DbTable, db_family: str
) -> Finding | None:
    """MX-DB-002: the two sides disagree about a column's type."""
    model_family = orm_field.type_family

    if model_family == db_family:
        return None
    if not (is_known_family(model_family) and is_known_family(db_family)):
        # At least one side fell back to its own type name rather than a
        # recognised family -- a vendor or custom type. `MY_CUSTOM_TYPE` and
        # `SomeVendorType` are the same column spelled two ways, so comparing
        # the strings would report a mismatch on correct code.
        return None
    if _is_benign_difference(model_family, db_family):
        return None

    column = table.column(orm_field.column_name)
    locations = [orm_field.location]
    if column is not None:
        locations.append(column.location)

    return make_finding(
        "MX-DB-002",
        identity=(table.name, orm_field.column_name, model_family, db_family),
        locations=locations,
        description=(
            f"{model.class_name}.{orm_field.name} is declared as {model_family} "
            f"({orm_field.type_name}) but {table.name}.{orm_field.column_name} is "
            f"{db_family} ({column.sql_type if column else '?'}). "
            + _mismatch_consequence(model_family, db_family)
        ),
        expected=f"{db_family} to match the database, or a migration to change the column",
        actual=f"model {model_family} vs database {db_family}",
        metadata={
            "table": table.name,
            "column": orm_field.column_name,
            "model": model.class_name,
            "field": orm_field.name,
            "model_type": orm_field.type_name,
            "model_family": model_family,
            "database_type": column.sql_type if column else None,
            "database_family": db_family,
        },
    )


# Pairs that are not worth reporting: the ORM and the database routinely
# disagree in these ways without any behavioural consequence.
_BENIGN_PAIRS = frozenset(
    {
        frozenset({"datetime", "date"}),
        frozenset({"string", "enum"}),
        frozenset({"string", "uuid"}),
        frozenset({"json", "string"}),
        frozenset({"array", "json"}),
    }
)


def _is_benign_difference(left: str, right: str) -> bool:
    return frozenset({left, right}) in _BENIGN_PAIRS


def _mismatch_consequence(model_family: str, db_family: str) -> str:
    """The reason a particular mismatch matters, where there is a sharp one."""
    pair = (model_family, db_family)
    if pair == ("decimal", "integer"):
        return (
            "Values are truncated rather than rejected, so money loses its "
            "fractional part silently — no error is raised."
        )
    if pair == ("integer", "decimal"):
        return "Reads return a Decimal where the code expects an int."
    if "string" in pair and "integer" in pair:
        return "Comparisons and ordering behave differently on each side."
    return "The ORM and the database will coerce differently."


def _foreign_key_findings(model: OrmModel, orm_field: OrmField, table: DbTable) -> list[Finding]:
    """MX-DB-004 and MX-DB-005, for a field the model declares as a key."""
    findings: list[Finding] = []
    declared_in_db = any(
        orm_field.column_name.lower() in {column.lower() for column in foreign_key.columns}
        for foreign_key in table.foreign_keys
    )

    if not declared_in_db:
        findings.append(
            make_finding(
                "MX-DB-004",
                identity=(table.name, orm_field.column_name),
                locations=[orm_field.location, table.location],
                description=(
                    f"{model.class_name}.{orm_field.name} declares "
                    f"ForeignKey({orm_field.foreign_key!r}), but "
                    f"{table.name}.{orm_field.column_name} has no REFERENCES clause in "
                    f"the migrations. The database cannot enforce the reference, so "
                    f"orphaned rows are possible and ON DELETE behaviour does nothing."
                ),
                expected=(
                    f"{orm_field.column_name} ... REFERENCES "
                    f"{orm_field.foreign_key.split('.')[0] if orm_field.foreign_key else '?'}"
                ),
                actual=f"{orm_field.column_name} with no foreign key constraint",
                metadata={
                    "table": table.name,
                    "column": orm_field.column_name,
                    "model": model.class_name,
                    "references": orm_field.foreign_key,
                },
            )
        )

    if orm_field.column_name.lower() not in table.indexed_columns():
        findings.append(
            make_finding(
                "MX-DB-005",
                identity=(table.name, orm_field.column_name),
                locations=[orm_field.location, table.location],
                description=(
                    f"{table.name}.{orm_field.column_name} is used as a foreign key but "
                    f"has no index. Every join through it is a sequential scan, which "
                    f"degrades as the table grows."
                ),
                expected=f"An index on {table.name}.{orm_field.column_name}",
                actual=(
                    f"Indexed columns on {table.name}: "
                    f"{', '.join(sorted(table.indexed_columns())) or 'none'}"
                ),
                metadata={
                    "table": table.name,
                    "column": orm_field.column_name,
                    "indexed_columns": sorted(table.indexed_columns()),
                },
            )
        )

    return findings


# ---------------------------------------------------------------------------
# Raw SQL vs schema
# ---------------------------------------------------------------------------


def _check_queries(data: SchemaInput) -> list[Finding]:
    """MX-DB-003: a query naming a column that exists nowhere."""
    findings: list[Finding] = []
    model_columns = _all_model_columns(data.orm)

    for query in data.queries:
        if not query.is_parseable or not query.tables:
            continue

        known_tables = [
            table
            for table in (data.schema.table(name) for name in query.tables)
            if table is not None
        ]
        if len(known_tables) != len(query.tables):
            # The query touches a table this scan did not build, so a column
            # it names could legitimately live there.
            continue

        for qualifier, column_name in query.column_references:
            if column_name.lower() in _IMPLICIT_COLUMNS:
                continue

            target = _resolve_target_table(qualifier, known_tables)
            if target is None:
                # Ambiguous: an unresolvable alias, or an unqualified name in a
                # multi-table query. Guessing would invent findings.
                continue
            if target.column(column_name) is not None:
                continue
            if column_name.lower() in model_columns.get(target.name.lower(), set()):
                # The column exists in the model but not the database, which is
                # MX-DB-001 against the model -- reporting it here as well
                # would be the same root cause twice.
                continue

            findings.append(_unknown_column(query, target, column_name))

    return findings


def _resolve_target_table(qualifier: str | None, tables: list[DbTable]) -> DbTable | None:
    """Which table a column reference belongs to, or None if unknowable."""
    if qualifier is None:
        # Unqualified: only unambiguous when the query touches one table.
        return tables[0] if len(tables) == 1 else None
    for table in tables:
        if table.name.lower() == qualifier.lower():
            return table
    # A table alias (`FROM products p`). Resolving it needs alias tracking the
    # extractor does not do, so the reference is skipped.
    return None


def _all_model_columns(orm: OrmExtraction) -> dict[str, set[str]]:
    """Table name -> column names the ORM models declare."""
    return {
        table_name.lower(): {orm_field.column_name.lower() for orm_field in model.fields.values()}
        for table_name, model in orm.by_table().items()
    }


def _unknown_column(query: SqlQuery, table: DbTable, column_name: str) -> Finding:
    location = query.column_locations.get(column_name.lower(), query.location)
    return make_finding(
        "MX-DB-003",
        identity=(table.name, column_name, "query"),
        locations=[location, table.location],
        description=(
            f"This query reads {table.name}.{column_name}, which exists in neither "
            f"the migrations nor any ORM model. Raw SQL bypasses the checks the ORM "
            f"would have made, so this fails only when the query runs."
        ),
        expected=f"{table.name}.{column_name} to exist",
        actual=f"{table.name} has: {', '.join(sorted(table.columns))}",
        metadata={
            "table": table.name,
            "column": column_name,
            "statement_kind": query.statement_kind,
            "existing_columns": sorted(table.columns),
            "sql": query.sql[:500],
        },
    )
