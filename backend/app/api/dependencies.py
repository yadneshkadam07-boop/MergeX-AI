"""Shared FastAPI dependencies.

The database session is created per request from the factory held on
``app.state``, so a test can swap in a SQLite engine by building the app with
different settings rather than by monkey-patching a module global.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import decode_access_token
from app.core.config import Settings, get_settings
from app.core.database import SessionFactory
from app.core.rate_limit import FixedWindowLimiter, client_key
from app.models.user import User
from app.schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.services.repo_importer import RepoImporter

DEFAULT_USER_ID = uuid.UUID("00000000-0000-4000-a000-000000000001")

__all__ = [
    "AuthRateLimitDep",
    "CurrentUserDep",
    "DEFAULT_USER_ID",
    "DemoRateLimitDep",
    "ImporterDep",
    "Pagination",
    "PaginationDep",
    "SessionDep",
    "SettingsDep",
    "get_current_user",
    "get_session",
]


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped session, committing on success.

    A handler that raises leaves the transaction rolled back, so a failed
    request cannot half-write a project row.
    """
    factory: SessionFactory | None = getattr(request.app.state, "session_factory", None)
    if factory is None:  # pragma: no cover - misconfiguration, not a code path
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not configured.",
        )

    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


class Pagination:
    """Validated ``limit``/``offset`` pair."""

    def __init__(
        self,
        limit: Annotated[
            int,
            Query(ge=1, le=MAX_PAGE_SIZE, description="Maximum rows to return."),
        ] = DEFAULT_PAGE_SIZE,
        offset: Annotated[int, Query(ge=0, description="Rows to skip.")] = 0,
    ) -> None:
        self.limit = limit
        self.offset = offset


def get_importer(settings: Annotated[Settings, Depends(get_settings)]) -> RepoImporter:
    """Build the repository importer for this request."""
    return RepoImporter(settings)


async def enforce_demo_rate_limit(request: Request) -> None:
    """Apply the demo endpoint's own, much tighter per-IP limits.

    Three limiters are stacked, checked from tightest to most permissive so
    the most informative error message reaches the client first:

    1. **Per-minute cap** (``demo_minute_limiter``): 5 requests per minute.
       The primary abuse barrier; stops a loop cold within 60 seconds.
    2. **Burst guard** (``demo_burst_limiter``): 2 requests per 10 minutes.
       Prevents a client from emptying the hourly budget in seconds while
       still allowing a person to click "Load demo" twice in quick succession.
    3. **Hourly cap** (``demo_limiter``): configurable via
       ``DEMO_RATE_LIMIT_PER_HOUR`` (default 5/h). A backstop for sustained
       low-rate abuse.

    All three are held on ``app.state`` rather than in a module global so
    tests that build several apps with different settings do not share window
    tables.
    """
    settings: Settings = request.app.state.settings
    key = client_key(request, trust_proxy_headers=settings.trust_proxy_headers)

    # --- 1. per-minute cap (primary barrier) ----------------------------------
    minute_limiter: FixedWindowLimiter | None = getattr(
        request.app.state, "demo_minute_limiter", None
    )
    if minute_limiter is not None:
        minute = minute_limiter.hit(key)
        if not minute.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"The demo endpoint allows {minute_limiter.limit} requests per minute "
                    f"per address. Please wait before trying again."
                ),
                headers={
                    "Retry-After": str(minute.retry_after(minute_limiter.now())),
                    "X-Demo-RateLimit-Limit": str(minute_limiter.limit),
                    "X-Demo-RateLimit-Remaining": "0",
                    "X-Demo-RateLimit-Reset": str(int(minute.reset_at)),
                },
            )

    # --- 2. burst guard -------------------------------------------------------
    burst_limiter: FixedWindowLimiter | None = getattr(
        request.app.state, "demo_burst_limiter", None
    )
    if burst_limiter is not None:
        burst = burst_limiter.hit(key)
        if not burst.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"The demo can be started {burst_limiter.limit} times per "
                    f"{int(burst_limiter.window_seconds // 60)} minutes from one address. "
                    f"Please wait before trying again."
                ),
                headers={
                    "Retry-After": str(burst.retry_after(burst_limiter.now())),
                    "X-Demo-RateLimit-Limit": str(burst_limiter.limit),
                    "X-Demo-RateLimit-Remaining": "0",
                    "X-Demo-RateLimit-Reset": str(int(burst.reset_at)),
                },
            )

    # --- 3. hourly cap --------------------------------------------------------
    limiter: FixedWindowLimiter | None = getattr(request.app.state, "demo_limiter", None)
    if limiter is None:  # pragma: no cover - misconfiguration, not a code path
        return

    decision = limiter.hit(key)
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"The demo can be started {limiter.limit} times per hour from one "
                f"address. Import your own repository, or try again shortly."
            ),
            headers={
                "Retry-After": str(decision.retry_after(limiter.now())),
                "X-Demo-RateLimit-Limit": str(limiter.limit),
                "X-Demo-RateLimit-Remaining": "0",
                "X-Demo-RateLimit-Reset": str(int(decision.reset_at)),
            },
        )


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
PaginationDep = Annotated[Pagination, Depends()]
ImporterDep = Annotated[RepoImporter, Depends(get_importer)]
DemoRateLimitDep = Annotated[None, Depends(enforce_demo_rate_limit)]


