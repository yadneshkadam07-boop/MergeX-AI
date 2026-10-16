"""The explanation contract.

The central guarantee under test: **a language model cannot change the
finding set.** `apply_explanations` iterates over findings and looks each one
up, so an invented entry is dropped and a missing one leaves the finding
untouched. That is a structural property, not a prompt instruction, and it is
asserted here directly.
"""

from __future__ import annotations

import pytest

from app.analysis.findings import Finding, make_finding
from app.models.enums import Severity
from app.services.explanations import (
    MAX_BATCH_CHARS,
    MAX_FINDINGS_PER_BATCH,
    Explanation,
    ExplanationResult,
    TemplateExplainer,
    TokenUsage,
    apply_explanations,
    batch_findings,
    build_batch_prompt,
    estimate_tokens,
    merge_results,
    redact_prompt,
)
from app.services.parsers.base import SourceLocation


def finding(
    rule_id: str = "MX-API-001",
    *,
    identity: tuple[object, ...] = ("GET", "/a"),
    evidence: str = 'api.get("/a");',
    **kwargs: object,
) -> Finding:
    return make_finding(
        rule_id,
        identity=identity,  # type: ignore[arg-type]
        locations=[
            SourceLocation(file_path="src/api.ts", line_start=7, line_end=7, snippet=evidence)
        ],
        description="A description.",
        expected="expected",
        actual="actual",
        **kwargs,  # type: ignore[arg-type]
    )


def explanation(fingerprint: str, *, source: str = "gemini") -> Explanation:
    return Explanation(
        fingerprint=fingerprint,
        explanation="Because of X.",
        suggested_fix="Change line 7.",
        source=source,
        fix_before="before();",
        fix_after="after();",
    )


class TestApplyExplanationsCannotChangeFindings:
    """The guarantee that makes the LLM safe to use at all."""

    def test_the_finding_set_is_identical(self) -> None:
        findings = [finding(identity=("GET", f"/p{i}")) for i in range(4)]
        result = ExplanationResult(
            explanations={f.fingerprint: explanation(f.fingerprint) for f in findings}
        )

        explained = apply_explanations(findings, result)

        assert [f.fingerprint for f in explained] == [f.fingerprint for f in findings]
        assert [f.rule_id for f in explained] == [f.rule_id for f in findings]
        assert [f.severity for f in explained] == [f.severity for f in findings]
        assert [f.locations for f in explained] == [f.locations for f in findings]

    def test_an_invented_finding_is_discarded(self) -> None:
        """A model returning an id for a finding that does not exist adds nothing."""
        findings = [finding()]
        result = ExplanationResult(
            explanations={
                findings[0].fingerprint: explanation(findings[0].fingerprint),
                "a-fingerprint-that-does-not-exist": explanation(
                    "a-fingerprint-that-does-not-exist"
                ),
            }
        )

        explained = apply_explanations(findings, result)

        assert len(explained) == 1
        assert explained[0].fingerprint == findings[0].fingerprint

    def test_a_missing_explanation_leaves_the_finding_intact(self) -> None:
        findings = [finding(identity=("GET", "/a")), finding(identity=("GET", "/b"))]
        result = ExplanationResult(
            explanations={findings[0].fingerprint: explanation(findings[0].fingerprint)}
        )

        explained = apply_explanations(findings, result)

        assert len(explained) == 2
        assert "explanation" in explained[0].metadata
        assert "explanation" not in explained[1].metadata

    def test_order_is_preserved(self) -> None:
        """A model cannot re-rank findings by reordering its response."""
        findings = [finding(identity=("GET", f"/p{i}")) for i in range(5)]
        reversed_result = ExplanationResult(
            explanations={f.fingerprint: explanation(f.fingerprint) for f in reversed(findings)}
        )

        explained = apply_explanations(findings, reversed_result)

        assert [f.fingerprint for f in explained] == [f.fingerprint for f in findings]

    def test_severity_cannot_be_changed(self) -> None:
        original = finding("MX-DB-005")
        result = ExplanationResult(
            explanations={original.fingerprint: explanation(original.fingerprint)}
        )

        explained = apply_explanations([original], result)

        assert explained[0].severity is Severity.LOW

    def test_an_empty_result_changes_nothing(self) -> None:
        findings = [finding()]

        explained = apply_explanations(findings, ExplanationResult())

        assert explained == findings

    def test_the_explanation_lands_in_metadata(self) -> None:
        original = finding()
        result = ExplanationResult(
            explanations={original.fingerprint: explanation(original.fingerprint)}
        )

        explained = apply_explanations([original], result)[0]

        assert explained.metadata["explanation"] == "Because of X."
        assert explained.metadata["suggested_fix"] == "Change line 7."
        assert explained.metadata["explanation_source"] == "gemini"
        assert explained.metadata["fix_before"] == "before();"
        assert explained.metadata["fix_after"] == "after();"


