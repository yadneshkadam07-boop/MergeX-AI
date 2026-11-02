"""Architecture topology synthesizer for GET /api/v1/projects/{id}/architecture.

Deterministically extracts nodes and edges from the project stack and maps findings
to the corresponding layers and communication boundaries.
"""

from __future__ import annotations

from app.models.analysis import Analysis
from app.models.enums import IssueCategory, Severity
from app.models.issue import Issue
from app.models.project import Project
from app.schemas.contract import ArchEdgeOut, ArchitectureOut, ArchNodeOut


def build_architecture_topology(
    project: Project,
    analysis: Analysis | None,
    issues: list[Issue],
) -> ArchitectureOut:
    """Build interactive architecture nodes and edges from detected stack and issues."""
    detected = (analysis.stack if analysis and analysis.stack else project.detected_stack) or {}
    technologies = detected.get("technologies", [])
    tech_names = [t.get("name", "") if isinstance(t, dict) else str(t) for t in technologies]
    frameworks = list(detected.get("frameworks") or [])
    all_tech = " ".join(tech_names + frameworks).lower()

    # Determine Frontend Tech
    fe_tech = "React / Vite"
    if "next" in all_tech:
        fe_tech = "Next.js"
    elif "vue" in all_tech:
        fe_tech = "Vue.js"
    elif "svelte" in all_tech:
        fe_tech = "Svelte"
    elif "react" in all_tech:
        fe_tech = "React 19 / Vite"

    # Determine Backend Tech
    be_tech = "FastAPI (Python)"
    if "django" in all_tech:
        be_tech = "Django"
    elif "express" in all_tech:
        be_tech = "Express / Node.js"
    elif "flask" in all_tech:
        be_tech = "Flask"
    elif "fastapi" in all_tech:
        be_tech = "FastAPI (Python 3.12)"

    # Determine Database Tech
    db_tech = "PostgreSQL"
    if "sqlite" in all_tech:
        db_tech = "SQLite 3"
    elif "mysql" in all_tech:
        db_tech = "MySQL 8"
    elif "postgres" in all_tech:
        db_tech = "PostgreSQL 16"

    # Partition issues to architecture layers
    client_issue_ids: list[str] = []
    api_issue_ids: list[str] = []
    db_issue_ids: list[str] = []
    boundary_client_api_ids: list[str] = []
    boundary_api_db_ids: list[str] = []

    for issue in issues:
        iid = str(issue.id)
        cat = issue.category
        path = (issue.file_path or "").lower()

        # Schema and ORM -> Database
        if cat == IssueCategory.SCHEMA or "models" in path or "schema" in path or "alembic" in path:
            db_issue_ids.append(iid)
            boundary_api_db_ids.append(iid)

        # API Contract -> Boundary between Web and API
        if cat == IssueCategory.API_CONTRACT:
            boundary_client_api_ids.append(iid)
            client_issue_ids.append(iid)
            api_issue_ids.append(iid)

        # Security -> API or boundary
        if cat == IssueCategory.SECURITY:
            api_issue_ids.append(iid)
            if "cors" in (issue.title + " " + issue.description).lower():
                boundary_client_api_ids.append(iid)

        # Frontend source files
        is_frontend = any(
            path.startswith(prefix) for prefix in ("src/", "frontend/", "client/", "ui/")
        ) or path.endswith((".tsx", ".jsx", ".vue"))
        if is_frontend and iid not in client_issue_ids:
            client_issue_ids.append(iid)

        # Backend source files
        is_backend = any(
            path.startswith(prefix) for prefix in ("backend/", "app/", "server/", "api/")
        ) or path.endswith((".py", ".go", ".rs"))
        if is_backend and iid not in api_issue_ids:
            api_issue_ids.append(iid)

    # Determine Edge statuses
    has_crit_client_api = any(
        i.severity == Severity.CRITICAL for i in issues if str(i.id) in boundary_client_api_ids
    )
    has_warn_client_api = any(
        i.severity in (Severity.HIGH, Severity.MEDIUM)
        for i in issues
        if str(i.id) in boundary_client_api_ids
    )
    edge_client_api_status = (
        "broken" if has_crit_client_api else ("warning" if has_warn_client_api else "ok")
    )

    has_crit_api_db = any(
        i.severity == Severity.CRITICAL for i in issues if str(i.id) in boundary_api_db_ids
    )
    has_warn_api_db = any(
        i.severity in (Severity.HIGH, Severity.MEDIUM)
        for i in issues
        if str(i.id) in boundary_api_db_ids
    )
    edge_api_db_status = "broken" if has_crit_api_db else ("warning" if has_warn_api_db else "ok")

    nodes = [
        ArchNodeOut(
            id="node_web",
            label="Web Client",
            kind="frontend",
            tech=fe_tech,
            description="Single-page responsive dashboard and audit workspace.",
            issueIds=client_issue_ids,
            position={"x": 100, "y": 150},
        ),
        ArchNodeOut(
            id="node_api",
            label="Core Gateway",
            kind="api",
            tech=be_tech,
            description="Async REST services and multi-agent orchestration.",
            issueIds=api_issue_ids,
            position={"x": 400, "y": 150},
        ),
        ArchNodeOut(
            id="node_db",
            label="Primary Store",
            kind="database",
            tech=db_tech,
            description="Relational store for analysis runs, projects, and audit findings.",
            issueIds=db_issue_ids,
            position={"x": 700, "y": 150},
        ),
    ]

    edges = [
        ArchEdgeOut(
            id="edge_client_api",
            source="node_web",
            target="node_api",
            label="REST / JSON",
            status=edge_client_api_status,
            issueIds=boundary_client_api_ids,
        ),
        ArchEdgeOut(
            id="edge_api_db",
            source="node_api",
            target="node_db",
            label="SQLAlchemy / ORM",
            status=edge_api_db_status,
            issueIds=boundary_api_db_ids,
        ),
    ]

    return ArchitectureOut(nodes=nodes, edges=edges)
