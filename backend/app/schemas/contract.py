"""Pydantic schemas matching the frontend contract in docs/API_CONTRACT.md.

These models allow the frontend client (src/lib/api/real.ts) to communicate with
the backend using its expected camelCase wire format, while validating inputs
and producing compliant response shapes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import IssueStatus
from app.services.github import InvalidGitHubUrlError, parse_github_url


class OneStepAnalysisCreate(BaseModel):
    """Input for POST /api/v1/analyses (one-step repository import + analysis queue)."""

    model_config = ConfigDict(populate_by_name=True)

    repo_url: str = Field(
        alias="repoUrl",
        description="GitHub repository URL.",
    )
    branch: str = Field(
        default="main",
        description="Branch to inspect.",
    )

    @field_validator("repo_url")
    @classmethod
    def _validate_github_url(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Repository URL is required.")
        try:
            return parse_github_url(value).canonical_url
        except InvalidGitHubUrlError as exc:
            raise ValueError(str(exc)) from exc


class AnalysisStepOut(BaseModel):
    """Progress step displayed in NewAnalysis.tsx."""

    id: int
    label: str
    status: str = "pending"


INITIAL_ANALYSIS_STEPS: list[dict[str, Any]] = [
    {"id": 1, "label": "Cloning repository & inspecting tree", "status": "running"},
    {"id": 2, "label": "Detecting frameworks & tech stack", "status": "pending"},
    {"id": 3, "label": "Analyzing contract compatibility", "status": "pending"},
    {"id": 4, "label": "Running static security audit", "status": "pending"},
    {"id": 5, "label": "Resolving dependency vulnerabilities", "status": "pending"},
    {"id": 6, "label": "Validating deployment readiness", "status": "pending"},
    {"id": 7, "label": "Synthesizing architecture topology", "status": "pending"},
    {"id": 8, "label": "Generating executive health score", "status": "pending"},
]


class OneStepAnalysisResponse(BaseModel):
    """Response matching CreateAnalysisResponse in frontend src/lib/api/types.ts."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    project_id: str = Field(alias="projectId")
    analysis_id: str = Field(alias="analysisId")
    name: str
    owner: str
    repo_url: str = Field(alias="repoUrl")
    stack: list[str] = Field(default_factory=list)
    health_score: int = Field(default=0, alias="healthScore")
    status: str = "analyzing"
    issue_counts: dict[str, int] = Field(
        default_factory=lambda: {
            "integration": 0,
            "security": 0,
            "dependencies": 0,
            "deployment": 0,
        },
        alias="issueCounts",
    )
    last_scanned_at: str = Field(alias="lastScannedAt")
    category_scores: dict[str, int] = Field(
        default_factory=lambda: {
            "integration": 0,
            "security": 0,
            "dependencies": 0,
            "deployment": 0,
        },
        alias="categoryScores",
    )
    severity_counts: dict[str, int] = Field(
        default_factory=lambda: {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
        },
        alias="severityCounts",
    )
    top_issues: list[dict[str, Any]] = Field(default_factory=list, alias="topIssues")
    scan_meta: dict[str, Any] = Field(default_factory=dict, alias="scanMeta")
    steps: list[dict[str, Any]] = Field(default_factory=lambda: list(INITIAL_ANALYSIS_STEPS))


def build_project_analysis_response(project: Any, analysis: Any) -> OneStepAnalysisResponse:
    """Build a OneStepAnalysisResponse / Project response for an active analysis."""
    from datetime import UTC

    now_iso = datetime.now(UTC).isoformat()
    detected = getattr(project, "detected_stack", None) or {}
    technologies = detected.get("technologies", [])
    stack_list = [t.get("name", "") for t in technologies if isinstance(t, dict) and t.get("name")]
    if not stack_list and detected.get("frameworks"):
        stack_list = list(detected.get("frameworks", []))
    if not stack_list:
        stack_list = ["TypeScript", "React"]

    owner = "repo-owner"
    source_url = getattr(project, "source_url", "") or ""
    if source_url:
        parts = [p for p in source_url.rstrip("/").split("/") if p]
        if len(parts) >= 2:
            owner = parts[-2]

    return OneStepAnalysisResponse(
        id=str(project.id),
        projectId=str(project.id),
        analysisId=str(analysis.id),
        name=project.name,
        owner=owner,
        repoUrl=source_url,
        stack=stack_list,
        healthScore=0,
        status="analyzing",
        lastScannedAt=now_iso,
        scanMeta={
            "branch": getattr(project, "source_ref", None) or "main",
            "commitSha": getattr(project, "commit_sha", None) or "",
            "durationSeconds": 0,
            "filesScanned": getattr(project, "file_count", None) or 0,
            "agentsRun": 8,
        },
        steps=list(INITIAL_ANALYSIS_STEPS),
    )


class AnalysisStatusResponse(BaseModel):
    """Response matching AnalysisStatusResponse in frontend src/lib/api/types.ts."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    project_id: str = Field(alias="projectId")
    status: str
    progress_percent: int = Field(alias="progressPercent")
    current_step_index: int = Field(alias="currentStepIndex")
    active_step: str | None = Field(default=None, alias="activeStep")
    error: str | None = None
    project: dict[str, Any] | None = None


class IssueStatusUpdate(BaseModel):
    """Payload for PATCH /api/v1/projects/{project_id}/issues/{issue_id}."""

    status: IssueStatus


class SuggestedFixOut(BaseModel):
    """Concrete fix instructions matching SuggestedFix in frontend."""

    model_config = ConfigDict(populate_by_name=True)

    summary: str
    steps: list[str] = Field(default_factory=list)
    code_before: str | None = Field(default=None, alias="codeBefore")
    code_after: str | None = Field(default=None, alias="codeAfter")
    language: str | None = "typescript"


class ProjectIssueOut(BaseModel):
    """Issue representation matching Issue in frontend src/types/issue.ts."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    project_id: str = Field(alias="projectId")
    category: str
    severity: str
    status: str
    title: str
    short_description: str = Field(alias="shortDescription")
    file_path: str = Field(default="", alias="filePath")
    line_start: int | None = Field(default=None, alias="lineStart")
    line_end: int | None = Field(default=None, alias="lineEnd")
    explanation: str
    impact: str
    suggested_fix: SuggestedFixOut = Field(alias="suggestedFix")
    meta: dict[str, Any] = Field(default_factory=dict)


