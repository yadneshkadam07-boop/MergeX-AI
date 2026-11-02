"""Tests for GET /api/v1/projects/{project_id}/report."""

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

SAMPLE_TREE = {
    "package.json": json.dumps({"dependencies": {"react": "^18.3.1"}}),
    "backend/requirements.txt": "fastapi==0.111.0\n",
}
MISSING_ID = "0ad4b1a6-0000-4000-8000-000000000000"


def make_zip(members: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()


@pytest.fixture
def project_id(client: TestClient) -> str:
    response = client.post(
        "/api/v1/projects/upload",
        files={"file": ("app.zip", make_zip(SAMPLE_TREE), "application/zip")},
    )
    assert response.status_code == 201
    return str(response.json()["project"]["id"])


def seed_completed_analysis(settings: Settings, project_id: str) -> str:
    engine = sa.create_engine(settings.database_url.replace("+aiosqlite", ""))
    analysis_id = str(uuid.uuid4()).replace("-", "")
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO analyses (id, project_id, status, created_at, updated_at, completed_at, health_score, ai_explanations_available)"
                    " VALUES (:id, :project_id, :status, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 82, 0)"
                ),
                {
                    "id": analysis_id,
                    "project_id": project_id.replace("-", ""),
                    "status": AnalysisStatus.SUCCEEDED.value,
                },
            )
            conn.execute(
                sa.text(
                    "INSERT INTO issues (id, analysis_id, created_at, updated_at,"
                    " category, severity, status, title, description, detected_by,"
                    " confidence, fingerprint, file_path, line_start, suggested_fix)"
                    " VALUES (:id, :analysis_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,"
                    " :category, :severity, :status, :title, :description, :detected_by,"
                    " :confidence, :fingerprint, :file_path, :line_start, :suggested_fix)"
                ),
                {
                    "id": str(uuid.uuid4()).replace("-", ""),
                    "analysis_id": analysis_id,
                    "category": IssueCategory.SECURITY.value,
                    "severity": Severity.HIGH.value,
                    "status": "open",
                    "title": "Open CORS policy",
                    "description": "Wildcard access permitted on mutating routes.",
                    "detected_by": "MX-SEC-001",
                    "confidence": 0.9,
                    "fingerprint": "fp-sec-1",
                    "file_path": "backend/app/main.py",
                    "line_start": 20,
                    "suggested_fix": "Restrict allow_origins to known frontend domains.",
                },
            )
    finally:
        engine.dispose()
    return analysis_id


class TestProjectReport:
    def test_missing_project_returns_404(self, client: TestClient) -> None:
        response = client.get(f"/api/v1/projects/{MISSING_ID}/report")
        assert response.status_code == 404

    def test_project_with_no_completed_analysis_returns_empty_sections(
        self, client: TestClient, project_id: str
    ) -> None:
        response = client.get(f"/api/v1/projects/{project_id}/report")
        assert response.status_code == 200
        data = response.json()
        assert "generatedAt" in data
        assert data["sections"] == []

    def test_project_with_completed_analysis_returns_markdown_report(
        self, client: TestClient, project_id: str, settings: Settings
    ) -> None:
        seed_completed_analysis(settings, project_id)

        response = client.get(f"/api/v1/projects/{project_id}/report")
        assert response.status_code == 200
        data = response.json()
        assert "generatedAt" in data
        assert len(data["sections"]) == 4

        section_ids = [s["id"] for s in data["sections"]]
        assert "sec_exec_summary" in section_ids
        assert "sec_findings_by_category" in section_ids
        assert "sec_critical_findings" in section_ids
        assert "sec_recommended_fixes" in section_ids

        # Verify executive summary mentions health score
        exec_sec = next(s for s in data["sections"] if s["id"] == "sec_exec_summary")
        assert "82/100" in exec_sec["markdown"]
