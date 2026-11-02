import { Link, useParams } from "react-router-dom";
import type { CategoryScores, IssueCounts } from "@/types/project";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { ArrowUpRight, Package, Rocket, ShieldCheck, Zap } from "lucide-react";

interface CategoryCardsProps {
  categoryScores: CategoryScores;
  issueCounts: IssueCounts;
}

interface CategoryCardItem {
  id: string;
  name: string;
  tabPath: string;
  icon: typeof Zap;
  score: number;
  issues: number;
}

export function CategoryCards({ categoryScores, issueCounts }: CategoryCardsProps) {
  const { id } = useParams<{ id: string }>();

  const categories: CategoryCardItem[] = [
    {
      id: "integration",
      name: "Integration",
      tabPath: "integration",
      icon: Zap,
      score: categoryScores.integration,
      issues: issueCounts.integration,
    },
    {
      id: "security",
      name: "Security",
      tabPath: "security",
      icon: ShieldCheck,
      score: categoryScores.security,
      issues: issueCounts.security,
    },
    {
      id: "dependencies",
      name: "Dependencies",
      tabPath: "dependencies",
      icon: Package,
      score: categoryScores.dependencies,
      issues: issueCounts.dependencies,
    },
    {
      id: "deployment",
      name: "Deployment Readiness",
      tabPath: "deploy",
      icon: Rocket,
      score: categoryScores.deployment,
      issues: issueCounts.deployment,
    },
  ];

  const getStatusLabel = (score: number) => {
    if (score >= 80) {
      return {
        label: "Healthy",
        variant: "border-success bg-success/12 text-success",
      };
    }
    if (score >= 50) {
      return {
        label: "Needs Attention",
        variant: "border-sev-medium bg-sev-medium/12 text-sev-medium",
      };
    }
    return {
      label: "Critical",
      variant: "border-sev-critical bg-sev-critical/12 text-sev-critical",
    };
  };

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {categories.map((cat) => {
        const Icon = cat.icon;
        const status = getStatusLabel(cat.score);

        return (
          <Link
            key={cat.id}
            to={`/project/${id}/${cat.tabPath}`}
            className="group focus-visible:ring-ring block rounded-xl focus:outline-hidden focus-visible:ring-2"
          >
            <Card interactive className="bg-card h-full border">
              <CardContent className="flex h-full flex-col justify-between space-y-4 p-5">
                <div>
                  <div className="flex items-center justify-between">
                    <div className="bg-primary/10 text-primary flex size-9 items-center justify-center rounded-lg">
                      <Icon className="size-4" />
                    </div>
                    <Badge
                      variant="outline"
                      className={`text-[10px] font-semibold ${status.variant}`}
                    >
                      {status.label}
                    </Badge>
                  </div>

                  <div className="mt-3.5 flex items-center justify-between">
                    <h3 className="text-foreground group-hover:text-primary text-sm font-semibold transition-colors">
                      {cat.name}
                    </h3>
                    <ArrowUpRight className="text-muted-foreground/60 group-hover:text-primary size-4 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
                  </div>

                  <p className="text-muted-foreground mt-1 text-xs">
                    {cat.issues === 0
                      ? "Zero issues flagged"
                      : `${cat.issues} open issue${cat.issues === 1 ? "" : "s"}`}
                  </p>
                </div>

                <div className="space-y-1.5 border-t pt-2">
                  <div className="flex items-center justify-between text-xs font-medium">
                    <span className="text-muted-foreground">Category Score</span>
                    <span className="text-foreground font-mono font-bold">{cat.score}/100</span>
                  </div>
                  <Progress value={cat.score} className="h-1.5" />
                </div>
              </CardContent>
            </Card>
          </Link>
        );
      })}
    </div>
  );
}
