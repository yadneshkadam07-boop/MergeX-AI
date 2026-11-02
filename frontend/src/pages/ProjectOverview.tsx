import { useProject } from "@/hooks/use-project";
import { ScoreRing } from "@/components/project/overview/ScoreRing";
import { SeverityBar } from "@/components/project/overview/SeverityBar";
import { CategoryCards } from "@/components/project/overview/CategoryCards";
import { PriorityIssuesList } from "@/components/project/overview/PriorityIssuesList";
import { ProjectInfoCards } from "@/components/project/overview/ProjectInfoCards";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useDocumentTitle } from "@/hooks/use-document-title";

export function ProjectOverview() {
  const { project } = useProject();
  useDocumentTitle("Overview", project.name);

  // If the project is in analyzing mode and hasn't received complete metrics yet
  if (project.status === "analyzing" && project.healthScore === 0) {
    return (
      <div className="animate-pulse space-y-6">
        <Card className="bg-card border">
          <CardContent className="flex flex-col items-center gap-8 p-6 md:flex-row">
            <Skeleton className="size-32 rounded-full" />
            <div className="w-full flex-1 space-y-3">
              <Skeleton className="h-6 w-3/4" />
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-4 w-1/2" />
            </div>
          </CardContent>
        </Card>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <Card key={i} className="bg-card border">
              <CardContent className="space-y-3 p-5">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-6 w-16" />
                <Skeleton className="h-2 w-full" />
              </CardContent>
            </Card>
          ))}
        </div>

        <Card className="bg-card border">
          <CardContent className="space-y-4 p-6">
            <Skeleton className="h-5 w-32" />
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* 1. Score + summary row */}
      <Card className="bg-card border shadow-xs">
        <CardContent className="flex flex-col items-center gap-8 p-6 md:flex-row">
          <ScoreRing score={project.healthScore} />
          <div className="w-full flex-1">
            <SeverityBar counts={project.severityCounts} />
          </div>
        </CardContent>
      </Card>

      {/* 2. Category cards (4 cards linking to tabs) */}
      <CategoryCards categoryScores={project.categoryScores} issueCounts={project.issueCounts} />

      {/* 3. Priority issues list */}
      <PriorityIssuesList issues={project.topIssues} />

      {/* 4. Two info cards side by side (Stack + Scan details) */}
      <ProjectInfoCards
        stack={project.stack}
        scanMeta={project.scanMeta}
        lastScannedAt={project.lastScannedAt}
      />
    </div>
  );
}
