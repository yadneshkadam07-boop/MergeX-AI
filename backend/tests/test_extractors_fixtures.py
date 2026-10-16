"""The extractor contract, asserted against all three seeded fixtures.

This is the test that makes Phase 3 possible. It checks three things that the
rule engine will depend on absolutely:

1. **Every seeded defect is extracted, at the right file and line.** The
   ``/api/user/{}`` typo must be found at ``users.ts:7`` -- not "somewhere in
   that file", because an issue's evidence snippet is built from the line
   range and a wrong range renders the finding useless.
2. **No false positives.** Each fixture contains correct code deliberately
   placed next to the broken code (``listUsers`` beside the typo'd
   ``getUser``, ``Supplier`` beside the drifted ``Product``). The
   ``must_not_report`` block names them, and they must come out clean.
3. **Every extracted item carries a usable location.** Enforced as an
   invariant over every item from every extractor, not spot-checked.

Expectations live in each fixture's ``expected_findings.json`` so the fixture
and its contract cannot drift apart.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.services.extractors.backend_routes import BackendRoute, extract_backend_routes
from app.services.extractors.db_schema import DbSchema, extract_db_schema
from app.services.extractors.frontend_api_calls import (
    FrontendApiCall,
    extract_frontend_api_calls,
)
from app.services.extractors.orm_models import OrmExtraction, extract_orm_models
from app.services.extractors.sql_queries import extract_sql_queries
from app.services.parsers.base import SourceLocation

FIXTURES = [
    "react_fastapi_mismatch",
    "react_fastapi_schema_drift",
    "react_fastapi_insecure",
]

ManifestLoader = Callable[[str], dict[str, Any]]
RepoResolver = Callable[[str], Path]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_all(root: Path) -> dict[str, Any]:
    """Run every extractor over a fixture, as the pipeline will."""
    return {
        "frontend_api_calls": extract_frontend_api_calls(root, subdirectories=("frontend",)),
        "backend_routes": extract_backend_routes(root, subdirectories=("backend",)),
        "db_schema": extract_db_schema(root, subdirectories=("backend",)),
        "orm_models": extract_orm_models(root, subdirectories=("backend",)),
        "sql_queries": extract_sql_queries(root, subdirectories=("backend",)),
    }


def _assert_location_usable(location: SourceLocation, label: str, root: Path) -> None:
    """A location must point at a real place in a real file."""
    assert location.file_path, f"{label}: empty file_path"
    assert not location.file_path.startswith("/"), f"{label}: path should be repo-relative"
    assert "\\" not in location.file_path, f"{label}: path should use forward slashes"

    target = root / location.file_path
    assert target.is_file(), f"{label}: {location.file_path} does not exist in the fixture"

    total_lines = len(target.read_text(encoding="utf-8").splitlines())
    assert 1 <= location.line_start <= total_lines, (
        f"{label}: line_start {location.line_start} outside {location.file_path} "
        f"({total_lines} lines)"
    )
    assert (
        location.line_start <= location.line_end <= total_lines
    ), f"{label}: line_end {location.line_end} invalid for {location.file_path}"


def _find_call(calls: list[FrontendApiCall], file_path: str, line: int) -> FrontendApiCall:
    for call in calls:
        if call.location.file_path == file_path and call.location.line_start == line:
            return call
    rendered = "\n  ".join(f"{c.location} {c.method} {c.path}" for c in calls)
    raise AssertionError(f"No frontend call at {file_path}:{line}. Found:\n  {rendered}")


def _find_route(routes: list[BackendRoute], file_path: str, line: int) -> BackendRoute:
    for route in routes:
        if route.location.file_path == file_path and route.location.line_start == line:
            return route
    rendered = "\n  ".join(f"{r.location} {r.method} {r.path}" for r in routes)
    raise AssertionError(f"No backend route at {file_path}:{line}. Found:\n  {rendered}")


# ---------------------------------------------------------------------------
# Requirement 3: every extracted item carries file_path and a line range
# ---------------------------------------------------------------------------


class TestLocationInvariant:
    """Phase 3 builds evidence snippets from these, so none may be missing."""

    @pytest.mark.parametrize("name", FIXTURES)
    def test_every_extracted_item_has_a_usable_location(
        self, name: str, fixture_repo: RepoResolver
    ) -> None:
        root = fixture_repo(name)
        results = _extract_all(root)
        checked = 0

        for call in results["frontend_api_calls"]:
            _assert_location_usable(call.location, f"frontend call {call.path}", root)
            checked += 1

        for route in results["backend_routes"].routes:
            _assert_location_usable(route.location, f"route {route.path}", root)
            checked += 1

        schema: DbSchema = results["db_schema"]
        for table in schema.tables.values():
            _assert_location_usable(table.location, f"table {table.name}", root)
            checked += 1
            for column in table.columns.values():
                _assert_location_usable(column.location, f"column {table.name}.{column.name}", root)
                checked += 1
            for foreign_key in table.foreign_keys:
                _assert_location_usable(foreign_key.location, f"fk on {table.name}", root)
                checked += 1
            for index in table.indexes:
                _assert_location_usable(index.location, f"index on {table.name}", root)
                checked += 1

        orm: OrmExtraction = results["orm_models"]
        for model in orm.models:
            _assert_location_usable(model.location, f"model {model.class_name}", root)
            checked += 1
            for orm_field in model.fields.values():
                _assert_location_usable(
                    orm_field.location, f"field {model.class_name}.{orm_field.name}", root
                )
                checked += 1
            for relationship in model.relationships:
                _assert_location_usable(
                    relationship.location,
                    f"relationship {model.class_name}.{relationship.name}",
                    root,
                )
                checked += 1

        for query in results["sql_queries"]:
            _assert_location_usable(query.location, f"query {query.statement_kind}", root)
            checked += 1

        assert checked > 0, f"{name}: nothing was extracted, so nothing was verified"

    @pytest.mark.parametrize("name", FIXTURES)
    def test_every_item_carries_an_evidence_snippet(
        self, name: str, fixture_repo: RepoResolver
    ) -> None:
        """The snippet is captured now because the sandbox is deleted later."""
        root = fixture_repo(name)
        results = _extract_all(root)

        for call in results["frontend_api_calls"]:
            assert call.location.snippet.strip(), f"no snippet for {call}"
        for route in results["backend_routes"].routes:
            assert route.location.snippet.strip(), f"no snippet for {route}"
        for model in results["orm_models"].models:
            for orm_field in model.fields.values():
                assert orm_field.location.snippet.strip(), f"no snippet for {orm_field.name}"
        for table in results["db_schema"].tables.values():
            for column in table.columns.values():
                assert column.location.snippet.strip(), f"no snippet for {column.name}"

    @pytest.mark.parametrize("name", FIXTURES)
    def test_snippets_quote_the_real_source(self, name: str, fixture_repo: RepoResolver) -> None:
        """A snippet must be the actual text at that line, not a paraphrase."""
        root = fixture_repo(name)
        for call in _extract_all(root)["frontend_api_calls"]:
            lines = (root / call.location.file_path).read_text(encoding="utf-8").splitlines()
            actual = lines[call.location.line_start - 1].strip()
            first_snippet_line = call.location.snippet.splitlines()[0].strip()
            assert (
                first_snippet_line == actual
            ), f"{call.location}: snippet {first_snippet_line!r} != source {actual!r}"


# ---------------------------------------------------------------------------
# Requirement 1: the manifest's expected extractions are produced exactly
# ---------------------------------------------------------------------------


class TestManifestFrontendCalls:
    @pytest.mark.parametrize("name", FIXTURES)
    def test_expected_calls_are_extracted(
        self, name: str, fixture_repo: RepoResolver, fixture_manifest: ManifestLoader
    ) -> None:
        root = fixture_repo(name)
        expected = fixture_manifest(name)["extraction"]["frontend_api_calls"]
        calls = extract_frontend_api_calls(root, subdirectories=("frontend",))

        for entry in expected:
            call = _find_call(calls, entry["file_path"], entry["line_start"])
            assert call.method == entry["method"], f"{entry['file_path']}:{entry['line_start']}"
            assert call.path == entry["path"]
            if "function" in entry:
                assert call.enclosing_function == entry["function"]
            if "has_auth_header" in entry:
                assert call.has_auth_header is entry["has_auth_header"]
            if "request_fields" in entry:
                assert list(call.request_fields) == entry["request_fields"]
            if "base_url" in entry:
                assert call.normalized.base_url == entry["base_url"]
            if "line_end" in entry:
                assert call.location.line_end == entry["line_end"]

    @pytest.mark.parametrize("name", FIXTURES)
    def test_no_unexpected_calls_are_extracted(
        self, name: str, fixture_repo: RepoResolver, fixture_manifest: ManifestLoader
    ) -> None:
        """Extra calls would be noise the rule engine has to filter."""
        root = fixture_repo(name)
        expected = {
            (entry["file_path"], entry["line_start"])
            for entry in fixture_manifest(name)["extraction"]["frontend_api_calls"]
        }
        found = {
            (call.location.file_path, call.location.line_start)
            for call in extract_frontend_api_calls(root, subdirectories=("frontend",))
        }

        assert found == expected, f"unexpected: {found - expected}, missing: {expected - found}"


class TestManifestBackendRoutes:
    @pytest.mark.parametrize("name", FIXTURES)
    def test_expected_routes_are_extracted(
        self, name: str, fixture_repo: RepoResolver, fixture_manifest: ManifestLoader
    ) -> None:
        root = fixture_repo(name)
        expected = fixture_manifest(name)["extraction"]["backend_routes"]
        routes = extract_backend_routes(root, subdirectories=("backend",)).routes

        for entry in expected:
            route = _find_route(routes, entry["file_path"], entry["line_start"])
            assert route.method == entry["method"]
            assert (
                route.path == entry["path"]
            ), f"{entry['file_path']}:{entry['line_start']} -- prefix resolution failed"
            if "handler" in entry:
                assert route.handler_name == entry["handler"]
            if "mount_prefix" in entry:
                assert route.mount_prefix == entry["mount_prefix"]
            if "dependencies" in entry:
                assert list(route.all_dependencies) == entry["dependencies"]
            if "is_authenticated" in entry:
                assert route.is_authenticated is entry["is_authenticated"]
            if "request_model" in entry:
                assert route.request_model == entry["request_model"]

    @pytest.mark.parametrize("name", FIXTURES)
    def test_no_unexpected_routes_are_extracted(
        self, name: str, fixture_repo: RepoResolver, fixture_manifest: ManifestLoader
    ) -> None:
        root = fixture_repo(name)
        expected = {
            (entry["file_path"], entry["line_start"])
            for entry in fixture_manifest(name)["extraction"]["backend_routes"]
        }
        found = {
            (route.location.file_path, route.location.line_start)
            for route in extract_backend_routes(root, subdirectories=("backend",)).routes
        }

        assert found == expected, f"unexpected: {found - expected}, missing: {expected - found}"

    @pytest.mark.parametrize("name", FIXTURES)
    def test_every_route_prefix_resolved_completely(
        self, name: str, fixture_repo: RepoResolver
    ) -> None:
        """An unresolved mount would silently corrupt every path under it."""
        extraction = extract_backend_routes(fixture_repo(name), subdirectories=("backend",))

        assert extraction.unresolved_mounts == []
        assert [r for r in extraction.routes if "mount_prefix_incomplete" in r.notes] == []

    @pytest.mark.parametrize("name", FIXTURES)
    def test_no_backend_file_failed_to_parse(self, name: str, fixture_repo: RepoResolver) -> None:
        extraction = extract_backend_routes(fixture_repo(name), subdirectories=("backend",))

        assert extraction.unparseable_files == []


class TestManifestDbSchema:
    @pytest.mark.parametrize("name", FIXTURES)
    def test_expected_tables_and_columns_are_extracted(
        self, name: str, fixture_repo: RepoResolver, fixture_manifest: ManifestLoader
    ) -> None:
        root = fixture_repo(name)
        expected = fixture_manifest(name)["extraction"]["db_schema"]
        schema = extract_db_schema(root, subdirectories=("backend",))

        if "migration_files" in expected:
            assert schema.migration_files == expected["migration_files"]

        for table_entry in expected["tables"]:
            table = schema.table(table_entry["name"])
            assert table is not None, f"table {table_entry['name']} not extracted"
            assert table.location.file_path == table_entry["file_path"]

            for column_entry in table_entry["columns"]:
                column = table.column(column_entry["name"])
                assert (
                    column is not None
                ), f"{table_entry['name']}.{column_entry['name']} not extracted"
                assert column.location.line_start == column_entry["line"], (
                    f"{table.name}.{column.name} reported at line "
                    f"{column.location.line_start}, expected {column_entry['line']}"
                )
                assert column.type_family == column_entry["type_family"]
                if "nullable" in column_entry:
                    assert column.nullable is column_entry["nullable"]
                if "is_primary_key" in column_entry:
                    assert column.is_primary_key is column_entry["is_primary_key"]
                if "is_unique" in column_entry:
                    assert column.is_unique is column_entry["is_unique"]

            for absent in table_entry.get("absent_columns", []):
                assert (
                    table.column(absent) is None
                ), f"{table.name}.{absent} must NOT exist -- the migration never creates it"

            for index_entry in table_entry.get("indexes", []):
                matching = [
                    index
                    for index in table.indexes
                    if list(index.columns) == index_entry["columns"]
                ]
                assert matching, f"index on {index_entry['columns']} not extracted"
                if index_entry.get("name"):
                    assert any(index.name == index_entry["name"] for index in matching)

            if "foreign_keys" in table_entry:
                assert len(table.foreign_keys) == len(table_entry["foreign_keys"])

    @pytest.mark.parametrize("name", FIXTURES)
    def test_no_unexpected_tables(
        self, name: str, fixture_repo: RepoResolver, fixture_manifest: ManifestLoader
    ) -> None:
        expected = {
            entry["name"].lower()
            for entry in fixture_manifest(name)["extraction"]["db_schema"]["tables"]
        }
        schema = extract_db_schema(fixture_repo(name), subdirectories=("backend",))

        assert set(schema.tables) == expected

    @pytest.mark.parametrize("name", FIXTURES)
    def test_no_sql_statement_was_skipped(self, name: str, fixture_repo: RepoResolver) -> None:
        """A skipped statement means the schema is incomplete."""
        schema = extract_db_schema(fixture_repo(name), subdirectories=("backend",))

        assert schema.statements_skipped == 0


class TestManifestOrmModels:
    @pytest.mark.parametrize("name", FIXTURES)
    def test_expected_models_and_fields_are_extracted(
        self, name: str, fixture_repo: RepoResolver, fixture_manifest: ManifestLoader
    ) -> None:
        root = fixture_repo(name)
        expected = fixture_manifest(name)["extraction"]["orm_models"]
        models = {
            m.class_name: m for m in extract_orm_models(root, subdirectories=("backend",)).models
        }

        for entry in expected:
            model = models.get(entry["class_name"])
            assert model is not None, f"model {entry['class_name']} not extracted"
            assert model.table_name == entry["table_name"]
            assert model.location.file_path == entry["file_path"]
            assert model.location.line_start == entry["line_start"]

            for field_entry in entry["fields"]:
                orm_field = model.fields.get(field_entry["name"])
                assert (
                    orm_field is not None
                ), f"{entry['class_name']}.{field_entry['name']} not extracted"
                assert orm_field.location.line_start == field_entry["line"], (
                    f"{model.class_name}.{orm_field.name} reported at line "
                    f"{orm_field.location.line_start}, expected {field_entry['line']}"
                )
                assert orm_field.type_family == field_entry["type_family"]
                if "nullable" in field_entry:
                    assert orm_field.nullable is field_entry["nullable"]
                if "is_primary_key" in field_entry:
                    assert orm_field.is_primary_key is field_entry["is_primary_key"]
                if "is_unique" in field_entry:
                    assert orm_field.is_unique is field_entry["is_unique"]
                if "foreign_key" in field_entry:
                    assert orm_field.foreign_key == field_entry["foreign_key"]

            for relationship_entry in entry.get("relationships", []):
                matching = [
                    relationship
                    for relationship in model.relationships
                    if relationship.name == relationship_entry["name"]
                ]
                assert matching, f"relationship {relationship_entry['name']} not extracted"
                assert matching[0].location.line_start == relationship_entry["line"]
                assert matching[0].target_model == relationship_entry["target_model"]

    @pytest.mark.parametrize("name", FIXTURES)
    def test_no_unexpected_models(
        self, name: str, fixture_repo: RepoResolver, fixture_manifest: ManifestLoader
    ) -> None:
        expected = {
            entry["class_name"] for entry in fixture_manifest(name)["extraction"]["orm_models"]
        }
        found = {
            model.class_name
            for model in extract_orm_models(fixture_repo(name), subdirectories=("backend",)).models
        }

        assert found == expected


class TestManifestSqlQueries:
    @pytest.mark.parametrize("name", FIXTURES)
    def test_expected_queries_are_extracted(
        self, name: str, fixture_repo: RepoResolver, fixture_manifest: ManifestLoader
    ) -> None:
        root = fixture_repo(name)
        expected = fixture_manifest(name)["extraction"]["sql_queries"]
        queries = extract_sql_queries(root, subdirectories=("backend",))

        for entry in expected:
            matching = [
                query
                for query in queries
                if query.location.file_path == entry["file_path"]
                and query.location.line_start == entry["line_start"]
            ]
            assert matching, (
                f"no SQL query at {entry['file_path']}:{entry['line_start']}; "
                f"found {[str(q.location) for q in queries]}"
            )
            query = matching[0]
            assert query.statement_kind == entry["kind"]
            assert list(query.tables) == entry["tables"]
            assert list(query.columns) == entry["columns"]
            if "line_end" in entry:
                assert query.location.line_end == entry["line_end"]

    @pytest.mark.parametrize("name", FIXTURES)
    def test_no_unexpected_queries(
        self, name: str, fixture_repo: RepoResolver, fixture_manifest: ManifestLoader
    ) -> None:
        """ORM calls must not be mistaken for raw SQL."""
        expected = {
            (entry["file_path"], entry["line_start"])
            for entry in fixture_manifest(name)["extraction"]["sql_queries"]
        }
        found = {
            (query.location.file_path, query.location.line_start)
            for query in extract_sql_queries(fixture_repo(name), subdirectories=("backend",))
        }

        assert found == expected


# ---------------------------------------------------------------------------
# Requirement 2: the must_not_report cases stay clean
# ---------------------------------------------------------------------------


class TestNoFalsePositives:
    """The correct code in each fixture must be extracted *correctly*.

    A false positive in Phase 3 will almost always originate here: a call
    whose path was mangled, a route whose prefix was lost, a field whose type
    was misread. These assert the inputs are right, so a later mismatch is a
    real finding rather than an extraction bug.
    """

    def test_correct_calls_match_their_routes_exactly(self, fixture_repo: RepoResolver) -> None:
        """``listUsers``/``listTasks``/``createTask`` are correct on both sides."""
        root = fixture_repo("react_fastapi_mismatch")
        calls = extract_frontend_api_calls(root, subdirectories=("frontend",))
        routes = extract_backend_routes(root, subdirectories=("backend",)).routes
        route_keys = {(route.method, route.path) for route in routes}

        for function in ("listUsers", "listTasks", "createTask"):
            call = next(c for c in calls if c.enclosing_function == function)
            assert (call.method, call.path) in route_keys, (
                f"{function} calls {call.method} {call.path}, which matches no route. "
                f"This is correct code: a mismatch here is an extraction bug. "
                f"Routes: {sorted(route_keys)}"
            )

    def test_request_fields_of_correct_call_match_the_backend_model(
        self, fixture_repo: RepoResolver
    ) -> None:
        """``createTask`` sends ``owner_id``, which is what TaskCreate declares."""
        root = fixture_repo("react_fastapi_mismatch")
        calls = extract_frontend_api_calls(root, subdirectories=("frontend",))
        create_task = next(c for c in calls if c.enclosing_function == "createTask")

        assert set(create_task.request_fields) == {"title", "owner_id"}

    def test_protected_routes_are_not_reported_as_open(
        self, fixture_repo: RepoResolver, fixture_manifest: ManifestLoader
    ) -> None:
        """``list_payments`` and ``delete_payment`` declare require_user."""
        root = fixture_repo("react_fastapi_insecure")
        routes = {
            route.handler_name: route
            for route in extract_backend_routes(root, subdirectories=("backend",)).routes
        }
        manifest = fixture_manifest("react_fastapi_insecure")
        protected = [
            entry["symbols"]
            for entry in manifest["must_not_report"]
            if "symbols" in entry and "authentication" in entry["reason"]
        ]

        for handler in [symbol for group in protected for symbol in group]:
            assert routes[
                handler
            ].is_authenticated, f"{handler} declares an auth dependency but was read as unprotected"

    def test_matching_table_produces_no_drift(self, fixture_repo: RepoResolver) -> None:
        """``suppliers`` agrees with its migration field for field."""
        root = fixture_repo("react_fastapi_schema_drift")
        schema = extract_db_schema(root, subdirectories=("backend",))
        models = extract_orm_models(root, subdirectories=("backend",)).by_table()

        table = schema.table("suppliers")
        model = models["suppliers"]
        assert table is not None

        for orm_field in model.fields.values():
            column = table.column(orm_field.column_name)
            assert column is not None, f"suppliers.{orm_field.column_name} should exist"
            assert column.type_family == orm_field.type_family, (
                f"suppliers.{orm_field.column_name}: model {orm_field.type_family} "
                f"vs db {column.type_family} -- these agree in the fixture"
            )

    def test_agreeing_product_columns_produce_no_drift(self, fixture_repo: RepoResolver) -> None:
        """Only the seeded columns may disagree; the rest must match."""
        root = fixture_repo("react_fastapi_schema_drift")
        schema = extract_db_schema(root, subdirectories=("backend",))
        models = extract_orm_models(root, subdirectories=("backend",)).by_table()

        table = schema.table("products")
        model = models["products"]
        assert table is not None
        seeded = {"warehouse_code", "unit_price"}

        for orm_field in model.fields.values():
            if orm_field.column_name in seeded:
                continue
            column = table.column(orm_field.column_name)
            assert column is not None, f"products.{orm_field.column_name} should exist"
            assert column.type_family == orm_field.type_family, (
                f"products.{orm_field.column_name}: model {orm_field.type_family} "
                f"vs db {column.type_family} -- not a seeded defect"
            )

    def test_orm_queries_are_not_extracted_as_raw_sql(self, fixture_repo: RepoResolver) -> None:
        """``list_products`` and ``low_stock`` use the ORM, not SQL strings."""
        root = fixture_repo("react_fastapi_schema_drift")
        queries = extract_sql_queries(root, subdirectories=("backend",))
        lines = (root / "backend/app/queries.py").read_text(encoding="utf-8").splitlines()

        orm_function_lines = {
            index + 1
            for index, line in enumerate(lines)
            if line.startswith("def list_products") or line.startswith("def low_stock")
        }
        for query in queries:
            if query.location.file_path != "backend/app/queries.py":
                continue
            for start in orm_function_lines:
                assert not (
                    start <= query.location.line_start <= start + 8
                ), f"ORM code at line {start} was extracted as raw SQL: {query}"

    def test_a_correct_query_references_only_existing_columns(
        self, fixture_repo: RepoResolver
    ) -> None:
        """``product_totals`` touches supplier_id, which exists."""
        root = fixture_repo("react_fastapi_schema_drift")
        schema = extract_db_schema(root, subdirectories=("backend",))
        queries = extract_sql_queries(root, subdirectories=("backend",))
        table = schema.table("products")
        assert table is not None

        totals = next(q for q in queries if "supplier_id" in q.columns)
        for column in totals.columns:
            assert table.column(column) is not None, (
                f"{column} is referenced by a correct query but was not extracted "
                "from the schema"
            )

    def test_non_wildcard_cors_fixture_is_unaffected(self, fixture_repo: RepoResolver) -> None:
        """Fixture 1's CORS is restricted; extraction must not invent a route."""
        root = fixture_repo("react_fastapi_mismatch")
        routes = extract_backend_routes(root, subdirectories=("backend",)).routes

        assert not any("cors" in route.handler_name.lower() for route in routes)


