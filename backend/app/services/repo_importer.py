"""Bring an untrusted repository into the analysis sandbox.

Two sources, one contract: both produce a directory of plain files inside
``WORKSPACE_DIR`` and an :class:`ImportResult` describing it. Nothing in this
module ever executes code from the repository -- no install, no build, no test
run. Analysis is static, always.

The sandbox is a context manager, so the working tree is removed on the way
out whether the import succeeded, failed or timed out.
"""

from __future__ import annotations

import shutil
import stat
import sys
import tempfile
import time
import uuid
from collections.abc import AsyncGenerator, Callable, Iterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from anyio import to_thread

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.security import safe_join
from app.models.enums import SourceType
from app.services.archive import (
    ArchiveLimits,
    InvalidArchiveError,
    extract_zip,
    is_ignored_path,
)
from app.services.git_client import (
    GitCommandError,
    GitResult,
    GitRunner,
    GitTimeoutError,
    build_clone_command,
    build_fetch_commit_commands,
    build_rev_parse_command,
    is_commit_sha,
    run_git,
)
from app.services.github import GitHubRepoRef

__all__ = [
    "ImportResult",
    "RepoImportError",
    "RepoImporter",
    "RepoTooLargeError",
    "Sandbox",
    "TreeStats",
    "measure_tree",
]

log = get_logger("app.repo_importer")


class RepoImportError(RuntimeError):
    """An import could not be completed. Message is safe to show a user."""


class RepoTooLargeError(RepoImportError):
    """The repository exceeds a configured size or file-count limit."""


class RepoNotFoundError(RepoImportError):
    """The repository or ref does not exist, or is not accessible."""


@dataclass(frozen=True, slots=True)
class TreeStats:
    """Measurements of an imported working tree."""

    file_count: int
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ImportResult:
    """A working tree, ready to analyse."""

    path: Path
    source_type: SourceType
    file_count: int
    size_bytes: int
    duration_ms: int
    commit_sha: str | None = None
    skipped_paths: int = 0


class Sandbox:
    """An isolated directory that deletes itself.

    Created under ``WORKSPACE_DIR`` rather than the system temp directory so
    that the location is configurable, auditable, and can be mounted as a
    container-only volume (see docker-compose.yml) -- cloned code never
    touches the host filesystem.
    """

    def __init__(self, root: Path, *, prefix: str = "import-") -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.path = Path(tempfile.mkdtemp(dir=root, prefix=prefix))

    def __enter__(self) -> Sandbox:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        """Remove the directory, defeating read-only files.

        Git marks objects in ``.git`` read-only, and on Windows that makes a
        plain ``rmtree`` fail with ``PermissionError``. The handler clears the
        read-only bit and retries.
        """
        if not self.path.exists():
            return
        if sys.version_info >= (3, 12):
            shutil.rmtree(self.path, onexc=_force_writable_and_retry)
        else:  # pragma: no cover - 3.11 branch
            shutil.rmtree(self.path, onerror=_force_writable_and_retry_legacy)
        log.debug("sandbox_removed", path=str(self.path))


def _force_writable_and_retry(
    func: Callable[[str], object], path: str, _exc: BaseException
) -> None:
    try:
        Path(path).chmod(stat.S_IWRITE)
        func(path)
    except OSError:
        # Last resort: a leaked directory is preferable to failing the request
        # that is trying to clean up after itself.
        log.warning("sandbox_cleanup_failed", path=path)


def _force_writable_and_retry_legacy(  # pragma: no cover - 3.11 branch
    func: Callable[[str], object], path: str, exc_info: object
) -> None:
    _force_writable_and_retry(func, path, RuntimeError(str(exc_info)))


def measure_tree(root: Path, *, max_files: int, max_bytes: int) -> TreeStats:
    """Count analysable files and bytes under ``root``, failing fast on limits.

    Ignored directories (``.git``, ``node_modules``, build output) are pruned
    during the walk, so the limits apply to what will actually be analysed.

    Raises:
        RepoTooLargeError: as soon as a limit is passed, without finishing the
            walk -- a hostile tree should not be fully traversed.
    """
    file_count = 0
    size_bytes = 0

    for path in _iter_analysable_files(root):
        file_count += 1
        if file_count > max_files:
            raise RepoTooLargeError(f"Repository contains more than {max_files} analysable files.")
        try:
            size_bytes += path.stat().st_size
        except OSError:
            continue  # vanished mid-walk; not worth failing the import
        if size_bytes > max_bytes:
            raise RepoTooLargeError(
                f"Repository exceeds the {max_bytes // (1024 * 1024)} MB size limit."
            )

    return TreeStats(file_count=file_count, size_bytes=size_bytes)


def _iter_analysable_files(root: Path) -> Iterator[Path]:
    """Yield files under ``root``, skipping ignored directories entirely."""
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            # Never follow a symlink out of the sandbox.
            if entry.is_symlink():
                continue
            relative = entry.relative_to(root).as_posix()
            if entry.is_dir():
                if not is_ignored_path(f"{relative}/"):
                    stack.append(entry)
                continue
            if not is_ignored_path(relative):
                yield entry


