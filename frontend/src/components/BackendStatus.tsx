import { useBackendStatus } from "@/hooks/use-backend-status";
import { cn } from "@/lib/utils";

/** Live connectivity indicator for the backend API. */
export function BackendStatus() {
  const { data, isPending, isError } = useBackendStatus();

  const label = isPending
    ? "Connecting to API…"
    : isError
      ? "API unreachable"
      : `API ${data.version} · ${data.environment}`;

  const tone = isPending
    ? "bg-severity-medium"
    : isError
      ? "bg-severity-critical"
      : "bg-severity-ok";

  return (
    <span className="border-border bg-card/60 text-muted-foreground inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium">
      <span
        aria-hidden="true"
        className={cn("size-2 rounded-full", tone, isPending && "animate-pulse")}
      />
      {label}
    </span>
  );
}
