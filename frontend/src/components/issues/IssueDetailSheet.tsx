import { useEffect, useState, useMemo, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import type { Issue, IssueStatus } from "@/types/issue";
import { getIssue, updateIssueStatus, createPullRequest } from "@/lib/api";
import type { CreatePullRequestResponse } from "@/lib/api/types";
import { SeverityBadge } from "@/components/shared/SeverityBadge";
import { LoadingState } from "@/components/shared/LoadingState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ButtonRow } from "@/components/ui/button-row";
import { toast } from "sonner";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import {
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Copy,
  ExternalLink,
  EyeOff,
  FileCode,
  GitPullRequest,
  Loader2,
  RotateCcw,
  Sparkles,
} from "lucide-react";

interface IssueDetailSheetProps {
  projectId: string;
  filteredIssues?: Issue[];
  onIssueUpdated?: (updated: Issue) => void;
}

export function IssueDetailSheet({
  projectId,
  filteredIssues = [],
  onIssueUpdated,
}: IssueDetailSheetProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const issueId = searchParams.get("issue");

  const [issue, setIssue] = useState<Issue | null>(null);
  const [loading, setLoading] = useState(false);
  const [copiedPrompt, setCopiedPrompt] = useState(false);
  const [copiedPath, setCopiedPath] = useState(false);
  const [creatingPr, setCreatingPr] = useState(false);
  const [prResult, setPrResult] = useState<CreatePullRequestResponse | null>(null);

  // Close sheet by removing query param
  const handleClose = useCallback(() => {
    const next = new URLSearchParams(searchParams);
    next.delete("issue");
    setSearchParams(next, { replace: true });
    setPrResult(null);
  }, [searchParams, setSearchParams]);

  // Fetch issue when issueId changes
  useEffect(() => {
    setPrResult(null);
    if (!issueId) {
      setIssue(null);
      return;
    }

    let isMounted = true;
    setLoading(true);

    getIssue(projectId, issueId)
      .then((data) => {
        if (!isMounted) return;
        if (!data) {
          // Invalid ID: close panel gracefully
          handleClose();
        } else {
          setIssue(data);
        }
        setLoading(false);
      })
      .catch((err) => {
        console.error("Failed to load issue:", err);
        if (isMounted) {
          handleClose();
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [projectId, issueId, handleClose]);

  // Index in currently filtered list for Prev/Next navigation
  const currentIndex = useMemo(() => {
    if (!issue || filteredIssues.length === 0) return -1;
    return filteredIssues.findIndex((i) => i.id === issue.id);
  }, [issue, filteredIssues]);

  const prevIssue = currentIndex > 0 ? filteredIssues[currentIndex - 1] : null;
  const nextIssue =
    currentIndex >= 0 && currentIndex < filteredIssues.length - 1
      ? filteredIssues[currentIndex + 1]
      : null;

  const navigateToIssue = (targetId: string) => {
    const next = new URLSearchParams(searchParams);
    next.set("issue", targetId);
    setSearchParams(next, { replace: true });
  };

  const handleCopyPath = async () => {
    if (!issue) return;
    const text = `${issue.filePath}${issue.lineStart ? `:${issue.lineStart}` : ""}`;
    await navigator.clipboard.writeText(text);
    setCopiedPath(true);
    toast.success("File path copied to clipboard");
    setTimeout(() => setCopiedPath(false), 2000);
  };

  const handleCopyAiPrompt = async () => {
    if (!issue) return;

    const promptText = `Fix this ${issue.severity.toUpperCase()} ${issue.category} issue in ${issue.filePath}:
Issue: ${issue.title}
Problem: ${issue.explanation}
Impact: ${issue.impact}

Recommended Remediation:
${issue.suggestedFix.summary}
Steps:
${issue.suggestedFix.steps.map((s, idx) => `${idx + 1}. ${s}`).join("\n")}

Please implement the exact fix in ${issue.filePath}.`;

    await navigator.clipboard.writeText(promptText);
    setCopiedPrompt(true);
    toast.success("AI fix prompt copied to clipboard");
    setTimeout(() => setCopiedPrompt(false), 2500);
  };

  const handleCreatePr = async () => {
    if (!issue || creatingPr) return;
    setCreatingPr(true);
    try {
      const savedToken =
        typeof window !== "undefined"
          ? sessionStorage.getItem("mergex_github_token") || undefined
          : undefined;
      const res = await createPullRequest(projectId, issue.id, savedToken);
      setPrResult(res);
      const updated: Issue = { ...issue, status: "resolved" };
      setIssue(updated);
      if (onIssueUpdated) onIssueUpdated(updated);
      toast.success(`GitHub Pull Request #${res.prNumber} opened successfully!`, {
        action: {
          label: "View PR",
          onClick: () => window.open(res.prUrl, "_blank"),
        },
      });
    } catch (err) {
      console.error("Failed to create pull request:", err);
      toast.error("Failed to create GitHub Pull Request. Please verify your token permissions.");
    } finally {
      setCreatingPr(false);
    }
  };

  const handleUpdateStatus = async (newStatus: IssueStatus) => {
    if (!issue) return;

    // Optimistic local state update
    const previous = { ...issue };
    const updated = { ...issue, status: newStatus };
    setIssue(updated);
    if (onIssueUpdated) onIssueUpdated(updated);

    toast.success(`Issue marked as ${newStatus}`, {
      action: {
        label: "Undo",
        onClick: () => {
          void (async () => {
            setIssue(previous);
            if (onIssueUpdated) onIssueUpdated(previous);
            try {
              await updateIssueStatus(projectId, previous.id, previous.status);
              toast.info(`Issue reverted to ${previous.status}`);
            } catch {
              toast.error("Failed to revert issue status");
            }
          })();
        },
      },
    });

    try {
      await updateIssueStatus(projectId, issue.id, newStatus);
    } catch (err) {
      console.error("Failed to update status:", err);
      // Rollback on failure
      setIssue(previous);
      if (onIssueUpdated) onIssueUpdated(previous);
      toast.error("Failed to update status. Rolled back changes.");
    }
  };

  const isOpen = Boolean(issueId);

  return (
    <Sheet
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) handleClose();
      }}
    >
      <SheetContent
        side="right"
        className="bg-background flex h-full w-full max-w-[calc(100vw-2rem)] flex-col overflow-hidden p-0 sm:max-w-xl md:max-w-2xl"
      >
        {/* Navigation Top Header */}
        <div className="bg-muted/20 flex min-w-0 flex-wrap items-center justify-between gap-2 border-b px-4 py-3 sm:px-6">
          <ButtonRow align="start" className="gap-1.5">
            <Button
              variant="ghost"
              size="sm"
              disabled={!prevIssue}
              onClick={() => prevIssue && navigateToIssue(prevIssue.id)}
              className="gap-1 text-xs font-medium"
            >
              <ChevronLeft className="size-4" />
              <span>Previous</span>
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={!nextIssue}
              onClick={() => nextIssue && navigateToIssue(nextIssue.id)}
              className="gap-1 text-xs font-medium"
            >
              <span>Next</span>
              <ChevronRight className="size-4" />
            </Button>
          </ButtonRow>

          <span className="text-muted-foreground shrink-0 font-mono text-xs">
            {currentIndex >= 0 ? `${currentIndex + 1} of ${filteredIssues.length}` : ""}
          </span>
        </div>

        {/* Scrollable Sheet Content */}
        <div className="flex-1 space-y-6 overflow-y-auto px-6 py-6">
          {loading || !issue ? (
            <LoadingState message="Loading issue details..." minHeight="min-h-[300px]" />
          ) : (
            <>
              {/* 1. Header: Badges & Title */}
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <SeverityBadge severity={issue.severity} />
                  <Badge variant="secondary" className="font-mono text-xs uppercase">
                    {issue.category}
                  </Badge>
                  <Badge
                    variant="outline"
                    className={
                      issue.status === "resolved"
                        ? "border-success bg-success/12 text-success font-semibold"
                        : issue.status === "ignored"
                          ? "border-muted bg-muted/60 text-muted-foreground font-semibold"
                          : "border-brand-secondary bg-brand-secondary/12 text-brand-secondary font-semibold"
                    }
                  >
                    {issue.status.toUpperCase()}
                  </Badge>
                </div>

                <SheetHeader className="p-0 text-left">
                  <SheetTitle className="text-foreground text-xl font-bold tracking-tight sm:text-2xl">
                    {issue.title}
                  </SheetTitle>
                  <SheetDescription className="text-muted-foreground text-xs">
                    {issue.shortDescription}
                  </SheetDescription>
                </SheetHeader>
              </div>

              {/* 2. Location */}
              <div className="bg-muted/40 flex items-center justify-between rounded-lg border p-3 text-xs">
                <div className="text-foreground flex max-w-sm items-center gap-2 truncate font-mono">
                  <FileCode className="text-muted-foreground size-4 shrink-0" />
                  <span className="truncate">
                    {issue.filePath}
                    {issue.lineStart
                      ? `:${issue.lineStart}${issue.lineEnd ? `-${issue.lineEnd}` : ""}`
                      : ""}
                  </span>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleCopyPath}
                  className="h-7 gap-1.5 px-2 text-xs"
                >
                  {copiedPath ? (
                    <Check className="text-success size-3" />
                  ) : (
                    <Copy className="size-3" />
                  )}
                  <span>{copiedPath ? "Copied" : "Copy path"}</span>
                </Button>
              </div>

              {/* 3. What's wrong */}
              <div className="space-y-1.5">
                <h4 className="text-muted-foreground text-xs font-semibold tracking-wider uppercase">
                  What's wrong
                </h4>
                <p className="text-foreground text-sm leading-relaxed">{issue.explanation}</p>
              </div>

              {/* 4. Why it matters */}
              <div className="space-y-1.5">
                <h4 className="text-muted-foreground text-xs font-semibold tracking-wider uppercase">
                  Why it matters
                </h4>
                <p className="text-muted-foreground text-sm leading-relaxed">{issue.impact}</p>
              </div>

              {/* 5. Category Details from Meta */}
              {issue.meta && (
                <div className="bg-card space-y-3 rounded-lg border p-4">
                  <h4 className="text-muted-foreground text-xs font-semibold tracking-wider uppercase">
                    Context Metadata
                  </h4>

                  {/* Integration Metadata */}
                  {issue.meta.integration && (
                    <div className="grid grid-cols-1 gap-3 font-mono text-xs sm:grid-cols-2">
                      {issue.meta.integration.frontendRef && (
                        <div className="bg-muted/60 space-y-1 rounded p-2.5">
                          <span className="text-muted-foreground font-sans text-[10px] font-semibold uppercase">
                            Frontend Reference
                          </span>
                          <p className="text-foreground truncate font-bold">
                            {issue.meta.integration.frontendRef}
                          </p>
                        </div>
                      )}
                      {issue.meta.integration.backendRef && (
                        <div className="bg-muted/60 space-y-1 rounded p-2.5">
                          <span className="text-muted-foreground font-sans text-[10px] font-semibold uppercase">
                            Backend Reference
                          </span>
                          <p className="text-foreground truncate font-bold">
                            {issue.meta.integration.backendRef}
                          </p>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Security Metadata */}
                  {issue.meta.security && (
                    <div className="flex flex-wrap gap-2 text-xs">
                      {issue.meta.security.cwe && (
                        <Badge
                          variant="outline"
                          className="border-sev-critical bg-sev-critical/12 text-sev-critical font-mono"
                        >
                          {issue.meta.security.cwe}
                        </Badge>
                      )}
                      {issue.meta.security.owaspCategory && (
                        <Badge variant="secondary" className="font-mono text-xs">
                          {issue.meta.security.owaspCategory}
                        </Badge>
                      )}
                    </div>
                  )}

                  {/* Dependencies Metadata */}
                  {issue.meta.dependencies && (
                    <div className="grid grid-cols-3 gap-2 text-center font-mono text-xs">
                      <div className="bg-muted/60 rounded p-2">
                        <span className="text-muted-foreground block font-sans text-[10px] font-semibold uppercase">
                          Package
                        </span>
                        <span className="text-foreground block truncate font-bold">
                          {issue.meta.dependencies.packageName}
                        </span>
                      </div>
                      <div className="bg-muted/60 rounded p-2">
                        <span className="text-muted-foreground block font-sans text-[10px] font-semibold uppercase">
                          Current
                        </span>
                        <span className="text-sev-critical block font-bold">
                          {issue.meta.dependencies.currentVersion}
                        </span>
                      </div>
                      <div className="bg-muted/60 rounded p-2">
                        <span className="text-muted-foreground block font-sans text-[10px] font-semibold uppercase">
                          Latest
                        </span>
                        <span className="text-success block font-bold">
                          {issue.meta.dependencies.latestVersion}
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* 6. Suggested Fix */}
              <div className="border-primary/20 bg-primary/5 space-y-4 rounded-xl border p-4">
                <div className="text-primary flex items-center gap-2 text-sm font-semibold">
                  <Sparkles className="size-4" />
                  <span>Suggested Fix</span>
                </div>

                <p className="text-foreground text-xs leading-relaxed font-medium">
                  {issue.suggestedFix.summary}
                </p>

                {/* Steps */}
                <div className="space-y-2">
                  <span className="text-muted-foreground text-[11px] font-semibold tracking-wider uppercase">
                    Remediation Steps
                  </span>
                  <ol className="text-muted-foreground list-inside list-decimal space-y-1.5 text-xs">
                    {issue.suggestedFix.steps.map((step, idx) => (
                      <li key={idx} className="leading-relaxed">
                        <span className="text-foreground">{step}</span>
                      </li>
                    ))}
                  </ol>
                </div>

                {/* Before / After Code Blocks */}
                {issue.suggestedFix.codeBefore && issue.suggestedFix.codeAfter && (
                  <div className="space-y-3 pt-2">
                    {/* Before block */}
                    <div className="space-y-1">
                      <div className="text-sev-critical flex items-center justify-between text-[11px] font-semibold">
                        <span>Before</span>
                        <span className="font-mono text-[10px] opacity-75">{issue.filePath}</span>
                      </div>
                      <pre className="border-l-sev-critical border-border bg-muted text-foreground overflow-x-auto rounded-lg border-y border-r border-l-4 p-3 font-mono text-xs">
                        <code>{issue.suggestedFix.codeBefore}</code>
                      </pre>
                    </div>

                    {/* After block */}
                    <div className="space-y-1">
                      <div className="text-success flex items-center justify-between text-[11px] font-semibold">
                        <span>After (Resolved)</span>
                        <span className="font-mono text-[10px] opacity-75">{issue.filePath}</span>
                      </div>
                      <pre className="border-l-success border-border bg-muted text-foreground overflow-x-auto rounded-lg border-y border-r border-l-4 p-3 font-mono text-xs">
                        <code>{issue.suggestedFix.codeAfter}</code>
                      </pre>
                    </div>
                  </div>
                )}

                {/* One-Click Pull Request Action */}
                <div className="pt-2">
                  {prResult ? (
                    <div className="space-y-2 rounded-lg border border-purple-500/30 bg-purple-500/10 p-3.5">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <GitPullRequest className="size-4 shrink-0 text-purple-400" />
                          <span className="text-xs font-semibold text-purple-300">
                            Pull Request Opened on GitHub!
                          </span>
                        </div>
                        <span className="rounded bg-purple-500/20 px-2 py-0.5 font-mono text-[10px] text-purple-300">
                          PR #{prResult.prNumber}
                        </span>
                      </div>
                      <p className="text-muted-foreground text-[11px]">
                        Branch <span className="text-foreground font-mono">{prResult.branch}</span>{" "}
                        created with automated remediation patch.
                      </p>
                      <Button
                        asChild
                        size="sm"
                        className="h-8 w-full gap-1.5 bg-purple-600 text-xs font-semibold text-white hover:bg-purple-500"
                      >
                        <a href={prResult.prUrl} target="_blank" rel="noopener noreferrer">
                          <span>View Pull Request #{prResult.prNumber} on GitHub</span>
                          <ExternalLink className="size-3" />
                        </a>
                      </Button>
                    </div>
                  ) : (
                    <Button
                      onClick={handleCreatePr}
                      disabled={creatingPr}
                      className="h-9 w-full gap-2 bg-gradient-to-r from-purple-600 to-indigo-600 text-xs font-semibold text-white shadow-sm hover:from-purple-500 hover:to-indigo-500"
                    >
                      {creatingPr ? (
                        <>
                          <Loader2 className="size-3.5 animate-spin" />
                          <span>Creating Branch & Pull Request...</span>
                        </>
                      ) : (
                        <>
                          <GitPullRequest className="size-3.5" />
                          <span>Create GitHub PR with Fix</span>
                        </>
                      )}
                    </Button>
                  )}
                </div>
              </div>
            </>
          )}
        </div>

        {/* 7. Sticky Actions Footer */}
        {issue && (
          <div className="bg-background flex min-w-0 flex-col gap-3 border-t p-4 shadow-lg sm:flex-row sm:items-center sm:justify-between sm:px-6">
            {/* Copy prompt button */}
            <Button
              variant="outline"
              size="sm"
              onClick={handleCopyAiPrompt}
              className="w-full gap-2 text-xs font-medium sm:w-auto"
              aria-live="polite"
            >
              {copiedPrompt ? (
                <>
                  <Check className="text-success size-3.5" />
                  <span>Prompt Copied!</span>
                </>
              ) : (
                <>
                  <Copy className="size-3.5" />
                  <span>Copy fix as AI prompt</span>
                </>
              )}
            </Button>

            {/* Status change actions */}
            <ButtonRow align="end" className="w-full sm:w-auto">
              {issue.status === "open" ? (
                <>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleUpdateStatus("ignored")}
                    className="text-muted-foreground hover:text-foreground text-xs"
                  >
                    <EyeOff className="mr-1.5 size-3.5" />
                    Ignore
                  </Button>
                  <Button
                    size="sm"
                    variant="brand"
                    onClick={() => handleUpdateStatus("resolved")}
                    className="gap-1.5 text-xs font-semibold"
                  >
                    <CheckCircle2 className="size-3.5" />
                    Mark as resolved
                  </Button>
                </>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleUpdateStatus("open")}
                  className="w-full gap-1.5 text-xs sm:w-auto"
                >
                  <RotateCcw className="size-3.5" />
                  Reopen Issue
                </Button>
              )}
            </ButtonRow>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
