"""Deletion of expired demo projects.

The demo endpoint is unauthenticated, so without this the database and the
workspace disk grow for as long as anyone keeps clicking the button. Demo
projects are disposable by definition: nobody comes back to one.

Deleting the row cascades to its analyses and issues. The retained upload
archive is *not* covered by that cascade -- it is a file, not a row -- so it
is removed here too. A file that cannot be removed is logged and the row is
still deleted: a leaked few kilobytes is better than a project that can never
be cleaned up.

The loop runs in the API process rather than as a scheduled job, because the
deployment target is a single instance and a second service would be more
moving parts than the problem deserves. If MergeX ever runs more than one
replica, this should become a scheduled job that one instance owns -- as it
stands every replica would do the same work, which is wasteful but not
incorrect.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import stat
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import SessionFactory
from app.core.logging import get_logger
from app.models.project import Project

__all__ = ["CleanupResult", "purge_expired_demos", "run_demo_cleanup_loop"]

log = get_logger("app.demo_cleanup")


@dataclass(frozen=True, slots=True)
class CleanupResult:
    """What one pass removed."""

    projects_deleted: int = 0
    archives_deleted: int = 0
    archives_failed: int = 0
    sandboxes_deleted: int = 0
    sandboxes_failed: int = 0

    @property
    def did_anything(self) -> bool:
        return bool(self.projects_deleted or self.archives_deleted or self.sandboxes_deleted)


async def purge_expired_demos(
    session: AsyncSession,
    *,
    retention_hours: int,
    now: datetime | None = None,
    workspace_dir: Path | None = None,
) -> CleanupResult:
    """Delete demo projects and sandbox directories older than the retention window.

    Args:
        session: An open session. The caller commits.
        retention_hours: How long a demo project is kept after creation.
        now: Injected in tests so expiry does not have to be waited for.
        workspace_dir: Optional workspace root to sweep for orphaned sandbox dirs.

    Returns:
        Counts of what was removed.
    """
    cutoff = (now or datetime.now(UTC)) - timedelta(hours=retention_hours)

    sandboxes_deleted = 0
    sandboxes_failed = 0
    if workspace_dir is not None:
        sandboxes_deleted, sandboxes_failed = _remove_stale_sandboxes(
            workspace_dir, cutoff.timestamp()
        )

    expired = list(
        await session.scalars(
            select(Project).where(Project.is_demo.is_(True), Project.created_at < cutoff)
        )
    )
    if not expired:
        return CleanupResult(
            sandboxes_deleted=sandboxes_deleted,
            sandboxes_failed=sandboxes_failed,
        )

    archives_deleted = 0
    archives_failed = 0

    for project in expired:
        if project.upload_path:
            removed = _remove_archive(Path(project.upload_path))
            if removed is True:
                archives_deleted += 1
            elif removed is False:
                archives_failed += 1
        await session.delete(project)

    await session.flush()

    result = CleanupResult(
        projects_deleted=len(expired),
        archives_deleted=archives_deleted,
        archives_failed=archives_failed,
        sandboxes_deleted=sandboxes_deleted,
        sandboxes_failed=sandboxes_failed,
    )
    log.info(
        "demo_projects_purged",
        projects=result.projects_deleted,
        archives=result.archives_deleted,
        archives_failed=result.archives_failed,
        sandboxes=result.sandboxes_deleted,
        retention_hours=retention_hours,
    )
    return result


def _remove_archive(path: Path) -> bool | None:
    """Delete a retained archive. True removed, False failed, None absent."""
    try:
        if not path.is_file():
            return None
        path.unlink()
        return True
    except OSError as exc:
        # A file we cannot remove must not stop the row being deleted.
        log.warning("demo_archive_not_removed", path=str(path), error=str(exc))
        return False


def _remove_stale_sandboxes(workspace_dir: Path, cutoff_epoch: float) -> tuple[int, int]:
    """Delete leftover sandbox directories (import-*) older than cutoff_epoch."""
    deleted = 0
    failed = 0
    try:
        if not workspace_dir.is_dir():
            return 0, 0
    except OSError:
        return 0, 0

    for path in workspace_dir.glob("import-*"):
        try:
            if not path.is_dir():
                continue
            if path.stat().st_mtime < cutoff_epoch:
                if sys.version_info >= (3, 12):
                    shutil.rmtree(path, onexc=_force_writable_and_retry)
                else:  # pragma: no cover - 3.11 branch
                    shutil.rmtree(path, onerror=_force_writable_and_retry_legacy)
                deleted += 1
        except OSError as exc:
            log.warning("demo_sandbox_not_removed", path=str(path), error=str(exc))
            failed += 1
    return deleted, failed


def _force_writable_and_retry(func: object, path: str, _exc: BaseException) -> None:
    try:
        Path(path).chmod(stat.S_IWRITE)
        if callable(func):
            func(path)
    except OSError:
        log.warning("sandbox_cleanup_failed", path=path)


def _force_writable_and_retry_legacy(  # pragma: no cover - 3.11 branch
    func: object, path: str, _exc_info: object
) -> None:
    try:
        Path(path).chmod(stat.S_IWRITE)
        if callable(func):
            func(path)
    except OSError:
        log.warning("sandbox_cleanup_failed", path=path)


async def run_demo_cleanup_loop(
    session_factory: SessionFactory,
    settings: Settings,
    *,
    stop: asyncio.Event | None = None,
) -> None:
    """Purge expired demos now, then on an interval until cancelled.

    Every failure is swallowed and retried next tick: cleanup falling over
    must never take the API down with it, and the next pass will find the
    same rows.
    """
    interval = settings.demo_cleanup_interval_minutes * 60
    stop_event = stop or asyncio.Event()

    while not stop_event.is_set():
        try:
            async with session_factory() as session:
                await purge_expired_demos(
                    session,
                    retention_hours=settings.demo_retention_hours,
                    workspace_dir=settings.workspace_path,
                )
                await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a cleanup failure is not an outage
            log.exception("demo_cleanup_failed")

        with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
            # Waiting on the event rather than sleeping means shutdown is
            # immediate instead of up to an hour late.
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
