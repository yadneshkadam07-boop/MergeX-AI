"""Shared pytest fixtures.

Two deliberate choices:

* **Tests never read the developer's ``.env``.** Every fixture builds an
  explicit ``Settings`` and injects it through dependency overrides, so
  results do not depend on the machine running them.
* **The database is file-backed SQLite in ``tmp_path``.** A file rather than
  ``:memory:`` because the app opens more than one connection and each
  in-memory connection would get its own empty database. SQLite rather than
  Postgres so the suite needs no running service; the models are written to be
  dialect-neutral (see ``app.models.base``), and
  ``test_migrations.py`` asserts that the migration matches the models.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import build_session_factory, create_engine
from app.main import create_app
from app.models import Base
from app.services.git_client import GitResult

SettingsFactory = Callable[..., Settings]

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture
def settings_factory(tmp_path: Path) -> SettingsFactory:
    """Build isolated ``Settings`` with a throwaway sandbox and database."""

    def _factory(**overrides: object) -> Settings:
        defaults: dict[str, object] = {
            "app_env": "local",
            "log_level": "WARNING",
            "workspace_dir": tmp_path / "workspace",
            "database_url": f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}",
            "gemini_api_key": None,
            "github_token": None,
            "rate_limit_per_minute": 10_000,
        }
        defaults.update(overrides)
        return Settings(**defaults)  # type: ignore[arg-type]

    return _factory


@pytest.fixture
def settings(settings_factory: SettingsFactory) -> Settings:
    return settings_factory()


@pytest.fixture
def db_schema(settings: Settings) -> None:
    """Create every table for this test.

    Synchronous on purpose: a sync fixture can be requested by both sync
    (``TestClient``) and async tests, whereas an async one cannot.
    """
    sync_url = settings.database_url.replace("+aiosqlite", "")
    engine = sa.create_engine(sync_url)
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()


@pytest.fixture
def app_factory(db_schema: None) -> Callable[[Settings], FastAPI]:
    """Build an app whose ``get_settings`` dependency is overridden."""

    def _factory(settings: Settings) -> FastAPI:
        application = create_app(settings)
        application.dependency_overrides[get_settings] = lambda: settings
        return application

    return _factory


@pytest.fixture
def client(settings: Settings, app_factory: Callable[[Settings], FastAPI]) -> Iterator[TestClient]:
    """Synchronous test client with lifespan events executed."""
    with TestClient(app_factory(settings)) as test_client:
        yield test_client


@pytest.fixture
async def session(settings: Settings, db_schema: None) -> AsyncGenerator[AsyncSession, None]:
    """A database session for testing services without going through HTTP."""
    engine = create_engine(settings)
    factory = build_session_factory(engine)
    try:
        async with factory() as db_session:
            yield db_session
    finally:
        await engine.dispose()


class FakeGit:
    """Stands in for the ``git`` binary.

    Lets the clone path be tested with no network and no git installed: a
    "clone" materialises a declared file tree, and ``rev-parse`` returns a
    fixed SHA. Failures are simulated by supplying a return code and stderr,
    which is how the error-translation paths get covered.
    """

    def __init__(
        self,
        tree: dict[str, str] | None = None,
        *,
        returncode: int = 0,
        stderr: str = "",
        head: str = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
    ) -> None:
        self.tree = tree if tree is not None else {"README.md": "# fixture\n"}
        self.returncode = returncode
        self.stderr = stderr
        self.head = head
        self.calls: list[list[str]] = []

    async def __call__(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        timeout: float,
    ) -> GitResult:
        command = list(args)
        self.calls.append(command)

        if "rev-parse" in command:
            return GitResult(returncode=0, stdout=f"{self.head}\n", stderr="")

        if self.returncode != 0:
            return GitResult(returncode=self.returncode, stdout="", stderr=self.stderr)

        if "clone" in command or "init" in command:
            self._materialise(Path(command[-1]))

        return GitResult(returncode=0, stdout="", stderr="")

    def _materialise(self, destination: Path) -> None:
        for relative, content in self.tree.items():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    @property
    def clone_command(self) -> list[str]:
        """The argv of the clone call, for asserting on hardening flags."""
        for command in self.calls:
            if "clone" in command:
                return command
        raise AssertionError(f"No clone was attempted; calls were {self.calls}")


@pytest.fixture
def fixture_repo() -> Callable[[str], Path]:
    """Resolve the path to one of the seeded-bug fixture repositories."""

    def _resolve(name: str) -> Path:
        path = FIXTURES_DIR / name
        if not path.is_dir():
            raise AssertionError(f"Fixture repository {name!r} is missing from {FIXTURES_DIR}")
        return path

    return _resolve


@pytest.fixture
def fixture_manifest() -> Callable[[str], dict[str, Any]]:
    """Load a fixture's ``expected_findings.json``.

    The manifest is the contract: it states what the extractors must find,
    where, and what they must *not* report. Tests assert against it rather
     than against values copied into the test file, so the fixture and its
    expectations cannot drift apart silently.
    """

    def _load(name: str) -> dict[str, Any]:
        path = FIXTURES_DIR / name / "expected_findings.json"
        if not path.is_file():
            raise AssertionError(f"Manifest missing for fixture {name!r}: {path}")
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return loaded

    return _load
