"""Rate limiting behaviour.

These tests exist because the library MergeX previously used (`slowapi`)
silently stopped enforcing anything against FastAPI 0.143 — the failure mode
was a 200 response, not an error. Enforcement is asserted here directly so a
regression cannot hide again.
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.core.rate_limit import FixedWindowLimiter, RateLimitMiddleware


class FakeClock:
    """Manually advanced time source, so tests never sleep."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def build_app(
    *,
    limit: int = 3,
    window_seconds: float = 60.0,
    trust_proxy_headers: bool = False,
    clock: FakeClock | None = None,
) -> FastAPI:
    """An app shaped like the real one: the route arrives via `include_router`."""
    router = APIRouter()

    @router.get("/thing")
    async def thing() -> dict[str, str]:
        return {"ok": "yes"}

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.add_middleware(
        RateLimitMiddleware,
        limit=limit,
        window_seconds=window_seconds,
        trust_proxy_headers=trust_proxy_headers,
        clock=clock or FakeClock(),
    )
    return app


class TestEnforcement:
    def test_requests_within_the_limit_succeed(self) -> None:
        with TestClient(build_app(limit=3)) as client:
            codes = [client.get("/api/v1/thing").status_code for _ in range(3)]

        assert codes == [200, 200, 200]

    def test_requests_beyond_the_limit_are_rejected(self) -> None:
        with TestClient(build_app(limit=3)) as client:
            codes = [client.get("/api/v1/thing").status_code for _ in range(6)]

        assert codes == [200, 200, 200, 429, 429, 429]

    def test_limit_applies_to_router_included_routes(self) -> None:
        """The exact case the previous library got wrong."""
        with TestClient(build_app(limit=1)) as client:
            assert client.get("/api/v1/thing").status_code == 200
            assert client.get("/api/v1/thing").status_code == 429

    def test_rejection_body_is_structured(self) -> None:
        with TestClient(build_app(limit=1)) as client:
            client.get("/api/v1/thing")
            response = client.get("/api/v1/thing")

        assert response.status_code == 429
        body = response.json()
        assert body["error"] == "rate_limit_exceeded"
        assert "1 requests per 60 seconds" in body["detail"]

    def test_counter_resets_after_the_window(self) -> None:
        clock = FakeClock()
        with TestClient(build_app(limit=2, clock=clock)) as client:
            assert client.get("/api/v1/thing").status_code == 200
            assert client.get("/api/v1/thing").status_code == 200
            assert client.get("/api/v1/thing").status_code == 429

            clock.advance(60.0)

            assert client.get("/api/v1/thing").status_code == 200

    def test_partial_window_does_not_reset(self) -> None:
        clock = FakeClock()
        with TestClient(build_app(limit=1, clock=clock)) as client:
            assert client.get("/api/v1/thing").status_code == 200
            clock.advance(59.0)
            assert client.get("/api/v1/thing").status_code == 429


class TestHeaders:
    def test_remaining_counts_down(self) -> None:
        with TestClient(build_app(limit=3)) as client:
            first = client.get("/api/v1/thing")
            second = client.get("/api/v1/thing")

        assert first.headers["X-RateLimit-Limit"] == "3"
        assert first.headers["X-RateLimit-Remaining"] == "2"
        assert second.headers["X-RateLimit-Remaining"] == "1"

    def test_rejection_reports_zero_remaining_and_retry_after(self) -> None:
        clock = FakeClock()
        with TestClient(build_app(limit=1, clock=clock)) as client:
            client.get("/api/v1/thing")
            response = client.get("/api/v1/thing")

        assert response.headers["X-RateLimit-Remaining"] == "0"
        assert 1 <= int(response.headers["Retry-After"]) <= 61

    def test_reset_is_a_unix_timestamp_in_the_future(self) -> None:
        clock = FakeClock(start=1_000_000.0)
        with TestClient(build_app(limit=2, clock=clock)) as client:
            response = client.get("/api/v1/thing")

        assert int(response.headers["X-RateLimit-Reset"]) == 1_000_060


