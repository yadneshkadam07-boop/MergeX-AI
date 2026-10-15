"""Sandbox path-safety guarantees.

MergeX unpacks untrusted archives, so these are platform-security tests, not
convenience helpers: a regression here is a host-filesystem write primitive.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.security import (
    UnsafePathError,
    is_within,
    mask_secret,
    redact_url_credentials,
    safe_archive_member_path,
    safe_join,
)


class TestIsWithin:
    def test_direct_child_is_within(self, tmp_path: Path) -> None:
        assert is_within(tmp_path, tmp_path / "a" / "b.txt")

    def test_base_itself_is_within(self, tmp_path: Path) -> None:
        assert is_within(tmp_path, tmp_path)

    def test_sibling_is_not_within(self, tmp_path: Path) -> None:
        assert not is_within(tmp_path / "base", tmp_path / "other")

    def test_traversal_is_not_within(self, tmp_path: Path) -> None:
        escaped = tmp_path / "base" / ".." / ".." / "etc"
        assert not is_within(tmp_path / "base", escaped)


class TestSafeJoin:
    def test_joins_nested_components(self, tmp_path: Path) -> None:
        assert safe_join(tmp_path, "src", "index.ts") == tmp_path / "src" / "index.ts"

    def test_ignores_empty_components(self, tmp_path: Path) -> None:
        assert safe_join(tmp_path, "", "src") == tmp_path / "src"

    @pytest.mark.parametrize(
        "component",
        ["..", "../etc/passwd", "a/../../b", "..\\windows"],
    )
    def test_rejects_traversal(self, tmp_path: Path, component: str) -> None:
        with pytest.raises(UnsafePathError, match="traversal"):
            safe_join(tmp_path, component)

    @pytest.mark.parametrize("component", ["/etc/passwd", "\\windows\\system32"])
    def test_rejects_absolute_components(self, tmp_path: Path, component: str) -> None:
        with pytest.raises(UnsafePathError, match="absolute"):
            safe_join(tmp_path, component)

    @pytest.mark.parametrize("component", ["bad\x00name", "line\nbreak", "carriage\rreturn"])
    def test_rejects_illegal_characters(self, tmp_path: Path, component: str) -> None:
        with pytest.raises(UnsafePathError, match="illegal characters"):
            safe_join(tmp_path, component)


class TestSafeArchiveMemberPath:
    def test_accepts_ordinary_member(self, tmp_path: Path) -> None:
        result = safe_archive_member_path(tmp_path, "repo/src/app.py")

        assert result == tmp_path / "repo" / "src" / "app.py"

    def test_normalises_backslash_separators(self, tmp_path: Path) -> None:
        result = safe_archive_member_path(tmp_path, "repo\\src\\app.py")

        assert result == tmp_path / "repo" / "src" / "app.py"

    def test_strips_redundant_current_directory(self, tmp_path: Path) -> None:
        assert safe_archive_member_path(tmp_path, "./repo/a.py") == tmp_path / "repo" / "a.py"

    @pytest.mark.parametrize(
        "member",
        [
            "../../etc/passwd",
            "repo/../../escape.txt",
            "a/b/../../../c",
        ],
    )
    def test_rejects_zip_slip(self, tmp_path: Path, member: str) -> None:
        with pytest.raises(UnsafePathError):
            safe_archive_member_path(tmp_path, member)

    @pytest.mark.parametrize("member", ["/etc/passwd", "\\windows\\win.ini"])
    def test_rejects_absolute_members(self, tmp_path: Path, member: str) -> None:
        with pytest.raises(UnsafePathError):
            safe_archive_member_path(tmp_path, member)

    @pytest.mark.parametrize("member", ["C:/Windows/system.ini", "D:evil.txt"])
    def test_rejects_drive_qualified_members(self, tmp_path: Path, member: str) -> None:
        with pytest.raises(UnsafePathError, match="drive-qualified"):
            safe_archive_member_path(tmp_path, member)

    def test_rejects_unc_members(self, tmp_path: Path) -> None:
        with pytest.raises(UnsafePathError, match="UNC"):
            safe_archive_member_path(tmp_path, "//attacker/share/payload")

    @pytest.mark.parametrize("member", ["", ".", "./"])
    def test_rejects_empty_members(self, tmp_path: Path, member: str) -> None:
        with pytest.raises(UnsafePathError):
            safe_archive_member_path(tmp_path, member)

    @pytest.mark.parametrize("member", ["NUL", "repo/CON.txt", "lpt1"])
    def test_rejects_windows_device_names(self, tmp_path: Path, member: str) -> None:
        with pytest.raises(UnsafePathError, match="reserved device"):
            safe_archive_member_path(tmp_path, member)


class TestRedaction:
    def test_mask_secret_keeps_tail(self) -> None:
        assert mask_secret("ghp_abcdefghijklmnop") == "********mnop"

    def test_mask_secret_handles_none(self) -> None:
        assert mask_secret(None) == "<unset>"

    def test_mask_secret_fully_masks_short_values(self) -> None:
        assert mask_secret("abc") == "***"

    def test_redacts_url_credentials(self) -> None:
        url = "postgresql+asyncpg://mergex:s3cret@db:5432/mergex"

        assert redact_url_credentials(url) == "postgresql+asyncpg://***:***@db:5432/mergex"

    def test_leaves_credential_free_url_untouched(self) -> None:
        url = "https://api.osv.dev/v1/querybatch"

        assert redact_url_credentials(url) == url
