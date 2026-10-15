"""Shared pytest fixtures.

Tests never read the developer's ``.env``: every fixture builds an explicit
``Settings`` instance and injects it through FastAPI's dependency overrides,
so results do not depend on the machine running them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import create_app

SettingsFactory = Callable[..., Settings]


@pytest.fixture
def settings_factory(tmp_path: Path) -> SettingsFactory:
    """Build isolated ``Settings`` with a throwaway sandbox directory."""

    def _factory(**overrides: object) -> Settings:
        defaults: dict[str, object] = {
            "app_env": "local",
            "log_level": "WARNING",
            "workspace_dir": tmp_path / "workspace",
            "gemini_api_key": None,
            "github_token": None,
            "database_url": "postgresql+asyncpg://test:test@localhost:5432/test",
            "rate_limit_per_minute": 10_000,
        }
        defaults.update(overrides)
        return Settings(**defaults)  # type: ignore[arg-type]

    return _factory


@pytest.fixture
def settings(settings_factory: SettingsFactory) -> Settings:
    return settings_factory()


@pytest.fixture
def app_factory() -> Callable[[Settings], FastAPI]:
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