class TestPromptRedaction:
    @pytest.mark.parametrize(
        "secret",
        [
            "sk_live_51H8xQ2KmNvR7pLdX4bWcZaYeTfUgIhJkOm",
            "AKIAIOSFODNN7EXAMPLE",
            "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789",
            "SG.aB3dEfGhIjKlMnOpQrSt.WxYz1234567890AbCdEfGh",
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.abcdef",
            "npm_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789",
        ],
    )
    def test_provider_credentials_are_masked(self, secret: str) -> None:
        redacted = redact_prompt(f'const KEY = "{secret}";')

        assert secret not in redacted
        assert "const KEY" in redacted

    def test_connection_string_credentials_are_masked(self) -> None:
        url = "postgresql://admin:sup3rs3cretpw@db.example.com:5432/app"

        redacted = redact_prompt(url)

        assert "sup3rs3cretpw" not in redacted
        assert "db.example.com" in redacted

    def test_ordinary_text_is_untouched(self) -> None:
        text = "The call at src/api.ts:7 requests /api/users."

        assert redact_prompt(text) == text

    def test_already_masked_evidence_stays_readable(self) -> None:
        text = 'ADMIN_PASSWORD = "********2024"'

        assert redact_prompt(text) == text


class TestPromptBuilding:
    def test_the_prompt_contains_what_the_model_needs(self) -> None:
        prompt = build_batch_prompt([finding("MX-API-002")])

        assert "finding_id:" in prompt
        assert "MX-API-002" in prompt
        assert "src/api.ts" in prompt
        assert "lines: 7-7" in prompt
        assert "expected: expected" in prompt
        assert "actual: actual" in prompt
        assert "evidence:" in prompt

    def test_the_fingerprint_is_the_correlation_id(self) -> None:
        target = finding()

        assert f"finding_id: {target.fingerprint}" in build_batch_prompt([target])

    def test_the_rationale_is_included(self) -> None:
        """The model needs to know why the rule exists to explain it well."""
        prompt = build_batch_prompt([finding("MX-API-001")])

        assert "why this rule exists:" in prompt

    def test_extra_locations_are_listed(self) -> None:
        multi = make_finding(
            "MX-API-001",
            identity=("GET", "/a"),
            locations=[
                SourceLocation(file_path="a.ts", line_start=1, line_end=1, snippet="a"),
                SourceLocation(file_path="b.ts", line_start=2, line_end=2, snippet="b"),
            ],
            description="d",
        )

        prompt = build_batch_prompt([multi])

        assert "also at: b.ts:2" in prompt

    def test_the_prompt_is_redacted_on_the_way_out(self) -> None:
        leaky = finding(evidence='KEY = "sk_live_51H8xQ2KmNvR7pLdX4bWcZaYeTfUgIhJkOm"')

        prompt = build_batch_prompt([leaky])

        assert "sk_live_51H8xQ2KmNvR7pLdX4bWcZaYeTfUgIhJkOm" not in prompt

    def test_several_findings_are_separated(self) -> None:
        prompt = build_batch_prompt(
            [finding(identity=("GET", "/a")), finding(identity=("GET", "/b"))]
        )

        assert prompt.count("finding_id:") == 2


