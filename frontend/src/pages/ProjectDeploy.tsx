import { useEffect, useState, useMemo, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { useProject } from "@/hooks/use-project";
import type { Issue, ChecklistItem } from "@/types/issue";
import { getIssues, getDeployChecklist } from "@/lib/api";
import { IssueFilters } from "@/components/issues/IssueFilters";
import { IssueTable } from "@/components/issues/IssueTable";
import { ErrorState } from "@/components/shared/ErrorState";
import { useDocumentTitle } from "@/hooks/use-document-title";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AlertTriangle, CheckCircle2, Rocket, XCircle } from "lucide-react";

export function ProjectDeploy() {
  const { project } = useProject();
  useDocumentTitle("Deploy Check", project.name);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [checklist, setChecklist] = useState<ChecklistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [issueData, checklistData] = await Promise.all([
        getIssues(project.id, "deployment"),
        getDeployChecklist(project.id),
      ]);
      setIssues(issueData);
      setChecklist(checklistData);
    } catch (err) {
      console.error("Failed to load deploy data:", err);
      setError(err instanceof Error ? err.message : "Failed to load deployment verification.");
    } finally {
      setLoading(false);
    }
  }, [project.id]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const searchQuery = searchParams.get("q")?.toLowerCase() || "";
  const severityParam = searchParams.get("severity");
  const selectedSeverities = useMemo(() => {
    return severityParam ? severityParam.split(",").filter(Boolean) : [];
  }, [severityParam]);
  const statusFilter = searchParams.get("status") || "open";

  const filteredIssues = useMemo(() => {
    return issues.filter((issue) => {
      if (statusFilter !== "all" && issue.status !== statusFilter) return false;
      if (selectedSeverities.length > 0 && !selectedSeverities.includes(issue.severity))
        return false;
      if (searchQuery) {
        const matchesTitle = issue.title.toLowerCase().includes(searchQuery);
        const matchesFile = issue.filePath.toLowerCase().includes(searchQuery);
        const matchesDesc = issue.shortDescription.toLowerCase().includes(searchQuery);
        if (!matchesTitle && !matchesFile && !matchesDesc) return false;
      }
      return true;
    });
  }, [issues, searchQuery, selectedSeverities, statusFilter]);

  // Overall readiness verdict based on checklist status
  const verdict = useMemo(() => {
    const fails = checklist.filter((c) => c.status === "fail").length;
    const warns = checklist.filter((c) => c.status === "warn").length;

    if (fails > 0) {
      return {
        label: `Not ready: ${fails} blocking issue${fails === 1 ? "" : "s"}`,
        variant: "border-sev-critical bg-sev-critical/12 text-sev-critical",
        description:
          "Critical container, routing, or environment misconfigurations prevent successful deployment.",
      };
    }
    if (warns > 0) {
      return {
        label: `Ready with warnings (${warns} non-blocking)`,
        variant: "border-sev-medium bg-sev-medium/12 text-sev-medium",
        description:
          "Application can be deployed, but minor performance or logging gaps were detected.",
      };
    }
    return {
      label: "Production Ready",
      variant: "border-success bg-success/12 text-success",
      description:
        "All container, environment variable, and health check criteria passed verification.",
    };
  }, [checklist]);

  const handleSelectIssue = (issue: Issue) => {
    const next = new URLSearchParams(searchParams);
    next.set("issue", issue.id);
    setSearchParams(next, { replace: true });
  };

  const renderChecklistStatus = (status: ChecklistItem["status"]) => {
    switch (status) {
      case "pass":
        return (
          <div className="text-success flex shrink-0 items-center gap-1.5 text-xs font-semibold">
            <CheckCircle2 className="size-4" />
            <span>Pass</span>
          </div>
        );
      case "warn":
        return (
          <div className="text-sev-medium flex shrink-0 items-center gap-1.5 text-xs font-semibold">
            <AlertTriangle className="size-4" />
            <span>Warning</span>
          </div>
        );
      case "fail":
        return (
          <div className="text-sev-critical flex shrink-0 items-center gap-1.5 text-xs font-semibold">
            <XCircle className="size-4" />
            <span>Fail</span>
          </div>
        );
    }
  };

  return (
    <div className="space-y-6">
      {/* Intro & Readiness Verdict */}
      <div className="space-y-3">
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <Rocket className="text-brand-secondary size-5" />
            <h2 className="text-foreground text-xl font-bold tracking-tight">
              Deployment Readiness & Environment Parity
            </h2>
          </div>
          <p className="text-muted-foreground text-xs leading-relaxed">
            Verifies container Dockerfiles, environment variables, SSL termination, and automated
            orchestrator readiness probes.
          </p>
        </div>

        {/* Verdict Banner */}
        <Card className="bg-card border shadow-xs">
          <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground text-xs font-semibold tracking-wider uppercase">
                  Deployment Verdict:
                </span>
                <Badge variant="outline" className={`text-xs font-semibold ${verdict.variant}`}>
                  {verdict.label}
                </Badge>
              </div>
              <p className="text-muted-foreground text-xs">{verdict.description}</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Deployment Readiness Checklist */}
      <Card className="bg-card border shadow-xs">
        <CardHeader className="border-b pb-3">
          <CardTitle className="text-sm font-semibold">
            Pre-Deployment Verification Checklist
          </CardTitle>
        </CardHeader>
        <CardContent className="divide-border/60 divide-y p-0">
          {checklist.map((item) => (
            <div
              key={item.id}
              className="hover:bg-muted/30 flex flex-col justify-between gap-2 p-3.5 text-xs transition-colors sm:flex-row sm:items-center"
            >
              <div className="space-y-0.5">
                <span className="text-foreground font-semibold">{item.label}</span>
                <p className="text-muted-foreground">{item.detail}</p>
              </div>
              <div className="self-end sm:self-center">{renderChecklistStatus(item.status)}</div>
            </div>
          ))}
        </CardContent>
      </Card>

      {error ? (
        <ErrorState
          title="Failed to load deployment checklist"
          message={error}
          onRetry={loadData}
        />
      ) : (
        <>
          {/* Deployment Issues Section */}
          <div className="space-y-4 pt-2">
            <div className="flex items-center justify-between">
              <h3 className="text-foreground text-base font-semibold">
                Deployment Configuration Issues
              </h3>
              <span className="text-muted-foreground font-mono text-xs">{issues.length} total</span>
            </div>

            <IssueFilters totalCount={issues.length} filteredCount={filteredIssues.length} />

            <IssueTable
              issues={filteredIssues}
              loading={loading}
              onSelect={handleSelectIssue}
              emptyTitle="No deployment blockers found"
              emptyDescription="Container files and environment manifests are ready for production release."
            />
          </div>
        </>
      )}
    </div>
  );
}
