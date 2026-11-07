import type { Project, AnalysisStep } from "@/types/project";
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
import { INITIAL_PROJECTS, INITIAL_ANALYSIS_STEPS } from "@/mock/projects";
import { generateIssues, generateChecklist } from "@/mock/issues";
import { generateArchitecture } from "@/mock/architecture";
import { generateReport } from "@/mock/report";
import { generateProjectDetails } from "@/lib/project-generator";
import { config } from "@/lib/config";

const STORAGE_KEY = "mergex_projects_store";
const ISSUES_OVERRIDES_KEY = "mergex_issue_status_overrides";
const SETTINGS_KEY = "mergex_user_settings";

export const DEFAULT_SETTINGS: UserSettings = {
  displayName: "MergeX Developer",
  email: "developer@mergex.ai",
  theme: "system",
  githubConnected: true,
  githubUsername: "mergex-developer",
  checks: {
    integration: true,
    security: true,
    dependencies: true,
    deployment: true,
  },
  alertSeverity: "high",
};

export function delay(min = 200, max = 500): Promise<void> {
  const scaledMin = Math.max(10, Math.floor(min * (config.mockDelayMs / 300)));
  const scaledMax = Math.max(scaledMin, Math.floor(max * (config.mockDelayMs / 300)));
  const ms = Math.floor(Math.random() * (scaledMax - scaledMin + 1)) + scaledMin;
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function getAnalysisSteps(): AnalysisStep[] {
  return INITIAL_ANALYSIS_STEPS.map((step) => ({ ...step }));
}

function readIssueOverrides(): Record<string, IssueStatus> {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(ISSUES_OVERRIDES_KEY);
    return raw ? (JSON.parse(raw) as Record<string, IssueStatus>) : {};
  } catch {
    return {};
  }
}

function writeIssueOverrides(overrides: Record<string, IssueStatus>): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(ISSUES_OVERRIDES_KEY, JSON.stringify(overrides));
  } catch (err) {
    console.error("Failed to persist issue overrides:", err);
  }
}

function readStorage(): Project[] {
  if (typeof window === "undefined") {
    return INITIAL_PROJECTS;
  }
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(INITIAL_PROJECTS));
      return INITIAL_PROJECTS;
    }
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return INITIAL_PROJECTS;

    return (parsed as Project[]).map((p: Project) => {
      let project = p;
      if (!project.categoryScores || !project.severityCounts || !project.scanMeta) {
        const details = generateProjectDetails(project.healthScore || 70);
        project = {
          ...project,
          categoryScores: details.categoryScores,
          severityCounts: details.severityCounts,
          topIssues: details.topIssues,
          scanMeta: details.scanMeta,
        };
      }
      return project;
    });
  } catch (err) {
    console.error("Failed to read projects from storage, resetting to mock:", err);
    return INITIAL_PROJECTS;
  }
}

function writeStorage(projects: Project[]): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(projects));
  } catch (err) {
    console.error("Failed to save projects to storage:", err);
  }
}

