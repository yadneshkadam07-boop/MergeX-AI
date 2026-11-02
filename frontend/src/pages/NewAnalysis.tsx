import React, { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import type { AnalysisStep, Project } from "@/types/project";
import { createAnalysis, updateProject, getAnalysisSteps, getAnalysisStatus } from "@/lib/api";
import { isMock } from "@/lib/config";
import { generateProjectDetails } from "@/lib/project-generator";
import { useDocumentTitle } from "@/hooks/use-document-title";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  ArrowRight,
  CheckCircle2,
  Circle,
  FolderGit2,
  Layers,
  Loader2,
  RotateCcw,
  ShieldAlert,
  Sparkles,
  Zap,
} from "lucide-react";

const GITHUB_REGEX = /^https?:\/\/(www\.)?github\.com\/[\w.-]+\/[\w.-]+\/?$/i;
const SAMPLE_REPO = "https://github.com/shadcn-ui/taxonomy";

export function NewAnalysis() {
  const navigate = useNavigate();
  useDocumentTitle("New Analysis");

  // Mode: "input" (Phase A) or "progress" (Phase B)
  const [phase, setPhase] = useState<"input" | "progress">("input");
  const [repoUrl, setRepoUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Phase B Live Progress state
  const [currentProject, setCurrentProject] = useState<Project | null>(null);
  const [steps, setSteps] = useState<AnalysisStep[]>([]);
  const [activeStepIndex, setActiveStepIndex] = useState(0);

  // References to keep timer cleanups bulletproof on unmount or cancel
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isCancelledRef = useRef<boolean>(false);

  // Reset steps when entering progress phase
  useEffect(() => {
    return () => {
      // Clear timers on component unmount
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
      isCancelledRef.current = true;
    };
  }, []);

  const handleValidateUrl = (url: string) => {
    if (!url.trim()) {
      return "GitHub repository URL is required.";
    }
    if (!GITHUB_REGEX.test(url.trim())) {
      return "Please enter a valid GitHub URL (e.g. https://github.com/owner/repo).";
    }
    return null;
  };

  const handleStartAnalysis = async (e: React.FormEvent) => {
    e.preventDefault();
    const validationError = handleValidateUrl(repoUrl);
    if (validationError) {
      setError(validationError);
      return;
    }

    setSubmitting(true);
    try {
      const res = await createAnalysis(repoUrl.trim());
      setCurrentProject(res);
      const freshSteps = res.steps && res.steps.length > 0 ? res.steps : getAnalysisSteps();
      setSteps(freshSteps);
      setActiveStepIndex(0);
      isCancelledRef.current = false;
      setPhase("progress");
      setSubmitting(false);

      if (isMock("analysis")) {
        // Simulated mock sequence
        runStepSequence(res.id, freshSteps, 0);
      } else {
        // Real FastAPI analysis polling
        startRealPolling(res.analysisId, res.id, freshSteps);
      }
    } catch (err) {
      console.error("Failed to start analysis:", err);
      setError("Failed to initialize analysis. Please try again.");
      setSubmitting(false);
    }
  };

  const startRealPolling = (
    analysisId: string,
    projectId: string,
    stepTemplates: AnalysisStep[],
  ) => {
    let consecutiveErrors = 0;
    const poll = async () => {
      if (isCancelledRef.current) return;
      try {
        const status = await getAnalysisStatus(analysisId);
        consecutiveErrors = 0;

        const activeIdx = Math.min(status.currentStepIndex || 0, stepTemplates.length - 1);
        setActiveStepIndex(activeIdx);
        setSteps((prev) =>
          prev.map((step, i) => {
            if (i < activeIdx) return { ...step, status: "done" };
            if (i === activeIdx)
              return { ...step, status: status.status === "failed" ? "pending" : "running" };
            return { ...step, status: "pending" };
          }),
        );

        if (status.status === "completed") {
          setSteps((prev) => prev.map((s) => ({ ...s, status: "done" })));
          timerRef.current = setTimeout(() => {
            if (!isCancelledRef.current) {
              void navigate(`/project/${projectId}`);
            }
          }, 800);
          return;
        }

        if (status.status === "failed") {
          setError(status.error || "Analysis failed on backend server.");
          setPhase("input");
          return;
        }

        timerRef.current = setTimeout(() => {
          void poll();
        }, 1500);
      } catch (err) {
        consecutiveErrors++;
        console.error("Error polling analysis status:", err);
        if (consecutiveErrors >= 5) {
          setError("Lost connection to analysis server. Please check your network and retry.");
          setPhase("input");
          return;
        }
        timerRef.current = setTimeout(
          () => {
            void poll();
          },
          1500 * Math.pow(1.5, consecutiveErrors),
        );
      }
    };

    void poll();
  };

  const runStepSequence = (projectId: string, currentSteps: AnalysisStep[], stepIdx: number) => {
    if (isCancelledRef.current) return;

    if (stepIdx >= currentSteps.length) {
      // All 8 steps completed! Finalize project data
      void finalizeAnalysis(projectId);
      return;
    }

    // Mark current step as running
    setSteps((prev) =>
      prev.map((step, i) => {
        if (i < stepIdx) return { ...step, status: "done" };
        if (i === stepIdx) return { ...step, status: "running" };
        return { ...step, status: "pending" };
      }),
    );
    setActiveStepIndex(stepIdx);

    // Run this step for 1100 - 1400ms
    const stepDuration = Math.floor(Math.random() * 300) + 1100;
    timerRef.current = setTimeout(() => {
      if (isCancelledRef.current) return;

      // Mark this step done
      setSteps((prev) =>
        prev.map((step, i) => (i === stepIdx ? { ...step, status: "done" } : step)),
      );

      // Advance to next step
      runStepSequence(projectId, currentSteps, stepIdx + 1);
    }, stepDuration);
  };

  const finalizeAnalysis = async (projectId: string) => {
    // Generate realistic randomized scores (55 - 95)
    const randomScore = Math.floor(Math.random() * 41) + 55;
    const details = generateProjectDetails(randomScore);

    try {
      await updateProject(projectId, {
        healthScore: randomScore,
        status: "completed",
        issueCounts: details.issueCounts,
        categoryScores: details.categoryScores,
        severityCounts: details.severityCounts,
        topIssues: details.topIssues,
        scanMeta: details.scanMeta,
      });

      // Pause briefly (~800ms) before navigating to /project/:id
      timerRef.current = setTimeout(() => {
        if (!isCancelledRef.current) {
          void navigate(`/project/${projectId}`);
        }
      }, 800);
    } catch (err) {
      console.error("Error finalizing analysis:", err);
    }
  };

  const handleCancel = () => {
    isCancelledRef.current = true;
    if (timerRef.current) {
      clearTimeout(timerRef.current);
    }
    setPhase("input");
    setActiveStepIndex(0);
    setCurrentProject(null);
  };

  const progressPercentage = Math.round((activeStepIndex / 8) * 100);

  return (
    <div className="flex min-h-[calc(100vh-12rem)] items-center justify-center py-8">
      {phase === "input" ? (
        /* Phase A: Input Form */
        <div className="w-full max-w-xl space-y-6">
          <Card className="bg-card border shadow-lg">
            <CardHeader className="space-y-2 pb-6 text-center">
              <div className="bg-primary/10 text-primary mx-auto flex size-12 items-center justify-center rounded-2xl">
                <FolderGit2 className="size-6" />
              </div>
              <CardTitle className="text-foreground text-2xl font-bold tracking-tight">
                Analyze a repository
              </CardTitle>
              <CardDescription className="text-muted-foreground text-sm">
                Enter a GitHub repository URL to inspect for multi-agent synthesis errors, API
                drift, and deployment blockers.
              </CardDescription>
            </CardHeader>

            <CardContent className="space-y-5">
              <form onSubmit={handleStartAnalysis} noValidate className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="repo-url" className="text-xs font-semibold">
                    GitHub Repository URL
                  </Label>
                  <Input
                    id="repo-url"
                    type="url"
                    placeholder="https://github.com/owner/repository"
                    value={repoUrl}
                    onChange={(e) => {
                      setRepoUrl(e.target.value);
                      if (error) setError(null);
                    }}
                    className={error ? "border-destructive focus-visible:ring-destructive" : ""}
                    aria-invalid={!!error}
                    aria-describedby={error ? "repo-error" : undefined}
                    disabled={submitting}
                  />
                  {error && (
                    <p id="repo-error" className="text-destructive text-xs font-medium">
                      {error}
                    </p>
                  )}
                </div>

                <div className="flex flex-col gap-2 pt-2">
                  <Button
                    type="submit"
                    size="lg"
                    className="w-full gap-2 font-semibold"
                    disabled={submitting}
                  >
                    {submitting ? (
                      <>
                        <Loader2 className="size-4 animate-spin" />
                        <span>Initializing...</span>
                      </>
                    ) : (
                      <>
                        <span>Start analysis</span>
                        <ArrowRight className="size-4" />
                      </>
                    )}
                  </Button>

                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      setRepoUrl(SAMPLE_REPO);
                      setError(null);
                    }}
                    disabled={submitting}
                    className="text-muted-foreground hover:text-foreground h-auto min-h-9 w-full px-3 py-2 text-center text-xs leading-normal break-words"
                  >
                    <Sparkles className="text-brand-secondary mr-1.5 size-3.5 shrink-0" />
                    <span>
                      Try a sample repo ({SAMPLE_REPO.replace("https://github.com/", "")})
                    </span>
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>

          {/* Validation Scope Card */}
          <Card className="bg-muted/30 border-dashed">
            <CardContent className="p-4">
              <p className="text-muted-foreground mb-2 text-xs font-semibold tracking-wider uppercase">
                What will be inspected
              </p>
              <div className="text-foreground grid grid-cols-2 gap-2 text-xs">
                <div className="flex items-center gap-1.5">
                  <Zap className="text-brand-secondary size-3.5" />
                  <span>API route & contract drift</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <Layers className="text-primary size-3.5" />
                  <span>Database model migrations</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <ShieldAlert className="text-sev-critical size-3.5" />
                  <span>Secrets & dependency CVEs</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <CheckCircle2 className="text-success size-3.5" />
                  <span>Docker & deploy readiness</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      ) : (
        /* Phase B: Live Progress */
        <Card className="bg-card w-full max-w-xl border shadow-lg">
          <CardHeader className="space-y-4 pb-4">
            <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0 flex-1">
                <span className="text-primary text-xs font-semibold tracking-wider uppercase">
                  Running Multi-Agent Diagnostics
                </span>
                <CardTitle className="text-foreground mt-0.5 truncate text-xl font-bold tracking-tight">
                  {currentProject?.name || "Repository"}
                </CardTitle>
                <CardDescription className="text-muted-foreground max-w-sm truncate text-xs">
                  {currentProject?.repoUrl}
                </CardDescription>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={handleCancel}
                className="text-muted-foreground hover:text-destructive shrink-0 gap-1.5 self-start text-xs sm:self-auto"
              >
                <RotateCcw className="size-3.5" />
                Cancel
              </Button>
            </div>

            {/* Overall Progress Bar */}
            <div className="space-y-1.5">
              <div className="flex justify-between text-xs font-semibold">
                <span className="text-muted-foreground">Overall Progress</span>
                <span className="text-primary font-mono">{progressPercentage}%</span>
              </div>
              <Progress value={progressPercentage} className="h-2" />
            </div>
          </CardHeader>

          <CardContent className="pt-2">
            {/* Live 8-step Vertical List with aria-live */}
            <div
              className="divide-border/60 space-y-3.5 divide-y"
              aria-live="polite"
              aria-atomic="false"
            >
              {steps.map((step, idx) => {
                const isRunning = step.status === "running";
                const isDone = step.status === "done";

                return (
                  <div
                    key={step.id}
                    className={`flex items-center justify-between pt-3.5 transition-colors first:pt-0 ${
                      isRunning ? "text-foreground font-semibold" : ""
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <div className="flex size-6 shrink-0 items-center justify-center">
                        {isDone ? (
                          <CheckCircle2 className="text-success animate-in zoom-in-75 size-5 duration-200" />
                        ) : isRunning ? (
                          <Loader2 className="text-primary size-5 animate-spin" />
                        ) : (
                          <Circle className="text-muted-foreground/40 size-4" />
                        )}
                      </div>
                      <span
                        className={`text-sm ${
                          isDone
                            ? "text-muted-foreground line-through opacity-85"
                            : isRunning
                              ? "text-foreground font-medium"
                              : "text-muted-foreground"
                        }`}
                      >
                        {step.label}
                      </span>
                    </div>

                    <span className="text-muted-foreground font-mono text-xs">
                      {isDone ? (
                        <span className="text-success font-semibold">Done</span>
                      ) : isRunning ? (
                        <span className="text-primary font-semibold">Analyzing...</span>
                      ) : (
                        <span className="text-muted-foreground/60">Step 0{idx + 1}</span>
                      )}
                    </span>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
