import { Badge } from "@/components/ui/badge";
import type { ProjectStatus } from "@/types/project";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface StatusBadgeProps {
  status: ProjectStatus;
  className?: string;
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  switch (status) {
    case "completed":
      return (
        <Badge
          variant="outline"
          className={cn(
            "border-success bg-success/12 text-success shrink-0 text-xs font-medium whitespace-nowrap",
            className,
          )}
        >
          Completed
        </Badge>
      );
    case "analyzing":
      return (
        <Badge
          variant="outline"
          className={cn(
            "border-brand-secondary bg-brand-secondary/12 text-brand-secondary shrink-0 gap-1.5 text-xs font-medium whitespace-nowrap",
            className,
          )}
        >
          <Loader2 className="text-brand-secondary size-3 animate-spin" />
          Analyzing
        </Badge>
      );
    case "failed":
      return (
        <Badge
          variant="outline"
          className={cn(
            "border-sev-critical bg-sev-critical/12 text-sev-critical shrink-0 text-xs font-medium whitespace-nowrap",
            className,
          )}
        >
          Failed
        </Badge>
      );
  }
}
