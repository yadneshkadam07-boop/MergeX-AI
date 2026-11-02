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

const env = import.meta.env as Record<string, string | undefined>;
const masterUseMock = parseBool(env.VITE_USE_MOCK, true);

export const config: AppConfig = {
  apiBaseUrl: env.VITE_API_BASE_URL || "/api",
  useMock: masterUseMock,
  mockDelayMs: Number(env.VITE_MOCK_DELAY_MS) || 300,
  githubClientId: env.VITE_GITHUB_CLIENT_ID || "",
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
