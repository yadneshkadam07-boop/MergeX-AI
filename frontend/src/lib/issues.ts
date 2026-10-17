import type { Category, ReportIssue, Severity } from "@/api/analyses";

/** The "no filter" sentinel. A Radix Select item cannot have an empty value. */
export const ALL = "all";

export interface IssueFilters {
  severity: Severity | typeof ALL;
  category: Category | typeof ALL;
  query: string;
}

/** Order is the backend's (most severe first); filtering must not reorder. */
export function filterIssues(issues: ReportIssue[], filters: IssueFilters): ReportIssue[] {
  const query = filters.query.trim().toLowerCase();

  return issues.filter((issue) => {
    if (filters.severity !== ALL && issue.severity !== filters.severity) return false;
    if (filters.category !== ALL && issue.category !== filters.category) return false;
    if (!query) return true;

    // Searched fields are the ones a user would recognise an issue by: what
    // it is, which rule found it, and where it is.
    const haystack = [issue.title, issue.rule_id, issue.file_path ?? "", issue.description]
      .join(" ")
      .toLowerCase();
    return haystack.includes(query);
  });
}
