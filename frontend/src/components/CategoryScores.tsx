import { AlertTriangle, MinusCircle } from "lucide-react";

import { CATEGORIES, type Category, type Score } from "@/api/analyses";
import { Progress } from "@/components/ui/progress";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { CATEGORY_DESCRIPTIONS, CATEGORY_LABELS, scoreTone } from "@/lib/severity";

interface CategoryScoresProps {
  score: Score;
  /** Categories whose rule group crashed; their scores are not trustworthy. */
  failedGroups: Category[];
}

/**
 * Per-category sub-scores.
 *
 * Three states, deliberately distinguishable at a glance, because conflating
 * them is the easiest way for a dashboard to mislead:
 *
 * - scored      — we looked and this is what we found
 * - not applicable — there was nothing of this kind in the project
 * - failed      — we could not look, so this says nothing about the code
 */
export function CategoryScores({ score, failedGroups }: CategoryScoresProps) {
  const failed = new Set(failedGroups);

  return (
    <ul className="space-y-4" data-testid="category-scores">
      {CATEGORIES.map((category) => {
        const entry = score.categories[category];
        const didFail = failed.has(category);
        const notApplicable = !didFail && entry !== undefined && !entry.analysed;
        const value = entry?.score ?? 100;
        const tone = scoreTone(value);

        return (
          <li key={category} className="space-y-1.5">
            <div className="flex items-baseline justify-between gap-3">
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="cursor-help text-sm font-medium">
                    {CATEGORY_LABELS[category]}
                  </span>
                </TooltipTrigger>
                <TooltipContent>{CATEGORY_DESCRIPTIONS[category]}</TooltipContent>
              </Tooltip>

              {didFail ? (
                <span className="text-severity-high inline-flex items-center gap-1 text-xs font-medium">
                  <AlertTriangle className="size-3.5" aria-hidden />
                  Analysis failed
                </span>
              ) : notApplicable ? (
                <span className="text-muted-foreground inline-flex items-center gap-1 text-xs">
                  <MinusCircle className="size-3.5" aria-hidden />
                  Not applicable
                </span>
              ) : (
                <span className="text-sm tabular-nums" style={{ color: tone.cssVar }}>
                  {value}
                  <span className="text-muted-foreground">/100</span>
                </span>
              )}
            </div>

            {/* The generated Progress paints its indicator `bg-primary`;
                `--tone` recolours it per category without editing the
                shadcn-generated file. */}
            <Progress
              value={didFail || notApplicable ? 0 : value}
              aria-label={`${CATEGORY_LABELS[category]} score`}
              className="h-1.5 [&>[data-slot=progress-indicator]]:bg-(--tone)"
              style={{ "--tone": tone.cssVar } as React.CSSProperties}
            />

            <p className="text-muted-foreground text-xs">
              {didFail
                ? "This category could not be checked — treat it as unknown, not clean."
                : notApplicable
                  ? "Nothing of this kind was found in the project."
                  : `${entry?.issue_count ?? 0} issue${(entry?.issue_count ?? 0) === 1 ? "" : "s"}`}
            </p>
          </li>
        );
      })}
    </ul>
  );
}
