"""Architecture topology synthesizer for GET /api/v1/projects/{id}/architecture.

Deterministically extracts nodes and edges from the project stack, codebase archetype,
and maps findings to corresponding layers and communication boundaries.
"""

from __future__ import annotations

from app.models.analysis import Analysis
from app.models.enums import IssueCategory, Severity
from app.models.issue import Issue
from app.models.project import Project
from app.schemas.contract import ArchEdgeOut, ArchitectureOut, ArchNodeOut


def _calc_edge_status(edge_issue_ids: list[str], issue_map: dict[str, Issue]) -> str:
    """Calculate edge status ('ok' | 'warning' | 'broken') from attached issues."""
    matched = [issue_map[iid] for iid in edge_issue_ids if iid in issue_map]
    if any(i.severity in (Severity.CRITICAL, Severity.HIGH) for i in matched):
        return "broken"
    if any(i.severity == Severity.MEDIUM for i in matched):
        return "warning"
    return "ok"


def build_architecture_topology(
    project: Project,
    analysis: Analysis | None,
    issues: list[Issue],
) -> ArchitectureOut:
    """Build interactive, domain-tailored architecture nodes and edges from detected stack and issues."""
    detected = project.detected_stack or {}
    if not detected and analysis and analysis.stack:
        detected = analysis.stack

    fe_list = detected.get("frontend") or []
    be_list = detected.get("backend") or []
    db_list = detected.get("database") or []
    build_list = detected.get("build") or []
    technologies = detected.get("technologies", [])
    tech_names = [t.get("name", "") if isinstance(t, dict) else str(t) for t in technologies]
    frameworks = list(detected.get("frameworks") or [])
    signals = [
        s.get("technology", "")
        for s in detected.get("signals", [])
        if isinstance(s, dict)
    ]
    pkg_mgrs = detected.get("package_managers") or []
    source_str = f"{getattr(project, 'source_url', '') or ''} {project.name or ''}"
    issue_paths_str = " ".join((i.file_path or "") for i in issues)

    all_tech = " ".join(
        fe_list
        + be_list
        + db_list
        + build_list
        + tech_names
        + frameworks
        + signals
        + pkg_mgrs
        + [source_str, issue_paths_str]
    ).lower()

    # --- Domain Archetype Detection ---
    is_chatbot_ml = any(
        kw in all_tech
        for kw in (
            "chatbot",
            "chat-bot",
            "chat",
            "nlp",
            "nltk",
            "spacy",
            "intent",
            "corpus",
            "symptom",
            "dialogue",
            "health-care",
            "healthcare",
            "medical",
            "pytorch",
            "torch",
            "tensorflow",
            "keras",
            "huggingface",
            "transformers",
            "langchain",
            "llm",
            "llama",
            "deeplearning",
            "classifier",
            "train.py",
        )
    )

    is_ecommerce_market = any(
        kw in all_tech
        for kw in (
            "ecommerce",
            "e-commerce",
            "marketplace",
            "market",
            "shop",
            "store",
            "cart",
            "stripe",
            "paypal",
            "razorpay",
            "bidding",
            "order",
            "catalog",
            "checkout",
            "auction",
            "product",
        )
    )

    is_nextjs = "next" in all_tech
    is_supabase = "supabase" in all_tech
    is_django = "django" in all_tech
    is_fastapi = "fastapi" in all_tech
    is_flask = "flask" in all_tech
    is_express = "express" in all_tech or "node" in all_tech
    is_mongo = "mongo" in all_tech or "mongoose" in all_tech
    is_postgres = (
        "postgres" in all_tech
        or "psql" in all_tech
        or "pg" in all_tech
        or is_supabase
        or "prisma" in all_tech
    )
    is_sqlite = "sqlite" in all_tech
    is_redis = "redis" in all_tech
    is_docker = "docker" in all_tech or "container" in all_tech

    # --- 1. Frontend Client Layer ---
    if is_chatbot_ml and not any(kw in all_tech for kw in ("react", "vue", "next", "svelte")):
        fe_label = "Chatbot Web Interface"
        fe_tech = (
            "HTML5 / Jinja2"
            if ("jinja" in all_tech or is_flask)
            else ("Streamlit UI" if "streamlit" in all_tech else "Conversational Web UI")
        )
        fe_desc = "Conversational chat interface handling user symptom inquiry, dialogue state, and triage."
    elif is_ecommerce_market:
        fe_label = "Marketplace Web Client" if "market" in all_tech else "Storefront Web SPA"
        if "webpack" in all_tech and "react" in all_tech:
            fe_tech = "React (Webpack)"
        elif "vite" in all_tech and "react" in all_tech:
            fe_tech = "React / Vite"
        elif "react" in all_tech:
            fe_tech = "React SPA"
        else:
            fe_tech = fe_list[0] if fe_list else "Web Storefront"
        fe_desc = "Product catalog browsing, responsive shopping cart, merchant dashboard, and checkout portal."
    elif is_nextjs:
        fe_label = "Next.js App Router Client"
        fe_tech = "Next.js 14+ / React 19"
        fe_desc = "Server components, client bundles, dynamic routing, and interactive audit views."
    elif "vue" in all_tech:
        fe_label = "Vue.js Single Page App"
        fe_tech = "Vue 3 / Vite"
        fe_desc = "Reactive client application with component state management and REST bindings."
    elif "react" in all_tech:
        fe_label = "React SPA Client"
        fe_tech = "React / Vite" if "vite" in all_tech else "React SPA"
        fe_desc = "Client-side interactive user interface routing views and executing API fetch calls."
    else:
        fe_label = "Web Client"
        fe_tech = fe_list[0] if fe_list else "Web Client"
        fe_desc = "Client-side interactive user interface routing views and executing API fetch calls."

    # --- 2. API / Core Server Layer ---
    if is_chatbot_ml:
        fe_health_kw = any(k in all_tech for k in ("health", "medical", "symptom"))
        be_label = "Healthcare Dialogue Server" if fe_health_kw else "NLP Chatbot Server"
        be_tech = "Flask (Python)" if is_flask else ("FastAPI (Python)" if is_fastapi else "Python Core Server")
        be_desc = "Dialogue session manager handling message parsing, context tracking, and response formatting."
    elif is_ecommerce_market:
        be_label = "Marketplace Core Controller" if "market" in all_tech else "E-Commerce REST Gateway"
        be_tech = "Express / Node.js" if is_express else (be_list[0] if be_list else "Node.js REST Service")
        be_desc = "Order processing, inventory reservation, vendor shops, and transactional routing."
    elif is_fastapi:
        be_label = "FastAPI Core Gateway"
        be_tech = "FastAPI (Python 3.12)"
        be_desc = "Asynchronous OpenAPI-compliant REST gateway with Pydantic validation and route handlers."
    elif is_django:
        be_label = "Django Application Server"
        be_tech = "Django / WSGI"
        be_desc = "Django view routing, ORM business logic, session security, and admin services."
    elif is_nextjs:
        be_label = "Next.js Server API & Actions"
        be_tech = "Node.js / Edge Runtime"
        be_desc = "Server Actions, route handlers, data mutations, and backend logic execution."
    else:
        be_label = "Core Gateway"
        be_tech = be_list[0] if be_list else ("Express / Node.js" if is_express else "REST API Gateway")
        be_desc = "Central application gateway providing REST and RPC services, business logic, and middleware."

    # --- 3. Primary Store / Knowledge Base Layer ---
    if is_chatbot_ml and not (is_mongo or is_postgres):
        fe_health_kw = any(k in all_tech for k in ("health", "medical", "symptom"))
        db_label = "Medical Knowledge Base & Corpus" if fe_health_kw else "Intents & Dialogue Corpus"
        db_tech = "SQLite 3 Knowledge Base" if is_sqlite else "JSON Dataset & Knowledge Base"
        db_desc = "Curated dataset of symptom patterns, intents definitions, medical guidelines, and verified responses."
    elif is_mongo:
        db_label = "Product & Order Database" if is_ecommerce_market else "MongoDB Document Cluster"
        db_tech = "MongoDB (Mongoose)"
        db_desc = "Document collections storing listings, user profiles, orders, and application state."
    elif is_postgres:
        db_label = "PostgreSQL Relational DB"
        db_tech = "PostgreSQL (Supabase)" if is_supabase else "PostgreSQL 16"
        db_desc = "Relational persistent store housing schema models, tables, and foreign keys."
    elif is_sqlite:
        db_label = "SQLite Embedded Store"
        db_tech = "SQLite 3"
        db_desc = "Embedded relational file database storing application records and transactional data."
    else:
        db_label = db_list[0] if db_list else "Primary Store"
        db_tech = db_list[0] if db_list else "Relational Store"
        db_desc = "Primary datastore housing schema models, records, and persistent entity state."

    # --- Issue Partitioning by Architecture Layer ---
    issue_map = {str(i.id): i for i in issues}
    client_issue_ids: list[str] = []
    api_issue_ids: list[str] = []
    db_issue_ids: list[str] = []
    auth_issue_ids: list[str] = []
    worker_issue_ids: list[str] = []
    ext_issue_ids: list[str] = []

    boundary_client_api_ids: list[str] = []
    boundary_api_db_ids: list[str] = []
    boundary_api_auth_ids: list[str] = []
    boundary_api_worker_ids: list[str] = []
    boundary_api_ext_ids: list[str] = []

    for issue in issues:
        iid = str(issue.id)
        cat = issue.category
        path = (issue.file_path or "").lower()
        title_desc = f"{issue.title} {issue.description}".lower()

        # Schema & ORM -> DB boundary
        if cat == IssueCategory.SCHEMA or any(k in path for k in ("models", "schema", "alembic", "migrations", "entities")):
            db_issue_ids.append(iid)
            boundary_api_db_ids.append(iid)
            api_issue_ids.append(iid)

        # API Contract -> Client-API boundary
        if cat == IssueCategory.API_CONTRACT:
            boundary_client_api_ids.append(iid)
            client_issue_ids.append(iid)
            api_issue_ids.append(iid)

        # Security -> Auth or API
        if cat == IssueCategory.SECURITY:
            api_issue_ids.append(iid)
            if "cors" in title_desc:
                boundary_client_api_ids.append(iid)
                client_issue_ids.append(iid)
            if any(k in title_desc or k in path for k in ("jwt", "auth", "token", "password", "secret", "session")):
                auth_issue_ids.append(iid)
                boundary_api_auth_ids.append(iid)
            if any(k in title_desc for k in ("injection", "sql", "mongo")):
                db_issue_ids.append(iid)
                boundary_api_db_ids.append(iid)

        # Dependencies
        if cat == IssueCategory.DEPENDENCY:
            if any(k in (path + " " + title_desc) for k in ("react", "vue", "client", "ui", "webpack", "vite", "tailwind", "lodash")):
                client_issue_ids.append(iid)
            else:
                api_issue_ids.append(iid)

        # Build & CI
        if str(cat).lower() in ("build", "deployment"):
            worker_issue_ids.append(iid)
            api_issue_ids.append(iid)

        # File-based location heuristics
        is_frontend_file = any(
            path.startswith(prefix) for prefix in ("src/", "frontend/", "client/", "ui/")
        ) or path.endswith((".tsx", ".jsx", ".vue", ".html", ".css"))
        if is_frontend_file and iid not in client_issue_ids:
            client_issue_ids.append(iid)

        is_backend_file = any(
            path.startswith(prefix) for prefix in ("backend/", "app/", "server/", "api/", "controllers/", "routes/")
        ) or path.endswith((".py", ".go", ".rs"))
        if is_backend_file and iid not in api_issue_ids:
            api_issue_ids.append(iid)

        if any(k in path for k in ("nlp", "train", "intent", "corpus", "nltk", "dialogue")):
            worker_issue_ids.append(iid)
            boundary_api_worker_ids.append(iid)

        if any(k in path for k in ("payment", "stripe", "checkout", "billing")):
            ext_issue_ids.append(iid)
            boundary_api_ext_ids.append(iid)

    def _unique(lst: list[str]) -> list[str]:
        return list(dict.fromkeys(lst))

    client_issue_ids = _unique(client_issue_ids)
    api_issue_ids = _unique(api_issue_ids)
    db_issue_ids = _unique(db_issue_ids)
    auth_issue_ids = _unique(auth_issue_ids)
    worker_issue_ids = _unique(worker_issue_ids)
    ext_issue_ids = _unique(ext_issue_ids)
    boundary_client_api_ids = _unique(boundary_client_api_ids)
    boundary_api_db_ids = _unique(boundary_api_db_ids)
    boundary_api_auth_ids = _unique(boundary_api_auth_ids)
    boundary_api_worker_ids = _unique(boundary_api_worker_ids)
    boundary_api_ext_ids = _unique(boundary_api_ext_ids)

    # --- Build Nodes & Edges ---
    nodes: list[ArchNodeOut] = []
    edges: list[ArchEdgeOut] = []

    # Node 1: Web Client (Backbone)
    nodes.append(
        ArchNodeOut(
            id="node_web",
            label=fe_label,
            kind="frontend",
            tech=fe_tech,
            description=fe_desc,
            issueIds=client_issue_ids,
            position={"x": 60, "y": 180},
        )
    )

    # Node 2: API Gateway (Backbone)
    nodes.append(
        ArchNodeOut(
            id="node_api",
            label=be_label,
            kind="api",
            tech=be_tech,
            description=be_desc,
            issueIds=api_issue_ids,
            position={"x": 380, "y": 180},
        )
    )

    # Edge: Client -> API (Backbone)
    client_api_edge_label = (
        "Chat Stream / REST"
        if is_chatbot_ml
        else ("Server Actions / REST" if is_nextjs else "REST /api/v1 (JSON)")
    )
    edges.append(
        ArchEdgeOut(
            id="edge_client_api",
            source="node_web",
            target="node_api",
            label=client_api_edge_label,
            status=_calc_edge_status(boundary_client_api_ids, issue_map),
            issueIds=boundary_client_api_ids,
        )
    )

    if is_chatbot_ml:
        # Chatbot Architecture: Client -> Dialogue Server -> Intent Engine & Knowledge Base
        worker_tech = "NLTK / Neural Classifier" if "nltk" in all_tech else ("PyTorch / Transformers" if "torch" in all_tech else "NLP Pipeline")
        nodes.append(
            ArchNodeOut(
                id="node_worker",
                label="NLP Intent Engine",
                kind="worker",
                tech=worker_tech,
                description="Evaluates conversational utterances, tokenizes text, and computes classification probabilities.",
                issueIds=worker_issue_ids,
                position={"x": 720, "y": 90},
            )
        )
        nodes.append(
            ArchNodeOut(
                id="node_db",
                label=db_label,
                kind="database",
                tech=db_tech,
                description=db_desc,
                issueIds=db_issue_ids,
                position={"x": 720, "y": 270},
            )
        )
        edges.append(
            ArchEdgeOut(
                id="edge_api_worker",
                source="node_api",
                target="node_worker",
                label="Intent Inference Pipeline",
                status=_calc_edge_status(boundary_api_worker_ids, issue_map),
                issueIds=boundary_api_worker_ids,
            )
        )
        edges.append(
            ArchEdgeOut(
                id="edge_api_db",
                source="node_api",
                target="node_db",
                label="Corpus & Guideline Lookup",
                status=_calc_edge_status(boundary_api_db_ids, issue_map),
                issueIds=boundary_api_db_ids,
            )
        )

    elif is_ecommerce_market:
        # E-Commerce & Marketplace Architecture
        auth_label = "Merchant & User Auth Guard" if "market" in all_tech else "JWT Customer Auth Guard"
        auth_tech = "JWT / Session Cookies" if is_express else "JWT + bcrypt"
        nodes.append(
            ArchNodeOut(
                id="node_auth",
                label=auth_label,
                kind="auth",
                tech=auth_tech,
                description="Cryptographic token issuance, password hashing, and role-based permissions.",
                issueIds=auth_issue_ids,
                position={"x": 380, "y": 380},
            )
        )
        nodes.append(
            ArchNodeOut(
                id="node_db",
                label=db_label,
                kind="database",
                tech=db_tech,
                description=db_desc,
                issueIds=db_issue_ids,
                position={"x": 720, "y": 70},
            )
        )
        ext_label = "Stripe Connect / Escrow" if "market" in all_tech else "Stripe Payment Gateway"
        nodes.append(
            ArchNodeOut(
                id="node_external",
                label=ext_label,
                kind="external",
                tech="Stripe API & Webhooks",
                description="Customer checkout sessions, payment intent processing, and settlement webhooks.",
                issueIds=ext_issue_ids,
                position={"x": 720, "y": 240},
            )
        )
        if is_redis or "cache" in all_tech:
            nodes.append(
                ArchNodeOut(
                    id="node_cache",
                    label="Cart & Session Cache",
                    kind="database",
                    tech="Redis 7.2",
                    description="Transient shopping cart states, session stores, and rate-limiting counters.",
                    issueIds=[],
                    position={"x": 720, "y": 410},
                )
            )

        edges.append(
            ArchEdgeOut(
                id="edge_client_auth",
                source="node_web",
                target="node_auth",
                label="OAuth & Login Flow",
                status="ok",
                issueIds=[],
            )
        )
        edges.append(
            ArchEdgeOut(
                id="edge_api_auth",
                source="node_api",
                target="node_auth",
                label="Bearer Token Validation",
                status=_calc_edge_status(boundary_api_auth_ids, issue_map),
                issueIds=boundary_api_auth_ids,
            )
        )
        edges.append(
            ArchEdgeOut(
                id="edge_api_db",
                source="node_api",
                target="node_db",
                label="Mongoose ODM (Pool)" if is_mongo else "SQL Connection Pool",
                status=_calc_edge_status(boundary_api_db_ids, issue_map),
                issueIds=boundary_api_db_ids,
            )
        )
        edges.append(
            ArchEdgeOut(
                id="edge_api_ext",
                source="node_api",
                target="node_external",
                label="Payment Intent / Webhooks",
                status=_calc_edge_status(boundary_api_ext_ids, issue_map),
                issueIds=boundary_api_ext_ids,
            )
        )
        if is_redis or "cache" in all_tech:
            edges.append(
                ArchEdgeOut(
                    id="edge_api_cache",
                    source="node_api",
                    target="node_cache",
                    label="RESP Protocol (TCP)",
                    status="ok",
                    issueIds=[],
                )
            )

    else:
        # Modern Fullstack / Microservices / Standard Architecture
        has_auth = is_supabase or "jwt" in all_tech or "auth" in all_tech or len(auth_issue_ids) > 0
        if has_auth:
            nodes.append(
                ArchNodeOut(
                    id="node_auth",
                    label="Supabase Auth Guard" if is_supabase else "JWT Auth Service",
                    kind="auth",
                    tech="Supabase GoTrue" if is_supabase else "JWT + bcrypt",
                    description="Manages session token issuance, cryptographic verification, and role-based access control.",
                    issueIds=auth_issue_ids,
                    position={"x": 380, "y": 380},
                )
            )

        nodes.append(
            ArchNodeOut(
                id="node_db",
                label=db_label,
                kind="database",
                tech=db_tech,
                description=db_desc,
                issueIds=db_issue_ids,
                position={"x": 720, "y": 80},
            )
        )

        if is_redis:
            nodes.append(
                ArchNodeOut(
                    id="node_cache",
                    label="Redis In-Memory Cache",
                    kind="database",
                    tech="Redis 7.2",
                    description="Key-value cache storing session tokens, rate limits, and warm query caches.",
                    issueIds=[],
                    position={"x": 720, "y": 250},
                )
            )

        if is_docker or "celery" in all_tech or "worker" in all_tech or len(worker_issue_ids) > 0:
            nodes.append(
                ArchNodeOut(
                    id="node_worker",
                    label="Async Worker Container" if is_docker else "Background Queue Job",
                    kind="worker",
                    tech="Celery / Redis" if "celery" in all_tech else "Node / Docker Worker",
                    description="Executes long-running asynchronous tasks, batch reporting jobs, and data pipeline transforms.",
                    issueIds=worker_issue_ids,
                    position={"x": 720, "y": 420},
                )
            )

        db_edge_label = (
            "Mongoose / ODM"
            if is_mongo
            else ("Prisma / SQL Pool" if is_nextjs else ("SQLAlchemy / ORM" if is_postgres else "Datastore / Query"))
        )
        edges.append(
            ArchEdgeOut(
                id="edge_api_db",
                source="node_api",
                target="node_db",
                label=db_edge_label,
                status=_calc_edge_status(boundary_api_db_ids, issue_map),
                issueIds=boundary_api_db_ids,
            )
        )

        if has_auth:
            edges.append(
                ArchEdgeOut(
                    id="edge_client_auth",
                    source="node_web",
                    target="node_auth",
                    label="OAuth / Session Exchange",
                    status="ok",
                    issueIds=[],
                )
            )
            edges.append(
                ArchEdgeOut(
                    id="edge_api_auth",
                    source="node_api",
                    target="node_auth",
                    label="JWT Verification",
                    status=_calc_edge_status(boundary_api_auth_ids, issue_map),
                    issueIds=boundary_api_auth_ids,
                )
            )

        if is_redis:
            edges.append(
                ArchEdgeOut(
                    id="edge_api_cache",
                    source="node_api",
                    target="node_cache",
                    label="RESP Protocol (TCP)",
                    status="ok",
                    issueIds=[],
                )
            )

        if is_docker or "celery" in all_tech or "worker" in all_tech or len(worker_issue_ids) > 0:
            edges.append(
                ArchEdgeOut(
                    id="edge_worker_api",
                    source="node_api",
                    target="node_worker",
                    label="Event Ingestion Bus",
                    status=_calc_edge_status(boundary_api_worker_ids, issue_map),
                    issueIds=boundary_api_worker_ids,
                )
            )

    return ArchitectureOut(nodes=nodes, edges=edges)