def serialize_project_issue(issue: Any, project_id: uuid.UUID) -> ProjectIssueOut:
    """Format an ORM Issue into the frontend ProjectIssueOut contract shape."""
    from app.models.enums import IssueCategory

    category_str = issue.category.value if hasattr(issue.category, "value") else str(issue.category)
    if issue.category in (IssueCategory.API_CONTRACT, IssueCategory.SCHEMA):
        category_str = "integration"
    elif issue.category == IssueCategory.DEPENDENCY:
        category_str = "dependencies"
    elif issue.category == IssueCategory.SECURITY:
        category_str = "security"

    ext = (issue.file_path or "").split(".")[-1].lower() if issue.file_path else "typescript"
    lang_map = {
        "ts": "typescript",
        "tsx": "typescript",
        "js": "javascript",
        "jsx": "javascript",
        "py": "python",
        "sql": "sql",
        "json": "json",
    }
    lang = lang_map.get(ext, "typescript")

    issue_status = getattr(issue, "status", IssueStatus.OPEN)
    status_str = issue_status.value if hasattr(issue_status, "value") else str(issue_status)

    severity_str = issue.severity.value if hasattr(issue.severity, "value") else str(issue.severity)

    return ProjectIssueOut(
        id=str(issue.id),
        project_id=str(project_id),
        category=category_str,
        severity=severity_str,
        status=status_str,
        title=issue.title,
        short_description=issue.description,
        file_path=issue.file_path or "",
        line_start=issue.line_start,
        line_end=issue.line_end,
        explanation=issue.explanation or issue.description,
        impact=issue.description,
        suggested_fix=SuggestedFixOut(
            summary=issue.suggested_fix or "Review and align cross-layer contract.",
            steps=(
                [issue.suggested_fix]
                if issue.suggested_fix
                else ["Review finding and apply suggested fix."]
            ),
            code_before=issue.fix_before,
            code_after=issue.fix_after,
            language=lang,
        ),
        meta={
            "evidence": issue.evidence,
            "expected": issue.expected,
            "actual": issue.actual,
            "ruleId": issue.detected_by,
        },
    )


class ChecklistItemOut(BaseModel):
    """Deployment readiness item matching ChecklistItem in frontend."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    label: str
    status: str  # "pass" | "warn" | "fail"
    detail: str


class ArchNodeOut(BaseModel):
    """Architecture node matching ArchNode in frontend."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    label: str
    kind: str  # "frontend" | "api" | "database" | "auth" | "external" | "worker"
    tech: str
    description: str
    issue_ids: list[str] = Field(default_factory=list, alias="issueIds")
    position: dict[str, int] = Field(default_factory=lambda: {"x": 100, "y": 150})


class ArchEdgeOut(BaseModel):
    """Architecture edge matching ArchEdge in frontend."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: str
    target: str
    label: str
    status: str  # "ok" | "warning" | "broken"
    issue_ids: list[str] = Field(default_factory=list, alias="issueIds")


class ArchitectureOut(BaseModel):
    """Architecture response matching ArchitectureResponse in frontend."""

    model_config = ConfigDict(populate_by_name=True)

    nodes: list[ArchNodeOut] = Field(default_factory=list)
    edges: list[ArchEdgeOut] = Field(default_factory=list)


class ReportSectionOut(BaseModel):
    """Section matching ReportSection in frontend."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    markdown: str


class ProjectReportOut(BaseModel):
    """Project report matching ProjectReport in frontend."""

    model_config = ConfigDict(populate_by_name=True)

    generated_at: str = Field(alias="generatedAt")
    sections: list[ReportSectionOut] = Field(default_factory=list)


class UserSettingsChecks(BaseModel):
    """Check toggles inside UserSettings."""

    integration: bool = True
    security: bool = True
    dependencies: bool = True
    deployment: bool = True


class UserSettingsOut(BaseModel):
    """User preferences matching UserSettings in frontend."""

    model_config = ConfigDict(populate_by_name=True)

    display_name: str = Field(default="Alex Vance", alias="displayName")
    email: str = Field(default="developer@mergex.ai")
    theme: str = Field(default="system")
    github_connected: bool = Field(default=False, alias="githubConnected")
    github_username: str | None = Field(default=None, alias="githubUsername")
    checks: UserSettingsChecks = Field(default_factory=UserSettingsChecks)
    alert_severity: str = Field(default="high", alias="alertSeverity")


class UserSettingsUpdate(BaseModel):
    """Payload for updating UserSettings."""

    model_config = ConfigDict(populate_by_name=True)

    display_name: str | None = Field(default=None, alias="displayName")
    email: str | None = None
    theme: str | None = None
    github_connected: bool | None = Field(default=None, alias="githubConnected")
    github_username: str | None = Field(default=None, alias="githubUsername")
    checks: dict[str, bool] | None = None
    alert_severity: str | None = Field(default=None, alias="alertSeverity")