class TestExemptions:
    def test_health_is_not_rate_limited(self) -> None:
        app = build_app(limit=1)

        @app.get("/health")
        async def health() -> dict[str, str]:
            return {"status": "ok"}

        with TestClient(app) as client:
            codes = [client.get("/health").status_code for _ in range(10)]

        assert codes == [200] * 10

    def test_openapi_is_not_rate_limited(self) -> None:
        with TestClient(build_app(limit=1)) as client:
            codes = [client.get("/openapi.json").status_code for _ in range(5)]

        assert codes == [200] * 5

    def test_exempt_requests_do_not_consume_the_budget(self) -> None:
        with TestClient(build_app(limit=2)) as client:
            for _ in range(5):
                client.get("/openapi.json")
            codes = [client.get("/api/v1/thing").status_code for _ in range(3)]

        assert codes == [200, 200, 429]


class TestClientIdentity:
    def test_forwarded_header_is_ignored_by_default(self) -> None:
        """Without a trusted proxy, a forged header must not mint a new bucket."""
        with TestClient(build_app(limit=1)) as client:
            assert client.get("/api/v1/thing").status_code == 200
            spoofed = client.get("/api/v1/thing", headers={"X-Forwarded-For": "9.9.9.9"})

        assert spoofed.status_code == 429

    def test_forwarded_header_separates_clients_when_trusted(self) -> None:
        with TestClient(build_app(limit=1, trust_proxy_headers=True)) as client:
            first = client.get("/api/v1/thing", headers={"X-Forwarded-For": "1.1.1.1"})
            second = client.get("/api/v1/thing", headers={"X-Forwarded-For": "2.2.2.2"})
            repeat = client.get("/api/v1/thing", headers={"X-Forwarded-For": "1.1.1.1"})

        assert first.status_code == 200
        assert second.status_code == 200
        assert repeat.status_code == 429

    def test_only_the_leftmost_forwarded_hop_is_used(self) -> None:
        with TestClient(build_app(limit=1, trust_proxy_headers=True)) as client:
            client.get("/api/v1/thing", headers={"X-Forwarded-For": "1.1.1.1, 10.0.0.1"})
            # Same origin client, different intermediate hop: still one bucket.
            response = client.get("/api/v1/thing", headers={"X-Forwarded-For": "1.1.1.1, 10.0.0.9"})

        assert response.status_code == 429


class TestConstruction:
    @pytest.mark.parametrize("limit", [0, -1])
    def test_rejects_a_nonpositive_limit(self, limit: int) -> None:
        with pytest.raises(ValueError, match="limit must be at least 1"):
            RateLimitMiddleware(FastAPI(), limit=limit)

    @pytest.mark.parametrize("window", [0.0, -5.0])
    def test_rejects_a_nonpositive_window(self, window: float) -> None:
        with pytest.raises(ValueError, match="window_seconds must be positive"):
            RateLimitMiddleware(FastAPI(), limit=10, window_seconds=window)


class TestMemoryBounds:
    """Asserted on the limiter, which is where the window table lives."""

    def test_expired_windows_are_pruned(self) -> None:
        clock = FakeClock()
        limiter = FixedWindowLimiter(limit=5, window_seconds=60.0, clock=clock)

        for index in range(100):
            limiter.hit(f"client-{index}")
        assert len(limiter._windows) == 100

        clock.advance(61.0)
        limiter._prune(clock())

        assert limiter._windows == {}

    def test_live_windows_are_cleared_only_as_a_last_resort(self) -> None:
        clock = FakeClock()
        limiter = FixedWindowLimiter(limit=5, window_seconds=60.0, clock=clock)

        limiter.hit("a")
        limiter.hit("b")
        # Nothing has expired, so pruning falls back to dropping the table.
        limiter._prune(clock())

        assert limiter._windows == {}

    def test_the_table_is_capped(self) -> None:
        """A flood of unique addresses must not grow the map without limit."""
        clock = FakeClock()
        limiter = FixedWindowLimiter(limit=5, window_seconds=60.0, max_tracked_keys=10, clock=clock)

        for index in range(25):
            limiter.hit(f"client-{index}")

        assert len(limiter._windows) <= 10
