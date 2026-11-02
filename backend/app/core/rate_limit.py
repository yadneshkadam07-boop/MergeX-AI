"""In-process fixed-window rate limiting.

Why this is hand-rolled rather than `slowapi`: as of FastAPI 0.143,
``include_router`` puts a single internal router object into ``app.routes``
instead of flattening the individual routes, so ``SlowAPIMiddleware`` cannot
find a route handler and **silently exempts every router-included endpoint** --
that is, the entire API. Its decorator path breaks the response instead. A
rate limiter that quietly stops limiting is worse than none, so MergeX owns
this code and tests it. See CLAUDE.md > Decisions.

Scope and limitations, stated plainly:

* Counters live in this process. Correct for a single instance; a multi-replica
  deployment needs a shared store (Redis) and should replace
  :class:`RateLimitMiddleware` rather than extend it.
* The window is a fixed window, not a sliding one, so a client may send up to
  ``2 * limit`` requests across a window boundary. That is an accepted
  trade-off for abuse protection on a small number of expensive endpoints.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

__all__ = [
    "EXEMPT_PATH_PREFIXES",
    "Decision",
    "FixedWindowLimiter",
    "RateLimitMiddleware",
    "client_key",
]

# Probes and API documentation are not abuse vectors, and throttling a health
# check makes a deployment look unhealthy under load.
EXEMPT_PATH_PREFIXES: tuple[str, ...] = (
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
)

# Upper bound on tracked clients, so a flood of unique source addresses cannot
# grow the counter map without limit.
_MAX_TRACKED_CLIENTS = 20_000

Clock = Callable[[], float]


@dataclass(slots=True)
class _Window:
    """A client's request count within the current window."""

    count: int
    reset_at: float


@dataclass(frozen=True, slots=True)
class Decision:
    """The outcome of one limiter check."""

    allowed: bool
    remaining: int
    reset_at: float

    def retry_after(self, now: float) -> int:
        """Seconds a client should wait, rounded up and never below one."""
        return max(1, int(self.reset_at - now) + 1)


class FixedWindowLimiter:
    """Counts requests per key in a fixed window.

    Separate from the middleware because two things need it: the blanket
    per-IP limit applied to every request, and the much tighter limit on the
    handful of endpoints that are expensive to serve. One implementation
    means one set of edge cases to get right.
    """

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: float,
        max_tracked_keys: int = _MAX_TRACKED_CLIENTS,
        clock: Clock = time.time,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")

        self.limit = limit
        self.window_seconds = float(window_seconds)
        self._max_tracked_keys = max_tracked_keys
        self._clock = clock
        self._windows: dict[str, _Window] = {}

    def hit(self, key: str) -> Decision:
        """Record a request against ``key`` and decide whether to allow it.

        Read-modify-write happens without an ``await``, so it is atomic with
        respect to the event loop and needs no lock.
        """
        now = self._clock()
        window = self._windows.get(key)

        if window is None or now >= window.reset_at:
            if len(self._windows) >= self._max_tracked_keys:
                self._prune(now)
            window = _Window(count=0, reset_at=now + self.window_seconds)
            self._windows[key] = window

        if window.count >= self.limit:
            return Decision(allowed=False, remaining=0, reset_at=window.reset_at)

        window.count += 1
        return Decision(
            allowed=True,
            remaining=self.limit - window.count,
            reset_at=window.reset_at,
        )

    def now(self) -> float:
        return self._clock()

    def reset(self) -> None:
        """Forget every window. Used by tests."""
        self._windows.clear()

    def _prune(self, now: float) -> None:
        """Drop expired windows; clear everything if all are still live."""
        expired = [key for key, window in self._windows.items() if now >= window.reset_at]
        for key in expired:
            del self._windows[key]
        if not expired:
            # Pathological case: more live clients than we will track. Dropping
            # the table resets limits rather than letting memory grow.
            self._windows.clear()


def client_key(request: Request, *, trust_proxy_headers: bool) -> str:
    """Identify the caller.

    ``X-Forwarded-For`` is honoured **only** behind a proxy that overwrites
    it; otherwise any client can forge a fresh identity per request and
    bypass every limit.
    """
    if trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            first_hop = forwarded.split(",")[0].strip()
            if first_hop:
                return first_hop
    client = request.client
    return client.host if client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Limit each client to ``limit`` requests per ``window_seconds``.

    Args:
        limit: Requests allowed per window. Must be positive.
        window_seconds: Window length in seconds.
        trust_proxy_headers: When True, take the client address from the
            leftmost ``X-Forwarded-For`` entry. Enable this **only** behind a
            proxy that overwrites the header (Render, Vercel, a load
            balancer); otherwise any client can forge a fresh identity per
            request and bypass the limit entirely.
        exempt_path_prefixes: Request paths starting with any of these are not
            counted and not limited.
        clock: Time source, injectable so tests do not have to sleep.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        limit: int,
        window_seconds: float = 60.0,
        trust_proxy_headers: bool = False,
        exempt_path_prefixes: Iterable[str] = EXEMPT_PATH_PREFIXES,
        clock: Clock = time.time,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")

        super().__init__(app)
        self.limit = limit
        self.window_seconds = float(window_seconds)
        self.trust_proxy_headers = trust_proxy_headers
        self.exempt_path_prefixes = tuple(exempt_path_prefixes)
        self._clock = clock
        self._limiter = FixedWindowLimiter(limit=limit, window_seconds=window_seconds, clock=clock)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path.startswith(self.exempt_path_prefixes):
            return await call_next(request)

        decision = self._limiter.hit(self._client_key(request))

        if not decision.allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "detail": (
                        f"Rate limit exceeded: {self.limit} requests per "
                        f"{int(self.window_seconds)} seconds."
                    ),
                },
                headers={
                    **self._headers(0, decision.reset_at),
                    "Retry-After": str(decision.retry_after(self._clock())),
                },
            )

        response = await call_next(request)
        response.headers.update(self._headers(decision.remaining, decision.reset_at))
        return response

    # -- internals ---------------------------------------------------------

    def _client_key(self, request: Request) -> str:
        return client_key(request, trust_proxy_headers=self.trust_proxy_headers)

    def _headers(self, remaining: int, reset_at: float) -> dict[str, str]:
        return {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(int(reset_at)),
        }
