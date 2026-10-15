import { API_BASE_URL } from "@/lib/env";

/** An HTTP error returned by the MergeX backend. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

interface BackendErrorBody {
  error?: string;
  detail?: unknown;
}

function messageFrom(body: BackendErrorBody, status: number): string {
  if (typeof body.detail === "string") return body.detail;
  if (typeof body.error === "string") return body.error;
  return `Request failed with status ${status}`;
}

/**
 * Perform a JSON request against the backend.
 *
 * Throws {@link ApiError} on any non-2xx response so TanStack Query can treat
 * it as a failed query rather than valid data.
 */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let body: BackendErrorBody = {};
    try {
      body = (await response.json()) as BackendErrorBody;
    } catch {
      // Non-JSON error body (a proxy or gateway page); fall back to the status.
    }
    throw new ApiError(
      response.status,
      body.error ?? "http_error",
      messageFrom(body, response.status),
    );
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
