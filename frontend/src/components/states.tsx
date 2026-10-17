import { AlertTriangle, CheckCircle2, Inbox, RefreshCw, WifiOff } from "lucide-react";
import type { ReactNode } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * The states every data-backed view has to handle.
 *
 * Kept together because the failure modes are the part of a dashboard most
 * likely to be skipped, and a shared set makes "did we handle empty?" a
 * question with a visible answer.
 */

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="space-y-4" role="status" aria-busy="true" aria-label={label}>
      <Skeleton className="h-8 w-56" />
      <div className="grid gap-4 md:grid-cols-3">
        <Skeleton className="h-52" />
        <Skeleton className="h-52 md:col-span-2" />
      </div>
      <Skeleton className="h-64" />
    </div>
  );
}

export function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <Alert variant="destructive" className="items-start">
      <AlertTriangle className="size-4" aria-hidden />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription className="space-y-3">
        <p>{message}</p>
        {onRetry ? (
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RefreshCw className="size-3.5" aria-hidden />
            Try again
          </Button>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}

/** A backend that cannot be reached at all, as distinct from a 4xx/5xx. */
export function OfflineState({ onRetry }: { onRetry?: () => void }) {
  return (
    <Alert className="items-start">
      <WifiOff className="size-4" aria-hidden />
      <AlertTitle>Cannot reach the MergeX API</AlertTitle>
      <AlertDescription className="space-y-3">
        <p>
          The backend did not respond. Check that it is running and that{" "}
          <code className="font-mono text-xs">VITE_API_BASE_URL</code> points at it.
        </p>
        {onRetry ? (
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RefreshCw className="size-3.5" aria-hidden />
            Retry
          </Button>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}

export function EmptyState({
  icon = <Inbox className="size-6" aria-hidden />,
  title,
  description,
  action,
  className,
}: {
  icon?: ReactNode;
  title: string;
  description: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "border-border flex flex-col items-center gap-3 rounded-xl border border-dashed px-6 py-14 text-center",
        className,
      )}
    >
      <span className="text-muted-foreground bg-muted flex size-12 items-center justify-center rounded-full">
        {icon}
      </span>
      <h3 className="text-lg font-medium">{title}</h3>
      <p className="text-muted-foreground max-w-prose text-sm">{description}</p>
      {action}
    </div>
  );
}

/** The genuinely good outcome: analysed, and nothing found. */
export function CleanState({ checked }: { checked: string }) {
  return (
    <EmptyState
      icon={<CheckCircle2 className="text-severity-ok size-6" aria-hidden />}
      title="No issues found"
      description={`${checked} Every check that applied to this project passed.`}
    />
  );
}
