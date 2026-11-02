import type { Category } from "@/api/analyses";
import { API_BASE_URL } from "@/lib/env";
import { getAuthToken } from "@/lib/http";

/**
 * The pipeline stages the backend streams, in the order they occur.
 *
 * `EventSource` dispatches by event name and has no wildcard, so every name
 * the server can send must be listed here or those events are silently
 * dropped — a stepper that never advances with no error anywhere.
 */
export const STAGES = [
  "queued",
  "importing",
  "stack",
  "api",
  "schema",
  "security",
  "synthesis",
  "complete",
] as const;
export type Stage = (typeof STAGES)[number];

export type EventStatus = "started" | "completed" | "failed" | "skipped";

export interface AnalysisEvent {
  id: number;
  analysis_id: string;
  stage: Stage;
  status: EventStatus;
  message: string;
  created_at: number;
  /** Findings produced by this stage, when the stage produces findings. */
  finding_count?: number;
  /** Running total across the run so far. */
  total_findings?: number;
  data?: Record<string, unknown>;
}

/** The stages shown in the stepper. `queued` and `complete` frame the run. */
export const PIPELINE_STAGES: Stage[] = [
  "importing",
  "stack",
  "api",
  "schema",
  "security",
  "synthesis",
];

export const STAGE_LABELS: Record<Stage, string> = {
  queued: "Queued",
  importing: "Importing repository",
  stack: "Detecting stack",
  api: "API contract",
  schema: "Database schema",
  security: "Security & dependencies",
  synthesis: "Scoring & explanations",
  complete: "Complete",
};

/** Which report category a stage's findings land in, where there is one. */
export const STAGE_CATEGORY: Partial<Record<Stage, Category>> = {
  api: "api_contract",
  schema: "schema",
  security: "security",
};

/**
 * URL for one analysis's event stream.
 *
 * `lastEventId` is passed as a query parameter rather than the standard
 * `Last-Event-ID` header because `EventSource` cannot set headers. The
 * backend accepts either. Authentication token is also passed via query param
 * since EventSource does not support custom Authorization headers.
 */
export function eventStreamUrl(analysisId: string, lastEventId = 0): string {
  const base = `${API_BASE_URL}/api/v1/analyses/${analysisId}/events`;
  const params = new URLSearchParams();
  if (lastEventId > 0) {
    params.set("last_event_id", String(lastEventId));
  }
  const token = getAuthToken();
  if (token) {
    params.set("token", token);
  }
  const queryString = params.toString();
  return queryString ? `${base}?${queryString}` : base;
}

export function isTerminal(event: AnalysisEvent): boolean {
  return event.stage === "complete";
}
