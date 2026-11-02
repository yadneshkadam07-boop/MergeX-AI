import { useEffect, useState, useMemo, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { useProject } from "@/hooks/use-project";
import type { Issue } from "@/types/issue";
import { getIssues } from "@/lib/api";
import { IssueFilters } from "@/components/issues/IssueFilters";
import { IssueTable } from "@/components/issues/IssueTable";
import { ErrorState } from "@/components/shared/ErrorState";
import { useDocumentTitle } from "@/hooks/use-document-title";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ShieldAlert } from "lucide-react";

export function ProjectSecurity() {
  const { project } = useProject();
  useDocumentTitle("Security", project.name);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();

  const loadIssues = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getIssues(project.id, "security");
      setIssues(data);
    } catch (err) {
      console.error("Failed to load security issues:", err);
      setError(err instanceof Error ? err.message : "Failed to load security diagnostics.");
    } finally {
      setLoading(false);
    }
  }, [project.id]);

  useEffect(() => {
    void loadIssues();
  }, [loadIssues]);

  // Client-side filtering driven by URL search params
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

  const severityBreakdown = useMemo(() => {
    return {
      critical: issues.filter((i) => i.severity === "critical" && i.status === "open").length,
      high: issues.filter((i) => i.severity === "high" && i.status === "open").length,
      medium: issues.filter((i) => i.severity === "medium" && i.status === "open").length,
      low: issues.filter((i) => i.severity === "low" && i.status === "open").length,
    };
  }, [issues]);

  const handleSelectIssue = (issue: Issue) => {
    const next = new URLSearchParams(searchParams);
    next.set("issue", issue.id);
    setSearchParams(next, { replace: true });
  };

  return (
    <div className="space-y-6">
      {/* Intro & Severity Summary Strip */}
      <div className="space-y-3">
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <ShieldAlert className="text-sev-critical size-5" />
            <h2 className="text-foreground text-xl font-bold tracking-tight">
              Security Vulnerabilities & Secrets
            </h2>
          </div>
          <p className="text-muted-foreground text-xs leading-relaxed">
            Audits source code for hardcoded secrets, wildcard CORS configurations, authentication
            bypass risks, and OWASP Top 10 vulnerabilities.
          </p>
        </div>

        {/* Severity Strip */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Card interactive className="bg-card/60 border">
            <CardContent className="flex items-center justify-between p-3">
              <span className="text-muted-foreground text-xs font-medium">Critical</span>
              <span className="text-sev-critical font-mono text-base font-bold">
                {severityBreakdown.critical}
              </span>
            </CardContent>
          </Card>
          <Card interactive className="bg-card/60 border">
            <CardContent className="flex items-center justify-between p-3">
              <span className="text-muted-foreground text-xs font-medium">High</span>
              <span className="text-sev-high font-mono text-base font-bold">
                {severityBreakdown.high}
              </span>
            </CardContent>
          </Card>
          <Card interactive className="bg-card/60 border">
            <CardContent className="flex items-center justify-between p-3">
              <span className="text-muted-foreground text-xs font-medium">Medium</span>
              <span className="text-sev-medium font-mono text-base font-bold">
                {severityBreakdown.medium}
              </span>
            </CardContent>
          </Card>
          <Card interactive className="bg-card/60 border">
            <CardContent className="flex items-center justify-between p-3">
              <span className="text-muted-foreground text-xs font-medium">Low</span>
              <span className="text-sev-low font-mono text-base font-bold">
                {severityBreakdown.low}
              </span>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Filters */}
      <IssueFilters totalCount={issues.length} filteredCount={filteredIssues.length} />

      {error ? (
        <ErrorState title="Failed to load security issues" message={error} onRetry={loadIssues} />
      ) : (
        <IssueTable
          issues={filteredIssues}
          loading={loading}
          onSelect={handleSelectIssue}
          extraHeaderLabel="CWE / OWASP"
          renderExtraCell={(issue) => {
            if (!issue.meta?.security?.cwe && !issue.meta?.security?.owaspCategory) {
              return <span className="text-muted-foreground text-xs">—</span>;
            }
            return (
              <div className="max-w-xs space-y-1">
                {issue.meta.security.cwe && (
                  <Badge
                    variant="outline"
                    className="border-sev-critical bg-sev-critical/12 text-sev-critical block truncate font-mono text-[10px]"
                  >
                    {issue.meta.security.cwe.split(":")[0]}
                  </Badge>
                )}
                {issue.meta.security.owaspCategory && (
                  <span className="text-muted-foreground block truncate font-mono text-[10px]">
                    {issue.meta.security.owaspCategory.split("-")[0]}
                  </span>
                )}
              </div>
            );
          }}
          emptyTitle="No security vulnerabilities found"
          emptyDescription="No exposed credentials or unvalidated authorization vectors were detected."
        />
      )}
    </div>
  );
}
