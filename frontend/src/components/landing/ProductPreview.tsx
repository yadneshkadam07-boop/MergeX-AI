import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { landingContent } from "@/content/landing";
import { GitBranch, ShieldCheck } from "lucide-react";

export function ProductPreview() {
  const { productPreview } = landingContent;

  const statusVariant = (status: "Passed" | "Warning" | "Critical") => {
    switch (status) {
      case "Passed":
        return "bg-success/12 text-success border-success";
      case "Warning":
        return "bg-sev-medium/12 text-sev-medium border-sev-medium";
      case "Critical":
        return "bg-sev-critical/12 text-sev-critical border-sev-critical";
    }
  };

  // SVG circular gauge geometry
  const radius = 38;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (productPreview.score / 100) * circumference;

  return (
    <Card interactive className="border-border bg-card w-full max-w-lg border shadow-xl">
      <CardHeader className="flex flex-row items-center justify-between border-b pb-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <CardTitle className="text-base font-semibold">{productPreview.projectName}</CardTitle>
            <div className="bg-muted text-muted-foreground flex items-center gap-1 rounded px-2 py-0.5 font-mono text-xs">
              <GitBranch className="size-3" />
              {productPreview.branch}
            </div>
          </div>
          <p className="text-muted-foreground text-xs">{productPreview.lastAnalyzed}</p>
        </div>
        <Badge variant="outline" className="border-sev-medium bg-sev-medium/12 text-sev-medium">
          {productPreview.scoreRating}
        </Badge>
      </CardHeader>

      <CardContent className="space-y-6 pt-6">
        {/* Score Ring & Metric */}
        <div className="bg-muted/40 flex items-center gap-6 rounded-lg border p-4">
          <div className="relative flex size-24 shrink-0 items-center justify-center">
            <svg className="size-24 -rotate-90" viewBox="0 0 96 96">
              {/* Background circle */}
              <circle
                cx="48"
                cy="48"
                r={radius}
                className="stroke-muted"
                strokeWidth="8"
                fill="none"
              />
              {/* Progress ring */}
              <circle
                cx="48"
                cy="48"
                r={radius}
                className="stroke-sev-medium"
                strokeWidth="8"
                strokeDasharray={circumference}
                strokeDashoffset={strokeDashoffset}
                strokeLinecap="round"
                fill="none"
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-2xl font-black tracking-tight">{productPreview.score}</span>
              <span className="text-muted-foreground text-[10px] font-semibold uppercase">
                / 100
              </span>
            </div>
          </div>

          <div className="space-y-1">
            <div className="flex items-center gap-1.5 text-sm font-semibold">
              <ShieldCheck className="text-primary size-4" />
              <span>Overall Health Score</span>
            </div>
            <p className="text-muted-foreground text-xs leading-relaxed">
              Based on AST syntax, API contracts, ORM schema synchronization, and container
              configuration.
            </p>
          </div>
        </div>

        {/* Category Rows */}
        <div className="space-y-2.5">
          <span className="text-muted-foreground text-xs font-semibold tracking-wider uppercase">
            Analysis Breakdown
          </span>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {productPreview.categories.map((cat) => (
              <div
                key={cat.name}
                className="bg-background hover:border-border/80 flex flex-col justify-between rounded-lg border p-3 transition-colors"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold">{cat.name}</span>
                  <span
                    className={`rounded-md border px-1.5 py-0.5 text-[10px] font-semibold ${statusVariant(cat.status)}`}
                  >
                    {cat.status}
                  </span>
                </div>
                <div className="mt-2 flex items-baseline justify-between text-xs">
                  <span className="text-foreground font-mono font-bold">{cat.scoreText}</span>
                </div>
                <p className="text-muted-foreground mt-1 truncate text-[11px]" title={cat.details}>
                  {cat.details}
                </p>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
