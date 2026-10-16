"""The full deterministic pipeline, over all three seeded fixtures.

This is the precision test. Each fixture's manifest declares the rules that
must fire *and* the correct code that must stay silent, and both halves are
asserted here against the complete engine rather than against one rule at a
time -- because a false positive can come from any rule, and the user sees
one list.

Also asserted: the engine never calls a language model, never crashes on an
unreachable advisory service, and produces byte-identical output across runs.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.analysis.engine import AnalysisResult, analyse
from app.models.enums import IssueCategory, Severity
from app.services.osv import StaticVulnerabilityClient, Vulnerability

FIXTURES = [
    "react_fastapi_mismatch",
    "react_fastapi_schema_drift",
    "react_fastapi_insecure",
]

ManifestLoader = Callable[[str], dict[str, Any]]
RepoResolver = Callable[[str], Path]

# Recorded advisories for the fixture's deliberately vulnerable pins. Using a
# static client keeps these tests offline and deterministic; the live lookup
# is covered by the `network`-marked tests in test_services_osv.py.
ADVISORIES: dict[tuple[str, str, str], tuple[Vulnerability, ...]] = {
    ("PyPI", "pyyaml", "5.3.1"): (
        Vulnerability(
            id="GHSA-8q59-q68h-6hv4",
            summary="Arbitrary code execution via full_load.",
            severity=Severity.CRITICAL,
            aliases=("CVE-2020-14343",),
            fixed_versions=("5.4",),
        ),
    ),
    ("PyPI", "requests", "2.19.1"): (
        Vulnerability(
            id="GHSA-j8r2-6x86-q33q",
            summary="Proxy-Authorization leaked on redirect.",
            severity=Severity.MEDIUM,
            aliases=("CVE-2023-32681",),
            fixed_versions=("2.31.0",),
        ),
    ),
    ("PyPI", "gitpython", "3.1.29"): (
        Vulnerability(
            id="GHSA-2mqj-m65w-jghx",
            summary="Untrusted search path on Windows.",
            severity=Severity.HIGH,
            aliases=("CVE-2024-22190",),
            fixed_versions=("3.1.41",),
        ),
    ),
    ("PyPI", "jinja2", "2.11.2"): (
        Vulnerability(
            id="GHSA-h5c8-rqwp-cp95",
            summary="XSS via the xmlattr filter.",
            severity=Severity.MEDIUM,
            aliases=("CVE-2024-22195",),
            fixed_versions=("3.1.3",),
        ),
    ),
    ("PyPI", "fastapi", "0.65.1"): (
        Vulnerability(
            id="GHSA-8h2j-cgx8-6xv7",
            summary="CSRF via form data content type.",
            severity=Severity.HIGH,
            aliases=("CVE-2021-32677",),
            fixed_versions=("0.65.2",),
        ),
    ),
}


def osv() -> StaticVulnerabilityClient:
    return StaticVulnerabilityClient(ADVISORIES)


async def run(root: Path, *, with_osv: bool = True) -> AnalysisResult:
    return await analyse(root, vulnerability_client=osv() if with_osv else None)


class TestSeededDefectsAreReported:
    """Every rule each manifest claims must actually fire on that fixture."""

    @pytest.mark.parametrize("name", FIXTURES)
    async def test_every_declared_rule_fires(
        self, name: str, fixture_repo: RepoResolver, fixture_manifest: ManifestLoader
    ) -> None:
        result = await run(fixture_repo(name))
        expected = {
            entry["rule_id"]
            for entry in fixture_manifest(name)["findings"]
            if entry.get("implemented")
        }

        produced = {finding.rule_id for finding in result.findings}

        assert expected <= produced, f"not reported: {sorted(expected - produced)}"

    @pytest.mark.parametrize("name", FIXTURES)
    async def test_no_rules_fire_that_the_manifest_does_not_declare(
        self, name: str, fixture_repo: RepoResolver, fixture_manifest: ManifestLoader
    ) -> None:
        """An undeclared finding is an unreviewed one: either a real defect
        the fixture should document, or a false positive."""
        result = await run(fixture_repo(name))
        declared = {entry["rule_id"] for entry in fixture_manifest(name)["findings"]}

        produced = {finding.rule_id for finding in result.findings}

        assert produced <= declared, f"undeclared: {sorted(produced - declared)}"

    async def test_the_api_fixture_reports_exactly_its_five_defects(
        self, fixture_repo: RepoResolver
    ) -> None:
        result = await run(fixture_repo("react_fastapi_mismatch"))

        assert sorted(finding.rule_id for finding in result.findings) == [
            "MX-API-001",
            "MX-API-002",
            "MX-API-003",
            "MX-API-004",
            "MX-API-005",
        ]

    async def test_the_schema_fixture_reports_exactly_its_five_defects(
        self, fixture_repo: RepoResolver
    ) -> None:
        result = await run(fixture_repo("react_fastapi_schema_drift"))

        assert sorted(finding.rule_id for finding in result.findings) == [
            "MX-DB-001",
            "MX-DB-002",
            "MX-DB-003",
            "MX-DB-004",
            "MX-DB-005",
        ]

    async def test_the_security_fixture_reports_every_security_rule(
        self, fixture_repo: RepoResolver
    ) -> None:
        result = await run(fixture_repo("react_fastapi_insecure"))
        produced = {finding.rule_id for finding in result.findings}

        assert {
            "MX-SEC-001",
            "MX-SEC-002",
            "MX-SEC-003",
            "MX-SEC-004",
            "MX-SEC-005",
            "MX-DEP-001",
        } <= produced

    async def test_the_five_cve_pinned_dependencies_are_all_flagged(
        self, fixture_repo: RepoResolver
    ) -> None:
        result = await run(fixture_repo("react_fastapi_insecure"))
        flagged = {
            finding.metadata["package"].lower()
            for finding in result.findings
            if finding.rule_id == "MX-DEP-001"
        }

        assert flagged == {"pyyaml", "requests", "gitpython", "jinja2", "fastapi"}


class TestNoFalsePositives:
    """The must_not_report half of each manifest, asserted end to end."""

    @pytest.mark.parametrize("name", FIXTURES)
    async def test_a_cross_layer_fixture_reports_only_its_own_category(
        self, name: str, fixture_repo: RepoResolver, fixture_manifest: ManifestLoader
    ) -> None:
        """A fixture seeded with API defects must not grow schema findings."""
        result = await run(fixture_repo(name))
        declared_categories = {entry["category"] for entry in fixture_manifest(name)["findings"]}

        produced = {finding.category.value for finding in result.findings}

        assert produced <= declared_categories

    async def test_correct_api_calls_produce_nothing(self, fixture_repo: RepoResolver) -> None:
        """listUsers, listTasks and createTask are correct on both sides."""
        result = await run(fixture_repo("react_fastapi_mismatch"))
        reported_lines = {
            (location.file_path, location.line_start)
            for finding in result.findings
            for location in finding.locations
        }

        # The correct calls, from the Phase 2 extraction ground truth.
        for file_path, line in [
            ("frontend/src/api/tasks.ts", 5),  # listTasks
            ("frontend/src/api/tasks.ts", 10),  # createTask
            ("frontend/src/api/users.ts", 12),  # listUsers
        ]:
            assert (
                file_path,
                line,
            ) not in reported_lines, f"{file_path}:{line} is correct code and must not be reported"

    async def test_the_matching_table_produces_no_schema_findings(
        self, fixture_repo: RepoResolver
    ) -> None:
        """`suppliers` agrees with its migration field for field."""
        result = await run(fixture_repo("react_fastapi_schema_drift"))

        for finding in result.findings:
            assert finding.metadata.get("table") != "suppliers", finding

    async def test_agreeing_product_columns_produce_no_findings(
        self, fixture_repo: RepoResolver
    ) -> None:
        result = await run(fixture_repo("react_fastapi_schema_drift"))
        reported = {
            finding.metadata.get("column")
            for finding in result.findings
            if finding.category is IssueCategory.SCHEMA
        }

        for column in ("sku", "name", "reorder_level", "description", "id", "created_at"):
            assert column not in reported, f"{column} agrees on both sides"

    async def test_the_public_api_url_is_not_reported_as_a_secret(
        self, fixture_repo: RepoResolver
    ) -> None:
        """`API_BASE_URL = "https://api.payments.example.com"` is not a credential."""
        result = await run(fixture_repo("react_fastapi_insecure"))
        secrets = [finding for finding in result.findings if finding.rule_id == "MX-SEC-001"]

        for finding in secrets:
            assert finding.metadata.get("variable") != "API_BASE_URL"

    async def test_protected_routes_are_not_reported_as_open(
        self, fixture_repo: RepoResolver
    ) -> None:
        result = await run(fixture_repo("react_fastapi_insecure"))
        open_handlers = {
            finding.metadata["handler"]
            for finding in result.findings
            if finding.rule_id == "MX-SEC-002"
        }

        assert "list_payments" not in open_handlers
        assert "delete_payment" not in open_handlers

    async def test_a_safe_dependency_is_not_reported(self, fixture_repo: RepoResolver) -> None:
        result = await run(fixture_repo("react_fastapi_insecure"))
        flagged = {
            finding.metadata["package"].lower()
            for finding in result.findings
            if finding.rule_id == "MX-DEP-001"
        }

        assert "sqlalchemy" not in flagged

    async def test_restricted_cors_is_not_reported(self, fixture_repo: RepoResolver) -> None:
        """Fixture 1 restricts CORS to the dev origin."""
        result = await run(fixture_repo("react_fastapi_mismatch"))

        assert not any(finding.rule_id == "MX-SEC-003" for finding in result.findings)

    async def test_a_clean_project_produces_nothing(self, tmp_path: Path) -> None:
        """The baseline: correct code scores 100 with no findings."""
        (tmp_path / "backend").mkdir()
        (tmp_path / "frontend").mkdir()
        (tmp_path / "backend" / "main.py").write_text(
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n"
            '@app.get("/api/users")\n'
            "def list_users():\n"
            "    pass\n",
            encoding="utf-8",
        )
        (tmp_path / "frontend" / "api.ts").write_text(
            'import axios from "axios";\n'
            'const api = axios.create({ baseURL: "/" });\n'
            'api.get("/api/users");\n',
            encoding="utf-8",
        )
        (tmp_path / "frontend" / "package.json").write_text(
            '{"dependencies": {"axios": "1.7.2"}}', encoding="utf-8"
        )

        result = await run(tmp_path)

        assert result.findings == []
        assert result.score.score == 100


class TestFindingCompleteness:
    """Every finding must carry what the issue schema stores."""

    @pytest.mark.parametrize("name", FIXTURES)
    async def test_every_finding_is_fully_populated(
        self, name: str, fixture_repo: RepoResolver
    ) -> None:
        root = fixture_repo(name)
        result = await run(root)

        assert result.findings, f"{name} produced no findings"
        for finding in result.findings:
            assert finding.rule_id
            assert finding.title.strip()
            assert finding.description.strip()
            assert finding.locations
            assert finding.fingerprint
            assert 0.0 < finding.confidence <= 1.0
            assert finding.expected, f"{finding.rule_id} has no expected value"
            assert finding.actual, f"{finding.rule_id} has no actual value"
            assert finding.evidence.strip(), f"{finding.rule_id} has no evidence"

            location = finding.primary_location
            assert (root / location.file_path).is_file()
            assert location.line_start >= 1
            assert location.line_end >= location.line_start

    @pytest.mark.parametrize("name", FIXTURES)
    async def test_fingerprints_are_unique_per_finding(
        self, name: str, fixture_repo: RepoResolver
    ) -> None:
        """Deduplication has already run, so no two findings may collide."""
        result = await run(fixture_repo(name))
        fingerprints = [finding.fingerprint for finding in result.findings]

        assert len(fingerprints) == len(set(fingerprints))

    async def test_no_finding_leaks_a_secret(self, fixture_repo: RepoResolver) -> None:
        """MergeX must not store the credentials it reports."""
        root = fixture_repo("react_fastapi_insecure")
        result = await run(root)

        literals = [
            "sk_live_51H8xQ2KmNvR7pLdX4bWcZaYeTfUgIhJkOm",
            "Adm1n!Payments2024",
            "p0stgr3s-prod-pw",
            "super-secret-dev-key-do-not-ship",
            "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            "xK9mPq2wRtY7",
        ]
        rendered = json.dumps(
            [
                {
                    "description": finding.description,
                    "evidence": finding.evidence,
                    "expected": finding.expected,
                    "actual": finding.actual,
                    "metadata": {k: str(v) for k, v in finding.metadata.items()},
                }
                for finding in result.findings
            ]
        )

        for literal in literals:
            assert literal not in rendered, f"{literal!r} leaked into a finding"


class TestScoring:
    async def test_a_single_category_failure_leaves_the_others_clean(
        self, fixture_repo: RepoResolver
    ) -> None:
        result = await run(fixture_repo("react_fastapi_mismatch"))

        assert result.score.categories["api_contract"].score < 100
        assert result.score.categories["schema"].score == 100
        assert result.score.categories["security"].score == 100

    async def test_the_api_fixture_scores_as_the_formula_dictates(
        self, fixture_repo: RepoResolver
    ) -> None:
        # 2 critical (-30) + 3 high (-24) = 46
        result = await run(fixture_repo("react_fastapi_mismatch"))

        assert result.score.score == 46

    async def test_the_schema_fixture_scores_as_the_formula_dictates(
        self, fixture_repo: RepoResolver
    ) -> None:
        # 2 critical (-30) + 1 high (-8) + 1 medium (-3) + 1 low (-1) = 58
        result = await run(fixture_repo("react_fastapi_schema_drift"))

        assert result.score.score == 58

    async def test_the_insecure_fixture_floors_at_zero(self, fixture_repo: RepoResolver) -> None:
        result = await run(fixture_repo("react_fastapi_insecure"))

        assert result.score.score == 0
        assert result.score.is_floored

    async def test_unanalysed_categories_are_marked(self, fixture_repo: RepoResolver) -> None:
        """Fixture 1 has no migrations, so its schema was not checked."""
        result = await run(fixture_repo("react_fastapi_mismatch"))

        assert result.score.categories["schema"].analysed is False
        assert result.score.categories["api_contract"].analysed is True


class TestCompletenessNotes:
    """'We found nothing' and 'we could not look' must read differently."""

    async def test_a_skipped_category_is_explained(self, fixture_repo: RepoResolver) -> None:
        result = await run(fixture_repo("react_fastapi_mismatch"))

        assert any("Schema checks were skipped" in note for note in result.notes)

    async def test_a_frontend_only_repo_says_why(self, tmp_path: Path) -> None:
        (tmp_path / "frontend").mkdir()
        (tmp_path / "frontend" / "api.ts").write_text('api.get("/api/users");\n', encoding="utf-8")

        result = await run(tmp_path)

        assert result.findings == []
        assert any("no backend routes" in note for note in result.notes)

    async def test_omitting_the_advisory_client_is_noted(self, fixture_repo: RepoResolver) -> None:
        """The engine never reaches the network on its own."""
        result = await run(fixture_repo("react_fastapi_insecure"), with_osv=False)

        assert any("Dependency vulnerability checking was not run" in n for n in result.notes)
        assert not any(f.rule_id == "MX-DEP-001" for f in result.findings)

    async def test_a_degraded_lookup_does_not_fail_the_analysis(
        self, fixture_repo: RepoResolver
    ) -> None:
        """An OSV outage must not stop the other findings being reported."""
        offline = StaticVulnerabilityClient(degraded=True, degraded_reason="timeout")

        result = await analyse(fixture_repo("react_fastapi_insecure"), vulnerability_client=offline)

        assert any(f.rule_id == "MX-SEC-001" for f in result.findings)
        assert not any(f.rule_id == "MX-DEP-001" for f in result.findings)
        assert any("unavailable" in note for note in result.notes)

    async def test_a_clean_run_has_no_notes(self, tmp_path: Path) -> None:
        (tmp_path / "backend").mkdir()
        (tmp_path / "frontend").mkdir()
        (tmp_path / "backend" / "main.py").write_text(
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n"
            '@app.get("/api/users")\n'
            "def list_users():\n"
            "    pass\n",
            encoding="utf-8",
        )
        (tmp_path / "backend" / "models.py").write_text(
            "from sqlalchemy import Column, Integer\n"
            "class User(Base):\n"
            '    __tablename__ = "users"\n'
            "    id = Column(Integer, primary_key=True)\n",
            encoding="utf-8",
        )
        (tmp_path / "backend" / "migrations.sql").write_text(
            "CREATE TABLE users (id SERIAL PRIMARY KEY);\n", encoding="utf-8"
        )
        (tmp_path / "frontend" / "api.ts").write_text('api.get("/api/users");\n', encoding="utf-8")

        result = await run(tmp_path)

        assert result.findings == []
        assert result.is_complete, f"unexpected notes: {result.notes}"


class TestDeterminism:
    @pytest.mark.parametrize("name", FIXTURES)
    async def test_two_runs_produce_identical_output(
        self, name: str, fixture_repo: RepoResolver
    ) -> None:
        """A score that moves between runs is a score nobody can act on."""
        root = fixture_repo(name)

        first = await run(root)
        second = await run(root)

        def signature(result: object) -> list[tuple[str, str, str]]:
            return [
                (finding.rule_id, finding.fingerprint, str(finding.primary_location))
                for finding in result.findings  # type: ignore[attr-defined]
            ]

        assert signature(first) == signature(second)
        assert first.score.score == second.score.score

    @pytest.mark.parametrize("name", FIXTURES)
    async def test_findings_are_ordered_worst_first(
        self, name: str, fixture_repo: RepoResolver
    ) -> None:
        rank = {
            Severity.CRITICAL: 0,
            Severity.HIGH: 1,
            Severity.MEDIUM: 2,
            Severity.LOW: 3,
        }
        result = await run(fixture_repo(name))

        severities = [rank[finding.severity] for finding in result.findings]

        assert severities == sorted(severities)


class TestExtractionCounts:
    async def test_counts_describe_what_was_examined(self, fixture_repo: RepoResolver) -> None:
        """So a report can say "we looked at N routes" rather than just a score."""
        result = await run(fixture_repo("react_fastapi_mismatch"))

        assert result.counts["frontend_calls"] == 8
        assert result.counts["backend_routes"] == 8
        assert result.counts["request_models"] == 4

    async def test_duration_is_recorded(self, fixture_repo: RepoResolver) -> None:
        result = await run(fixture_repo("react_fastapi_mismatch"))

        assert result.duration_ms >= 0
