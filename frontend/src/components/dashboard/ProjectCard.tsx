import { Link } from "react-router-dom";
import type { Project } from "@/types/project";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { HealthScoreBadge } from "@/components/shared/HealthScoreBadge";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { formatRelativeTime } from "@/lib/utils";
import { GitBranch, Clock } from "lucide-react";

interface ProjectCardProps {
  project: Project;
}

export function ProjectCard({ project }: ProjectCardProps) {
  const { issueCounts } = project;

  return (
    <Link
      to={`/project/${project.id}`}
      className="group focus-visible:ring-ring block w-full min-w-0 rounded-xl focus:outline-hidden focus-visible:ring-2"
    >
      <Card interactive className="bg-card h-full w-full min-w-0 gap-0 overflow-hidden border p-0">
        <CardHeader className="w-full min-w-0 p-5 pb-3">
          <div className="flex w-full min-w-0 items-start justify-between gap-3">
            <div className="min-w-0 flex-1 space-y-1">
              <h3 className="text-foreground group-hover:text-primary truncate text-base font-semibold transition-colors">
                {project.name}
              </h3>
              <p className="text-muted-foreground flex items-center gap-1.5 truncate text-xs">
                <GitBranch className="size-3.5 shrink-0" />
                <span className="truncate">
                  {project.owner}/{project.name}
                </span>
              </p>
            </div>
            <StatusBadge status={project.status} className="shrink-0" />
          </div>
        </CardHeader>

        <CardContent className="w-full min-w-0 space-y-4 p-5 pt-1">
          {/* Tech stack chips */}
          <div className="flex min-h-[1.5rem] flex-wrap gap-1.5">
            {project.stack.map((tech) => (
              <Badge
                key={tech}
                variant="secondary"
                className="bg-muted/70 text-muted-foreground px-2 py-0.5 text-[11px] font-normal"
              >
                {tech}
              </Badge>
            ))}
          </div>

          {/* Health score and metrics */}
          <div className="flex items-center justify-between border-t border-dashed pt-3">
            <span className="text-muted-foreground text-xs font-medium">Health Score</span>
            {project.status === "analyzing" ? (
              <span className="text-muted-foreground font-mono text-xs italic">Evaluating...</span>
            ) : (
              <HealthScoreBadge score={project.healthScore} className="shrink-0" />
            )}
          </div>

          {/* 4 category issue breakdown numbers */}
          <div className="bg-muted/40 grid grid-cols-4 gap-1.5 rounded-lg border p-2 text-center">
            <div className="min-w-0 space-y-0.5">
              <div className="text-foreground font-mono text-xs font-bold">
                {issueCounts.integration}
              </div>
              <div className="text-muted-foreground truncate text-[10px]">Integr.</div>
            </div>
            <div className="min-w-0 space-y-0.5">
              <div className="text-foreground font-mono text-xs font-bold">
                {issueCounts.security}
              </div>
              <div className="text-muted-foreground truncate text-[10px]">Secur.</div>
            </div>
            <div className="min-w-0 space-y-0.5">
              <div className="text-foreground font-mono text-xs font-bold">
                {issueCounts.dependencies}
              </div>
              <div className="text-muted-foreground truncate text-[10px]">Dep.</div>
            </div>
            <div className="min-w-0 space-y-0.5">
              <div className="text-foreground font-mono text-xs font-bold">
                {issueCounts.deployment}
              </div>
              <div className="text-muted-foreground truncate text-[10px]">Deploy</div>
            </div>
          </div>

          {/* Last scanned timestamp */}
          <div className="text-muted-foreground flex items-center gap-1.5 pt-1 text-[11px]">
            <Clock className="size-3 shrink-0" />
            <span className="truncate">Scanned {formatRelativeTime(project.lastScannedAt)}</span>
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}
