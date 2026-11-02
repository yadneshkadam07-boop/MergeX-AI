import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { realApi, normalizeProject } from "./real";
import { ApiError } from "@/lib/http";

describe("realApi.getProjects", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("unwraps a paginated Page envelope object response into a Project array", async () => {
    const mockPageResponse = {
      items: [
        {
          id: "p1-uuid",
          name: "mergex-test-project",
          source_type: "github",
          source_url: "https://github.com/org/mergex-test-project",
          source_ref: "main",
          detected_stack: {
            frontend: ["React"],
            backend: ["FastAPI"],
          },
          commit_sha: "abcdef123456",
          file_count: 42,
          size_bytes: 10240,
          healthScore: 88,
          created_at: "2026-11-01T12:00:00Z",
          updated_at: "2026-11-01T12:00:00Z",
        },
      ],
      total: 1,
      limit: 20,
      offset: 0,
    };

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        statusText: "OK",
        headers: new Headers({ "content-type": "application/json" }),
        json: () => Promise.resolve(mockPageResponse),
      }),
    );

    const projects = await realApi.getProjects();
    expect(Array.isArray(projects)).toBe(true);
    expect(projects).toHaveLength(1);
    const first = projects[0]!;
    expect(first.id).toBe("p1-uuid");
    expect(first.name).toBe("mergex-test-project");
    expect(first.owner).toBe("org");
    expect(first.stack).toEqual(["React", "FastAPI"]);
    expect(first.issueCounts).toBeDefined();
    expect(typeof first.issueCounts.integration).toBe("number");
  });

  it("handles a bare array response directly", async () => {
    const mockArrayResponse = [
      {
        id: "p2-uuid",
        name: "direct-array-project",
        stack: ["React", "FastAPI"],
        healthScore: 90,
      },
    ];

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        statusText: "OK",
        headers: new Headers({ "content-type": "application/json" }),
        json: () => Promise.resolve(mockArrayResponse),
      }),
    );

    const projects = await realApi.getProjects();
    expect(Array.isArray(projects)).toBe(true);
    expect(projects).toHaveLength(1);
    const first = projects[0]!;
    expect(first.id).toBe("p2-uuid");
    expect(first.stack).toEqual(["React", "FastAPI"]);
  });

  it("safely handles an unexpected non-array object response without throwing", async () => {
    // If backend returns an unexpected object (e.g. without items array)
    const mockUnexpectedObject = {
      status: "ok",
      unexpected: "data",
    };

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        statusText: "OK",
        headers: new Headers({ "content-type": "application/json" }),
        json: () => Promise.resolve(mockUnexpectedObject),
      }),
    );

    const projects = await realApi.getProjects();
    expect(Array.isArray(projects)).toBe(true);
    expect(projects).toEqual([]);
  });

  it("propagates ApiError on error response (e.g. 500 or 401)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        headers: new Headers({ "content-type": "application/json" }),
        text: () => Promise.resolve(JSON.stringify({ detail: "Database connection failed" })),
      }),
    );

    await expect(realApi.getProjects()).rejects.toThrow(ApiError);
  });
});

describe("normalizeProject helper", () => {
  it("normalizes an empty or null input into a safe fallback Project", () => {
    const project = normalizeProject(null);
    expect(project).toBeDefined();
    expect(project.id).toBe("unknown");
    expect(Array.isArray(project.stack)).toBe(true);
    expect(typeof project.issueCounts.integration).toBe("number");
    expect(typeof project.categoryScores.security).toBe("number");
  });

  it("extracts github owner from source_url if owner is missing", () => {
    const project = normalizeProject({
      id: "abc",
      name: "repo",
      source_url: "https://github.com/my-org/repo",
    });
    expect(project.owner).toBe("my-org");
  });
});
