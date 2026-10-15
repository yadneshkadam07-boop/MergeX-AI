"""The ``projects`` table: an imported codebase."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import SourceType

if TYPE_CHECKING:
    from app.models.analysis import Analysis


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A codebase a user asked MergeX to look at.

    A project records *where the code comes from*, not the code itself. Working
    trees are transient: they are re-created inside the sandbox for each
    analysis and deleted afterwards. The one exception is an uploaded ZIP,
    which has no origin to re-fetch from and so is retained at
    :attr:`upload_path` until the project is deleted.
    """

    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    source_type: Mapped[SourceType] = mapped_column(
        enum_column(SourceType, "source_type"),
        nullable=False,
    )
    # Set for SourceType.GITHUB. Normalised to https://github.com/owner/repo.
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Branch, tag or commit requested by the user; NULL means the default branch.
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Set for SourceType.ZIP: path to the retained archive inside the workspace.
    upload_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    upload_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Facts from the most recent import. NULL until the first successful one.
    detected_stack: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    file_count: Mapped[int | None] = mapped_column(nullable=True)
    # BigInteger explicitly: a byte count should not be capped at 2 GB just
    # because the current import limit is 100 MB.
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_imported_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Why the last import failed, for display. NULL when the last one worked.
    import_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    analyses: Mapped[list[Analysis]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="desc(Analysis.created_at)",
    )

    __table_args__ = (
        # A GitHub project must carry a URL; an uploaded one must not. This is
        # the invariant the API relies on when deciding how to re-import.
        CheckConstraint(
            "(source_type = 'github' AND source_url IS NOT NULL)"
            " OR (source_type = 'zip' AND source_url IS NULL)",
            name="source_matches_type",
        ),
        Index("ix_projects_created_at", "created_at"),
    )

    @property
    def is_importable(self) -> bool:
        """True when the code can still be fetched for a fresh analysis."""
        if self.source_type is SourceType.GITHUB:
            return self.source_url is not None
        return self.upload_path is not None
