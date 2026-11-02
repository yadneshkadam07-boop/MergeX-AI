import { Badge } from "@/components/ui/badge";
import type { ProjectStatus } from "@/types/project";
import { Loader2 } from "lucide-react";

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
          className={`border-success bg-success/12 text-success text-xs font-medium ${className || ""}`}
        >
          Completed
        </Badge>
      );
    case "analyzing":
      return (
        <Badge
          variant="outline"
          className={`border-brand-secondary bg-brand-secondary/12 text-brand-secondary gap-1.5 text-xs font-medium ${className || ""}`}
        >
          <Loader2 className="text-brand-secondary size-3 animate-spin" />
          Analyzing
        </Badge>
      );
    case "failed":
      return (
        <Badge
          variant="outline"
          className={`border-sev-critical bg-sev-critical/12 text-sev-critical text-xs font-medium ${className || ""}`}
        >
          Failed
        </Badge>
      );
  }
}
