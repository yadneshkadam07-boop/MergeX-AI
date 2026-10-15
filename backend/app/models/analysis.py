"""The ``analyses`` table: one validation run over a project."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import AnalysisStage, AnalysisStatus

if TYPE_CHECKING:
    from app.models.issue import Issue
    from app.models.project import Project


class Analysis(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One run of the agent pipeline against one snapshot of a project.

    Runs are append-only history: re-analysing a project creates a new row
    rather than mutating the previous one, so a score can be compared over
    time and a regression can be attributed to a commit.
    """

    __tablename__ = "analyses"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )

    status: Mapped[AnalysisStatus] = mapped_column(
        enum_column(AnalysisStatus, "analysis_status"),
        nullable=False,
        default=AnalysisStatus.PENDING,
    )
    # Which agent is running, for the live progress stepper. NULL once terminal.
    stage: Mapped[AnalysisStage | None] = mapped_column(
        enum_column(AnalysisStage, "analysis_stage"),
        nullable=True,
    )

    # --- Results. All NULL until the run succeeds. -------------------------
    health_score: Mapped[int | None] = mapped_column(nullable=True)
    # {"api_contract": 82, "schema": 95, "security": 60, "dependency": 100}
    category_scores: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    # Snapshot of the stack as seen by this run, so a historical analysis
    # still explains itself after the project's stack has changed.
    stack: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)

    # --- What was analysed -------------------------------------------------
    commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    file_count: Mapped[int | None] = mapped_column(nullable=True)

    # --- Timing and failure ------------------------------------------------
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    # Operator-facing reason for FAILED. Never contains a stack trace.
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # True when findings were reported without Gemini explanations, so the UI
    # can say so instead of looking like the model produced nothing.
    ai_explanations_available: Mapped[bool] = mapped_column(nullable=False, default=False)

    project: Mapped[Project] = relationship(back_populates="analyses")
    issues: Mapped[list[Issue]] = relationship(
        back_populates="analysis",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "health_score IS NULL OR (health_score >= 0 AND health_score <= 100)",
            name="health_score_in_range",
        ),
        # Listing a project's runs newest-first is the hot query.
        Index("ix_analyses_project_id_created_at", "project_id", "created_at"),
        Index("ix_analyses_status", "status"),
    )

    @property
    def is_terminal(self) -> bool:
        return self.status.is_terminal
