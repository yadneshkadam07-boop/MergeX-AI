import { cn } from "@/lib/utils";

interface ScoreRingProps {
  score: number;
  size?: number;
  strokeWidth?: number;
  className?: string;
}

export function ScoreRing({ score, size = 132, strokeWidth = 10, className }: ScoreRingProps) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset =
    circumference - (Math.max(0, Math.min(100, score)) / 100) * circumference;

  let strokeColor = "stroke-success";
  let label = "Healthy";

  if (score < 50) {
    strokeColor = "stroke-sev-critical";
    label = "Critical";
  } else if (score < 80) {
    strokeColor = "stroke-sev-medium";
    label = "Needs Attention";
  }

  return (
    <div
      role="img"
      aria-label={`Project Health Score: ${score} out of 100 (${label})`}
      className={cn("relative flex shrink-0 items-center justify-center select-none", className)}
      style={{ width: size, height: size }}
    >
      <svg className="size-full -rotate-90" viewBox={`0 0 ${size} ${size}`}>
        {/* Background track */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          className="stroke-muted"
          strokeWidth={strokeWidth}
          fill="none"
        />
        {/* Animated Progress ring */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          className={cn(strokeColor, "transition-all duration-700 ease-out")}
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          strokeLinecap="round"
          fill="none"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
        <span className="text-foreground font-mono text-3xl font-extrabold tracking-tight">
          {score}
        </span>
        <span className="text-muted-foreground text-[11px] font-semibold tracking-wider uppercase">
          Health Score
        </span>
      </div>
    </div>
  );
}
