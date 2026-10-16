"""The report endpoint and the progress stream.

``GET /analyses/{id}/report`` is what Phase 5 renders, so it is asserted here
as a contract: score, sub-scores, every issue with its explanation and a
concrete before/after, the detected stack, and the caveats about what could
not be checked.

``GET /analyses/{id}/events`` is asserted for the three cases that matter to a
browser: a client that connects late, one that reconnects with
``Last-Event-ID``, and one watching a run that fails. In all three the stream
must end with a terminal event rather than going quiet.

One test runs the whole thing: upload a real fixture repository, queue an
analysis, and read the report back. ``TestClient`` runs the background task
inline, which makes that a genuine end-to-end check of the API, the pipeline,
persistence and the report in one pass.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sse_starlette.sse import AppStatus

from app.core.config import Settings
from app.core.events import EventStatus, Stage, event_bus
from app.models.enums import AnalysisStatus, IssueCategory, Severity
from tests.conftest import FIXTURE_CREDENTIALS

MISSING_ID = "0ad4b1a6-0000-4000-8000-000000000000"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def zip_of(root: Path) -> bytes:
    """Pack a directory the way a user's upload arrives."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.name != "expected_findings.json":
                archive.write(path, path.relative_to(root).as_posix())
    return buffer.getvalue()


def sync_engine(settings: Settings) -> sa.Engine:
    return sa.create_engine(settings.database_url.replace("+aiosqlite", ""))


def hex_id(value: str | uuid.UUID) -> str:
    return str(value).replace("-", "")


SCORE_PAYLOAD = {
    "score": 61,
    "total_issues": 4,
    "severity_counts": {"critical": 1, "high": 2, "medium": 1, "low": 0},
    "is_floored": False,
    "categories": {
        "api_contract": {
            "score": 84,
            "issue_count": 2,
            "severity_counts": {"high": 2},
            "analysed": True,
        },
        "security": {
            "score": 85,
            "issue_count": 1,
            "severity_counts": {"critical": 1},
            "analysed": True,
        },
        "schema": {
            "score": 100,
            "issue_count": 0,
            "severity_counts": {},
            "analysed": False,
        },
        "dependency": {
            "score": 97,
            "issue_count": 1,
            "severity_counts": {"medium": 1},
            "analysed": True,
        },
    },
}

STACK_PAYLOAD = {
    "frontend": ["React"],
    "backend": ["FastAPI"],
    "database": ["PostgreSQL"],
    "notes": ["Schema checks were skipped: no migrations were found."],
    "counts": {"frontend_calls": 8, "backend_routes": 8},
    "failed_groups": ["schema"],
    "explanation_sources": {"gemini": 3, "template": 1},
}


