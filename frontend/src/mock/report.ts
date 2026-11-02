import type { Project } from "@/types/project";
import type { Issue } from "@/types/issue";
import type { ArchNode, ArchEdge } from "@/types/architecture";
import type { ProjectReport } from "@/types/report";
import { generateChecklist } from "@/mock/issues";

export function generateReport(
  project: Project,
  issues: Issue[],
  architecture: { nodes: ArchNode[]; edges: ArchEdge[] },
): ProjectReport {
  const openIssues = issues.filter((i) => i.status === "open");
  const checklist = generateChecklist(project);

  const criticalCount = openIssues.filter((i) => i.severity === "critical").length;
  const highCount = openIssues.filter((i) => i.severity === "high").length;
  const mediumCount = openIssues.filter((i) => i.severity === "medium").length;
  const lowCount = openIssues.filter((i) => i.severity === "low").length;

  const topOpen = [...openIssues]
    .sort((a, b) => {
      const order = { critical: 0, high: 1, medium: 2, low: 3 };
      return order[a.severity] - order[b.severity];
    })
    .slice(0, 5);

  const sections = [
    // 1. Project Overview
    {
      id: "overview",
      title: "1. Project Overview",
      markdown: `### Executive Summary

- **Project Name:** ${project.name}
- **Repository:** [${project.owner}/${project.name}](${project.repoUrl})
- **Overall Health Score:** **${project.healthScore}/100**
- **Analysis Status:** ${project.status.toUpperCase()}
- **Scanned Branch:** \`${project.scanMeta.branch}\` (Commit \`${project.scanMeta.commitSha}\`)
- **Diagnostic Run Duration:** ${project.scanMeta.durationSeconds}s across ${project.scanMeta.filesScanned} files
- **Identified Stack:** ${project.stack.join(", ")}

MergeX AI multi-agent diagnostics evaluated this repository across AST code structure, API route contracts, database schema synchronization, third-party dependency vulnerabilities, and deployment readiness.`,
    },

    // 2. Architecture Summary
    {
      id: "architecture",
      title: "2. Architecture Summary",
      markdown: `### System Topology

The analyzed architecture comprises **${architecture.nodes.length} major system components** and **${architecture.edges.length} interconnecting communications channels**.

| Component | Kind | Technology Stack | Active Issues |
| :--- | :--- | :--- | :--- |
${architecture.nodes
  .map(
    (n) =>
      `| **${n.label}** | \`${n.kind}\` | ${n.tech} | ${
        n.issueIds.length > 0 ? `**${n.issueIds.length} open**` : "Clean"
      } |`,
  )
  .join("\n")}

#### Topology Insights
- Primary client ingestion pathways communicate via REST JSON schemas to the central API gateway.
- Data persistence utilizes connection pooling to relational database storage with isolated caching layers.`,
    },

    // 3. API Endpoints Table
    {
      id: "api-endpoints",
      title: "3. API Endpoints & Contract Drift",
      markdown: `### Discovered API Route Specifications

| Method | Endpoint Route | Target Component | Status / Notes |
| :--- | :--- | :--- | :--- |
| \`GET\` | \`/api/v1/health\` | Core API | Returns service health & DB socket pool status |
| \`POST\` | \`/api/v1/auth/login\` | Auth Service | Session token generation |
| \`GET\` | \`/api/v1/users/me\` | Core API | Retrieves authenticated user profile |
| \`GET\` | \`/api/users\` | Core API | **Contract Drift Detected**: Frontend requests plural, backend binds singular \`/api/user\` |
| \`POST\` | \`/api/v1/orders\` | Core API | Order creation endpoint (validates payload schema) |
| \`GET\` | \`/api/v1/search\` | Core API | Query items catalogue (pagination limit recommended) |
| \`POST\` | \`/api/v1/ai/generate\` | External Provider | Inferences prompt generation tasks |`,
    },

    // 4. Database Schema Summary
    {
      id: "database-schema",
      title: "4. Database Schema Summary",
      markdown: `### Primary Data Entities

| Table Name | Primary Key | Key Attributes | Integrity Flags |
| :--- | :--- | :--- | :--- |
| \`users\` | \`id\` (UUID) | \`email\`, \`username\`, \`role\`, \`created_at\` | Clean constraint indices |
| \`orders\` | \`id\` (Integer) | \`user_id\`, \`amount\`, \`status\`, \`currency\` | **Warning**: Missing foreign key constraint on \`user_id\` |
| \`sessions\` | \`id\` (String) | \`user_id\`, \`expires_at\`, \`token_hash\` | Indexed with cascading deletion |
| \`audit_logs\` | \`id\` (BigInt) | \`action\`, \`actor_id\`, \`ip_address\`, \`timestamp\` | Immutable append-only partition |`,
    },

    // 5. Findings Summary
    {
      id: "findings",
      title: "5. Findings Summary & Priority Triage",
      markdown: `### Diagnostic Severity Breakdown

| Severity Level | Open Count |
| :--- | :--- |
| **Critical** | ${criticalCount} |
| **High** | ${highCount} |
| **Medium** | ${mediumCount} |
| **Low** | ${lowCount} |
| **Total Open Issues** | **${openIssues.length}** |

#### Top Priority Remediations
${
  topOpen.length === 0
    ? "_No critical or high open issues detected._"
    : topOpen
        .map(
          (iss, idx) =>
            `${idx + 1}. **[${iss.severity.toUpperCase()}]** ${iss.title}\n   - **File:** \`${iss.filePath}\`\n   - **Impact:** ${iss.impact}`,
        )
        .join("\n\n")
}`,
    },

    // 6. Deployment Readiness
    {
      id: "deployment-readiness",
      title: "6. Deployment Readiness Verification",
      markdown: `### Pre-Flight Deployment Checklist

| Verification Check | Status | Verification Details |
| :--- | :--- | :--- |
${checklist.map((c) => `| **${c.label}** | \`${c.status.toUpperCase()}\` | ${c.detail} |`).join("\n")}`,
    },

    // 7. Recommended Next Steps
    {
      id: "next-steps",
      title: "7. Recommended Next Steps",
      markdown: `### Immediate Remediation Playbook

To unblock production merges and elevate the project health score above 85, implement the following steps:

1. **Resolve Contract Route Drift:** Align \`/api/users\` client endpoints with \`/api/user\` backend route definitions.
2. **Apply Database Migration:** Declare an explicit foreign key on \`orders.user_id\` referencing \`users.id\`.
3. **Purge Committed Secret Keys:** Revoke any API keys present in runtime files and bind them exclusively to environment variables.
4. **Restrict CORS Allowlist:** Update CORS policy from wildcard \`*\` to trusted host domains.
5. **Pin Vulnerable Packages:** Upgrade pinned dependencies reporting CVE vulnerabilities to patched minor versions.`,
    },
  ];

  return {
    generatedAt: new Date().toISOString(),
    sections,
  };
}
