"""Enumerations shared by the ORM models and the API schemas.

All of these are persisted as ``VARCHAR`` with a ``CHECK`` constraint rather
than as native PostgreSQL ``ENUM`` types. Two reasons:

1. Adding a value to a native PG enum requires ``ALTER TYPE ... ADD VALUE``,
   which cannot run inside a transaction block on older servers and makes
   migrations awkward. The issue taxonomy will grow.
2. The same DDL then works on SQLite, so the test suite does not need a
   running database.

Values are lowercase and are what lands in the database and on the wire; see
``values_callable`` in :mod:`app.models.base`.
"""

from __future__ import annotations

from enum import StrEnum


class SourceType(StrEnum):
    """Where a project's code came from."""

    GITHUB = "github"
    ZIP = "zip"


class AnalysisStatus(StrEnum):
    """Lifecycle of one analysis run."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        """True when no further transition is expected."""
        return self in {AnalysisStatus.SUCCEEDED, AnalysisStatus.FAILED, AnalysisStatus.CANCELLED}


class AnalysisStage(StrEnum):
    """The agent currently executing, streamed to the UI over SSE."""

    IMPORTING = "importing"
    DETECTING_STACK = "detecting_stack"
    API_CONTRACT = "api_contract"
    SCHEMA = "schema"
    SECURITY = "security"
    SYNTHESIZING = "synthesizing"


class IssueCategory(StrEnum):
    """Which cross-layer check produced a finding."""

    API_CONTRACT = "api_contract"
    SCHEMA = "schema"
    SECURITY = "security"
    DEPENDENCY = "dependency"


class IssueStatus(StrEnum):
    """Workflow state of a finding in the project dashboard."""

    OPEN = "open"
    RESOLVED = "resolved"
    IGNORED = "ignored"


class Severity(StrEnum):
    """Impact ranking. Drives the health-score deduction."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def score_penalty(self) -> int:
        """Points deducted from the health score for one issue at this level."""
        return _SCORE_PENALTIES[self]


# Defined by the product spec: start at 100, deduct per issue, floor at 0.
_SCORE_PENALTIES: dict[Severity, int] = {
    Severity.CRITICAL: 15,
    Severity.HIGH: 8,
    Severity.MEDIUM: 3,
    Severity.LOW: 1,
}

# Most severe first. Used for ordering issue lists and for ranking.
SEVERITY_ORDER: tuple[Severity, ...] = (
    Severity.CRITICAL,
    Severity.HIGH,
    Severity.MEDIUM,
    Severity.LOW,
)
