import { useLocation, useParams } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { LayoutDashboard } from "lucide-react";

interface PlaceholderPageProps {
  title: string;
  description?: string;
  stageBadge?: string;
}

export function PlaceholderPage({
  title,
  description = "This page layout is configured for Stage 1. Functional content and workflows will be added in subsequent stages.",
  stageBadge = "Stage 1 Shell",
}: PlaceholderPageProps) {
  const location = useLocation();
  const params = useParams();

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-foreground text-2xl font-bold tracking-tight">{title}</h1>
            <Badge variant="outline" className="text-muted-foreground text-xs font-medium">
              {stageBadge}
            </Badge>
          </div>
          <p className="text-muted-foreground mt-1 text-sm">{description}</p>
        </div>
      </div>

      <Card className="border-dashed">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <LayoutDashboard className="text-muted-foreground size-5" />
            <CardTitle className="text-base font-semibold">Route Information</CardTitle>
          </div>
          <CardDescription>Details of the active route matching in this shell.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground w-24 font-medium">Path:</span>
            <code className="bg-muted text-foreground rounded px-2 py-0.5 font-mono text-xs">
              {location.pathname}
            </code>
          </div>
          {Object.keys(params).length > 0 && (
            <div className="flex items-start gap-2">
              <span className="text-muted-foreground w-24 font-medium">Parameters:</span>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(params).map(([key, val]) => (
                  <Badge key={key} variant="secondary" className="font-mono text-xs">
                    {key}={val}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
