import type { IssueCategory, IssueSeverity } from "@/types/project";
export type { IssueCategory, IssueSeverity };

export type IssueStatus = "open" | "resolved" | "ignored";

export interface SuggestedFix {
  summary: string;
  steps: string[];
  codeBefore?: string;
  codeAfter?: string;
  language?: string;
}

export interface IssueMeta {
  integration?: {
    frontendRef?: string;
    backendRef?: string;
  };
  security?: {
    cwe?: string;
    owaspCategory?: string;
  };
  dependencies?: {
    packageName: string;
    currentVersion: string;
    latestVersion: string;
    cve?: string;
  };
}

export interface Issue {
  id: string;
  projectId: string;
  category: IssueCategory;
  severity: IssueSeverity;
  status: IssueStatus;
  title: string;
  shortDescription: string;
  filePath: string;
  lineStart?: number;
  lineEnd?: number;
  explanation: string;
  impact: string;
  suggestedFix: SuggestedFix;
  meta?: IssueMeta;
}

export interface ChecklistItem {
  id: string;
  label: string;
  status: "pass" | "warn" | "fail";
  detail: string;
}
