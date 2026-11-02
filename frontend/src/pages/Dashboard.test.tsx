import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { Dashboard } from "./Dashboard";
import * as api from "@/lib/api";
import type { Project } from "@/types/project";

describe("Dashboard Page", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("handles an unexpected object response gracefully without crashing on projects.filter", async () => {
    // Simulate API returning an object instead of an array (e.g. { error: "..." } or un-unwrapped envelope)
    vi.spyOn(api, "getProjects").mockResolvedValue({ items: [] } as unknown as Project[]);

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    // Should not crash and should show empty state
    await waitFor(() => {
      expect(screen.getByText("No projects analyzed yet")).toBeInTheDocument();
    });
  });

  it("handles an error response gracefully without crashing on projects.filter", async () => {
    vi.spyOn(api, "getProjects").mockRejectedValue(new Error("HTTP 401: Unauthorized"));

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    // Should display error UI and not throw 'projects.filter is not a function'
    await waitFor(() => {
      expect(screen.getByText("Failed to load projects")).toBeInTheDocument();
      expect(screen.getByText("HTTP 401: Unauthorized")).toBeInTheDocument();
    });
  });

  it("renders projects successfully when receiving a valid array", async () => {
    const mockProjects: Project[] = [
      {
        id: "proj-1",
        name: "Test Repository",
        owner: "testowner",
        repoUrl: "https://github.com/testowner/test",
        stack: ["React", "FastAPI"],
        healthScore: 85,
        status: "completed",
        issueCounts: {
          integration: 2,
          security: 1,
          dependencies: 0,
          deployment: 0,
        },
        lastScannedAt: new Date().toISOString(),
        categoryScores: {
          integration: 90,
          security: 80,
          dependencies: 85,
          deployment: 85,
        },
        severityCounts: {
          critical: 0,
          high: 1,
          medium: 2,
          low: 0,
        },
        topIssues: [],
        scanMeta: {
          branch: "main",
          commitSha: "1234567",
          durationSeconds: 15,
          filesScanned: 50,
          agentsRun: 4,
        },
      },
    ];

    vi.spyOn(api, "getProjects").mockResolvedValue(mockProjects);

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("Test Repository")).toBeInTheDocument();
      expect(screen.getByText("Total Projects")).toBeInTheDocument();
    });
  });
});
