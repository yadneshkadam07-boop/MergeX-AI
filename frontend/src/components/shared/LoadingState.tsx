import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface LoadingStateProps {
  message?: string;
  description?: string;
  className?: string;
  minHeight?: string;
}

export function LoadingState({
  message = "Loading...",
  description,
  className,
  minHeight = "min-h-[260px]",
}: LoadingStateProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "border-border/80 bg-muted/10 animate-in fade-in-50 flex flex-col items-center justify-center rounded-xl border border-dashed p-8 text-center duration-200",
        minHeight,
        className,
      )}
    >
      <div className="relative flex items-center justify-center">
        <div className="border-primary/20 absolute size-10 animate-ping rounded-full border-2 opacity-75" />
        <Loader2 className="text-primary relative size-6 animate-spin" />
      </div>
      <p className="text-foreground mt-4 text-xs font-semibold tracking-tight">{message}</p>
      {description && (
        <p className="text-muted-foreground mt-1 max-w-sm text-[11px]">{description}</p>
      )}
      <span className="sr-only">{message}</span>
    </div>
  );
}