@pytest.fixture
def seeded(client: TestClient, settings: Settings) -> dict[str, str]:
    """A finished analysis with four issues, written directly.

    Seeded rather than produced by a run so the report's shape is asserted
    against known values, including the cases a real fixture would not
    produce: a floored score, a failed group, a missing explanation.
    """
    project_id = uuid.uuid4()
    analysis_id = uuid.uuid4()

    engine = sync_engine(settings)
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    "INSERT INTO projects (id, created_at, updated_at, name,"
                    " source_type, source_url) VALUES (:id, CURRENT_TIMESTAMP,"
                    " CURRENT_TIMESTAMP, :name, 'github', :url)"
                ),
                {
                    "id": hex_id(project_id),
                    "name": "payments-api",
                    "url": "https://github.com/acme/payments-api",
                },
            )
            connection.execute(
                sa.text(
                    "INSERT INTO analyses (id, created_at, updated_at, project_id,"
                    " status, health_score, category_scores, stack, commit_sha,"
                    " file_count, duration_ms, started_at, completed_at,"
                    " ai_explanations_available)"
                    " VALUES (:id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, :project_id,"
                    " 'succeeded', 61, :scores, :stack, :sha, 128, 4210,"
                    " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)"
                ),
                {
                    "id": hex_id(analysis_id),
                    "project_id": hex_id(project_id),
                    "scores": json.dumps(SCORE_PAYLOAD),
                    "stack": json.dumps(STACK_PAYLOAD),
                    "sha": "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
                },
            )
            rows = [
                (
                    IssueCategory.SECURITY,
                    Severity.CRITICAL,
                    "MX-SEC-001",
                    "Hardcoded credential in frontend source",
                    'export const STRIPE_SECRET_KEY = "********JkOm";',
                    "This key is bundled into the client build.",
                    "At frontend/src/api/config.ts:3, read it from the server.",
                ),
                (
                    IssueCategory.API_CONTRACT,
                    Severity.HIGH,
                    "MX-API-001",
                    "Frontend calls an endpoint the backend does not define",
                    'api.get("/api/user/${id}");',
                    "The path is singular; the backend defines the plural form.",
                    "At frontend/src/api/users.ts:12, use /api/users/${id}.",
                ),
                (
                    IssueCategory.API_CONTRACT,
                    Severity.HIGH,
                    "MX-API-002",
                    "Backend route is never called",
                    "@router.get('/api/reports/monthly')",
                    None,
                    None,
                ),
                (
                    IssueCategory.DEPENDENCY,
                    Severity.MEDIUM,
                    "MX-DEP-001",
                    "Dependency has a known vulnerability",
                    "PyYAML==5.3.1",
                    "CVE-2020-14343 allows code execution.",
                    "In backend/requirements.txt:4, raise PyYAML to 5.4.",
                ),
            ]
            for index, (
                category,
                severity,
                rule,
                title,
                evidence,
                explanation,
                fix,
            ) in enumerate(rows):
                connection.execute(
                    sa.text(
                        "INSERT INTO issues (id, analysis_id, created_at, updated_at,"
                        " category, severity, title, description, detected_by,"
                        " confidence, fingerprint, file_path, line_start, line_end,"
                        " evidence, expected, actual, explanation, suggested_fix,"
                        " explanation_source, fix_before, fix_after)"
                        " VALUES (:id, :analysis_id, CURRENT_TIMESTAMP,"
                        " CURRENT_TIMESTAMP, :category, :severity, :title,"
                        " :description, :rule, :confidence, :fingerprint, :file_path,"
                        " :line_start, :line_end, :evidence, :expected, :actual,"
                        " :explanation, :fix, :source, :before, :after)"
                    ),
                    {
                        "id": hex_id(uuid.uuid4()),
                        "analysis_id": hex_id(analysis_id),
                        "category": category.value,
                        "severity": severity.value,
                        "title": title,
                        "description": f"{title}.",
                        "rule": rule,
                        "confidence": 0.95,
                        "fingerprint": f"fp-{index}",
                        "file_path": f"src/file{index}.ts",
                        "line_start": index + 1,
                        "line_end": index + 1,
                        "evidence": evidence,
                        "expected": "the expected value",
                        "actual": "the actual value",
                        "explanation": explanation,
                        "fix": fix,
                        "source": "gemini" if explanation else None,
                        "before": evidence if fix else None,
                        "after": "corrected();" if fix else None,
                    },
                )
    finally:
        engine.dispose()

    return {"project_id": str(project_id), "analysis_id": str(analysis_id)}


@pytest.fixture(autouse=True)
def clean_bus() -> Iterator[None]:
    """The event bus is process-wide; a test must not see another's events.

    Also clears ``sse_starlette``'s shutdown event, which it caches at module
    level on first use and binds to the event loop that created it.
    ``TestClient`` runs each request in a fresh loop, so without this reset
    the second SSE request in a session fails with "bound to a different
    event loop". A server has one long-lived loop, so this is an artefact of
    the test transport rather than a defect in the endpoint.
    """
    event_bus.reset()
    AppStatus.should_exit_event = None
    yield
    event_bus.reset()
    AppStatus.should_exit_event = None


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


