"""Settings parsing and derived values."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import REPO_ROOT, Settings


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


class TestCorsOrigins:
    def test_parses_comma_separated_string(self) -> None:
        parsed = _settings(cors_origins="http://a.test, http://b.test")

        assert parsed.cors_origins == ["http://a.test", "http://b.test"]

    def test_accepts_a_list(self) -> None:
        assert _settings(cors_origins=["http://a.test"]).cors_origins == ["http://a.test"]

    def test_drops_empty_entries(self) -> None:
        assert _settings(cors_origins="http://a.test,,  ,").cors_origins == ["http://a.test"]


class TestApiPrefix:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("/api/v1", "/api/v1"), ("api/v1", "/api/v1"), ("/api/v1/", "/api/v1")],
    )
    def test_normalises_prefix(self, raw: str, expected: str) -> None:
        assert _settings(api_v1_prefix=raw).api_v1_prefix == expected

    def test_root_prefix_becomes_empty(self) -> None:
        assert _settings(api_v1_prefix="/").api_v1_prefix == ""


class TestAiToggle:
    def test_disabled_without_a_key(self) -> None:
        assert _settings(gemini_api_key=None).ai_explanations_enabled is False

    def test_disabled_for_a_blank_key(self) -> None:
        assert _settings(gemini_api_key="   ").ai_explanations_enabled is False

    def test_enabled_with_a_key(self) -> None:
        assert _settings(gemini_api_key="abc123").ai_explanations_enabled is True

    def test_key_is_not_exposed_by_repr(self) -> None:
        assert "abc123" not in repr(_settings(gemini_api_key="abc123"))


class TestSandboxLimits:
    def test_size_limits_convert_to_bytes(self) -> None:
        assert _settings(max_repo_size_mb=100).max_repo_size_bytes == 100 * 1024 * 1024

    def test_upload_limits_convert_to_bytes(self) -> None:
        assert _settings(max_upload_size_mb=50).max_upload_size_bytes == 50 * 1024 * 1024

    def test_relative_workspace_resolves_to_absolute(self) -> None:
        assert _settings(workspace_dir=Path("./.workspace")).workspace_path.is_absolute()

    def test_absolute_workspace_is_preserved(self, tmp_path: Path) -> None:
        assert _settings(workspace_dir=tmp_path).workspace_path == tmp_path

    def test_rejects_a_nonsense_size_limit(self) -> None:
        with pytest.raises(ValidationError):
            _settings(max_repo_size_mb=0)

    def test_rejects_an_unknown_environment(self) -> None:
        with pytest.raises(ValidationError):
            _settings(app_env="banana")


def test_production_flag() -> None:
    prod = _settings(
        app_env="production",
        # Provide a valid production DB URL so the startup check passes.
        database_url="postgresql+asyncpg://user:pass@db.supabase.co:5432/postgres",
        cors_origins=["https://app.vercel.app"],
        jwt_secret="prod-secret-must-be-at-least-32-chars-long-random-key",
    )
    assert prod.is_production is True
    assert _settings(app_env="local").is_production is False


class TestEnvExampleStaysInSync:
    """`.env.example` is the only documentation of configuration.

    A setting that exists in code but not in the template is undiscoverable;
    a variable in the template that no longer exists is a lie. Both drift
    silently, so they are asserted here.
    """

    # Internal defaults deliberately not exposed as environment variables.
    INTERNAL_FIELDS = frozenset({"app_name", "github_api_url"})
    # Documented in the template but consumed by docker-compose or Vite, not
    # by Settings.
    NON_SETTINGS_VARS = frozenset(
        {
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "POSTGRES_DB",
            "POSTGRES_PORT",
            "VITE_API_BASE_URL",
        }
    )

    @staticmethod
    def _documented() -> set[str]:
        template = REPO_ROOT / ".env.example"
        assert template.is_file(), f"{template} is missing"
        return set(
            re.findall(r"^([A-Z][A-Z0-9_]*)=", template.read_text(encoding="utf-8"), re.MULTILINE)
        )

    def test_every_setting_is_documented(self) -> None:
        expected = {
            name.upper() for name in Settings.model_fields if name not in self.INTERNAL_FIELDS
        }

        undocumented = expected - self._documented()

        assert undocumented == set(), f"Add these to .env.example: {sorted(undocumented)}"

    def test_the_template_has_no_dead_variables(self) -> None:
        known = {name.upper() for name in Settings.model_fields} | self.NON_SETTINGS_VARS

        unknown = self._documented() - known

        assert unknown == set(), f"These are in .env.example but unused: {sorted(unknown)}"
