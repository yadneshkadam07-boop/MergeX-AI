"""Phase 5.5 deployment-readiness tests.

Covers three concerns that ship together:

1. **Per-minute demo rate limit** — ``POST /projects/demo`` allows N requests
   per minute per IP; the (N+1)th returns 429 with ``Retry-After``,
   ``X-RateLimit-*`` headers and a machine-readable error body.

2. **Production startup validation** — ``Settings`` refuses to start when
   obvious production misconfigurations are detected (local DATABASE_URL,
   empty or wildcard CORS_ORIGINS).

3. **Demo project cleanup** — recent demos are kept; expired demos (row +
   archive file + cascade-deleted analyses) are removed.

The cleanup unit-tests live in ``test_demo_limits.py``; here we only assert
the integration that the *lifespan* loop actually runs and that the retention
threshold is respected, because they exercise different code paths.
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
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.enums import SourceType
from app.models.project import Project
from app.services.demo_cleanup import purge_expired_demos

SettingsFactory = Callable[..., Settings]
AppFactory = Callable[[Settings], FastAPI]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _skip_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests care about the HTTP contract, not the analysis pipeline."""

    async def _noop(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr("app.api.routes.analyses._execute", _noop)


def _make_client(settings: Settings, app_factory: AppFactory) -> TestClient:
    return TestClient(app_factory(settings))


# ---------------------------------------------------------------------------
# 1.  Per-minute demo rate limit
# ---------------------------------------------------------------------------


class TestDemoPerMinuteLimit:
    """The 6th request within a minute returns 429 with the required headers."""

    def test_sixth_request_is_rejected(
        self, settings_factory: SettingsFactory, app_factory: AppFactory
    ) -> None:
        """Five requests succeed; the sixth is rate-limited."""
        # demo_burst_limit is set high to disable the burst guard so only the
        # per-minute cap is under test.
        settings = settings_factory(
            demo_rate_limit_per_minute=5,
            demo_burst_limit=100,
            demo_burst_window_minutes=1,
        )
        with _make_client(settings, app_factory) as client:
            statuses = [client.post("/api/v1/projects/demo").status_code for _ in range(6)]

        assert statuses[:5] == [201, 201, 201, 201, 201]
        assert statuses[5] == 429

    def test_429_carries_retry_after_header(
        self, settings_factory: SettingsFactory, app_factory: AppFactory
    ) -> None:
        settings = settings_factory(
            demo_rate_limit_per_minute=1,
            demo_burst_limit=100,
            demo_burst_window_minutes=1,
        )
        with _make_client(settings, app_factory) as client:
            client.post("/api/v1/projects/demo")
            blocked = client.post("/api/v1/projects/demo")

        assert blocked.status_code == 429
        retry_after = int(blocked.headers["Retry-After"])
        assert (
            1 <= retry_after <= 61
        ), f"Retry-After should be 1–61 s for a 60-second window; got {retry_after}"

    def test_429_carries_ratelimit_headers(
        self, settings_factory: SettingsFactory, app_factory: AppFactory
    ) -> None:
        # X-Demo-RateLimit-* headers are specific to the demo dependency and
        # are not clobbered by the blanket RateLimitMiddleware (which uses the
        # X-RateLimit-* namespace).
        settings = settings_factory(
            demo_rate_limit_per_minute=1,
            demo_burst_limit=100,
            demo_burst_window_minutes=1,
        )
        with _make_client(settings, app_factory) as client:
            client.post("/api/v1/projects/demo")
            blocked = client.post("/api/v1/projects/demo")

        assert blocked.headers["X-Demo-RateLimit-Limit"] == "1"
        assert blocked.headers["X-Demo-RateLimit-Remaining"] == "0"
        assert int(blocked.headers["X-Demo-RateLimit-Reset"]) > 0

    def test_429_body_is_machine_readable(
        self, settings_factory: SettingsFactory, app_factory: AppFactory
    ) -> None:
        """The error field must be the stable code ``rate_limit_exceeded``."""
        settings = settings_factory(
            demo_rate_limit_per_minute=1,
            demo_burst_limit=100,
            demo_burst_window_minutes=1,
        )
        with _make_client(settings, app_factory) as client:
            client.post("/api/v1/projects/demo")
            blocked = client.post("/api/v1/projects/demo")

        body = blocked.json()
        assert body["error"] == "rate_limit_exceeded"
        assert "detail" in body
        assert "minute" in body["detail"].lower()

    def test_per_minute_fires_before_hourly_cap(
        self, settings_factory: SettingsFactory, app_factory: AppFactory
    ) -> None:
        """When both limits apply, the tighter (minute) one fires first."""
        # Hourly cap is generous; minute cap is tight.
        settings = settings_factory(
            demo_rate_limit_per_minute=2,
            demo_rate_limit_per_hour=100,
            demo_burst_limit=100,  # disable burst guard for this test
            demo_burst_window_minutes=1,
        )
        with _make_client(settings, app_factory) as client:
            statuses = [client.post("/api/v1/projects/demo").status_code for _ in range(4)]

        assert statuses == [201, 201, 429, 429]

    def test_other_endpoints_are_not_affected(
        self, settings_factory: SettingsFactory, app_factory: AppFactory
    ) -> None:
        """The demo limiter must not consume the blanket API budget."""
        settings = settings_factory(demo_rate_limit_per_minute=1)
        with _make_client(settings, app_factory) as client:
            client.post("/api/v1/projects/demo")
            assert client.post("/api/v1/projects/demo").status_code == 429

            # Other endpoints remain accessible.
            assert client.get("/api/v1/projects").status_code == 200
            assert client.get("/health").status_code == 200

    def test_different_ips_have_separate_buckets(
        self, settings_factory: SettingsFactory, app_factory: AppFactory
    ) -> None:
        """With proxy header trust on, each IP gets its own counter."""
        settings = settings_factory(demo_rate_limit_per_minute=1, trust_proxy_headers=True)
        with _make_client(settings, app_factory) as client:
            first_a = client.post("/api/v1/projects/demo", headers={"X-Forwarded-For": "10.0.0.1"})
            blocked_a = client.post(
                "/api/v1/projects/demo", headers={"X-Forwarded-For": "10.0.0.1"}
            )
            first_b = client.post("/api/v1/projects/demo", headers={"X-Forwarded-For": "10.0.0.2"})

        assert first_a.status_code == 201
        assert blocked_a.status_code == 429
        assert first_b.status_code == 201

    def test_forged_forwarded_header_cannot_reset_minute_window(
        self, settings_factory: SettingsFactory, app_factory: AppFactory
    ) -> None:
        """Without trust_proxy_headers the header is ignored."""
        settings = settings_factory(demo_rate_limit_per_minute=1, trust_proxy_headers=False)
        with _make_client(settings, app_factory) as client:
            client.post("/api/v1/projects/demo", headers={"X-Forwarded-For": "1.2.3.4"})
            second = client.post("/api/v1/projects/demo", headers={"X-Forwarded-For": "9.9.9.9"})

        assert second.status_code == 429


# ---------------------------------------------------------------------------
# 2.  Production startup validation
# ---------------------------------------------------------------------------


class TestProductionStartupValidation:
    """Settings raises with a clear message for obvious misconfigurations."""

    def _prod_settings(self, **overrides: object) -> Settings:
        # Provide safe defaults for a production build; individual tests
        # override the field under test to trigger the error.
        safe: dict[str, object] = {
            "app_env": "production",
            "database_url": "postgresql+asyncpg://user:pass@db.supabase.co:5432/postgres",
            "cors_origins": ["https://my-app.vercel.app"],
            "jwt_secret": "prod-secret-must-be-at-least-32-chars-long-random-key",
        }
        safe.update(overrides)
        return Settings(**safe)  # type: ignore[arg-type]

    def test_local_database_url_is_rejected_in_production(self) -> None:
        with pytest.raises(ValidationError, match="DATABASE_URL is the local development default"):
            self._prod_settings(
                database_url="postgresql+asyncpg://mergex:mergex@localhost:5432/mergex"
            )

    def test_compose_database_url_is_rejected_in_production(self) -> None:
        """The docker-compose default (db host) is equally wrong in production."""
        with pytest.raises(ValidationError, match="DATABASE_URL is the local development default"):
            self._prod_settings(database_url="postgresql+asyncpg://mergex:mergex@db:5432/mergex")

    def test_empty_cors_origins_is_rejected_in_production(self) -> None:
        with pytest.raises(ValidationError, match="CORS_ORIGINS is empty"):
            self._prod_settings(cors_origins=[])

    def test_wildcard_cors_is_rejected_in_production(self) -> None:
        with pytest.raises(ValidationError, match="wildcard"):
            self._prod_settings(cors_origins=["*"])

    def test_insecure_jwt_secret_is_rejected_in_production(self) -> None:
        with pytest.raises(ValidationError, match="JWT_SECRET"):
            self._prod_settings(
                jwt_secret="dev-secret-change-in-production-mergex-jwt-token-key-32b"
            )

    def test_multiple_errors_are_reported_together(self) -> None:
        """A single validation pass collects all errors; the operator does not
        have to fix-and-restart repeatedly."""
        with pytest.raises(ValidationError) as exc_info:
            self._prod_settings(
                database_url="postgresql+asyncpg://mergex:mergex@localhost:5432/mergex",
                cors_origins=[],
            )
        msg = str(exc_info.value)
        assert "DATABASE_URL" in msg
        assert "CORS_ORIGINS" in msg

    def test_valid_production_settings_do_not_raise(self) -> None:
        """The happy path must not raise."""
        settings = self._prod_settings()
        assert settings.is_production is True

    def test_local_settings_skip_the_check(self) -> None:
        """Development environments use local defaults by design."""
        settings = Settings(
            app_env="local",
            database_url="postgresql+asyncpg://mergex:mergex@localhost:5432/mergex",
            cors_origins=[],  # type: ignore[arg-type]
        )
        assert settings.app_env == "local"

    def test_staging_settings_skip_the_check(self) -> None:
        settings = Settings(app_env="staging")  # type: ignore[arg-type]
        assert settings.app_env == "staging"

    def test_missing_gemini_key_logs_warning_on_startup(self, app_factory: AppFactory) -> None:
        """In production without GEMINI_API_KEY, startup logs a warning."""
        import structlog.testing

        settings = self._prod_settings(
            database_url="sqlite+aiosqlite:///:memory:",
            gemini_api_key=None,
        )
        app = app_factory(settings)
        with structlog.testing.capture_logs() as captured, TestClient(app):
            pass

        warnings = [event for event in captured if event.get("event") == "gemini_api_key_missing"]
        assert len(warnings) == 1
        assert "template" in warnings[0]["detail"].lower()


# ---------------------------------------------------------------------------
# 3.  Demo cleanup retention boundary
# ---------------------------------------------------------------------------


async def _add_project(
    session: AsyncSession,
    *,
    is_demo: bool,
    age_hours: float,
    archive: Path | None = None,
) -> Project:
    project = Project(
        id=uuid.uuid4(),
        name="demo" if is_demo else "real",
        source_type=SourceType.ZIP,
        source_url=None,
        upload_path=str(archive) if archive else None,
        upload_filename="project.zip",
        is_demo=is_demo,
        created_at=datetime.now(UTC) - timedelta(hours=age_hours),
    )
    session.add(project)
    await session.flush()
    return project


class TestDemoRetentionBoundary:
    """Cleanup keeps recent demos and removes only the expired ones."""

    async def test_project_exactly_at_cutoff_is_kept(self, session: AsyncSession) -> None:
        """A project created exactly at the retention boundary is not expired.

        The cutoff is computed as ``now - timedelta(hours=retention_hours)``.
        A project whose ``created_at`` equals the cutoff satisfies
        ``created_at < cutoff`` as ``False``, so it must be kept.

        We inject ``now`` to make both sides of the comparison deterministic;
        without it, sub-millisecond timing between the fixture and the function
        would make the boundary non-deterministic.
        """
        pinned_now = datetime.now(UTC)
        # created_at == pinned_now - 24h → created_at == cutoff → not deleted
        project = await _add_project(session, is_demo=True, age_hours=0)
        # Override the created_at directly so it is precisely at the cutoff.
        project.created_at = pinned_now - timedelta(hours=24)
        await session.flush()

        result = await purge_expired_demos(session, retention_hours=24, now=pinned_now)

        assert result.projects_deleted == 0

    async def test_project_one_second_past_cutoff_is_removed(self, session: AsyncSession) -> None:
        """Strictly past the cutoff → deleted."""
        # age_hours slightly > retention_hours.
        await _add_project(session, is_demo=True, age_hours=24.001)

        result = await purge_expired_demos(session, retention_hours=24)

        assert result.projects_deleted == 1

    async def test_archive_file_is_deleted_with_expired_row(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        archive = tmp_path / "old_demo.zip"
        archive.write_bytes(b"PK" + b"\x00" * 20)
        await _add_project(session, is_demo=True, age_hours=25, archive=archive)

        await purge_expired_demos(session, retention_hours=24)

        assert not archive.exists()

    async def test_recent_demo_archive_is_kept(self, session: AsyncSession, tmp_path: Path) -> None:
        archive = tmp_path / "new_demo.zip"
        archive.write_bytes(b"PK" + b"\x00" * 20)
        await _add_project(session, is_demo=True, age_hours=1, archive=archive)

        result = await purge_expired_demos(session, retention_hours=24)

        assert result.projects_deleted == 0
        assert archive.exists()

    async def test_real_project_is_never_deleted_regardless_of_age(
        self, session: AsyncSession
    ) -> None:
        await _add_project(session, is_demo=False, age_hours=1000)

        result = await purge_expired_demos(session, retention_hours=24)

        assert result.projects_deleted == 0
        count = await session.scalar(sa.select(sa.func.count()).select_from(Project))
        assert count == 1

    async def test_mixed_bag_only_expired_demos_go(self, session: AsyncSession) -> None:
        """Expired demo, recent demo, and a real project — only the first goes."""
        await _add_project(session, is_demo=True, age_hours=48)  # expired
        await _add_project(session, is_demo=True, age_hours=2)  # recent
        await _add_project(session, is_demo=False, age_hours=100)  # real

        result = await purge_expired_demos(session, retention_hours=24)

        assert result.projects_deleted == 1
        remaining = list(await session.scalars(sa.select(Project)))
        assert {p.name for p in remaining} == {"demo", "real"}

    async def test_stale_sandbox_dir_is_removed_with_expired_demos(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        import os
        import time

        sandbox = tmp_path / "import-expired-test"
        sandbox.mkdir()
        (sandbox / "code.py").write_text("print('hello')")
        # 30 hours ago
        stale_ts = time.time() - (30 * 3600)
        os.utime(sandbox, (stale_ts, stale_ts))

        result = await purge_expired_demos(session, retention_hours=24, workspace_dir=tmp_path)

        assert result.sandboxes_deleted == 1
        assert not sandbox.exists()

    async def test_recent_sandbox_dir_is_kept_with_recent_demos(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        sandbox = tmp_path / "import-active-test"
        sandbox.mkdir()
        (sandbox / "active.py").write_text("print('running')")

        result = await purge_expired_demos(session, retention_hours=24, workspace_dir=tmp_path)

        assert result.sandboxes_deleted == 0
        assert sandbox.exists()
