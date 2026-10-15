"""Health endpoint contract.

Phase 0's acceptance criterion: the health endpoint returns 200.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import __version__
from app.core.config import Settings

AppFactory = Callable[[Settings], FastAPI]


def test_liveness_returns_200(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "MergeX AI"
    assert body["version"] == __version__
    assert body["environment"] == "local"
    assert body["uptime_seconds"] >= 0


def test_liveness_echoes_request_id(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "abc123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "abc123"


def test_liveness_generates_request_id_when_absent(client: TestClient) -> None:
    response = client.get("/health")

    assert response.headers["X-Request-ID"]


def test_readiness_ok_when_workspace_writable(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["components"]["workspace"]["status"] == "ok"


def test_readiness_reports_gemini_not_configured(client: TestClient) -> None:
    body = client.get("/health/ready").json()

    gemini = body["components"]["gemini"]
    assert gemini["status"] == "not_configured"
    assert "GEMINI_API_KEY" in gemini["detail"]
    # A missing key must not make the service unready: deterministic analysis
    # is the product; AI explanations are an enhancement.
    assert body["status"] == "ok"


def test_readiness_reports_gemini_ok_when_key_present(
    settings_factory: Callable[..., Settings], app_factory: AppFactory
) -> None:
    configured = settings_factory(gemini_api_key="test-key")

    with TestClient(app_factory(configured)) as client:
        body = client.get("/health/ready").json()

    assert body["components"]["gemini"]["status"] == "ok"


def test_readiness_unavailable_when_workspace_unwritable(
    settings_factory: Callable[..., Settings], app_factory: AppFactory
) -> None:
    # A regular file where the sandbox directory should be: mkdir must fail.
    blocked = settings_factory()
    blocker = blocked.workspace_path.parent
    blocker.mkdir(parents=True, exist_ok=True)
    blocked.workspace_path.write_text("not a directory", encoding="utf-8")

    with TestClient(app_factory(blocked)) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["components"]["workspace"]["status"] == "unavailable"


def test_openapi_schema_is_served(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "MergeX AI"
    assert "/health" in schema["paths"]
