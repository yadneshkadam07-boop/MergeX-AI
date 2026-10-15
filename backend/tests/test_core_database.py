"""Database URL normalisation.

These are the tests that make "paste your Supabase connection string into
.env" actually work. Each case corresponds to a concrete failure:

* a dashboard URL says ``postgresql://``, which loads the *synchronous* driver
* Supabase appends ``?sslmode=require``, which asyncpg rejects outright
* the pooled endpoint cannot support prepared statements

All pure functions, so no database is involved.
"""

from __future__ import annotations

import pytest
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.database import build_engine_options, create_engine, normalise_database_url


class TestDriverRewriting:
    @pytest.mark.parametrize(
        "raw",
        [
            "postgresql://user:pw@host:5432/db",
            "postgres://user:pw@host:5432/db",
            "postgresql+asyncpg://user:pw@host:5432/db",
        ],
    )
    def test_always_ends_up_on_asyncpg(self, raw: str) -> None:
        assert normalise_database_url(raw).url.startswith("postgresql+asyncpg://")

    def test_preserves_host_port_and_database(self) -> None:
        target = normalise_database_url("postgres://u:p@db.example.com:6543/mergex")

        assert target.url == "postgresql+asyncpg://u:p@db.example.com:6543/mergex"

    def test_non_postgres_urls_pass_through_untouched(self) -> None:
        """The test suite's own SQLite URL must not be rewritten."""
        raw = "sqlite+aiosqlite:///./test.db"

        assert normalise_database_url(raw).url == raw

    def test_strips_surrounding_whitespace(self) -> None:
        target = normalise_database_url("  postgres://u:p@host/db\n")

        assert target.url == "postgresql+asyncpg://u:p@host/db"

    def test_rejects_an_empty_url(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            normalise_database_url("   ")


class TestSslHandling:
    @pytest.mark.parametrize("mode", ["require", "verify-ca", "verify-full"])
    def test_sslmode_becomes_an_asyncpg_connect_arg(self, mode: str) -> None:
        """asyncpg has no `sslmode` kwarg; passing it through raises TypeError."""
        target = normalise_database_url(f"postgresql://u:p@host/db?sslmode={mode}")

        assert "sslmode" not in target.url
        assert target.connect_args == {"ssl": "require"}

    @pytest.mark.parametrize("mode", ["disable", "allow", "prefer"])
    def test_non_encrypting_modes_add_no_ssl_arg(self, mode: str) -> None:
        target = normalise_database_url(f"postgresql://u:p@host/db?sslmode={mode}")

        assert target.connect_args == {}
        assert "sslmode" not in target.url

    @pytest.mark.parametrize(
        "param",
        ["channel_binding=require", "target_session_attrs=read-write", "connect_timeout=10"],
    )
    def test_other_libpq_only_params_are_dropped(self, param: str) -> None:
        target = normalise_database_url(f"postgresql://u:p@host/db?{param}")

        assert "?" not in target.url

    def test_unknown_params_are_preserved(self) -> None:
        """A genuine asyncpg/SQLAlchemy option must survive."""
        target = normalise_database_url("postgresql://u:p@host/db?prepared_statement_cache_size=0")

        assert "prepared_statement_cache_size=0" in target.url

    def test_handles_several_params_at_once(self) -> None:
        target = normalise_database_url(
            "postgresql://u:p@host/db?sslmode=require&application_name=x&foo=bar"
        )

        assert target.connect_args == {"ssl": "require"}
        assert "foo=bar" in target.url
        assert "application_name" not in target.url


class TestCredentialSafety:
    def test_safe_rendering_masks_the_password(self) -> None:
        target = normalise_database_url("postgresql://admin:s3cret@host/db")

        assert "s3cret" not in target.safe
        assert target.safe == "postgresql+asyncpg://***:***@host/db"


class TestEngineConfiguration:
    def _settings(self, **overrides: object) -> Settings:
        base: dict[str, object] = {
            "database_url": "postgresql+asyncpg://u:p@host:5432/db",
            "workspace_dir": "./.workspace",
        }
        base.update(overrides)
        return Settings(**base)  # type: ignore[arg-type]

    def test_pools_by_default(self) -> None:
        _, options = build_engine_options(self._settings(db_pool_size=7, db_max_overflow=3))

        assert options["pool_size"] == 7
        assert options["max_overflow"] == 3
        assert "poolclass" not in options

    def test_pgbouncer_mode_disables_pooling_and_statement_caching(self) -> None:
        """Supabase's pooled endpoint (port 6543) needs all three of these."""
        _, options = build_engine_options(self._settings(db_disable_prepared_statements=True))

        assert options["poolclass"] is NullPool
        assert options["prepared_statement_cache_size"] == 0
        assert options["connect_args"]["statement_cache_size"] == 0
        # Pool sizing is meaningless with NullPool and must not be passed.
        assert "pool_size" not in options

    def test_pgbouncer_mode_keeps_the_ssl_arg(self) -> None:
        """The two Supabase quirks occur together and must not cancel out."""
        settings = self._settings(
            database_url="postgresql://u:p@pooler.supabase.com:6543/postgres?sslmode=require",
            db_disable_prepared_statements=True,
        )

        _, options = build_engine_options(settings)

        assert options["connect_args"]["ssl"] == "require"
        assert options["connect_args"]["statement_cache_size"] == 0

    def test_sqlite_url_does_not_receive_postgres_pool_options(self) -> None:
        """SQLite rejects pool_size, so the engine must not pass it."""
        _, options = build_engine_options(self._settings(database_url="sqlite+aiosqlite:///./x.db"))

        assert "pool_size" not in options
        assert "max_overflow" not in options

    def test_pre_ping_is_always_enabled(self) -> None:
        """Cloud databases drop idle connections without warning."""
        _, options = build_engine_options(self._settings())

        assert options["pool_pre_ping"] is True

    def test_engine_is_constructible(self) -> None:
        """Building an engine must not open a connection as a side effect."""
        engine = create_engine(self._settings())

        assert engine.dialect.name == "postgresql"
