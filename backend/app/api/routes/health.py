"""Liveness and readiness endpoints.

``/health`` is used by the container healthcheck and by Render; it must stay
dependency-free and fast. ``/health/ready`` probes the things the service
genuinely needs before it can accept work.
"""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import text

from app import __version__
from app.core.config import Settings, get_settings
from app.schemas.health import ComponentHealth, LivenessResponse, ReadinessResponse

router = APIRouter(tags=["health"])

# Captured at import time, i.e. once per process.
_PROCESS_START = time.monotonic()

SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get(
    "/health",
    response_model=LivenessResponse,
    summary="Liveness probe",
)
async def liveness(settings: SettingsDep) -> LivenessResponse:
    """Report that the process is running. Touches no dependency."""
    return LivenessResponse(
        app=settings.app_name,
        version=__version__,
        environment=settings.app_env,
        uptime_seconds=round(time.monotonic() - _PROCESS_START, 3),
    )


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    responses={503: {"model": ReadinessResponse, "description": "A dependency is unavailable."}},
)
async def readiness(
    settings: SettingsDep, request: Request, response: Response
) -> ReadinessResponse:
    """Probe the dependencies required to accept an analysis request."""
    components: dict[str, ComponentHealth] = {
        "database": await _check_database(request),
        "workspace": _check_workspace(settings),
        "gemini": ComponentHealth(
            status="ok" if settings.ai_explanations_enabled else "not_configured",
            detail=(
                None
                if settings.ai_explanations_enabled
                else "GEMINI_API_KEY is unset; findings are reported without AI explanations."
            ),
        ),
    }

    if any(c.status == "unavailable" for c in components.values()):
        overall: str = "unavailable"
    elif any(c.status == "degraded" for c in components.values()):
        overall = "degraded"
    else:
        overall = "ok"

    if overall == "unavailable":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(status=overall, components=components)  # type: ignore[arg-type]


async def _check_database(request: Request) -> ComponentHealth:
    """Open a connection and run the cheapest possible statement.

    ``SELECT 1`` rather than a table query on purpose: this answers "can we
    reach the database", not "are migrations applied", which is a separate
    question with a separate failure mode.
    """
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        return ComponentHealth(
            status="unavailable",
            detail="No database session factory; the application did not start cleanly.",
        )
    try:
        async with factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - any driver error means not ready
        # The URL can contain a password, so only the exception type is
        # reported; the full error goes to the structured log.
        return ComponentHealth(
            status="unavailable",
            detail=f"Database is unreachable ({type(exc).__name__}).",
        )
    return ComponentHealth(status="ok", detail=None)


def _check_workspace(settings: Settings) -> ComponentHealth:
    """Verify the analysis sandbox directory exists and is writable."""
    path = settings.workspace_path
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return ComponentHealth(status="unavailable", detail=f"{path} is not writable: {exc}")
    return ComponentHealth(status="ok", detail=None)
