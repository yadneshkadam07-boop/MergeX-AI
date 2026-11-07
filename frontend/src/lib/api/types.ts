import type { Project, AnalysisStep } from "@/types/project";
import type { Issue, IssueCategory, IssueStatus, ChecklistItem } from "@/types/issue";
import type { ArchNode, ArchEdge } from "@/types/architecture";
import type { ProjectReport } from "@/types/report";
import type { UserSettings } from "@/types/settings";

export interface CreateAnalysisPayload {
  repoUrl: string;
  branch?: string;
}

export interface CreateAnalysisResponse extends Project {
  analysisId: string;
  projectId: string;
  steps: AnalysisStep[];
}

export interface AnalysisStatusResponse {
  id: string;
  projectId: string;
  status: "pending" | "running" | "completed" | "failed" | "analyzing";
  progressPercent: number;
  currentStepIndex: number;
  activeStep?: string;
  error?: string;
  project?: Project;
}

export interface IssueFilterParams {
  category?: IssueCategory;
  severity?: string;
  status?: string;
  q?: string;
}

export interface ArchitectureResponse {
  nodes: ArchNode[];
  edges: ArchEdge[];
}

export interface CreatePullRequestResponse {
  prUrl: string;
  prNumber: number;
  branch: string;
  status: string;
  note?: string;
}

export interface ApiClientContract {
  getProjects(): Promise<Project[]>;
  getProject(id: string): Promise<Project | null>;
  createAnalysis(
    repoUrl: string,
    branch?: string,
    githubToken?: string,
  ): Promise<CreateAnalysisResponse>;
  getAnalysisStatus(analysisId: string): Promise<AnalysisStatusResponse>;
  updateProject(id: string, updates: Partial<Project>): Promise<Project>;
  getIssues(projectId: string, category?: IssueCategory): Promise<Issue[]>;
  getIssue(projectId: string, issueId: string): Promise<Issue | null>;
  updateIssueStatus(projectId: string, issueId: string, status: IssueStatus): Promise<Issue>;
  createPullRequest(
    projectId: string,
    issueId: string,
    githubToken?: string,
  ): Promise<CreatePullRequestResponse>;
  getDeployChecklist(projectId: string): Promise<ChecklistItem[]>;
  getArchitecture(projectId: string): Promise<ArchitectureResponse>;
  getReport(projectId: string): Promise<ProjectReport>;
  rescanProject(projectId: string): Promise<Project>;
  getSettings(): Promise<UserSettings>;
  saveSettings(settings: UserSettings): Promise<void>;
}
