import type { SeverityCounts } from "@/types/project";
import { cn } from "@/lib/utils";

interface SeverityBarProps {
  counts: SeverityCounts;
  className?: string;
}

export function SeverityBar({ counts, className }: SeverityBarProps) {
  const total = counts.critical + counts.high + counts.medium + counts.low;

  // Proportions
  const pct = (val: number) => (total > 0 ? (val / total) * 100 : 0);

  // Short dynamic headline summary
  const getSummarySentence = () => {
    if (total === 0) {
      return "All security, integration, and deployment checks passed with zero flagged issues.";
    }

    const parts: string[] = [];
    if (counts.critical > 0) {
      parts.push(`${counts.critical} critical`);
    }
    if (counts.high > 0) {
      parts.push(`${counts.high} high`);
    }

    if (parts.length > 0) {
      return `${parts.join(" and ")} issues need attention before deployment.`;
    }

    return `${counts.medium} medium and ${counts.low} low priority issues detected across code.`;
  };

  return (
    <div className={cn("space-y-3", className)}>
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-foreground text-sm font-semibold">{getSummarySentence()}</p>
        <span className="text-muted-foreground shrink-0 font-mono text-xs">
          {total} total issues
        </span>
      </div>

      {/* Proportional Stacked Bar */}
      <div className="bg-muted flex h-3 w-full overflow-hidden rounded-full">
        {total === 0 ? (
          <div className="bg-success h-full w-full" title="Zero issues" />
        ) : (
          <>
            {counts.critical > 0 && (
              <div
                style={{ width: `${pct(counts.critical)}%` }}
                className="bg-sev-critical h-full transition-all duration-500"
                title={`Critical: ${counts.critical}`}
              />
            )}
            {counts.high > 0 && (
              <div
                style={{ width: `${pct(counts.high)}%` }}
                className="bg-sev-high h-full transition-all duration-500"
                title={`High: ${counts.high}`}
              />
            )}
            {counts.medium > 0 && (
              <div
                style={{ width: `${pct(counts.medium)}%` }}
                className="bg-sev-medium h-full transition-all duration-500"
                title={`Medium: ${counts.medium}`}
              />
            )}
            {counts.low > 0 && (
              <div
                style={{ width: `${pct(counts.low)}%` }}
                className="bg-sev-low h-full transition-all duration-500"
                title={`Low: ${counts.low}`}
              />
            )}
          </>
        )}
      </div>

      {/* Legend with text counts */}
      <div className="text-muted-foreground flex flex-wrap items-center gap-4 pt-1 text-xs font-medium">
        <div className="flex items-center gap-1.5">
          <span className="bg-sev-critical size-2 shrink-0 rounded-full" />
          <span>Critical:</span>
          <span className="text-foreground font-mono font-bold">{counts.critical}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="bg-sev-high size-2 shrink-0 rounded-full" />
          <span>High:</span>
          <span className="text-foreground font-mono font-bold">{counts.high}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="bg-sev-medium size-2 shrink-0 rounded-full" />
          <span>Medium:</span>
          <span className="text-foreground font-mono font-bold">{counts.medium}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="bg-sev-low size-2 shrink-0 rounded-full" />
          <span>Low:</span>
          <span className="text-foreground font-mono font-bold">{counts.low}</span>
        </div>
      </div>
    </div>
  );
}
