"""Typed application settings, loaded once from the environment.

Every tunable lives here. Nothing in the codebase reads ``os.environ``
directly, so configuration is discoverable and validated at startup.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# backend/app/core/config.py -> parents[2] == backend/
BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent

AppEnv = Literal["local", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Runtime configuration for the API and the analysis engine."""

    model_config = SettingsConfigDict(
        # The repo-root .env is the shared source of truth; a backend-local
        # .env may override it for one-off local experiments.
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Application -------------------------------------------------------
    app_name: str = "MergeX AI"
    app_env: AppEnv = "local"
    log_level: LogLevel = "INFO"
    api_v1_prefix: str = "/api/v1"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    # ---- Database ----------------------------------------------------------
    database_url: str = "postgresql+asyncpg://mergex:mergex@localhost:5432/mergex"
    db_echo: bool = False
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=10, ge=0, le=50)
    # Required for Supabase's connection pooler (port 6543) and any pgbouncer
    # in transaction mode, where a prepared statement cannot outlive its
    # transaction. Leave false for a direct connection (port 5432).
    db_disable_prepared_statements: bool = False

    # ---- Gemini (explanation layer only) -----------------------------------
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout_seconds: int = Field(default=60, ge=5, le=300)
    gemini_max_retries: int = Field(default=3, ge=0, le=10)

    # ---- GitHub ------------------------------------------------------------
    github_token: SecretStr | None = None
    github_api_url: str = "https://api.github.com"
    github_client_id: str | None = None
    github_client_secret: SecretStr | None = None

    # ---- Analysis sandbox limits ------------------------------------------
    workspace_dir: Path = BACKEND_DIR / ".workspace"
    max_repo_size_mb: int = Field(default=100, ge=1, le=2048)
    max_file_count: int = Field(default=20_000, ge=1)
    max_upload_size_mb: int = Field(default=100, ge=1, le=2048)
    analysis_timeout_seconds: int = Field(default=600, ge=30, le=7200)
    clone_timeout_seconds: int = Field(default=120, ge=10, le=1800)

    # ---- Rate limiting -----------------------------------------------------
    rate_limit_per_minute: int = Field(default=60, ge=1)
    # The demo endpoint is unauthenticated and does real work -- it packs an
    # archive, imports it and runs a full analysis -- so it gets its own, much
    # tighter limit on top of the blanket one. An hour window rather than a
    # minute: the point is to stop someone looping it, not to pace a person
    # clicking the button twice.
    demo_rate_limit_per_hour: int = Field(default=5, ge=1)
    # Strict per-minute cap on the demo endpoint. This is the primary abuse
    # barrier: 5 requests per minute is enough for a live demo but too slow
    # for a loop. The hourly cap is a secondary backstop.
    demo_rate_limit_per_minute: int = Field(default=5, ge=1)
    # Short-window burst guard stacked on top of the hourly cap. Two requests
    # per 10 minutes stops a client from draining their hourly budget in one
    # second, while still allowing a person to click the button twice quickly.
    demo_burst_limit: int = Field(default=2, ge=1)
    demo_burst_window_minutes: int = Field(default=10, ge=1)
    # Demo projects are disposable. They are deleted on this schedule so an
    # unauthenticated endpoint cannot fill the database or the disk.
    demo_retention_hours: int = Field(default=24, ge=1)
    demo_cleanup_interval_minutes: int = Field(default=60, ge=1)
    # Take the client address from X-Forwarded-For. Enable this ONLY when a
    # trusted proxy overwrites that header (Render, a load balancer); otherwise
    # a client can forge a new identity per request and bypass the limit.
    trust_proxy_headers: bool = False

    # ---- Authentication & Security -----------------------------------------
    jwt_secret: str = "mergex-dev-secret-change-in-production-0987654321"
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 1440
    auth_rate_limit_per_minute: int = 15
    allow_anonymous_user: bool = False

    # ---- External services -------------------------------------------------
    osv_api_url: str = "https://api.osv.dev/v1/querybatch"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        """Accept ``a,b`` as well as a JSON array for ``CORS_ORIGINS``."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("api_v1_prefix")
    @classmethod
    def _normalise_prefix(cls, value: str) -> str:
        prefix = "/" + value.strip("/")
        return "" if prefix == "/" else prefix

    @model_validator(mode="after")
    def _production_readiness_check(self) -> Settings:
        """Fail fast with a useful message for obvious production misconfigurations.

        Runs after all individual field validators so every field has its final
        value. Only fires in ``production`` so local and staging environments
        are not burdened with mandatory secrets during development.
        """
        if self.app_env != "production":
            return self

        errors: list[str] = []

        # A default local Postgres URL in production means the operator forgot
        # to set DATABASE_URL; it will connection-refuse immediately, but the
        # message will be an obscure asyncpg error rather than a clear one.
        _local_defaults = {
            "postgresql+asyncpg://mergex:mergex@localhost:5432/mergex",
            "postgresql+asyncpg://mergex:mergex@db:5432/mergex",
        }
        if self.database_url in _local_defaults:
            errors.append(
                "DATABASE_URL is the local development default. "
                "Set it to your Supabase (or other) connection string."
            )

        # JWT secret cannot be the development default in production
        if not self.jwt_secret or "dev-secret" in self.jwt_secret:
            errors.append("JWT_SECRET must be set to a secure, random secret in production.")

        if self.allow_anonymous_user:
            errors.append("ALLOW_ANONYMOUS_USER cannot be true in production.")

        # An empty CORS_ORIGINS list means the CORSMiddleware will reject every
        # browser request, making the frontend completely non-functional.
        if not self.cors_origins:
            errors.append(
                "CORS_ORIGINS is empty. Set it to your Vercel deployment URL, "
                "e.g. https://your-app.vercel.app"
            )
        elif any(o.strip() == "*" for o in self.cors_origins):
            errors.append(
                "CORS_ORIGINS contains a wildcard (*). "
                "Wildcards are not safe in production; use explicit origins."
            )

        if errors:
            joined = "; ".join(errors)
            raise ValueError(f"Production startup check failed ({len(errors)} issue(s)): {joined}")

        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ai_explanations_enabled(self) -> bool:
        """False when no Gemini key is set: analysis still runs, unexplained."""
        key = self.gemini_api_key
        return key is not None and bool(key.get_secret_value().strip())

    @property
    def max_repo_size_bytes(self) -> int:
        return self.max_repo_size_mb * 1024 * 1024

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def workspace_path(self) -> Path:
        """Absolute sandbox root; relative values resolve against ``backend/``."""
        path = self.workspace_dir
        return path if path.is_absolute() else (BACKEND_DIR / path).resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton (cached)."""
    return Settings()
