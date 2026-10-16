"""The ``issues`` table: one finding produced by a deterministic rule."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import IssueCategory, Severity

if TYPE_CHECKING:
    from app.models.analysis import Analysis


class Issue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single cross-layer defect found in one analysis run.

    Every row is produced by a deterministic rule, recorded in
    :attr:`detected_by`. :attr:`suggested_fix` and :attr:`explanation` are the
    only language-model contributions and are nullable precisely because the
    finding does not depend on them -- an analysis run with no Gemini key
    stores the same rows with those two columns empty.
    """

    __tablename__ = "issues"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"),
        nullable=False,
    )

    category: Mapped[IssueCategory] = mapped_column(
        enum_column(IssueCategory, "issue_category"),
        nullable=False,
    )
    severity: Mapped[Severity] = mapped_column(
        enum_column(Severity, "issue_severity"),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # --- Location. NULL for findings that are not tied to a line, such as a
    # vulnerable transitive dependency. ------------------------------------
    file_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    line_start: Mapped[int | None] = mapped_column(nullable=True)
    line_end: Mapped[int | None] = mapped_column(nullable=True)
    # The offending source lines, so the UI need not re-read the repository
    # (which no longer exists once the sandbox is cleaned up).
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- The cross-layer comparison, in plain terms -----------------------
    expected: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Provenance --------------------------------------------------------
    # Stable rule identifier, e.g. "MX-API-001". The contract with fixtures.
    detected_by: Mapped[str] = mapped_column(String(50), nullable=False)
    # Rule's own certainty, 0..1. Not the model's.
    confidence: Mapped[float] = mapped_column(nullable=False, default=1.0)
    # Stable hash of the defect's identity, used to dedupe within a run and to
    # recognise the same issue across runs.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    # --- Explanation layer (optional by design) ----------------------------
    # Written by the synthesiser. `explanation_source` records whether the
    # prose came from Gemini or from the rule's offline template, so the UI
    # can say so and so a regression in model quality is visible.
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_fix: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # The concrete edit, kept as two columns rather than folded into
    # `suggested_fix` so the UI can render a diff and offer a copy button
    # without parsing prose.
    fix_before: Mapped[str | None] = mapped_column(Text, nullable=True)
    fix_after: Mapped[str | None] = mapped_column(Text, nullable=True)

    analysis: Mapped[Analysis] = relationship(back_populates="issues")

    __table_args__ = (
        # Deduplication is enforced by the database, not just by the
        # synthesizer: the same defect cannot be recorded twice in one run.
        UniqueConstraint("analysis_id", "fingerprint", name="analysis_id_fingerprint"),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="confidence_in_range",
        ),
        CheckConstraint(
            "line_start IS NULL OR line_end IS NULL OR line_end >= line_start",
            name="line_range_ordered",
        ),
        Index("ix_issues_analysis_id_severity", "analysis_id", "severity"),
        Index("ix_issues_analysis_id_category", "analysis_id", "category"),
    )

    @property
    def score_penalty(self) -> int:
        """Health-score points this issue costs."""
        return self.severity.score_penalty