class TestBatching:
    def test_a_small_set_is_one_batch(self) -> None:
        assert len(batch_findings([finding() for _ in range(3)])) == 1

    def test_the_count_cap_is_respected(self) -> None:
        findings = [finding(identity=("GET", f"/p{i}")) for i in range(MAX_FINDINGS_PER_BATCH * 2)]

        batches = batch_findings(findings)

        assert len(batches) == 2
        assert all(len(batch) <= MAX_FINDINGS_PER_BATCH for batch in batches)

    def test_the_size_cap_can_split_before_the_count_cap(self) -> None:
        """Findings with long evidence exceed a request before six of them fit.

        Evidence is capped at 2000 characters when a finding is built, so a
        single finding can never blow the batch on its own — but a handful
        with full-size snippets can, and the size cap is what catches that.
        """
        large = [
            finding(identity=("GET", f"/p{i}"), evidence="x" * 2000)
            for i in range(MAX_FINDINGS_PER_BATCH)
        ]

        batches = batch_findings(large)

        assert len(batches) > 1
        assert len(batches[0]) < MAX_FINDINGS_PER_BATCH
        for batch in batches:
            total = sum(len(f.evidence) + len(f.description) + 400 for f in batch)
            assert total <= MAX_BATCH_CHARS + 2400

    def test_every_finding_appears_exactly_once(self) -> None:
        findings = [finding(identity=("GET", f"/p{i}")) for i in range(14)]

        batched = [f for batch in batch_findings(findings) for f in batch]

        assert [f.fingerprint for f in batched] == [f.fingerprint for f in findings]

    def test_an_empty_list_yields_no_batches(self) -> None:
        assert batch_findings([]) == []

    def test_token_estimate_is_proportional(self) -> None:
        assert estimate_tokens("x" * 400) == 100
        assert estimate_tokens("") == 1


class TestTemplateExplainer:
    async def test_every_finding_gets_an_explanation(self) -> None:
        findings = [finding(identity=("GET", f"/p{i}")) for i in range(3)]

        result = await TemplateExplainer().explain(findings)

        assert len(result.explanations) == 3
        assert all(f.fingerprint in result.explanations for f in findings)

    async def test_it_never_degrades(self) -> None:
        """This is the offline path; it has nothing to fall back to."""
        result = await TemplateExplainer().explain([finding()])

        assert result.degraded is False

    async def test_the_source_is_recorded(self) -> None:
        result = await TemplateExplainer().explain([finding()])

        assert all(e.source == "template" for e in result.explanations.values())

    async def test_it_uses_no_tokens(self) -> None:
        result = await TemplateExplainer().explain([finding()])

        assert result.usage.total_tokens == 0
        assert result.usage.calls == 0


class TestTokenUsage:
    def test_usage_accumulates(self) -> None:
        total = TokenUsage(10, 5, 15, 1).plus(TokenUsage(20, 10, 30, 1))

        assert total == TokenUsage(30, 15, 45, 2)

    def test_source_counts_are_derived(self) -> None:
        result = ExplanationResult(
            explanations={
                "a": explanation("a", source="gemini"),
                "b": explanation("b", source="template"),
                "c": explanation("c", source="gemini"),
            }
        )

        assert result.source_counts == {"gemini": 2, "template": 1}


class TestMergeResults:
    def test_the_primary_wins(self) -> None:
        primary = ExplanationResult(explanations={"a": explanation("a", source="gemini")})
        fallback = ExplanationResult(explanations={"a": explanation("a", source="template")})

        merged = merge_results(primary, fallback)

        assert merged.explanations["a"].source == "gemini"

    def test_gaps_are_filled(self) -> None:
        primary = ExplanationResult(explanations={"a": explanation("a")})
        fallback = ExplanationResult(
            explanations={"a": explanation("a"), "b": explanation("b", source="template")}
        )

        merged = merge_results(primary, fallback)

        assert set(merged.explanations) == {"a", "b"}

    def test_degradation_propagates(self) -> None:
        primary = ExplanationResult(degraded=True, degraded_reason="timeout")

        merged = merge_results(primary, ExplanationResult())

        assert merged.degraded
        assert merged.degraded_reason == "timeout"
