import { AlertTriangle, Check, Circle, Loader2, MinusCircle } from "lucide-react";

import { PIPELINE_STAGES, STAGE_LABELS, type Stage } from "@/api/events";
import type { StageState } from "@/hooks/use-analysis-stream";
import { cn } from "@/lib/utils";

interface StageStepperProps {
  stages: Partial<Record<Stage, StageState>>;
  className?: string;
}

const ICONS = {
  completed: Check,
  failed: AlertTriangle,
  skipped: MinusCircle,
  started: Loader2,
  pending: Circle,
} as const;

type Visual = keyof typeof ICONS;

const TONES: Record<Visual, string> = {
  completed: "text-severity-ok border-severity-ok/40 bg-severity-ok/10",
  failed: "text-severity-high border-severity-high/40 bg-severity-high/10",
  skipped: "text-muted-foreground border-border bg-muted/40",
  started: "text-foreground border-ring bg-accent",
  pending: "text-muted-foreground/60 border-border bg-background",
};

/**
 * The pipeline, one row per stage.
 *
 * A skipped stage is shown as skipped rather than hidden or ticked: "there
 * were no migrations to check" and "the schema is clean" are different
 * outcomes, and the stepper is where that difference first reaches a user.
 */
export function StageStepper({ stages, className }: StageStepperProps) {
  return (
    <ol className={cn("space-y-1", className)} data-testid="stage-stepper">
      {PIPELINE_STAGES.map((stage) => {
        const state = stages[stage];
        const visual: Visual = state ? state.status : "pending";
        const Icon = ICONS[visual];

        return (
          <li
            key={stage}
            data-stage={stage}
            data-status={visual}
            className="flex items-start gap-3 rounded-lg px-2 py-2"
          >
            <span
              className={cn(
                "mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border",
                TONES[visual],
              )}
            >
              <Icon
                className={cn("size-3.5", visual === "started" && "animate-spin")}
                aria-hidden
              />
            </span>

            <span className="min-w-0 flex-1">
              <span className="flex flex-wrap items-baseline justify-between gap-x-3">
                <span
                  className={cn(
                    "text-sm font-medium",
                    visual === "pending" && "text-muted-foreground/60",
                  )}
                >
                  {STAGE_LABELS[stage]}
                </span>

                {state?.findingCount !== null && state?.findingCount !== undefined ? (
                  <span
                    className={cn(
                      "text-xs tabular-nums",
                      state.findingCount > 0 ? "text-severity-high" : "text-severity-ok",
                    )}
                  >
                    {state.findingCount} issue{state.findingCount === 1 ? "" : "s"}
                  </span>
                ) : null}
              </span>

              {state?.message ? (
                <span className="text-muted-foreground block truncate text-xs">
                  {state.message}
                </span>
              ) : null}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
