import React, { memo, useState, useMemo, useEffect } from "react";
import type { Issue } from "@/types/issue";
import { SeverityBadge } from "@/components/shared/SeverityBadge";
import { EmptyState } from "@/components/shared/EmptyState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createBatchPullRequest } from "@/lib/api";
import { ApiError } from "@/lib/http";
import { toast } from "sonner";
import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  FileCode,
  GitPullRequest,
  Loader2,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface IssueTableProps {
  issues: Issue[];
  projectId?: string;
  loading?: boolean;
  onSelect: (issue: Issue) => void;
  renderExtraHeader?: () => React.ReactNode;
  renderExtraCell?: (issue: Issue) => React.ReactNode;
  extraHeaderLabel?: string;
  emptyTitle?: string;
  emptyDescription?: string;
  onIssuesResolved?: (resolvedIds: string[]) => void;
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
  isSelected: boolean;
  onSelect: (issue: Issue) => void;
  onToggleSelect: (issueId: string) => void;
  renderExtraCell?: ((issue: Issue) => React.ReactNode) | undefined;
  hasExtraCell?: boolean;
}

const MemoizedIssueTableRow = memo(function IssueTableRow({
  issue,
  isSelected,
  onSelect,
  onToggleSelect,
  renderExtraCell,
  hasExtraCell,
}: IssueRowProps) {
  const isMuted = issue.status !== "open";
  const locationTooltip = `${issue.filePath}${
    issue.lineStart ? ` (Line ${issue.lineStart}${issue.lineEnd ? `-${issue.lineEnd}` : ""})` : ""
  }`;

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
        "smooth-row hover:bg-muted/50 focus:bg-muted/60 cursor-pointer transition-colors focus:outline-hidden",
        isMuted && "bg-muted/15 opacity-60",
        isSelected && "bg-purple-500/10 hover:bg-purple-500/15",
      )}
    >
      {/* Checkbox */}
      <TableCell
        className="w-10 py-3 pl-4 align-top"
        onClick={(e) => {
          e.stopPropagation();
        }}
      >
        <input
          type="checkbox"
          checked={isSelected}
          onChange={() => onToggleSelect(issue.id)}
          className="size-4 rounded border-border accent-purple-600 cursor-pointer"
          aria-label={`Select issue ${issue.title}`}
        />
      </TableCell>

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

      {/* File Location with High-Performance Native Tooltip */}
      <TableCell className="py-3 align-top">
        <div
          title={locationTooltip}
          className="text-muted-foreground hover:text-foreground inline-flex max-w-[190px] items-center gap-1.5 truncate font-mono text-[11px] cursor-help"
        >
          <FileCode className="size-3.5 shrink-0 opacity-70" />
          <span className="truncate">{issue.filePath}</span>
        </div>
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
  isSelected,
  onSelect,
  onToggleSelect,
}: {
  issue: Issue;
  isSelected: boolean;
  onSelect: (issue: Issue) => void;
  onToggleSelect: (issueId: string) => void;
}) {
  const isMuted = issue.status !== "open";
  const locationTooltip = `${issue.filePath}${
    issue.lineStart ? ` (Line ${issue.lineStart}${issue.lineEnd ? `-${issue.lineEnd}` : ""})` : ""
  }`;

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
        "smooth-card bg-card focus-visible:ring-ring cursor-pointer gap-0 rounded-xl border p-4 py-4 text-left focus:outline-hidden focus-visible:ring-2",
        isMuted && "bg-muted/20 opacity-60",
        isSelected && "border-purple-500/40 bg-purple-500/10",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div
          className="flex items-center gap-2.5"
          onClick={(e) => {
            e.stopPropagation();
          }}
        >
          <input
            type="checkbox"
            checked={isSelected}
            onChange={() => onToggleSelect(issue.id)}
            className="size-4 rounded border-border accent-purple-600 cursor-pointer"
            aria-label={`Select issue ${issue.title}`}
          />
          <SeverityBadge severity={issue.severity} />
        </div>
        {getStatusBadge(issue.status)}
      </div>

      <h4 className="text-foreground mt-2.5 line-clamp-2 text-sm font-semibold">{issue.title}</h4>
      <p className="text-muted-foreground mt-1 line-clamp-1 text-xs">{issue.shortDescription}</p>

      <div className="text-muted-foreground mt-3 flex items-center justify-between border-t pt-2.5 text-xs">
        <div
          title={locationTooltip}
          className="flex max-w-[200px] items-center gap-1 truncate font-mono text-[11px] cursor-help"
        >
          <FileCode className="size-3.5 shrink-0 opacity-70" />
          <span className="truncate">{issue.filePath}</span>
        </div>
        <ChevronRight className="text-muted-foreground/60 size-4" />
      </div>
    </Card>
  );
});

