import type { Category, Severity } from "@/api/analyses";

/**
 * Presentation for one severity.
 *
 * Colours come from the `--severity-*` tokens so that one severity reads
 * identically in the table, the charts and (in Phase 6) the graph. A chart
 * library needs a real colour string rather than a class, which is what
 * `cssVar` is for.
 */
export interface SeverityStyle {
  label: string;
  /** Tailwind classes for a badge. */
  badge: string;
  /** Tailwind class for a solid swatch. */
  swatch: string;
  /** The CSS custom property, for Recharts and inline styles. */
  cssVar: string;
  /** Points deducted from the health score, per issue. */
  weight: number;
}

export const SEVERITY_STYLES: Record<Severity, SeverityStyle> = {
  critical: {
    label: "Critical",
    badge: "border-severity-critical/30 bg-severity-critical/12 text-severity-critical",
    swatch: "bg-severity-critical",
    cssVar: "var(--severity-critical)",
    weight: 15,
  },
  high: {
    label: "High",
    badge: "border-severity-high/30 bg-severity-high/12 text-severity-high",
    swatch: "bg-severity-high",
    cssVar: "var(--severity-high)",
    weight: 8,
  },
  medium: {
    label: "Medium",
    badge: "border-severity-medium/35 bg-severity-medium/15 text-severity-medium",
    swatch: "bg-severity-medium",
    cssVar: "var(--severity-medium)",
    weight: 3,
  },
  low: {
    label: "Low",
    badge: "border-severity-low/30 bg-severity-low/12 text-severity-low",
    swatch: "bg-severity-low",
    cssVar: "var(--severity-low)",
    weight: 1,
  },
};

export const CATEGORY_LABELS: Record<Category, string> = {
  api_contract: "API contract",
  schema: "Database schema",
  security: "Security",
  dependency: "Dependencies",
};

export const CATEGORY_DESCRIPTIONS: Record<Category, string> = {
  api_contract: "Frontend calls checked against backend routes",
  schema: "ORM models checked against the database schema",
  security: "Secrets, authentication gaps, CORS and debug settings",
  dependency: "Pinned versions checked against published advisories",
};

/**
 * Band a health score for colour.
 *
 * The thresholds are presentational only; the score itself is computed by
 * the backend and must never be recomputed here.
 */
export function scoreTone(score: number): { cssVar: string; label: string } {
  if (score >= 90) return { cssVar: "var(--severity-ok)", label: "Healthy" };
  if (score >= 70) return { cssVar: "var(--severity-medium)", label: "Needs attention" };
  if (score >= 40) return { cssVar: "var(--severity-high)", label: "Poor" };
  return { cssVar: "var(--severity-critical)", label: "Critical" };
}

/** Total issues across the severity tallies, tolerating absent keys. */
export function countIssues(counts: Partial<Record<Severity, number>>): number {
  return Object.values(counts).reduce<number>((total, value) => total + (value ?? 0), 0);
}
