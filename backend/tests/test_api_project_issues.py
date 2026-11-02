"""Tests for project-level issue endpoints:
- GET /api/v1/projects/{project_id}/issues
- GET /api/v1/projects/{project_id}/issues/{issue_id}
- PATCH /api/v1/projects/{project_id}/issues/{issue_id}
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
from app.models.enums import AnalysisStatus, IssueCategory, IssueStatus, Severity

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


@pytest.fixture(autouse=True)
def do_not_run_the_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    async def do_nothing(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr("app.api.routes.analyses._execute", do_nothing)


@pytest.fixture
def project_id(client: TestClient) -> str:
    response = client.post(
        "/api/v1/projects/upload",
        files={"file": ("app.zip", make_zip(SAMPLE_TREE), "application/zip")},
    )
    assert response.status_code == 201
    return str(response.json()["project"]["id"])


def seed_completed_analysis_with_issues(
    settings: Settings, project_id: str
) -> tuple[str, list[dict]]:
    """Create a succeeded analysis with diverse seeded issues."""
    engine = sa.create_engine(settings.database_url.replace("+aiosqlite", ""))
    analysis_id = str(uuid.uuid4()).replace("-", "")
    seeded_issues = [
        {
            "id": str(uuid.uuid4()).replace("-", ""),
            "analysis_id": analysis_id,
            "category": IssueCategory.API_CONTRACT.value,
            "severity": Severity.CRITICAL.value,
            "status": IssueStatus.OPEN.value,
            "title": "Auth API route mismatch",
            "description": "Frontend calls POST /auth/login, router specifies /token",
            "detected_by": "MX-API-001",
            "confidence": 1.0,
            "fingerprint": "fp-1",
            "file_path": "src/lib/api.ts",
            "line_start": 42,
        },
        {
            "id": str(uuid.uuid4()).replace("-", ""),
            "analysis_id": analysis_id,
            "category": IssueCategory.SECURITY.value,
            "severity": Severity.HIGH.value,
            "status": IssueStatus.OPEN.value,
            "title": "CORS wildcard allowed",
            "description": "CORS configured with allow_origins=['*']",
            "detected_by": "MX-SEC-002",
            "confidence": 0.95,
            "fingerprint": "fp-2",
            "file_path": "backend/app/main.py",
            "line_start": 15,
        },
        {
            "id": str(uuid.uuid4()).replace("-", ""),
            "analysis_id": analysis_id,
            "category": IssueCategory.DEPENDENCY.value,
            "severity": Severity.MEDIUM.value,
            "status": IssueStatus.RESOLVED.value,
            "title": "Vulnerable urllib3 version",
            "description": "CVE-2023-45803 in urllib3",
            "detected_by": "MX-DEP-003",
            "confidence": 1.0,
            "fingerprint": "fp-3",
            "file_path": "backend/requirements.txt",
            "line_start": 1,
        },
    ]

    try:
        with engine.begin() as connection:
            # Insert analysis record
            connection.execute(
                sa.text(
                    "INSERT INTO analyses (id, project_id, status, created_at, updated_at, completed_at, health_score, ai_explanations_available)"
                    " VALUES (:id, :project_id, :status, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 75, 0)"
                ),
                {
                    "id": analysis_id,
                    "project_id": project_id.replace("-", ""),
                    "status": AnalysisStatus.SUCCEEDED.value,
                },
            )
            # Insert issues
            for iss in seeded_issues:
                connection.execute(
                    sa.text(
                        "INSERT INTO issues (id, analysis_id, created_at, updated_at,"
                        " category, severity, status, title, description, detected_by,"
                        " confidence, fingerprint, file_path, line_start)"
                        " VALUES (:id, :analysis_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,"
                        " :category, :severity, :status, :title, :description, :detected_by,"
                        " :confidence, :fingerprint, :file_path, :line_start)"
                    ),
                    iss,
                )
    finally:
        engine.dispose()

    return str(uuid.UUID(analysis_id)), seeded_issues


class TestGetProjectIssues:
    def test_missing_project_returns_404(self, client: TestClient) -> None:
        response = client.get(f"/api/v1/projects/{MISSING_ID}/issues")
        assert response.status_code == 404

    def test_project_with_no_completed_analysis_returns_empty_list(
        self, client: TestClient, project_id: str
    ) -> None:
        response = client.get(f"/api/v1/projects/{project_id}/issues")
        assert response.status_code == 200
        assert response.json() == []

    def test_returns_issues_from_latest_completed_analysis(
        self, client: TestClient, project_id: str, settings: Settings
    ) -> None:
        _, seeded = seed_completed_analysis_with_issues(settings, project_id)

        response = client.get(f"/api/v1/projects/{project_id}/issues")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3

        # Most severe first: critical -> high -> medium
        assert data[0]["severity"] == "critical"
        assert data[0]["category"] == "integration"  # mapped from api_contract
        assert data[0]["status"] == "open"
        assert data[0]["projectId"] == project_id
        assert "suggestedFix" in data[0]

        assert data[1]["severity"] == "high"
        assert data[1]["category"] == "security"

        assert data[2]["severity"] == "medium"
        assert data[2]["category"] == "dependencies"
        assert data[2]["status"] == "resolved"

    def test_filter_by_category(
        self, client: TestClient, project_id: str, settings: Settings
    ) -> None:
        seed_completed_analysis_with_issues(settings, project_id)

        # Integration filter
        res = client.get(f"/api/v1/projects/{project_id}/issues?category=integration")
        assert res.status_code == 200
        assert len(res.json()) == 1
        assert res.json()[0]["category"] == "integration"

        # Security filter
        res = client.get(f"/api/v1/projects/{project_id}/issues?category=security")
        assert res.status_code == 200
        assert len(res.json()) == 1
        assert res.json()[0]["category"] == "security"

        # Dependencies filter
        res = client.get(f"/api/v1/projects/{project_id}/issues?category=dependencies")
        assert res.status_code == 200
        assert len(res.json()) == 1
        assert res.json()[0]["category"] == "dependencies"

    def test_filter_by_severity(
        self, client: TestClient, project_id: str, settings: Settings
    ) -> None:
        seed_completed_analysis_with_issues(settings, project_id)

        res = client.get(f"/api/v1/projects/{project_id}/issues?severity=critical")
        assert res.status_code == 200
        assert len(res.json()) == 1
        assert res.json()[0]["severity"] == "critical"

    def test_filter_by_status(
        self, client: TestClient, project_id: str, settings: Settings
    ) -> None:
        seed_completed_analysis_with_issues(settings, project_id)

        res = client.get(f"/api/v1/projects/{project_id}/issues?status=resolved")
        assert res.status_code == 200
        assert len(res.json()) == 1
        assert res.json()[0]["status"] == "resolved"

        res = client.get(f"/api/v1/projects/{project_id}/issues?status=open")
        assert res.status_code == 200
        assert len(res.json()) == 2

    def test_filter_by_query_string(
        self, client: TestClient, project_id: str, settings: Settings
    ) -> None:
        seed_completed_analysis_with_issues(settings, project_id)

        res = client.get(f"/api/v1/projects/{project_id}/issues?q=wildcard")
        assert res.status_code == 200
        assert len(res.json()) == 1
        issue = res.json()[0]
        assert "wildcard" in (issue["title"] + " " + issue["shortDescription"]).lower()


class TestSingleIssueAndPatch:
    def test_get_issue_by_id(self, client: TestClient, project_id: str, settings: Settings) -> None:
        _, seeded = seed_completed_analysis_with_issues(settings, project_id)
        target_issue_id = str(uuid.UUID(seeded[0]["id"]))

        res = client.get(f"/api/v1/projects/{project_id}/issues/{target_issue_id}")
        assert res.status_code == 200
        assert res.json()["id"] == target_issue_id
        assert res.json()["status"] == "open"

    def test_get_issue_not_found(self, client: TestClient, project_id: str) -> None:
        res = client.get(f"/api/v1/projects/{project_id}/issues/{MISSING_ID}")
        assert res.status_code == 404

    def test_patch_issue_status(
        self, client: TestClient, project_id: str, settings: Settings
    ) -> None:
        _, seeded = seed_completed_analysis_with_issues(settings, project_id)
        target_issue_id = str(uuid.UUID(seeded[0]["id"]))

        # Mark as resolved
        res = client.patch(
            f"/api/v1/projects/{project_id}/issues/{target_issue_id}",
            json={"status": "resolved"},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "resolved"

        # Verify persisted via GET
        check = client.get(f"/api/v1/projects/{project_id}/issues/{target_issue_id}")
        assert check.status_code == 200
        assert check.json()["status"] == "resolved"

        # Mark as ignored
        res = client.patch(
            f"/api/v1/projects/{project_id}/issues/{target_issue_id}",
            json={"status": "ignored"},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "ignored"

        # Invalid status returns 422
        res = client.patch(
            f"/api/v1/projects/{project_id}/issues/{target_issue_id}",
            json={"status": "invalid_status"},
        )
        assert res.status_code == 422

    def test_patch_issue_mismatched_project_returns_404(
        self, client: TestClient, project_id: str, settings: Settings
    ) -> None:
        _, seeded = seed_completed_analysis_with_issues(settings, project_id)
        target_issue_id = str(uuid.UUID(seeded[0]["id"]))

        other_project_response = client.post(
            "/api/v1/projects/upload",
            files={"file": ("app2.zip", make_zip(SAMPLE_TREE), "application/zip")},
        )
        other_project_id = str(other_project_response.json()["project"]["id"])

        res = client.patch(
            f"/api/v1/projects/{other_project_id}/issues/{target_issue_id}",
            json={"status": "resolved"},
        )
        assert res.status_code == 404
