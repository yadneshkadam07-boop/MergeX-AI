"""Health scoring, including the edge cases that make a score trustworthy."""

from __future__ import annotations

import pytest

from app.analysis.findings import Finding, make_finding
from app.analysis.scoring import MAX_SCORE, MIN_SCORE, score_findings
from app.models.enums import IssueCategory, Severity
from app.services.parsers.base import SourceLocation


def finding(
    rule_id: str,
    *,
    severity: Severity | None = None,
    identity: tuple[object, ...] = ("x",),
) -> Finding:
    return make_finding(
        rule_id,
        identity=identity,  # type: ignore[arg-type]
        locations=[SourceLocation(file_path="a.py", line_start=1, line_end=1, snippet="x")],
        description="d",
        severity=severity,
    )


def api(severity: Severity, tag: object = "a") -> Finding:
    return finding("MX-API-001", severity=severity, identity=(tag,))


def schema(severity: Severity, tag: object = "s") -> Finding:
    return finding("MX-DB-001", severity=severity, identity=(tag,))


class TestDeductionTable:
    @pytest.mark.parametrize(
        ("severity", "expected"),
        [
            (Severity.CRITICAL, 85),
            (Severity.HIGH, 92),
            (Severity.MEDIUM, 97),
            (Severity.LOW, 99),
        ],
    )
    def test_one_issue_deducts_the_right_amount(self, severity: Severity, expected: int) -> None:
        assert score_findings([api(severity)]).score == expected

    def test_deductions_accumulate(self) -> None:
        findings = [
            api(Severity.CRITICAL, 1),
            api(Severity.HIGH, 2),
            api(Severity.MEDIUM, 3),
            api(Severity.LOW, 4),
        ]

        # 100 - 15 - 8 - 3 - 1
        assert score_findings(findings).score == 73

    def test_each_severity_matches_the_enum(self) -> None:
        """The table lives on the enum; scoring must not keep its own copy."""
        assert Severity.CRITICAL.score_penalty == 15
        assert Severity.HIGH.score_penalty == 8
        assert Severity.MEDIUM.score_penalty == 3
        assert Severity.LOW.score_penalty == 1


class TestEdgeCases:
    def test_zero_issues_scores_one_hundred(self) -> None:
        result = score_findings([])

        assert result.score == MAX_SCORE
        assert result.total_issues == 0
        assert result.is_perfect
        assert not result.is_floored

    def test_the_score_floors_at_zero(self) -> None:
        """Seven criticals is -105, which must not become a negative score."""
        findings = [api(Severity.CRITICAL, index) for index in range(7)]

        result = score_findings(findings)

        assert result.score == MIN_SCORE
        assert result.is_floored

    def test_exactly_one_hundred_points_of_deductions_reaches_zero(self) -> None:
        # 6 criticals (90) + 1 medium (3) + 7 low (7) = 100
        findings = [
            *[api(Severity.CRITICAL, f"c{index}") for index in range(6)],
            api(Severity.MEDIUM, "m"),
            *[api(Severity.LOW, f"l{index}") for index in range(7)],
        ]

        assert score_findings(findings).score == 0

    def test_a_single_point_above_the_floor(self) -> None:
        # 6 criticals (90) + 3 medium (9) = 99
        findings = [
            *[api(Severity.CRITICAL, f"c{index}") for index in range(6)],
            *[api(Severity.MEDIUM, f"m{index}") for index in range(3)],
        ]

        result = score_findings(findings)

        assert result.score == 1
        assert not result.is_floored

    def test_a_perfect_score_is_not_floored(self) -> None:
        assert not score_findings([]).is_floored

    def test_a_floored_score_with_no_issues_is_impossible(self) -> None:
        """is_floored must not fire on an empty, perfect result."""
        result = score_findings([])

        assert result.score == 100
        assert result.is_floored is False


class TestCategorySubScores:
    def test_one_broken_category_leaves_the_others_clean(self) -> None:
        """The headline case: a broken schema must not dirty the API score."""
        findings = [schema(Severity.CRITICAL, 1), schema(Severity.HIGH, 2)]

        result = score_findings(findings)

        assert result.categories["schema"].score == 77  # 100 - 15 - 8
        assert result.categories["api_contract"].score == 100
        assert result.categories["security"].score == 100
        assert result.categories["dependency"].score == 100
        assert result.score == 77

    def test_each_category_is_scored_over_its_own_issues_only(self) -> None:
        findings = [api(Severity.CRITICAL), schema(Severity.LOW)]

        result = score_findings(findings)

        assert result.categories["api_contract"].score == 85
        assert result.categories["schema"].score == 99
        assert result.score == 84  # 100 - 15 - 1

    def test_a_category_can_floor_while_the_total_does_not(self) -> None:
        findings = [schema(Severity.CRITICAL, index) for index in range(7)]

        result = score_findings(findings)

        assert result.categories["schema"].score == 0
        assert result.score == 0

    def test_every_category_is_always_present(self) -> None:
        """A stable shape means the UI needs no conditionals."""
        result = score_findings([])

        assert set(result.categories) == {category.value for category in IssueCategory}

    def test_issue_counts_are_per_category(self) -> None:
        findings = [api(Severity.LOW, 1), api(Severity.LOW, 2), schema(Severity.LOW, 3)]

        result = score_findings(findings)

        assert result.categories["api_contract"].issue_count == 2
        assert result.categories["schema"].issue_count == 1
        assert result.categories["security"].issue_count == 0
        assert result.categories["security"].is_clean

    def test_unanalysed_categories_are_marked(self) -> None:
        """'No database' is not the same as 'a perfect database'."""
        result = score_findings([], categories_analysed={IssueCategory.SECURITY})

        assert result.categories["security"].analysed is True
        assert result.categories["schema"].analysed is False
        # Still 100, so it cannot drag the total down.
        assert result.categories["schema"].score == 100

    def test_all_categories_analysed_by_default(self) -> None:
        result = score_findings([])

        assert all(category.analysed for category in result.categories.values())


class TestSeverityCounts:
    def test_counts_every_level_even_at_zero(self) -> None:
        result = score_findings([api(Severity.CRITICAL)])

        assert result.severity_counts == {
            "critical": 1,
            "high": 0,
            "medium": 0,
            "low": 0,
        }

    def test_counts_are_per_category_too(self) -> None:
        findings = [api(Severity.CRITICAL), schema(Severity.LOW)]

        result = score_findings(findings)

        assert result.categories["api_contract"].severity_counts["critical"] == 1
        assert result.categories["schema"].severity_counts["low"] == 1
        assert result.categories["schema"].severity_counts["critical"] == 0


class TestSerialisation:
    def test_round_trips_as_json(self) -> None:
        import json

        payload = score_findings([api(Severity.HIGH)]).to_dict()

        assert json.loads(json.dumps(payload)) == payload

    def test_includes_the_breakdown(self) -> None:
        payload = score_findings([api(Severity.HIGH)]).to_dict()

        assert payload["score"] == 92
        assert payload["total_issues"] == 1
        assert payload["categories"]["api_contract"]["score"] == 92
        assert payload["categories"]["api_contract"]["analysed"] is True
