"""Tests for GET /api/v1/projects/{project_id}/deploy-checklist."""

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


class TestDeployChecklist:
    def test_missing_project_returns_404(self, client: TestClient) -> None:
        response = client.get(f"/api/v1/projects/{MISSING_ID}/deploy-checklist")
        assert response.status_code == 404

    def test_no_analysis_yet_returns_warn_status(self, client: TestClient, project_id: str) -> None:
        response = client.get(f"/api/v1/projects/{project_id}/deploy-checklist")
        assert response.status_code == 200
        items = response.json()
        assert len(items) == 4
        assert all(item["status"] == "warn" for item in items)
        ids = [i["id"] for i in items]
        assert "chk_env_secrets" in ids
        assert "chk_docker_healthcheck" in ids
        assert "chk_cors_strict" in ids
        assert "chk_db_pool" in ids

    def test_completed_analysis_evaluates_items(
        self, client: TestClient, project_id: str, settings: Settings
    ) -> None:
        engine = sa.create_engine(settings.database_url.replace("+aiosqlite", ""))
        analysis_id = str(uuid.uuid4()).replace("-", "")
        try:
            with engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO analyses (id, project_id, status, created_at, updated_at, completed_at, health_score, ai_explanations_available)"
                        " VALUES (:id, :project_id, :status, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 90, 0)"
                    ),
                    {
                        "id": analysis_id,
                        "project_id": project_id.replace("-", ""),
                        "status": AnalysisStatus.SUCCEEDED.value,
                    },
                )
                # Seed a critical CORS wildcard issue
                conn.execute(
                    sa.text(
                        "INSERT INTO issues (id, analysis_id, created_at, updated_at,"
                        " category, severity, status, title, description, detected_by,"
                        " confidence, fingerprint, file_path, line_start)"
                        " VALUES (:id, :analysis_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,"
                        " :category, :severity, :status, :title, :description, :detected_by,"
                        " :confidence, :fingerprint, :file_path, :line_start)"
                    ),
                    {
                        "id": str(uuid.uuid4()).replace("-", ""),
                        "analysis_id": analysis_id,
                        "category": IssueCategory.SECURITY.value,
                        "severity": Severity.CRITICAL.value,
                        "status": "open",
                        "title": "Unauthenticated CORS wildcard",
                        "description": "Allow_origins wildcard '*' permits open access.",
                        "detected_by": "MX-SEC-002",
                        "confidence": 1.0,
                        "fingerprint": "fp-cors",
                        "file_path": "backend/app/main.py",
                        "line_start": 18,
                    },
                )
        finally:
            engine.dispose()

        response = client.get(f"/api/v1/projects/{project_id}/deploy-checklist")
        assert response.status_code == 200
        items = response.json()
        item_map = {i["id"]: i for i in items}

        # CORS should fail due to the critical finding
        assert item_map["chk_cors_strict"]["status"] == "fail"
        # Others without findings should pass
        assert item_map["chk_env_secrets"]["status"] == "pass"
        assert item_map["chk_docker_healthcheck"]["status"] == "pass"
        assert item_map["chk_db_pool"]["status"] == "pass"