async def enforce_auth_rate_limit(request: Request) -> None:
    """Rate limit authentication endpoints (register and token) to protect against brute-force."""
    settings: Settings = request.app.state.settings
    key = client_key(request, trust_proxy_headers=settings.trust_proxy_headers)
    limiter: FixedWindowLimiter | None = getattr(request.app.state, "auth_limiter", None)
    if limiter is not None:
        decision = limiter.hit(key)
        if not decision.allowed:
            wait_s = int(decision.retry_after(limiter.now()))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many authentication attempts. Please wait {wait_s} seconds.",
                headers={
                    "Retry-After": str(decision.retry_after(limiter.now())),
                    "X-RateLimit-Limit": str(limiter.limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(decision.reset_at)),
                },
            )


AuthRateLimitDep = Annotated[None, Depends(enforce_auth_rate_limit)]


async def get_current_user(
    request: Request,
    session: SessionDep,
    token_query: Annotated[str | None, Query(alias="token")] = None,
) -> User:
    """Resolve the authenticated User from Bearer token or SSE query param.

    If unauthenticated:
    - Raises 401 Unauthorized in production or when allow_anonymous_user is False.
    - If allow_anonymous_user is True (e.g. headless unit tests), falls back to the default user.
    """
    settings: Settings = request.app.state.settings
    auth_header = request.headers.get("Authorization")
    token: str | None = None

    if auth_header:
        parts = auth_header.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization header format. Expected Bearer <token>.",
                headers={"WWW-Authenticate": "Bearer"},
            )
    elif token_query:
        token = token_query.strip() or None

    if not token:
        if settings.allow_anonymous_user:
            user = await session.get(User, DEFAULT_USER_ID)
            if user is None:
                user = User(
                    id=DEFAULT_USER_ID,
                    email="developer@mergex.ai",
                    password_hash="$2b$12$b.we3xq6ykEWvSq5rz2cpu.P/JfIxC5Gm7xfSynZUrr98sdqwKnCe",
                    display_name="Alex Vance",
                )
                session.add(user)
                await session.flush()
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(
            token,
            secret=settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
        user_id_str = payload.get("sub")
        if not user_id_str:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user_id = uuid.UUID(user_id_str)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


async def get_optional_current_user(
    request: Request,
    session: SessionDep,
    token_query: Annotated[str | None, Query(alias="token")] = None,
) -> User | None:
    """Resolve user if Authorization token is provided, or return None."""
    settings: Settings = request.app.state.settings
    auth_header = request.headers.get("Authorization")
    token: str | None = None
    if auth_header:
        parts = auth_header.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
    elif token_query:
        token = token_query.strip() or None

    if not token:
        return None

    try:
        payload = decode_access_token(
            token,
            secret=settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
        user_id_str = payload.get("sub")
        if not user_id_str:
            return None
        user_id = uuid.UUID(user_id_str)
        return await session.get(User, user_id)
    except Exception:
        return None


OptionalUserDep = Annotated[User | None, Depends(get_optional_current_user)]
