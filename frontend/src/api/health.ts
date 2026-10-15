import { apiFetch } from "@/api/client";

export interface Liveness {
  status: "ok";
  app: string;
  version: string;
  environment: string;
  uptime_seconds: number;
}

export type ComponentStatus = "ok" | "degraded" | "unavailable" | "not_configured";

export interface Readiness {
  status: "ok" | "degraded" | "unavailable";
  components: Record<string, { status: ComponentStatus; detail: string | null }>;
}

export const healthKeys = {
  liveness: ["health", "liveness"] as const,
  readiness: ["health", "readiness"] as const,
};

export function getLiveness(): Promise<Liveness> {
  return apiFetch<Liveness>("/health");
}

export function getReadiness(): Promise<Readiness> {
  return apiFetch<Readiness>("/health/ready");
}
