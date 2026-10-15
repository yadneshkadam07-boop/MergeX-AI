"""Typed application settings, loaded once from the environment.

Every tunable lives here. Nothing in the codebase reads ``os.environ``
directly, so configuration is discoverable and validated at startup.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, computed_field, field_validator
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

    # ---- Gemini (explanation layer only) -----------------------------------
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout_seconds: int = Field(default=60, ge=5, le=300)
    gemini_max_retries: int = Field(default=3, ge=0, le=10)

    # ---- GitHub ------------------------------------------------------------
    github_token: SecretStr | None = None
    github_api_url: str = "https://api.github.com"

    # ---- Analysis sandbox limits ------------------------------------------
    workspace_dir: Path = BACKEND_DIR / ".workspace"
    max_repo_size_mb: int = Field(default=100, ge=1, le=2048)
    max_file_count: int = Field(default=20_000, ge=1)
    max_upload_size_mb: int = Field(default=100, ge=1, le=2048)
    analysis_timeout_seconds: int = Field(default=600, ge=30, le=7200)
    clone_timeout_seconds: int = Field(default=120, ge=10, le=1800)

    # ---- Rate limiting -----------------------------------------------------
    rate_limit_per_minute: int = Field(default=60, ge=1)
    # Take the client address from X-Forwarded-For. Enable this ONLY when a
    # trusted proxy overwrites that header (Render, a load balancer); otherwise
    # a client can forge a new identity per request and bypass the limit.
    trust_proxy_headers: bool = False

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
