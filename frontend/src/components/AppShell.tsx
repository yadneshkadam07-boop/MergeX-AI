import { Moon, Sun } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { useTheme } from "@/hooks/use-theme";
import { cn } from "@/lib/utils";

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={toggle}
      aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
    >
      {theme === "dark" ? (
        <Sun className="size-4" aria-hidden />
      ) : (
        <Moon className="size-4" aria-hidden />
      )}
    </Button>
  );
}

/** Header, width constraint and footer, shared by every page. */
export function AppShell({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-border/70 bg-background/80 sticky top-0 z-20 border-b backdrop-blur">
        <div className="mx-auto flex h-14 w-full max-w-7xl items-center justify-between gap-4 px-4 sm:px-6">
          <Link to="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <span className="bg-foreground text-background flex size-6 items-center justify-center rounded text-xs font-bold">
              M
            </span>
            MergeX AI
          </Link>
          <div className="flex items-center gap-1">
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className={cn("mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6", className)}>
        {children}
      </main>

      <footer className="border-border/70 border-t">
        <p className="text-muted-foreground mx-auto w-full max-w-7xl px-4 py-5 text-xs sm:px-6">
          Findings come from deterministic analysis. A language model only explains them — it cannot
          add, remove or re-rank a finding.
        </p>
      </footer>
    </div>
  );
}
