"""The state object the LangGraph workflow threads through its nodes.

LangGraph merges concurrent writes to the same key, so any field three
parallel branches can write needs a reducer. ``findings`` and ``group_errors``
use list concatenation; everything else is written by exactly one node.

``group_errors`` is what makes a crashed branch survivable: a node that fails
records the failure here and returns, the other branches finish normally, and
the synthesiser marks that category as failed in the report rather than
reporting it as clean.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, TypedDict

from app.analysis.findings import Finding
from app.models.enums import IssueCategory
from app.services.extractors.backend_routes import RouteExtraction
from app.services.extractors.db_schema import DbSchema
from app.services.extractors.frontend_api_calls import FrontendApiCall
from app.services.extractors.orm_models import OrmExtraction
from app.services.extractors.request_models import RequestModel
from app.services.extractors.sql_queries import SqlQuery
from app.services.stack_detector import StackReport

__all__ = ["AnalysisState", "GroupError", "ProgressReporter"]


@dataclass(frozen=True, slots=True)
class GroupError:
    """A rule group that failed, and why.

    Kept as data rather than raised so the other branches are unaffected and
    the report can say which category is unreliable instead of silently
    omitting it.
    """

    category: IssueCategory
    message: str
    exception_type: str


class ProgressReporter:
    """How a node reports progress, without knowing about SSE or databases.

    Defaults to doing nothing, so the graph is runnable in a test with no
    event bus attached.
    """

    def started(self, stage: str, message: str) -> None:
        """A stage began."""

    def completed(self, stage: str, message: str, finding_count: int | None = None) -> None:
        """A stage finished successfully."""

    def failed(self, stage: str, message: str) -> None:
        """A stage failed. The run continues."""

    def skipped(self, stage: str, message: str) -> None:
        """A stage had nothing to do."""


class AnalysisState(TypedDict, total=False):
    """Everything the workflow reads and writes.

    ``total=False`` because LangGraph passes partial updates between nodes;
    each node returns only the keys it sets.
    """

    # -- Inputs, set once before the graph runs -----------------------------
    root: Path
    frontend_roots: tuple[str, ...]
    backend_roots: tuple[str, ...]
    combined_roots: tuple[str, ...]
    reporter: ProgressReporter

    # -- Stack detection ----------------------------------------------------
    stack: StackReport

    # -- Extraction, performed once and shared by the parallel branches -----
    calls: list[FrontendApiCall]
    routes: RouteExtraction
    request_models: dict[str, RequestModel]
    schema: DbSchema
    orm: OrmExtraction
    queries: list[SqlQuery]
    counts: dict[str, int]

    # -- Rule output. Written concurrently, so it needs a reducer. ----------
    findings: Annotated[list[Finding], operator.add]
    group_errors: Annotated[list[GroupError], operator.add]
    notes: Annotated[list[str], operator.add]
    categories_analysed: Annotated[list[IssueCategory], operator.add]

    # -- Dependency lookup --------------------------------------------------
    vulnerability_client: Any

    # -- Synthesis ----------------------------------------------------------
    deduplicated: list[Finding]
    score: Any
    explanation_usage: Any
    explanation_sources: dict[str, int]


def initial_state(
    root: Path,
    *,
    frontend_roots: tuple[str, ...] = (),
    backend_roots: tuple[str, ...] = (),
    reporter: ProgressReporter | None = None,
    vulnerability_client: Any = None,
) -> AnalysisState:
    """Build the state a run starts from, with the accumulators empty."""
    return AnalysisState(
        root=root,
        frontend_roots=frontend_roots,
        backend_roots=backend_roots,
        reporter=reporter or ProgressReporter(),
        vulnerability_client=vulnerability_client,
        findings=[],
        group_errors=[],
        notes=[],
        categories_analysed=[],
        counts={},
    )


@dataclass(slots=True)
class WorkflowResult:
    """What a completed workflow produced."""

    findings: list[Finding]
    score: Any
    stack: StackReport
    notes: list[str] = field(default_factory=list)
    group_errors: list[GroupError] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    explanation_usage: Any = None
    explanation_sources: dict[str, int] = field(default_factory=dict)
    duration_ms: int = 0

    @property
    def failed_categories(self) -> list[IssueCategory]:
        return [error.category for error in self.group_errors]

    @property
    def is_complete(self) -> bool:
        return not self.notes and not self.group_errors
