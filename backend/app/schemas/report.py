"""The analysis report: everything the dashboard needs in one response.

Phase 5 builds the UI on this shape, so it is deliberately complete — score,
sub-scores, every finding with its explanation and concrete fix, the stack,
and the caveats. One request renders a dashboard; the issue list endpoint
remains for paging through a large result.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AnalysisStatus, IssueCategory, Severity

__all__ = ["AnalysisReport", "CategoryScoreOut", "ReportIssue", "ScoreOut"]


class CategoryScoreOut(BaseModel):
    """One category's score and tallies."""

    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=0, le=100)
    issue_count: int = Field(ge=0)
    severity_counts: dict[str, int]
    analysed: bool = Field(
        description=(
            "False when the project had nothing of this kind to check. The score "
            "is still 100, but the UI should say 'not applicable' rather than "
            "'perfect'."
        )
    )


class ScoreOut(BaseModel):
    """The health score and its breakdown."""

    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=0, le=100)
    total_issues: int = Field(ge=0)
    severity_counts: dict[str, int]
    categories: dict[str, CategoryScoreOut]
    is_floored: bool = Field(
        default=False,
        description=(
            "True when deductions exceeded 100 and the score was clamped. Two "
            "floored projects are not equally bad."
        ),
    )


class ReportIssue(BaseModel):
    """One finding, with everything needed to render it."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    rule_id: str = Field(description="Stable rule identifier, e.g. MX-API-002.")
    category: IssueCategory
    severity: Severity
    title: str
    description: str

    file_path: str | None
    line_start: int | None
    line_end: int | None
    evidence: str | None = Field(
        default=None, description="Source snippet. Credentials are masked."
    )

    expected: str | None
    actual: str | None
    confidence: float = Field(ge=0.0, le=1.0)
    fingerprint: str

    explanation: str | None
    suggested_fix: str | None
    explanation_source: str | None = Field(default=None, description="'gemini' or 'template'.")
    fix_before: str | None = None
    fix_after: str | None = None


class AnalysisReport(BaseModel):
    """The full report for one analysis."""

    model_config = ConfigDict(extra="forbid")

    analysis_id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    status: AnalysisStatus

    score: ScoreOut | None = Field(default=None, description="Null until the analysis succeeds.")
    issues: list[ReportIssue] = Field(default_factory=list, description="Most severe first.")

    stack: dict[str, Any] | None = None
    notes: list[str] = Field(
        default_factory=list,
        description=(
            "Caveats about completeness. 'We found nothing' and 'we could not "
            "look' are different outcomes and both appear here."
        ),
    )
    failed_groups: list[str] = Field(
        default_factory=list,
        description="Rule groups that crashed. Their categories are unreliable.",
    )
    counts: dict[str, int] = Field(
        default_factory=dict, description="What was examined: routes, calls, tables."
    )
    explanation_sources: dict[str, int] = Field(
        default_factory=dict,
        description="How many explanations came from the model versus templates.",
    )

    commit_sha: str | None = None
    file_count: int | None = None
    duration_ms: int | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
