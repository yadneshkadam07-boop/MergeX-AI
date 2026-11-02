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
import { Package } from "lucide-react";

export function ProjectDependencies() {
  const { project } = useProject();
  useDocumentTitle("Dependencies", project.name);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();

  const loadIssues = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getIssues(project.id, "dependencies");
      setIssues(data);
    } catch (err) {
      console.error("Failed to load dependency issues:", err);
      setError(err instanceof Error ? err.message : "Failed to load dependency diagnostics.");
    } finally {
      setLoading(false);
    }
  }, [project.id]);

  useEffect(() => {
    void loadIssues();
  }, [loadIssues]);

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
        const matchesPackage = issue.meta?.dependencies?.packageName
          .toLowerCase()
          .includes(searchQuery);
        if (!matchesTitle && !matchesFile && !matchesPackage) return false;
      }
      return true;
    });
  }, [issues, searchQuery, selectedSeverities, statusFilter]);

  // Summary strip statistics
  const summary = useMemo(() => {
    const totalFlagged = issues.length;
    const withCve = issues.filter((i) => i.meta?.dependencies?.cve).length;
    const outdated = issues.filter(
      (i) =>
        i.meta?.dependencies &&
        i.meta.dependencies.currentVersion !== i.meta.dependencies.latestVersion,
    ).length;

    return { totalFlagged, withCve, outdated };
  }, [issues]);

  const handleSelectIssue = (issue: Issue) => {
    const next = new URLSearchParams(searchParams);
    next.set("issue", issue.id);
    setSearchParams(next, { replace: true });
  };

  return (
    <div className="space-y-6">
      {/* Intro & Summary Strip */}
      <div className="space-y-3">
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <Package className="text-brand-secondary size-5" />
            <h2 className="text-foreground text-xl font-bold tracking-tight">
              Dependencies & Third-Party Packages
            </h2>
          </div>
          <p className="text-muted-foreground text-xs leading-relaxed">
            Evaluates software bill of materials (SBOM), checks for known CVE security advisories,
            and flags deprecated or bloated libraries.
          </p>
        </div>

        {/* Dependency Summary Strip */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Card interactive className="bg-card/60 border">
            <CardContent className="flex items-center justify-between p-3">
              <span className="text-muted-foreground text-xs font-medium">
                Total Flagged Packages
              </span>
              <span className="text-foreground font-mono text-base font-bold">
                {summary.totalFlagged}
              </span>
            </CardContent>
          </Card>
          <Card interactive className="bg-card/60 border">
            <CardContent className="flex items-center justify-between p-3">
              <span className="text-muted-foreground text-xs font-medium">
                Known CVE Advisories
              </span>
              <span className="text-sev-critical font-mono text-base font-bold">
                {summary.withCve}
              </span>
            </CardContent>
          </Card>
          <Card interactive className="bg-card/60 border">
            <CardContent className="flex items-center justify-between p-3">
              <span className="text-muted-foreground text-xs font-medium">Outdated Releases</span>
              <span className="text-sev-high font-mono text-base font-bold">
                {summary.outdated}
              </span>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Filters */}
      <IssueFilters totalCount={issues.length} filteredCount={filteredIssues.length} />

      {error ? (
        <ErrorState title="Failed to load dependency issues" message={error} onRetry={loadIssues} />
      ) : (
        <IssueTable
          issues={filteredIssues}
          loading={loading}
          onSelect={handleSelectIssue}
          extraHeaderLabel="Package & CVE"
          renderExtraCell={(issue) => {
            if (!issue.meta?.dependencies)
              return <span className="text-muted-foreground text-xs">—</span>;
            const { packageName, currentVersion, latestVersion, cve } = issue.meta.dependencies;
            return (
              <div className="max-w-xs space-y-1 font-mono text-[11px]">
                <div className="flex items-center gap-1.5 truncate">
                  <span className="text-foreground font-bold">{packageName}</span>
                  <span className="text-muted-foreground font-normal">
                    ({currentVersion} → {latestVersion})
                  </span>
                </div>
                {cve && (
                  <Badge
                    variant="outline"
                    className="border-sev-critical bg-sev-critical/12 text-sev-critical px-1.5 py-0 text-[10px]"
                  >
                    {cve}
                  </Badge>
                )}
              </div>
            );
          }}
          emptyTitle="No dependency risks found"
          emptyDescription="All packages are pinned, up to date, and free of known vulnerability advisories."
        />
      )}
    </div>
  );
}
