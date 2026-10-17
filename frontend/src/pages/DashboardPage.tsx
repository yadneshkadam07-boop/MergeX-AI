import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Info, Network } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { analysisKeys, getReport, type ReportIssue } from "@/api/analyses";
import { ApiError } from "@/api/client";
import { AppShell } from "@/components/AppShell";
import { CategoryScores } from "@/components/CategoryScores";
import { IssueDrawer } from "@/components/IssueDrawer";
import { IssueTable } from "@/components/IssueTable";
import { ScoreGauge } from "@/components/ScoreGauge";
import { SeverityChart } from "@/components/SeverityChart";
import {
  CleanState,
  EmptyState,
  ErrorState,
  LoadingState,
  OfflineState,
} from "@/components/states";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CATEGORY_LABELS } from "@/lib/severity";
import { stackBadgesFrom } from "@/lib/stack";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground text-xs tracking-wide uppercase">{label}</dt>
      <dd className="text-sm font-medium tabular-nums">{value}</dd>
    </div>
  );
}

/**
 * The report.
 *
 * Everything on this page comes from one `/report` call. The caveats are
 * given the same prominence as the score, because a 100 from a project where
 * three checks could not run is not a 100.
 */
export function DashboardPage() {
  const { analysisId } = useParams<{ analysisId: string }>();
  const [selected, setSelected] = useState<ReportIssue | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const {
    data: report,
    error,
    isPending,
    refetch,
  } = useQuery({
    queryKey: analysisKeys.report(analysisId ?? ""),
    queryFn: () => getReport(analysisId as string),
    enabled: Boolean(analysisId),
  });

  const open = (issue: ReportIssue) => {
    setSelected(issue);
    setDrawerOpen(true);
  };

  if (isPending) {
    return (
      <AppShell>
        <LoadingState label="Loading report" />
      </AppShell>
    );
  }

  if (error) {
    // A TypeError from fetch means the request never reached the server;
    // an ApiError means it did and was refused. Different advice.
    return (
      <AppShell>
        {error instanceof ApiError ? (
          <ErrorState
            title={error.status === 404 ? "Analysis not found" : "Could not load the report"}
            message={error.message}
            onRetry={() => void refetch()}
          />
        ) : (
          <OfflineState onRetry={() => void refetch()} />
        )}
      </AppShell>
    );
  }

  if (report.status === "failed") {
    return (
      <AppShell className="max-w-3xl">
        <div className="space-y-4 py-6">
          <Alert variant="destructive">
            <AlertTriangle className="size-4" aria-hidden />
            <AlertTitle>This analysis failed</AlertTitle>
            <AlertDescription>
              {report.error_message ?? "The run stopped before producing a report."}
            </AlertDescription>
          </Alert>
          <Button asChild variant="outline">
            <Link to="/">
              <ArrowLeft className="size-4" aria-hidden />
              Import another project
            </Link>
          </Button>
        </div>
      </AppShell>
    );
  }

  if (report.status === "pending" || report.status === "running" || report.score === null) {
    return (
      <AppShell className="max-w-3xl">
        <EmptyState
          title="This analysis has not finished"
          description="The report appears once the run completes."
          action={
            <Button asChild>
              <Link to={`/analyses/${report.analysis_id}`}>Watch it run</Link>
            </Button>
          }
        />
      </AppShell>
    );
  }

  const { score } = report;
  const stackBadges = stackBadgesFrom(report.stack);
  const checkedSummary = Object.entries(report.counts)
    .filter(([, value]) => value > 0)
    .map(([key, value]) => `${value} ${key.replace(/_/g, " ")}`)
    .join(", ");

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-1">
            <h1 className="text-2xl font-semibold tracking-tight">{report.project_name}</h1>
            <p className="text-muted-foreground text-sm">
              {report.file_count ?? 0} files analysed
              {report.duration_ms !== null ? ` in ${(report.duration_ms / 1000).toFixed(1)}s` : ""}
              {report.commit_sha ? ` · ${report.commit_sha.slice(0, 7)}` : ""}
            </p>
          </div>
          <Button asChild variant="outline" size="sm">
            <Link to="/">
              <ArrowLeft className="size-4" aria-hidden />
              New analysis
            </Link>
          </Button>
        </div>

        {report.failed_groups.length > 0 ? (
          <Alert>
            <AlertTriangle className="size-4" aria-hidden />
            <AlertTitle>
              {report.failed_groups.length === 1
                ? "One category could not be analysed"
                : `${report.failed_groups.length} categories could not be analysed`}
            </AlertTitle>
            <AlertDescription>
              {report.failed_groups.map((group) => CATEGORY_LABELS[group]).join(", ")} failed to
              run. Those categories are unknown, not clean — the rest of the report is unaffected.
            </AlertDescription>
          </Alert>
        ) : null}

        <div className="grid gap-5 lg:grid-cols-3">
          <Card className="lg:col-span-1">
            <CardHeader>
              <CardTitle className="text-base">Health score</CardTitle>
              <CardDescription>
                100 minus 15 per critical, 8 per high, 3 per medium, 1 per low.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col items-center gap-4">
              <ScoreGauge
                score={score.score}
                isFloored={score.is_floored}
                caption={`${score.total_issues} issue${score.total_issues === 1 ? "" : "s"} across ${report.file_count ?? 0} files`}
              />
              {score.is_floored ? (
                <p className="text-muted-foreground text-center text-xs">
                  Deductions exceeded 100 and the score was clamped.
                </p>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">By category</CardTitle>
              <CardDescription>Each scored over its own issues.</CardDescription>
            </CardHeader>
            <CardContent>
              <CategoryScores score={score} failedGroups={report.failed_groups} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">By severity</CardTitle>
              <CardDescription>What the deductions are made of.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <SeverityChart counts={score.severity_counts} />
              <dl className="grid grid-cols-2 gap-3">
                <Stat
                  label="Explained by AI"
                  value={String(report.explanation_sources.gemini ?? 0)}
                />
                <Stat
                  label="From templates"
                  value={String(report.explanation_sources.template ?? 0)}
                />
              </dl>
            </CardContent>
          </Card>
        </div>

        <Tabs defaultValue="issues">
          <TabsList>
            <TabsTrigger value="issues">Issues ({report.issues.length})</TabsTrigger>
            <TabsTrigger value="coverage">What was checked</TabsTrigger>
            <TabsTrigger value="architecture">
              <Network className="size-4" aria-hidden />
              Architecture
            </TabsTrigger>
          </TabsList>

          <TabsContent value="issues" className="pt-4">
            {report.issues.length === 0 ? (
              <CleanState
                checked={
                  checkedSummary
                    ? `MergeX examined ${checkedSummary}.`
                    : "MergeX examined this project."
                }
              />
            ) : (
              <IssueTable
                issues={report.issues}
                onSelect={open}
                selectedId={drawerOpen ? selected?.id : undefined}
              />
            )}
          </TabsContent>

          <TabsContent value="coverage" className="space-y-5 pt-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Examined</CardTitle>
                <CardDescription>
                  The facts the rules compared. A rule with nothing to compare stays silent.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {Object.keys(report.counts).length === 0 ? (
                  <p className="text-muted-foreground text-sm">Nothing was recorded.</p>
                ) : (
                  <dl className="grid gap-4 sm:grid-cols-3">
                    {Object.entries(report.counts).map(([key, value]) => (
                      <Stat key={key} label={key.replace(/_/g, " ")} value={String(value)} />
                    ))}
                  </dl>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Caveats</CardTitle>
                <CardDescription>
                  &ldquo;We found nothing&rdquo; and &ldquo;we could not look&rdquo; are different
                  results.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {report.notes.length === 0 ? (
                  <p className="text-muted-foreground text-sm">
                    Every applicable check ran to completion.
                  </p>
                ) : (
                  <ul className="space-y-2">
                    {report.notes.map((note) => (
                      <li key={note} className="text-muted-foreground flex gap-2 text-sm">
                        <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
                        <span>{note}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>

            {stackBadges.length > 0 ? (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Detected stack</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-wrap gap-2">
                  {stackBadges.map((item) => (
                    <Badge key={item} variant="secondary">
                      {item}
                    </Badge>
                  ))}
                </CardContent>
              </Card>
            ) : null}
          </TabsContent>

          <TabsContent value="architecture" className="pt-4">
            <EmptyState
              icon={<Network className="size-6" aria-hidden />}
              title="Architecture graph"
              description="An interactive map of how the layers connect, with broken edges highlighted. Arriving in Phase 6."
            />
          </TabsContent>
        </Tabs>
      </div>

      <IssueDrawer issue={selected} open={drawerOpen} onOpenChange={setDrawerOpen} />
    </AppShell>
  );
}
