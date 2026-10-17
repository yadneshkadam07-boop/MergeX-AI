import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { IssueTable } from "@/components/IssueTable";
import { filterIssues } from "@/lib/issues";
import { makeIssue } from "@/test/factories";

const ISSUES = [
  makeIssue({
    severity: "critical",
    category: "security",
    rule_id: "MX-SEC-001",
    title: "Hardcoded credential in frontend source",
    file_path: "frontend/src/api/config.ts",
  }),
  makeIssue({
    severity: "high",
    category: "api_contract",
    rule_id: "MX-API-002",
    title: "Frontend request path looks like a typo of a real route",
    file_path: "frontend/src/api/users.ts",
  }),
  makeIssue({
    severity: "high",
    category: "schema",
    rule_id: "MX-DB-001",
    title: "ORM field has no matching database column",
    file_path: "backend/app/models.py",
  }),
  makeIssue({
    severity: "medium",
    category: "dependency",
    rule_id: "MX-DEP-001",
    title: "Dependency has a known vulnerability",
    file_path: "backend/requirements.txt",
  }),
  makeIssue({
    severity: "low",
    category: "api_contract",
    rule_id: "MX-API-006",
    title: "Backend route is never called",
    file_path: "backend/app/routes.py",
  }),
];

/** Rows, excluding the header. */
function rows(): HTMLElement[] {
  const [, ...bodyRows] = screen.getAllByRole("row");
  return bodyRows;
}

function titles(): string[] {
  return rows().map((row) => within(row).getAllByRole("cell")[1]?.textContent ?? "");
}

async function selectOption(
  user: ReturnType<typeof userEvent.setup>,
  label: string | RegExp,
  option: string,
) {
  await user.click(screen.getByRole("combobox", { name: label }));
  await user.click(await screen.findByRole("option", { name: option }));
}

describe("filterIssues", () => {
  it("returns everything when nothing is filtered", () => {
    expect(filterIssues(ISSUES, { severity: "all", category: "all", query: "" })).toHaveLength(5);
  });

  it("filters by severity", () => {
    const result = filterIssues(ISSUES, { severity: "high", category: "all", query: "" });

    expect(result.map((issue) => issue.rule_id)).toEqual(["MX-API-002", "MX-DB-001"]);
  });

  it("filters by category", () => {
    const result = filterIssues(ISSUES, { severity: "all", category: "api_contract", query: "" });

    expect(result.map((issue) => issue.rule_id)).toEqual(["MX-API-002", "MX-API-006"]);
  });

  it("combines severity and category", () => {
    const result = filterIssues(ISSUES, {
      severity: "high",
      category: "api_contract",
      query: "",
    });

    expect(result.map((issue) => issue.rule_id)).toEqual(["MX-API-002"]);
  });

  it("searches the title", () => {
    const result = filterIssues(ISSUES, { severity: "all", category: "all", query: "typo" });

    expect(result.map((issue) => issue.rule_id)).toEqual(["MX-API-002"]);
  });

  it("searches the rule id", () => {
    const result = filterIssues(ISSUES, { severity: "all", category: "all", query: "MX-DEP" });

    expect(result.map((issue) => issue.rule_id)).toEqual(["MX-DEP-001"]);
  });

  it("searches the file path", () => {
    const result = filterIssues(ISSUES, { severity: "all", category: "all", query: "models.py" });

    expect(result.map((issue) => issue.rule_id)).toEqual(["MX-DB-001"]);
  });

  it("ignores case and surrounding space", () => {
    const result = filterIssues(ISSUES, { severity: "all", category: "all", query: "  mx-sec  " });

    expect(result.map((issue) => issue.rule_id)).toEqual(["MX-SEC-001"]);
  });

  it("tolerates an issue with no file path", () => {
    const issues = [makeIssue({ file_path: null, rule_id: "MX-SEC-003" })];

    expect(filterIssues(issues, { severity: "all", category: "all", query: "sec" })).toHaveLength(
      1,
    );
  });

  it("preserves the backend's ordering", () => {
    const result = filterIssues(ISSUES, { severity: "all", category: "all", query: "a" });

    const original = ISSUES.filter((issue) => result.includes(issue));
    expect(result).toEqual(original);
  });

  it("returns nothing when nothing matches", () => {
    expect(filterIssues(ISSUES, { severity: "all", category: "all", query: "zzzzz" })).toHaveLength(
      0,
    );
  });
});

