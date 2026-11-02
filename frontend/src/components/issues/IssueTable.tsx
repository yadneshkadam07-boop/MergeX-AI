import React, { memo } from "react";
import type { Issue } from "@/types/issue";
import { SeverityBadge } from "@/components/shared/SeverityBadge";
import { EmptyState } from "@/components/shared/EmptyState";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Skeleton } from "@/components/ui/skeleton";
import { CheckCircle2, ChevronRight, FileCode } from "lucide-react";
import { cn } from "@/lib/utils";

interface IssueTableProps {
  issues: Issue[];
  loading?: boolean;
  onSelect: (issue: Issue) => void;
  renderExtraHeader?: () => React.ReactNode;
  renderExtraCell?: (issue: Issue) => React.ReactNode;
  extraHeaderLabel?: string;
  emptyTitle?: string;
  emptyDescription?: string;
}

function getStatusBadge(status: Issue["status"]) {
  switch (status) {
    case "resolved":
      return (
        <Badge
          variant="outline"
          className="border-success bg-success/12 text-success text-[10px] font-semibold"
        >
          Resolved
        </Badge>
      );
    case "ignored":
      return (
        <Badge
          variant="outline"
          className="border-muted bg-muted/60 text-muted-foreground text-[10px] font-semibold"
        >
          Ignored
        </Badge>
      );
    case "open":
    default:
      return (
        <Badge
          variant="outline"
          className="border-brand-secondary bg-brand-secondary/12 text-brand-secondary text-[10px] font-semibold"
        >
          Open
        </Badge>
      );
  }
}

interface IssueRowProps {
  issue: Issue;
  onSelect: (issue: Issue) => void;
  renderExtraCell?: ((issue: Issue) => React.ReactNode) | undefined;
  hasExtraCell?: boolean;
}

const MemoizedIssueTableRow = memo(function IssueTableRow({
  issue,
  onSelect,
  renderExtraCell,
  hasExtraCell,
}: IssueRowProps) {
  const isMuted = issue.status !== "open";

  return (
    <TableRow
      tabIndex={0}
      onClick={() => onSelect(issue)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(issue);
        }
      }}
      className={cn(
        "hover:bg-muted/50 focus:bg-muted/60 cursor-pointer transition-colors focus:outline-hidden",
        isMuted && "bg-muted/15 opacity-60",
      )}
    >
      {/* Severity */}
      <TableCell className="py-3 align-top">
        <SeverityBadge severity={issue.severity} />
      </TableCell>

      {/* Title & Short Description */}
      <TableCell className="max-w-md py-3">
        <div className="space-y-0.5">
          <p className="text-foreground text-xs leading-snug font-semibold">{issue.title}</p>
          <p className="text-muted-foreground line-clamp-1 text-[11px]">{issue.shortDescription}</p>
        </div>
      </TableCell>

      {/* File Location with Tooltip */}
      <TableCell className="py-3 align-top">
        <Tooltip delayDuration={200}>
          <TooltipTrigger asChild>
            <div className="text-muted-foreground hover:text-foreground inline-flex max-w-[180px] items-center gap-1.5 truncate font-mono text-[11px]">
              <FileCode className="size-3.5 shrink-0" />
              <span className="truncate">{issue.filePath}</span>
            </div>
          </TooltipTrigger>
          <TooltipContent side="top" className="max-w-sm font-mono text-xs break-all">
            {issue.filePath}
            {issue.lineStart
              ? ` (Line ${issue.lineStart}${issue.lineEnd ? `-${issue.lineEnd}` : ""})`
              : ""}
          </TooltipContent>
        </Tooltip>
      </TableCell>

      {/* Optional Extra Category Cell */}
      {hasExtraCell && renderExtraCell && (
        <TableCell className="py-3 align-top">{renderExtraCell(issue)}</TableCell>
      )}

      {/* Status */}
      <TableCell className="py-3 text-right align-top">{getStatusBadge(issue.status)}</TableCell>
    </TableRow>
  );
});

const MemoizedIssueMobileCard = memo(function IssueMobileCard({
  issue,
  onSelect,
}: {
  issue: Issue;
  onSelect: (issue: Issue) => void;
}) {
  const isMuted = issue.status !== "open";

  return (
    <Card
      interactive
      role="button"
      tabIndex={0}
      onClick={() => onSelect(issue)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(issue);
        }
      }}
      className={cn(
        "bg-card focus-visible:ring-ring cursor-pointer gap-0 rounded-xl border p-4 py-4 text-left focus:outline-hidden focus-visible:ring-2",
        isMuted && "bg-muted/20 opacity-60",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <SeverityBadge severity={issue.severity} />
        {getStatusBadge(issue.status)}
      </div>

      <h4 className="text-foreground mt-2.5 line-clamp-2 text-sm font-semibold">{issue.title}</h4>
      <p className="text-muted-foreground mt-1 line-clamp-1 text-xs">{issue.shortDescription}</p>

      <div className="text-muted-foreground mt-3 flex items-center justify-between border-t pt-2.5 text-xs">
        <div className="flex max-w-[200px] items-center gap-1 truncate font-mono text-[11px]">
          <FileCode className="size-3.5 shrink-0" />
          <span className="truncate">{issue.filePath}</span>
        </div>
        <ChevronRight className="text-muted-foreground/60 size-4" />
      </div>
    </Card>
  );
});

export function IssueTable({
  issues,
  loading = false,
  onSelect,
  extraHeaderLabel,
  renderExtraCell,
  emptyTitle = "No issues detected",
  emptyDescription = "No issues matching the selected filters were found in this category.",
}: IssueTableProps) {
  if (loading) {
    return (
      <div className="bg-card space-y-2 rounded-xl border p-4">
        {[1, 2, 3, 4, 5].map((i) => (
          <div
            key={i}
            className="flex animate-pulse items-center justify-between gap-4 border-b py-2 last:border-0"
          >
            <Skeleton className="h-6 w-20 rounded-md" />
            <div className="flex-1 space-y-1">
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-3 w-1/3" />
            </div>
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-6 w-16" />
          </div>
        ))}
      </div>
    );
  }

  if (issues.length === 0) {
    return <EmptyState icon={CheckCircle2} title={emptyTitle} description={emptyDescription} />;
  }

  return (
    <div className="w-full">
      {/* Mobile Card View (< md) */}
      <div className="grid grid-cols-1 gap-3 md:hidden">
        {issues.map((issue) => (
          <MemoizedIssueMobileCard key={issue.id} issue={issue} onSelect={onSelect} />
        ))}
      </div>

      {/* Desktop Table View (>= md) */}
      <div className="bg-card hidden overflow-hidden rounded-xl border shadow-xs md:block">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-28 text-xs font-semibold">Severity</TableHead>
              <TableHead className="text-xs font-semibold">Issue Title</TableHead>
              <TableHead className="w-48 text-xs font-semibold">File Location</TableHead>
              {extraHeaderLabel && (
                <TableHead className="w-44 text-xs font-semibold">{extraHeaderLabel}</TableHead>
              )}
              <TableHead className="w-24 text-right text-xs font-semibold">Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {issues.map((issue) => (
              <MemoizedIssueTableRow
                key={issue.id}
                issue={issue}
                onSelect={onSelect}
                renderExtraCell={renderExtraCell}
                hasExtraCell={Boolean(extraHeaderLabel)}
              />
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
