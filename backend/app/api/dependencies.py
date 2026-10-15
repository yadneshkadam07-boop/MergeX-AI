"""Shared FastAPI dependencies.

The database session is created per request from the factory held on
``app.state``, so a test can swap in a SQLite engine by building the app with
different settings rather than by monkey-patching a module global.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import SessionFactory
from app.schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.services.repo_importer import RepoImporter

__all__ = [
    "ImporterDep",
    "Pagination",
    "PaginationDep",
    "SessionDep",
    "SettingsDep",
    "get_session",
]


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped session, committing on success.

    A handler that raises leaves the transaction rolled back, so a failed
    request cannot half-write a project row.
    """
    factory: SessionFactory | None = getattr(request.app.state, "session_factory", None)
    if factory is None:  # pragma: no cover - misconfiguration, not a code path
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not configured.",
        )

    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


class Pagination:
    """Validated ``limit``/``offset`` pair."""

    def __init__(
        self,
        limit: Annotated[
            int,
            Query(ge=1, le=MAX_PAGE_SIZE, description="Maximum rows to return."),
        ] = DEFAULT_PAGE_SIZE,
        offset: Annotated[int, Query(ge=0, description="Rows to skip.")] = 0,
    ) -> None:
        self.limit = limit
        self.offset = offset


def get_importer(settings: Annotated[Settings, Depends(get_settings)]) -> RepoImporter:
    """Build the repository importer for this request."""
    return RepoImporter(settings)


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
PaginationDep = Annotated[Pagination, Depends()]
ImporterDep = Annotated[RepoImporter, Depends(get_importer)]
