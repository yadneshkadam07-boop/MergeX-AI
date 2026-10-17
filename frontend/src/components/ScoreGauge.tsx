import { PolarAngleAxis, RadialBar, RadialBarChart, ResponsiveContainer } from "recharts";

import { cn } from "@/lib/utils";
import { scoreTone } from "@/lib/severity";

interface ScoreGaugeProps {
  score: number;
  /** Shown under the number: "4 issues", or why there is no score. */
  caption?: string;
  isFloored?: boolean;
  size?: number;
  className?: string;
}

/**
 * The health score, as a dial.
 *
 * The number is the backend's; nothing here recomputes it. `isFloored` is
 * surfaced because two projects clamped at 0 are not equally bad, and a bare
 * 0 implies they are.
 */
export function ScoreGauge({
  score,
  caption,
  isFloored = false,
  size = 200,
  className,
}: ScoreGaugeProps) {
  const tone = scoreTone(score);
  const data = [{ name: "score", value: score, fill: tone.cssVar }];

  return (
    <div className={cn("flex flex-col items-center gap-2", className)}>
      <div className="relative" style={{ width: size, height: size }} data-testid="score-gauge">
        <ResponsiveContainer width="100%" height="100%">
          <RadialBarChart
            innerRadius="76%"
            outerRadius="100%"
            data={data}
            startAngle={90}
            endAngle={-270}
          >
            <PolarAngleAxis type="number" domain={[0, 100]} angleAxisId={0} tick={false} />
            <RadialBar
              dataKey="value"
              angleAxisId={0}
              cornerRadius={999}
              background={{ fill: "var(--muted)" }}
              isAnimationActive={false}
            />
          </RadialBarChart>
        </ResponsiveContainer>

        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span
            className="text-5xl font-semibold tabular-nums"
            style={{ color: tone.cssVar }}
            aria-label={`Health score ${score} out of 100`}
          >
            {score}
          </span>
          <span className="text-muted-foreground text-xs tracking-wide uppercase">
            {isFloored ? `${tone.label} · floored` : tone.label}
          </span>
        </div>
      </div>

      {caption ? <p className="text-muted-foreground text-sm">{caption}</p> : null}
    </div>
  );
}
