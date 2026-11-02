import { describe, it, expect } from "vitest";
import { generateProjectDetails } from "./project-generator";

describe("generateProjectDetails", () => {
  it("generates scores bounded between 0 and 100", () => {
    const details = generateProjectDetails(85);
    expect(details.categoryScores.integration).toBeGreaterThanOrEqual(0);
    expect(details.categoryScores.integration).toBeLessThanOrEqual(100);
    expect(details.categoryScores.security).toBeGreaterThanOrEqual(0);
    expect(details.categoryScores.security).toBeLessThanOrEqual(100);
  });

  it("produces valid 7-character commitSha in scanMeta", () => {
    const details = generateProjectDetails(72);
    expect(details.scanMeta.commitSha).toHaveLength(7);
    expect(details.scanMeta.branch).toBe("main");
    expect(details.scanMeta.agentsRun).toBe(6);
  });

  it("returns zero critical issues for high scores (>= 85)", () => {
    const details = generateProjectDetails(95);
    expect(details.severityCounts.critical).toBe(0);
  });

  it("clamps out-of-range health scores safely", () => {
    const negative = generateProjectDetails(-20);
    expect(negative.categoryScores.integration).toBeGreaterThanOrEqual(0);

    const excessive = generateProjectDetails(150);
    expect(excessive.categoryScores.integration).toBeLessThanOrEqual(100);
  });
});
