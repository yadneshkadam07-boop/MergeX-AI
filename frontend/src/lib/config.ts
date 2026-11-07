/**
 * MergeX AI Runtime Configuration
 *
 * Centralizes environment variable reads and controls the mock vs. real backend switch.
 * All defaults ensure the application functions in mock mode without any backend running.
 */

export interface MockConfig {
  projects: boolean;
  issues: boolean;
  analysis: boolean;
  settings: boolean;
  auth: boolean;
}

export interface AppConfig {
  apiBaseUrl: string;
  useMock: boolean;
  mockDelayMs: number;
  githubClientId: string;
  mockEndpoints: MockConfig;
}

function parseBool(val: unknown, defaultVal: boolean): boolean {
  if (typeof val !== "string" || val === "") return defaultVal;
  return val.toLowerCase() === "true" || val === "1";
}

function normalizeApiBaseUrl(val: string | undefined): string {
  if (!val || val === "" || val === "/") return "/api";
  let cleaned = val.trim().replace(/\/+$/, "");
  // If base is a domain without /api (e.g. https://mergex-backend.onrender.com)
  if (
    !cleaned.endsWith("/api") &&
    !cleaned.endsWith("/api/v1") &&
    (cleaned.startsWith("http://") || cleaned.startsWith("https://"))
  ) {
    cleaned = `${cleaned}/api`;
  }
  return cleaned;
}

const env = import.meta.env as Record<string, string | undefined>;
// Default to real mode (false) in production and when backend is available;
// can still be explicitly forced to true with VITE_USE_MOCK=true.
const masterUseMock = parseBool(env.VITE_USE_MOCK, false);

export const config: AppConfig = {
  apiBaseUrl: normalizeApiBaseUrl(env.VITE_API_BASE_URL),
  useMock: masterUseMock,
  mockDelayMs: Number(env.VITE_MOCK_DELAY_MS) || 300,
  githubClientId: env.VITE_GITHUB_CLIENT_ID || "Ov23liBpHwSdnjI5koMF",
  mockEndpoints: {
    projects: parseBool(env.VITE_MOCK_PROJECTS, masterUseMock),
    issues: parseBool(env.VITE_MOCK_ISSUES, masterUseMock),
    analysis: parseBool(env.VITE_MOCK_ANALYSIS, masterUseMock),
    settings: parseBool(env.VITE_MOCK_SETTINGS, masterUseMock),
    auth: parseBool(env.VITE_MOCK_AUTH, masterUseMock),
  },
};

/**
 * Returns true if the specific subsystem or the global application is in mock mode.
 */
export function isMock(feature?: keyof MockConfig): boolean {
  if (!feature) return config.useMock;
  return config.mockEndpoints[feature] ?? config.useMock;
}
