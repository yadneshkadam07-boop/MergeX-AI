"""Analysis endpoints.

Phase 1 manages the *record* of a run; the pipeline that executes it lands in
Phase 4. These tests therefore cover lifecycle and query behaviour, and seed
issues directly through the ORM to exercise the tallies and the severity
ordering the dashboard depends on.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.models.enums import AnalysisStatus, IssueCategory, Severity

MISSING_ID = "0ad4b1a6-0000-4000-8000-000000000000"

SAMPLE_TREE = {
    "package.json": json.dumps({"dependencies": {"react": "^18.3.1"}}),
    "backend/requirements.txt": "fastapi==0.111.0\n",
}


def make_zip(members: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()


@pytest.fixture
def project_id(client: TestClient) -> str:
    """A project created through the real upload endpoint."""
    response = client.post(
        "/api/v1/projects/upload",
        files={"file": ("app.zip", make_zip(SAMPLE_TREE), "application/zip")},
    )
    assert response.status_code == 201
    return str(response.json()["project"]["id"])


def seed_issues(settings: Settings, analysis_id: str, severities: list[Severity]) -> None:
    """Insert issues directly.

    Written with Core against the sync driver because no code path creates
    issues until Phase 4, and going through the ORM here would test nothing.
    """
    engine = sa.create_engine(settings.database_url.replace("+aiosqlite", ""))
    try:
        with engine.begin() as connection:
            for index, severity in enumerate(severities):
                connection.execute(
                    sa.text(
                        "INSERT INTO issues (id, analysis_id, created_at, updated_at,"
                        " category, severity, title, description, detected_by,"
                        " confidence, fingerprint, file_path, line_start)"
                        " VALUES (:id, :analysis_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,"
                        " :category, :severity, :title, :description, :detected_by,"
                        " :confidence, :fingerprint, :file_path, :line_start)"
                    ),
                    {
                        "id": str(uuid.uuid4()).replace("-", ""),
                        "analysis_id": analysis_id.replace("-", ""),
                        "category": IssueCategory.API_CONTRACT.value,
                        "severity": severity.value,
                        "title": f"Seeded {severity.value} issue",
                        "description": "Seeded for test purposes.",
                        "detected_by": "MX-API-001",
                        "confidence": 1.0,
                        "fingerprint": f"fp-{index}",
                        "file_path": f"src/file{index}.ts",
                        "line_start": index + 1,
                    },
                )
    finally:
        engine.dispose()


class TestCreateAnalysis:
    def test_queues_a_pending_run(self, client: TestClient, project_id: str) -> None:
        response = client.post(f"/api/v1/projects/{project_id}/analyses", json={})

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "pending"
        assert body["project_id"] == project_id
        # Nothing has run yet, so there are no results.
        assert body["health_score"] is None
        assert body["stage"] is None
        assert body["completed_at"] is None
        assert body["ai_explanations_available"] is False

    def test_records_a_ref_override(self, client: TestClient, project_id: str) -> None:
        response = client.post(
            f"/api/v1/projects/{project_id}/analyses", json={"source_ref": "release/v2"}
        )

        assert response.status_code == 201
        assert response.json()["stack"] == {"requested_ref": "release/v2"}

    def test_refuses_a_second_concurrent_run(self, client: TestClient, project_id: str) -> None:
        """A double-click must not start two clones of the same repository."""
        assert client.post(f"/api/v1/projects/{project_id}/analyses", json={}).status_code == 201

        second = client.post(f"/api/v1/projects/{project_id}/analyses", json={})

        assert second.status_code == 409
        assert "already queued or running" in second.json()["detail"]

    def test_allows_a_new_run_once_the_previous_one_finished(
        self, client: TestClient, project_id: str, settings: Settings
    ) -> None:
        first = client.post(f"/api/v1/projects/{project_id}/analyses", json={}).json()
        _set_status(settings, first["id"], AnalysisStatus.SUCCEEDED)

        second = client.post(f"/api/v1/projects/{project_id}/analyses", json={})

        assert second.status_code == 201

    def test_unknown_project_returns_404(self, client: TestClient) -> None:
        response = client.post(f"/api/v1/projects/{MISSING_ID}/analyses", json={})

        assert response.status_code == 404

    def test_rejects_unknown_fields(self, client: TestClient, project_id: str) -> None:
        response = client.post(
            f"/api/v1/projects/{project_id}/analyses", json={"status": "succeeded"}
        )

        assert response.status_code == 422


class TestListAnalyses:
    def test_lists_newest_first(
        self, client: TestClient, project_id: str, settings: Settings
    ) -> None:
        first = client.post(f"/api/v1/projects/{project_id}/analyses", json={}).json()
        _set_status(settings, first["id"], AnalysisStatus.SUCCEEDED)
        second = client.post(f"/api/v1/projects/{project_id}/analyses", json={}).json()

        body = client.get(f"/api/v1/projects/{project_id}/analyses").json()

        assert body["total"] == 2
        returned = [item["analysis"]["id"] for item in body["items"]]
        assert set(returned) == {first["id"], second["id"]}

    def test_includes_issue_tallies(
        self, client: TestClient, project_id: str, settings: Settings
    ) -> None:
        analysis = client.post(f"/api/v1/projects/{project_id}/analyses", json={}).json()
        seed_issues(
            settings,
            analysis["id"],
            [Severity.CRITICAL, Severity.CRITICAL, Severity.HIGH, Severity.LOW],
        )

        body = client.get(f"/api/v1/projects/{project_id}/analyses").json()

        counts = body["items"][0]["issue_counts"]
        assert counts == {"total": 4, "critical": 2, "high": 1, "medium": 0, "low": 1}

    def test_tallies_are_zero_for_a_pending_run(self, client: TestClient, project_id: str) -> None:
        client.post(f"/api/v1/projects/{project_id}/analyses", json={})

        body = client.get(f"/api/v1/projects/{project_id}/analyses").json()

        assert body["items"][0]["issue_counts"]["total"] == 0

    def test_empty_list_for_a_project_with_no_runs(
        self, client: TestClient, project_id: str
    ) -> None:
        body = client.get(f"/api/v1/projects/{project_id}/analyses").json()

        assert body["items"] == []
        assert body["total"] == 0

    def test_unknown_project_returns_404(self, client: TestClient) -> None:
        assert client.get(f"/api/v1/projects/{MISSING_ID}/analyses").status_code == 404

    def test_paginates(self, client: TestClient, project_id: str, settings: Settings) -> None:
        for _ in range(3):
            created = client.post(f"/api/v1/projects/{project_id}/analyses", json={}).json()
            _set_status(settings, created["id"], AnalysisStatus.SUCCEEDED)

        body = client.get(f"/api/v1/projects/{project_id}/analyses", params={"limit": 2}).json()

        assert body["total"] == 3
        assert len(body["items"]) == 2


class TestGetAnalysis:
    def test_reads_one_run(self, client: TestClient, project_id: str) -> None:
        created = client.post(f"/api/v1/projects/{project_id}/analyses", json={}).json()

        response = client.get(f"/api/v1/analyses/{created['id']}")

        assert response.status_code == 200
        assert response.json()["analysis"]["id"] == created["id"]

    def test_unknown_id_returns_404(self, client: TestClient) -> None:
        assert client.get(f"/api/v1/analyses/{MISSING_ID}").status_code == 404

    def test_malformed_id_returns_422(self, client: TestClient) -> None:
        assert client.get("/api/v1/analyses/not-a-uuid").status_code == 422


class TestListIssues:
    def test_orders_by_severity_not_alphabetically(
        self, client: TestClient, project_id: str, settings: Settings
    ) -> None:
        """Alphabetical order would give critical, high, low, medium."""
        analysis = client.post(f"/api/v1/projects/{project_id}/analyses", json={}).json()
        seed_issues(
            settings,
            analysis["id"],
            [Severity.LOW, Severity.MEDIUM, Severity.CRITICAL, Severity.HIGH],
        )

        body = client.get(f"/api/v1/analyses/{analysis['id']}/issues").json()

        assert [item["severity"] for item in body["items"]] == [
            "critical",
            "high",
            "medium",
            "low",
        ]

    def test_returns_the_full_issue_shape(
        self, client: TestClient, project_id: str, settings: Settings
    ) -> None:
        analysis = client.post(f"/api/v1/projects/{project_id}/analyses", json={}).json()
        seed_issues(settings, analysis["id"], [Severity.CRITICAL])

        issue = client.get(f"/api/v1/analyses/{analysis['id']}/issues").json()["items"][0]

        assert issue["category"] == "api_contract"
        assert issue["detected_by"] == "MX-API-001"
        assert issue["confidence"] == 1.0
        assert issue["file_path"] == "src/file0.ts"
        # The model-generated fields are empty without an API key, by design.
        assert issue["explanation"] is None
        assert issue["suggested_fix"] is None

    def test_empty_for_an_analysis_with_no_findings(
        self, client: TestClient, project_id: str
    ) -> None:
        analysis = client.post(f"/api/v1/projects/{project_id}/analyses", json={}).json()

        body = client.get(f"/api/v1/analyses/{analysis['id']}/issues").json()

        assert body == {"items": [], "total": 0, "limit": 20, "offset": 0}

    def test_unknown_analysis_returns_404(self, client: TestClient) -> None:
        assert client.get(f"/api/v1/analyses/{MISSING_ID}/issues").status_code == 404


class TestDeleteAnalysis:
    def test_deletes_a_finished_run(self, client: TestClient, project_id: str) -> None:
        created = client.post(f"/api/v1/projects/{project_id}/analyses", json={}).json()

        assert client.delete(f"/api/v1/analyses/{created['id']}").status_code == 204
        assert client.get(f"/api/v1/analyses/{created['id']}").status_code == 404

    def test_refuses_to_delete_a_running_analysis(
        self, client: TestClient, project_id: str, settings: Settings
    ) -> None:
        created = client.post(f"/api/v1/projects/{project_id}/analyses", json={}).json()
        _set_status(settings, created["id"], AnalysisStatus.RUNNING)

        response = client.delete(f"/api/v1/analyses/{created['id']}")

        assert response.status_code == 409
        assert "running" in response.json()["detail"]

    def test_deleting_an_analysis_deletes_its_issues(
        self, client: TestClient, project_id: str, settings: Settings
    ) -> None:
        analysis = client.post(f"/api/v1/projects/{project_id}/analyses", json={}).json()
        seed_issues(settings, analysis["id"], [Severity.CRITICAL, Severity.LOW])

        client.delete(f"/api/v1/analyses/{analysis['id']}")

        assert _issue_count(settings) == 0

    def test_unknown_id_returns_404(self, client: TestClient) -> None:
        assert client.delete(f"/api/v1/analyses/{MISSING_ID}").status_code == 404


class TestCascade:
    def test_deleting_a_project_deletes_its_analyses_and_issues(
        self, client: TestClient, project_id: str, settings: Settings
    ) -> None:
        analysis = client.post(f"/api/v1/projects/{project_id}/analyses", json={}).json()
        seed_issues(settings, analysis["id"], [Severity.HIGH])

        assert client.delete(f"/api/v1/projects/{project_id}").status_code == 204

        assert client.get(f"/api/v1/analyses/{analysis['id']}").status_code == 404
        assert _issue_count(settings) == 0


class TestErrorEnvelope:
    """Every error shares one shape, so the frontend handles one type."""

    def test_not_found_has_a_machine_code(self, client: TestClient) -> None:
        body = client.get(f"/api/v1/analyses/{MISSING_ID}").json()

        assert body["error"] == "not_found"
        assert body["detail"] == "Analysis not found."

    def test_conflict_has_a_machine_code(
        self, client: TestClient, project_id: str, settings: Settings
    ) -> None:
        created = client.post(f"/api/v1/projects/{project_id}/analyses", json={}).json()
        _set_status(settings, created["id"], AnalysisStatus.RUNNING)

        body = client.delete(f"/api/v1/analyses/{created['id']}").json()

        assert body["error"] == "conflict"

    def test_validation_errors_are_json_serialisable_and_itemised(self, client: TestClient) -> None:
        """A validator raising ValueError previously produced an opaque 500."""
        response = client.post("/api/v1/projects", json={"source_url": "https://gitlab.com/a/b"})

        assert response.status_code == 422
        body = response.json()
        assert body["error"] == "validation_error"
        assert isinstance(body["detail"], str)
        assert body["errors"][0]["field"] == "body.source_url"
        assert "github.com" in body["errors"][0]["message"]

    def test_a_missing_required_field_is_itemised(self, client: TestClient) -> None:
        response = client.post("/api/v1/projects", json={})

        assert response.status_code == 422
        body = response.json()
        assert body["error"] == "validation_error"
        assert [error["field"] for error in body["errors"]] == ["body.source_url"]
        assert body["errors"][0]["type"] == "missing"


def _set_status(settings: Settings, analysis_id: str, status: AnalysisStatus) -> None:
    """Move an analysis to a terminal/running state without a pipeline."""
    engine = sa.create_engine(settings.database_url.replace("+aiosqlite", ""))
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.text("UPDATE analyses SET status = :status WHERE id = :id"),
                {"status": status.value, "id": analysis_id.replace("-", "")},
            )
    finally:
        engine.dispose()


def _issue_count(settings: Settings) -> int:
    engine = sa.create_engine(settings.database_url.replace("+aiosqlite", ""))
    try:
        with engine.begin() as connection:
            return int(connection.execute(sa.text("SELECT COUNT(*) FROM issues")).scalar_one())
    finally:
        engine.dispose()
