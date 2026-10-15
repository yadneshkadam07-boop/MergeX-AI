"""Create-and-import orchestration for projects.

Lives outside the routers so the flow is testable without HTTP, and so the
Phase 4 background job can reuse it.

Invariant: a working tree never outlives the import. Only facts about the
repository are persisted; each analysis takes a fresh copy.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import BinaryIO, Protocol

from anyio import to_thread
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.models.enums import SourceType
from app.models.project import Project
from app.services.github import parse_github_url
from app.services.repo_importer import ImportResult, RepoImporter
from app.services.stack_detector import StackReport, detect_stack

__all__ = [
    "ImportOutcome",
    "UploadTooLargeError",
    "build_github_project",
    "build_zip_project",
    "stream_upload_to_disk",
]

log = get_logger("app.project_service")

_CHUNK_BYTES = 1024 * 1024


class UploadTooLargeError(ValueError):
    """Upload exceeded ``MAX_UPLOAD_SIZE_MB``."""


class ChunkedUpload(Protocol):
    """The part of Starlette's ``UploadFile`` this module needs."""

    async def read(self, size: int = -1) -> bytes: ...


@dataclass(frozen=True, slots=True)
class ImportOutcome:
    """A persisted project plus what the import observed."""

    project: Project
    stack: StackReport
    result: ImportResult


async def stream_upload_to_disk(upload: ChunkedUpload, destination: Path, max_bytes: int) -> int:
    """Copy an upload to ``destination`` in chunks, enforcing ``max_bytes``.

    Chunked so a large archive never lands in memory whole, and counted while
    writing because a declared Content-Length cannot be trusted. A rejected
    upload leaves no partial file behind.

    Disk writes are pushed to a worker thread: at the 100 MB limit a
    synchronous write loop would block the event loop long enough to stall
    every other request, including health probes.

    Returns:
        Bytes written.

    Raises:
        UploadTooLargeError: the limit was passed; ``destination`` is removed.
    """
    await to_thread.run_sync(partial(destination.parent.mkdir, parents=True, exist_ok=True))
    written = 0
    try:
        sink = await to_thread.run_sync(_open_binary, destination)
        try:
            while True:
                chunk = await upload.read(_CHUNK_BYTES)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise UploadTooLargeError(
                        f"Upload exceeds the {max_bytes // (1024 * 1024)} MB limit."
                    )
                await to_thread.run_sync(sink.write, chunk)
        finally:
            await to_thread.run_sync(sink.close)
    except BaseException:
        await to_thread.run_sync(partial(destination.unlink, missing_ok=True))
        raise
    return written


async def build_github_project(
    session: AsyncSession,
    settings: Settings,
    importer: RepoImporter,
    *,
    source_url: str,
    source_ref: str | None = None,
    name: str | None = None,
) -> ImportOutcome:
    """Clone a repository, detect its stack, and add the project to ``session``.

    Raises:
        InvalidGitHubUrlError: the URL is not a usable GitHub repository.
        RepoImportError: clone failed, timed out, or exceeded a limit.
    """
    repo = parse_github_url(source_url, ref=source_ref)
    token = settings.github_token.get_secret_value() if settings.github_token else None

    project = Project(
        id=uuid.uuid4(),
        name=name or repo.default_project_name,
        source_type=SourceType.GITHUB,
        source_url=repo.canonical_url,
        source_ref=repo.ref,
    )

    async with importer.import_github(repo, token=token) as result:
        # Walks the whole tree and parses every manifest: thread it so the
        # event loop stays responsive during a large import.
        stack = await to_thread.run_sync(detect_stack, result.path)

    _record_import(project, result, stack)
    session.add(project)
    await session.flush()

    log.info(
        "project_created",
        project_id=str(project.id),
        source="github",
        repo=repo.full_name,
        files=result.file_count,
    )
    return ImportOutcome(project=project, stack=stack, result=result)


async def build_zip_project(
    session: AsyncSession,
    importer: RepoImporter,
    *,
    project_id: uuid.UUID,
    archive_path: Path,
    filename: str,
    name: str | None = None,
) -> ImportOutcome:
    """Extract a retained archive, detect its stack, and add the project.

    ``archive_path`` is kept after this returns: a ZIP has no origin to
    re-fetch, so the archive itself is the project's source of truth. The
    caller deletes it if this raises.

    Raises:
        RepoImportError: the archive is invalid or violates a limit.
    """
    project = Project(
        id=project_id,
        name=name or _name_from_filename(filename),
        source_type=SourceType.ZIP,
        source_url=None,
        upload_path=str(archive_path),
        upload_filename=filename,
    )

    async with importer.import_zip(archive_path) as result:
        stack = await to_thread.run_sync(detect_stack, result.path)

    _record_import(project, result, stack)
    session.add(project)
    await session.flush()

    log.info(
        "project_created",
        project_id=str(project.id),
        source="zip",
        files=result.file_count,
    )
    return ImportOutcome(project=project, stack=stack, result=result)


def _record_import(project: Project, result: ImportResult, stack: StackReport) -> None:
    """Copy import facts onto the project row."""
    project.detected_stack = stack.to_dict()
    project.commit_sha = result.commit_sha
    project.file_count = result.file_count
    project.size_bytes = result.size_bytes
    project.last_imported_at = datetime.now(UTC)
    project.import_error = None


def _open_binary(path: Path) -> BinaryIO:
    """Open for binary writing.

    A named helper rather than `partial(path.open, "wb")` so the binary
    overload of `Path.open` is actually selected by the type checker.
    """
    return path.open("wb")


def _name_from_filename(filename: str) -> str:
    """Derive a display name from an uploaded archive's name."""
    stem = Path(filename).stem.strip() or "Uploaded project"
    # GitHub's "Download ZIP" produces `repo-main.zip`; drop the branch suffix.
    for suffix in ("-main", "-master", "-develop", "-dev"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return stem[:200] or "Uploaded project"
