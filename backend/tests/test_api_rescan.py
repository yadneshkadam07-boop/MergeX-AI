"""Tests for POST /api/v1/projects/{project_id}/rescan."""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

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


class TestProjectRescan:
    def test_missing_project_returns_404(self, client: TestClient) -> None:
        response = client.post(f"/api/v1/projects/{MISSING_ID}/rescan")
        assert response.status_code == 404

    def test_rescan_queues_analysis_and_returns_project(
        self, client: TestClient, project_id: str
    ) -> None:
        response = client.post(f"/api/v1/projects/{project_id}/rescan")
        assert response.status_code == 200
        data = response.json()
        assert data["projectId"] == project_id
        assert data["status"] == "analyzing"
        assert "analysisId" in data
        assert len(data["steps"]) == 8
        assert data["steps"][0]["status"] == "running"

    def test_rescan_conflicts_if_analysis_already_active(
        self, client: TestClient, project_id: str
    ) -> None:
        # First rescan queues an analysis (which stays PENDING due to do_not_run_the_pipeline)
        res1 = client.post(f"/api/v1/projects/{project_id}/rescan")
        assert res1.status_code == 200

        # Second rescan attempts to run concurrently -> 409 Conflict
        res2 = client.post(f"/api/v1/projects/{project_id}/rescan")
        assert res2.status_code == 409
        assert "already running" in res2.json()["detail"].lower()
