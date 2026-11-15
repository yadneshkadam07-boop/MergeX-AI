"""Project endpoints: import, list, read, rename, delete."""

from __future__ import annotations

import uuid
from functools import partial
from pathlib import Path
from typing import Annotated

from anyio import to_thread
from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import case, func, select
from sqlalchemy.orm import selectinload

from app.api.dependencies import (
    CurrentUserDep,
    DemoRateLimitDep,
    ImporterDep,
    OptionalUserDep,
    PaginationDep,
    SessionDep,
    SettingsDep,
)
from app.core.events import EventStatus, Stage, event_bus
from app.core.logging import get_logger
from app.models.analysis import Analysis
from app.models.enums import AnalysisStatus, IssueCategory, IssueStatus, Severity, SourceType
from app.models.issue import Issue
from app.models.project import Project
from app.models.user import User
from app.schemas.common import (
    CONFLICT_RESPONSE,
    NOT_FOUND_RESPONSE,
    RATE_LIMITED_RESPONSE,
    UNPROCESSABLE_RESPONSE,
    Page,
)
from app.schemas.contract import (
    ArchitectureOut,
    ChecklistItemOut,
    CreateBatchPullRequestRequest,
    CreateBatchPullRequestResponse,
    CreatePullRequestRequest,
    CreatePullRequestResponse,
    IssueStatusUpdate,
    OneStepAnalysisResponse,
    ProjectIssueOut,
    ProjectReportOut,
    build_project_analysis_response,
    serialize_project_issue,
)
from app.schemas.project import (
    ProjectCreateFromGitHub,
    ProjectCreateResponse,
    ProjectImportSummary,
    ProjectRead,
    ProjectUpdate,
)
from app.services.architecture_builder import build_architecture_topology
from app.services.demo import DEMO_FIXTURE, DemoUnavailableError, pack_demo_archive
from app.services.deploy_checklist_builder import build_deploy_checklist
from app.services.github import InvalidGitHubUrlError
from app.services.github_pr import (
    create_batch_pull_request,
    create_pull_request_for_issue,
)
from app.services.project_service import (
    ImportOutcome,
    UploadTooLargeError,
    build_github_project,
    build_zip_project,
    stream_upload_to_disk,
)
from app.services.repo_importer import RepoImportError, RepoTooLargeError
from app.services.report_builder import build_project_executive_report

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
    current_user: CurrentUserDep,
) -> ProjectCreateResponse:
    """Clone a repository, detect its stack, and record the project.

    The clone is deleted before the response is sent; each analysis takes a
    fresh copy. Nothing from the repository is executed.
    """
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
        outcome = await build_github_project(
            session,
            settings,
            importer,
            source_url=payload.source_url,
            source_ref=payload.source_ref,
            name=payload.name,
            user_id=current_user.id,
            token=payload.github_token,
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
    current_user: CurrentUserDep,
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
            user_id=current_user.id,
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


@router.post(
    "/demo",
    response_model=ProjectCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Import the bundled demo project",
    responses=_IMPORT_RESPONSES,
)
async def create_demo_project(
    session: SessionDep,
    importer: ImporterDep,
    _limit: DemoRateLimitDep,
    current_user: OptionalUserDep = None,
) -> ProjectCreateResponse:
    """Import the seeded fixture, so the product can be demonstrated with no
    repository to hand.

    The fixture is packed into a ZIP and handed to the ordinary upload path,
    so this exercises the same import code a real upload does rather than
    introducing a second one. There is no user input to validate: the source
    is a directory inside the image.
    """
    project_id = uuid.uuid4()
    archive_path = importer.upload_destination(project_id)

    try:
        await to_thread.run_sync(partial(pack_demo_archive, archive_path))
    except DemoUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    try:
        outcome = await build_zip_project(
            session,
            importer,
            project_id=project_id,
            archive_path=archive_path,
            filename=f"{DEMO_FIXTURE}.zip",
            name="Demo — React + FastAPI (seeded bugs)",
            is_demo=True,
            user_id=current_user.id if current_user else None,
        )
    except RepoImportError as exc:  # pragma: no cover - the fixture is valid
        await to_thread.run_sync(partial(archive_path.unlink, missing_ok=True))
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    log.info("demo_project_created", project_id=str(project_id))
    return ProjectCreateResponse(
        project=ProjectRead.model_validate(outcome.project),
        import_summary=_summarise(outcome),
    )


async def _populate_project_metrics(session: SessionDep, project: Project) -> ProjectRead:
    latest_analysis = await session.scalar(
        select(Analysis)
        .where(Analysis.project_id == project.id)
        .order_by(Analysis.created_at.desc(), Analysis.id.desc())
        .limit(1)
    )

    # Find the most recent succeeded analysis for robust metrics calculation
    latest_succeeded = latest_analysis if (
        latest_analysis
        and (
            latest_analysis.status == AnalysisStatus.SUCCEEDED
            or str(getattr(latest_analysis.status, "value", latest_analysis.status)).lower() == "succeeded"
        )
    ) else None

    if latest_succeeded is None:
        latest_succeeded = await session.scalar(
            select(Analysis)
            .where(
                Analysis.project_id == project.id,
                Analysis.status == AnalysisStatus.SUCCEEDED,
            )
            .order_by(Analysis.created_at.desc(), Analysis.id.desc())
            .limit(1)
        )

    status_str = "completed"
    health_score = 100
    issue_counts = {"integration": 0, "security": 0, "dependencies": 0, "deployment": 0}
    cat_scores = {"integration": 100, "security": 100, "dependencies": 100, "deployment": 100}
    sev_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    top_issues: list[dict[str, Any]] = []

    if latest_analysis:
        status_val = str(getattr(latest_analysis.status, "value", latest_analysis.status)).lower()
        if status_val in ("pending", "running"):
            status_str = "analyzing"
        elif status_val == "failed" and latest_succeeded is None:
            status_str = "failed"
        else:
            status_str = "completed"
    elif project.import_error:
        status_str = "failed"

    # Populate findings and score from the latest succeeded analysis (or latest if none succeeded)
    target_analysis = latest_succeeded or latest_analysis
    if target_analysis:
        # Check explicit health_score on the analysis model
        if target_analysis.health_score is not None:
            health_score = int(target_analysis.health_score)
        elif target_analysis.category_scores and "score" in target_analysis.category_scores:
            health_score = int(target_analysis.category_scores["score"])

        # Query all issues for this analysis from the database to guarantee accurate counts
        order_clause = (
            case(
                {
                    Severity.CRITICAL: 0,
                    Severity.HIGH: 1,
                    Severity.MEDIUM: 2,
                    Severity.LOW: 3,
                },
                value=Issue.severity,
                else_=4,
            ),
            Issue.detected_by.asc(),
            Issue.file_path.asc(),
        )
        all_issues = list((await session.scalars(
            select(Issue)
            .where(Issue.analysis_id == target_analysis.id)
            .order_by(*order_clause)
        )).all())

        if not all_issues:
            all_issues = list((await session.scalars(
                select(Issue)
                .join(Analysis, Issue.analysis_id == Analysis.id)
                .where(Analysis.project_id == project.id)
                .order_by(*order_clause)
            )).all())

        if all_issues:
            def _cat_str(i: Issue) -> str:
                return str(getattr(i.category, "value", i.category)).lower().strip()

            def _sev_str(i: Issue) -> str:
                return str(getattr(i.severity, "value", i.severity)).lower().strip()

            def _stat_str(i: Issue) -> str:
                return str(getattr(i.status, "value", i.status)).lower().strip()

            open_issues = [i for i in all_issues if _stat_str(i) in ("open", "detected", "")]

            int_count = sum(1 for i in all_issues if _cat_str(i) in ("api_contract", "schema", "integration"))
            sec_count = sum(1 for i in all_issues if _cat_str(i) == "security")
            dep_count = sum(1 for i in all_issues if _cat_str(i) in ("dependency", "dependencies"))
            deploy_count = sum(
                1 for i in all_issues
                if _cat_str(i) not in ("api_contract", "schema", "integration", "security", "dependency", "dependencies")
            )

            issue_counts = {
                "integration": int_count,
                "security": sec_count,
                "dependencies": dep_count,
                "deployment": deploy_count,
            }

            sev_counts = {
                "critical": sum(1 for i in all_issues if _sev_str(i) == "critical"),
                "high": sum(1 for i in all_issues if _sev_str(i) == "high"),
                "medium": sum(1 for i in all_issues if _sev_str(i) == "medium"),
                "low": sum(1 for i in all_issues if _sev_str(i) == "low"),
            }

            if any(_stat_str(i) in ("resolved", "fixed", "ignored") for i in all_issues):
                open_sevs = {
                    "critical": sum(1 for i in open_issues if _sev_str(i) == "critical"),
                    "high": sum(1 for i in open_issues if _sev_str(i) == "high"),
                    "medium": sum(1 for i in open_issues if _sev_str(i) == "medium"),
                    "low": sum(1 for i in open_issues if _sev_str(i) == "low"),
                }
                health_score = max(
                    0,
                    100 - (open_sevs["critical"] * 15 + open_sevs["high"] * 8 + open_sevs["medium"] * 3 + open_sevs["low"] * 1),
                )
            elif target_analysis.health_score is None and (not target_analysis.category_scores or "score" not in target_analysis.category_scores):
                health_score = max(
                    0,
                    100 - (sev_counts["critical"] * 15 + sev_counts["high"] * 8 + sev_counts["medium"] * 3 + sev_counts["low"] * 1),
                )

            top_rows = all_issues[:5]
            for iss in top_rows:
                c_val = _cat_str(iss)
                c_name = "dependencies" if c_val in ("dependency", "dependencies") else (
                    "security" if c_val == "security" else "integration"
                )
                top_issues.append({
                    "id": str(iss.id),
                    "title": iss.title,
                    "category": c_name,
                    "severity": _sev_str(iss),
                    "filePath": iss.file_path,
                    "shortDescription": iss.description[:120] if iss.description else "",
                })
        elif target_analysis.category_scores:
            cat_data = target_analysis.category_scores or {}
            categories = cat_data.get("categories") or {}
            dep_count = int(categories.get("dependency", {}).get("issue_count", 0))
            sec_count = int(categories.get("security", {}).get("issue_count", 0))
            api_count = int(categories.get("api_contract", {}).get("issue_count", 0))
            schema_count = int(categories.get("schema", {}).get("issue_count", 0))
            issue_counts = {
                "integration": api_count + schema_count,
                "security": sec_count,
                "dependencies": dep_count,
                "deployment": 0,
            }

            dep_s = int(categories.get("dependency", {}).get("score", 100))
            sec_s = int(categories.get("security", {}).get("score", 100))
            api_s = int(categories.get("api_contract", {}).get("score", 100))
            sch_s = int(categories.get("schema", {}).get("score", 100))
            cat_scores = {
                "integration": min(api_s, sch_s),
                "security": sec_s,
                "dependencies": dep_s,
                "deployment": 100,
            }

            raw_sevs = cat_data.get("severity_counts") or {}
            sev_counts = {
                "critical": int(raw_sevs.get("critical", 0)),
                "high": int(raw_sevs.get("high", 0)),
                "medium": int(raw_sevs.get("medium", 0)),
                "low": int(raw_sevs.get("low", 0)),
            }
    elif project.import_error:
        status_str = "failed"

    stack_list: list[str] = []
    if project.detected_stack:
        for tech in project.detected_stack.get("technologies", []):
            if isinstance(tech, dict) and tech.get("name"):
                stack_list.append(tech["name"])
        if not stack_list and project.detected_stack.get("frameworks"):
            stack_list.extend(project.detected_stack.get("frameworks", []))
        if not stack_list:
            for k in ("frontend", "backend", "database", "build", "package_managers"):
                vals = project.detected_stack.get(k) or []
                for v in vals:
                    if isinstance(v, str) and v not in stack_list:
                        stack_list.append(v)
    if not stack_list:
        stack_list = ["React", "Node.js"]

    duration_sec = 0
    if latest_analysis and latest_analysis.duration_ms:
        duration_sec = max(1, latest_analysis.duration_ms // 1000)

    scan_meta = {
        "branch": project.source_ref or "main",
        "commitSha": (latest_analysis.commit_sha if latest_analysis and latest_analysis.commit_sha else project.commit_sha or "HEAD")[:7],
        "durationSeconds": duration_sec,
        "filesScanned": (latest_analysis.file_count if latest_analysis and latest_analysis.file_count else project.file_count) or 0,
        "agentsRun": 4,
    }

    base = ProjectRead.model_validate(project)
    base.status = status_str
    base.health_score = health_score
    base.issue_counts = issue_counts
    base.category_scores = cat_scores
    base.severity_counts = sev_counts
    base.top_issues = top_issues
    base.scan_meta = scan_meta
    base.stack = stack_list
    return base


@router.get("", response_model=Page[ProjectRead], summary="List projects")
async def list_projects(
    session: SessionDep,
    pagination: PaginationDep,
    current_user: CurrentUserDep,
) -> Page[ProjectRead]:
    """Most recently created first, scoped to the authenticated user."""
    base_stmt = select(Project).where(Project.user_id == current_user.id)
    total = await session.scalar(select(func.count()).select_from(base_stmt.subquery())) or 0
    rows = (await session.scalars(
        base_stmt.order_by(Project.created_at.desc(), Project.id.desc())
        .limit(pagination.limit)
        .offset(pagination.offset)
    )).all()
    items = [await _populate_project_metrics(session, row) for row in rows]
    return Page[ProjectRead](
        items=items,
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
async def get_project(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user: OptionalUserDep = None,
) -> ProjectRead:
    project = await _require_project(session, project_id, current_user)
    return await _populate_project_metrics(session, project)


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
    current_user: CurrentUserDep,
) -> ProjectRead:
    """Only the display name is mutable; a source change means a new import."""
    project = await _require_project(session, project_id, current_user)
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
async def delete_project(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> None:
    """Delete a project, its analyses and issues, and any retained archive."""
    project = await _require_project(session, project_id, current_user)
    retained = project.upload_path

    # Analyses and issues go via ON DELETE CASCADE.
    await session.delete(project)
    await session.flush()

    if retained and project.source_type is SourceType.ZIP:
        await to_thread.run_sync(partial(Path(retained).unlink, missing_ok=True))

    log.info("project_deleted", project_id=str(project_id))


@router.get(
    "/{project_id}/issues",
    response_model=list[ProjectIssueOut],
    summary="List issues for a project",
    responses=NOT_FOUND_RESPONSE,
)
async def list_project_issues(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user: OptionalUserDep = None,
    category: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    q: str | None = None,
) -> list[ProjectIssueOut]:
    """Return issues from the project's latest completed analysis run.

    Supports filtering by category, severity, status, and search query.
    If the project has no completed analysis yet, returns an empty list.
    """
    await _require_project(session, project_id, current_user)

    latest_analysis = await session.scalar(
        select(Analysis)
        .where(
            Analysis.project_id == project_id,
            Analysis.status == AnalysisStatus.SUCCEEDED,
        )
        .order_by(Analysis.created_at.desc(), Analysis.id.desc())
        .limit(1)
    )
    if latest_analysis is None:
        return []

    stmt = select(Issue).where(Issue.analysis_id == latest_analysis.id)

    if category:
        cat_lower = category.lower().strip()
        if cat_lower == "integration":
            stmt = stmt.where(
                Issue.category.in_([IssueCategory.API_CONTRACT, IssueCategory.SCHEMA])
            )
        elif cat_lower in ("dependencies", "dependency"):
            stmt = stmt.where(Issue.category == IssueCategory.DEPENDENCY)
        elif cat_lower == "security":
            stmt = stmt.where(Issue.category == IssueCategory.SECURITY)
        else:
            try:
                matched_enum = IssueCategory(cat_lower)
                stmt = stmt.where(Issue.category == matched_enum)
            except ValueError:
                stmt = stmt.where(Issue.category == cat_lower)

    if severity:
        sev_lower = severity.lower().strip()
        try:
            matched_sev = Severity(sev_lower)
            stmt = stmt.where(Issue.severity == matched_sev)
        except ValueError:
            stmt = stmt.where(Issue.severity == sev_lower)

    if status:
        stat_lower = status.lower().strip()
        try:
            matched_stat = IssueStatus(stat_lower)
            stmt = stmt.where(Issue.status == matched_stat)
        except ValueError:
            stmt = stmt.where(Issue.status == stat_lower)

    if q:
        query_pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            Issue.title.ilike(query_pattern)
            | Issue.description.ilike(query_pattern)
            | Issue.file_path.ilike(query_pattern)
        )

    stmt = stmt.order_by(
        case(
            {
                Severity.CRITICAL: 0,
                Severity.HIGH: 1,
                Severity.MEDIUM: 2,
                Severity.LOW: 3,
            },
            value=Issue.severity,
            else_=4,
        ),
        Issue.file_path.asc(),
        Issue.line_start.asc(),
    )

    issues = (await session.scalars(stmt)).all()
    return [serialize_project_issue(i, project_id) for i in issues]


@router.get(
    "/{project_id}/issues/{issue_id}",
    response_model=ProjectIssueOut,
    summary="Get a project issue by ID",
    responses=NOT_FOUND_RESPONSE,
)
async def get_project_issue(
    project_id: uuid.UUID,
    issue_id: uuid.UUID,
    session: SessionDep,
    current_user: OptionalUserDep = None,
) -> ProjectIssueOut:
    """Retrieve a single issue by ID for a project."""
    await _require_project(session, project_id, current_user)

    issue = await session.get(Issue, issue_id, options=[selectinload(Issue.analysis)])
    if issue is None or issue.analysis.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue not found.")

    return serialize_project_issue(issue, project_id)


@router.patch(
    "/{project_id}/issues/{issue_id}",
    response_model=ProjectIssueOut,
    summary="Update project issue status",
    responses=NOT_FOUND_RESPONSE,
)
async def update_project_issue_status(
    project_id: uuid.UUID,
    issue_id: uuid.UUID,
    payload: IssueStatusUpdate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> ProjectIssueOut:
    """Update an issue's status (open, resolved, ignored)."""
    await _require_project(session, project_id, current_user)

    issue = await session.get(Issue, issue_id, options=[selectinload(Issue.analysis)])
    if issue is None or issue.analysis.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue not found.")

    issue.status = payload.status
    await session.flush()
    await session.refresh(issue)

    return serialize_project_issue(issue, project_id)


@router.post(
    "/{project_id}/issues/{issue_id}/create-pr",
    response_model=CreatePullRequestResponse,
    summary="Create GitHub Pull Request for issue fix",
    responses=NOT_FOUND_RESPONSE,
)
async def create_issue_pr(
    project_id: uuid.UUID,
    issue_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    current_user: OptionalUserDep = None,
    payload: CreatePullRequestRequest | None = None,
    github_token_header: str | None = Header(None, alias="x-github-token"),
) -> CreatePullRequestResponse:
    """Create a pull request on GitHub applying the suggested fix for an issue."""
    project = await _require_project(session, project_id, current_user)

    issue = await session.get(Issue, issue_id, options=[selectinload(Issue.analysis)])
    if issue is None or issue.analysis.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue not found.")

    explicit_token = (payload.github_token if payload else None) or github_token_header
    token = explicit_token or settings.github_token
    token_str = token.get_secret_value() if hasattr(token, "get_secret_value") else str(token or "")

    repo_url = getattr(project, "source_url", None) or "https://github.com/yadneshkadam07-boop/MergeX-AI"

    res = await create_pull_request_for_issue(
        token=token_str if token_str else None,
        repo_url=repo_url,
        issue=issue,
    )

    issue.status = IssueStatus.RESOLVED
    await session.flush()

    return CreatePullRequestResponse(
        pr_url=res["prUrl"],
        pr_number=res["prNumber"],
        branch=res["branch"],
        status=res.get("status", "created"),
        note=res.get("note"),
    )


@router.post(
    "/{project_id}/create-batch-pr",
    response_model=CreateBatchPullRequestResponse,
    summary="Create consolidated GitHub Pull Request for multiple issues",
    responses=NOT_FOUND_RESPONSE,
)
async def create_batch_issue_pr(
    project_id: uuid.UUID,
    payload: CreateBatchPullRequestRequest,
    session: SessionDep,
    settings: SettingsDep,
    current_user: OptionalUserDep = None,
    github_token_header: str | None = Header(None, alias="x-github-token"),
) -> CreateBatchPullRequestResponse:
    """Create a single combined pull request on GitHub resolving multiple issues."""
    project = await _require_project(session, project_id, current_user)

    if not payload.issue_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No issues provided for batch PR.")

    stmt = (
        select(Issue)
        .join(Issue.analysis)
        .where(
            Analysis.project_id == project_id,
            Issue.id.in_(payload.issue_ids),
        )
    )
    result = await session.scalars(stmt)
    issues = list(result.all())

    if not issues:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No matching issues found for this project.")

    explicit_token = payload.github_token or github_token_header
    token = explicit_token or settings.github_token
    token_str = token.get_secret_value() if hasattr(token, "get_secret_value") else str(token or "")

    repo_url = getattr(project, "source_url", None) or "https://github.com/yadneshkadam07-boop/MergeX-AI"

    res = await create_batch_pull_request(
        token=token_str if token_str else None,
        repo_url=repo_url,
        issues=issues,
    )

    for iss in issues:
        iss.status = IssueStatus.RESOLVED

    await session.flush()

    return CreateBatchPullRequestResponse(
        pr_url=res["prUrl"],
        pr_number=res["prNumber"],
        branch=res["branch"],
        status=res.get("status", "created"),
        resolved_issue_ids=res.get("resolvedIssueIds", [str(i.id) for i in issues]),
        note=res.get("note"),
    )


@router.post(
    "/{project_id}/rescan",
    response_model=OneStepAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Rescan a project",
    responses={**NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
async def rescan_project(
    project_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
    current_user: CurrentUserDep,
) -> OneStepAnalysisResponse:
    """Initiate an immediate re-scan of the project on its current repository and branch."""
    project = await _require_project(session, project_id, current_user)

    # Check if an analysis is already pending or running for that project
    active = await session.scalar(
        select(Analysis).where(
            Analysis.project_id == project.id,
            Analysis.status.in_([AnalysisStatus.PENDING, AnalysisStatus.RUNNING]),
        )
    )
    if active is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "An analysis is already running for this project.",
        )

    analysis = Analysis(
        id=uuid.uuid4(),
        project_id=project.id,
        status=AnalysisStatus.PENDING,
        commit_sha=project.commit_sha,
    )
    if project.source_ref:
        analysis.stack = {"requested_ref": project.source_ref}

    session.add(analysis)
    await session.commit()
    await session.refresh(analysis)

    event_bus.publish(analysis.id, Stage.QUEUED, EventStatus.STARTED, "Analysis queued")
    from app.api.routes.analyses import _execute

    background.add_task(_execute, request.app, settings, analysis.id)

    log.info("project_rescan_queued", analysis_id=str(analysis.id), project_id=str(project.id))
    return build_project_analysis_response(project, analysis)


@router.get(
    "/{project_id}/report",
    response_model=ProjectReportOut,
    summary="Get executive markdown report for a project",
    responses=NOT_FOUND_RESPONSE,
)
async def get_project_report(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user: OptionalUserDep = None,
) -> ProjectReportOut:
    """Generate or retrieve the structured multi-section Markdown report."""
    project = await _require_project(session, project_id, current_user)

    latest_analysis = await session.scalar(
        select(Analysis)
        .where(Analysis.project_id == project_id, Analysis.status == AnalysisStatus.SUCCEEDED)
        .order_by(Analysis.created_at.desc(), Analysis.id.desc())
        .limit(1)
    )

    issues: list[Issue] = []
    if latest_analysis is not None:
        issues = list(
            await session.scalars(
                select(Issue)
                .where(Issue.analysis_id == latest_analysis.id)
                .order_by(
                    case(
                        {
                            Severity.CRITICAL: 0,
                            Severity.HIGH: 1,
                            Severity.MEDIUM: 2,
                            Severity.LOW: 3,
                        },
                        value=Issue.severity,
                        else_=4,
                    ),
                    Issue.file_path.asc(),
                )
            )
        )

    return build_project_executive_report(project, latest_analysis, issues)


@router.get(
    "/{project_id}/deploy-checklist",
    response_model=list[ChecklistItemOut],
    summary="Get deployment readiness checklist",
    responses=NOT_FOUND_RESPONSE,
)
async def get_project_deploy_checklist(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user: OptionalUserDep = None,
) -> list[ChecklistItemOut]:
    """Return deployment checklist items derived from the latest findings."""
    project = await _require_project(session, project_id, current_user)

    latest_analysis = await session.scalar(
        select(Analysis)
        .where(Analysis.project_id == project_id, Analysis.status == AnalysisStatus.SUCCEEDED)
        .order_by(Analysis.created_at.desc(), Analysis.id.desc())
        .limit(1)
    )

    issues: list[Issue] = []
    if latest_analysis is not None:
        issues = list(
            await session.scalars(select(Issue).where(Issue.analysis_id == latest_analysis.id))
        )

    return build_deploy_checklist(project, latest_analysis, issues)


@router.get(
    "/{project_id}/architecture",
    response_model=ArchitectureOut,
    summary="Get architecture nodes and edges",
    responses=NOT_FOUND_RESPONSE,
)
async def get_project_architecture(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user: OptionalUserDep = None,
) -> ArchitectureOut:
    """Return interactive architecture nodes and edges with attached findings."""
    project = await _require_project(session, project_id, current_user)

    latest_analysis = await session.scalar(
        select(Analysis)
        .where(Analysis.project_id == project_id, Analysis.status == AnalysisStatus.SUCCEEDED)
        .order_by(Analysis.created_at.desc(), Analysis.id.desc())
        .limit(1)
    )

    issues: list[Issue] = []
    if latest_analysis is not None:
        issues = list(
            await session.scalars(select(Issue).where(Issue.analysis_id == latest_analysis.id))
        )

    return build_architecture_topology(project, latest_analysis, issues)


async def _require_project(
    session: SessionDep,
    project_id: uuid.UUID,
    user: User | None = None,
) -> Project:
    """Load a project or raise 404."""
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Project with ID '{project_id}' could not be found."
        )
    if user is not None and project.user_id is not None and project.user_id != user.id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Project with ID '{project_id}' could not be found."
        )
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
