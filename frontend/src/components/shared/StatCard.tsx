import type { ReactNode } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface StatCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: ReactNode;
  className?: string;
}

export function StatCard({ title, value, subtitle, icon, className }: StatCardProps) {
  return (
    <Card interactive className={cn("bg-card border shadow-xs", className)}>
      <CardContent className="flex items-center justify-between p-5">
        <div className="space-y-1">
          <p className="text-muted-foreground text-xs font-semibold tracking-wider uppercase">
            {title}
          </p>
          <p className="text-foreground text-2xl font-bold tracking-tight">{value}</p>
          {subtitle && <p className="text-muted-foreground text-xs">{subtitle}</p>}
        </div>
        <div className="bg-muted text-foreground/80 flex size-11 items-center justify-center rounded-xl">
          {icon}
        </div>
      </CardContent>
    </Card>
  );
}
