import type { Project } from "@/types/project";
import type { Issue, IssueCategory, IssueStatus, ChecklistItem } from "@/types/issue";
import type { ProjectReport } from "@/types/report";
import type { UserSettings } from "@/types/settings";
import type {
  ApiClientContract,
  CreateAnalysisResponse,
  AnalysisStatusResponse,
  ArchitectureResponse,
  CreatePullRequestResponse,
} from "./types";
import { http, ApiError } from "@/lib/http";
import { stackBadgesFrom } from "@/lib/stack";
import { generateProjectDetails } from "@/lib/project-generator";

export function normalizeProject(raw: unknown): Project {
  if (!raw || typeof raw !== "object") {
    const details = generateProjectDetails(70);
    return {
      id: "unknown",
      name: "Unnamed Project",
      owner: "mergex-developer",
      repoUrl: "",
      stack: [],
      healthScore: 70,
      status: "completed",
      issueCounts: details.issueCounts,
      lastScannedAt: new Date().toISOString(),
      categoryScores: details.categoryScores,
      severityCounts: details.severityCounts,
      topIssues: details.topIssues,
      scanMeta: details.scanMeta,
    };
  }

  const p = raw as Record<string, unknown>;
  const id = typeof p.id === "string" ? p.id : typeof p.id === "number" ? String(p.id) : "unknown";
  const name = typeof p.name === "string" ? p.name : "Unnamed Project";

  let owner = typeof p.owner === "string" ? p.owner : "";
  if (!owner && typeof p.source_url === "string") {
    const match = p.source_url.match(/github\.com\/([^/]+)/);
    if (match && match[1]) owner = match[1];
  }
  if (!owner) owner = "mergex-developer";

  const repoUrl =
    typeof p.repoUrl === "string"
      ? p.repoUrl
      : typeof p.source_url === "string"
        ? p.source_url
        : "";

  let stack: string[] = [];
  if (Array.isArray(p.stack)) {
    stack = p.stack.filter((s): s is string => typeof s === "string");
  } else if (p.detected_stack && typeof p.detected_stack === "object") {
    stack = stackBadgesFrom(p.detected_stack as Record<string, unknown>);
  }

  const healthScore =
    typeof p.healthScore === "number"
      ? p.healthScore
      : typeof p.health_score === "number"
        ? p.health_score
        : 70;

  let status: Project["status"] = "completed";
  if (p.status === "analyzing" || p.status === "completed" || p.status === "failed") {
    status = p.status;
  } else if (p.import_error) {
    status = "failed";
  }

  const lastScannedAt =
    typeof p.lastScannedAt === "string"
      ? p.lastScannedAt
      : typeof p.last_imported_at === "string"
        ? p.last_imported_at
        : typeof p.updated_at === "string"
          ? p.updated_at
          : typeof p.created_at === "string"
            ? p.created_at
            : new Date().toISOString();

  const rawIssueCounts = p.issueCounts as Record<string, unknown> | undefined;
  const rawCatScores = p.categoryScores as Record<string, unknown> | undefined;
  const rawSevCounts = p.severityCounts as Record<string, unknown> | undefined;

  const needsDetails = !rawIssueCounts || !rawCatScores || !rawSevCounts || !p.scanMeta;

  const details = needsDetails ? generateProjectDetails(healthScore) : null;

  const issueCounts = rawIssueCounts
    ? {
        integration: Number(rawIssueCounts.integration) || 0,
        security: Number(rawIssueCounts.security) || 0,
        dependencies: Number(rawIssueCounts.dependencies) || 0,
        deployment: Number(rawIssueCounts.deployment) || 0,
      }
    : details!.issueCounts;

  const categoryScores = rawCatScores
    ? {
        integration: Number(rawCatScores.integration) || 0,
        security: Number(rawCatScores.security) || 0,
        dependencies: Number(rawCatScores.dependencies) || 0,
        deployment: Number(rawCatScores.deployment) || 0,
      }
    : details!.categoryScores;

  const severityCounts = rawSevCounts
    ? {
        critical: Number(rawSevCounts.critical) || 0,
        high: Number(rawSevCounts.high) || 0,
        medium: Number(rawSevCounts.medium) || 0,
        low: Number(rawSevCounts.low) || 0,
      }
    : details!.severityCounts;

  const topIssues = Array.isArray(p.topIssues)
    ? (p.topIssues as Project["topIssues"])
    : (details?.topIssues ?? []);

  const scanMeta =
    p.scanMeta && typeof p.scanMeta === "object"
      ? (p.scanMeta as Project["scanMeta"])
      : (details?.scanMeta ?? {
          branch: typeof p.source_ref === "string" ? p.source_ref : "main",
          commitSha: typeof p.commit_sha === "string" ? p.commit_sha.slice(0, 7) : "HEAD",
          durationSeconds: 0,
          filesScanned: Number(p.file_count) || 0,
          agentsRun: 4,
        });

  return {
    id,
    name,
    owner,
    repoUrl,
    stack,
    healthScore,
    status,
    issueCounts,
    lastScannedAt,
    categoryScores,
    severityCounts,
    topIssues,
    scanMeta,
  };
}

export const realApi: ApiClientContract = {
  async getProjects(): Promise<Project[]> {
    const response = await http.get<unknown>("/projects");
    let items: unknown[];
    if (Array.isArray(response)) {
      items = response;
    } else if (
      response &&
      typeof response === "object" &&
      "items" in response &&
      Array.isArray((response as { items: unknown[] }).items)
    ) {
      items = (response as { items: unknown[] }).items;
    } else {
      return [];
    }
    return items.map(normalizeProject);
  },

  async getProject(id: string): Promise<Project | null> {
    try {
      const response = await http.get<unknown>(`/projects/${encodeURIComponent(id)}`);
      if (!response || typeof response !== "object") return null;
      return normalizeProject(response);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        return null;
      }
      throw err;
    }
  },

  async createAnalysis(
    repoUrl: string,
    branch = "main",
    githubToken?: string,
  ): Promise<CreateAnalysisResponse> {
    return http.post<CreateAnalysisResponse>("/analyses", {
      repoUrl,
      branch,
      ...(githubToken ? { githubToken } : {}),
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

  async createPullRequest(projectId: string, issueId: string): Promise<CreatePullRequestResponse> {
    return http.post<CreatePullRequestResponse>(
      `/projects/${encodeURIComponent(projectId)}/issues/${encodeURIComponent(issueId)}/create-pr`,
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
