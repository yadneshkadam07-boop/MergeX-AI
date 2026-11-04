/**
 * MergeX AI API Gateway
 *
 * Dispatches API calls between the deterministic Mock implementation and the
 * real FastAPI backend based on runtime configuration (`isMock()`).
 */

import type { Project } from "@/types/project";
import type { Issue, IssueCategory, IssueStatus, ChecklistItem } from "@/types/issue";
import type { ProjectReport } from "@/types/report";
import type { UserSettings } from "@/types/settings";
import type {
  CreateAnalysisResponse,
  AnalysisStatusResponse,
  ArchitectureResponse,
  CreatePullRequestResponse,
} from "./api/types";
import { isMock } from "./config";
import { mockApi } from "./api/mock";
import { realApi } from "./api/real";

export * from "./api/types";
export { getAnalysisSteps } from "./api/mock";

export async function getProjects(): Promise<Project[]> {
  const result = isMock("projects") ? await mockApi.getProjects() : await realApi.getProjects();
  return Array.isArray(result) ? result : [];
}

export async function getProject(id: string): Promise<Project | null> {
  return isMock("projects") ? mockApi.getProject(id) : realApi.getProject(id);
}

export async function createAnalysis(
  repoUrl: string,
  branch?: string,
): Promise<CreateAnalysisResponse> {
  return isMock("analysis")
    ? mockApi.createAnalysis(repoUrl, branch)
    : realApi.createAnalysis(repoUrl, branch);
}

export async function getAnalysisStatus(analysisId: string): Promise<AnalysisStatusResponse> {
  return isMock("analysis")
    ? mockApi.getAnalysisStatus(analysisId)
    : realApi.getAnalysisStatus(analysisId);
}

export async function updateProject(id: string, updates: Partial<Project>): Promise<Project> {
  return isMock("projects")
    ? mockApi.updateProject(id, updates)
    : realApi.updateProject(id, updates);
}

export async function getIssues(projectId: string, category?: IssueCategory): Promise<Issue[]> {
  return isMock("issues")
    ? mockApi.getIssues(projectId, category)
    : realApi.getIssues(projectId, category);
}

export async function getIssue(projectId: string, issueId: string): Promise<Issue | null> {
  return isMock("issues")
    ? mockApi.getIssue(projectId, issueId)
    : realApi.getIssue(projectId, issueId);
}

export async function updateIssueStatus(
  projectId: string,
  issueId: string,
  status: IssueStatus,
): Promise<Issue> {
  return isMock("issues")
    ? mockApi.updateIssueStatus(projectId, issueId, status)
    : realApi.updateIssueStatus(projectId, issueId, status);
}

export async function createPullRequest(
  projectId: string,
  issueId: string,
): Promise<CreatePullRequestResponse> {
  return isMock("issues")
    ? mockApi.createPullRequest(projectId, issueId)
    : realApi.createPullRequest(projectId, issueId);
}

export async function getDeployChecklist(projectId: string): Promise<ChecklistItem[]> {
  return isMock("issues")
    ? mockApi.getDeployChecklist(projectId)
    : realApi.getDeployChecklist(projectId);
}

export async function getArchitecture(projectId: string): Promise<ArchitectureResponse> {
  return isMock("projects")
    ? mockApi.getArchitecture(projectId)
    : realApi.getArchitecture(projectId);
}

export async function getReport(projectId: string): Promise<ProjectReport> {
  return isMock("projects") ? mockApi.getReport(projectId) : realApi.getReport(projectId);
}

export async function rescanProject(projectId: string): Promise<Project> {
  return isMock("projects") ? mockApi.rescanProject(projectId) : realApi.rescanProject(projectId);
}

export async function getSettings(): Promise<UserSettings> {
  return isMock("settings") ? mockApi.getSettings() : realApi.getSettings();
}

export async function saveSettings(settings: UserSettings): Promise<void> {
  return isMock("settings") ? mockApi.saveSettings(settings) : realApi.saveSettings(settings);
}
