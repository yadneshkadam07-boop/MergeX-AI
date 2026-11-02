import type { Project } from "@/types/project";
import type { Issue, IssueCategory, IssueStatus, ChecklistItem } from "@/types/issue";
import type { ProjectReport } from "@/types/report";
import type { UserSettings } from "@/types/settings";
import type {
  ApiClientContract,
  CreateAnalysisResponse,
  AnalysisStatusResponse,
  ArchitectureResponse,
} from "./types";
import { http, ApiError } from "@/lib/http";

export const realApi: ApiClientContract = {
  async getProjects(): Promise<Project[]> {
    return http.get<Project[]>("/projects");
  },

  async getProject(id: string): Promise<Project | null> {
    try {
      return await http.get<Project>(`/projects/${encodeURIComponent(id)}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        return null;
      }
      throw err;
    }
  },

  async createAnalysis(repoUrl: string, branch = "main"): Promise<CreateAnalysisResponse> {
    return http.post<CreateAnalysisResponse>("/analyses", {
      repoUrl,
      branch,
    });
  },

  async getAnalysisStatus(analysisId: string): Promise<AnalysisStatusResponse> {
    return http.get<AnalysisStatusResponse>(`/analyses/${encodeURIComponent(analysisId)}/status`);
  },

  async updateProject(id: string, updates: Partial<Project>): Promise<Project> {
    return http.patch<Project>(`/projects/${encodeURIComponent(id)}`, updates);
  },

  async getIssues(projectId: string, category?: IssueCategory): Promise<Issue[]> {
    const path = category
      ? `/projects/${encodeURIComponent(projectId)}/issues?category=${encodeURIComponent(category)}`
      : `/projects/${encodeURIComponent(projectId)}/issues`;
    return http.get<Issue[]>(path);
  },

  async getIssue(projectId: string, issueId: string): Promise<Issue | null> {
    try {
      return await http.get<Issue>(
        `/projects/${encodeURIComponent(projectId)}/issues/${encodeURIComponent(issueId)}`,
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        return null;
      }
      throw err;
    }
  },

  async updateIssueStatus(projectId: string, issueId: string, status: IssueStatus): Promise<Issue> {
    return http.patch<Issue>(
      `/projects/${encodeURIComponent(projectId)}/issues/${encodeURIComponent(issueId)}`,
      { status },
    );
  },

  async getDeployChecklist(projectId: string): Promise<ChecklistItem[]> {
    return http.get<ChecklistItem[]>(`/projects/${encodeURIComponent(projectId)}/deploy-checklist`);
  },

  async getArchitecture(projectId: string): Promise<ArchitectureResponse> {
    return http.get<ArchitectureResponse>(
      `/projects/${encodeURIComponent(projectId)}/architecture`,
    );
  },

  async getReport(projectId: string): Promise<ProjectReport> {
    return http.get<ProjectReport>(`/projects/${encodeURIComponent(projectId)}/report`);
  },

  async rescanProject(projectId: string): Promise<Project> {
    return http.post<Project>(`/projects/${encodeURIComponent(projectId)}/rescan`);
  },

  async getSettings(): Promise<UserSettings> {
    return http.get<UserSettings>("/settings");
  },

  async saveSettings(settings: UserSettings): Promise<void> {
    await http.put<void>("/settings", settings);
  },
};
