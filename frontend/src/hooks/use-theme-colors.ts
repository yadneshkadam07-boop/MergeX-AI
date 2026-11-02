import { useState, useEffect } from "react";

export interface ResolvedThemeColors {
  background: string;
  foreground: string;
  card: string;
  cardForeground: string;
  border: string;
  muted: string;
  mutedForeground: string;
  primary: string;
  success: string;
  sevCritical: string;
  sevHigh: string;
  sevMedium: string;
  sevLow: string;
  brandSecondary: string;
  isDark: boolean;
}

function getCssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const val = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return val || fallback;
}

export function useThemeColors(): ResolvedThemeColors {
  const [colors, setColors] = useState<ResolvedThemeColors>(() => {
    const isDark =
      typeof document !== "undefined" && document.documentElement.classList.contains("dark");
    return {
      background: isDark ? "#170A14" : "#FFF3E6",
      foreground: isDark ? "#FFF3E6" : "#381932",
      card: isDark ? "#26101F" : "#FFFAF5",
      cardForeground: isDark ? "#FFF3E6" : "#381932",
      border: isDark ? "#4D2A44" : "#EBD0B4",
      muted: isDark ? "#381932" : "#F8E5D1",
      mutedForeground: isDark ? "#AC84A2" : "#693E5E",
      primary: isDark ? "#FFF3E6" : "#381932",
      success: isDark ? "#4FB68A" : "#167352",
      sevCritical: isDark ? "#F87171" : "#B42318",
      sevHigh: isDark ? "#FB923C" : "#B83A05",
      sevMedium: isDark ? "#FACC15" : "#8C5905",
      sevLow: isDark ? "#5BC0DE" : "#1D6F8C",
      brandSecondary: isDark ? "#4FB68A" : "#013220",
      isDark,
    };
  });

  useEffect(() => {
    const updateColors = () => {
      const isDark = document.documentElement.classList.contains("dark");
      setColors({
        background: getCssVar("--background", isDark ? "#170A14" : "#FFF3E6"),
        foreground: getCssVar("--foreground", isDark ? "#FFF3E6" : "#381932"),
        card: getCssVar("--card", isDark ? "#26101F" : "#FFFAF5"),
        cardForeground: getCssVar("--card-foreground", isDark ? "#FFF3E6" : "#381932"),
        border: getCssVar("--border", isDark ? "#4D2A44" : "#EBD0B4"),
        muted: getCssVar("--muted", isDark ? "#381932" : "#F8E5D1"),
        mutedForeground: getCssVar("--muted-foreground", isDark ? "#AC84A2" : "#693E5E"),
        primary: getCssVar("--primary", isDark ? "#FFF3E6" : "#381932"),
        success: getCssVar("--success", isDark ? "#4FB68A" : "#167352"),
        sevCritical: getCssVar("--sev-critical", isDark ? "#F87171" : "#B42318"),
        sevHigh: getCssVar("--sev-high", isDark ? "#FB923C" : "#B83A05"),
        sevMedium: getCssVar("--sev-medium", isDark ? "#FACC15" : "#8C5905"),
        sevLow: getCssVar("--sev-low", isDark ? "#5BC0DE" : "#1D6F8C"),
        brandSecondary: getCssVar("--brand-secondary", isDark ? "#4FB68A" : "#013220"),
        isDark,
      });
    };

    updateColors();

    const observer = new MutationObserver((mutations) => {
      for (const m of mutations) {
        if (m.type === "attributes" && m.attributeName === "class") {
          updateColors();
          break;
        }
      }
    });

    observer.observe(document.documentElement, { attributes: true });
    return () => observer.disconnect();
  }, []);

  return colors;
}
