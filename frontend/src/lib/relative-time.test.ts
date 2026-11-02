import { describe, it, expect } from "vitest";
import { formatRelativeTime } from "./utils";

describe("formatRelativeTime", () => {
  it("returns 'recently' on invalid date strings", () => {
    expect(formatRelativeTime("invalid-date")).toBe("recently");
  });

  it("returns 'just now' for times under 60 seconds ago", () => {
    const date = new Date(Date.now() - 30 * 1000).toISOString();
    expect(formatRelativeTime(date)).toBe("just now");
  });

  it("returns '1 minute ago' or minutes ago", () => {
    const oneMin = new Date(Date.now() - 65 * 1000).toISOString();
    expect(formatRelativeTime(oneMin)).toBe("1 minute ago");

    const tenMin = new Date(Date.now() - 10 * 60 * 1000).toISOString();
    expect(formatRelativeTime(tenMin)).toBe("10 minutes ago");
  });

  it("returns hours ago correctly", () => {
    const twoHours = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
    expect(formatRelativeTime(twoHours)).toBe("2 hours ago");
  });

  it("returns 'yesterday' for 1 day ago", () => {
    const oneDay = new Date(Date.now() - 25 * 60 * 60 * 1000).toISOString();
    expect(formatRelativeTime(oneDay)).toBe("yesterday");
  });

  it("returns days ago correctly", () => {
    const fiveDays = new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString();
    expect(formatRelativeTime(fiveDays)).toBe("5 days ago");
  });
});
