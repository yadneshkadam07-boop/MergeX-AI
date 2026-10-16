"""The analysis engine: extract, apply rules, deduplicate, score.

This is the whole deterministic pipeline, callable as one function. Phase 4
wraps it in LangGraph to run the three rule groups concurrently and stream
progress, and adds Gemini explanations on top of the result. Nothing here
calls a language model, and nothing here needs to: a finding's existence,
severity, location and evidence are all decided before any model is involved.

The engine reports what it *could not* check as explicitly as what it found.
A dependency lookup that failed, a category with no inputs, a repository with
no backend -- each of those produces a note rather than a silently clean
result, because "we found nothing" and "we could not look" mean very
different things to someone reading a score.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from app.analysis.findings import Finding, deduplicate
from app.analysis.rules.api_contract import ApiContractInput, run_api_contract_rules
from app.analysis.rules.dependencies import DependencyInput, run_dependency_rules
from app.analysis.rules.schema import SchemaInput, run_schema_rules
from app.analysis.rules.security import SecurityInput, run_security_rules
from app.analysis.scoring import HealthScore, score_findings
from app.core.logging import get_logger
from app.models.enums import IssueCategory
from app.services.extractors.backend_routes import extract_backend_routes
from app.services.extractors.db_schema import extract_db_schema
from app.services.extractors.frontend_api_calls import extract_frontend_api_calls
from app.services.extractors.orm_models import extract_orm_models
from app.services.extractors.request_models import extract_request_models
from app.services.extractors.sql_queries import extract_sql_queries
from app.services.osv import VulnerabilityClient
from app.services.stack_detector import StackReport, detect_stack

__all__ = ["AnalysisResult", "analyse"]

log = get_logger("app.analysis.engine")


@dataclass(slots=True)
class AnalysisResult:
    """Everything one deterministic analysis produced."""

    findings: list[Finding]
    score: HealthScore
    stack: StackReport
    notes: list[str] = field(default_factory=list)
    """Caveats about completeness, shown alongside the score."""
    duration_ms: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    """Extraction tallies, useful for "we looked at N routes" in the report."""

    @property
    def is_complete(self) -> bool:
        """True when every check ran without a caveat."""
        return not self.notes


async def analyse(
    root: Path,
    *,
    vulnerability_client: VulnerabilityClient | None = None,
    stack: StackReport | None = None,
) -> AnalysisResult:
    """Run the full deterministic analysis over an imported working tree.

    Args:
        root: The imported repository.
        vulnerability_client: Supplies dependency advisories. When omitted the
            dependency check is skipped and noted -- the caller decides
            whether to reach the network, so the engine itself never does
            something surprising.
        stack: A previously computed stack report, to avoid detecting twice.
    """
    started = time.perf_counter()
    report = stack or detect_stack(root)

    frontend_roots = tuple(_usable_roots(root, report.frontend_roots))
    backend_roots = tuple(_usable_roots(root, report.backend_roots))

    notes: list[str] = []
    findings: list[Finding] = []
    analysed: set[IssueCategory] = set()

    # -- Extraction ---------------------------------------------------------
    calls = extract_frontend_api_calls(root, subdirectories=frontend_roots)
    routes = extract_backend_routes(root, subdirectories=backend_roots)
    request_models = extract_request_models(root, subdirectories=backend_roots)
    schema = extract_db_schema(root, subdirectories=backend_roots)
    orm = extract_orm_models(root, subdirectories=backend_roots)
    queries = extract_sql_queries(root, subdirectories=backend_roots)

    counts = {
        "frontend_calls": len(calls),
        "backend_routes": len(routes.routes),
        "request_models": len(request_models),
        "database_tables": len(schema.tables),
        "orm_models": len(orm.models),
        "sql_queries": len(queries),
    }

    # -- API contract -------------------------------------------------------
    if calls and routes.routes:
        analysed.add(IssueCategory.API_CONTRACT)
        findings.extend(
            run_api_contract_rules(
                ApiContractInput(calls=calls, routes=routes, request_models=request_models)
            )
        )
        if routes.unresolved_mounts:
            notes.append(
                f"{len(routes.unresolved_mounts)} router mount(s) could not be traced to "
                f"an application, so missing-endpoint checks were skipped to avoid "
                f"false positives."
            )
    else:
        notes.append(_why_no_api_check(len(calls), len(routes.routes)))

    # -- Schema -------------------------------------------------------------
    if not schema.is_empty and orm.models:
        analysed.add(IssueCategory.SCHEMA)
        findings.extend(run_schema_rules(SchemaInput(schema=schema, orm=orm, queries=queries)))
    else:
        notes.append(_why_no_schema_check(len(schema.tables), len(orm.models)))

    # -- Security -----------------------------------------------------------
    analysed.add(IssueCategory.SECURITY)
    findings.extend(
        run_security_rules(
            SecurityInput(
                root=root,
                routes=routes,
                subdirectories=tuple(dict.fromkeys(frontend_roots + backend_roots)),
            )
        )
    )

    # -- Dependencies -------------------------------------------------------
    if vulnerability_client is not None:
        analysed.add(IssueCategory.DEPENDENCY)
        dependency_findings, dependency_note = await run_dependency_rules(
            DependencyInput(
                root=root,
                client=vulnerability_client,
                subdirectories=tuple(dict.fromkeys(frontend_roots + backend_roots)),
            )
        )
        findings.extend(dependency_findings)
        if dependency_note:
            notes.append(dependency_note)
    else:
        notes.append(
            "Dependency vulnerability checking was not run: no advisory source was "
            "configured for this analysis."
        )

    # -- Merge and score ----------------------------------------------------
    deduplicated = deduplicate(findings)
    score = score_findings(deduplicated, categories_analysed=analysed)
    duration_ms = int((time.perf_counter() - started) * 1000)

    log.info(
        "analysis_complete",
        findings=len(deduplicated),
        merged_from=len(findings),
        score=score.score,
        duration_ms=duration_ms,
        notes=len(notes),
    )

    return AnalysisResult(
        findings=deduplicated,
        score=score,
        stack=report,
        notes=notes,
        duration_ms=duration_ms,
        counts=counts,
    )


def _usable_roots(root: Path, candidates: list[str]) -> list[str]:
    """Keep only roots that exist and are not the repository root itself.

    ``"."`` means "the manifest is at the top level", which as a subdirectory
    filter would be a no-op, so it is dropped and the whole tree is scanned.
    """
    return [
        candidate
        for candidate in candidates
        if candidate not in {".", ""} and (root / candidate).is_dir()
    ]


def _why_no_api_check(call_count: int, route_count: int) -> str:
    """A specific reason, because "no issues" and "not checked" differ."""
    if not call_count and not route_count:
        return (
            "API contract checks were skipped: no frontend HTTP calls and no backend "
            "routes were found."
        )
    if not call_count:
        return (
            "API contract checks were skipped: no frontend HTTP calls were found, so "
            f"the {route_count} backend route(s) have nothing to compare against."
        )
    return (
        "API contract checks were skipped: no backend routes were found, so the "
        f"{call_count} frontend call(s) cannot be matched. A frontend-only repository "
        "is not a repository full of missing endpoints."
    )


def _why_no_schema_check(table_count: int, model_count: int) -> str:
    if not table_count and not model_count:
        return "Schema checks were skipped: no migrations and no ORM models were found."
    if not table_count:
        return (
            f"Schema checks were skipped: {model_count} ORM model(s) were found but no "
            f"migrations, so every field would appear to be missing a column."
        )
    return (
        f"Schema checks were skipped: {table_count} table(s) were found but no ORM "
        f"models to compare them against."
    )
