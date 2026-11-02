"""Tests for one-step analysis endpoints (POST /api/v1/analyses, GET /api/v1/analyses/{id}/status)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_importer
from app.core.config import Settings
from app.services.project_service import RepoImporter
from tests.conftest import FakeGit

AppFactory = Callable[[Settings], FastAPI]

SAMPLE_TREE = {
    "package.json": json.dumps({"dependencies": {"react": "^18.3.1"}}),
    "src/App.tsx": "export default function App() { return null; }\n",
}


@pytest.fixture(autouse=True)
def do_not_run_the_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep queued analyses queued without background execution."""

    async def do_nothing(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr("app.api.routes.analyses._execute", do_nothing)


def client_with_git(
    settings: Settings, app_factory: AppFactory, git: FakeGit
) -> tuple[TestClient, FastAPI]:
    app = app_factory(settings)
    app.dependency_overrides[get_importer] = lambda: RepoImporter(settings, git_runner=git)
    return TestClient(app), app


class TestOneStepAnalysis:
    def test_invalid_github_url_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/analyses",
            json={"repoUrl": "not-a-valid-url", "branch": "main"},
        )
        assert response.status_code == 422

    def test_creates_project_and_queues_analysis(
        self, settings: Settings, app_factory: AppFactory
    ) -> None:
        test_client, _ = client_with_git(settings, app_factory, FakeGit(SAMPLE_TREE))
        repo_url = "https://github.com/org-test/repo-one-step"

        with test_client as client:
            response = client.post(
                "/api/v1/analyses",
                json={"repoUrl": repo_url, "branch": "main"},
            )
            assert response.status_code == 201
            data = response.json()
            assert "analysisId" in data
            assert "projectId" in data
            assert data["id"] == data["projectId"]
            assert data["status"] == "analyzing"
            assert data["repoUrl"] == repo_url
            assert len(data["steps"]) == 8
            assert data["steps"][0]["status"] == "running"
            assert data["steps"][1]["status"] == "pending"

            # Check status endpoint immediately returns running/pending
            status_res = client.get(f"/api/v1/analyses/{data['analysisId']}/status")
            assert status_res.status_code == 200
            status_data = status_res.json()
            assert status_data["id"] == data["analysisId"]
            assert status_data["projectId"] == data["projectId"]
            assert status_data["status"] == "running"
            assert status_data["progressPercent"] > 0

    def test_reuses_existing_project_for_same_canonical_url(
        self, settings: Settings, app_factory: AppFactory
    ) -> None:
        import sqlalchemy as sa

        test_client, _ = client_with_git(settings, app_factory, FakeGit(SAMPLE_TREE))
        repo_url = "https://github.com/org-test/reuse-test"

        with test_client as client:
            res1 = client.post("/api/v1/analyses", json={"repoUrl": repo_url, "branch": "main"})
            assert res1.status_code == 201
            proj_id1 = res1.json()["projectId"]
            analysis_id1 = res1.json()["analysisId"]

            # Second call while first is still pending/running: re-connects to existing active analysis
            res2 = client.post(
                "/api/v1/analyses",
                json={"repoUrl": f"{repo_url}.git", "branch": "main"},
            )
            assert res2.status_code == 201
            proj_id2 = res2.json()["projectId"]
            analysis_id2 = res2.json()["analysisId"]
            assert proj_id1 == proj_id2
            assert analysis_id1 == analysis_id2

            # Now mark the first analysis as completed (SUCCEEDED)
            engine = sa.create_engine(settings.database_url.replace("+aiosqlite", ""))
            try:
                with engine.begin() as conn:
                    conn.execute(
                        sa.text("UPDATE analyses SET status = 'succeeded' WHERE id = :id"),
                        {"id": analysis_id1.replace("-", "")},
                    )
            finally:
                engine.dispose()

            # Third call: now that previous run is terminal, a fresh analysis run is created
            res3 = client.post(
                "/api/v1/analyses",
                json={"repoUrl": repo_url, "branch": "main"},
            )
            assert res3.status_code == 201
            proj_id3 = res3.json()["projectId"]
            analysis_id3 = res3.json()["analysisId"]
            assert proj_id1 == proj_id3
            assert analysis_id3 != analysis_id1


class TestAnalysisStatus:
    def test_missing_analysis_returns_404(self, client: TestClient) -> None:
        missing_id = str(uuid.uuid4())
        response = client.get(f"/api/v1/analyses/{missing_id}/status")
        assert response.status_code == 404
