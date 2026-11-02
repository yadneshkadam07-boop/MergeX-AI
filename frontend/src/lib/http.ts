/**
 * MergeX AI Typed HTTP Client
 *
 * Lightweight, zero-dependency fetch wrapper designed for the FastAPI backend.
 * Provides timeout management, Bearer token injection, structured ApiError,
 * and 401 interceptor handling.
 */

import { config } from "./config";

export interface RequestOptions extends Omit<RequestInit, "body"> {
  params?: Record<string, string | number | boolean | undefined>;
  timeoutMs?: number;
  skipAuth?: boolean;
}

export class ApiError<T = unknown> extends Error {
  public readonly status: number;
  public readonly statusText: string;
  public readonly data?: T | undefined;
  public readonly url: string;

  constructor(status: number, statusText: string, url: string, data?: T, message?: string) {
    super(message || `HTTP ${status}: ${statusText}`);
    this.name = "ApiError";
    this.status = status;
    this.statusText = statusText;
    this.url = url;
    this.data = data;
  }
}

const AUTH_TOKEN_KEY = "mergex_auth_token";

export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

export function setAuthToken(token: string | null): void {
  if (typeof window === "undefined") return;
  if (token) {
    localStorage.setItem(AUTH_TOKEN_KEY, token);
  } else {
    localStorage.removeItem(AUTH_TOKEN_KEY);
  }
}

function createAbortSignal(
  timeoutMs: number,
  externalSignal?: AbortSignal | null,
): { signal: AbortSignal; cleanup: () => void } {
  const controller = new AbortController();
  const timer = setTimeout(() => {
    controller.abort(new Error(`Request timed out after ${timeoutMs}ms`));
  }, timeoutMs);

  if (externalSignal) {
    externalSignal.addEventListener("abort", () => {
      clearTimeout(timer);
      controller.abort(externalSignal.reason);
    });
  }

  return {
    signal: controller.signal,
    cleanup: () => clearTimeout(timer),
  };
}

function buildUrl(
  path: string,
  params?: Record<string, string | number | boolean | undefined>,
): string {
  // Normalize base and path
  const base = config.apiBaseUrl.replace(/\/+$/, "");
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const fullUrl =
    path.startsWith("http://") || path.startsWith("https://") ? path : `${base}${normalizedPath}`;

  if (!params) return fullUrl;

  const url = new URL(
    fullUrl,
    typeof window !== "undefined" ? window.location.origin : "http://localhost",
  );
  for (const [key, val] of Object.entries(params)) {
    if (val !== undefined) {
      url.searchParams.set(key, String(val));
    }
  }
  return url.toString();
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  const {
    params,
    timeoutMs = 15000,
    skipAuth = false,
    signal: externalSignal,
    headers: customHeaders,
    ...rest
  } = options;

  const url = buildUrl(path, params);
  const { signal, cleanup } = createAbortSignal(timeoutMs, externalSignal);

  const headers = new Headers(customHeaders);

  if (!skipAuth) {
    const token = getAuthToken();
    if (token && !headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }

  if (body !== undefined && !headers.has("Content-Type") && !(body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  headers.set("Accept", "application/json");

  try {
    const response = await fetch(url, {
      ...rest,
      method,
      headers,
      signal,
      body: body !== undefined ? (body instanceof FormData ? body : JSON.stringify(body)) : null,
    });

    cleanup();

    if (response.status === 401) {
      setAuthToken(null);
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("mergex:unauthorized"));
      }
    }

    if (!response.ok) {
      let errorData: unknown;
      let errorMessage = `HTTP error ${response.status}: ${response.statusText}`;

      try {
        const text = await response.text();
        if (text) {
          const parsed = JSON.parse(text) as Record<string, unknown>;
          errorData = parsed;
          if (typeof parsed.detail === "string") {
            errorMessage = parsed.detail;
          } else if (
            parsed.error &&
            typeof parsed.error === "object" &&
            "message" in parsed.error
          ) {
            errorMessage = String(parsed.error.message);
          }
        }
      } catch {
        // Fallback to default message if response is not JSON
      }

      throw new ApiError(response.status, response.statusText, url, errorData, errorMessage);
    }

    if (response.status === 204) {
      return undefined as unknown as T;
    }

    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      return (await response.json()) as T;
    }

    return (await response.text()) as unknown as T;
  } catch (err) {
    cleanup();
    if (err instanceof ApiError) throw err;
    if (err instanceof Error && err.name === "AbortError") {
      throw new ApiError(
        408,
        "Request Timeout",
        url,
        undefined,
        `Request timed out after ${timeoutMs}ms`,
      );
    }
    throw new ApiError(
      0,
      "Network Error",
      url,
      undefined,
      err instanceof Error ? err.message : "Network request failed",
    );
  }
}

export const http = {
  get<T>(path: string, options?: RequestOptions): Promise<T> {
    return request<T>("GET", path, undefined, options);
  },
  post<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
    return request<T>("POST", path, body, options);
  },
  put<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
    return request<T>("PUT", path, body, options);
  },
  patch<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
    return request<T>("PATCH", path, body, options);
  },
  delete<T>(path: string, options?: RequestOptions): Promise<T> {
    return request<T>("DELETE", path, undefined, options);
  },
};
