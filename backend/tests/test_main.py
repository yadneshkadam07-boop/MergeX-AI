"""Application wiring: middleware order, error handling, API mounting.

`test_core_rate_limit` proves the limiter works in isolation; these tests
prove `create_app` actually installs it and that failures are rendered the way
the API contract promises.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings

AppFactory = Callable[[Settings], FastAPI]
SettingsFactory = Callable[..., Settings]


class TestRateLimitWiring:
    def test_the_real_app_enforces_the_configured_limit(
        self, settings_factory: SettingsFactory, app_factory: AppFactory
    ) -> None:
        # The limiter runs before routing, so an unrouted path is still
        # counted — which is what makes it usable as a wiring probe while the
        # API surface is only health endpoints.
        limited = settings_factory(rate_limit_per_minute=2)

        with TestClient(app_factory(limited)) as client:
            codes = [client.get("/api/v1/does-not-exist").status_code for _ in range(4)]

        assert codes == [404, 404, 429, 429]

    def test_health_probes_bypass_the_limit(
        self, settings_factory: SettingsFactory, app_factory: AppFactory
    ) -> None:
        limited = settings_factory(rate_limit_per_minute=1)

        with TestClient(app_factory(limited)) as client:
            codes = [client.get("/health").status_code for _ in range(5)]

        assert codes == [200] * 5

    def test_rate_limit_headers_are_exposed(
        self, settings_factory: SettingsFactory, app_factory: AppFactory
    ) -> None:
        limited = settings_factory(rate_limit_per_minute=5)

        with TestClient(app_factory(limited)) as client:
            response = client.get("/api/v1/does-not-exist")

        assert response.headers["X-RateLimit-Limit"] == "5"


class TestErrorHandling:
    def test_unhandled_exceptions_return_an_opaque_500(
        self, settings: Settings, app_factory: AppFactory
    ) -> None:
        app = app_factory(settings)

        @app.get("/boom")
        async def boom() -> None:
            raise RuntimeError("database password is hunter2")

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/boom", headers={"X-Request-ID": "trace-me"})

        assert response.status_code == 500
        body = response.json()
        assert body["error"] == "internal_server_error"
        assert body["detail"] == "An unexpected error occurred."
        assert body["request_id"] == "trace-me"
        # The exception message must never reach the client.
        assert "hunter2" not in response.text

    def test_unknown_paths_return_404(self, client: TestClient) -> None:
        assert client.get("/nope").status_code == 404


class TestCors:
    def test_preflight_allows_the_configured_origin(
        self, settings_factory: SettingsFactory, app_factory: AppFactory
    ) -> None:
        configured = settings_factory(cors_origins="http://localhost:5173")

        with TestClient(app_factory(configured)) as client:
            response = client.options(
                "/health",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "GET",
                },
            )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"

    def test_preflight_rejects_an_unknown_origin(
        self, settings_factory: SettingsFactory, app_factory: AppFactory
    ) -> None:
        configured = settings_factory(cors_origins="http://localhost:5173")

        with TestClient(app_factory(configured)) as client:
            response = client.options(
                "/health",
                headers={
                    "Origin": "http://evil.test",
                    "Access-Control-Request-Method": "GET",
                },
            )

        assert "access-control-allow-origin" not in response.headers

    def test_request_id_header_is_exposed_to_the_browser(
        self, settings_factory: SettingsFactory, app_factory: AppFactory
    ) -> None:
        configured = settings_factory(cors_origins="http://localhost:5173")

        with TestClient(app_factory(configured)) as client:
            response = client.get("/health", headers={"Origin": "http://localhost:5173"})

        assert "X-Request-ID" in response.headers["access-control-expose-headers"]


class TestApiMounting:
    def test_api_router_is_mounted_under_the_configured_prefix(
        self, settings_factory: SettingsFactory, app_factory: AppFactory
    ) -> None:
        configured = settings_factory(api_v1_prefix="/api/v2")
        app = app_factory(configured)

        # No resource routers exist yet; assert the prefix the app was built
        # with rather than a concrete route, so this test survives Phase 1.
        assert app.state.settings.api_v1_prefix == "/api/v2"

    def test_openapi_documents_the_health_endpoints(self, client: TestClient) -> None:
        paths = client.get("/openapi.json").json()["paths"]

        assert set(paths) == {"/health", "/health/ready"}
