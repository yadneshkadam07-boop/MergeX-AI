import { apiFetch } from "@/api/client";

/** Severity levels, ordered most severe first. */
export const SEVERITIES = ["critical", "high", "medium", "low"] as const;
export type Severity = (typeof SEVERITIES)[number];

export const CATEGORIES = ["api_contract", "schema", "security", "dependency"] as const;
export type Category = (typeof CATEGORIES)[number];

export type AnalysisStatus = "pending" | "running" | "succeeded" | "failed";

/** One finding, with everything needed to render it. Mirrors `ReportIssue`. */
export interface ReportIssue {
  id: string;
  rule_id: string;
  category: Category;
  severity: Severity;
  title: string;
  description: string;

  file_path: string | null;
  line_start: number | null;
  line_end: number | null;
  evidence: string | null;

  expected: string | null;
  actual: string | null;
  confidence: number;
  fingerprint: string;

  explanation: string | null;
  suggested_fix: string | null;
  /** `"gemini"` or `"template"` — which wrote the prose above. */
  explanation_source: string | null;
  fix_before: string | null;
  fix_after: string | null;
}

export interface CategoryScore {
  score: number;
  issue_count: number;
  severity_counts: Partial<Record<Severity, number>>;
  /**
   * False when the project had nothing of this kind to check, or when the
   * rule group crashed. A score of 100 then means "not applicable", not
   * "perfect", and the UI must say so.
   */
  analysed: boolean;
}

export interface Score {
  score: number;
  total_issues: number;
  severity_counts: Partial<Record<Severity, number>>;
  categories: Partial<Record<Category, CategoryScore>>;
  is_floored: boolean;
}

export interface AnalysisReport {
  analysis_id: string;
  project_id: string;
  project_name: string;
  status: AnalysisStatus;

  /** Null until the analysis succeeds. */
  score: Score | null;
  issues: ReportIssue[];

  stack: Record<string, unknown> | null;
  /** Caveats about completeness: what could not be checked, and why. */
  notes: string[];
  /** Rule groups that crashed. Their categories are unreliable. */
  failed_groups: Category[];
  counts: Record<string, number>;
  explanation_sources: Record<string, number>;

  commit_sha: string | null;
  file_count: number | null;
  duration_ms: number | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface AnalysisSummary {
  id: string;
  project_id: string;
  status: AnalysisStatus;
  stage: string | null;
  health_score: number | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export const analysisKeys = {
  all: ["analyses"] as const,
  detail: (id: string) => ["analyses", id] as const,
  report: (id: string) => ["analyses", id, "report"] as const,
};

/** Queue a run. Returns immediately; follow progress over SSE. */
export function createAnalysis(projectId: string): Promise<AnalysisSummary> {
  return apiFetch<AnalysisSummary>(`/api/v1/projects/${projectId}/analyses`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function getAnalysis(analysisId: string): Promise<AnalysisSummary> {
  return apiFetch<AnalysisSummary>(`/api/v1/analyses/${analysisId}`);
}

export function getReport(analysisId: string): Promise<AnalysisReport> {
  return apiFetch<AnalysisReport>(`/api/v1/analyses/${analysisId}/report`);
}
