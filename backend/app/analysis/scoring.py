"""Health scoring.

The formula, fixed by the product spec: start at 100, deduct 15 per critical
issue, 8 per high, 3 per medium, 1 per low, and floor at 0.

Two things are deliberate and worth stating because they look like bugs
otherwise:

**A category with no issues scores 100, not "n/a".** A project with no
database has a perfect schema score. That is defensible -- there is nothing
wrong with its schema -- and :attr:`CategoryScore.issue_count` plus
:attr:`analysed` let the UI distinguish "clean" from "nothing to check".

**Deductions are per issue, not per occurrence.** A finding merged from three
call sites is one deduction. Counting occurrences would let a single typo in a
shared helper dominate a score, which would make the number say more about
code structure than about correctness.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Final

from app.analysis.findings import Finding
from app.models.enums import SEVERITY_ORDER, IssueCategory

__all__ = [
    "MAX_SCORE",
    "MIN_SCORE",
    "CategoryScore",
    "HealthScore",
    "score_findings",
]

MAX_SCORE: Final[int] = 100
MIN_SCORE: Final[int] = 0


@dataclass(frozen=True, slots=True)
class CategoryScore:
    """The score for one category, computed over that category's issues only."""

    category: IssueCategory
    score: int
    issue_count: int
    severity_counts: dict[str, int]
    analysed: bool = True
    """False when the project has nothing of this kind to check at all.

    A project with no migrations has not *passed* the schema checks; there
    were none to run. The score is still 100 so it cannot drag the total
    down, but the UI should say "not applicable" rather than "perfect".
    """

    @property
    def is_clean(self) -> bool:
        return self.issue_count == 0


@dataclass(frozen=True, slots=True)
class HealthScore:
    """The overall score plus its per-category breakdown."""

    score: int
    total_issues: int
    severity_counts: dict[str, int]
    categories: dict[str, CategoryScore] = field(default_factory=dict)

    @property
    def is_perfect(self) -> bool:
        return self.score == MAX_SCORE and self.total_issues == 0

    @property
    def is_floored(self) -> bool:
        """True when the deductions exceeded 100 and the score was clamped.

        Worth surfacing: a floored score means "at least this bad", and two
        floored projects are not equally bad.
        """
        return self.score == MIN_SCORE and self.total_issues > 0

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable form, as persisted on the analysis row.

        Typed ``Any`` rather than ``object`` because this is a JSON
        document whose nested values callers index into, and because it
        lands in a JSONB column declared the same way.
        """
        return {
            "score": self.score,
            "total_issues": self.total_issues,
            "severity_counts": dict(self.severity_counts),
            "categories": {
                name: {
                    "score": category.score,
                    "issue_count": category.issue_count,
                    "severity_counts": dict(category.severity_counts),
                    "analysed": category.analysed,
                }
                for name, category in self.categories.items()
            },
        }


def score_findings(
    findings: list[Finding],
    *,
    categories_analysed: set[IssueCategory] | None = None,
) -> HealthScore:
    """Compute the health score and sub-scores for a set of findings.

    Args:
        findings: Deduplicated findings. Pass the output of
            :func:`app.analysis.findings.deduplicate`, not the raw rule
            output, or one defect found twice will be deducted twice.
        categories_analysed: Categories the run was actually able to check.
            A category omitted here reports ``analysed=False``. Defaults to
            all of them.
    """
    analysed = set(IssueCategory) if categories_analysed is None else set(categories_analysed)

    overall = _deduct(findings)
    severity_counts = _count_severities(findings)

    category_scores: dict[str, CategoryScore] = {}
    for category in IssueCategory:
        in_category = [finding for finding in findings if finding.category is category]
        category_scores[category.value] = CategoryScore(
            category=category,
            score=_deduct(in_category),
            issue_count=len(in_category),
            severity_counts=_count_severities(in_category),
            analysed=category in analysed,
        )

    return HealthScore(
        score=overall,
        total_issues=len(findings),
        severity_counts=severity_counts,
        categories=category_scores,
    )


def _deduct(findings: list[Finding]) -> int:
    """Apply the deduction table and clamp to the valid range."""
    total = sum(finding.severity.score_penalty for finding in findings)
    return max(MIN_SCORE, MAX_SCORE - total)


def _count_severities(findings: list[Finding]) -> dict[str, int]:
    """Counts per severity, always listing every level so the UI is stable."""
    counter = Counter(finding.severity for finding in findings)
    return {severity.value: counter.get(severity, 0) for severity in SEVERITY_ORDER}
