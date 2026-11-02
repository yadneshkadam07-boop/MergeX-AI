export type ArchNodeKind = "frontend" | "api" | "database" | "auth" | "external" | "worker";

export interface ArchNode {
  id: string;
  label: string;
  kind: ArchNodeKind;
  tech: string;
  description: string;
  issueIds: string[];
  position?: { x: number; y: number };
}

export type ArchEdgeStatus = "ok" | "warning" | "broken";

export interface ArchEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  status: ArchEdgeStatus;
  issueIds?: string[];
}