class TestReport:
    def test_the_score_and_sub_scores_are_returned(
        self, client: TestClient, seeded: dict[str, str]
    ) -> None:
        response = client.get(f"/api/v1/analyses/{seeded['analysis_id']}/report")

        assert response.status_code == 200
        body = response.json()
        assert body["score"]["score"] == 61
        assert body["score"]["total_issues"] == 4
        assert body["score"]["severity_counts"]["critical"] == 1
        assert body["score"]["categories"]["api_contract"]["score"] == 84
        assert body["score"]["categories"]["api_contract"]["issue_count"] == 2

    def test_an_unanalysed_category_says_so(
        self, client: TestClient, seeded: dict[str, str]
    ) -> None:
        """100 because nothing was checked is not 100 because all was well."""
        body = client.get(f"/api/v1/analyses/{seeded['analysis_id']}/report").json()

        schema = body["score"]["categories"]["schema"]
        assert schema["score"] == 100
        assert schema["analysed"] is False

    def test_the_issues_carry_their_explanations(
        self, client: TestClient, seeded: dict[str, str]
    ) -> None:
        body = client.get(f"/api/v1/analyses/{seeded['analysis_id']}/report").json()

        explained = [issue for issue in body["issues"] if issue["explanation"]]
        assert len(explained) == 3
        first = explained[0]
        assert first["suggested_fix"]
        assert first["explanation_source"] == "gemini"
        assert first["fix_before"] and first["fix_after"]

    def test_an_unexplained_issue_is_still_returned(
        self, client: TestClient, seeded: dict[str, str]
    ) -> None:
        """A finding without prose is still a finding."""
        body = client.get(f"/api/v1/analyses/{seeded['analysis_id']}/report").json()

        unexplained = [issue for issue in body["issues"] if not issue["explanation"]]
        assert len(unexplained) == 1
        assert unexplained[0]["rule_id"] == "MX-API-002"
        assert unexplained[0]["title"]
        assert unexplained[0]["file_path"]

    def test_issues_are_ordered_most_severe_first(
        self, client: TestClient, seeded: dict[str, str]
    ) -> None:
        body = client.get(f"/api/v1/analyses/{seeded['analysis_id']}/report").json()

        assert [issue["severity"] for issue in body["issues"]] == [
            "critical",
            "high",
            "high",
            "medium",
        ]

    def test_every_issue_carries_its_location_and_rule(
        self, client: TestClient, seeded: dict[str, str]
    ) -> None:
        body = client.get(f"/api/v1/analyses/{seeded['analysis_id']}/report").json()

        for issue in body["issues"]:
            assert issue["rule_id"].startswith("MX-")
            assert issue["file_path"]
            assert issue["line_start"] is not None
            assert issue["fingerprint"]
            assert 0.0 < issue["confidence"] <= 1.0

    def test_the_caveats_are_separated_from_the_stack(
        self, client: TestClient, seeded: dict[str, str]
    ) -> None:
        body = client.get(f"/api/v1/analyses/{seeded['analysis_id']}/report").json()

        assert body["notes"] == STACK_PAYLOAD["notes"]
        assert body["failed_groups"] == ["schema"]
        assert body["counts"]["frontend_calls"] == 8
        assert body["explanation_sources"] == {"gemini": 3, "template": 1}
        # The sidecar keys are surfaced as their own fields, not duplicated.
        assert body["stack"]["frontend"] == ["React"]
        assert "notes" not in body["stack"]
        assert "failed_groups" not in body["stack"]

    def test_the_run_metadata_is_included(self, client: TestClient, seeded: dict[str, str]) -> None:
        body = client.get(f"/api/v1/analyses/{seeded['analysis_id']}/report").json()

        assert body["project_name"] == "payments-api"
        assert body["status"] == "succeeded"
        assert body["file_count"] == 128
        assert body["duration_ms"] == 4210
        assert body["commit_sha"].startswith("a1b2c3d4")
        assert body["started_at"] and body["completed_at"]

    def test_a_pending_analysis_reports_no_score(
        self, client: TestClient, settings: Settings, seeded: dict[str, str]
    ) -> None:
        """The endpoint is readable while a run is still in flight."""
        engine = sync_engine(settings)
        try:
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "UPDATE analyses SET status='running', health_score=NULL,"
                        " category_scores=NULL WHERE id=:id"
                    ),
                    {"id": hex_id(seeded["analysis_id"])},
                )
        finally:
            engine.dispose()

        body = client.get(f"/api/v1/analyses/{seeded['analysis_id']}/report").json()

        assert body["status"] == "running"
        assert body["score"] is None

    def test_a_failed_analysis_reports_its_error(
        self, client: TestClient, settings: Settings, seeded: dict[str, str]
    ) -> None:
        engine = sync_engine(settings)
        try:
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "UPDATE analyses SET status='failed',"
                        " error_message='Repository not found.' WHERE id=:id"
                    ),
                    {"id": hex_id(seeded["analysis_id"])},
                )
        finally:
            engine.dispose()

        body = client.get(f"/api/v1/analyses/{seeded['analysis_id']}/report").json()

        assert body["status"] == "failed"
        assert body["error_message"] == "Repository not found."

    def test_an_unknown_analysis_returns_404(self, client: TestClient) -> None:
        response = client.get(f"/api/v1/analyses/{MISSING_ID}/report")

        assert response.status_code == 404
        assert response.json()["detail"] == "Analysis not found."

    def test_a_malformed_id_returns_422(self, client: TestClient) -> None:
        response = client.get("/api/v1/analyses/not-a-uuid/report")

        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Server-Sent Events
# ---------------------------------------------------------------------------


def parse_sse(payload: str) -> list[dict[str, object]]:
    """Pull the JSON out of an SSE body, ignoring comments."""
    events: list[dict[str, object]] = []
    for block in payload.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))
    return events


