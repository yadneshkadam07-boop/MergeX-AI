"""The LangGraph workflow.

::

    stack ──┬── api_contract ──┐
            ├── schema ────────┼── synthesize
            └── security ──────┘

The three rule groups fan out from stack detection and join at the
synthesiser. LangGraph runs a fan-out concurrently, and merges their writes
through the reducers declared on :class:`~app.agents.state.AnalysisState`.

**Every node catches its own exceptions.** If a node raises, LangGraph aborts
the whole run — so a crash in the security rules would lose the API and schema
findings too. Instead each node wraps its body, records a
:class:`~app.agents.state.GroupError`, and returns normally. The other
branches finish, the synthesiser still runs, and the report names the category
that failed rather than showing it as clean. "No security issues found" and
"the security analysis crashed" must never look the same.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.state import (
    AnalysisState,
    GroupError,
    ProgressReporter,
    WorkflowResult,
    initial_state,
)
from app.analysis.findings import Finding, deduplicate
from app.analysis.rules.api_contract import ApiContractInput, run_api_contract_rules
from app.analysis.rules.dependencies import DependencyInput, run_dependency_rules
from app.analysis.rules.schema import SchemaInput, run_schema_rules
from app.analysis.rules.security import SecurityInput, run_security_rules
from app.analysis.scoring import score_findings
from app.core.logging import get_logger
from app.models.enums import IssueCategory
from app.services.explanations import Explainer, TemplateExplainer, apply_explanations
from app.services.extractors.backend_routes import extract_backend_routes
from app.services.extractors.db_schema import extract_db_schema
from app.services.extractors.frontend_api_calls import extract_frontend_api_calls
from app.services.extractors.orm_models import extract_orm_models
from app.services.extractors.request_models import extract_request_models
from app.services.extractors.sql_queries import extract_sql_queries
from app.services.stack_detector import StackReport, detect_stack

__all__ = ["build_graph", "run_workflow"]

log = get_logger("app.agents.graph")


def _guard(
    category: IssueCategory, stage: str
) -> Callable[[Callable[[AnalysisState], Awaitable[dict[str, Any]]]], Any]:
    """Wrap a rule node so a crash degrades one branch instead of the run.

    Returns the node's normal update on success, and on failure a state update
    recording the error -- never an exception, which LangGraph would propagate
    and abort every sibling branch with.
    """

    def decorate(
        node: Callable[[AnalysisState], Awaitable[dict[str, Any]]],
    ) -> Callable[[AnalysisState], Awaitable[dict[str, Any]]]:
        async def wrapped(state: AnalysisState) -> dict[str, Any]:
            reporter: ProgressReporter = state["reporter"]
            reporter.started(stage, f"Running {stage} analysis")
            try:
                update = await node(state)
            except Exception as exc:  # noqa: BLE001 - isolating the branch is the point
                log.exception("rule_group_failed", category=category.value, stage=stage)
                reporter.failed(stage, f"{type(exc).__name__}: {exc}")
                return {
                    "group_errors": [
                        GroupError(
                            category=category,
                            message=str(exc)[:300],
                            exception_type=type(exc).__name__,
                        )
                    ],
                    "notes": [
                        f"The {category.value.replace('_', ' ')} analysis failed "
                        f"({type(exc).__name__}), so that category is incomplete. "
                        f"The other checks completed normally."
                    ],
                }

            produced = len(update.get("findings", []))
            reporter.completed(stage, f"{stage} analysis complete", finding_count=produced)
            return update

        return wrapped

    return decorate


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


async def detect_stack_node(state: AnalysisState) -> dict[str, Any]:
    """Identify the stack, then extract every fact the rule groups compare.

    Extraction happens here rather than in each branch so the three groups
    share one pass over the tree. They are rule engines, not parsers.
    """
    reporter: ProgressReporter = state["reporter"]
    reporter.started("stack", "Detecting the project's stack")

    root = state["root"]
    stack = state.get("stack") or detect_stack(root)

    frontend_roots = state.get("frontend_roots") or _usable(root, stack.frontend_roots)
    backend_roots = state.get("backend_roots") or _usable(root, stack.backend_roots)
    combined = tuple(dict.fromkeys(frontend_roots + backend_roots))

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

    reporter.completed(
        "stack",
        f"Detected {', '.join(stack.frontend + stack.backend) or 'no known frameworks'}",
    )
    return {
        "stack": stack,
        "frontend_roots": frontend_roots,
        "backend_roots": backend_roots,
        "combined_roots": combined,
        "calls": calls,
        "routes": routes,
        "request_models": request_models,
        "schema": schema,
        "orm": orm,
        "queries": queries,
        "counts": counts,
    }


@_guard(IssueCategory.API_CONTRACT, "api")
async def api_contract_node(state: AnalysisState) -> dict[str, Any]:
    calls = state.get("calls") or []
    routes = state["routes"]

    if not calls or not routes.routes:
        state["reporter"].skipped("api", "No calls or no routes to compare")
        return {"notes": [_why_no_api_check(len(calls), len(routes.routes))]}

    findings = run_api_contract_rules(
        ApiContractInput(
            calls=calls, routes=routes, request_models=state.get("request_models") or {}
        )
    )
    notes: list[str] = []
    if routes.unresolved_mounts:
        notes.append(
            f"{len(routes.unresolved_mounts)} router mount(s) could not be traced to an "
            f"application, so missing-endpoint checks were skipped to avoid false positives."
        )
    return {
        "findings": findings,
        "notes": notes,
        "categories_analysed": [IssueCategory.API_CONTRACT],
    }


@_guard(IssueCategory.SCHEMA, "schema")
async def schema_node(state: AnalysisState) -> dict[str, Any]:
    schema = state["schema"]
    orm = state["orm"]

    if schema.is_empty or not orm.models:
        state["reporter"].skipped("schema", "No migrations or no models")
        return {"notes": [_why_no_schema_check(len(schema.tables), len(orm.models))]}

    findings = run_schema_rules(
        SchemaInput(schema=schema, orm=orm, queries=state.get("queries") or [])
    )
    return {"findings": findings, "categories_analysed": [IssueCategory.SCHEMA]}


@_guard(IssueCategory.SECURITY, "security")
async def security_node(state: AnalysisState) -> dict[str, Any]:
    """Security rules, plus the dependency lookup.

    The two are grouped because both are "is this project safe to deploy"
    questions and because the dependency check is usually the slowest thing
    in the run -- putting it in a branch that already exists keeps the fan-out
    at three.
    """
    root = state["root"]
    combined = state.get("combined_roots") or ()

    findings = run_security_rules(
        SecurityInput(root=root, routes=state["routes"], subdirectories=combined)
    )
    categories = [IssueCategory.SECURITY]
    notes: list[str] = []

    client = state.get("vulnerability_client")
    if client is not None:
        dependency_findings, note = await run_dependency_rules(
            DependencyInput(root=root, client=client, subdirectories=combined)
        )
        findings.extend(dependency_findings)
        categories.append(IssueCategory.DEPENDENCY)
        if note:
            notes.append(note)
    else:
        notes.append(
            "Dependency vulnerability checking was not run: no advisory source was "
            "configured for this analysis."
        )

    return {"findings": findings, "notes": notes, "categories_analysed": categories}


async def _explain_safely(explainer: Explainer, findings: list[Finding]) -> Any:
    """Explain findings, surviving a failure of the explainer itself.

    Two layers, because "never fail the analysis" has to hold even if the
    fallback is what breaks: the configured explainer, then the template
    explainer, then an empty result. Findings with no explanation still render
    — they carry a description, evidence and an expected/actual pair of their
    own — so the worst outcome is plainer prose, not a lost report.
    """
    from app.services.explanations import ExplanationResult

    try:
        return await explainer.explain(findings)
    except Exception as exc:  # noqa: BLE001 - an explainer must never fail a run
        log.exception("explainer_failed")
        primary_error = f"{type(exc).__name__}: {exc}"

    try:
        result = await TemplateExplainer().explain(findings)
    except Exception as exc:  # noqa: BLE001 - last resort
        log.exception("template_explainer_failed")
        result = ExplanationResult()
        primary_error = f"{primary_error}; fallback also failed: {type(exc).__name__}"

    result.degraded = True
    result.degraded_reason = primary_error
    return result


def make_synthesize_node(
    explainer: Explainer,
) -> Callable[[AnalysisState], Awaitable[dict[str, Any]]]:
    """Build the synthesiser, which is the only node that touches a model.

    Deduplication and scoring happen *before* explanation, and explanation
    cannot change either: it attaches prose to findings that already exist.
    """

    async def synthesize_node(state: AnalysisState) -> dict[str, Any]:
        reporter: ProgressReporter = state["reporter"]
        reporter.started("synthesis", "Merging findings and writing explanations")

        raw: list[Finding] = state.get("findings") or []
        merged = deduplicate(raw)

        analysed = set(state.get("categories_analysed") or [])
        score = score_findings(merged, categories_analysed=analysed)

        explanations = await _explain_safely(explainer, merged)

        explained = apply_explanations(merged, explanations)

        notes: list[str] = []
        if explanations.degraded:
            notes.append(
                f"AI explanations were unavailable ({explanations.degraded_reason}); "
                f"rule-based explanations were used instead. The findings themselves "
                f"are unaffected."
            )

        reporter.completed(
            "synthesis",
            f"{len(explained)} issues, health score {score.score}",
            finding_count=len(explained),
        )
        return {
            "deduplicated": explained,
            "score": score,
            "notes": notes,
            "explanation_usage": explanations.usage,
            "explanation_sources": explanations.source_counts,
        }

    return synthesize_node


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------


def build_graph(explainer: Explainer) -> Any:
    """Compile the workflow.

    The three rule nodes have no edges between them, which is what makes
    LangGraph run them concurrently; each has an edge to the synthesiser, so
    it waits for all three.
    """
    graph = StateGraph(AnalysisState)

    graph.add_node("stack", detect_stack_node)
    graph.add_node("api", api_contract_node)
    graph.add_node("schema", schema_node)
    graph.add_node("security", security_node)
    # LangGraph types a node's state parameter as ``Never`` when the graph's
    # own parameter cannot be inferred from a closure, so a node built by a
    # factory does not match its signature. The call is correct at runtime.
    graph.add_node("synthesize", make_synthesize_node(explainer))  # type: ignore[arg-type]

    graph.add_edge(START, "stack")
    for branch in ("api", "schema", "security"):
        graph.add_edge("stack", branch)
        graph.add_edge(branch, "synthesize")
    graph.add_edge("synthesize", END)

    return graph.compile()


async def run_workflow(
    root: Any,
    *,
    explainer: Explainer | None = None,
    vulnerability_client: Any = None,
    reporter: ProgressReporter | None = None,
    stack: StackReport | None = None,
) -> WorkflowResult:
    """Run the whole workflow over an imported tree."""
    started = time.perf_counter()
    state = initial_state(
        root,
        reporter=reporter,
        vulnerability_client=vulnerability_client,
    )
    if stack is not None:
        state["stack"] = stack

    compiled = build_graph(explainer or TemplateExplainer())
    final: AnalysisState = await compiled.ainvoke(state)

    duration_ms = int((time.perf_counter() - started) * 1000)
    result = WorkflowResult(
        findings=final.get("deduplicated") or [],
        score=final["score"],
        stack=final["stack"],
        notes=list(final.get("notes") or []),
        group_errors=list(final.get("group_errors") or []),
        counts=final.get("counts") or {},
        explanation_usage=final.get("explanation_usage"),
        explanation_sources=final.get("explanation_sources") or {},
        duration_ms=duration_ms,
    )

    log.info(
        "workflow_complete",
        findings=len(result.findings),
        score=result.score.score,
        failed_groups=[error.category.value for error in result.group_errors],
        duration_ms=duration_ms,
    )
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _usable(root: Any, candidates: list[str]) -> tuple[str, ...]:
    return tuple(
        candidate
        for candidate in candidates
        if candidate not in {".", ""} and (root / candidate).is_dir()
    )


def _why_no_api_check(call_count: int, route_count: int) -> str:
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
