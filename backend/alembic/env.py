"""Alembic environment.

The URL comes from ``app.core.config`` rather than ``alembic.ini`` so that
migrations and the application can never disagree about which database they
are pointed at. Both therefore honour the same ``.env``.

Runs async for PostgreSQL. A synchronous SQLite URL is also supported, which
is how the test suite verifies that migrations actually apply.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, create_engine, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.core.database import normalise_database_url

# Importing the package registers every model on Base.metadata; without it,
# autogenerate would propose dropping all tables.
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# A URL already present in the config wins: that is how the test suite and
# `alembic -x url=...` point a run at a throwaway database. Otherwise the
# application's own settings decide, so `alembic upgrade head` and the running
# service can never disagree about which database they mean.
if config.get_main_option("sqlalchemy.url", None):
    _connect_args: dict[str, object] = {}
else:
    _target = normalise_database_url(get_settings().database_url)
    _connect_args = dict(_target.connect_args)
    # Escaped because ConfigParser performs %-interpolation on values.
    config.set_main_option("sqlalchemy.url", _target.url.replace("%", "%%"))


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Detect column type changes, which Alembic ignores by default.
        compare_type=True,
        compare_server_default=True,
        # Emit CHECK constraints for non-native enums on every backend.
        render_as_batch=connection.dialect.name == "sqlite",
        include_schemas=False,
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting (``alembic upgrade --sql``)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async(url: str) -> None:
    """Connect with the async engine and run migrations."""
    section = dict(config.get_section(config.config_ini_section, {}))
    section["sqlalchemy.url"] = url

    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=_connect_args,
    )
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(_run_migrations)
    finally:
        await connectable.dispose()


def _run_sync(url: str) -> None:
    """Run migrations over a synchronous driver."""
    connectable = create_engine(url, poolclass=pool.NullPool, connect_args=_connect_args)
    try:
        with connectable.connect() as connection:
            _run_migrations(connection)
    finally:
        connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for an online run.

    Both driver kinds are supported: the application uses asyncpg, while the
    test suite points this at synchronous SQLite.
    """
    url = config.get_main_option("sqlalchemy.url")
    if url is None:  # pragma: no cover - guarded by the config block above
        raise RuntimeError("No database URL configured for Alembic.")

    if "+aiosqlite" in url or "+asyncpg" in url or "+aiomysql" in url:
        asyncio.run(_run_async(url))
    else:
        _run_sync(url)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