class TestEventStream:
    def test_a_late_client_receives_the_whole_run(
        self, client: TestClient, seeded: dict[str, str]
    ) -> None:
        analysis_id = seeded["analysis_id"]
        event_bus.publish(analysis_id, Stage.QUEUED, EventStatus.STARTED, "Queued.")
        event_bus.publish(
            analysis_id,
            Stage.API_CONTRACT,
            EventStatus.COMPLETED,
            "2 issues.",
            finding_count=2,
        )
        event_bus.publish(
            analysis_id,
            Stage.COMPLETE,
            EventStatus.COMPLETED,
            "Done.",
            total_findings=2,
        )

        response = client.get(f"/api/v1/analyses/{analysis_id}/events")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = parse_sse(response.text)
        assert [event["stage"] for event in events] == ["queued", "api", "complete"]
        assert events[-1]["status"] == "completed"

    def test_the_frames_carry_ids_for_reconnection(
        self, client: TestClient, seeded: dict[str, str]
    ) -> None:
        analysis_id = seeded["analysis_id"]
        event_bus.publish(analysis_id, Stage.QUEUED, EventStatus.STARTED, "Queued.")
        event_bus.publish(analysis_id, Stage.COMPLETE, EventStatus.COMPLETED, "Done.")

        response = client.get(f"/api/v1/analyses/{analysis_id}/events")

        assert "id: 1" in response.text
        assert "event: queued" in response.text
        assert "event: complete" in response.text

    def test_a_reconnecting_client_gets_only_what_it_missed(
        self, client: TestClient, seeded: dict[str, str]
    ) -> None:
        """The ``Last-Event-ID`` header is what a browser sends automatically."""
        analysis_id = seeded["analysis_id"]
        for index in range(4):
            event_bus.publish(analysis_id, Stage.STACK, EventStatus.COMPLETED, f"step {index}")
        event_bus.publish(analysis_id, Stage.COMPLETE, EventStatus.COMPLETED, "Done.")

        response = client.get(
            f"/api/v1/analyses/{analysis_id}/events",
            headers={"Last-Event-ID": "3"},
        )

        events = parse_sse(response.text)
        assert [event["id"] for event in events] == [4, 5]

    def test_the_last_event_id_can_be_a_query_parameter(
        self, client: TestClient, seeded: dict[str, str]
    ) -> None:
        """For clients that cannot set headers, such as a plain EventSource."""
        analysis_id = seeded["analysis_id"]
        event_bus.publish(analysis_id, Stage.QUEUED, EventStatus.STARTED, "Queued.")
        event_bus.publish(analysis_id, Stage.COMPLETE, EventStatus.COMPLETED, "Done.")

        response = client.get(
            f"/api/v1/analyses/{analysis_id}/events", params={"last_event_id": "1"}
        )

        assert [event["id"] for event in parse_sse(response.text)] == [2]

    @pytest.mark.parametrize("value", ["", "abc", "-5", "99999999999999999999"])
    def test_a_nonsense_last_event_id_is_tolerated(
        self, client: TestClient, seeded: dict[str, str], value: str
    ) -> None:
        """A malformed header must not turn into a 500."""
        analysis_id = seeded["analysis_id"]
        event_bus.publish(analysis_id, Stage.QUEUED, EventStatus.STARTED, "Queued.")
        event_bus.publish(analysis_id, Stage.COMPLETE, EventStatus.COMPLETED, "Done.")

        response = client.get(
            f"/api/v1/analyses/{analysis_id}/events",
            headers={"Last-Event-ID": value},
        )

        assert response.status_code == 200

    def test_a_failed_run_still_ends_the_stream(
        self, client: TestClient, seeded: dict[str, str]
    ) -> None:
        analysis_id = seeded["analysis_id"]
        event_bus.publish(analysis_id, Stage.IMPORTING, EventStatus.STARTED, "Cloning.")
        event_bus.publish(analysis_id, Stage.COMPLETE, EventStatus.FAILED, "Repository not found.")

        events = parse_sse(client.get(f"/api/v1/analyses/{analysis_id}/events").text)

        assert events[-1]["stage"] == "complete"
        assert events[-1]["status"] == "failed"
        assert events[-1]["message"] == "Repository not found."

    def test_the_stage_counts_are_streamed(
        self, client: TestClient, seeded: dict[str, str]
    ) -> None:
        """The requirement: a status and a finding count per stage."""
        analysis_id = seeded["analysis_id"]
        for stage, count in [
            (Stage.API_CONTRACT, 2),
            (Stage.SCHEMA, 1),
            (Stage.SECURITY, 4),
        ]:
            event_bus.publish(
                analysis_id,
                stage,
                EventStatus.COMPLETED,
                f"{stage.value} complete",
                finding_count=count,
            )
        event_bus.publish(analysis_id, Stage.COMPLETE, EventStatus.COMPLETED, "Done.")

        events = parse_sse(client.get(f"/api/v1/analyses/{analysis_id}/events").text)

        counted = {
            event["stage"]: event.get("finding_count")
            for event in events
            if "finding_count" in event
        }
        assert counted == {"api": 2, "schema": 1, "security": 4}

    def test_an_unknown_analysis_returns_404(self, client: TestClient) -> None:
        """Not an empty stream: a 404 tells the client to stop retrying."""
        response = client.get(f"/api/v1/analyses/{MISSING_ID}/events")

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------


