"""ZIP extraction safety.

A ZIP upload is the most hostile input MergeX accepts: the archive controls
every member name, every declared size, and the compression ratio. These are
security tests — a regression here is a host-filesystem write primitive.
"""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest

from app.services.archive import (
    ArchiveLimits,
    InvalidArchiveError,
    extract_zip,
    is_ignored_path,
)

GENEROUS = ArchiveLimits(max_total_bytes=10 * 1024 * 1024, max_file_count=1000)


def build_zip(path: Path, members: dict[str, str | bytes]) -> Path:
    """Write a ZIP containing ``members``."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            archive.writestr(name, data)
    return path


def build_zip_with_symlink(path: Path, link_name: str, target: str) -> Path:
    """Write a ZIP whose member is a symlink, as Info-ZIP stores them."""
    with zipfile.ZipFile(path, "w") as archive:
        info = zipfile.ZipInfo(link_name)
        info.create_system = 3  # Unix
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, target)
        archive.writestr("app/main.py", "print('hi')\n")
    return path


class TestHappyPath:
    def test_extracts_files(self, tmp_path: Path) -> None:
        archive = build_zip(
            tmp_path / "src.zip",
            {"app/main.py": "print('hi')\n", "README.md": "# hi\n"},
        )
        destination = tmp_path / "out"
        destination.mkdir()

        result = extract_zip(archive, destination, GENEROUS, strip_top_level=False)

        assert result.file_count == 2
        assert (destination / "app" / "main.py").read_text(encoding="utf-8") == "print('hi')\n"
        assert result.size_bytes > 0

    def test_strips_the_github_wrapper_directory(self, tmp_path: Path) -> None:
        """GitHub's "Download ZIP" wraps everything in `repo-main/`."""
        archive = build_zip(
            tmp_path / "repo-main.zip",
            {"repo-main/package.json": "{}", "repo-main/src/app.ts": "export {};"},
        )
        destination = tmp_path / "out"
        destination.mkdir()

        result = extract_zip(archive, destination, GENEROUS)

        assert result.stripped_prefix == "repo-main"
        assert (destination / "package.json").is_file()
        assert (destination / "src" / "app.ts").is_file()
        assert not (destination / "repo-main").exists()

    def test_does_not_strip_when_there_is_no_single_wrapper(self, tmp_path: Path) -> None:
        archive = build_zip(
            tmp_path / "multi.zip",
            {"frontend/app.ts": "export {};", "backend/main.py": "pass\n"},
        )
        destination = tmp_path / "out"
        destination.mkdir()

        result = extract_zip(archive, destination, GENEROUS)

        assert result.stripped_prefix is None
        assert (destination / "frontend" / "app.ts").is_file()
        assert (destination / "backend" / "main.py").is_file()

    def test_does_not_strip_when_a_file_sits_at_the_root(self, tmp_path: Path) -> None:
        archive = build_zip(
            tmp_path / "mixed.zip",
            {"README.md": "# hi\n", "src/app.ts": "export {};"},
        )
        destination = tmp_path / "out"
        destination.mkdir()

        result = extract_zip(archive, destination, GENEROUS)

        assert result.stripped_prefix is None
        assert (destination / "README.md").is_file()


class TestZipSlip:
    @pytest.mark.parametrize(
        "member",
        [
            "../escaped.txt",
            "../../escaped.txt",
            "app/../../escaped.txt",
            "/etc/passwd",
            "C:/Windows/evil.ini",
        ],
    )
    def test_malicious_members_are_skipped_not_written(self, tmp_path: Path, member: str) -> None:
        archive = build_zip(tmp_path / "evil.zip", {member: "pwned", "safe.py": "pass\n"})
        destination = tmp_path / "out"
        destination.mkdir()

        result = extract_zip(archive, destination, GENEROUS, strip_top_level=False)

        assert result.skipped_paths == 1
        assert result.file_count == 1
        assert (destination / "safe.py").is_file()
        # Nothing outside the destination was created.
        assert not (tmp_path / "escaped.txt").exists()
        assert list(destination.rglob("escaped.txt")) == []

    def test_an_entirely_malicious_archive_yields_nothing(self, tmp_path: Path) -> None:
        archive = build_zip(tmp_path / "evil.zip", {"../../../a.txt": "x", "../b.txt": "y"})
        destination = tmp_path / "out"
        destination.mkdir()

        result = extract_zip(archive, destination, GENEROUS, strip_top_level=False)

        assert result.file_count == 0
        assert result.skipped_paths == 2
        assert not (tmp_path / "a.txt").exists()

    def test_rejected_member_names_are_reported(self, tmp_path: Path) -> None:
        archive = build_zip(tmp_path / "evil.zip", {"../x.txt": "x", "ok.py": "pass"})
        destination = tmp_path / "out"
        destination.mkdir()

        result = extract_zip(archive, destination, GENEROUS, strip_top_level=False)

        assert result.rejected == ["../x.txt"]


class TestSymlinks:
    def test_symlink_members_are_not_extracted(self, tmp_path: Path) -> None:
        """A symlink would let a later read follow a path out of the sandbox."""
        archive = build_zip_with_symlink(tmp_path / "link.zip", "escape", "/etc/passwd")
        destination = tmp_path / "out"
        destination.mkdir()

        result = extract_zip(archive, destination, GENEROUS, strip_top_level=False)

        assert result.file_count == 1
        assert not (destination / "escape").exists()
        assert (destination / "app" / "main.py").is_file()


