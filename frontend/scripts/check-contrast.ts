// WCAG Contrast Checker for MergeX AI Brand Tokens
export interface RGB {
  r: number;
  g: number;
  b: number;
}

export function hexToRgb(hex: string): RGB {
  const clean = hex.replace("#", "").trim();
  if (clean.length === 3) {
    return {
      r: parseInt(clean[0] + clean[0], 16),
      g: parseInt(clean[1] + clean[1], 16),
      b: parseInt(clean[2] + clean[2], 16),
    };
  }
  return {
    r: parseInt(clean.substring(0, 2), 16),
    g: parseInt(clean.substring(2, 4), 16),
    b: parseInt(clean.substring(4, 6), 16),
  };
}

export function sRgbLuminance(rgb: RGB): number {
  const a = [rgb.r, rgb.g, rgb.b].map((v) => {
    const s = v / 255;
    return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * a[0] + 0.7152 * a[1] + 0.0722 * a[2];
}

export function contrastRatio(fgHex: string, bgHex: string): number {
  const l1 = sRgbLuminance(hexToRgb(fgHex));
  const l2 = sRgbLuminance(hexToRgb(bgHex));
  const brighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (brighter + 0.05) / (darker + 0.05);
}

export function mixColors(fgHex: string, bgHex: string, fgAlpha: number): string {
  const fg = hexToRgb(fgHex);
  const bg = hexToRgb(bgHex);
  const r = Math.round(fg.r * fgAlpha + bg.r * (1 - fgAlpha));
  const g = Math.round(fg.g * fgAlpha + bg.g * (1 - fgAlpha));
  const b = Math.round(fg.b * fgAlpha + bg.b * (1 - fgAlpha));
  return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`;
}

export interface ThemeTokens {
  background: string;
  foreground: string;
  card: string;
  cardForeground: string;
  popover: string;
  popoverForeground: string;
  primary: string;
  primaryForeground: string;
  secondary: string;
  secondaryForeground: string;
  muted: string;
  mutedForeground: string;
  accent: string;
  accentForeground: string;
  border: string;
  input: string;
  ring: string;
  destructive: string;
  brandSecondary: string;
  brandSecondaryForeground: string;
  success: string;
  sevCritical: string;
  sevHigh: string;
  sevMedium: string;
  sevLow: string;
  // Decorative feature icon tokens
  featEvergreen: string;
  featIndigo: string;
  featOrchid: string;
  featRose: string;
  featSky: string;
  featGold: string;
}

// Token values: adjusted sev-high and sev-medium slightly to guarantee 4.5:1 on 12% tint
export const lightTokens: ThemeTokens = {
  background: "#FFF3E6",
  foreground: "#381932",
  card: "#FFFAF5",
  cardForeground: "#381932",
  popover: "#FFFAF5",
  popoverForeground: "#381932",
  primary: "#381932",
  primaryForeground: "#FFF3E6",
  secondary: "#F8E5D1",
  secondaryForeground: "#381932",
  muted: "#F8E5D1",
  mutedForeground: "#693E5E",
  accent: "#D9F1E5",
  accentForeground: "#013220",
  border: "#EBD0B4",
  input: "#EBD0B4",
  ring: "#895A7E",
  destructive: "#B42318",
  brandSecondary: "#013220",
  brandSecondaryForeground: "#FFF3E6",
  success: "#167352",
  sevCritical: "#B42318",
  sevHigh: "#B83A05", // Adjusted from #C2410C to pass 4.5:1 on 12% tint (was 4.21:1 -> now 4.60:1)
  sevMedium: "#8C5905", // Adjusted from #92600A to pass 4.5:1 on 12% tint (was 4.44:1 -> now 4.71:1)
  sevLow: "#1D6F8C",
  featEvergreen: "#167352",
  featIndigo: "#4650C8",
  featOrchid: "#A1329B",
  featRose: "#BE3455",
  featSky: "#1D6FA8",
  featGold: "#946200",
};

export const darkTokens: ThemeTokens = {
  background: "#170A14",
  foreground: "#FFF3E6",
  card: "#26101F",
  cardForeground: "#FFF3E6",
  popover: "#26101F",
  popoverForeground: "#FFF3E6",
  primary: "#FFF3E6",
  primaryForeground: "#381932",
  secondary: "#381932",
  secondaryForeground: "#FFF3E6",
  muted: "#381932",
  mutedForeground: "#AC84A2",
  accent: "#06432D",
  accentForeground: "#D9F1E5",
  border: "#4D2A44",
  input: "#4D2A44",
  ring: "#AC84A2",
  destructive: "#F87171",
  brandSecondary: "#4FB68A",
  brandSecondaryForeground: "#013220",
  success: "#4FB68A",
  sevCritical: "#F87171",
  sevHigh: "#FB923C",
  sevMedium: "#FACC15",
  sevLow: "#5BC0DE",
  featEvergreen: "#4FB68A",
  featIndigo: "#A5ADFF",
  featOrchid: "#E58AD9",
  featRose: "#F58FA9",
  featSky: "#7CC4F0",
  featGold: "#F0C060",
};

interface CheckItem {
  name: string;
  fg: string;
  bg: string;
  required: number;
}

function runThemeChecks(themeName: string, tokens: ThemeTokens): boolean {
  console.log(`\n================== ${themeName.toUpperCase()} THEME ==================`);
  const checks: CheckItem[] = [
    { name: "foreground on background", fg: tokens.foreground, bg: tokens.background, required: 4.5 },
    { name: "foreground on card", fg: tokens.foreground, bg: tokens.card, required: 4.5 },
    { name: "foreground on popover", fg: tokens.foreground, bg: tokens.popover, required: 4.5 },
    { name: "foreground on muted", fg: tokens.foreground, bg: tokens.muted, required: 4.5 },
    { name: "muted-foreground on background", fg: tokens.mutedForeground, bg: tokens.background, required: 4.5 },
    { name: "muted-foreground on card", fg: tokens.mutedForeground, bg: tokens.card, required: 4.5 },
    { name: "muted-foreground on muted", fg: tokens.mutedForeground, bg: tokens.muted, required: 4.5 },
    { name: "primary-foreground on primary", fg: tokens.primaryForeground, bg: tokens.primary, required: 4.5 },
    { name: "secondary-foreground on secondary", fg: tokens.secondaryForeground, bg: tokens.secondary, required: 4.5 },
    { name: "brand-secondary-foreground on brand-secondary", fg: tokens.brandSecondaryForeground, bg: tokens.brandSecondary, required: 4.5 },
    { name: "accent-foreground on accent", fg: tokens.accentForeground, bg: tokens.accent, required: 4.5 },

    // Severity colors on background & card
    { name: "sev-critical on background", fg: tokens.sevCritical, bg: tokens.background, required: 4.5 },
    { name: "sev-critical on card", fg: tokens.sevCritical, bg: tokens.card, required: 4.5 },
    { name: "sev-high on background", fg: tokens.sevHigh, bg: tokens.background, required: 4.5 },
    { name: "sev-high on card", fg: tokens.sevHigh, bg: tokens.card, required: 4.5 },
    { name: "sev-medium on background", fg: tokens.sevMedium, bg: tokens.background, required: 4.5 },
    { name: "sev-medium on card", fg: tokens.sevMedium, bg: tokens.card, required: 4.5 },
    { name: "sev-low on background", fg: tokens.sevLow, bg: tokens.background, required: 4.5 },
    { name: "sev-low on card", fg: tokens.sevLow, bg: tokens.card, required: 4.5 },

    // Severity colors on 12% tint over card
    {
      name: "sev-critical on 12% tint",
      fg: tokens.sevCritical,
      bg: mixColors(tokens.sevCritical, tokens.card, 0.12),
      required: 4.5,
    },
    {
      name: "sev-high on 12% tint",
      fg: tokens.sevHigh,
      bg: mixColors(tokens.sevHigh, tokens.card, 0.12),
      required: 4.5,
    },
    {
      name: "sev-medium on 12% tint",
      fg: tokens.sevMedium,
      bg: mixColors(tokens.sevMedium, tokens.card, 0.12),
      required: 4.5,
    },
    {
      name: "sev-low on 12% tint",
      fg: tokens.sevLow,
      bg: mixColors(tokens.sevLow, tokens.card, 0.12),
      required: 4.5,
    },

    // Success
    { name: "success on background", fg: tokens.success, bg: tokens.background, required: 4.5 },
    { name: "success on card", fg: tokens.success, bg: tokens.card, required: 4.5 },

    // UI components / Boundaries
    { name: "ring on background (UI)", fg: tokens.ring, bg: tokens.background, required: 3.0 },

    // Feature icon decorative tokens (against card and 14% tinted tile, required: 3.0)
    { name: "feat-evergreen on card", fg: tokens.featEvergreen, bg: tokens.card, required: 3.0 },
    { name: "feat-evergreen on 14% tile", fg: tokens.featEvergreen, bg: mixColors(tokens.featEvergreen, tokens.card, 0.14), required: 3.0 },
    { name: "feat-indigo on card", fg: tokens.featIndigo, bg: tokens.card, required: 3.0 },
    { name: "feat-indigo on 14% tile", fg: tokens.featIndigo, bg: mixColors(tokens.featIndigo, tokens.card, 0.14), required: 3.0 },
    { name: "feat-orchid on card", fg: tokens.featOrchid, bg: tokens.card, required: 3.0 },
    { name: "feat-orchid on 14% tile", fg: tokens.featOrchid, bg: mixColors(tokens.featOrchid, tokens.card, 0.14), required: 3.0 },
    { name: "feat-rose on card", fg: tokens.featRose, bg: tokens.card, required: 3.0 },
    { name: "feat-rose on 14% tile", fg: tokens.featRose, bg: mixColors(tokens.featRose, tokens.card, 0.14), required: 3.0 },
    { name: "feat-sky on card", fg: tokens.featSky, bg: tokens.card, required: 3.0 },
    { name: "feat-sky on 14% tile", fg: tokens.featSky, bg: mixColors(tokens.featSky, tokens.card, 0.14), required: 3.0 },
    { name: "feat-gold on card", fg: tokens.featGold, bg: tokens.card, required: 3.0 },
    { name: "feat-gold on 14% tile", fg: tokens.featGold, bg: mixColors(tokens.featGold, tokens.card, 0.14), required: 3.0 },
  ];

  let allPassed = true;
  console.log(
    `${"Pair".padEnd(45)} | ${"FG".padEnd(9)} | ${"BG".padEnd(9)} | ${"Ratio".padEnd(7)} | ${"Req".padEnd(5)} | Status`
  );
  console.log("-".repeat(90));

  for (const c of checks) {
    const ratio = contrastRatio(c.fg, c.bg);
    const passed = ratio >= c.required;
    if (!passed) allPassed = false;
    const ratioStr = ratio.toFixed(2) + ":1";
    const status = passed ? "✓ PASS" : "✗ FAIL";
    console.log(
      `${c.name.padEnd(45)} | ${c.fg.padEnd(9)} | ${c.bg.padEnd(9)} | ${ratioStr.padEnd(7)} | ${c.required.toFixed(1).padEnd(5)} | ${status}`
    );
  }

  // Also print decorative border ratio for reference
  const borderRatio = contrastRatio(tokens.border, tokens.background);
  console.log(
    `${"border on background (card has surface fill)".padEnd(45)} | ${tokens.border.padEnd(9)} | ${tokens.background.padEnd(9)} | ${(borderRatio.toFixed(2) + ":1").padEnd(7)} | ${"N/A".padEnd(5)} | (WCAG 1.4.11 fill exempt)`
  );

  return allPassed;
}

export function main() {
  const lightPass = runThemeChecks("Light", lightTokens);
  const darkPass = runThemeChecks("Dark", darkTokens);

  console.log("\n========================================================");
  if (lightPass && darkPass) {
    console.log("All WCAG Contrast Checks PASSED for both Light and Dark themes!");
    process.exit(0);
  } else {
    console.error("Some contrast checks FAILED. Adjusting tokens may be required.");
    process.exit(1);
  }
}

main();
