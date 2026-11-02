import { cn } from "@/lib/utils";

interface HealthScoreBadgeProps {
  score: number;
  className?: string;
  showLabel?: boolean;
}

/**
 * HealthScoreBadge displays a 0-100 score color-coded using design tokens:
 * - 80+: Good (success / evergreen)
 * - 50-79: Warning (sev-medium / warning)
 * - <50: Danger (sev-critical / danger)
 */
export function HealthScoreBadge({ score, className, showLabel = false }: HealthScoreBadgeProps) {
  let colorClasses: string;
  let label: string;

  if (score >= 80) {
    colorClasses = "bg-success/12 text-success border-success";
    label = "Healthy";
  } else if (score >= 50) {
    colorClasses = "bg-sev-medium/12 text-sev-medium border-sev-medium";
    label = "Needs Attention";
  } else {
    colorClasses = "bg-sev-critical/12 text-sev-critical border-sev-critical";
    label = "Critical";
  }

  return (
    <div
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-semibold select-none",
        colorClasses,
        className,
      )}
      title={`Health Score: ${score}/100 (${label})`}
    >
      <span className="font-mono font-bold">{score}</span>
      <span className="text-[10px] font-normal opacity-75">/100</span>
      {showLabel && <span className="ml-1 text-[11px] font-medium">· {label}</span>}
    </div>
  );
}