class TestLimits:
    def test_rejects_too_many_files(self, tmp_path: Path) -> None:
        archive = build_zip(tmp_path / "many.zip", {f"f{i}.py": "x" for i in range(20)})
        destination = tmp_path / "out"
        destination.mkdir()
        limits = ArchiveLimits(max_total_bytes=1024 * 1024, max_file_count=10)

        with pytest.raises(InvalidArchiveError, match="exceeds the limit of 10"):
            extract_zip(archive, destination, limits, strip_top_level=False)

    def test_rejects_an_archive_that_expands_past_the_limit(self, tmp_path: Path) -> None:
        archive = build_zip(tmp_path / "big.zip", {"big.py": "x" * 5000})
        destination = tmp_path / "out"
        destination.mkdir()
        limits = ArchiveLimits(max_total_bytes=1000, max_file_count=100)

        with pytest.raises(InvalidArchiveError, match="exceeds the limit"):
            extract_zip(archive, destination, limits, strip_top_level=False)

    def test_rejects_an_oversized_single_member(self, tmp_path: Path) -> None:
        archive = build_zip(tmp_path / "one-big.zip", {"big.py": "x" * 5000})
        destination = tmp_path / "out"
        destination.mkdir()
        limits = ArchiveLimits(
            max_total_bytes=1024 * 1024, max_file_count=100, max_member_bytes=1000
        )

        with pytest.raises(InvalidArchiveError, match="per-file limit"):
            extract_zip(archive, destination, limits, strip_top_level=False)

    def test_rejects_a_zip_bomb_by_compression_ratio(self, tmp_path: Path) -> None:
        """64 MB of zeros compresses to almost nothing: ratio, not size, catches it."""
        archive = build_zip(tmp_path / "bomb.zip", {"bomb.bin.py": b"\0" * (64 * 1024 * 1024)})
        destination = tmp_path / "out"
        destination.mkdir()
        limits = ArchiveLimits(max_total_bytes=128 * 1024 * 1024, max_file_count=100)

        with pytest.raises(InvalidArchiveError, match="zip bomb"):
            extract_zip(archive, destination, limits, strip_top_level=False)

    def test_normal_source_compression_is_not_mistaken_for_a_bomb(self, tmp_path: Path) -> None:
        """Realistic, highly compressible source must still import."""
        body = "def handler(request):\n    return {'ok': True}\n" * 400
        archive = build_zip(tmp_path / "src.zip", {f"mod{i}.py": body for i in range(60)})
        destination = tmp_path / "out"
        destination.mkdir()
        limits = ArchiveLimits(max_total_bytes=128 * 1024 * 1024, max_file_count=1000)

        result = extract_zip(archive, destination, limits, strip_top_level=False)

        assert result.file_count == 60


class TestInvalidArchives:
    def test_rejects_a_file_that_is_not_a_zip(self, tmp_path: Path) -> None:
        not_a_zip = tmp_path / "fake.zip"
        not_a_zip.write_text("this is not a zip", encoding="utf-8")
        destination = tmp_path / "out"
        destination.mkdir()

        with pytest.raises(InvalidArchiveError, match="not a valid ZIP"):
            extract_zip(not_a_zip, destination, GENEROUS)

    def test_rejects_an_archive_with_no_source_files(self, tmp_path: Path) -> None:
        archive = build_zip(tmp_path / "junk.zip", {"node_modules/left-pad/index.js": "x"})
        destination = tmp_path / "out"
        destination.mkdir()

        with pytest.raises(InvalidArchiveError, match="no analysable source"):
            extract_zip(archive, destination, GENEROUS)


class TestIgnorePolicy:
    @pytest.mark.parametrize(
        "path",
        [
            "node_modules/react/index.js",
            "frontend/node_modules/x/y.js",
            ".git/objects/ab/cdef",
            "__pycache__/mod.cpython-312.pyc",
            ".venv/lib/site-packages/x.py",
            "dist/bundle.js",
            "build/output.js",
            ".next/server/page.js",
            "coverage/lcov-report/index.html",
            "app/icon.woff2",
            "assets/video.mp4",
            "nested/inner.zip",
        ],
    )
    def test_ignores_dependency_build_and_binary_paths(self, path: str) -> None:
        assert is_ignored_path(path)

    @pytest.mark.parametrize(
        "path",
        [
            "src/app.tsx",
            "backend/app/main.py",
            "package.json",
            "requirements.txt",
            "migrations/0001_init.sql",
            "prisma/schema.prisma",
            ".env",
            "README.md",
            "src/components/node_modules_helper.ts",
        ],
    )
    def test_keeps_analysable_paths(self, path: str) -> None:
        assert not is_ignored_path(path)

    def test_ignored_directories_are_not_extracted(self, tmp_path: Path) -> None:
        archive = build_zip(
            tmp_path / "app.zip",
            {
                "src/app.ts": "export {};",
                "node_modules/react/index.js": "module.exports = {};",
                ".git/config": "[core]",
            },
        )
        destination = tmp_path / "out"
        destination.mkdir()

        result = extract_zip(archive, destination, GENEROUS, strip_top_level=False)

        assert result.file_count == 1
        assert not (destination / "node_modules").exists()
        assert not (destination / ".git").exists()