class TestTheWholePipelineThroughTheApi:
    """Upload a fixture, analyse it, read the report.

    ``TestClient`` runs the background task inline, so a single request
    exercises the API, the importer, the workflow, persistence and the report.
    """

    @pytest.fixture
    def analysed(
        self, client: TestClient, fixture_repo: Callable[[str], Path]
    ) -> dict[str, object]:
        upload = client.post(
            "/api/v1/projects/upload",
            files={
                "file": (
                    "insecure.zip",
                    zip_of(fixture_repo("react_fastapi_insecure")),
                    "application/zip",
                )
            },
        )
        assert upload.status_code == 201, upload.text
        project_id = upload.json()["project"]["id"]

        created = client.post(f"/api/v1/projects/{project_id}/analyses", json={})
        assert created.status_code == 201, created.text
        analysis_id = created.json()["id"]

        report = client.get(f"/api/v1/analyses/{analysis_id}/report")
        assert report.status_code == 200, report.text
        body: dict[str, object] = report.json()
        return body

    def test_the_analysis_succeeded(self, analysed: dict[str, object]) -> None:
        assert analysed["status"] == AnalysisStatus.SUCCEEDED.value
        assert analysed["error_message"] is None

    def test_the_seeded_defects_are_reported(self, analysed: dict[str, object]) -> None:
        issues = analysed["issues"]
        assert isinstance(issues, list)
        rules = {issue["rule_id"] for issue in issues}

        assert "MX-SEC-001" in rules, "the hardcoded secret was not reported"
        assert "MX-SEC-004" in rules, "the committed .env was not reported"

    def test_the_score_reflects_the_defects(self, analysed: dict[str, object]) -> None:
        score = analysed["score"]
        assert isinstance(score, dict)

        assert score["score"] < 100
        assert score["total_issues"] == len(analysed["issues"])  # type: ignore[arg-type]
        assert score["categories"]["security"]["issue_count"] > 0

    def test_every_issue_is_explained_without_an_api_key(self, analysed: dict[str, object]) -> None:
        """The offline path, through the API: prose for every finding."""
        issues = analysed["issues"]
        assert isinstance(issues, list)

        assert all(issue["explanation"] for issue in issues)
        assert all(issue["suggested_fix"] for issue in issues)
        assert {issue["explanation_source"] for issue in issues} == {"template"}

    def test_the_fixes_name_a_real_location(self, analysed: dict[str, object]) -> None:
        """Not generic advice: the fix must point at the file it applies to."""
        issues = analysed["issues"]
        assert isinstance(issues, list)

        for issue in issues:
            fix = issue["suggested_fix"]
            assert (
                issue["file_path"] in fix or str(issue["line_start"]) in fix
            ), f"{issue['rule_id']}: the fix does not name its own location"

    def test_no_credential_is_returned_by_the_api(self, analysed: dict[str, object]) -> None:
        """The last line of defence: nothing leaks through the response body."""
        body = json.dumps(analysed)

        leaked = [secret for secret in FIXTURE_CREDENTIALS if secret in body]

        assert leaked == [], f"credentials returned by the report endpoint: {leaked}"

    def test_the_stream_recorded_the_run(
        self, client: TestClient, analysed: dict[str, object]
    ) -> None:
        """The events of a finished run are still replayable afterwards."""
        response = client.get(f"/api/v1/analyses/{analysed['analysis_id']}/events")

        events = parse_sse(response.text)
        stages = [event["stage"] for event in events]
        assert stages[0] == "queued"
        assert stages[-1] == "complete"
        assert {"importing", "stack", "api", "schema", "security", "synthesis"} <= set(stages)
