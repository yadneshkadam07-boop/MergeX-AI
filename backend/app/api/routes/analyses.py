"""Analysis endpoints: queue a run, list runs, read one, delete.

Phase 1 manages the *record* of a run. Executing it — the LangGraph pipeline
and the SSE progress stream — lands in Phase 4, which is why a created
analysis stays ``pending`` and why there is no endpoint to mutate its status
from outside.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.sql.elements import ColumnElement

from app.api.dependencies import PaginationDep, SessionDep
from app.core.logging import get_logger
from app.models.analysis import Analysis
from app.models.enums import AnalysisStatus, Severity
from app.models.issue import Issue
from app.models.project import Project
from app.schemas.analysis import (
    AnalysisCreate,
    AnalysisRead,
    AnalysisSummary,
    IssueCounts,
    IssueRead,
)
from app.schemas.common import CONFLICT_RESPONSE, NOT_FOUND_RESPONSE, Page

log = get_logger("app.api.analyses")

# Nested under a project: creating a run always targets one project.
project_analyses_router = APIRouter(prefix="/projects/{project_id}/analyses", tags=["analyses"])
# Top-level: an analysis is addressable on its own once it exists.
analyses_router = APIRouter(prefix="/analyses", tags=["analyses"])


@project_analyses_router.post(
    "",
    response_model=AnalysisRead,
    status_code=status.HTTP_201_CREATED,
    summary="Queue an analysis run",
    responses={**NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
async def create_analysis(
    project_id: uuid.UUID,
    payload: AnalysisCreate,
    session: SessionDep,
) -> AnalysisRead:
    """Create a pending run for a project.

    Refuses if a run is already queued or in flight, so a double-click cannot
    start two clones of the same repository at once.
    """
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    if not project.is_importable:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This project's source is no longer available; re-import it.",
        )

    active = await session.scalar(
        select(func.count())
        .select_from(Analysis)
        .where(
            Analysis.project_id == project_id,
            Analysis.status.in_([AnalysisStatus.PENDING, AnalysisStatus.RUNNING]),
        )
    )
    if active:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "An analysis for this project is already queued or running.",
        )

    analysis = Analysis(
        id=uuid.uuid4(),
        project_id=project_id,
        status=AnalysisStatus.PENDING,
        commit_sha=project.commit_sha,
    )
    if payload.source_ref is not None:
        # Recorded on the run so the pipeline knows what to check out, without
        # mutating the project's configured default.
        analysis.stack = {"requested_ref": payload.source_ref}

    session.add(analysis)
    await session.flush()

    log.info("analysis_queued", analysis_id=str(analysis.id), project_id=str(project_id))
    return AnalysisRead.model_validate(analysis)


@project_analyses_router.get(
    "",
    response_model=Page[AnalysisSummary],
    summary="List a project's analyses",
    responses=NOT_FOUND_RESPONSE,
)
async def list_project_analyses(
    project_id: uuid.UUID,
    session: SessionDep,
    pagination: PaginationDep,
) -> Page[AnalysisSummary]:
    """Newest run first, each with its issue tallies."""
    if await session.get(Project, project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")

    total = (
        await session.scalar(
            select(func.count()).select_from(Analysis).where(Analysis.project_id == project_id)
        )
        or 0
    )
    rows = list(
        await session.scalars(
            select(Analysis)
            .where(Analysis.project_id == project_id)
            .order_by(Analysis.created_at.desc(), Analysis.id.desc())
            .limit(pagination.limit)
            .offset(pagination.offset)
        )
    )

    counts = await _issue_counts_for(session, [row.id for row in rows])
    return Page[AnalysisSummary](
        items=[
            AnalysisSummary(
                analysis=AnalysisRead.model_validate(row),
                issue_counts=counts.get(row.id, IssueCounts()),
            )
            for row in rows
        ],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@analyses_router.get(
    "/{analysis_id}",
    response_model=AnalysisSummary,
    summary="Get an analysis",
    responses=NOT_FOUND_RESPONSE,
)
async def get_analysis(analysis_id: uuid.UUID, session: SessionDep) -> AnalysisSummary:
    analysis = await _require_analysis(session, analysis_id)
    counts = await _issue_counts_for(session, [analysis.id])
    return AnalysisSummary(
        analysis=AnalysisRead.model_validate(analysis),
        issue_counts=counts.get(analysis.id, IssueCounts()),
    )


@analyses_router.get(
    "/{analysis_id}/issues",
    response_model=Page[IssueRead],
    summary="List an analysis's findings",
    responses=NOT_FOUND_RESPONSE,
)
async def list_analysis_issues(
    analysis_id: uuid.UUID,
    session: SessionDep,
    pagination: PaginationDep,
) -> Page[IssueRead]:
    """Most severe first, then by category and file.

    Ordering is done in SQL with an explicit severity ranking, because
    ``severity`` is stored as text and alphabetical order would put
    ``critical`` after ``high``.
    """
    await _require_analysis(session, analysis_id)

    total = (
        await session.scalar(
            select(func.count()).select_from(Issue).where(Issue.analysis_id == analysis_id)
        )
        or 0
    )
    rows = await session.scalars(
        select(Issue)
        .where(Issue.analysis_id == analysis_id)
        .order_by(
            _severity_rank(),
            Issue.category.asc(),
            Issue.file_path.asc(),
            Issue.line_start.asc(),
        )
        .limit(pagination.limit)
        .offset(pagination.offset)
    )
    return Page[IssueRead](
        items=[IssueRead.model_validate(row) for row in rows],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@analyses_router.delete(
    "/{analysis_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an analysis",
    responses={**NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
async def delete_analysis(analysis_id: uuid.UUID, session: SessionDep) -> None:
    """Delete a finished run and its findings."""
    analysis = await _require_analysis(session, analysis_id)
    if analysis.status is AnalysisStatus.RUNNING:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cannot delete an analysis while it is running.",
        )
    await session.delete(analysis)
    await session.flush()
    log.info("analysis_deleted", analysis_id=str(analysis_id))


def _severity_rank() -> ColumnElement[int]:
    """A CASE expression ordering severities by impact, not alphabet.

    ``severity`` is persisted as text, so ``ORDER BY severity`` would yield
    critical, high, low, medium. Enum members are used as the keys so
    SQLAlchemy renders them through the column's type and binds the stored
    lowercase values.
    """
    return case(
        {
            Severity.CRITICAL: 0,
            Severity.HIGH: 1,
            Severity.MEDIUM: 2,
            Severity.LOW: 3,
        },
        value=Issue.severity,
        else_=4,
    )


async def _require_analysis(session: SessionDep, analysis_id: uuid.UUID) -> Analysis:
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found.")
    return analysis


async def _issue_counts_for(
    session: SessionDep,
    analysis_ids: list[uuid.UUID],
) -> dict[uuid.UUID, IssueCounts]:
    """Tally issues per severity for several analyses in one query."""
    if not analysis_ids:
        return {}

    rows = await session.execute(
        select(Issue.analysis_id, Issue.severity, func.count())
        .where(Issue.analysis_id.in_(analysis_ids))
        .group_by(Issue.analysis_id, Issue.severity)
    )

    tallies: dict[uuid.UUID, dict[str, int]] = {}
    for analysis_id, severity, count in rows:
        bucket = tallies.setdefault(analysis_id, {})
        bucket[Severity(severity).value] = count

    return {
        analysis_id: IssueCounts(
            total=sum(bucket.values()),
            critical=bucket.get(Severity.CRITICAL.value, 0),
            high=bucket.get(Severity.HIGH.value, 0),
            medium=bucket.get(Severity.MEDIUM.value, 0),
            low=bucket.get(Severity.LOW.value, 0),
        )
        for analysis_id, bucket in tallies.items()
    }