describe("IssueTable", () => {
  it("renders every issue", () => {
    render(<IssueTable issues={ISSUES} onSelect={vi.fn()} />);

    expect(rows()).toHaveLength(5);
    expect(screen.getByText("5 issues")).toBeInTheDocument();
  });

  it("filters as the user types", async () => {
    const user = userEvent.setup();
    render(<IssueTable issues={ISSUES} onSelect={vi.fn()} />);

    await user.type(screen.getByRole("textbox", { name: /search issues/i }), "typo");

    expect(rows()).toHaveLength(1);
    expect(titles()[0]).toContain("MX-API-002");
    expect(screen.getByText("1 of 5 issues")).toBeInTheDocument();
  });

  it("filters by severity from the dropdown", async () => {
    const user = userEvent.setup();
    render(<IssueTable issues={ISSUES} onSelect={vi.fn()} />);

    await selectOption(user, /filter by severity/i, "Critical");

    expect(rows()).toHaveLength(1);
    expect(titles()[0]).toContain("MX-SEC-001");
  });

  it("filters by category from the dropdown", async () => {
    const user = userEvent.setup();
    render(<IssueTable issues={ISSUES} onSelect={vi.fn()} />);

    await selectOption(user, /filter by category/i, "API contract");

    expect(rows()).toHaveLength(2);
  });

  it("applies the search and the dropdowns together", async () => {
    const user = userEvent.setup();
    render(<IssueTable issues={ISSUES} onSelect={vi.fn()} />);

    await selectOption(user, /filter by severity/i, "High");
    await user.type(screen.getByRole("textbox", { name: /search issues/i }), "backend/");

    expect(rows()).toHaveLength(1);
    expect(titles()[0]).toContain("MX-DB-001");
  });

  it("explains an empty result instead of showing a blank table", async () => {
    const user = userEvent.setup();
    render(<IssueTable issues={ISSUES} onSelect={vi.fn()} />);

    await user.type(screen.getByRole("textbox", { name: /search issues/i }), "nothing matches");

    expect(screen.getByText(/no issues match these filters/i)).toBeInTheDocument();
  });

  it("clears every filter at once", async () => {
    const user = userEvent.setup();
    render(<IssueTable issues={ISSUES} onSelect={vi.fn()} />);
    await selectOption(user, /filter by severity/i, "Critical");
    await user.type(screen.getByRole("textbox", { name: /search issues/i }), "sec");

    await user.click(screen.getByRole("button", { name: /clear/i }));

    expect(rows()).toHaveLength(5);
    expect(screen.getByRole("textbox", { name: /search issues/i })).toHaveValue("");
  });

  it("offers no clear button until something is filtered", async () => {
    const user = userEvent.setup();
    render(<IssueTable issues={ISSUES} onSelect={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /clear/i })).not.toBeInTheDocument();

    await user.type(screen.getByRole("textbox", { name: /search issues/i }), "a");

    expect(screen.getByRole("button", { name: /clear/i })).toBeInTheDocument();
  });

  it("selects an issue on click", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<IssueTable issues={ISSUES} onSelect={onSelect} />);

    await user.click(screen.getByRole("row", { name: /hardcoded credential/i }));

    expect(onSelect).toHaveBeenCalledWith(ISSUES[0]);
  });

  it("selects an issue from the keyboard", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<IssueTable issues={ISSUES} onSelect={onSelect} />);

    screen.getByRole("row", { name: /hardcoded credential/i }).focus();
    await user.keyboard("{Enter}");

    expect(onSelect).toHaveBeenCalledWith(ISSUES[0]);
  });

  it("shows the severity of every row", () => {
    render(<IssueTable issues={ISSUES} onSelect={vi.fn()} />);

    const labels = rows().map((row) => within(row).getAllByRole("cell")[0]?.textContent);
    expect(labels).toEqual(["Critical", "High", "High", "Medium", "Low"]);
  });

  it("handles a report with no issues", () => {
    render(<IssueTable issues={[]} onSelect={vi.fn()} />);

    expect(screen.getByText("0 issues")).toBeInTheDocument();
    expect(screen.getByText(/no issues match these filters/i)).toBeInTheDocument();
  });
});