class RepoImporter:
    """Imports repositories into the sandbox.

    ``git_runner`` is injectable so the clone path can be tested without a
    network or a git binary.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        git_runner: GitRunner | None = None,
    ) -> None:
        self._settings = settings
        self._run_git: GitRunner = git_runner or _default_git_runner

    # -- GitHub -----------------------------------------------------------

    @asynccontextmanager
    async def import_github(
        self,
        repo: GitHubRepoRef,
        *,
        token: str | None = None,
    ) -> AsyncGenerator[ImportResult, None]:
        """Shallow-clone ``repo`` into a sandbox for the duration of the block.

        The working tree is deleted when the block exits.

        Raises:
            RepoNotFoundError: repository or ref missing/inaccessible.
            RepoTooLargeError: tree exceeds the configured limits.
            RepoImportError: clone failed or timed out.
        """
        started = time.perf_counter()
        with Sandbox(self._settings.workspace_path) as sandbox:
            checkout = sandbox.path / "repo"
            url = repo.authenticated_clone_url(token) if token else repo.clone_url

            await self._clone(url, checkout, repo.ref, sandbox.path)

            # Walking a 20k-file tree and stat-ing every entry is blocking
            # work; keep it off the event loop.
            stats = await to_thread.run_sync(
                partial(
                    measure_tree,
                    checkout,
                    max_files=self._settings.max_file_count,
                    max_bytes=self._settings.max_repo_size_bytes,
                )
            )
            commit_sha = await self._read_head(checkout, sandbox.path)

            log.info(
                "github_import_complete",
                repo=repo.full_name,
                ref=repo.ref,
                commit=commit_sha,
                files=stats.file_count,
                bytes=stats.size_bytes,
            )
            yield ImportResult(
                path=checkout,
                source_type=SourceType.GITHUB,
                file_count=stats.file_count,
                size_bytes=stats.size_bytes,
                commit_sha=commit_sha,
                duration_ms=_elapsed_ms(started),
            )

    async def _clone(self, url: str, checkout: Path, ref: str | None, cwd: Path) -> None:
        timeout = float(self._settings.clone_timeout_seconds)

        if ref and is_commit_sha(ref):
            commands = build_fetch_commit_commands(url, checkout, ref)
        else:
            commands = [build_clone_command(url, checkout, ref=ref)]

        for command in commands:
            try:
                result = await self._run_git(command, cwd=cwd, timeout=timeout)
            except GitTimeoutError as exc:
                raise RepoImportError(
                    f"Cloning timed out after {timeout:.0f} seconds. The repository may be "
                    "too large to import."
                ) from exc
            except (GitCommandError, OSError) as exc:
                raise RepoImportError(f"Could not run git: {exc}") from exc

            if result.returncode != 0:
                raise self._clone_failure(result, ref)

    @staticmethod
    def _clone_failure(result: GitResult, ref: str | None) -> RepoImportError:
        """Translate git's stderr into something a user can act on."""
        stderr = result.stderr.lower()
        if "could not find remote branch" in stderr or "unknown revision" in stderr:
            return RepoNotFoundError(f"Branch or commit {ref!r} does not exist in that repository.")
        if "repository not found" in stderr or "not found" in stderr:
            return RepoNotFoundError(
                "Repository not found. It may be private — set GITHUB_TOKEN to import it."
            )
        if "authentication failed" in stderr or "invalid username" in stderr:
            return RepoNotFoundError(
                "Authentication failed. Check that GITHUB_TOKEN is valid and has access."
            )
        if "could not resolve host" in stderr or "network is unreachable" in stderr:
            return RepoImportError("Could not reach github.com. Check network connectivity.")
        # Never surface raw stderr: it can contain the token-bearing URL.
        log.warning("clone_failed", returncode=result.returncode, stderr=result.stderr[:500])
        return RepoImportError("Cloning the repository failed.")

    async def _read_head(self, checkout: Path, cwd: Path) -> str | None:
        """Report the checked-out commit, or None if it cannot be determined."""
        try:
            result = await self._run_git(build_rev_parse_command(checkout), cwd=cwd, timeout=30.0)
        except (GitCommandError, OSError):
            return None
        if result.returncode != 0:
            return None
        sha = result.stdout.strip()
        return sha or None

    # -- ZIP ---------------------------------------------------------------

    @asynccontextmanager
    async def import_zip(self, archive_path: Path) -> AsyncGenerator[ImportResult, None]:
        """Extract ``archive_path`` into a sandbox for the duration of the block.

        Raises:
            RepoImportError: if the archive is invalid or violates a limit.
        """
        started = time.perf_counter()
        with Sandbox(self._settings.workspace_path) as sandbox:
            checkout = sandbox.path / "repo"
            checkout.mkdir(parents=True, exist_ok=True)

            limits = ArchiveLimits(
                max_total_bytes=self._settings.max_repo_size_bytes,
                max_file_count=self._settings.max_file_count,
            )
            try:
                # Decompressing up to 100 MB would otherwise stall every
                # other request for the duration.
                extraction = await to_thread.run_sync(extract_zip, archive_path, checkout, limits)
            except InvalidArchiveError as exc:
                raise RepoImportError(str(exc)) from exc

            log.info(
                "zip_import_complete",
                files=extraction.file_count,
                bytes=extraction.size_bytes,
                skipped=extraction.skipped_paths,
            )
            yield ImportResult(
                path=checkout,
                source_type=SourceType.ZIP,
                file_count=extraction.file_count,
                size_bytes=extraction.size_bytes,
                duration_ms=_elapsed_ms(started),
                skipped_paths=extraction.skipped_paths,
            )

    # -- Retained uploads ---------------------------------------------------

    def upload_destination(self, project_id: uuid.UUID) -> Path:
        """Where a project's uploaded archive is retained.

        A ZIP has no origin to re-fetch from, so the archive itself is kept
        (outside any sandbox) and re-extracted for each analysis. The name is
        derived from the project id, never from the user-supplied filename.
        """
        uploads = safe_join(self._settings.workspace_path, "uploads")
        uploads.mkdir(parents=True, exist_ok=True)
        return uploads / f"{project_id}.zip"


async def _default_git_runner(
    args: Sequence[str],
    *,
    cwd: Path,
    timeout: float,
) -> GitResult:
    return await run_git(args, cwd=cwd, timeout=timeout)


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
