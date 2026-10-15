"""Repository import: sandbox lifecycle, limits, and clone orchestration.

The clone path is exercised through an injected fake git runner, so these
tests need no network and no git binary. The one test that really talks to
GitHub is marked ``network`` and is excluded from the default run.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.core.config import Settings
from app.models.enums import SourceType
from app.services.git_client import build_clone_command, build_rev_parse_command, is_commit_sha
from app.services.github import GitHubRepoRef, parse_github_url
from app.services.repo_importer import (
    RepoImporter,
    RepoImportError,
    RepoTooLargeError,
    Sandbox,
    measure_tree,
)
from tests.conftest import FakeGit

REPO = GitHubRepoRef(owner="owner", repo="repo")


class TestSandbox:
    def test_creates_a_directory_inside_the_workspace(self, tmp_path: Path) -> None:
        with Sandbox(tmp_path / "workspace") as sandbox:
            assert sandbox.path.is_dir()
            assert sandbox.path.parent == (tmp_path / "workspace")

    def test_removes_itself_on_exit(self, tmp_path: Path) -> None:
        with Sandbox(tmp_path / "workspace") as sandbox:
            created = sandbox.path
            (created / "file.txt").write_text("x", encoding="utf-8")

        assert not created.exists()

    def test_removes_itself_when_the_block_raises(self, tmp_path: Path) -> None:
        """A failed import must not leak a working tree."""
        created: Path | None = None
        with pytest.raises(RuntimeError), Sandbox(tmp_path / "workspace") as sandbox:
            created = sandbox.path
            (created / "file.txt").write_text("x", encoding="utf-8")
            raise RuntimeError("import blew up")

        assert created is not None
        assert not created.exists()

    def test_removes_read_only_files(self, tmp_path: Path) -> None:
        """Git marks objects read-only; on Windows that breaks a naive rmtree."""
        with Sandbox(tmp_path / "workspace") as sandbox:
            created = sandbox.path
            locked = created / "locked.txt"
            locked.write_text("x", encoding="utf-8")
            locked.chmod(0o444)

        assert not created.exists()

    def test_sandboxes_are_distinct(self, tmp_path: Path) -> None:
        with Sandbox(tmp_path / "w") as first, Sandbox(tmp_path / "w") as second:
            assert first.path != second.path


class TestMeasureTree:
    def test_counts_files_and_bytes(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x" * 10, encoding="utf-8")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "b.ts").write_text("y" * 20, encoding="utf-8")

        stats = measure_tree(tmp_path, max_files=100, max_bytes=1_000_000)

        assert stats.file_count == 2
        assert stats.size_bytes == 30

    def test_prunes_ignored_directories(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("x", encoding="utf-8")
        for ignored in ("node_modules", ".git", "__pycache__", "dist"):
            directory = tmp_path / ignored
            directory.mkdir()
            (directory / "junk.js").write_text("x" * 5000, encoding="utf-8")

        stats = measure_tree(tmp_path, max_files=100, max_bytes=1_000_000)

        assert stats.file_count == 1
        assert stats.size_bytes == 1

    def test_rejects_too_many_files(self, tmp_path: Path) -> None:
        for index in range(12):
            (tmp_path / f"f{index}.py").write_text("x", encoding="utf-8")

        with pytest.raises(RepoTooLargeError, match="more than 5 analysable files"):
            measure_tree(tmp_path, max_files=5, max_bytes=1_000_000)

    def test_rejects_an_oversized_tree(self, tmp_path: Path) -> None:
        (tmp_path / "big.py").write_text("x" * 5000, encoding="utf-8")

        with pytest.raises(RepoTooLargeError, match="size limit"):
            measure_tree(tmp_path, max_files=100, max_bytes=1024)

    def test_an_empty_tree_measures_zero(self, tmp_path: Path) -> None:
        stats = measure_tree(tmp_path, max_files=10, max_bytes=1024)

        assert stats.file_count == 0


class TestCloneCommand:
    """The hardening flags are asserted, not assumed."""

    def test_clone_is_shallow_and_single_branch(self) -> None:
        command = build_clone_command("https://github.com/o/r.git", Path("/tmp/dest"))

        assert "--depth=1" in command
        assert "--single-branch" in command
        assert "--no-tags" in command

    def test_clone_disables_symlinks_hooks_and_submodules(self) -> None:
        command = build_clone_command("https://github.com/o/r.git", Path("/tmp/dest"))
        joined = " ".join(command)

        assert "core.symlinks=false" in joined
        assert "core.hooksPath=" in joined
        assert "--no-recurse-submodules" in command
        assert "credential.helper=" in joined

    def test_url_is_passed_after_a_double_dash(self) -> None:
        """So a URL beginning with '-' cannot be read as an option."""
        command = build_clone_command("https://github.com/o/r.git", Path("/tmp/dest"))

        assert command[command.index("--") + 1] == "https://github.com/o/r.git"

    def test_branch_is_passed_as_an_option_value(self) -> None:
        command = build_clone_command("https://github.com/o/r.git", Path("/d"), ref="develop")

        assert "--branch=develop" in command

    def test_rev_parse_targets_the_checkout(self) -> None:
        checkout = Path("/d/repo")

        # str(Path) is platform-specific, so the expected value is built the
        # same way rather than hard-coding a POSIX separator.
        assert build_rev_parse_command(checkout) == [
            "git",
            "-C",
            str(checkout),
            "rev-parse",
            "HEAD",
        ]

    @pytest.mark.parametrize("ref", ["a1b2c3d", "a" * 40, "0123456789abcdef"])
    def test_recognises_commit_shas(self, ref: str) -> None:
        assert is_commit_sha(ref)

    @pytest.mark.parametrize("ref", ["main", "develop", "v1.2.3", "feature/login", "abc"])
    def test_does_not_mistake_branches_for_shas(self, ref: str) -> None:
        assert not is_commit_sha(ref)


class TestGitHubImport:
    async def test_imports_a_cloned_tree(self, settings: Settings) -> None:
        git = FakeGit({"package.json": "{}", "src/app.ts": "export {};"})
        importer = RepoImporter(settings, git_runner=git)

        async with importer.import_github(REPO) as result:
            assert result.source_type is SourceType.GITHUB
            assert result.file_count == 2
            assert (result.path / "package.json").is_file()
            checkout = result.path

        # The working tree is gone once the block exits.
        assert not checkout.exists()

    async def test_records_the_checked_out_commit(self, settings: Settings) -> None:
        git = FakeGit(head="f" * 40)
        importer = RepoImporter(settings, git_runner=git)

        async with importer.import_github(REPO) as result:
            assert result.commit_sha == "f" * 40

    async def test_passes_the_branch_to_git(self, settings: Settings) -> None:
        git = FakeGit()
        importer = RepoImporter(settings, git_runner=git)
        repo = parse_github_url("https://github.com/owner/repo/tree/develop")

        async with importer.import_github(repo):
            pass

        assert "--branch=develop" in git.clone_command

    async def test_uses_the_fetch_path_for_a_commit_sha(self, settings: Settings) -> None:
        """A SHA cannot be cloned directly; init+fetch is used instead."""
        git = FakeGit()
        importer = RepoImporter(settings, git_runner=git)
        repo = GitHubRepoRef(owner="o", repo="r", ref="a" * 40)

        async with importer.import_github(repo):
            pass

        assert any("init" in call for call in git.calls)
        assert any("fetch" in call for call in git.calls)
        assert not any("clone" in call for call in git.calls)

    async def test_token_is_embedded_in_the_clone_url(self, settings: Settings) -> None:
        git = FakeGit()
        importer = RepoImporter(settings, git_runner=git)

        async with importer.import_github(REPO, token="ghp_secret"):
            pass

        assert any("x-access-token:ghp_secret@github.com" in part for part in git.clone_command)

    async def test_enforces_the_file_count_limit(self, settings_factory: object) -> None:
        tight = settings_factory(max_file_count=2)  # type: ignore[operator]
        git = FakeGit({f"f{i}.py": "x" for i in range(5)})
        importer = RepoImporter(tight, git_runner=git)

        with pytest.raises(RepoTooLargeError):
            async with importer.import_github(REPO):
                pass

    async def test_enforces_the_size_limit(self, settings_factory: object) -> None:
        tight = settings_factory(max_repo_size_mb=1)  # type: ignore[operator]
        git = FakeGit({"big.py": "x" * (2 * 1024 * 1024)})
        importer = RepoImporter(tight, git_runner=git)

        with pytest.raises(RepoTooLargeError, match="size limit"):
            async with importer.import_github(REPO):
                pass


class TestCloneFailures:
    """git's stderr is translated into something a user can act on."""

    @pytest.mark.parametrize(
        ("stderr", "expected"),
        [
            ("fatal: repository not found", "may be private"),
            ("fatal: Authentication failed for 'https://github.com/o/r'", "GITHUB_TOKEN"),
            ("fatal: Could not resolve host: github.com", "network connectivity"),
            ("warning: Could not find remote branch nope to clone", "does not exist"),
        ],
    )
    async def test_maps_stderr_to_a_useful_message(
        self, settings: Settings, stderr: str, expected: str
    ) -> None:
        importer = RepoImporter(settings, git_runner=FakeGit(returncode=128, stderr=stderr))

        with pytest.raises(RepoImportError, match=expected):
            async with importer.import_github(REPO):
                pass

    async def test_unknown_failures_do_not_leak_stderr(self, settings: Settings) -> None:
        """stderr can contain the token-bearing URL, so it is never surfaced."""
        secret = "https://x-access-token:ghp_leak@github.com/o/r.git"
        importer = RepoImporter(
            settings, git_runner=FakeGit(returncode=1, stderr=f"fatal: weird thing {secret}")
        )

        with pytest.raises(RepoImportError) as caught:
            async with importer.import_github(REPO):
                pass

        assert "ghp_leak" not in str(caught.value)
        assert str(caught.value) == "Cloning the repository failed."

    async def test_sandbox_is_cleaned_up_after_a_failure(self, settings: Settings) -> None:
        importer = RepoImporter(settings, git_runner=FakeGit(returncode=128, stderr="fatal: x"))

        with pytest.raises(RepoImportError):
            async with importer.import_github(REPO):
                pass

        leftovers = list(settings.workspace_path.glob("import-*"))
        assert leftovers == []