export function IssueTable({
  issues,
  projectId,
  loading = false,
  onSelect,
  extraHeaderLabel,
  renderExtraCell,
  emptyTitle = "No issues detected",
  emptyDescription = "No issues matching the selected filters were found in this category.",
  onIssuesResolved,
}: IssueTableProps) {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [creatingBatchPr, setCreatingBatchPr] = useState(false);
  const [tokenModalOpen, setTokenModalOpen] = useState(false);
  const [githubToken, setGithubToken] = useState(() => {
    if (typeof window !== "undefined") {
      return sessionStorage.getItem("mergex_github_token") || "";
    }
    return "";
  });
  const [rememberToken, setRememberToken] = useState(true);

  // Pagination for ultra-fast rendering & smooth scrolling
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState<number>(20);

  useEffect(() => {
    setCurrentPage(1);
  }, [issues.length]);

  const totalPages = pageSize === -1 ? 1 : Math.ceil(issues.length / pageSize);
  const safePage = Math.min(Math.max(currentPage, 1), Math.max(totalPages, 1));

  const displayedIssues = useMemo(() => {
    if (pageSize === -1 || issues.length <= pageSize) return issues;
    const start = (safePage - 1) * pageSize;
    return issues.slice(start, start + pageSize);
  }, [issues, safePage, pageSize]);

  const toggleSelect = (issueId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(issueId)) {
        next.delete(issueId);
      } else {
        next.add(issueId);
      }
      return next;
    });
  };

  const openIssues = displayedIssues.filter((i) => i.status === "open");
  const allOpenSelected =
    openIssues.length > 0 && openIssues.every((i) => selectedIds.has(i.id));

  const toggleSelectAll = () => {
    if (allOpenSelected) {
      setSelectedIds((prev) => {
        const next = new Set(prev);
        openIssues.forEach((i) => next.delete(i.id));
        return next;
      });
    } else {
      setSelectedIds((prev) => {
        const next = new Set(prev);
        openIssues.forEach((i) => next.add(i.id));
        return next;
      });
    }
  };

  const executeBatchPr = async (token?: string) => {
    if (!projectId || selectedIds.size === 0 || creatingBatchPr) return;
    setCreatingBatchPr(true);
    const idsToResolve = Array.from(selectedIds);

    try {
      const res = await createBatchPullRequest(projectId, idsToResolve, token);
      setSelectedIds(new Set());

      if (onIssuesResolved) {
        onIssuesResolved(res.resolvedIssueIds || idsToResolve);
      }
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("mergex:issue-updated"));
      }

      if (res.status === "simulated") {
        toast.info(`Simulated Consolidated PR generated (${res.branch})`, {
          description: "Connect a GitHub PAT with write access for a live repository pull request.",
        });
      } else {
        toast.success(`Consolidated PR #${res.prNumber} opened on GitHub!`, {
          description: `Applied fixes for ${res.resolvedIssueIds?.length || idsToResolve.length} issues.`,
          action: {
            label: "View PR",
            onClick: () => window.open(res.prUrl, "_blank"),
          },
        });
      }
    } catch (err) {
      console.error("Failed to create batch pull request:", err);
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Failed to create Consolidated Pull Request.";
      toast.error(msg);
    } finally {
      setCreatingBatchPr(false);
    }
  };

  const handleInitiateBatchPr = () => {
    if (selectedIds.size === 0 || creatingBatchPr) return;
    const savedToken =
      typeof window !== "undefined"
        ? sessionStorage.getItem("mergex_github_token") || ""
        : "";

    if (savedToken.trim()) {
      executeBatchPr(savedToken.trim());
    } else {
      setTokenModalOpen(true);
    }
  };

  const handleConfirmBatchToken = (useToken: boolean) => {
    const tokenToUse = useToken && githubToken.trim() ? githubToken.trim() : undefined;
    if (typeof window !== "undefined") {
      if (useToken && rememberToken && githubToken.trim()) {
        sessionStorage.setItem("mergex_github_token", githubToken.trim());
      } else if (!useToken) {
        sessionStorage.removeItem("mergex_github_token");
      }
    }
    setTokenModalOpen(false);
    executeBatchPr(tokenToUse);
  };

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
    <div className="w-full space-y-4">
      {/* Mobile Card View (< md) */}
      <div className="grid grid-cols-1 gap-3 md:hidden">
        {displayedIssues.map((issue) => (
          <MemoizedIssueMobileCard
            key={issue.id}
            issue={issue}
            isSelected={selectedIds.has(issue.id)}
            onSelect={onSelect}
            onToggleSelect={toggleSelect}
          />
        ))}
      </div>

      {/* Desktop Table View (>= md) */}
      <div className="bg-card hidden overflow-hidden rounded-xl border shadow-xs md:block">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-10 pl-4">
                <input
                  type="checkbox"
                  checked={allOpenSelected}
                  onChange={toggleSelectAll}
                  className="size-4 rounded border-border accent-purple-600 cursor-pointer"
                  aria-label="Select all open issues on this page"
                  title="Select all open issues on this page"
                />
              </TableHead>
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
            {displayedIssues.map((issue) => (
              <MemoizedIssueTableRow
                key={issue.id}
                issue={issue}
                isSelected={selectedIds.has(issue.id)}
                onSelect={onSelect}
                onToggleSelect={toggleSelect}
                renderExtraCell={renderExtraCell}
                hasExtraCell={Boolean(extraHeaderLabel)}
              />
            ))}
          </TableBody>
        </Table>
      </div>

      {/* High-Performance Pagination Footer */}
      {issues.length > 20 && (
        <div className="flex flex-col sm:flex-row items-center justify-between gap-3 px-2 pt-1 text-xs text-muted-foreground">
          <div>
            Showing{" "}
            <span className="font-semibold text-foreground">
              {pageSize === -1 ? 1 : (safePage - 1) * pageSize + 1}–
              {pageSize === -1 ? issues.length : Math.min(safePage * pageSize, issues.length)}
            </span>{" "}
            of <span className="font-semibold text-foreground">{issues.length}</span> issues
          </div>

          <div className="flex items-center gap-1.5">
            <Button
              variant="outline"
              size="sm"
              disabled={safePage <= 1}
              onClick={() => setCurrentPage((p) => Math.max(p - 1, 1))}
              className="h-7 w-7 p-0"
              aria-label="Previous page"
            >
              <ChevronLeft className="size-3.5" />
            </Button>

            <span className="px-2 text-xs font-medium">
              Page {safePage} of {totalPages}
            </span>

            <Button
              variant="outline"
              size="sm"
              disabled={safePage >= totalPages}
              onClick={() => setCurrentPage((p) => Math.min(p + 1, totalPages))}
              className="h-7 w-7 p-0"
              aria-label="Next page"
            >
              <ChevronRight className="size-3.5" />
            </Button>

            {/* Page size toggle */}
            <div className="ml-2 flex items-center gap-1 border-l pl-2 border-border">
              <span className="text-[11px] text-muted-foreground">Per page:</span>
              {[20, 50, -1].map((size) => (
                <button
                  key={size}
                  onClick={() => {
                    setPageSize(size);
                    setCurrentPage(1);
                  }}
                  className={cn(
                    "px-1.5 py-0.5 rounded text-[11px] font-medium transition-colors cursor-pointer",
                    pageSize === size
                      ? "bg-purple-600 text-white font-semibold"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {size === -1 ? "All" : size}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Floating Sticky Batch Action Bar (GPU Accelerated) */}
      {selectedIds.size > 0 && (
        <div className="gpu-accelerated fixed bottom-6 left-1/2 -translate-x-1/2 z-40 flex items-center gap-3 rounded-full border border-purple-500/30 bg-background/95 backdrop-blur-md px-4 py-2.5 shadow-2xl animate-in fade-in slide-in-from-bottom-4 duration-200">
          <Badge
            variant="secondary"
            className="bg-purple-500/20 text-purple-300 font-semibold text-xs h-6 px-2.5"
          >
            {selectedIds.size} {selectedIds.size === 1 ? "issue" : "issues"} selected
          </Badge>

          <Button
            size="sm"
            onClick={handleInitiateBatchPr}
            disabled={creatingBatchPr}
            className="h-8 gap-1.5 rounded-full bg-gradient-to-r from-purple-600 to-indigo-600 text-xs font-semibold text-white shadow-sm hover:from-purple-500 hover:to-indigo-500"
          >
            {creatingBatchPr ? (
              <>
                <Loader2 className="size-3.5 animate-spin" />
                <span>Creating Consolidated PR...</span>
              </>
            ) : (
              <>
                <GitPullRequest className="size-3.5" />
                <span>Fix with Consolidated PR</span>
              </>
            )}
          </Button>

          <Button
            variant="ghost"
            size="sm"
            onClick={() => setSelectedIds(new Set())}
            className="h-8 rounded-full text-xs text-muted-foreground hover:text-foreground"
          >
            <X className="size-3.5" />
            <span>Clear</span>
          </Button>
        </div>
      )}

      {/* GitHub Token Modal for Batch PR */}
      <Dialog open={tokenModalOpen} onOpenChange={setTokenModalOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <div className="flex items-center gap-2">
              <div className="bg-purple-500/10 text-purple-400 flex size-8 items-center justify-center rounded-lg">
                <GitPullRequest className="size-4" />
              </div>
              <DialogTitle className="text-base font-semibold">
                Create Consolidated PR ({selectedIds.size} issues)
              </DialogTitle>
            </div>
            <DialogDescription className="text-xs">
              MergeX AI will create a single branch applying automated patches across all {selectedIds.size} selected issues and open a combined Pull Request on GitHub.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label htmlFor="batch-pr-token" className="text-xs font-medium">
                GitHub Personal Access Token (PAT)
              </Label>
              <Input
                id="batch-pr-token"
                type="password"
                placeholder="ghp_xxxxxxxxxxxxxxxxxxxx"
                value={githubToken}
                onChange={(e) => setGithubToken(e.target.value)}
                className="h-9 font-mono text-xs"
              />
              <p className="text-muted-foreground text-[11px] leading-relaxed">
                Requires <code className="text-foreground font-mono">repo</code> scope. For public &amp; 3rd-party repositories, MergeX AI automatically forks the repo to your account and opens the PR upstream.
                <a
                  href="https://github.com/settings/tokens/new?scopes=repo&description=MergeX+AI+PR+Remediation"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 font-semibold text-primary hover:underline ml-1"
                >
                  Generate Token on GitHub ↗
                </a>
              </p>
            </div>

            <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
              <input
                type="checkbox"
                checked={rememberToken}
                onChange={(e) => setRememberToken(e.target.checked)}
                className="rounded border-border accent-purple-600 size-3.5"
              />
              <span>Remember token for this browser session</span>
            </label>
          </div>

          <DialogFooter className="flex-col gap-2 sm:flex-row sm:justify-between">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => handleConfirmBatchToken(false)}
              className="text-muted-foreground hover:text-foreground text-xs"
            >
              Simulate Demo PR
            </Button>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setTokenModalOpen(false)}
                className="text-xs"
              >
                Cancel
              </Button>
              <Button
                type="button"
                size="sm"
                onClick={() => handleConfirmBatchToken(true)}
                disabled={!githubToken.trim()}
                className="bg-purple-600 hover:bg-purple-500 text-white text-xs font-semibold gap-1.5"
              >
                <GitPullRequest className="size-3.5" />
                <span>Create Consolidated PR</span>
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
