"""FastAPI application factory and ASGI entrypoint.

Run with: ``uvicorn app.main:app --reload``
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from http import HTTPStatus

import structlog
from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api.router import api_router
from app.api.routes.health import router as health_router
from app.core.config import Settings, get_settings
from app.core.database import build_session_factory, create_engine
from app.core.logging import configure_logging, get_logger
from app.core.rate_limit import RateLimitMiddleware

REQUEST_ID_HEADER = "X-Request-ID"

DESCRIPTION = """
**MergeX AI** validates that the layers of a software project actually fit
together: frontend API calls against backend routes, backend models against
the database schema, configuration against deployment.

Findings are produced by deterministic analysis (Tree-sitter, Python `ast`,
rule engines). The language model only explains, ranks and suggests fixes --
it is never the sole source of a finding.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Start-up and shut-down hooks."""
    settings: Settings = app.state.settings
    log = get_logger("app.lifespan")

    try:
        settings.workspace_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # Do not refuse to boot: /health/ready reports the sandbox as
        # unavailable, which is more useful than a crash loop.
        log.error("workspace_unavailable", path=str(settings.workspace_path), error=str(exc))

    # The engine is created here, not at import time, so that building an app
    # never opens a connection as a side effect and tests can point a second
    # app at a different database.
    engine = create_engine(settings)
    app.state.db_engine = engine
    app.state.session_factory = build_session_factory(engine)

    log.info(
        "startup",
        app=settings.app_name,
        version=__version__,
        environment=settings.app_env,
        workspace=str(settings.workspace_path),
        ai_explanations=settings.ai_explanations_enabled,
    )

    try:
        yield
    finally:
        # Return pooled connections before the process exits; without this,
        # Postgres is left holding them until its own timeout.
        await engine.dispose()
        log.info("shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the ASGI application.

    Accepting ``settings`` keeps the app testable: tests can construct an
    instance with overrides instead of mutating the environment.
    """
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        description=DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.state.settings = settings

    _register_middleware(app, settings)
    _register_exception_handlers(app)

    # Probes live at the root: deployment platforms should not need to know
    # the API version prefix.
    app.include_router(health_router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    return app


def _register_middleware(app: FastAPI, settings: Settings) -> None:
    # Order matters: middleware added last runs first on the way in, so the
    # request-context middleware below wraps everything and the rate limiter
    # sits closest to the router.
    app.add_middleware(
        RateLimitMiddleware,
        limit=settings.rate_limit_per_minute,
        window_seconds=60.0,
        trust_proxy_headers=settings.trust_proxy_headers,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )

    @app.middleware("http")
    async def request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Attach a request id, bind log context, emit one access log line."""
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        log = get_logger("app.request")
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            log.exception("request_failed", duration_ms=_elapsed_ms(started))
            raise

        duration_ms = _elapsed_ms(started)
        response.headers[REQUEST_ID_HEADER] = request_id
        # Health probes are frequent and uninteresting unless they fail.
        if not request.url.path.startswith("/health") or response.status_code >= 400:
            log.info("request", status_code=response.status_code, duration_ms=duration_ms)
        return response


def _register_exception_handlers(app: FastAPI) -> None:
    # 429 responses are produced directly by RateLimitMiddleware, which never
    # raises, so no handler is registered for them.

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Give every error the same envelope.

        FastAPI's default emits a bare ``{"detail": ...}``, which would mean
        clients had to handle two different error shapes.
        """
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": _error_code(exc.status_code), "detail": str(exc.detail)},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Report field errors in a JSON-safe, stable shape.

        ``exc.errors()`` is not serialisable: when a field validator raises,
        Pydantic puts the original exception object in the entry's ``ctx``.
        Passing it straight through turned every such 422 into a 500. Only the
        three fields a client can act on are projected out.
        """
        field_errors = [
            {
                "field": ".".join(str(part) for part in error.get("loc", ())) or "body",
                "message": str(error.get("msg", "Invalid value")),
                "type": str(error.get("type", "value_error")),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": "validation_error",
                "detail": _validation_summary(field_errors),
                "errors": field_errors,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        """Return an opaque 500: internals never reach the client."""
        request_id = request.headers.get(REQUEST_ID_HEADER, "unknown")
        get_logger("app.error").exception("unhandled_exception")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "internal_server_error",
                "detail": "An unexpected error occurred.",
                "request_id": request_id,
            },
        )


def _error_code(status_code: int) -> str:
    """Map a status code to a stable machine-readable code.

    ``404`` becomes ``not_found``, ``409`` becomes ``conflict``. Derived from
    the HTTP reason phrase so a new status needs no table entry.
    """
    try:
        phrase = HTTPStatus(status_code).phrase
    except ValueError:
        return "error"
    return phrase.lower().replace(" ", "_").replace("-", "_")


def _validation_summary(field_errors: list[dict[str, str]]) -> str:
    """One readable sentence describing what failed validation."""
    if not field_errors:
        return "Request failed validation."
    first = field_errors[0]
    suffix = f" (and {len(field_errors) - 1} more)" if len(field_errors) > 1 else ""
    return f"{first['field']}: {first['message']}{suffix}"


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


app = create_app()