# ---------------------------------------------------------------------------
# The headline seeded defects, asserted individually
# ---------------------------------------------------------------------------


class TestSeededDefectsAreVisible:
    """Each seeded bug must be reconstructible from the extracted facts alone.

    Phase 3 will implement these as rules; here we prove the inputs it needs
    are present and correct.
    """

    def test_path_typo_is_extracted_with_file_and_line(self, fixture_repo: RepoResolver) -> None:
        """MX-API-002: ``/api/user/{}`` at users.ts:7, one edit from a real route."""
        from app.services.extractors.paths import paths_differ_by_one_edit

        root = fixture_repo("react_fastapi_mismatch")
        calls = extract_frontend_api_calls(root, subdirectories=("frontend",))
        routes = extract_backend_routes(root, subdirectories=("backend",)).routes

        call = _find_call(calls, "frontend/src/api/users.ts", 7)
        assert call.method == "GET"
        assert call.path == "/api/user/{}"
        assert "api.get" in call.callee
        assert "/api/user/${id}" in call.location.snippet

        near_misses = [
            route
            for route in routes
            if route.method == "GET" and paths_differ_by_one_edit(call.path, route.path)
        ]
        assert [route.path for route in near_misses] == ["/api/users/{}"]
        assert near_misses[0].location.line_start == 18

    def test_missing_endpoint_has_no_matching_route(self, fixture_repo: RepoResolver) -> None:
        """MX-API-001: nothing serves ``/api/users/export``."""
        root = fixture_repo("react_fastapi_mismatch")
        call = _find_call(
            extract_frontend_api_calls(root, subdirectories=("frontend",)),
            "frontend/src/api/users.ts",
            33,
        )
        routes = extract_backend_routes(root, subdirectories=("backend",)).routes

        assert call.path == "/api/users/export"
        assert not any(route.path == call.path for route in routes)

    def test_method_mismatch_is_visible(self, fixture_repo: RepoResolver) -> None:
        """MX-API-003: POST on the frontend, DELETE on the backend."""
        root = fixture_repo("react_fastapi_mismatch")
        call = _find_call(
            extract_frontend_api_calls(root, subdirectories=("frontend",)),
            "frontend/src/api/users.ts",
            27,
        )
        routes = extract_backend_routes(root, subdirectories=("backend",)).routes
        same_path = [route for route in routes if route.path == call.path]

        assert call.method == "POST"
        assert [route.method for route in same_path] == ["DELETE"]

    def test_field_name_drift_is_visible(self, fixture_repo: RepoResolver) -> None:
        """MX-API-004: the frontend sends ``fullName``, the model wants ``full_name``."""
        root = fixture_repo("react_fastapi_mismatch")
        call = _find_call(
            extract_frontend_api_calls(root, subdirectories=("frontend",)),
            "frontend/src/api/users.ts",
            20,
        )
        route = _find_route(
            extract_backend_routes(root, subdirectories=("backend",)).routes,
            "backend/app/routers/users.py",
            26,
        )

        assert call.request_fields == ("email", "fullName")
        assert route.request_model == "UserCreate"

    def test_missing_auth_header_is_visible(self, fixture_repo: RepoResolver) -> None:
        """MX-API-005: the route requires a token, the call sends none."""
        root = fixture_repo("react_fastapi_mismatch")
        call = _find_call(
            extract_frontend_api_calls(root, subdirectories=("frontend",)),
            "frontend/src/api/tasks.ts",
            17,
        )
        route = _find_route(
            extract_backend_routes(root, subdirectories=("backend",)).routes,
            "backend/app/routers/tasks.py",
            31,
        )

        assert call.has_auth_header is False
        assert route.is_authenticated is True
        assert route.all_dependencies == ("require_admin",)

    def test_model_field_missing_from_database_is_visible(self, fixture_repo: RepoResolver) -> None:
        """MX-DB-001: ``warehouse_code`` is in the model at line 25, not in the DB."""
        root = fixture_repo("react_fastapi_schema_drift")
        schema = extract_db_schema(root, subdirectories=("backend",))
        model = extract_orm_models(root, subdirectories=("backend",)).by_table()["products"]

        orm_field = model.fields["warehouse_code"]
        assert orm_field.location.file_path == "backend/app/models.py"
        assert orm_field.location.line_start == 25
        assert "warehouse_code" in orm_field.location.snippet

        table = schema.table("products")
        assert table is not None
        assert table.column("warehouse_code") is None

    def test_type_mismatch_is_visible(self, fixture_repo: RepoResolver) -> None:
        """MX-DB-002: ``decimal`` in the model, ``integer`` in the database."""
        root = fixture_repo("react_fastapi_schema_drift")
        schema = extract_db_schema(root, subdirectories=("backend",))
        model = extract_orm_models(root, subdirectories=("backend",)).by_table()["products"]
        table = schema.table("products")
        assert table is not None

        orm_field = model.fields["unit_price"]
        column = table.column("unit_price")
        assert column is not None

        assert orm_field.type_family == "decimal"
        assert column.type_family == "integer"
        assert orm_field.location.line_start == 29
        assert column.location.line_start == 12

    def test_query_on_nonexistent_column_is_visible(self, fixture_repo: RepoResolver) -> None:
        """MX-DB-003: the SQL names ``last_counted_at``, which exists nowhere."""
        root = fixture_repo("react_fastapi_schema_drift")
        schema = extract_db_schema(root, subdirectories=("backend",))
        model = extract_orm_models(root, subdirectories=("backend",)).by_table()["products"]
        queries = extract_sql_queries(root, subdirectories=("backend",))

        query = next(q for q in queries if "last_counted_at" in q.columns)
        assert query.tables == ("products",)
        assert query.location.file_path == "backend/app/queries.py"
        assert "last_counted_at" in query.sql

        table = schema.table("products")
        assert table is not None
        assert table.column("last_counted_at") is None
        assert "last_counted_at" not in model.fields

    def test_missing_foreign_key_is_visible(self, fixture_repo: RepoResolver) -> None:
        """MX-DB-004/005: the model declares a FK, the migration does not."""
        root = fixture_repo("react_fastapi_schema_drift")
        schema = extract_db_schema(root, subdirectories=("backend",))
        model = extract_orm_models(root, subdirectories=("backend",)).by_table()["products"]
        table = schema.table("products")
        assert table is not None

        assert model.fields["supplier_id"].foreign_key == "suppliers.id"
        assert table.foreign_keys == []
        # MX-DB-005: and it is not indexed either.
        assert "supplier_id" not in table.indexed_columns()

    def test_unprotected_sibling_routes_are_visible(self, fixture_repo: RepoResolver) -> None:
        """MX-SEC-002: two routes on a router whose siblings are all protected."""
        root = fixture_repo("react_fastapi_insecure")
        routes = extract_backend_routes(root, subdirectories=("backend",)).routes

        open_routes = sorted(
            (route.handler_name, route.location.line_start)
            for route in routes
            if not route.is_authenticated
        )
        protected = sorted(route.handler_name for route in routes if route.is_authenticated)

        assert open_routes == [("export_customers", 22), ("refund_payment", 15)]
        assert protected == ["delete_payment", "list_payments"]
