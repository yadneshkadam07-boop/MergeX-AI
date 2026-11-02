import React from "react";
import type { FeatureTone } from "@/content/landing";
import { cn } from "@/lib/utils";

const TONE_VARIABLES: Record<FeatureTone, string> = {
  evergreen: "var(--feat-evergreen)",
  indigo: "var(--feat-indigo)",
  orchid: "var(--feat-orchid)",
  rose: "var(--feat-rose)",
  sky: "var(--feat-sky)",
  gold: "var(--feat-gold)",
};

export interface FeatureIconProps {
  icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean | "true" | "false" }>;
  tone: FeatureTone;
  className?: string;
}

export function FeatureIcon({ icon: Icon, tone, className }: FeatureIconProps) {
  const toneVar = TONE_VARIABLES[tone];

  return (
    <div
      style={
        {
          "--tone": toneVar,
        } as React.CSSProperties
      }
      className={cn(
        "flex size-10 shrink-0 items-center justify-center rounded-lg border",
        // Tile resting background: 14% tint over card
        "bg-[color-mix(in_srgb,var(--tone)_14%,transparent)]",
        // Tile border: 1px at ~28% opacity of tone
        "border-[color-mix(in_srgb,var(--tone)_28%,transparent)]",
        // Smooth 200ms ease-out transitions
        "transition-colors duration-200 ease-out",
        // Hover: tint rises to ~22% on pointing devices with hover support (preventing sticky touch hover)
        "[@media(hover:hover)]:group-hover:bg-[color-mix(in_srgb,var(--tone)_22%,transparent)]",
        className,
      )}
    >
      <Icon
        aria-hidden="true"
        className={cn(
          "size-5 text-[var(--tone)] transition-transform duration-200 ease-out",
          // Scale to 1.08 on parent card hover/focus
          "[@media(hover:hover)]:group-hover:scale-[1.08]",
          // Respect prefers-reduced-motion: keep tint change, disable scale
          "motion-reduce:group-hover:scale-100",
        )}
      />
    </div>
  );
}
