import { useEffect, useState, useMemo } from "react";
import { Link } from "react-router-dom";
import type { Project, ProjectStatus } from "@/types/project";
import { getProjects } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { StatCard } from "@/components/shared/StatCard";
import { ProjectCard } from "@/components/dashboard/ProjectCard";
import { DashboardSkeleton } from "@/components/dashboard/DashboardSkeleton";
import { DashboardEmptyState } from "@/components/dashboard/DashboardEmptyState";
import { ErrorState } from "@/components/shared/ErrorState";
import { useDocumentTitle } from "@/hooks/use-document-title";
import { Activity, AlertTriangle, FolderGit2, PlusCircle, Search } from "lucide-react";

export function Dashboard() {
  useDocumentTitle("Dashboard");
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getProjects();
      setProjects(data);
    } catch (err) {
      console.error("Failed to load projects:", err);
      setError(err instanceof Error ? err.message : "Failed to load projects. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadData();
  }, []);

  // Summary statistics
  const stats = useMemo(() => {
    const total = projects.length;
    const completedProjects = projects.filter((p) => p.status === "completed");
    const avgScore =
      completedProjects.length > 0
        ? Math.round(
            completedProjects.reduce((acc, p) => acc + p.healthScore, 0) / completedProjects.length,
          )
        : 0;

    const totalOpenIssues = projects.reduce((acc, p) => {
      const counts = p.issueCounts;
      return acc + counts.integration + counts.security + counts.dependencies + counts.deployment;
    }, 0);

    return { total, avgScore, totalOpenIssues };
  }, [projects]);

  // Filtered projects
  const filteredProjects = useMemo(() => {
    return projects.filter((p) => {
      const matchesSearch =
        p.name.toLowerCase().includes(search.toLowerCase()) ||
        p.owner.toLowerCase().includes(search.toLowerCase()) ||
        p.stack.some((tech) => tech.toLowerCase().includes(search.toLowerCase()));

      const matchesStatus =
        statusFilter === "all" ? true : p.status === (statusFilter as ProjectStatus);

      return matchesSearch && matchesStatus;
    });
  }, [projects, search, statusFilter]);

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div className="flex min-w-0 flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0 flex-1">
          <h1 className="text-foreground text-2xl font-bold tracking-tight break-words sm:text-3xl">
            Projects
          </h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Monitor and triage architectural diagnostics across your AI-assisted repositories.
          </p>
        </div>
        <Button
          asChild
          size="default"
          className="shrink-0 gap-2 self-start font-semibold shadow-xs sm:self-auto"
        >
          <Link to="/analyze">
            <PlusCircle className="size-4" />
            <span>New analysis</span>
          </Link>
        </Button>
      </div>

      {loading ? (
        <DashboardSkeleton />
      ) : error ? (
        <ErrorState title="Failed to load projects" message={error} onRetry={loadData} />
      ) : (
        <>
          {/* Summary Row */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <StatCard
              title="Total Projects"
              value={stats.total}
              subtitle="Active monitored codebases"
              icon={<FolderGit2 className="text-brand-secondary size-5" />}
            />
            <StatCard
              title="Average Health"
              value={`${stats.avgScore}/100`}
              subtitle="Across completed scans"
              icon={<Activity className="text-success size-5" />}
            />
            <StatCard
              title="Open Issues"
              value={stats.totalOpenIssues}
              subtitle="Integration, security & deploy"
              icon={<AlertTriangle className="text-sev-medium size-5" />}
            />
          </div>

          {/* Search & Status Filters */}
          <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="relative w-full max-w-sm min-w-0 flex-1">
              <Search className="text-muted-foreground absolute top-1/2 left-3 size-4 -translate-y-1/2" />
              <Input
                placeholder="Search projects or tech stack..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="h-10 w-full pl-9"
              />
            </div>

            <div className="flex w-full items-center gap-2 sm:w-auto">
              <span className="text-muted-foreground hidden shrink-0 text-xs font-medium sm:inline">
                Status:
              </span>
              <Select value={statusFilter} onValueChange={setStatusFilter}>
                <SelectTrigger className="h-10 w-full sm:w-40">
                  <SelectValue placeholder="All Statuses" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Statuses</SelectItem>
                  <SelectItem value="completed">Completed</SelectItem>
                  <SelectItem value="analyzing">Analyzing</SelectItem>
                  <SelectItem value="failed">Failed</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Project Cards Grid or Empty State */}
          {projects.length === 0 ? (
            <DashboardEmptyState />
          ) : filteredProjects.length === 0 ? (
            <DashboardEmptyState
              isFiltered
              onClearFilters={() => {
                setSearch("");
                setStatusFilter("all");
              }}
            />
          ) : (
            <div className="grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-3">
              {filteredProjects.map((project) => (
                <ProjectCard key={project.id} project={project} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
