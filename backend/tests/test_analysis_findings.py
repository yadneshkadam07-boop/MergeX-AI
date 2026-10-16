"""Findings: fingerprints, deduplication, and secret redaction.

The redaction tests are security tests. A scanner that finds a hardcoded API
key and then stores that key verbatim in its own issue table -- which is
served over an API and rendered in a browser -- has moved the secret, not
reported it.
"""

from __future__ import annotations

import pytest

from app.analysis.findings import Finding, deduplicate, make_finding
from app.models.enums import IssueCategory, Severity
from app.services.parsers.base import SourceLocation


def location(file_path: str = "a.ts", line: int = 1, snippet: str = "x = 1") -> SourceLocation:
    return SourceLocation(file_path=file_path, line_start=line, line_end=line, snippet=snippet)


def build(
    rule_id: str = "MX-API-001",
    *,
    identity: tuple[object, ...] = ("GET", "/a"),
    locations: list[SourceLocation] | None = None,
    **kwargs: object,
) -> Finding:
    return make_finding(
        rule_id,
        identity=identity,  # type: ignore[arg-type]
        locations=locations or [location()],
        description="description",
        **kwargs,  # type: ignore[arg-type]
    )


class TestConstruction:
    def test_fills_fields_from_the_taxonomy(self) -> None:
        finding = build("MX-API-001")

        assert finding.category is IssueCategory.API_CONTRACT
        assert finding.severity is Severity.CRITICAL
        assert finding.title == "Frontend calls an endpoint the backend does not define"
        assert finding.confidence == 1.0

    def test_severity_can_be_overridden_by_data(self) -> None:
        """A dependency advisory's severity comes from the advisory."""
        finding = build("MX-DEP-001", severity=Severity.LOW)

        assert finding.severity is Severity.LOW

    def test_confidence_can_be_weakened(self) -> None:
        finding = build("MX-SEC-001", confidence=0.6)

        assert finding.confidence == 0.6

    def test_rejects_an_unknown_rule(self) -> None:
        with pytest.raises(KeyError, match="MX-NOPE-001"):
            build("MX-NOPE-001")

    def test_rejects_a_finding_with_no_location(self) -> None:
        """An issue with nowhere to point at cannot be rendered."""
        with pytest.raises(ValueError, match="at least one location"):
            Finding(
                rule_id="MX-API-001",
                category=IssueCategory.API_CONTRACT,
                severity=Severity.HIGH,
                title="t",
                description="d",
                locations=(),
                fingerprint="f",
                confidence=1.0,
            )

    @pytest.mark.parametrize("confidence", [0.0, -0.1, 1.1])
    def test_rejects_confidence_outside_the_range(self, confidence: float) -> None:
        with pytest.raises(ValueError, match="confidence"):
            build(confidence=confidence)

    def test_primary_location_is_the_first(self) -> None:
        first = location("a.ts", 5)
        second = location("b.ts", 9)

        finding = build(locations=[first, second])

        assert finding.primary_location == first
        assert finding.occurrence_count == 2

    def test_duplicate_locations_are_collapsed(self) -> None:
        finding = build(locations=[location("a.ts", 1), location("a.ts", 1)])

        assert finding.occurrence_count == 1


class TestFingerprints:
    def test_the_same_defect_fingerprints_identically(self) -> None:
        first = build(identity=("GET", "/api/users"))
        second = build(identity=("GET", "/api/users"))

        assert first.fingerprint == second.fingerprint

    def test_different_defects_differ(self) -> None:
        first = build(identity=("GET", "/api/users"))
        second = build(identity=("GET", "/api/orders"))

        assert first.fingerprint != second.fingerprint

    def test_the_rule_is_part_of_the_identity(self) -> None:
        first = build("MX-API-001", identity=("GET", "/a"))
        second = build("MX-API-002", identity=("GET", "/a"))

        assert first.fingerprint != second.fingerprint

    def test_location_does_not_affect_the_fingerprint(self) -> None:
        """The same root cause in two files is one defect, so one fingerprint."""
        first = build(locations=[location("a.ts", 1)])
        second = build(locations=[location("b.ts", 99)])

        assert first.fingerprint == second.fingerprint

    def test_fingerprints_are_stable_across_runs(self) -> None:
        """Needed to recognise the same issue in a later analysis."""
        assert build().fingerprint == build().fingerprint

    def test_fingerprint_fits_the_database_column(self) -> None:
        finding = build()

        assert len(finding.fingerprint) == 32
        assert all(character in "0123456789abcdef" for character in finding.fingerprint)

    def test_none_in_the_identity_is_handled(self) -> None:
        assert build(identity=(None, "/a")).fingerprint


