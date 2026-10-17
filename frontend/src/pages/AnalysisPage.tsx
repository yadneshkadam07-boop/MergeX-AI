import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, WifiOff } from "lucide-react";
import { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { analysisKeys, getAnalysis } from "@/api/analyses";
import { AppShell } from "@/components/AppShell";
import { StageStepper } from "@/components/StageStepper";
import { ErrorState } from "@/components/states";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useAnalysisStream } from "@/hooks/use-analysis-stream";

/**
 * Live progress for one run.
 *
 * The stream is the primary source here, but it is not the only one: a user
 * can open this page long after the run finished, or reload it, so the
 * analysis row is fetched too. Whichever says the run is over wins, and the
 * page moves on to the dashboard.
 */
export function AnalysisPage() {
  const { analysisId } = useParams<{ analysisId: string }>();
  const navigate = useNavigate();

  const stream = useAnalysisStream(analysisId);

  // Polled only as a safety net for the case where the stream never
  // connects at all; once it is open the events are authoritative.
  const { data: analysis, error } = useQuery({
    queryKey: analysisKeys.detail(analysisId ?? ""),
    queryFn: () => getAnalysis(analysisId as string),
    enabled: Boolean(analysisId),
    refetchInterval: stream.connection === "error" && !stream.isFinished ? 3_000 : false,
  });

  const succeeded = stream.terminal?.status === "completed" || analysis?.status === "succeeded";
  const failed = stream.isFailed || analysis?.status === "failed";

  useEffect(() => {
    if (!succeeded || failed || !analysisId) return;
    // A moment on the completed stepper, then the report.
    const timer = setTimeout(() => navigate(`/analyses/${analysisId}/report`), 900);
    return () => clearTimeout(timer);
  }, [succeeded, failed, analysisId, navigate]);

  if (!analysisId) {
    return (
      <AppShell className="max-w-3xl">
        <ErrorState message="No analysis was specified." />
      </AppShell>
    );
  }

  const failureMessage =
    stream.terminal?.message ?? analysis?.error_message ?? "The analysis did not complete.";

  return (
    <AppShell className="max-w-3xl">
      <div className="space-y-6 py-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">
            {failed ? "Analysis failed" : succeeded ? "Analysis complete" : "Analysing project"}
          </h1>
          <p className="text-muted-foreground text-sm">
            {failed
              ? "The run stopped before it could produce a report."
              : succeeded
                ? "Opening the report…"
                : "Each stage reports as it finishes. You can leave this page and come back."}
          </p>
        </div>

        {stream.connection === "reconnecting" ? (
          <Alert>
            <RefreshCw className="size-4 animate-spin" aria-hidden />
            <AlertTitle>Reconnecting…</AlertTitle>
            <AlertDescription>
              The connection dropped (attempt {stream.reconnectAttempts}). The analysis keeps
              running on the server; progress resumes from where it left off.
            </AlertDescription>
          </Alert>
        ) : null}

        {stream.connection === "error" && !stream.isFinished ? (
          <Alert>
            <WifiOff className="size-4" aria-hidden />
            <AlertTitle>Lost the live connection</AlertTitle>
            <AlertDescription className="space-y-3">
              <p>
                Progress updates have stopped, but the analysis is still running on the server.
                Reconnect to pick it up, or open the report when it finishes.
              </p>
              <Button variant="outline" size="sm" onClick={stream.reconnect}>
                <RefreshCw className="size-3.5" aria-hidden />
                Reconnect
              </Button>
            </AlertDescription>
          </Alert>
        ) : null}

        {failed ? (
          <Alert variant="destructive">
            <AlertTriangle className="size-4" aria-hidden />
            <AlertTitle>The analysis failed</AlertTitle>
            <AlertDescription className="space-y-3">
              <p>{failureMessage}</p>
              <Button variant="outline" size="sm" onClick={() => navigate("/")}>
                Import another project
              </Button>
            </AlertDescription>
          </Alert>
        ) : null}

        <Card>
          {/* CardAction is what switches CardHeader's grid to two columns;
              a flex override on the header is ignored. */}
          <CardHeader>
            <CardTitle className="text-base">Pipeline</CardTitle>
            <CardDescription>
              {stream.connection === "open" || stream.connection === "connecting"
                ? "Live"
                : stream.isFinished
                  ? "Finished"
                  : "Not connected"}
            </CardDescription>
            <CardAction className="text-right">
              <p className="text-2xl font-semibold tabular-nums">{stream.totalFindings}</p>
              <p className="text-muted-foreground text-xs">issues so far</p>
            </CardAction>
          </CardHeader>
          <CardContent>
            <StageStepper stages={stream.stages} />
          </CardContent>
        </Card>

        {succeeded && !failed ? (
          <Button onClick={() => navigate(`/analyses/${analysisId}/report`)} className="w-full">
            <CheckCircle2 className="size-4" aria-hidden />
            View the report
          </Button>
        ) : null}

        {!stream.isFinished && !failed ? (
          <p className="text-muted-foreground flex items-center gap-2 text-sm">
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
            Analysis in progress
          </p>
        ) : null}

        {error && stream.connection === "error" ? (
          <ErrorState
            title="Cannot reach the API"
            message="Neither the event stream nor the analysis record could be loaded."
          />
        ) : null}
      </div>
    </AppShell>
  );
}
