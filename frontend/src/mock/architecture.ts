import type { Project } from "@/types/project";
import type { Issue } from "@/types/issue";
import type { ArchNode, ArchEdge } from "@/types/architecture";

/**
 * Deterministically generates domain-tailored architecture topology (nodes & edges)
 * tailored to each project's detected stack, repository archetype, and open findings.
 */
export function generateArchitecture(
  project: Project,
  issues: Issue[],
): { nodes: ArchNode[]; edges: ArchEdge[] } {
  // Filter for active open issues (resolved/ignored issues do not count)
  const openIssues = issues.filter((i) => i.status === "open");
  const issueMap = new Map(openIssues.map((i) => [i.id, i]));

  const stackStr = (project.stack || []).join(" ").toLowerCase();
  const nameStr = (project.name || "").toLowerCase();
  const repoStr = (project.repoUrl || "").toLowerCase();
  const issuePathsStr = openIssues.map((i) => `${i.filePath} ${i.title}`).join(" ").toLowerCase();

  const allTech = `${stackStr} ${nameStr} ${repoStr} ${issuePathsStr}`;

  // Domain archetype signals
  const isChatbotMl = [
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
  ].some((kw) => allTech.includes(kw));

  const isEcommerceMarket = [
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
  ].some((kw) => allTech.includes(kw));

  const isNextjs = allTech.includes("next");
  const isSupabase = allTech.includes("supabase");
  const isDjango = allTech.includes("django");
  const isFastAPI = allTech.includes("fastapi");
  const isFlask = allTech.includes("flask");
  const isExpress = allTech.includes("express") || allTech.includes("node");
  const isMongo = allTech.includes("mongo") || allTech.includes("mongoose");
  const isPostgres =
    allTech.includes("postgres") ||
    allTech.includes("psql") ||
    allTech.includes("pg") ||
    isSupabase ||
    allTech.includes("prisma");
  const isSqlite = allTech.includes("sqlite");
  const isRedis = allTech.includes("redis");
  const isDocker = allTech.includes("docker") || allTech.includes("container");

  // --- Layer Attributes ---

  // 1. Frontend
  let feLabel = "Web Client";
  let feTech = "React SPA";
  let feDesc = "Client-side interactive user interface routing views and executing API fetch calls.";

  if (isChatbotMl && !["react", "vue", "next", "svelte"].some((k) => allTech.includes(k))) {
    feLabel = "Chatbot Web Interface";
    feTech = allTech.includes("jinja") || isFlask ? "HTML5 / Jinja2" : "Conversational Web UI";
    feDesc =
      "Conversational chat interface handling user symptom inquiry, dialogue state, and triage.";
  } else if (isEcommerceMarket) {
    feLabel = allTech.includes("market") ? "Marketplace Web Client" : "Storefront Web SPA";
    if (allTech.includes("webpack") && allTech.includes("react")) {
      feTech = "React (Webpack)";
    } else if (allTech.includes("vite") && allTech.includes("react")) {
      feTech = "React / Vite";
    } else if (allTech.includes("react")) {
      feTech = "React SPA";
    } else {
      feTech = "Web Storefront";
    }
    feDesc =
      "Product catalog browsing, responsive shopping cart, merchant dashboard, and checkout portal.";
  } else if (isNextjs) {
    feLabel = "Next.js App Router Client";
    feTech = "Next.js 14+ / React 19";
    feDesc = "Server components, client bundles, dynamic routing, and interactive audit views.";
  } else if (allTech.includes("vue")) {
    feLabel = "Vue.js Single Page App";
    feTech = "Vue 3 / Vite";
    feDesc = "Reactive client application with component state management and REST bindings.";
  } else if (allTech.includes("react")) {
    feLabel = "React SPA Client";
    feTech = allTech.includes("vite") ? "React / Vite" : "React 19 + Vite";
    feDesc = "Client-side interactive user interface routing views and executing API fetch calls.";
  }

  // 2. Core API / Backend
  let beLabel = "Core Gateway";
  let beTech = isExpress ? "Express / Node.js" : "REST API Gateway";
  let beDesc =
    "Central application gateway providing REST and RPC services, business logic, and middleware.";

  if (isChatbotMl) {
    const isHealth = ["health", "medical", "symptom"].some((k) => allTech.includes(k));
    beLabel = isHealth ? "Healthcare Dialogue Server" : "NLP Chatbot Server";
    beTech = isFlask ? "Flask (Python)" : isFastAPI ? "FastAPI (Python)" : "Python Core Server";
    beDesc =
      "Dialogue session manager handling message parsing, context tracking, and response formatting.";
  } else if (isEcommerceMarket) {
    beLabel = allTech.includes("market")
      ? "Marketplace Core Controller"
      : "E-Commerce REST Gateway";
    beTech = isExpress ? "Express / Node.js" : "Node.js REST Service";
    beDesc = "Order processing, inventory reservation, vendor shops, and transactional routing.";
  } else if (isFastAPI) {
    beLabel = "FastAPI Core Gateway";
    beTech = "FastAPI (Python 3.12)";
    beDesc =
      "Asynchronous OpenAPI-compliant REST gateway with Pydantic validation and route handlers.";
  } else if (isDjango) {
    beLabel = "Django Application Server";
    beTech = "Django / WSGI";
    beDesc = "Django view routing, ORM business logic, session security, and admin services.";
  } else if (isNextjs) {
    beLabel = "Next.js Server API & Actions";
    beTech = "Node.js / Edge Runtime";
    beDesc = "Server Actions, route handlers, data mutations, and backend logic execution.";
  }

  // 3. Primary Store / Datastore
  let dbLabel = "Primary Store";
  let dbTech = "Relational Store";
  let dbDesc = "Primary datastore housing schema models, records, and persistent entity state.";

  if (isChatbotMl && !isMongo && !isPostgres) {
    const isHealth = ["health", "medical", "symptom"].some((k) => allTech.includes(k));
    dbLabel = isHealth ? "Medical Knowledge Base & Corpus" : "Intents & Dialogue Corpus";
    dbTech = isSqlite ? "SQLite 3 Knowledge Base" : "JSON Dataset & Knowledge Base";
    dbDesc =
      "Curated dataset of symptom patterns, intents definitions, medical guidelines, and verified responses.";
  } else if (isMongo) {
    dbLabel = isEcommerceMarket ? "Product & Order Database" : "MongoDB Document Cluster";
    dbTech = "MongoDB (Mongoose)";
    dbDesc = "Document collections storing listings, user profiles, orders, and application state.";
  } else if (isPostgres) {
    dbLabel = "PostgreSQL Relational DB";
    dbTech = isSupabase ? "PostgreSQL (Supabase)" : "PostgreSQL 16";
    dbDesc = "Relational persistent store housing schema models, tables, and foreign keys.";
  } else if (isSqlite) {
    dbLabel = "SQLite Embedded Store";
    dbTech = "SQLite 3";
    dbDesc =
      "Embedded relational file database storing application records and transactional data.";
  }

  // --- Partition Issues to Layers ---
  const clientIssueIds: string[] = [];
  const apiIssueIds: string[] = [];
  const dbIssueIds: string[] = [];
  const authIssueIds: string[] = [];
  const workerIssueIds: string[] = [];
  const extIssueIds: string[] = [];

  const boundaryClientApiIds: string[] = [];
  const boundaryApiDbIds: string[] = [];
  const boundaryApiAuthIds: string[] = [];
  const boundaryApiWorkerIds: string[] = [];
  const boundaryApiExtIds: string[] = [];

  for (const issue of openIssues) {
    const iid = issue.id;
    const cat = issue.category as string;
    const path = (issue.filePath || "").toLowerCase();
    const titleDesc = `${issue.title} ${issue.shortDescription || ""} ${issue.explanation || ""}`.toLowerCase();

    // Integration / Contract / Schema
    if (
      cat === "integration" ||
      cat === "schema" ||
      ["models", "schema", "alembic", "migrations", "entities"].some((k) => path.includes(k))
    ) {
      dbIssueIds.push(iid);
      boundaryApiDbIds.push(iid);
      apiIssueIds.push(iid);
    }
    if (cat === "integration" || cat === "api_contract") {
      boundaryClientApiIds.push(iid);
      clientIssueIds.push(iid);
      apiIssueIds.push(iid);
    }

    // Security
    if (cat === "security") {
      apiIssueIds.push(iid);
      if (titleDesc.includes("cors")) {
        boundaryClientApiIds.push(iid);
        clientIssueIds.push(iid);
      }
      if (["jwt", "auth", "token", "password", "secret", "session"].some((k) => titleDesc.includes(k) || path.includes(k))) {
        authIssueIds.push(iid);
        boundaryApiAuthIds.push(iid);
      }
      if (["injection", "sql", "mongo"].some((k) => titleDesc.includes(k))) {
        dbIssueIds.push(iid);
        boundaryApiDbIds.push(iid);
      }
    }

    // Dependencies
    if (cat === "dependencies" || cat === "dependency") {
      if (["react", "vue", "client", "ui", "webpack", "vite", "tailwind", "lodash"].some((k) => path.includes(k) || titleDesc.includes(k))) {
        clientIssueIds.push(iid);
      } else {
        apiIssueIds.push(iid);
      }
    }

    // Deployment / Build
    if (cat === "deployment" || cat === "build") {
      workerIssueIds.push(iid);
      apiIssueIds.push(iid);
    }

    // Heuristics by file path
    const isFrontendFile =
      ["src/", "frontend/", "client/", "ui/"].some((p) => path.startsWith(p)) ||
      [".tsx", ".jsx", ".vue", ".html", ".css"].some((ext) => path.endsWith(ext));
    if (isFrontendFile && !clientIssueIds.includes(iid)) {
      clientIssueIds.push(iid);
    }

    const isBackendFile =
      ["backend/", "app/", "server/", "api/", "controllers/", "routes/"].some((p) => path.startsWith(p)) ||
      [".py", ".go", ".rs"].some((ext) => path.endsWith(ext));
    if (isBackendFile && !apiIssueIds.includes(iid)) {
      apiIssueIds.push(iid);
    }

    if (["nlp", "train", "intent", "corpus", "nltk", "dialogue"].some((k) => path.includes(k))) {
      workerIssueIds.push(iid);
      boundaryApiWorkerIds.push(iid);
    }

    if (["payment", "stripe", "checkout", "billing"].some((k) => path.includes(k))) {
      extIssueIds.push(iid);
      boundaryApiExtIds.push(iid);
    }
  }

  const unique = (arr: string[]) => Array.from(new Set(arr));

  const cleanClient = unique(clientIssueIds);
  const cleanApi = unique(apiIssueIds);
  const cleanDb = unique(dbIssueIds);
  const cleanAuth = unique(authIssueIds);
  const cleanWorker = unique(workerIssueIds);
  const cleanExt = unique(extIssueIds);

  const cleanEdgeClientApi = unique(boundaryClientApiIds);
  const cleanEdgeApiDb = unique(boundaryApiDbIds);
  const cleanEdgeApiAuth = unique(boundaryApiAuthIds);
  const cleanEdgeApiWorker = unique(boundaryApiWorkerIds);
  const cleanEdgeApiExt = unique(boundaryApiExtIds);

  const calcStatus = (edgeIds: string[]): ArchEdge["status"] => {
    const attached = edgeIds.map((id) => issueMap.get(id)).filter(Boolean) as Issue[];
    if (attached.some((i) => i.severity === "critical" || i.severity === "high")) {
      return "broken";
    }
    if (attached.some((i) => i.severity === "medium")) {
      return "warning";
    }
    return "ok";
  };

  const nodes: ArchNode[] = [];
  const edges: ArchEdge[] = [];

  // Node 1: Web Client (Backbone)
  nodes.push({
    id: "node_web",
    label: feLabel,
    kind: "frontend",
    tech: feTech,
    description: feDesc,
    issueIds: cleanClient,
    position: { x: 60, y: 180 },
  });

  // Node 2: Core API (Backbone)
  nodes.push({
    id: "node_api",
    label: beLabel,
    kind: "api",
    tech: beTech,
    description: beDesc,
    issueIds: cleanApi,
    position: { x: 380, y: 180 },
  });

  // Edge: Client -> API (Backbone)
  edges.push({
    id: "edge_client_api",
    source: "node_web",
    target: "node_api",
    label: isChatbotMl
      ? "Chat Stream / REST"
      : isNextjs
        ? "Server Actions / REST"
        : "REST /api/v1 (JSON)",
    status: calcStatus(cleanEdgeClientApi),
    issueIds: cleanEdgeClientApi,
  });

  if (isChatbotMl) {
    const workerTech = allTech.includes("nltk")
      ? "NLTK / Neural Classifier"
      : allTech.includes("torch")
        ? "PyTorch / Transformers"
        : "NLP Pipeline";

    nodes.push({
      id: "node_worker",
      label: "NLP Intent Engine",
      kind: "worker",
      tech: workerTech,
      description:
        "Evaluates conversational utterances, tokenizes text, and computes classification probabilities.",
      issueIds: cleanWorker,
      position: { x: 720, y: 90 },
    });

    nodes.push({
      id: "node_db",
      label: dbLabel,
      kind: "database",
      tech: dbTech,
      description: dbDesc,
      issueIds: cleanDb,
      position: { x: 720, y: 270 },
    });

    edges.push({
      id: "edge_api_worker",
      source: "node_api",
      target: "node_worker",
      label: "Intent Inference Pipeline",
      status: calcStatus(cleanEdgeApiWorker),
      issueIds: cleanEdgeApiWorker,
    });

    edges.push({
      id: "edge_api_db",
      source: "node_api",
      target: "node_db",
      label: "Corpus & Guideline Lookup",
      status: calcStatus(cleanEdgeApiDb),
      issueIds: cleanEdgeApiDb,
    });
  } else if (isEcommerceMarket) {
    const authLabel = allTech.includes("market")
      ? "Merchant & User Auth Guard"
      : "JWT Customer Auth Guard";
    const authTech = isExpress ? "JWT / Session Cookies" : "JWT + bcrypt";

    nodes.push({
      id: "node_auth",
      label: authLabel,
      kind: "auth",
      tech: authTech,
      description:
        "Cryptographic token issuance, password hashing, and role-based permissions.",
      issueIds: cleanAuth,
      position: { x: 380, y: 380 },
    });

    nodes.push({
      id: "node_db",
      label: dbLabel,
      kind: "database",
      tech: dbTech,
      description: dbDesc,
      issueIds: cleanDb,
      position: { x: 720, y: 70 },
    });

    const extLabel = allTech.includes("market")
      ? "Stripe Connect / Escrow"
      : "Stripe Payment Gateway";

    nodes.push({
      id: "node_external",
      label: extLabel,
      kind: "external",
      tech: "Stripe API & Webhooks",
      description:
        "Customer checkout sessions, payment intent processing, and settlement webhooks.",
      issueIds: cleanExt,
      position: { x: 720, y: 240 },
    });

    if (isRedis || allTech.includes("cache")) {
      nodes.push({
        id: "node_cache",
        label: "Cart & Session Cache",
        kind: "database",
        tech: "Redis 7.2",
        description:
          "Transient shopping cart states, session stores, and rate-limiting counters.",
        issueIds: [],
        position: { x: 720, y: 410 },
      });
    }

    edges.push({
      id: "edge_client_auth",
      source: "node_web",
      target: "node_auth",
      label: "OAuth & Login Flow",
      status: "ok",
      issueIds: [],
    });

    edges.push({
      id: "edge_api_auth",
      source: "node_api",
      target: "node_auth",
      label: "Bearer Token Validation",
      status: calcStatus(cleanEdgeApiAuth),
      issueIds: cleanEdgeApiAuth,
    });

    edges.push({
      id: "edge_api_db",
      source: "node_api",
      target: "node_db",
      label: isMongo ? "Mongoose ODM (Pool)" : "SQL Connection Pool",
      status: calcStatus(cleanEdgeApiDb),
      issueIds: cleanEdgeApiDb,
    });

    edges.push({
      id: "edge_api_ext",
      source: "node_api",
      target: "node_external",
      label: "Payment Intent / Webhooks",
      status: calcStatus(cleanEdgeApiExt),
      issueIds: cleanEdgeApiExt,
    });

    if (isRedis || allTech.includes("cache")) {
      edges.push({
        id: "edge_api_cache",
        source: "node_api",
        target: "node_cache",
        label: "RESP Protocol (TCP)",
        status: "ok",
        issueIds: [],
      });
    }
  } else {
    // Modern Fullstack / Microservices / Standard Architecture
    const hasAuth = isSupabase || allTech.includes("jwt") || allTech.includes("auth") || cleanAuth.length > 0;
    if (hasAuth) {
      nodes.push({
        id: "node_auth",
        label: isSupabase ? "Supabase Auth Guard" : "JWT Auth Service",
        kind: "auth",
        tech: isSupabase ? "Supabase GoTrue" : "JWT + bcrypt",
        description:
          "Manages session token issuance, cryptographic verification, and role-based access control.",
        issueIds: cleanAuth,
        position: { x: 380, y: 380 },
      });
    }

    nodes.push({
      id: "node_db",
      label: dbLabel,
      kind: "database",
      tech: dbTech,
      description: dbDesc,
      issueIds: cleanDb,
      position: { x: 720, y: 80 },
    });

    if (isRedis) {
      nodes.push({
        id: "node_cache",
        label: "Redis In-Memory Cache",
        kind: "database",
        tech: "Redis 7.2",
        description: "Key-value cache storing session tokens, rate limits, and warm query caches.",
        issueIds: [],
        position: { x: 720, y: 250 },
      });
    }

    if (isDocker || allTech.includes("celery") || allTech.includes("worker") || cleanWorker.length > 0) {
      nodes.push({
        id: "node_worker",
        label: isDocker ? "Async Worker Container" : "Background Queue Job",
        kind: "worker",
        tech: allTech.includes("celery") ? "Celery / Redis" : "Node / Docker Worker",
        description:
          "Executes long-running asynchronous tasks, batch reporting jobs, and data pipeline transforms.",
        issueIds: cleanWorker,
        position: { x: 720, y: 420 },
      });
    }

    const dbEdgeLabel = isMongo
      ? "Mongoose / ODM"
      : isNextjs
        ? "Prisma / SQL Pool"
        : isPostgres
          ? "SQLAlchemy / ORM"
          : "Datastore / Query";

    edges.push({
      id: "edge_api_db",
      source: "node_api",
      target: "node_db",
      label: dbEdgeLabel,
      status: calcStatus(cleanEdgeApiDb),
      issueIds: cleanEdgeApiDb,
    });

    if (hasAuth) {
      edges.push({
        id: "edge_client_auth",
        source: "node_web",
        target: "node_auth",
        label: "OAuth / Session Exchange",
        status: "ok",
        issueIds: [],
      });
      edges.push({
        id: "edge_api_auth",
        source: "node_api",
        target: "node_auth",
        label: "JWT Verification",
        status: calcStatus(cleanEdgeApiAuth),
        issueIds: cleanEdgeApiAuth,
      });
    }

    if (isRedis) {
      edges.push({
        id: "edge_api_cache",
        source: "node_api",
        target: "node_cache",
        label: "RESP Protocol (TCP)",
        status: "ok",
        issueIds: [],
      });
    }

    if (isDocker || allTech.includes("celery") || allTech.includes("worker") || cleanWorker.length > 0) {
      edges.push({
        id: "edge_worker_api",
        source: "node_api",
        target: "node_worker",
        label: "Event Ingestion Bus",
        status: calcStatus(cleanEdgeApiWorker),
        issueIds: cleanEdgeApiWorker,
      });
    }
  }

  return { nodes, edges };
}
