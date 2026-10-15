"""SQLAlchemy 2.0 ORM models.

Every model module is imported here so that ``Base.metadata`` is complete by
the time Alembic autogenerate inspects it. Importing only ``Base`` elsewhere
would silently produce migrations that drop the tables it never saw.
"""

from __future__ import annotations

from app.models.analysis import Analysis
from app.models.base import Base
from app.models.enums import (
    AnalysisStage,
    AnalysisStatus,
    IssueCategory,
    Severity,
    SourceType,
)
from app.models.issue import Issue
from app.models.project import Project

__all__ = [
    "AnalysisStage",
    "AnalysisStatus",
    "Analysis",
    "Base",
    "Issue",
    "IssueCategory",
    "Project",
    "Severity",
    "SourceType",
]
