import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertOctagon, RotateCcw, Home } from "lucide-react";
import { Button } from "@/components/ui/button";

interface Props {
  children?: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public override state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public override componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Uncaught application error:", error, errorInfo);
  }

  private handleReload = () => {
    window.location.reload();
  };

  private handleReset = () => {
    this.setState({ hasError: false, error: null });
    window.location.href = "/dashboard";
  };

  public override render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div
          role="alert"
          className="animate-in fade-in-50 flex min-h-[60vh] flex-col items-center justify-center p-6 text-center"
        >
          <div className="bg-destructive/10 text-destructive ring-destructive/5 flex size-14 items-center justify-center rounded-2xl ring-8">
            <AlertOctagon className="size-7" />
          </div>
          <h2 className="text-foreground mt-5 text-xl font-bold tracking-tight sm:text-2xl">
            Application Encountered an Error
          </h2>
          <p className="text-muted-foreground mt-2 max-w-md text-xs leading-relaxed">
            An unexpected error interrupted this view. You can reload the page or return to the
            dashboard.
          </p>

          {this.state.error && (
            <div className="bg-muted/30 text-muted-foreground mt-4 max-w-lg overflow-x-auto rounded-lg border p-3 text-left font-mono text-[11px]">
              {this.state.error.message || String(this.state.error)}
            </div>
          )}

          <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
            <Button
              type="button"
              variant="default"
              size="sm"
              onClick={this.handleReload}
              className="gap-2 text-xs font-semibold"
            >
              <RotateCcw className="size-3.5" />
              <span>Reload Page</span>
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={this.handleReset}
              className="gap-2 text-xs font-semibold"
            >
              <Home className="size-3.5" />
              <span>Go to Dashboard</span>
            </Button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

/**
 * Route-level Error Element for React Router
 */
export function RouteErrorFallback() {
  return (
    <div
      role="alert"
      className="animate-in fade-in-50 flex min-h-[60vh] flex-col items-center justify-center p-6 text-center"
    >
      <div className="bg-destructive/10 text-destructive ring-destructive/5 flex size-14 items-center justify-center rounded-2xl ring-8">
        <AlertOctagon className="size-7" />
      </div>
      <h2 className="text-foreground mt-5 text-xl font-bold tracking-tight sm:text-2xl">
        Page Failed to Load
      </h2>
      <p className="text-muted-foreground mt-2 max-w-md text-xs leading-relaxed">
        We encountered a problem loading this screen. Please try reloading or head back to your
        projects.
      </p>

      <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
        <Button
          type="button"
          variant="default"
          size="sm"
          onClick={() => window.location.reload()}
          className="gap-2 text-xs font-semibold"
        >
          <RotateCcw className="size-3.5" />
          <span>Reload</span>
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => (window.location.href = "/dashboard")}
          className="gap-2 text-xs font-semibold"
        >
          <Home className="size-3.5" />
          <span>Go to Dashboard</span>
        </Button>
      </div>
    </div>
  );
}
