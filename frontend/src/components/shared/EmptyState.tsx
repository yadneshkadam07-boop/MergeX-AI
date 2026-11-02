import React from "react";
import { Inbox } from "lucide-react";
import { cn } from "@/lib/utils";

interface EmptyStateProps {
  icon?: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
  action?: React.ReactNode;
  className?: string;
  minHeight?: string;
}

export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
  className,
  minHeight = "min-h-[260px]",
}: EmptyStateProps) {
  return (
    <div
      role="region"
      aria-label={title}
      className={cn(
        "border-border bg-card/40 text-card-foreground animate-in fade-in-50 flex flex-col items-center justify-center rounded-xl border border-dashed p-8 text-center duration-200",
        minHeight,
        className,
      )}
    >
      <div className="bg-muted/60 text-muted-foreground ring-muted/20 flex size-12 items-center justify-center rounded-full ring-8">
        <Icon className="size-6" />
      </div>
      <h3 className="text-foreground mt-4 text-sm font-bold tracking-tight">{title}</h3>
      <p className="text-muted-foreground mt-1.5 max-w-sm text-xs leading-relaxed">{description}</p>
      {action && (
        <div className="mt-5 flex max-w-full min-w-0 flex-wrap justify-center">{action}</div>
      )}
    </div>
  );
}
