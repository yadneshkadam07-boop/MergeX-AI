"""The demo endpoint's limit, and the cleanup that keeps it from piling up.

`POST /projects/demo` is the one endpoint anyone on the internet can call
that does real work. Two things therefore have to hold: it cannot be looped,
and what it creates does not accumulate.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.enums import SourceType
from app.models.project import Project
from app.services.demo_cleanup import purge_expired_demos, run_demo_cleanup_loop

SettingsFactory = Callable[..., Settings]
AppFactory = Callable[[Settings], FastAPI]


@pytest.fixture(autouse=True)
def do_not_run_the_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests are about the limit and the rows, not the analysis."""

    async def do_nothing(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr("app.api.routes.analyses._execute", do_nothing)


def client_for(settings: Settings, app_factory: AppFactory) -> TestClient:
    return TestClient(app_factory(settings))


# ---------------------------------------------------------------------------
# The limit
# ---------------------------------------------------------------------------


class TestDemoRateLimit:
    def test_the_limit_is_enforced_per_address(
        self, settings_factory: SettingsFactory, app_factory: AppFactory
    ) -> None:
        # Disable per-minute and burst guards so the hourly cap is the only
        # one under test here.
        settings = settings_factory(
            demo_rate_limit_per_hour=3,
            demo_rate_limit_per_minute=1000,
            demo_burst_limit=1000,
            demo_burst_window_minutes=1,
        )
        with client_for(settings, app_factory) as client:
            accepted = [client.post("/api/v1/projects/demo").status_code for _ in range(3)]
            blocked = client.post("/api/v1/projects/demo")

        assert accepted == [201, 201, 201]
        assert blocked.status_code == 429

    def test_the_refusal_explains_itself(
        self, settings_factory: SettingsFactory, app_factory: AppFactory
    ) -> None:
        settings = settings_factory(
            demo_rate_limit_per_hour=1,
            demo_rate_limit_per_minute=1000,
            demo_burst_limit=1000,
            demo_burst_window_minutes=1,
        )
        with client_for(settings, app_factory) as client:
            client.post("/api/v1/projects/demo")
            blocked = client.post("/api/v1/projects/demo")

        body = blocked.json()
        assert body["error"] == "rate_limit_exceeded"
        assert "per hour" in body["detail"]
        # A client should be told when to come back, not left to guess.
        assert int(blocked.headers["Retry-After"]) > 0

    def test_it_is_tighter_than_the_blanket_limit(
        self, settings_factory: SettingsFactory, app_factory: AppFactory
    ) -> None:
        """The demo limit must bite first, or it is not a limit at all."""
        settings = settings_factory(rate_limit_per_minute=10_000, demo_rate_limit_per_hour=2)
        with client_for(settings, app_factory) as client:
            statuses = [client.post("/api/v1/projects/demo").status_code for _ in range(4)]

        assert statuses == [201, 201, 429, 429]

    def test_other_endpoints_are_unaffected(
        self, settings_factory: SettingsFactory, app_factory: AppFactory
    ) -> None:
        settings = settings_factory(demo_rate_limit_per_hour=1)
        with client_for(settings, app_factory) as client:
            client.post("/api/v1/projects/demo")
            assert client.post("/api/v1/projects/demo").status_code == 429

            # The demo window must not have consumed anyone else's budget.
            assert client.get("/api/v1/projects").status_code == 200
            assert client.get("/health").status_code == 200

    def test_a_forged_forwarded_header_cannot_reset_the_window(
        self, settings_factory: SettingsFactory, app_factory: AppFactory
    ) -> None:
        """With TRUST_PROXY_HEADERS off, the header is ignored entirely."""
        settings = settings_factory(demo_rate_limit_per_hour=1, trust_proxy_headers=False)
        with client_for(settings, app_factory) as client:
            client.post("/api/v1/projects/demo", headers={"X-Forwarded-For": "1.1.1.1"})
            second = client.post("/api/v1/projects/demo", headers={"X-Forwarded-For": "2.2.2.2"})

        assert second.status_code == 429

    def test_the_proxy_header_identifies_the_client_when_trusted(
        self, settings_factory: SettingsFactory, app_factory: AppFactory
    ) -> None:
        """On Render the platform overwrites the header, so it is the client."""
        settings = settings_factory(demo_rate_limit_per_hour=1, trust_proxy_headers=True)
        with client_for(settings, app_factory) as client:
            first = client.post("/api/v1/projects/demo", headers={"X-Forwarded-For": "1.1.1.1"})
            same = client.post("/api/v1/projects/demo", headers={"X-Forwarded-For": "1.1.1.1"})
            other = client.post("/api/v1/projects/demo", headers={"X-Forwarded-For": "2.2.2.2"})

        assert first.status_code == 201
        assert same.status_code == 429
        assert other.status_code == 201

    def test_two_apps_do_not_share_a_window(
        self, settings_factory: SettingsFactory, app_factory: AppFactory
    ) -> None:
        """The limiter is per-app state, not a module global."""
        settings = settings_factory(demo_rate_limit_per_hour=1)
        with client_for(settings, app_factory) as first:
            assert first.post("/api/v1/projects/demo").status_code == 201
        with client_for(settings, app_factory) as second:
            assert second.post("/api/v1/projects/demo").status_code == 201


class TestDemoProjectsAreMarked:
    def test_a_demo_project_is_flagged(self, client: TestClient, settings: Settings) -> None:
        project_id = client.post("/api/v1/projects/demo").json()["project"]["id"]

        engine = sa.create_engine(settings.database_url.replace("+aiosqlite", ""))
        try:
            with engine.connect() as connection:
                flag = connection.execute(
                    sa.text("SELECT is_demo FROM projects WHERE id = :id"),
                    {"id": project_id.replace("-", "")},
                ).scalar_one()
        finally:
            engine.dispose()

        assert bool(flag) is True

    def test_an_uploaded_project_is_not_flagged(
        self, client: TestClient, settings: Settings
    ) -> None:
        """Only the demo endpoint may create something deletable by a timer."""
        import io
        import zipfile

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("package.json", '{"dependencies":{"react":"^18.0.0"}}')

        response = client.post(
            "/api/v1/projects/upload",
            files={"file": ("app.zip", buffer.getvalue(), "application/zip")},
        )
        project_id = response.json()["project"]["id"]

        engine = sa.create_engine(settings.database_url.replace("+aiosqlite", ""))
        try:
            with engine.connect() as connection:
                flag = connection.execute(
                    sa.text("SELECT is_demo FROM projects WHERE id = :id"),
                    {"id": project_id.replace("-", "")},
                ).scalar_one()
        finally:
            engine.dispose()

        assert bool(flag) is False


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


async def make_project(
    session: AsyncSession,
    *,
    is_demo: bool,
    age_hours: float,
    archive: Path | None = None,
) -> Project:
    project = Project(
        id=uuid.uuid4(),
        name="demo" if is_demo else "kept",
        source_type=SourceType.ZIP,
        source_url=None,
        upload_path=str(archive) if archive else None,
        upload_filename="demo.zip",
        is_demo=is_demo,
        created_at=datetime.now(UTC) - timedelta(hours=age_hours),
    )
    session.add(project)
    await session.flush()
    return project


class TestPurgeExpiredDemos:
    async def test_an_expired_demo_is_deleted(self, session: AsyncSession) -> None:
        await make_project(session, is_demo=True, age_hours=25)

        result = await purge_expired_demos(session, retention_hours=24)

        assert result.projects_deleted == 1
        assert (await session.scalar(sa.select(sa.func.count()).select_from(Project))) == 0

    async def test_a_recent_demo_is_kept(self, session: AsyncSession) -> None:
        """Someone may still be looking at it."""
        await make_project(session, is_demo=True, age_hours=1)

        result = await purge_expired_demos(session, retention_hours=24)

        assert result.projects_deleted == 0
        assert (await session.scalar(sa.select(sa.func.count()).select_from(Project))) == 1

    async def test_a_real_project_is_never_deleted(self, session: AsyncSession) -> None:
        """However old it is. This is the important one."""
        await make_project(session, is_demo=False, age_hours=24 * 365)

        result = await purge_expired_demos(session, retention_hours=24)

        assert result.projects_deleted == 0
        assert (await session.scalar(sa.select(sa.func.count()).select_from(Project))) == 1

    async def test_only_the_expired_demos_go(self, session: AsyncSession) -> None:
        await make_project(session, is_demo=True, age_hours=48)
        await make_project(session, is_demo=True, age_hours=2)
        await make_project(session, is_demo=False, age_hours=48)

        result = await purge_expired_demos(session, retention_hours=24)

        assert result.projects_deleted == 1
        remaining = list(await session.scalars(sa.select(Project)))
        assert {project.name for project in remaining} == {"demo", "kept"}

    async def test_the_retained_archive_is_removed(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        """The row cascades; the file on disk does not."""
        archive = tmp_path / "demo.zip"
        archive.write_bytes(b"PK\x05\x06" + b"\x00" * 18)
        await make_project(session, is_demo=True, age_hours=25, archive=archive)

        result = await purge_expired_demos(session, retention_hours=24)

        assert result.archives_deleted == 1
        assert not archive.exists()

    async def test_a_missing_archive_is_not_an_error(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        await make_project(session, is_demo=True, age_hours=25, archive=tmp_path / "gone.zip")

        result = await purge_expired_demos(session, retention_hours=24)

        assert result.projects_deleted == 1
        assert result.archives_deleted == 0
        assert result.archives_failed == 0

    async def test_an_undeletable_archive_still_deletes_the_row(
        self, session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A leaked file is better than a row that can never be cleaned up."""
        archive = tmp_path / "locked.zip"
        archive.write_bytes(b"x")
        await make_project(session, is_demo=True, age_hours=25, archive=archive)

        def refuse(self: Path, **kwargs: object) -> None:
            raise OSError("in use by another process")

        monkeypatch.setattr(Path, "unlink", refuse)

        result = await purge_expired_demos(session, retention_hours=24)

        assert result.projects_deleted == 1
        assert result.archives_failed == 1

    async def test_the_analyses_go_with_the_project(self, session: AsyncSession) -> None:
        from app.models.analysis import Analysis
        from app.models.enums import AnalysisStatus

        project = await make_project(session, is_demo=True, age_hours=25)
        session.add(
            Analysis(
                id=uuid.uuid4(),
                project_id=project.id,
                status=AnalysisStatus.SUCCEEDED,
                health_score=46,
            )
        )
        await session.flush()

        await purge_expired_demos(session, retention_hours=24)
        await session.flush()

        assert (await session.scalar(sa.select(sa.func.count()).select_from(Analysis))) == 0

    async def test_an_empty_database_is_a_no_op(self, session: AsyncSession) -> None:
        result = await purge_expired_demos(session, retention_hours=24)

        assert result.did_anything is False

    async def test_the_cutoff_is_injectable(self, session: AsyncSession) -> None:
        """So expiry can be asserted without waiting a day."""
        await make_project(session, is_demo=True, age_hours=0)

        result = await purge_expired_demos(
            session, retention_hours=24, now=datetime.now(UTC) + timedelta(hours=25)
        )

        assert result.projects_deleted == 1

    async def test_stale_sandbox_dir_is_removed(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        import os
        import time

        sandbox = tmp_path / "import-stale123"
        sandbox.mkdir()
        (sandbox / "sample.txt").write_text("abandoned checkout")
        # Set mtime to 25 hours ago
        stale_time = time.time() - (25 * 3600)
        os.utime(sandbox, (stale_time, stale_time))

        result = await purge_expired_demos(session, retention_hours=24, workspace_dir=tmp_path)

        assert result.sandboxes_deleted == 1
        assert not sandbox.exists()

    async def test_recent_sandbox_dir_is_kept(self, session: AsyncSession, tmp_path: Path) -> None:
        sandbox = tmp_path / "import-active456"
        sandbox.mkdir()
        (sandbox / "active.txt").write_text("in progress")

        result = await purge_expired_demos(session, retention_hours=24, workspace_dir=tmp_path)

        assert result.sandboxes_deleted == 0
        assert sandbox.exists()


class TestCleanupLoop:
    async def test_it_purges_immediately_and_then_stops(
        self, session: AsyncSession, settings: Settings
    ) -> None:
        """Start-up should not wait an hour to clean up a restart's backlog."""
        import asyncio

        from app.core.database import build_session_factory, create_engine

        await make_project(session, is_demo=True, age_hours=100)
        await session.commit()

        engine = create_engine(settings)
        factory = build_session_factory(engine)
        stop = asyncio.Event()
        try:
            task = asyncio.create_task(run_demo_cleanup_loop(factory, settings, stop=stop))
            await asyncio.sleep(0.2)
            stop.set()
            await asyncio.wait_for(task, timeout=5)
        finally:
            await engine.dispose()

        assert (await session.scalar(sa.select(sa.func.count()).select_from(Project))) == 0

    async def test_a_failure_does_not_kill_the_loop(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cleanup falling over must never take the API down with it."""
        import asyncio

        calls = 0

        async def explode(*args: object, **kwargs: object) -> None:
            nonlocal calls
            calls += 1
            raise RuntimeError("the database is unreachable")

        monkeypatch.setattr("app.services.demo_cleanup.purge_expired_demos", explode)

        from app.core.database import build_session_factory, create_engine

        engine = create_engine(settings)
        factory = build_session_factory(engine)
        stop = asyncio.Event()
        try:
            task = asyncio.create_task(run_demo_cleanup_loop(factory, settings, stop=stop))
            await asyncio.sleep(0.2)
            stop.set()
            await asyncio.wait_for(task, timeout=5)
        finally:
            await engine.dispose()

        assert calls >= 1
        assert task.done() and task.exception() is None

    async def test_the_app_starts_and_stops_the_loop(
        self, settings: Settings, app_factory: AppFactory
    ) -> None:
        """A cancelled task at shutdown, not a warning about a pending one."""
        app = app_factory(settings)

        with TestClient(app):
            task = app.state.demo_cleanup_task
            assert not task.done()

        assert task.done()
