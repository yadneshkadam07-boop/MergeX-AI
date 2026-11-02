import React from "react";
import { cn } from "@/lib/utils";

interface LogoProps extends React.HTMLAttributes<HTMLDivElement> {
  showWordmark?: boolean;
  size?: "sm" | "md" | "lg";
}

/**
 * Placeholder Logo component for MergeX AI.
 * Clearly marked as a placeholder until the official brand logo is provided.
 */
export function Logo({ showWordmark = true, size = "md", className, ...props }: LogoProps) {
  const iconSizes = {
    sm: "size-6 text-xs",
    md: "size-8 text-sm",
    lg: "size-10 text-base",
  };

  const textSizes = {
    sm: "text-base",
    md: "text-lg",
    lg: "text-xl",
  };

  return (
    <div
      data-testid="mergex-logo-placeholder"
      className={cn(
        "text-foreground inline-flex items-center gap-2.5 font-bold tracking-tight select-none",
        className,
      )}
      {...props}
    >
      {/* Icon badge placeholder */}
      <div
        className={cn(
          "bg-primary text-primary-foreground ring-border/50 flex shrink-0 items-center justify-center rounded-lg font-black shadow-xs ring-1",
          iconSizes[size],
        )}
        aria-label="MergeX AI Logo mark"
      >
        M
      </div>

      {showWordmark && (
        <span className={cn("font-bold tracking-tight", textSizes[size])}>
          MergeX <span className="text-muted-foreground font-medium">AI</span>
        </span>
      )}
    </div>
  );
}
