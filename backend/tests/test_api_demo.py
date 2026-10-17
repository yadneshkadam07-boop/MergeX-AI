"""The bundled demo project.

The demo exists so the product can be shown without a repository to hand, so
what matters is that it goes through the *same* import path as a real upload
and produces the findings the fixture manifest promises. A demo that took a
shortcut would be a demo of code nobody else runs.
"""

from __future__ import annotations

import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.services.demo import (
    DEMO_FIXTURE,
    DemoUnavailableError,
    demo_fixture_path,
    pack_demo_archive,
)


class TestPackDemoArchive:
    def test_the_fixture_is_packed_with_relative_paths(self, tmp_path: Path) -> None:
        destination = tmp_path / "demo.zip"

        count = pack_demo_archive(destination)

        with zipfile.ZipFile(destination) as archive:
            names = archive.namelist()
        assert count == len(names)
        assert "frontend/src/api/users.ts" in names
        assert all(not name.startswith("/") for name in names)
        assert all(".." not in name for name in names)

    def test_the_manifest_is_excluded(self, tmp_path: Path) -> None:
        """``expected_findings.json`` is the test contract, not project code."""
        destination = tmp_path / "demo.zip"

        pack_demo_archive(destination)

        with zipfile.ZipFile(destination) as archive:
            assert "expected_findings.json" not in archive.namelist()

    def test_an_unknown_fixture_is_reported_not_guessed(self, tmp_path: Path) -> None:
        with pytest.raises(DemoUnavailableError):
            pack_demo_archive(tmp_path / "demo.zip", name="no_such_fixture")

    def test_the_demo_fixture_exists(self) -> None:
        assert demo_fixture_path().is_dir()
        assert DEMO_FIXTURE == "react_fastapi_mismatch"


class TestDemoEndpoint:
    def test_it_creates_an_importable_project(self, client: TestClient) -> None:
        response = client.post("/api/v1/projects/demo")

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["project"]["source_type"] == "zip"
        assert body["project"]["import_error"] is None
        assert body["import_summary"]["file_count"] > 0

    def test_the_stack_is_detected(self, client: TestClient) -> None:
        body = client.post("/api/v1/projects/demo").json()

        stack = body["project"]["detected_stack"]
        assert "React" in stack["frontend"]
        assert "FastAPI" in stack["backend"]

    def test_each_call_creates_its_own_project(self, client: TestClient) -> None:
        """Two people demoing at once must not share a project."""
        first = client.post("/api/v1/projects/demo").json()["project"]["id"]
        second = client.post("/api/v1/projects/demo").json()["project"]["id"]

        assert first != second

    def test_the_demo_analyses_to_the_expected_findings(
        self, client: TestClient, fixture_manifest: Callable[[str], dict[str, Any]]
    ) -> None:
        """The demo must produce what the fixture manifest promises.

        ``TestClient`` runs the background task inline, so this is the whole
        pipeline: pack, import, analyse, persist, report.
        """
        project_id = client.post("/api/v1/projects/demo").json()["project"]["id"]
        analysis_id = client.post(f"/api/v1/projects/{project_id}/analyses", json={}).json()["id"]

        report = client.get(f"/api/v1/analyses/{analysis_id}/report").json()

        assert report["status"] == "succeeded"
        expected = {
            finding["rule_id"]
            for finding in fixture_manifest(DEMO_FIXTURE)["findings"]
            if finding.get("implemented")
        }
        assert expected <= {issue["rule_id"] for issue in report["issues"]}
        assert report["score"]["score"] < 100
        assert all(issue["explanation"] for issue in report["issues"])
