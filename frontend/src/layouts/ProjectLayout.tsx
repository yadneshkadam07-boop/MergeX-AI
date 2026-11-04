import { useState, useEffect, useRef, useCallback } from "react";
import { Link, Outlet, useParams } from "react-router-dom";
import type { Project } from "@/types/project";
import { getProject, rescanProject } from "@/lib/api";
import { ProjectTabs } from "@/components/project/ProjectTabs";
import { IssueDetailSheet } from "@/components/issues/IssueDetailSheet";
import { HealthScoreBadge } from "@/components/shared/HealthScoreBadge";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { ErrorState } from "@/components/shared/ErrorState";
import { EmptyState } from "@/components/shared/EmptyState";
import { useDocumentTitle } from "@/hooks/use-document-title";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ButtonRow } from "@/components/ui/button-row";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  AlertOctagon,
  ArrowLeft,
  Download,
  ExternalLink,
  FolderX,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { exportReportMarkdown } from "@/lib/export-report";

export function ProjectLayout() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rescanning, setRescanning] = useState(false);
  const [exportingReport, setExportingReport] = useState(false);

  useDocumentTitle(project?.name, "Project");

  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const isMountedRef = useRef(true);

  const loadProject = useCallback(
    async (silent = false) => {
      if (!id) return;
      if (!silent) setLoading(true);
      setError(null);
      try {
        const data = await getProject(id);
        if (isMountedRef.current) {
          setProject(data);
          if (!silent) setLoading(false);
        }
      } catch (err) {
        console.error("Failed to fetch project:", err);
        if (isMountedRef.current) {
          setError(err instanceof Error ? err.message : "Failed to fetch project diagnostics.");
          if (!silent) setLoading(false);
        }
      }
    },
    [id],
  );

  useEffect(() => {
    isMountedRef.current = true;
    void loadProject();

    return () => {
      isMountedRef.current = false;
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, [loadProject]);

  // Polling logic when project status is "analyzing"
  useEffect(() => {
    if (project?.status === "analyzing") {
      if (!pollIntervalRef.current) {
        pollIntervalRef.current = setInterval(() => {
          void (async () => {
            if (!id) return;
            const updated = await getProject(id);
            if (isMountedRef.current && updated) {
              setProject(updated);
              if (updated.status !== "analyzing") {
                if (pollIntervalRef.current) {
                  clearInterval(pollIntervalRef.current);
                  pollIntervalRef.current = null;
                }
              }
            }
          })();
        }, 2000);
      }
    } else {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    }

    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };
  }, [project?.status, id]);

  const handleRescan = async () => {
    if (!id || rescanning) return;
    setRescanning(true);
    toast.info("Rescan initiated. Multi-agent diagnostic running...");
    try {
      const updated = await rescanProject(id);
      if (isMountedRef.current) {
        setProject(updated);
        setRescanning(false);
        toast.success("Repository re-scanned successfully!");
      }
    } catch (err) {
      console.error("Failed to rescan project:", err);
      if (isMountedRef.current) setRescanning(false);
      toast.error("Failed to rescan project. Please try again.");
    }
  };

  const handleExportReport = async () => {
    if (!project) return;
    setExportingReport(true);
    try {
      await exportReportMarkdown(project.id, project.name);
    } finally {
      if (isMountedRef.current) {
        setExportingReport(false);
      }
    }
  };

  if (loading) {
    return (
      <div className="animate-pulse space-y-6">
        <Skeleton className="h-4 w-32" />
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="space-y-2">
            <Skeleton className="h-8 w-64" />
            <Skeleton className="h-4 w-48" />
          </div>
          <div className="flex gap-2">
            <Skeleton className="h-9 w-24" />
            <Skeleton className="h-9 w-28" />
          </div>
        </div>
        <Skeleton className="h-10 w-full rounded-md" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <div>
          <Link
            to="/dashboard"
            className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 text-xs font-medium transition-colors"
          >
            <ArrowLeft className="size-3.5" />
            <span>Back to Projects</span>
          </Link>
        </div>
        <ErrorState title="Failed to load project" message={error} onRetry={() => loadProject()} />
      </div>
    );
  }

  if (!project) {
    return (
      <div className="space-y-6">
        <div>
          <Link
            to="/dashboard"
            className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 text-xs font-medium transition-colors"
          >
            <ArrowLeft className="size-3.5" />
            <span>Back to Projects</span>
          </Link>
        </div>
        <EmptyState
          icon={FolderX}
          title="Project not found"
          description="The requested project ID doesn't exist in local storage or has been removed."
          action={
            <Button
              asChild
              size="default"
              variant="outline"
              className="gap-2 text-xs font-semibold"
            >
              <Link to="/dashboard">
                <ArrowLeft className="size-3.5" />
                <span>Back to Dashboard</span>
              </Link>
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Back link */}
      <div>
        <Link
          to="/dashboard"
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 text-xs font-medium transition-colors"
        >
          <ArrowLeft className="size-3.5" />
          <span>Back to Projects</span>
        </Link>
      </div>

      {/* Project Header */}
      <div className="flex min-w-0 flex-col gap-4 border-b pb-6 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0 flex-1 space-y-2.5">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-foreground text-2xl font-extrabold tracking-tight break-words sm:text-3xl">
              {project.name}
            </h1>
            <StatusBadge status={project.status} />
            {project.status !== "analyzing" && (
              <HealthScoreBadge score={project.healthScore} showLabel />
            )}
          </div>

          <div className="text-muted-foreground flex flex-wrap items-center gap-3 text-xs">
            <span className="font-mono break-all">
              {project.owner}/{project.name}
            </span>
            <span>·</span>
            <div className="flex flex-wrap gap-1.5">
              {project.stack.map((tech) => (
                <Badge
                  key={tech}
                  variant="secondary"
                  className="bg-muted/80 text-muted-foreground px-2 py-0 text-[10px] font-normal"
                >
                  {tech}
                </Badge>
              ))}
            </div>
          </div>
        </div>

        {/* Action Controls */}
        <ButtonRow align="start" className="shrink-0 lg:justify-end">
          <Button
            variant="outline"
            size="sm"
            onClick={handleExportReport}
            disabled={exportingReport || project.status === "analyzing"}
            className="gap-1.5 text-xs font-semibold"
          >
            {exportingReport ? (
              <>
                <Loader2 className="size-3.5 animate-spin" />
                <span>Exporting...</span>
              </>
            ) : (
              <>
                <Download className="size-3.5" />
                <span>Export Report</span>
              </>
            )}
          </Button>

          <Button asChild variant="outline" size="sm" className="gap-1.5 text-xs">
            <a
              href={project.repoUrl}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`View ${project.name} repository on GitHub`}
            >
              <span>View on GitHub</span>
              <ExternalLink className="size-3.5" />
            </a>
          </Button>

          <Button
            size="sm"
            onClick={handleRescan}
            disabled={rescanning || project.status === "analyzing"}
            className="gap-2 text-xs font-semibold"
          >
            {rescanning || project.status === "analyzing" ? (
              <>
                <Loader2 className="size-3.5 animate-spin" />
                <span>Re-scanning...</span>
              </>
            ) : (
              <>
                <RefreshCw className="size-3.5" />
                <span>Re-scan</span>
              </>
            )}
          </Button>
        </ButtonRow>
      </div>

      {/* Status Banners */}
      {project.status === "analyzing" && (
        <div
          role="status"
          aria-live="polite"
          className="border-brand-secondary/30 bg-brand-secondary/10 text-brand-secondary flex items-center gap-3 rounded-lg border p-3 text-xs"
        >
          <Loader2 className="text-brand-secondary size-4 shrink-0 animate-spin" />
          <span>
            Deep multi-agent inspection in progress. Polling diagnostics stream every 2 seconds...
          </span>
        </div>
      )}

      {project.status === "failed" && (
        <div className="border-sev-critical/30 bg-sev-critical/10 text-sev-critical flex flex-col justify-between gap-3 rounded-lg border p-3.5 text-xs sm:flex-row sm:items-center">
          <div className="flex items-center gap-2.5">
            <AlertOctagon className="text-sev-critical size-4 shrink-0" />
            <span>
              The previous analysis run failed due to critical syntax or container
              misconfigurations.
            </span>
          </div>
          <Button
            size="sm"
            variant="destructive"
            onClick={handleRescan}
            disabled={rescanning}
            className="h-7 shrink-0 self-end px-3 text-xs sm:self-auto"
          >
            {rescanning ? "Retrying..." : "Retry Analysis"}
          </Button>
        </div>
      )}

      {/* Tab Navigation */}
      <ProjectTabs issueCounts={project.issueCounts} />

      {/* Nested Route Output */}
      <main className="pt-2">
        <Outlet context={{ project, refreshProject: () => loadProject(true) }} />
      </main>

      {/* Global Issue Detail Slide-Over */}
      <IssueDetailSheet projectId={project.id} onIssueUpdated={() => loadProject(true)} />
    </div>
  );
}
