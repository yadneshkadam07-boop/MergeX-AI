"""Project endpoints: import, list, read, rename, delete."""

from __future__ import annotations

import uuid
from functools import partial
from pathlib import Path
from typing import Annotated

from anyio import to_thread
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select

from app.api.dependencies import ImporterDep, PaginationDep, SessionDep, SettingsDep
from app.core.logging import get_logger
from app.models.enums import SourceType
from app.models.project import Project
from app.schemas.common import (
    NOT_FOUND_RESPONSE,
    RATE_LIMITED_RESPONSE,
    UNPROCESSABLE_RESPONSE,
    Page,
)
from app.schemas.project import (
    ProjectCreateFromGitHub,
    ProjectCreateResponse,
    ProjectImportSummary,
    ProjectRead,
    ProjectUpdate,
)
from app.services.github import InvalidGitHubUrlError
from app.services.project_service import (
    ImportOutcome,
    UploadTooLargeError,
    build_github_project,
    build_zip_project,
    stream_upload_to_disk,
)
from app.services.repo_importer import RepoImportError, RepoTooLargeError

router = APIRouter(prefix="/projects", tags=["projects"])
log = get_logger("app.api.projects")

_IMPORT_RESPONSES = {**UNPROCESSABLE_RESPONSE, **RATE_LIMITED_RESPONSE}


@router.post(
    "",
    response_model=ProjectCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Import a GitHub repository",
    responses=_IMPORT_RESPONSES,
)
async def create_project_from_github(
    payload: ProjectCreateFromGitHub,
    session: SessionDep,
    settings: SettingsDep,
    importer: ImporterDep,
) -> ProjectCreateResponse:
    """Clone a repository, detect its stack, and record the project.

    The clone is deleted before the response is sent; each analysis takes a
    fresh copy. Nothing from the repository is executed.
    """
    try:
        outcome = await build_github_project(
            session,
            settings,
            importer,
            source_url=payload.source_url,
            source_ref=payload.source_ref,
            name=payload.name,
        )
    except InvalidGitHubUrlError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except RepoTooLargeError as exc:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(exc)) from exc
    except RepoImportError as exc:
        # The source is at fault, not this service: 422 rather than 500.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    return ProjectCreateResponse(
        project=ProjectRead.model_validate(outcome.project),
        import_summary=_summarise(outcome),
    )


@router.post(
    "/upload",
    response_model=ProjectCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Import a project from a ZIP archive",
    responses=_IMPORT_RESPONSES,
)
async def create_project_from_zip(
    session: SessionDep,
    settings: SettingsDep,
    importer: ImporterDep,
    file: Annotated[UploadFile, File(description="ZIP archive of the project.")],
    name: Annotated[str | None, Form(max_length=200)] = None,
) -> ProjectCreateResponse:
    """Extract an uploaded archive, detect its stack, and record the project.

    The archive is retained (there is no origin to re-fetch from) but the
    extracted tree is not.
    """
    filename = file.filename or "upload.zip"
    if not filename.lower().endswith(".zip"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Only .zip archives are supported.",
        )

    # The id is minted here because the retained archive is named after it.
    project_id = uuid.uuid4()
    archive_path = importer.upload_destination(project_id)

    try:
        await stream_upload_to_disk(file, archive_path, settings.max_upload_size_bytes)
    except UploadTooLargeError as exc:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(exc)) from exc

    try:
        outcome = await build_zip_project(
            session,
            importer,
            project_id=project_id,
            archive_path=archive_path,
            filename=filename,
            name=name,
        )
    except RepoTooLargeError as exc:
        await to_thread.run_sync(partial(archive_path.unlink, missing_ok=True))
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(exc)) from exc
    except RepoImportError as exc:
        # Do not keep an archive we could not read.
        await to_thread.run_sync(partial(archive_path.unlink, missing_ok=True))
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    return ProjectCreateResponse(
        project=ProjectRead.model_validate(outcome.project),
        import_summary=_summarise(outcome),
    )


@router.get("", response_model=Page[ProjectRead], summary="List projects")
async def list_projects(session: SessionDep, pagination: PaginationDep) -> Page[ProjectRead]:
    """Most recently created first."""
    total = await session.scalar(select(func.count()).select_from(Project)) or 0
    rows = await session.scalars(
        select(Project)
        .order_by(Project.created_at.desc(), Project.id.desc())
        .limit(pagination.limit)
        .offset(pagination.offset)
    )
    return Page[ProjectRead](
        items=[ProjectRead.model_validate(row) for row in rows],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get(
    "/{project_id}",
    response_model=ProjectRead,
    summary="Get a project",
    responses=NOT_FOUND_RESPONSE,
)
async def get_project(project_id: uuid.UUID, session: SessionDep) -> ProjectRead:
    return ProjectRead.model_validate(await _require_project(session, project_id))


@router.patch(
    "/{project_id}",
    response_model=ProjectRead,
    summary="Rename a project",
    responses=NOT_FOUND_RESPONSE,
)
async def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    session: SessionDep,
) -> ProjectRead:
    """Only the display name is mutable; a source change means a new import."""
    project = await _require_project(session, project_id)
    project.name = payload.name
    await session.flush()
    # `updated_at` is computed by the database via `onupdate`, so after an
    # UPDATE the attribute is expired. Reading it during response
    # serialisation would attempt lazy IO outside the async context and raise
    # MissingGreenlet, so it is refreshed explicitly here.
    await session.refresh(project)
    return ProjectRead.model_validate(project)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project",
    responses=NOT_FOUND_RESPONSE,
)
async def delete_project(project_id: uuid.UUID, session: SessionDep) -> None:
    """Delete a project, its analyses and issues, and any retained archive."""
    project = await _require_project(session, project_id)
    retained = project.upload_path

    # Analyses and issues go via ON DELETE CASCADE.
    await session.delete(project)
    await session.flush()

    if retained and project.source_type is SourceType.ZIP:
        await to_thread.run_sync(partial(Path(retained).unlink, missing_ok=True))

    log.info("project_deleted", project_id=str(project_id))


async def _require_project(session: SessionDep, project_id: uuid.UUID) -> Project:
    """Load a project or raise 404."""
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def _summarise(outcome: ImportOutcome) -> ProjectImportSummary:
    """Build the import summary from an import outcome."""
    result = outcome.result
    return ProjectImportSummary(
        file_count=result.file_count,
        size_bytes=result.size_bytes,
        commit_sha=result.commit_sha,
        duration_ms=result.duration_ms,
        skipped_paths=result.skipped_paths,
    )