export const mockApi: ApiClientContract = {
  async getProjects(): Promise<Project[]> {
    await delay(250, 450);
    return readStorage();
  },

  async getProject(id: string): Promise<Project | null> {
    await delay(150, 300);
    const projects = readStorage();
    const found = projects.find((p) => p.id === id);
    if (!found) return null;

    if (!found.categoryScores || !found.severityCounts || !found.scanMeta) {
      const details = generateProjectDetails(found.healthScore);
      const enriched: Project = {
        ...found,
        categoryScores: details.categoryScores,
        severityCounts: details.severityCounts,
        topIssues: details.topIssues,
        scanMeta: details.scanMeta,
      };
      const updatedList = projects.map((p) => (p.id === id ? enriched : p));
      writeStorage(updatedList);
      return enriched;
    }

    return found;
  },

  async createAnalysis(
    repoUrl: string,
    branch = "main",
    _githubToken?: string,
  ): Promise<CreateAnalysisResponse> {
    await delay(350, 600);

    const cleanUrl = repoUrl.replace(/\/+$/, "");
    const parts = cleanUrl.split("/");
    const repoName = parts[parts.length - 1] || "analyzed-repo";
    const owner = parts[parts.length - 2] || "mergex-developer";

    const id = `prj_${Date.now().toString(36)}`;

    const newProject: Project = {
      id,
      name: repoName,
      owner,
      repoUrl,
      stack: ["React", "TypeScript", "TailwindCSS"],
      healthScore: 0,
      status: "analyzing",
      issueCounts: {
        integration: 0,
        security: 0,
        dependencies: 0,
        deployment: 0,
      },
      lastScannedAt: new Date().toISOString(),
      categoryScores: {
        integration: 0,
        security: 0,
        dependencies: 0,
        deployment: 0,
      },
      severityCounts: {
        critical: 0,
        high: 0,
        medium: 0,
        low: 0,
      },
      topIssues: [],
      scanMeta: {
        branch,
        commitSha: Math.random().toString(16).substring(2, 9),
        durationSeconds: 0,
        filesScanned: 0,
        agentsRun: 6,
      },
    };

    const current = readStorage();
    writeStorage([newProject, ...current]);

    return {
      ...newProject,
      analysisId: `ana_${id}`,
      projectId: id,
      steps: INITIAL_ANALYSIS_STEPS.map((s) => ({ ...s })),
    };
  },

  async getAnalysisStatus(analysisId: string): Promise<AnalysisStatusResponse> {
    await delay(100, 200);
    const projectId = analysisId.replace("ana_", "");
    const project = await this.getProject(projectId);

    return {
      id: analysisId,
      projectId,
      status: project?.status || "completed",
      progressPercent: project?.status === "completed" ? 100 : 50,
      currentStepIndex: 8,
      ...(project ? { project } : {}),
    };
  },

  async updateProject(id: string, updates: Partial<Project>): Promise<Project> {
    await delay(100, 200);
    const current = readStorage();
    const idx = current.findIndex((p) => p.id === id);
    const existing = current[idx];
    if (idx === -1 || !existing) {
      throw new Error(`Project ${id} not found.`);
    }

    const updated: Project = {
      ...existing,
      ...updates,
      issueCounts: {
        ...existing.issueCounts,
        ...(updates.issueCounts || {}),
      },
      categoryScores:
        updates.categoryScores && existing.categoryScores
          ? { ...existing.categoryScores, ...updates.categoryScores }
          : existing.categoryScores,
      severityCounts:
        updates.severityCounts && existing.severityCounts
          ? { ...existing.severityCounts, ...updates.severityCounts }
          : existing.severityCounts,
      topIssues: updates.topIssues ?? existing.topIssues,
      scanMeta:
        updates.scanMeta && existing.scanMeta
          ? { ...existing.scanMeta, ...updates.scanMeta }
          : existing.scanMeta,
    };

    current[idx] = updated;
    writeStorage(current);
    return updated;
  },

  async getIssues(projectId: string, category?: IssueCategory): Promise<Issue[]> {
    await delay(200, 400);
    const overrides = readIssueOverrides();
    const project = await this.getProject(projectId);
    if (!project) return [];

    const issues = generateIssues(project);

    const applied = issues.map((issue) => {
      const overrideStatus = overrides[issue.id];
      if (overrideStatus) {
        return { ...issue, status: overrideStatus };
      }
      return issue;
    });

    if (category) {
      return applied.filter((i) => i.category === category);
    }

    return applied;
  },

  async getIssue(projectId: string, issueId: string): Promise<Issue | null> {
    await delay(150, 300);
    const issues = await this.getIssues(projectId);
    return issues.find((i) => i.id === issueId) || null;
  },

  async updateIssueStatus(projectId: string, issueId: string, status: IssueStatus): Promise<Issue> {
    await delay(200, 400);
    const overrides = readIssueOverrides();
    overrides[issueId] = status;
    writeIssueOverrides(overrides);

    const issue = await this.getIssue(projectId, issueId);
    if (!issue) {
      throw new Error(`Issue ${issueId} not found in project ${projectId}`);
    }

    return { ...issue, status };
  },

  async createPullRequest(projectId: string, issueId: string): Promise<CreatePullRequestResponse> {
    await delay(600, 1000);
    const overrides = readIssueOverrides();
    overrides[issueId] = "resolved";
    writeIssueOverrides(overrides);

    const project = await this.getProject(projectId);
    const repoUrl = project?.repoUrl || "https://github.com/yadneshkadam07-boop/MergeX-AI";
    const prNum = Math.floor(Math.random() * 40) + 10;
    return {
      prUrl: `${repoUrl}/pull/${prNum}`,
      prNumber: prNum,
      branch: `mergex/fix-issue-${issueId.slice(0, 6)}`,
      status: "simulated",
      note: "Automated PR created successfully.",
    };
  },

  async getDeployChecklist(projectId: string): Promise<ChecklistItem[]> {
    await delay(200, 350);
    const project = await this.getProject(projectId);
    if (!project) return [];
    return generateChecklist(project);
  },

  async getArchitecture(projectId: string): Promise<ArchitectureResponse> {
    await delay(250, 450);
    const project = await this.getProject(projectId);
    if (!project) {
      return { nodes: [], edges: [] };
    }
    const issues = await this.getIssues(projectId);
    return generateArchitecture(project, issues);
  },

  async getReport(projectId: string): Promise<ProjectReport> {
    await delay(300, 500);
    const project = await this.getProject(projectId);
    if (!project) {
      throw new Error(`Project ${projectId} not found.`);
    }
    const issues = await this.getIssues(projectId);
    const architecture = await this.getArchitecture(projectId);
    return generateReport(project, issues, architecture);
  },

  async rescanProject(projectId: string): Promise<Project> {
    await delay(300, 600);
    const project = await this.getProject(projectId);
    if (!project) throw new Error(`Project ${projectId} not found.`);

    const randomizedScore = Math.min(
      100,
      Math.max(30, project.healthScore + (Math.floor(Math.random() * 9) - 4)),
    );
    const details = generateProjectDetails(randomizedScore);

    return this.updateProject(projectId, {
      healthScore: randomizedScore,
      lastScannedAt: new Date().toISOString(),
      categoryScores: details.categoryScores,
      severityCounts: details.severityCounts,
      topIssues: details.topIssues,
      scanMeta: {
        ...(project.scanMeta || details.scanMeta),
        durationSeconds: Math.floor(Math.random() * 20) + 18,
        commitSha: Math.random().toString(16).substring(2, 9),
      },
    });
  },

  async getSettings(): Promise<UserSettings> {
    await delay(200, 400);
    if (typeof window === "undefined") return DEFAULT_SETTINGS;
    try {
      const raw = localStorage.getItem(SETTINGS_KEY);
      return raw ? (JSON.parse(raw) as UserSettings) : DEFAULT_SETTINGS;
    } catch {
      return DEFAULT_SETTINGS;
    }
  },

  async saveSettings(settings: UserSettings): Promise<void> {
    await delay(200, 400);
    if (typeof window === "undefined") return;
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    } catch (err) {
      console.error("Failed to save settings:", err);
    }
  },
};
