import { Link, useParams } from "react-router-dom";
import type { PriorityIssue } from "@/types/project";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SeverityBadge } from "@/components/shared/SeverityBadge";
import { AlertCircle, CheckCircle2, ChevronRight, FileCode } from "lucide-react";

interface PriorityIssuesListProps {
  issues: PriorityIssue[];
}

export function PriorityIssuesList({ issues }: PriorityIssuesListProps) {
  const { id } = useParams<{ id: string }>();

  const getCategoryTab = (category: PriorityIssue["category"]) => {
    switch (category) {
      case "integration":
        return "integration";
      case "security":
        return "security";
      case "dependencies":
        return "dependencies";
      case "deployment":
        return "deploy";
    }
  };

  if (!issues || issues.length === 0) {
    return (
      <Card className="bg-card border">
        <CardContent className="flex flex-col items-center justify-center py-12 text-center">
          <div className="bg-success/12 text-success flex size-12 items-center justify-center rounded-2xl">
            <CheckCircle2 className="size-6" />
          </div>
          <h3 className="text-foreground mt-3 text-base font-semibold">
            No priority issues detected
          </h3>
          <p className="text-muted-foreground mt-1 max-w-sm text-xs">
            All high and critical risk diagnostics have cleared. Check specific tabs for
            lower-priority optimizations.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="bg-card border shadow-xs">
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <div className="flex items-center gap-2">
          <AlertCircle className="text-brand-secondary size-5" />
          <CardTitle className="text-base font-semibold">Priority Issues</CardTitle>
        </div>
        <span className="text-muted-foreground font-mono text-xs">
          Showing top {issues.length} items
        </span>
      </CardHeader>

      <CardContent className="divide-border/60 divide-y p-0">
        {issues.map((issue) => {
          const tab = getCategoryTab(issue.category);

          return (
            <div
              key={issue.id}
              className="hover:bg-muted/30 flex flex-col gap-3 p-4 transition-colors sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="min-w-0 flex-1 space-y-1.5">
                <div className="flex flex-wrap items-center gap-2">
                  <SeverityBadge severity={issue.severity} />
                  <span className="text-foreground text-xs leading-snug font-semibold">
                    {issue.title}
                  </span>
                </div>

                <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
                  <Badge
                    variant="secondary"
                    className="px-1.5 py-0 font-mono text-[10px] uppercase"
                  >
                    {issue.category}
                  </Badge>
                  <span className="hidden sm:inline">·</span>
                  <div className="text-muted-foreground flex max-w-md items-center gap-1 truncate font-mono text-[11px]">
                    <FileCode className="size-3 shrink-0" />
                    <span className="truncate">{issue.filePath}</span>
                  </div>
                </div>

                <p className="text-muted-foreground line-clamp-1 pt-0.5 text-xs leading-relaxed">
                  {issue.shortDescription}
                </p>
              </div>

              <div className="shrink-0 self-end sm:self-center">
                <Link
                  to={`/project/${id}/${tab}`}
                  className="text-primary inline-flex items-center gap-1 text-xs font-medium hover:underline"
                >
                  <span>View in {issue.category}</span>
                  <ChevronRight className="size-3.5" />
                </Link>
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
