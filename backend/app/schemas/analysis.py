"""Analysis request and response models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AnalysisStage, AnalysisStatus, IssueCategory, Severity


class AnalysisCreate(BaseModel):
    """Queue a new analysis run for a project.

    Deliberately almost empty: what gets analysed is determined by the
    project's recorded source, not by the request, so a run is reproducible.
    """

    model_config = ConfigDict(extra="forbid")

    source_ref: str | None = Field(
        default=None,
        max_length=255,
        description=(
            "Override the branch, tag or commit for this run only. "
            "Defaults to the project's configured ref."
        ),
    )


class IssueCounts(BaseModel):
    """Issue tallies, so a list view needs no second request."""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(default=0, ge=0)
    critical: int = Field(default=0, ge=0)
    high: int = Field(default=0, ge=0)
    medium: int = Field(default=0, ge=0)
    low: int = Field(default=0, ge=0)


class AnalysisRead(BaseModel):
    """An analysis run as the API returns it."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    project_id: uuid.UUID

    status: AnalysisStatus
    stage: AnalysisStage | None

    health_score: int | None = Field(default=None, ge=0, le=100)
    category_scores: dict[str, Any] | None
    stack: dict[str, Any] | None

    commit_sha: str | None
    file_count: int | None

    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    error_message: str | None
    ai_explanations_available: bool

    created_at: datetime
    updated_at: datetime


class AnalysisSummary(BaseModel):
    """An analysis plus its issue tallies, for dashboards and list views."""

    model_config = ConfigDict(extra="forbid")

    analysis: AnalysisRead
    issue_counts: IssueCounts


class IssueRead(BaseModel):
    """A single finding.

    ``detected_by`` names the deterministic rule that produced it.
    ``explanation`` and ``suggested_fix`` are the only model-generated fields
    and are null when no API key was configured.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    analysis_id: uuid.UUID

    category: IssueCategory
    severity: Severity
    title: str
    description: str

    file_path: str | None
    line_start: int | None
    line_end: int | None
    evidence: str | None

    expected: str | None
    actual: str | None

    detected_by: str
    confidence: float = Field(ge=0.0, le=1.0)
    fingerprint: str

    explanation: str | None
    suggested_fix: str | None

    created_at: datetime
