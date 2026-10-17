import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ScoreGauge } from "@/components/ScoreGauge";
import { countIssues, scoreTone } from "@/lib/severity";

describe("scoreTone", () => {
  it.each([
    [100, "Healthy"],
    [90, "Healthy"],
    [89, "Needs attention"],
    [70, "Needs attention"],
    [69, "Poor"],
    [40, "Poor"],
    [39, "Critical"],
    [0, "Critical"],
  ])("bands %i as %s", (score, label) => {
    expect(scoreTone(score).label).toBe(label);
  });

  it("uses a severity token for every band, so colours stay consistent", () => {
    for (const score of [100, 80, 50, 10]) {
      expect(scoreTone(score).cssVar).toMatch(/^var\(--severity-[a-z]+\)$/);
    }
  });
});

describe("countIssues", () => {
  it("sums the tallies", () => {
    expect(countIssues({ critical: 1, high: 2, medium: 3, low: 4 })).toBe(10);
  });

  it("treats absent severities as zero", () => {
    expect(countIssues({ high: 2 })).toBe(2);
  });

  it("is zero for an empty report", () => {
    expect(countIssues({})).toBe(0);
  });
});

describe("ScoreGauge", () => {
  it("shows the score it is given", () => {
    render(<ScoreGauge score={46} />);

    expect(screen.getByText("46")).toBeInTheDocument();
  });

  it("labels the score for assistive technology", () => {
    render(<ScoreGauge score={46} />);

    expect(screen.getByLabelText("Health score 46 out of 100")).toBeInTheDocument();
  });

  it("shows a perfect score as healthy", () => {
    render(<ScoreGauge score={100} />);

    expect(screen.getByText("100")).toBeInTheDocument();
    expect(screen.getByText("Healthy")).toBeInTheDocument();
  });

  it("shows zero rather than treating it as missing", () => {
    render(<ScoreGauge score={0} />);

    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.getByText("Critical")).toBeInTheDocument();
  });

  it("says when the score was clamped, because two zeros are not equal", () => {
    render(<ScoreGauge score={0} isFloored />);

    expect(screen.getByText("Critical · floored")).toBeInTheDocument();
  });

  it("does not mention flooring otherwise", () => {
    render(<ScoreGauge score={0} />);

    expect(screen.queryByText(/floored/)).not.toBeInTheDocument();
  });

  it("renders a caption when given one", () => {
    render(<ScoreGauge score={72} caption="5 issues across 128 files" />);

    expect(screen.getByText("5 issues across 128 files")).toBeInTheDocument();
  });

  it("omits the caption element when there is none", () => {
    const { container } = render(<ScoreGauge score={72} />);

    expect(container.querySelector("p")).toBeNull();
  });

  it("colours the number by band", () => {
    render(<ScoreGauge score={95} />);

    expect(screen.getByText("95")).toHaveStyle({ color: "var(--severity-ok)" });
  });

  it("colours a failing score critically", () => {
    render(<ScoreGauge score={12} />);

    expect(screen.getByText("12")).toHaveStyle({ color: "var(--severity-critical)" });
  });
});
