import type { Project, IssueSeverity } from "@/types/project";
import type { Issue, IssueCategory, IssueStatus, ChecklistItem } from "@/types/issue";
import type { ProjectReport } from "@/types/report";
import type { UserSettings } from "@/types/settings";
import type {
  ApiClientContract,
  CreateAnalysisResponse,
  AnalysisStatusResponse,
  ArchitectureResponse,
  CreatePullRequestResponse,
  CreateBatchPullRequestResponse,
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

  const rawIssueCounts = (p.issueCounts || p.issue_counts) as Record<string, unknown> | undefined;
  const rawCatScores = (p.categoryScores || p.category_scores) as Record<string, unknown> | undefined;
  const rawSevCounts = (p.severityCounts || p.severity_counts) as Record<string, unknown> | undefined;
  const rawTopIssues = (p.topIssues || p.top_issues) as unknown[] | undefined;
  const rawScanMeta = (p.scanMeta || p.scan_meta) as Record<string, unknown> | undefined;

  const issueCounts = rawIssueCounts
    ? {
        integration: Number(rawIssueCounts.integration) || 0,
        security: Number(rawIssueCounts.security) || 0,
        dependencies: Number(rawIssueCounts.dependencies) || 0,
        deployment: Number(rawIssueCounts.deployment) || 0,
      }
    : {
        integration: 0,
        security: 0,
        dependencies: 0,
        deployment: 0,
      };

  const categoryScores = rawCatScores
    ? {
        integration: Number(rawCatScores.integration) || 0,
        security: Number(rawCatScores.security) || 0,
        dependencies: Number(rawCatScores.dependencies) || 0,
        deployment: Number(rawCatScores.deployment) || 0,
      }
    : {
        integration: 100,
        security: 100,
        dependencies: 100,
        deployment: 100,
      };

  const severityCounts = rawSevCounts
    ? {
        critical: Number(rawSevCounts.critical) || 0,
        high: Number(rawSevCounts.high) || 0,
        medium: Number(rawSevCounts.medium) || 0,
        low: Number(rawSevCounts.low) || 0,
      }
    : {
        critical: 0,
        high: 0,
        medium: 0,
        low: 0,
      };

  const topIssues = Array.isArray(rawTopIssues)
    ? (rawTopIssues as Project["topIssues"])
    : [];

  const scanMeta: Project["scanMeta"] =
    rawScanMeta && typeof rawScanMeta === "object"
      ? {
          branch: typeof rawScanMeta.branch === "string" ? rawScanMeta.branch : "main",
          commitSha: typeof rawScanMeta.commitSha === "string" ? rawScanMeta.commitSha : "HEAD",
          durationSeconds: Number(rawScanMeta.durationSeconds) || 0,
          filesScanned: Number(rawScanMeta.filesScanned) || 0,
          agentsRun: Number(rawScanMeta.agentsRun) || 4,
        }
      : {
          branch: typeof p.source_ref === "string" ? p.source_ref : "main",
          commitSha: typeof p.commit_sha === "string" ? p.commit_sha.slice(0, 7) : "HEAD",
          durationSeconds: 0,
          filesScanned: Number(p.file_count) || 0,
          agentsRun: 4,
        };

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
      const project = normalizeProject(response);

      const totalCount =
        project.issueCounts.integration +
        project.issueCounts.security +
        project.issueCounts.dependencies +
        project.issueCounts.deployment;

      // If backend did not provide non-zero issue counts, sync with /issues
      if (totalCount === 0 && project.status === "completed") {
        try {
          const issues = await http.get<Issue[]>(`/projects/${encodeURIComponent(id)}/issues`);
          if (Array.isArray(issues) && issues.length > 0) {
            const counts = { integration: 0, security: 0, dependencies: 0, deployment: 0 };
            const sevs = { critical: 0, high: 0, medium: 0, low: 0 };
            for (const iss of issues) {
              const cat = String(iss.category);
              if (cat === "api_contract" || cat === "schema" || cat === "integration") {
                counts.integration++;
              } else if (cat === "security") {
                counts.security++;
              } else if (cat === "dependency" || cat === "dependencies") {
                counts.dependencies++;
              } else if (cat === "deployment") {
                counts.deployment++;
              }
              const sev = iss.severity;
              if (sev in sevs) sevs[sev as keyof typeof sevs]++;
            }
            project.issueCounts = counts;
            project.severityCounts = sevs;
            if (project.topIssues.length === 0) {
              project.topIssues = issues.slice(0, 5).map((i) => {
                const catStr = String(i.category);
                const normCat: IssueCategory =
                  catStr === "dependency" ? "dependencies" : (i.category as IssueCategory);
                return {
                  id: i.id,
                  title: i.title,
                  category: normCat,
                  severity: i.severity as IssueSeverity,
                  filePath: i.filePath,
                  shortDescription: i.shortDescription || i.title,
                };
              });
            }
          }
        } catch {
          // ignore issue sync error
        }
      }

      return project;
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        return null;
      }
      throw err;
    }
  },

  async createAnalysis(
    repoUrl: string,
    branch?: string,
    githubToken?: string,
  ): Promise<CreateAnalysisResponse> {
    const payload: Record<string, string> = { repoUrl };
    if (branch && branch.trim()) {
      payload.branch = branch.trim();
    }
    if (githubToken) {
      payload.githubToken = githubToken;
    }
    return http.post<CreateAnalysisResponse>("/analyses", payload);
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

  async createPullRequest(
    projectId: string,
    issueId: string,
    githubToken?: string,
  ): Promise<CreatePullRequestResponse> {
    const headers: Record<string, string> = {};
    if (githubToken) {
      headers["X-GitHub-Token"] = githubToken;
    }
    return http.post<CreatePullRequestResponse>(
      `/projects/${encodeURIComponent(projectId)}/issues/${encodeURIComponent(issueId)}/create-pr`,
      { githubToken },
      { headers },
    );
  },

  async createBatchPullRequest(
    projectId: string,
    issueIds: string[],
    githubToken?: string,
  ): Promise<CreateBatchPullRequestResponse> {
    const headers: Record<string, string> = {};
    if (githubToken) {
      headers["X-GitHub-Token"] = githubToken;
    }
    return http.post<CreateBatchPullRequestResponse>(
      `/projects/${encodeURIComponent(projectId)}/create-batch-pr`,
      { issueIds, githubToken },
      { headers },
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
