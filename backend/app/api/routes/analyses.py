"""Analysis endpoints: queue a run, watch it, read its report.

Creating an analysis schedules the LangGraph pipeline as a background task
and returns immediately; the client follows progress over SSE at
``/analyses/{id}/events`` and reads the result from
``/analyses/{id}/report``.

There is deliberately no endpoint for setting an analysis's status. A run's
state is owned by the runner, so it cannot be driven into an inconsistent one
from outside.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement
from sse_starlette.sse import EventSourceResponse

from app.api.dependencies import CurrentUserDep, ImporterDep, PaginationDep, SessionDep, SettingsDep
from app.core.config import Settings
from app.core.events import EventStatus, Stage, event_bus
from app.core.logging import get_logger
from app.models.analysis import Analysis
from app.models.enums import AnalysisStage, AnalysisStatus, Severity
from app.models.issue import Issue
from app.models.project import Project
from app.models.user import User
from app.schemas.analysis import (
    AnalysisCreate,
    AnalysisRead,
    AnalysisSummary,
    IssueCounts,
    IssueRead,
)
from app.schemas.common import CONFLICT_RESPONSE, NOT_FOUND_RESPONSE, Page
from app.schemas.contract import (
    INITIAL_ANALYSIS_STEPS,
    AnalysisStatusResponse,
    OneStepAnalysisCreate,
    OneStepAnalysisResponse,
)
from app.schemas.report import (
    AnalysisReport,
    CategoryScoreOut,
    ReportIssue,
    ScoreOut,
)
from app.services.analysis_runner import AnalysisRunner
from app.services.github import InvalidGitHubUrlError, parse_github_url
from app.services.project_service import build_github_project
from app.services.repo_importer import RepoImportError, RepoTooLargeError

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
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
    current_user: CurrentUserDep,
) -> AnalysisRead:
    """Create a pending run for a project.

    Refuses if a run is already queued or in flight, so a double-click cannot
    start two clones of the same repository at once.
    """
    project = await session.get(Project, project_id)
    if project is None or project.user_id != current_user.id:
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
    # Committed here, not left to the dependency's teardown: the background
    # task opens its own session and must be able to see this row. Relying on
    # the relative ordering of dependency teardown and background execution is
    # exactly the kind of assumption that breaks on a framework upgrade.
    await session.commit()
    await session.refresh(analysis)

    event_bus.publish(analysis.id, Stage.QUEUED, EventStatus.STARTED, "Analysis queued")
    # Scheduled rather than awaited: a clone plus a full analysis takes far
    # longer than a request should. The client follows /events from here.
    background.add_task(_execute, request.app, settings, analysis.id)

    log.info("analysis_queued", analysis_id=str(analysis.id), project_id=str(project_id))
    return AnalysisRead.model_validate(analysis)


async def _execute(app: Any, settings: Settings, analysis_id: uuid.UUID) -> None:
    """Run an analysis in the background, in its own session.

    The request's session is closed by the time this runs, so a new one is
    opened from the application's factory. Failures are recorded on the row
    and published as a terminal event by the runner; this wrapper exists only
    to catch a failure of the runner itself, which would otherwise vanish
    into the task group.
    """
    factory = getattr(app.state, "session_factory", None)
    if factory is None:  # pragma: no cover - misconfiguration
        log.error("analysis_not_started", reason="no_session_factory")
        return

    runner = AnalysisRunner(settings=settings, bus=event_bus)
    try:
        async with factory() as session:
            await runner.run(session, analysis_id)
            await session.commit()
    except Exception:  # noqa: BLE001 - a background task must not die silently
        log.exception("analysis_task_crashed", analysis_id=str(analysis_id))
        event_bus.publish(
            analysis_id,
            Stage.COMPLETE,
            EventStatus.FAILED,
            "The analysis task failed unexpectedly.",
        )


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
    current_user: CurrentUserDep,
) -> Page[AnalysisSummary]:
    """Newest run first, each with its issue tallies."""
    project = await session.get(Project, project_id)
    if project is None or project.user_id != current_user.id:
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


def _build_one_step_response(
    project: Project, analysis: Analysis, repo: Any
) -> OneStepAnalysisResponse:
    now_iso = datetime.now(UTC).isoformat()
    detected = project.detected_stack or {}
    technologies = detected.get("technologies", [])
    stack_list = [t.get("name", "") for t in technologies if isinstance(t, dict) and t.get("name")]
    if not stack_list and detected.get("frameworks"):
        stack_list = list(detected.get("frameworks", []))
    if not stack_list:
        stack_list = ["TypeScript", "React"]

    owner = getattr(repo, "owner", "") or (
        project.source_url.split("/")[-2] if project.source_url else "repo-owner"
    )

    return OneStepAnalysisResponse(
        id=str(project.id),
        projectId=str(project.id),
        analysisId=str(analysis.id),
        name=project.name,
        owner=owner,
        repoUrl=project.source_url or getattr(repo, "canonical_url", ""),
        stack=stack_list,
        healthScore=0,
        status="analyzing",
        lastScannedAt=now_iso,
        scanMeta={
            "branch": project.source_ref or getattr(repo, "ref", "main") or "main",
            "commitSha": project.commit_sha or "",
            "durationSeconds": 0,
            "filesScanned": project.file_count or 0,
            "agentsRun": 8,
        },
        steps=list(INITIAL_ANALYSIS_STEPS),
    )


@analyses_router.post(
    "",
    response_model=OneStepAnalysisResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a one-step analysis from a GitHub repository URL",
    responses={
        **CONFLICT_RESPONSE,
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Invalid repository URL or import error."
        },
    },
)
async def create_one_step_analysis(
    payload: OneStepAnalysisCreate,
    session: SessionDep,
    settings: SettingsDep,
    importer: ImporterDep,
    background: BackgroundTasks,
    request: Request,
    current_user: CurrentUserDep,
) -> OneStepAnalysisResponse:
    """Import a GitHub repository (or reuse existing) and queue an analysis in one step.

    Returns the initial project structure and analysis ID immediately so the
    frontend can stream progress or poll status.
    """
    # Enforce Pro tier for private repository token scanning
    if payload.github_token:
        user_tier = getattr(current_user, "tier", "free") or "free"
        if user_tier == "free":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Private repository scanning is a Developer Pro feature. "
                    "Upgrade to unlock private repository audits."
                ),
            )

    try:
        repo = parse_github_url(payload.repo_url, ref=payload.branch)
    except InvalidGitHubUrlError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    # Check if a project with the same canonical URL already exists for this user
    project = await session.scalar(
        select(Project).where(
            Project.source_url == repo.canonical_url,
            Project.user_id == current_user.id,
        )
    )

    if project is None:
        try:
            outcome = await build_github_project(
                session,
                settings,
                importer,
                source_url=payload.repo_url,
                source_ref=payload.branch,
                name=repo.default_project_name,
                user_id=current_user.id,
                token=payload.github_token,
            )
            project = outcome.project
        except RepoTooLargeError as exc:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(exc)) from exc
        except RepoImportError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    else:
        # Check if an analysis is already queued or running
        active = await session.scalar(
            select(Analysis).where(
                Analysis.project_id == project.id,
                Analysis.status.in_([AnalysisStatus.PENDING, AnalysisStatus.RUNNING]),
            )
        )
        if active is not None:
            return _build_one_step_response(project, active, repo)

    analysis = Analysis(
        id=uuid.uuid4(),
        project_id=project.id,
        status=AnalysisStatus.PENDING,
        commit_sha=project.commit_sha,
    )
    analysis_meta: dict[str, Any] = {}
    if payload.branch:
        analysis_meta["requested_ref"] = payload.branch
    if payload.github_token:
        analysis_meta["github_token"] = payload.github_token
    if analysis_meta:
        analysis.stack = analysis_meta

    session.add(analysis)
    await session.commit()
    await session.refresh(analysis)

    event_bus.publish(analysis.id, Stage.QUEUED, EventStatus.STARTED, "Analysis queued")
    background.add_task(_execute, request.app, settings, analysis.id)

    log.info("one_step_analysis_queued", analysis_id=str(analysis.id), project_id=str(project.id))
    return _build_one_step_response(project, analysis, repo)


@analyses_router.get(
    "/{analysis_id}/status",
    response_model=AnalysisStatusResponse,
    summary="Get polling status of an analysis",
    responses=NOT_FOUND_RESPONSE,
)
async def get_analysis_status(
    analysis_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> AnalysisStatusResponse:
    analysis = await session.get(Analysis, analysis_id, options=[selectinload(Analysis.project)])
    if analysis is None or (analysis.project and analysis.project.user_id != current_user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found.")

    step_index = 0
    progress = 10
    active_step = "Cloning repository & inspecting tree"

    if analysis.status is AnalysisStatus.SUCCEEDED:
        status_str = "completed"
        progress = 100
        step_index = 8
        active_step = "Completed"
    elif analysis.status in (AnalysisStatus.FAILED, AnalysisStatus.CANCELLED):
        status_str = "failed"
        progress = 100
        step_index = 8
        active_step = "Failed"
    elif analysis.status is AnalysisStatus.PENDING:
        status_str = "running"
        progress = 15
        step_index = 0
        active_step = "Cloning repository & inspecting tree"
    else:  # AnalysisStatus.RUNNING
        status_str = "running"
        stage = analysis.stage
        if stage == AnalysisStage.IMPORTING:
            step_index = 0
            progress = 15
            active_step = "Cloning repository & inspecting tree"
        elif stage == AnalysisStage.DETECTING_STACK:
            step_index = 1
            progress = 28
            active_step = "Detecting frameworks & tech stack"
        elif stage == AnalysisStage.API_CONTRACT:
            step_index = 2
            progress = 42
            active_step = "Analyzing contract compatibility"
        elif stage == AnalysisStage.SCHEMA:
            step_index = 3
            progress = 56
            active_step = "Running static schema & model audit"
        elif stage == AnalysisStage.SECURITY:
            step_index = 4
            progress = 70
            active_step = "Scanning security and dependency CVEs"
        elif stage == AnalysisStage.SYNTHESIZING:
            step_index = 6
            progress = 85
            active_step = "Synthesizing architecture & fix suggestions"
        else:
            step_index = 3
            progress = 50
            active_step = "Analyzing repository"

    project_payload: dict[str, Any] | None = None
    if analysis.status is AnalysisStatus.SUCCEEDED and analysis.project:
        project_payload = {
            "id": str(analysis.project.id),
            "name": analysis.project.name,
            "status": "completed",
            "healthScore": analysis.health_score or 100,
        }

    return AnalysisStatusResponse(
        id=str(analysis.id),
        projectId=str(analysis.project_id),
        status=status_str,
        progressPercent=progress,
        currentStepIndex=step_index,
        activeStep=active_step,
        error=analysis.error_message,
        project=project_payload,
    )


@analyses_router.get(
    "/{analysis_id}",
    response_model=AnalysisSummary,
    summary="Get an analysis",
    responses=NOT_FOUND_RESPONSE,
)
async def get_analysis(
    analysis_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> AnalysisSummary:
    analysis = await _require_analysis(session, analysis_id, current_user)
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
    current_user: CurrentUserDep,
) -> Page[IssueRead]:
    """Most severe first, then by category and file.

    Ordering is done in SQL with an explicit severity ranking, because
    ``severity`` is stored as text and alphabetical order would put
    ``critical`` after ``high``.
    """
    await _require_analysis(session, analysis_id, current_user)

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
async def delete_analysis(
    analysis_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> None:
    """Delete a finished run and its findings."""
    analysis = await _require_analysis(session, analysis_id, current_user)
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


async def _require_analysis(
    session: SessionDep,
    analysis_id: uuid.UUID,
    user: User | None = None,
) -> Analysis:
    analysis = await session.get(Analysis, analysis_id, options=[selectinload(Analysis.project)])
    if analysis is None or (
        user is not None and analysis.project and analysis.project.user_id != user.id
    ):
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


# ---------------------------------------------------------------------------
# Live progress
# ---------------------------------------------------------------------------


@analyses_router.get(
    "/{analysis_id}/events",
    summary="Stream analysis progress (SSE)",
    responses=NOT_FOUND_RESPONSE,
)
async def stream_analysis_events(
    analysis_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> EventSourceResponse:
    """Server-Sent Events for one analysis.

    Reconnection is supported through the standard ``Last-Event-ID`` header,
    which browsers send automatically: everything the client missed is
    replayed before the live stream resumes. A client that connects after the
    run has finished still receives the whole history and the terminal event,
    rather than an open stream that never produces anything.

    The stream always ends with a ``complete`` event, on success and on
    failure alike, so a client knows when to stop listening.
    """
    analysis = await session.get(Analysis, analysis_id, options=[selectinload(Analysis.project)])
    if analysis is None or (analysis.project and analysis.project.user_id != current_user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found.")

    last_event_id = _last_event_id(request)

    async def publisher() -> Any:
        async for event in event_bus.subscribe(analysis_id, after_id=last_event_id):
            if await request.is_disconnected():
                break
            if event is None:
                # Keeps proxies from closing an idle connection. A comment
                # frame is ignored by EventSource clients.
                yield {"comment": "keep-alive"}
                continue
            yield {
                "id": str(event.id),
                "event": event.stage.value,
                "data": json.dumps(event.to_dict(), separators=(",", ":")),
            }

    return EventSourceResponse(publisher())


def _last_event_id(request: Request) -> int:
    """Parse ``Last-Event-ID``, tolerating anything a client might send."""
    raw = request.headers.get("last-event-id") or request.query_params.get("last_event_id")
    try:
        return max(0, int(raw)) if raw else 0
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@analyses_router.get(
    "/{analysis_id}/report",
    response_model=AnalysisReport,
    summary="Full analysis report",
    responses=NOT_FOUND_RESPONSE,
)
async def get_analysis_report(
    analysis_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> AnalysisReport:
    """Everything needed to render the dashboard, in one response.

    Score, sub-scores, every issue with its explanation and concrete fix, the
    detected stack, and the caveats about what could not be checked. The
    paginated issue list remains available for very large results.
    """
    analysis = await session.get(Analysis, analysis_id, options=[selectinload(Analysis.project)])
    if analysis is None or (analysis.project and analysis.project.user_id != current_user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found.")

    issues = list(
        await session.scalars(
            select(Issue)
            .where(Issue.analysis_id == analysis_id)
            .order_by(_severity_rank(), Issue.detected_by.asc(), Issue.file_path.asc())
        )
    )

    stack = analysis.stack or {}
    return AnalysisReport(
        analysis_id=analysis.id,
        project_id=analysis.project_id,
        project_name=analysis.project.name,
        status=analysis.status,
        score=_score_out(analysis.category_scores),
        issues=[_report_issue(issue) for issue in issues],
        stack={k: v for k, v in stack.items() if k not in _STACK_SIDECAR_KEYS},
        notes=list(stack.get("notes") or []),
        failed_groups=list(stack.get("failed_groups") or []),
        counts=dict(stack.get("counts") or {}),
        explanation_sources=dict(stack.get("explanation_sources") or {}),
        commit_sha=analysis.commit_sha,
        file_count=analysis.file_count,
        duration_ms=analysis.duration_ms,
        error_message=analysis.error_message,
        started_at=analysis.started_at,
        completed_at=analysis.completed_at,
    )


# Keys the runner stores alongside the stack report but which the report
# surfaces as their own fields.
_STACK_SIDECAR_KEYS = frozenset({"notes", "counts", "failed_groups", "explanation_sources"})


def _score_out(payload: dict[str, Any] | None) -> ScoreOut | None:
    """Rebuild the score from what was persisted, tolerating an older shape."""
    if not payload or "score" not in payload:
        return None
    categories = {
        name: CategoryScoreOut(
            score=int(entry.get("score", 100)),
            issue_count=int(entry.get("issue_count", 0)),
            severity_counts=dict(entry.get("severity_counts") or {}),
            analysed=bool(entry.get("analysed", True)),
        )
        for name, entry in (payload.get("categories") or {}).items()
    }
    score = int(payload["score"])
    total = int(payload.get("total_issues", 0))
    return ScoreOut(
        score=score,
        total_issues=total,
        severity_counts=dict(payload.get("severity_counts") or {}),
        categories=categories,
        is_floored=score == 0 and total > 0,
    )


def _report_issue(issue: Issue) -> ReportIssue:
    return ReportIssue(
        id=issue.id,
        rule_id=issue.detected_by,
        category=issue.category,
        severity=issue.severity,
        title=issue.title,
        description=issue.description,
        file_path=issue.file_path,
        line_start=issue.line_start,
        line_end=issue.line_end,
        evidence=issue.evidence,
        expected=issue.expected,
        actual=issue.actual,
        confidence=issue.confidence,
        fingerprint=issue.fingerprint,
        explanation=issue.explanation,
        suggested_fix=issue.suggested_fix,
        explanation_source=issue.explanation_source,
        fix_before=issue.fix_before,
        fix_after=issue.fix_after,
    )
