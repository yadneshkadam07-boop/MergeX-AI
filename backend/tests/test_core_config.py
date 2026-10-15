"""Settings parsing and derived values."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


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
    assert _settings(app_env="production").is_production is True
    assert _settings(app_env="local").is_production is False
