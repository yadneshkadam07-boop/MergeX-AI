"""Project endpoints, end to end over HTTP.

The GitHub path uses an injected fake git runner, so no network is involved.
The ZIP path uses real archives, since that is where the interesting failure
modes live.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_importer
from app.core.config import Settings
from app.services.repo_importer import RepoImporter
from tests.conftest import FakeGit

AppFactory = Callable[[Settings], FastAPI]

SAMPLE_TREE = {
    "package.json": json.dumps({"dependencies": {"react": "^18.3.1"}}),
    "src/App.tsx": "export default function App() { return null; }\n",
    "backend/requirements.txt": "fastapi==0.111.0\n",
}


def client_with_git(
    settings: Settings, app_factory: AppFactory, git: FakeGit
) -> tuple[TestClient, FastAPI]:
    """A client whose importer uses ``git`` instead of the real binary."""
    app = app_factory(settings)
    app.dependency_overrides[get_importer] = lambda: RepoImporter(settings, git_runner=git)
    return TestClient(app), app


def make_zip(members: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()


class TestCreateFromGitHub:
    def test_imports_and_detects_the_stack(
        self, settings: Settings, app_factory: AppFactory
    ) -> None:
        test_client, _ = client_with_git(settings, app_factory, FakeGit(SAMPLE_TREE))

        with test_client as client:
            response = client.post(
                "/api/v1/projects",
                json={"source_url": "https://github.com/owner/repo"},
            )

        assert response.status_code == 201
        body = response.json()
        project = body["project"]
        assert project["name"] == "repo"
        assert project["source_type"] == "github"
        assert project["source_url"] == "https://github.com/owner/repo"
        assert project["detected_stack"]["frontend"] == ["React"]
        assert project["detected_stack"]["backend"] == ["FastAPI"]
        assert body["import_summary"]["file_count"] == 3

    def test_accepts_an_explicit_name_and_ref(
        self, settings: Settings, app_factory: AppFactory
    ) -> None:
        test_client, _ = client_with_git(settings, app_factory, FakeGit(SAMPLE_TREE))

        with test_client as client:
            response = client.post(
                "/api/v1/projects",
                json={
                    "source_url": "https://github.com/owner/repo",
                    "source_ref": "develop",
                    "name": "My Project",
                },
            )

        project = response.json()["project"]
        assert project["name"] == "My Project"
        assert project["source_ref"] == "develop"

    def test_records_the_commit_sha(self, settings: Settings, app_factory: AppFactory) -> None:
        test_client, _ = client_with_git(settings, app_factory, FakeGit(SAMPLE_TREE, head="b" * 40))

        with test_client as client:
            response = client.post(
                "/api/v1/projects", json={"source_url": "https://github.com/owner/repo"}
            )

        assert response.json()["project"]["commit_sha"] == "b" * 40

    @pytest.mark.parametrize(
        "url",
        [
            "https://gitlab.com/owner/repo",
            "http://169.254.169.254/latest/meta-data/",
            "not-a-url",
            "https://github.com/owner",
        ],
    )
    def test_rejects_unusable_urls_with_422(
        self, settings: Settings, app_factory: AppFactory, url: str
    ) -> None:
        """Validation happens before any clone is attempted."""
        git = FakeGit(SAMPLE_TREE)
        test_client, _ = client_with_git(settings, app_factory, git)

        with test_client as client:
            response = client.post("/api/v1/projects", json={"source_url": url})

        assert response.status_code == 422
        assert git.calls == [], "No git command should run for an invalid URL"

    def test_clone_failure_returns_422_and_persists_nothing(
        self, settings: Settings, app_factory: AppFactory
    ) -> None:
        git = FakeGit(returncode=128, stderr="fatal: repository not found")
        test_client, _ = client_with_git(settings, app_factory, git)

        with test_client as client:
            response = client.post(
                "/api/v1/projects", json={"source_url": "https://github.com/owner/nope"}
            )
            assert response.status_code == 422
            assert "private" in response.json()["detail"]

            # The failed import must not have left a project behind.
            assert client.get("/api/v1/projects").json()["total"] == 0

    def test_oversized_repository_returns_413(
        self, settings_factory: Callable[..., Settings], app_factory: AppFactory
    ) -> None:
        tight = settings_factory(max_file_count=1)
        test_client, _ = client_with_git(tight, app_factory, FakeGit(SAMPLE_TREE))

        with test_client as client:
            response = client.post(
                "/api/v1/projects", json={"source_url": "https://github.com/owner/repo"}
            )

        assert response.status_code == 413

    def test_rejects_unknown_fields(self, settings: Settings, app_factory: AppFactory) -> None:
        test_client, _ = client_with_git(settings, app_factory, FakeGit(SAMPLE_TREE))

        with test_client as client:
            response = client.post(
                "/api/v1/projects",
                json={"source_url": "https://github.com/owner/repo", "sneaky": True},
            )

        assert response.status_code == 422

    def test_no_working_tree_survives_the_request(
        self, settings: Settings, app_factory: AppFactory
    ) -> None:
        test_client, _ = client_with_git(settings, app_factory, FakeGit(SAMPLE_TREE))

        with test_client as client:
            client.post("/api/v1/projects", json={"source_url": "https://github.com/owner/repo"})

        assert list(settings.workspace_path.glob("import-*")) == []


class TestCreateFromZip:
    def test_imports_an_uploaded_archive(self, client: TestClient) -> None:
        payload = make_zip({f"myapp-main/{k}": v for k, v in SAMPLE_TREE.items()})

        response = client.post(
            "/api/v1/projects/upload",
            files={"file": ("myapp-main.zip", payload, "application/zip")},
        )

        assert response.status_code == 201
        project = response.json()["project"]
        assert project["source_type"] == "zip"
        assert project["source_url"] is None
        assert project["upload_filename"] == "myapp-main.zip"
        # "-main" is GitHub's branch suffix and is stripped from the name.
        assert project["name"] == "myapp"
        assert project["detected_stack"]["frontend"] == ["React"]

    def test_retains_the_archive_for_later_analyses(
        self, client: TestClient, settings: Settings
    ) -> None:
        payload = make_zip(SAMPLE_TREE)

        response = client.post(
            "/api/v1/projects/upload",
            files={"file": ("app.zip", payload, "application/zip")},
        )

        project_id = response.json()["project"]["id"]
        retained = settings.workspace_path / "uploads" / f"{project_id}.zip"
        assert retained.is_file()

    def test_rejects_a_non_zip_extension(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/projects/upload",
            files={"file": ("app.tar.gz", b"\x1f\x8b", "application/gzip")},
        )

        assert response.status_code == 422
        assert ".zip" in response.json()["detail"]

    def test_rejects_a_file_that_is_not_really_a_zip(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/projects/upload",
            files={"file": ("app.zip", b"this is not a zip", "application/zip")},
        )

        assert response.status_code == 422
        assert "ZIP" in response.json()["detail"]

    def test_discards_the_archive_when_extraction_fails(
        self, client: TestClient, settings: Settings
    ) -> None:
        """An archive we could not read must not be kept."""
        client.post(
            "/api/v1/projects/upload",
            files={"file": ("app.zip", b"not a zip at all", "application/zip")},
        )

        uploads = settings.workspace_path / "uploads"
        assert not uploads.exists() or list(uploads.glob("*.zip")) == []

    def test_rejects_an_oversized_upload(
        self, settings_factory: Callable[..., Settings], app_factory: AppFactory
    ) -> None:
        """The limit applies to the bytes uploaded, not the expanded size.

        Incompressible data is required here: 2 MB of a repeated character
        deflates to a few kilobytes and would never reach the upload limit.
        """
        tight = settings_factory(max_upload_size_mb=1)
        incompressible = os.urandom(2 * 1024 * 1024)

        with TestClient(app_factory(tight)) as client:
            response = client.post(
                "/api/v1/projects/upload",
                files={"file": ("big.zip", incompressible, "application/zip")},
            )

        assert response.status_code == 413
        assert "limit" in response.json()["detail"]

    def test_rejects_an_archive_with_no_source(self, client: TestClient) -> None:
        payload = make_zip({"node_modules/left-pad/index.js": "x"})

        response = client.post(
            "/api/v1/projects/upload",
            files={"file": ("junk.zip", payload, "application/zip")},
        )

        assert response.status_code == 422


class TestListAndRead:
    def _create(self, client: TestClient, name: str) -> str:
        response = client.post(
            "/api/v1/projects/upload",
            files={"file": (f"{name}.zip", make_zip(SAMPLE_TREE), "application/zip")},
            data={"name": name},
        )
        assert response.status_code == 201
        return str(response.json()["project"]["id"])

    def test_lists_projects_newest_first(self, client: TestClient) -> None:
        self._create(client, "first")
        self._create(client, "second")

        body = client.get("/api/v1/projects").json()

        assert body["total"] == 2
        assert [item["name"] for item in body["items"]] == ["second", "first"]

    def test_paginates(self, client: TestClient) -> None:
        for index in range(3):
            self._create(client, f"p{index}")

        body = client.get("/api/v1/projects", params={"limit": 2, "offset": 1}).json()

        assert body["total"] == 3
        assert len(body["items"]) == 2
        assert body["limit"] == 2
        assert body["offset"] == 1

    def test_rejects_an_oversized_page(self, client: TestClient) -> None:
        assert client.get("/api/v1/projects", params={"limit": 500}).status_code == 422

    def test_empty_list_is_valid(self, client: TestClient) -> None:
        body = client.get("/api/v1/projects").json()

        assert body == {"items": [], "total": 0, "limit": 20, "offset": 0}

    def test_reads_one_project(self, client: TestClient) -> None:
        project_id = self._create(client, "readable")

        response = client.get(f"/api/v1/projects/{project_id}")

        assert response.status_code == 200
        assert response.json()["id"] == project_id

    def test_unknown_id_returns_404(self, client: TestClient) -> None:
        response = client.get("/api/v1/projects/0ad4b1a6-0000-4000-8000-000000000000")

        assert response.status_code == 404

    def test_malformed_id_returns_422(self, client: TestClient) -> None:
        assert client.get("/api/v1/projects/not-a-uuid").status_code == 422


class TestUpdateAndDelete:
    def _create(self, client: TestClient) -> str:
        response = client.post(
            "/api/v1/projects/upload",
            files={"file": ("app.zip", make_zip(SAMPLE_TREE), "application/zip")},
        )
        return str(response.json()["project"]["id"])

    def test_renames_a_project(self, client: TestClient) -> None:
        project_id = self._create(client)

        response = client.patch(f"/api/v1/projects/{project_id}", json={"name": "Renamed"})

        assert response.status_code == 200
        assert response.json()["name"] == "Renamed"
        assert client.get(f"/api/v1/projects/{project_id}").json()["name"] == "Renamed"

    def test_rejects_an_empty_name(self, client: TestClient) -> None:
        project_id = self._create(client)

        assert client.patch(f"/api/v1/projects/{project_id}", json={"name": ""}).status_code == 422

    def test_cannot_change_the_source(self, client: TestClient) -> None:
        """Sources are immutable; changing one means a new import."""
        project_id = self._create(client)

        response = client.patch(
            f"/api/v1/projects/{project_id}",
            json={"name": "ok", "source_url": "https://github.com/owner/other"},
        )

        assert response.status_code == 422

    def test_deletes_a_project(self, client: TestClient) -> None:
        project_id = self._create(client)

        assert client.delete(f"/api/v1/projects/{project_id}").status_code == 204
        assert client.get(f"/api/v1/projects/{project_id}").status_code == 404

    def test_deleting_removes_the_retained_archive(
        self, client: TestClient, settings: Settings
    ) -> None:
        project_id = self._create(client)
        retained = settings.workspace_path / "uploads" / f"{project_id}.zip"
        assert retained.is_file()

        client.delete(f"/api/v1/projects/{project_id}")

        assert not retained.exists()

    def test_deleting_an_unknown_project_returns_404(self, client: TestClient) -> None:
        response = client.delete("/api/v1/projects/0ad4b1a6-0000-4000-8000-000000000000")

        assert response.status_code == 404


class TestReadiness:
    def test_database_is_reported_as_reachable(self, client: TestClient) -> None:
        body = client.get("/health/ready").json()

        assert body["components"]["database"]["status"] == "ok"
        assert body["status"] == "ok"

    def test_unreachable_database_makes_the_service_unready(
        self, settings_factory: Callable[..., Settings], app_factory: AppFactory
    ) -> None:
        broken = settings_factory(
            database_url="postgresql+asyncpg://nobody:nobody@127.0.0.1:1/absent"
        )

        with TestClient(app_factory(broken)) as client:
            response = client.get("/health/ready")

        assert response.status_code == 503
        body = response.json()
        assert body["components"]["database"]["status"] == "unavailable"

    def test_database_failure_detail_hides_the_password(
        self, settings_factory: Callable[..., Settings], app_factory: AppFactory
    ) -> None:
        broken = settings_factory(
            database_url="postgresql+asyncpg://nobody:sup3rs3cret@127.0.0.1:1/absent"
        )

        with TestClient(app_factory(broken)) as client:
            body = client.get("/health/ready").json()

        assert "sup3rs3cret" not in json.dumps(body)


def test_fixture_repo_imports_cleanly_as_a_zip(
    client: TestClient, fixture_repo: Callable[[str], Path]
) -> None:
    """The demo path: zip a seeded fixture, upload it, get its stack back."""
    root = fixture_repo("react_fastapi_mismatch")
    members = {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in root.rglob("*")
        if path.is_file()
    }

    response = client.post(
        "/api/v1/projects/upload",
        files={"file": ("mismatch.zip", make_zip(members), "application/zip")},
    )

    assert response.status_code == 201
    stack = response.json()["project"]["detected_stack"]
    assert stack["frontend"] == ["React"]
    assert stack["backend"] == ["FastAPI"]
    assert stack["frontend_roots"] == ["frontend"]
    assert stack["backend_roots"] == ["backend"]
