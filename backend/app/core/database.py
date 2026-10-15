"""Async engine, session factory and URL normalisation.

The normalisation is not incidental tidying — it is what lets the same
``DATABASE_URL`` work for local Postgres, a Supabase direct connection and a
Supabase pooled connection:

* **Driver.** A URL copied from a dashboard says ``postgresql://`` or
  ``postgres://``. Both are rewritten to ``postgresql+asyncpg://``, because
  SQLAlchemy would otherwise load the synchronous psycopg2 driver and fail.
* **``sslmode``.** libpq accepts it; asyncpg does not, and raises
  ``TypeError: connect() got an unexpected keyword argument 'sslmode'``.
  Supabase URLs routinely carry ``?sslmode=require``, so it is translated to
  asyncpg's ``ssl`` connect-arg instead.
* **Prepared statements.** Supabase's pooler (port 6543, pgbouncer in
  transaction mode) cannot support them: a statement prepared on one backend
  may be executed on another, which fails with ``prepared statement "__asyncpg_
  stmt_1__" does not exist``. ``DB_DISABLE_PREPARED_STATEMENTS=true`` turns
  caching off and switches to ``NullPool``, which is what that pooler needs.
  A direct connection (port 5432) should leave it off.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.security import redact_url_credentials

__all__ = [
    "DatabaseUrl",
    "SessionFactory",
    "build_engine_options",
    "build_session_factory",
    "create_engine",
    "normalise_database_url",
]

log = get_logger("app.database")

SessionFactory = async_sessionmaker[AsyncSession]

# Query parameters understood by libpq but not by asyncpg. Passing any of them
# through makes connection fail with an opaque TypeError.
_LIBPQ_ONLY_PARAMS = frozenset(
    {
        "sslmode",
        "sslrootcert",
        "sslcert",
        "sslkey",
        "channel_binding",
        "target_session_attrs",
        "options",
        "application_name",
        "connect_timeout",
        "gssencmode",
    }
)

# sslmode values that mean "encrypt the connection".
_SSL_REQUIRED_MODES = frozenset({"require", "verify-ca", "verify-full"})

_ASYNC_SCHEME = "postgresql+asyncpg"


@dataclass(frozen=True, slots=True)
class DatabaseUrl:
    """A connection URL split into what SQLAlchemy and asyncpg each need."""

    url: str
    connect_args: dict[str, Any] = field(default_factory=dict)

    @property
    def safe(self) -> str:
        """The URL with credentials masked, for logging."""
        return redact_url_credentials(self.url)


def normalise_database_url(raw_url: str) -> DatabaseUrl:
    """Rewrite ``raw_url`` into something asyncpg can actually connect with.

    Pure function: no I/O, so it is directly unit-tested. Non-PostgreSQL URLs
    (notably ``sqlite+aiosqlite://`` used by the test suite) pass through
    untouched.

    Raises:
        ValueError: if ``raw_url`` is empty.
    """
    if not raw_url or not raw_url.strip():
        raise ValueError("DATABASE_URL must not be empty")

    parts = urlsplit(raw_url.strip())
    scheme = parts.scheme.lower()

    if not scheme.startswith(("postgres", "postgresql")):
        return DatabaseUrl(url=raw_url.strip())

    connect_args: dict[str, Any] = {}
    kept_params: list[tuple[str, str]] = []

    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered == "sslmode":
            if value.lower() in _SSL_REQUIRED_MODES:
                # asyncpg takes `ssl`, not `sslmode`. "require" encrypts
                # without verifying the certificate chain, which is what
                # libpq's `require` means too.
                connect_args["ssl"] = "require"
            continue
        if lowered in _LIBPQ_ONLY_PARAMS:
            continue
        kept_params.append((key, value))

    normalised = urlunsplit(
        (
            _ASYNC_SCHEME,
            parts.netloc,
            parts.path,
            urlencode(kept_params),
            parts.fragment,
        )
    )
    return DatabaseUrl(url=normalised, connect_args=connect_args)


def build_engine_options(settings: Settings) -> tuple[DatabaseUrl, dict[str, Any]]:
    """Work out the URL and keyword arguments for the engine.

    Separated from :func:`create_engine` so the options are directly testable;
    they are otherwise sealed inside the engine and cannot be inspected.
    """
    target = normalise_database_url(settings.database_url)
    kwargs: dict[str, Any] = {
        "echo": settings.db_echo,
        # Verify a pooled connection before handing it out; cloud databases
        # drop idle connections without warning.
        "pool_pre_ping": True,
        "connect_args": dict(target.connect_args),
    }

    if settings.db_disable_prepared_statements:
        # pgbouncer in transaction mode: no statement may outlive a transaction.
        kwargs["poolclass"] = NullPool
        kwargs["connect_args"]["statement_cache_size"] = 0
        kwargs["prepared_statement_cache_size"] = 0
    elif target.url.startswith(_ASYNC_SCHEME):
        kwargs["pool_size"] = settings.db_pool_size
        kwargs["max_overflow"] = settings.db_max_overflow
        kwargs["pool_recycle"] = 1800

    return target, kwargs


def create_engine(settings: Settings) -> AsyncEngine:
    """Build the async engine for ``settings``."""
    target, kwargs = build_engine_options(settings)
    engine = create_async_engine(target.url, **kwargs)

    if engine.dialect.name == "sqlite":
        _enforce_sqlite_foreign_keys(engine)

    log.info(
        "database_engine_created",
        url=target.safe,
        prepared_statements=not settings.db_disable_prepared_statements,
    )
    return engine


def _enforce_sqlite_foreign_keys(engine: AsyncEngine) -> None:
    """Turn on foreign-key enforcement for every SQLite connection.

    SQLite ignores ``REFERENCES`` clauses unless ``PRAGMA foreign_keys`` is
    enabled, and the pragma is per-connection rather than per-database.
    Without this, ``ON DELETE CASCADE`` silently does nothing — so a test
    suite running on SQLite would report that cascading deletes work when on
    PostgreSQL they are the only thing that removes child rows.
    """

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragma(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


def build_session_factory(engine: AsyncEngine) -> SessionFactory:
    """Build the session factory bound to ``engine``.

    ``expire_on_commit=False`` so a response model can still read an object's
    attributes after the request's transaction has committed.
    """
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )


async def session_scope(factory: SessionFactory) -> AsyncGenerator[AsyncSession, None]:
    """Yield a session, committing on success and rolling back on error."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
