import type { Project } from "@/types/project";
import type { Issue } from "@/types/issue";
import type { ArchNode, ArchEdge } from "@/types/architecture";

/**
 * Deterministically generates architecture topology with 6-9 nodes and connects them.
 * Evaluates open issues to assign issues to nodes and determine edge statuses (broken / warning / ok).
 */
export function generateArchitecture(
  project: Project,
  issues: Issue[],
): { nodes: ArchNode[]; edges: ArchEdge[] } {
  // Filter for active open issues (resolved/ignored issues do not count)
  const openIssues = issues.filter((i) => i.status === "open");

  // Map issues by category for easy attachment
  const integrationIssueIds = openIssues
    .filter((i) => i.category === "integration")
    .map((i) => i.id);
  const securityIssueIds = openIssues.filter((i) => i.category === "security").map((i) => i.id);
  const depIssueIds = openIssues.filter((i) => i.category === "dependencies").map((i) => i.id);
  const deployIssueIds = openIssues.filter((i) => i.category === "deployment").map((i) => i.id);

  // Extract stack hints
  const hasSupabase = project.stack.some((s) => s.toLowerCase().includes("supabase"));
  const hasDocker = project.stack.some((s) => s.toLowerCase().includes("docker"));
  const hasFastAPI = project.stack.some((s) => s.toLowerCase().includes("fastapi"));
  const hasNext = project.stack.some((s) => s.toLowerCase().includes("next"));
  const hasRedis = project.stack.some((s) => s.toLowerCase().includes("redis"));

  const nodes: ArchNode[] = [
    // 1. Frontend Client
    {
      id: "node_frontend",
      label: hasNext ? "Next.js Web Client" : "React SPA Frontend",
      kind: "frontend",
      tech: hasNext ? "Next.js (App Router)" : "React 19 + Vite",
      description:
        "Client-side interactive user interface routing views and executing API fetch calls.",
      issueIds: depIssueIds.slice(0, 2),
      position: { x: 50, y: 180 },
    },

    // 2. Main API Service
    {
      id: "node_api",
      label: hasFastAPI ? "FastAPI Core Gateway" : "Express / Node API",
      kind: "api",
      tech: hasFastAPI ? "FastAPI (Python 3.12)" : "Node.js REST Service",
      description:
        "Central application gateway providing REST and RPC services, business logic, and middleware.",
      issueIds: [...securityIssueIds.slice(0, 2), ...deployIssueIds.slice(0, 1)],
      position: { x: 380, y: 180 },
    },

    // 3. Auth Service
    {
      id: "node_auth",
      label: hasSupabase ? "Supabase Auth Guard" : "JWT Auth Service",
      kind: "auth",
      tech: hasSupabase ? "Supabase GoTrue" : "JWT + bcrypt",
      description:
        "Manages session token issuance, cryptographic verification, and role-based access control.",
      issueIds: securityIssueIds.slice(2, 4),
      position: { x: 380, y: 380 },
    },

    // 4. Primary Database
    {
      id: "node_db",
      label: "PostgreSQL Database",
      kind: "database",
      tech: hasSupabase ? "PostgreSQL (Supabase)" : "PostgreSQL 16",
      description:
        "Primary relational persistent store housing schema models, tables, and foreign keys.",
      issueIds: integrationIssueIds.slice(1, 3),
      position: { x: 720, y: 80 },
    },

    // 5. Cache / Queue or Redis
    {
      id: "node_cache",
      label: hasRedis ? "Redis In-Memory Cache" : "Memory Cache Layer",
      kind: "database",
      tech: hasRedis ? "Redis 7.2" : "In-Memory LRU Store",
      description:
        "Key-value cache storing ephemeral session tokens, rate limits, and warm database query caches.",
      issueIds: [],
      position: { x: 720, y: 260 },
    },

    // 6. External AI / Provider
    {
      id: "node_external",
      label: "OpenAI / Claude API",
      kind: "external",
      tech: "HTTPS REST API",
      description:
        "External multi-agent foundation model inference service for AI-assisted processing.",
      issueIds: securityIssueIds
        .filter((id) => id.includes("iss_5") || id.includes("iss_2"))
        .slice(0, 1),
      position: { x: 720, y: 440 },
    },

    // 7. Background Worker / Queue (if Docker or FastAPI)
    {
      id: "node_worker",
      label: hasDocker ? "Async Worker Container" : "Background Queue Job",
      kind: "worker",
      tech: "Celery / Node Worker",
      description:
        "Executes long-running asynchronous tasks, batch reporting jobs, and data pipeline transforms.",
      issueIds: deployIssueIds.slice(1, 3),
      position: { x: 380, y: -20 },
    },
  ];

  // Helper to calculate edge status based on attached issues
  const calculateEdgeStatus = (edgeIssueIds: string[]): ArchEdge["status"] => {
    const attached = openIssues.filter((i) => edgeIssueIds.includes(i.id));
    if (attached.some((i) => i.severity === "critical" || i.severity === "high")) {
      return "broken";
    }
    if (attached.some((i) => i.severity === "medium")) {
      return "warning";
    }
    return "ok";
  };

  const frontendToApiIssues = integrationIssueIds;
  const apiToDbIssues = integrationIssueIds.slice(1, 3);
  const apiToAuthIssues = securityIssueIds.slice(0, 2);

  const edges: ArchEdge[] = [
    {
      id: "edge_fe_api",
      source: "node_frontend",
      target: "node_api",
      label: "REST /api/v1 (JSON)",
      status: calculateEdgeStatus(frontendToApiIssues),
      issueIds: frontendToApiIssues,
    },
    {
      id: "edge_fe_auth",
      source: "node_frontend",
      target: "node_auth",
      label: "OAuth / Session Exchange",
      status: "ok",
      issueIds: [],
    },
    {
      id: "edge_api_db",
      source: "node_api",
      target: "node_db",
      label: "SQL ORM (Pool)",
      status: calculateEdgeStatus(apiToDbIssues),
      issueIds: apiToDbIssues,
    },
    {
      id: "edge_api_cache",
      source: "node_api",
      target: "node_cache",
      label: "RESP Protocol (TCP)",
      status: "ok",
      issueIds: [],
    },
    {
      id: "edge_api_auth",
      source: "node_api",
      target: "node_auth",
      label: "JWT Verification",
      status: calculateEdgeStatus(apiToAuthIssues),
      issueIds: apiToAuthIssues,
    },
    {
      id: "edge_api_ext",
      source: "node_api",
      target: "node_external",
      label: "HTTPS Model Inference",
      status: "ok",
      issueIds: [],
    },
    {
      id: "edge_worker_api",
      source: "node_worker",
      target: "node_api",
      label: "Event Ingestion Bus",
      status: calculateEdgeStatus(deployIssueIds),
      issueIds: deployIssueIds,
    },
    {
      id: "edge_worker_db",
      source: "node_worker",
      target: "node_db",
      label: "Batch Processing Write",
      status: "ok",
      issueIds: [],
    },
  ];

  return { nodes, edges };
}