class TestRedaction:
    SECRET = "sk_live_51H8xQ2KmNvR7pLdX4bWcZaYeTfUgIhJkOm"

    def test_the_secret_is_masked_in_the_evidence(self) -> None:
        finding = build(
            "MX-SEC-001",
            identity=("config.ts", "KEY"),
            locations=[location("config.ts", 3, f'const KEY = "{self.SECRET}";')],
            secrets=(self.SECRET,),
        )

        assert self.SECRET not in finding.evidence
        assert "const KEY" in finding.evidence
        assert finding.evidence.count("*") >= 8

    def test_the_tail_is_kept_so_the_credential_is_recognisable(self) -> None:
        finding = build(
            "MX-SEC-001",
            identity=("a", "b"),
            locations=[location("a.ts", 1, f'k = "{self.SECRET}"')],
            secrets=(self.SECRET,),
        )

        assert finding.evidence.endswith('JkOm"')

    def test_several_secrets_are_all_masked(self) -> None:
        other = "AKIAIOSFODNN7EXAMPLE"
        finding = build(
            "MX-SEC-004",
            identity=(".env",),
            locations=[location(".env", 1, f"A={self.SECRET}\nB={other}")],
            secrets=(self.SECRET, other),
        )

        assert self.SECRET not in finding.evidence
        assert other not in finding.evidence

    def test_evidence_is_untouched_when_there_are_no_secrets(self) -> None:
        finding = build(locations=[location("a.ts", 1, "const x = 1;")])

        assert finding.evidence == "const x = 1;"

    def test_long_evidence_is_truncated(self) -> None:
        finding = build(locations=[location("a.ts", 1, "x" * 5000)])

        assert len(finding.evidence) < 2100
        assert finding.evidence.endswith("…")


class TestDeduplication:
    def test_the_same_defect_from_two_files_becomes_one_finding(self) -> None:
        """A typo'd path called from two components is one issue."""
        first = build(locations=[location("a.ts", 1)])
        second = build(locations=[location("b.ts", 2)])

        merged = deduplicate([first, second])

        assert len(merged) == 1
        assert merged[0].occurrence_count == 2
        assert {loc.file_path for loc in merged[0].locations} == {"a.ts", "b.ts"}

    def test_distinct_defects_are_kept_apart(self) -> None:
        first = build(identity=("GET", "/a"))
        second = build(identity=("GET", "/b"))

        assert len(deduplicate([first, second])) == 2

    def test_merged_locations_are_recorded_in_metadata(self) -> None:
        merged = deduplicate(
            [build(locations=[location("a.ts", 1)]), build(locations=[location("b.ts", 2)])]
        )

        assert "occurrences" in merged[0].metadata
        assert len(merged[0].metadata["occurrences"]) == 2

    def test_a_single_occurrence_gains_no_occurrences_key(self) -> None:
        merged = deduplicate([build()])

        assert "occurrences" not in merged[0].metadata

    def test_the_worst_severity_wins(self) -> None:
        """A defect is as bad as its worst occurrence."""
        low = build("MX-DEP-001", severity=Severity.LOW)
        critical = build("MX-DEP-001", severity=Severity.CRITICAL)

        merged = deduplicate([low, critical])

        assert len(merged) == 1
        assert merged[0].severity is Severity.CRITICAL

    def test_the_highest_confidence_wins(self) -> None:
        merged = deduplicate([build(confidence=0.5), build(confidence=0.9)])

        assert merged[0].confidence == 0.9

    def test_metadata_is_unioned(self) -> None:
        merged = deduplicate([build(metadata={"a": 1}), build(metadata={"b": 2})])

        assert merged[0].metadata["a"] == 1
        assert merged[0].metadata["b"] == 2

    def test_output_is_ordered_by_severity(self) -> None:
        findings = [
            build("MX-DB-005", identity=("t", "low")),
            build("MX-API-001", identity=("GET", "/critical")),
            build("MX-API-003", identity=("GET", "/high")),
            build("MX-DB-004", identity=("t", "medium")),
        ]

        severities = [finding.severity for finding in deduplicate(findings)]

        assert severities == [
            Severity.CRITICAL,
            Severity.HIGH,
            Severity.MEDIUM,
            Severity.LOW,
        ]

    def test_ordering_is_deterministic(self) -> None:
        """Two runs over the same code must produce identical reports."""
        findings = [
            build(
                "MX-API-001",
                identity=("GET", f"/p{index}"),
                locations=[location(f"f{index}.ts", index + 1)],
            )
            for index in range(6)
        ]

        first = [str(finding.primary_location) for finding in deduplicate(findings)]
        second = [
            str(finding.primary_location) for finding in deduplicate(list(reversed(findings)))
        ]

        assert first == second

    def test_an_empty_list_deduplicates_to_nothing(self) -> None:
        assert deduplicate([]) == []
