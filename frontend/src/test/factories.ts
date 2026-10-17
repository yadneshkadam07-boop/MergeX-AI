import type { Category, ReportIssue, Severity } from "@/api/analyses";

let counter = 0;

/**
 * A report issue with sensible defaults.
 *
 * Shaped exactly like the backend's `ReportIssue`, so a change to that
 * contract shows up as a type error here rather than as a passing test
 * against a shape the API no longer returns.
 */
export function makeIssue(overrides: Partial<ReportIssue> = {}): ReportIssue {
  counter += 1;
  const severity: Severity = overrides.severity ?? "high";
  const category: Category = overrides.category ?? "api_contract";

  return {
    id: `issue-${counter}`,
    rule_id: "MX-API-001",
    category,
    severity,
    title: "Frontend calls an endpoint the backend does not define",
    description: "The call has no matching backend route.",
    file_path: "frontend/src/api/users.ts",
    line_start: 7,
    line_end: 7,
    evidence: "const response = await api.get(`/api/user/${id}`);",
    expected: "GET /api/users/{id}",
    actual: "GET /api/user/{id}",
    confidence: 1,
    fingerprint: `fp-${counter}`,
    explanation: "The path is singular; the backend serves the plural form.",
    suggested_fix: "At frontend/src/api/users.ts:7, use /api/users/${id}.",
    explanation_source: "template",
    fix_before: "await api.get(`/api/user/${id}`);",
    fix_after: "await api.get(`/api/users/${id}`);",
    ...overrides,
  };
}
