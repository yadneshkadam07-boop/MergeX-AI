export type ProjectStatus = "analyzing" | "completed" | "failed";

export type IssueCategory = "integration" | "security" | "dependencies" | "deployment";

export type IssueSeverity = "critical" | "high" | "medium" | "low";

export interface IssueCounts {
  integration: number;
  security: number;
  dependencies: number;
  deployment: number;
}

export interface CategoryScores {
  integration: number; // 0 - 100
  security: number; // 0 - 100
  dependencies: number; // 0 - 100
  deployment: number; // 0 - 100
}

export interface SeverityCounts {
  critical: number;
  high: number;
  medium: number;
  low: number;
}

export interface PriorityIssue {
  id: string;
  title: string;
  category: IssueCategory;
  severity: IssueSeverity;
  filePath: string;
  shortDescription: string;
}

export interface ScanMeta {
  branch: string;
  commitSha: string; // 7 chars
  durationSeconds: number;
  filesScanned: number;
  agentsRun: number;
}

export interface Project {
  id: string;
  name: string;
  owner: string;
  repoUrl: string;
  stack: string[];
  healthScore: number; // 0 - 100
  status: ProjectStatus;
  issueCounts: IssueCounts;
  lastScannedAt: string; // ISO date string

  // Extended Stage 4 properties
  categoryScores: CategoryScores;
  severityCounts: SeverityCounts;
  topIssues: PriorityIssue[];
  scanMeta: ScanMeta;
}

export type StepStatus = "pending" | "running" | "done";

export interface AnalysisStep {
  id: number;
  label: string;
  status: StepStatus;
}
