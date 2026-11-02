import { describe, it, expect } from "vitest";
import type { Issue } from "@/types/issue";

function filterIssues(
  issues: Issue[],
  filters: {
    status?: string;
    severities?: string[];
    query?: string;
  },
): Issue[] {
  return issues.filter((issue) => {
    if (filters.status && filters.status !== "all" && issue.status !== filters.status) {
      return false;
    }
    if (
      filters.severities &&
      filters.severities.length > 0 &&
      !filters.severities.includes(issue.severity)
    ) {
      return false;
    }
    if (filters.query) {
      const q = filters.query.toLowerCase();
      const match =
        issue.title.toLowerCase().includes(q) ||
        issue.filePath.toLowerCase().includes(q) ||
        issue.shortDescription.toLowerCase().includes(q);
      if (!match) return false;
    }
    return true;
  });
}

describe("Issue Filtering Pure Logic", () => {
  const sampleIssues: Issue[] = [
    {
      id: "iss-1",
      projectId: "proj-1",
      category: "integration",
      severity: "critical",
      status: "open",
      title: "Contract mismatch in user endpoint",
      shortDescription: "Frontend calls /api/users, backend expects /api/user",
      filePath: "src/api/users.ts",
      explanation: "Explanation",
      impact: "High impact",
      suggestedFix: { summary: "Fix endpoint", steps: ["Update route"] },
    },
    {
      id: "iss-2",
      projectId: "proj-1",
      category: "security",
      severity: "high",
      status: "resolved",
      title: "Hardcoded secret in config",
      shortDescription: "API secret token in plaintext",
      filePath: "src/config.ts",
      explanation: "Explanation",
      impact: "High risk",
      suggestedFix: { summary: "Use env var", steps: ["Add .env"] },
    },
    {
      id: "iss-3",
      projectId: "proj-1",
      category: "dependencies",
      severity: "medium",
      status: "open",
      title: "Vulnerable lodash version",
      shortDescription: "Prototype pollution vulnerability",
      filePath: "package.json",
      explanation: "Explanation",
      impact: "Medium",
      suggestedFix: { summary: "Bump package", steps: ["npm update lodash"] },
    },
  ];

  it("filters by status correctly", () => {
    const openOnly = filterIssues(sampleIssues, { status: "open" });
    expect(openOnly).toHaveLength(2);
    expect(openOnly.map((i) => i.id)).toEqual(["iss-1", "iss-3"]);

    const resolvedOnly = filterIssues(sampleIssues, { status: "resolved" });
    expect(resolvedOnly).toHaveLength(1);
    expect(resolvedOnly[0]?.id).toBe("iss-2");
  });

  it("filters by severity multi-selection", () => {
    const criticalOrHigh = filterIssues(sampleIssues, { severities: ["critical", "high"] });
    expect(criticalOrHigh).toHaveLength(2);

    const mediumOnly = filterIssues(sampleIssues, { severities: ["medium"] });
    expect(mediumOnly).toHaveLength(1);
  });

  it("filters by query matching title or file path", () => {
    const byQuery = filterIssues(sampleIssues, { query: "lodash" });
    expect(byQuery).toHaveLength(1);
    expect(byQuery[0]?.title).toContain("lodash");

    const byPath = filterIssues(sampleIssues, { query: "package.json" });
    expect(byPath).toHaveLength(1);
  });

  it("combines status, severity, and query filters", () => {
    const combined = filterIssues(sampleIssues, {
      status: "open",
      severities: ["critical"],
      query: "contract",
    });
    expect(combined).toHaveLength(1);
    expect(combined[0]?.id).toBe("iss-1");
  });
});
