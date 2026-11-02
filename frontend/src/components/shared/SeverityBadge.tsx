import { Badge } from "@/components/ui/badge";
import type { IssueSeverity } from "@/types/project";
import { cn } from "@/lib/utils";

interface SeverityBadgeProps {
  severity: IssueSeverity;
  className?: string;
  showDot?: boolean;
}

export function SeverityBadge({ severity, className, showDot = true }: SeverityBadgeProps) {
  let badgeClasses = "";
  let dotClass = "";
  let label = "";

  switch (severity) {
    case "critical":
      badgeClasses = "border border-sev-critical bg-sev-critical/12 text-sev-critical";
      dotClass = "bg-sev-critical";
      label = "Critical";
      break;
    case "high":
      badgeClasses = "border border-sev-high bg-sev-high/12 text-sev-high";
      dotClass = "bg-sev-high";
      label = "High";
      break;
    case "medium":
      badgeClasses = "border border-sev-medium bg-sev-medium/12 text-sev-medium";
      dotClass = "bg-sev-medium";
      label = "Medium";
      break;
    case "low":
      badgeClasses = "border border-sev-low bg-sev-low/12 text-sev-low";
      dotClass = "bg-sev-low";
      label = "Low";
      break;
  }

  return (
    <Badge
      variant="outline"
      className={cn(
        "gap-1.5 rounded-md px-2 py-0.5 text-[11px] font-semibold tracking-wider uppercase select-none",
        badgeClasses,
        className,
      )}
    >
      {showDot && <span className={cn("size-1.5 shrink-0 rounded-full", dotClass)} />}
      <span>{label}</span>
    </Badge>
  );
}
