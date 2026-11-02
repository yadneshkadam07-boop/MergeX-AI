import React from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ErrorStateProps {
  title?: string;
  message: string;
  onRetry?: () => void;
  action?: React.ReactNode;
  className?: string;
  minHeight?: string;
}

export function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
  action,
  className,
  minHeight = "min-h-[260px]",
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      aria-live="assertive"
      className={cn(
        "border-destructive/30 bg-destructive/5 animate-in fade-in-50 flex flex-col items-center justify-center rounded-xl border p-8 text-center duration-200",
        minHeight,
        className,
      )}
    >
      <div className="bg-destructive/10 text-destructive ring-destructive/5 flex size-12 items-center justify-center rounded-full ring-8">
        <AlertTriangle className="size-6" />
      </div>
      <h3 className="text-foreground mt-4 text-sm font-bold tracking-tight">{title}</h3>
      <p className="text-muted-foreground mt-1.5 max-w-sm text-xs leading-relaxed">{message}</p>
      {(onRetry || action) && (
        <div className="mt-5 flex max-w-full min-w-0 flex-wrap items-center justify-center gap-3">
          {onRetry && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onRetry}
              className="border-destructive/20 hover:bg-destructive/10 hover:text-destructive gap-1.5 text-xs font-semibold"
            >
              <RefreshCw className="size-3.5" />
              <span>Retry</span>
            </Button>
          )}
          {action}
        </div>
      )}
    </div>
  );
}
