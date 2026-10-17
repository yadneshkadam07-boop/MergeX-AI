import { apiFetch } from "@/api/client";
import { API_BASE_URL } from "@/lib/env";

export interface DetectedStack {
  frontend?: string[];
  backend?: string[];
  database?: string[];
  build?: string[];
  package_managers?: string[];
  is_monorepo?: boolean;
}

export interface Project {
  id: string;
  name: string;
  source_type: "github" | "zip";
  source_url: string | null;
  source_ref: string | null;
  upload_filename: string | null;
  detected_stack: DetectedStack | null;
  commit_sha: string | null;
  file_count: number | null;
  size_bytes: number | null;
  last_imported_at: string | null;
  import_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface ImportSummary {
  file_count: number;
  size_bytes: number;
  commit_sha: string | null;
  duration_ms: number;
  skipped_paths: number;
}

export interface ProjectCreateResponse {
  project: Project;
  import_summary: ImportSummary;
}

export const projectKeys = {
  all: ["projects"] as const,
  detail: (id: string) => ["projects", id] as const,
};

export function importGitHub(
  sourceUrl: string,
  sourceRef?: string,
): Promise<ProjectCreateResponse> {
  return apiFetch<ProjectCreateResponse>("/api/v1/projects", {
    method: "POST",
    body: JSON.stringify({
      source_url: sourceUrl,
      ...(sourceRef ? { source_ref: sourceRef } : {}),
    }),
  });
}

/**
 * Upload a ZIP.
 *
 * Not routed through `apiFetch`: a `FormData` body must keep the boundary
 * `Content-Type` the browser generates, and `apiFetch` sets JSON headers.
 */
export async function uploadZip(file: File): Promise<ProjectCreateResponse> {
  const body = new FormData();
  body.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/v1/projects/upload`, {
    method: "POST",
    body,
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    let detail = `Upload failed with status ${response.status}`;
    try {
      const parsed = (await response.json()) as { detail?: unknown };
      if (typeof parsed.detail === "string") detail = parsed.detail;
    } catch {
      // Non-JSON error body; keep the status-based message.
    }
    throw new Error(detail);
  }

  return (await response.json()) as ProjectCreateResponse;
}

/** Import the fixture bundled with the backend, for demoing with no repo. */
export function importDemo(): Promise<ProjectCreateResponse> {
  return apiFetch<ProjectCreateResponse>("/api/v1/projects/demo", { method: "POST" });
}