class TestZipImport:
    def _archive(self, path: Path, members: dict[str, str]) -> Path:
        with zipfile.ZipFile(path, "w") as archive:
            for name, content in members.items():
                archive.writestr(name, content)
        return path

    async def test_imports_an_archive(self, settings: Settings, tmp_path: Path) -> None:
        archive = self._archive(
            tmp_path / "app.zip",
            {"repo/package.json": "{}", "repo/src/app.ts": "export {};"},
        )
        importer = RepoImporter(settings)

        async with importer.import_zip(archive) as result:
            assert result.source_type is SourceType.ZIP
            assert result.file_count == 2
            # The wrapper directory was stripped.
            assert (result.path / "package.json").is_file()
            checkout = result.path

        assert not checkout.exists()

    async def test_the_archive_itself_is_retained(self, settings: Settings, tmp_path: Path) -> None:
        """There is no origin to re-fetch a ZIP from, so it must survive."""
        archive = self._archive(tmp_path / "app.zip", {"app.py": "pass\n"})
        importer = RepoImporter(settings)

        async with importer.import_zip(archive):
            pass

        assert archive.is_file()

    async def test_reports_skipped_unsafe_members(self, settings: Settings, tmp_path: Path) -> None:
        archive = self._archive(
            tmp_path / "evil.zip", {"../escape.txt": "pwned", "app.py": "pass\n"}
        )
        importer = RepoImporter(settings)

        async with importer.import_zip(archive) as result:
            assert result.skipped_paths == 1
            assert result.file_count == 1

    async def test_rejects_a_non_zip(self, settings: Settings, tmp_path: Path) -> None:
        bogus = tmp_path / "fake.zip"
        bogus.write_text("not a zip", encoding="utf-8")
        importer = RepoImporter(settings)

        with pytest.raises(RepoImportError, match="not a valid ZIP"):
            async with importer.import_zip(bogus):
                pass


class TestUploadDestination:
    def test_is_named_after_the_project_id(self, settings: Settings) -> None:
        import uuid

        project_id = uuid.uuid4()
        importer = RepoImporter(settings)

        destination = importer.upload_destination(project_id)

        assert destination.name == f"{project_id}.zip"
        assert destination.parent.name == "uploads"
        # Inside the workspace, never anywhere else.
        assert settings.workspace_path in destination.parents


@pytest.mark.network
async def test_clones_a_real_public_repository(settings: Settings) -> None:
    """End-to-end against GitHub. Excluded from the default run.

    Run with: pytest -m network
    """
    importer = RepoImporter(settings)
    repo = parse_github_url("https://github.com/octocat/Hello-World")

    async with importer.import_github(repo) as result:
        assert result.file_count >= 1
        assert result.commit_sha is not None
        assert len(result.commit_sha) == 40
