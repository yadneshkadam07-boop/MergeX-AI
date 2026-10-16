"""The explanation layer: the only place a language model touches a finding.

**What the model may do:** write prose explaining a finding, and propose a
concrete fix.

**What it may not do:** create a finding, remove one, change its severity,
re-rank it, or alter its location. That is structurally enforced rather than
merely requested — :func:`apply_explanations` iterates over the *findings*
and looks each one up by fingerprint, so a model that invents an entry has it
ignored and a model that omits one gets a template instead. The finding set is
decided before any model is involved and cannot be changed afterwards.

**Offline is a first-class path, not a degraded one.** With no API key the
template explainer supplies a concrete, rule-specific explanation and fix for
every finding, with real file and line references. The product works entirely
without Gemini; the model improves the prose, it does not enable the feature.

**Prompts are redacted.** Findings already carry masked evidence, and the
prompt builder masks again on the way out as a second line of defence: a rule
added later that forgets to mask must not be able to leak a credential to a
third party.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import Final, Protocol

from pydantic import BaseModel, Field

from app.analysis.findings import Finding
from app.core.logging import get_logger

__all__ = [
    "Explainer",
    "Explanation",
    "ExplanationBatch",
    "ExplanationItem",
    "ExplanationResult",
    "TemplateExplainer",
    "TokenUsage",
    "apply_explanations",
    "build_batch_prompt",
    "redact_prompt",
]

log = get_logger("app.explanations")

# Batching. The cap is on characters rather than tokens because a token count
# needs the model's tokeniser; four characters per token is the usual
# approximation and erring small costs one extra request, not correctness.
MAX_FINDINGS_PER_BATCH: Final[int] = 6
MAX_BATCH_CHARS: Final[int] = 12_000
CHARS_PER_TOKEN_ESTIMATE: Final[int] = 4


# ---------------------------------------------------------------------------
# Structured output contract
# ---------------------------------------------------------------------------


class ExplanationItem(BaseModel):
    """One finding's explanation, as the model must return it."""

    finding_id: str = Field(
        description="The exact finding_id from the input. Do not invent new ids."
    )
    explanation: str = Field(
        description=(
            "Two to four sentences in plain English: what is wrong, why it matters, "
            "and what a user will see when it fails. No preamble, no markdown headings."
        )
    )
    suggested_fix: str = Field(
        description=(
            "One or two sentences naming the exact file and line to change and what "
            "to change it to."
        )
    )
    fix_before: str = Field(
        default="",
        description="The current code, copied from the evidence. Empty if not applicable.",
    )
    fix_after: str = Field(
        default="",
        description="The corrected code. Empty if the fix is not a code edit.",
    )


class ExplanationBatch(BaseModel):
    """The response schema handed to the model."""

    items: list[ExplanationItem] = Field(
        description="Exactly one entry per finding in the input, in the same order."
    )


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Explanation:
    """An explanation attached to one finding."""

    fingerprint: str
    explanation: str
    suggested_fix: str
    source: str
    """``gemini`` or ``template``. Shown in the UI so a user knows the origin."""
    fix_before: str | None = None
    fix_after: str | None = None


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Token accounting for one analysis."""

    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    calls: int = 0

    def plus(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            calls=self.calls + other.calls,
        )


@dataclass(slots=True)
class ExplanationResult:
    """Everything the explanation pass produced."""

    explanations: dict[str, Explanation] = field(default_factory=dict)
    usage: TokenUsage = field(default_factory=TokenUsage)
    degraded: bool = False
    degraded_reason: str | None = None

    @property
    def source_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for explanation in self.explanations.values():
            counts[explanation.source] = counts.get(explanation.source, 0) + 1
        return counts


class Explainer(Protocol):
    """How explanations get produced.

    A protocol so the analysis pipeline never depends on a network, an API key
    or a particular provider.
    """

    async def explain(self, findings: Sequence[Finding]) -> ExplanationResult: ...


# ---------------------------------------------------------------------------
# Applying explanations to findings
# ---------------------------------------------------------------------------


def apply_explanations(findings: Sequence[Finding], result: ExplanationResult) -> list[Finding]:
    """Attach explanations to findings without changing the finding set.

    The iteration is over ``findings``, so the output has exactly the same
    length, order, rule IDs, severities, locations and fingerprints as the
    input. An explanation whose ``finding_id`` matches nothing is discarded;
    a finding with no explanation keeps empty metadata fields. A model cannot
    add, drop or reorder a finding through this function.
    """
    explained: list[Finding] = []
    for finding in findings:
        explanation = result.explanations.get(finding.fingerprint)
        if explanation is None:
            explained.append(finding)
            continue
        metadata = {
            **finding.metadata,
            "explanation": explanation.explanation,
            "suggested_fix": explanation.suggested_fix,
            "explanation_source": explanation.source,
        }
        if explanation.fix_before:
            metadata["fix_before"] = explanation.fix_before
        if explanation.fix_after:
            metadata["fix_after"] = explanation.fix_after
        explained.append(replace(finding, metadata=metadata))
    return explained


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

SYSTEM_INSTRUCTION: Final[
    str
] = """\
You are explaining defects found by MergeX AI, a static analyser that compares \
the layers of a software project against each other.

Every finding you are given has ALREADY been confirmed by deterministic \
analysis. Your job is to explain it and propose a fix. You must not question \
whether it is real, and you must not add, remove, merge or re-order findings.

Rules:
1. Return exactly one item per input finding, reusing its finding_id verbatim.
2. Explanations are two to four sentences of plain English. State what is \
wrong, why it matters, and what a user sees when it fails. No headings, no \
bullet lists, no restating the rule name.
3. A suggested fix must name the real file and line given in the finding, and \
fix_before / fix_after must be concrete code -- the actual line as given, and \
the actual corrected line. Never write generic advice like "validate input" \
or "use environment variables" without showing the edit.
4. Values shown as asterisks are redacted credentials. Never guess at them and \
never include a credential in your output.
5. If you cannot propose a concrete code change, leave fix_before and \
fix_after empty and say what to investigate instead.
"""


def build_batch_prompt(findings: Sequence[Finding]) -> str:
    """Render a batch of findings as a prompt.

    Every value interpolated here comes from a finding, whose evidence was
    already redacted at construction. :func:`redact_prompt` is applied on top
    regardless.
    """
    blocks: list[str] = []
    for finding in findings:
        definition = finding.definition
        location = finding.primary_location
        extra_locations = (
            "\n".join(f"  also at: {loc}" for loc in finding.locations[1:])
            if finding.occurrence_count > 1
            else ""
        )
        blocks.append(
            "\n".join(
                part
                for part in [
                    f"finding_id: {finding.fingerprint}",
                    f"rule: {finding.rule_id} — {definition.title}",
                    f"category: {finding.category.value}",
                    f"severity: {finding.severity.value}",
                    f"why this rule exists: {definition.rationale}",
                    f"file: {location.file_path}",
                    f"lines: {location.line_start}-{location.line_end}",
                    extra_locations,
                    f"expected: {finding.expected or '(not applicable)'}",
                    f"actual: {finding.actual or '(not applicable)'}",
                    f"detail: {finding.description}",
                    "evidence:",
                    _indent(finding.evidence or "(no snippet)"),
                    _render_metadata(finding),
                ]
                if part
            )
        )

    prompt = (
        f"Explain these {len(findings)} findings. "
        f"Return one item per finding, reusing each finding_id exactly.\n\n"
        + "\n\n---\n\n".join(blocks)
    )
    return redact_prompt(prompt)


def _indent(text: str, prefix: str = "  ") -> str:
    return "\n".join(f"{prefix}{line}" for line in text.splitlines())


# Metadata keys worth showing a model. Everything else is internal bookkeeping
# that would only consume tokens.
_USEFUL_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "path",
        "method",
        "called_path",
        "suggested_path",
        "raw_path",
        "caller",
        "handler",
        "dependencies",
        "sibling_dependencies",
        "model",
        "drifted_fields",
        "sent_fields",
        "model_fields",
        "table",
        "column",
        "field",
        "model_type",
        "database_type",
        "references",
        "existing_columns",
        "indexed_columns",
        "variable",
        "detector",
        "sensitive_terms",
        "protected_siblings",
        "allow_origins",
        "allow_credentials",
        "factory",
        "credential_keys",
        "package",
        "version",
        "advisories",
        "fixed_versions",
        "statement_kind",
        "route_methods",
        "call_method",
    }
)


def _render_metadata(finding: Finding) -> str:
    useful = {
        key: value
        for key, value in sorted(finding.metadata.items())
        if key in _USEFUL_METADATA_KEYS and value not in (None, [], {}, "")
    }
    if not useful:
        return ""
    lines = [f"  {key}: {_short(value)}" for key, value in useful.items()]
    return "context:\n" + "\n".join(lines)


def _short(value: object, limit: int = 300) -> str:
    text = str(value)
    return text if len(text) <= limit else f"{text[:limit]}…"


# Provider credential formats, re-checked on the way out. Duplicated from the
# security rule deliberately: this is a safety net, and a safety net that
# imports its patterns from the thing it is protecting against is not one.
_OUTBOUND_SECRET_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{4,}"),
    re.compile(r"\bnpm_[A-Za-z0-9]{36}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    # user:password@host in a connection string
    re.compile(r"://[^\s:/@]+:[^\s:/@]{6,}@"),
)

# A value assigned to a credential-named identifier, whatever its shape.
#
# The patterns above recognise secrets by their own format, which covers the
# providers that use a prefix but not a bare high-entropy string: an AWS
# secret access key or a JWT signing key is indistinguishable from any other
# 32 characters. What gives those away is the *name* they are assigned to, so
# this masks the value and keeps the name -- which is the part the model needs
# in order to write a useful explanation.
#
# The trade-off is deliberately asymmetric. Masking too much costs a little
# prose quality on one finding; masking too little sends a live credential to
# a third party.
_CREDENTIAL_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(
    r"""
    \b(
        [A-Za-z0-9_]*
        (?: SECRET | PASSWORD | PASSWD | PASSPHRASE | TOKEN | CREDENTIAL
          | PRIVATE[_-]?KEY | SIGNING[_-]?KEY | API[_-]?KEY | ACCESS[_-]?KEY
          | KEY )
        [A-Za-z0-9_]*
    )
    (\s*[:=]\s*)          # = or : , however the language spells assignment
    (["']?)               # an optional opening quote
    ([^\s"',;)}\]]{10,})  # the value: long enough to be a secret
    """,
    re.IGNORECASE | re.VERBOSE,
)


def redact_prompt(prompt: str) -> str:
    """Mask anything credential-shaped before it leaves the process.

    Findings are already redacted, so in normal operation this changes
    nothing. It exists because the cost of being wrong is sending a live
    credential to a third-party API, and a rule added next year must not be
    able to cause that by forgetting one call.
    """
    redacted = prompt
    for pattern in _OUTBOUND_SECRET_PATTERNS:
        redacted = pattern.sub(_mask_match, redacted)
    return _CREDENTIAL_ASSIGNMENT.sub(_mask_assignment, redacted)


def _mask_match(match: re.Match[str]) -> str:
    text = match.group(0)
    if text.startswith("://"):
        return "://***:***@"
    return _mask(text)


def _mask_assignment(match: re.Match[str]) -> str:
    """Mask the value, keep the name, the operator and the quote."""
    name, operator, quote, value = match.groups()
    return f"{name}{operator}{quote}{_mask(value)}"


def _mask(text: str) -> str:
    """Asterisks plus the last four characters, so masking is idempotent.

    Keeping a short suffix lets a user match the masked value against the one
    in their own secret store without the value itself appearing here.
    """
    return f"{'*' * 8}{text[-4:]}" if len(text) > 4 else "*" * len(text)


def batch_findings(findings: Sequence[Finding]) -> list[list[Finding]]:
    """Split findings into batches that fit a request.

    Bounded by both a count and an estimated size: a handful of findings with
    long evidence can exceed a sensible request on their own.
    """
    batches: list[list[Finding]] = []
    current: list[Finding] = []
    current_chars = 0

    for finding in findings:
        size = _estimated_chars(finding)
        too_many = len(current) >= MAX_FINDINGS_PER_BATCH
        too_big = current and current_chars + size > MAX_BATCH_CHARS
        if too_many or too_big:
            batches.append(current)
            current = []
            current_chars = 0
        current.append(finding)
        current_chars += size

    if current:
        batches.append(current)
    return batches


def _estimated_chars(finding: Finding) -> int:
    return (
        len(finding.description)
        + len(finding.evidence)
        + len(finding.expected or "")
        + len(finding.actual or "")
        + 400  # rule metadata, labels and separators
    )


def estimate_tokens(text: str) -> int:
    """A rough token count, for logging and batch sizing only."""
    return max(1, len(text) // CHARS_PER_TOKEN_ESTIMATE)


# ---------------------------------------------------------------------------
# The offline explainer
# ---------------------------------------------------------------------------


class TemplateExplainer:
    """Produces explanations with no network and no API key.

    This is the product's offline path. Each rule has its own template which
    builds a concrete before/after from the finding's own metadata, so the
    output names real files, real lines and real code rather than giving
    generic advice.
    """

    async def explain(self, findings: Sequence[Finding]) -> ExplanationResult:
        from app.services.explanation_templates import render_template

        result = ExplanationResult()
        for finding in findings:
            result.explanations[finding.fingerprint] = render_template(finding)
        log.info("template_explanations_generated", count=len(result.explanations))
        return result


def merge_results(primary: ExplanationResult, fallback: ExplanationResult) -> ExplanationResult:
    """Fill gaps in ``primary`` from ``fallback``.

    Used when some batches succeed and others fail: the successful
    explanations are kept and only the missing ones fall back, so one bad
    request does not discard good output.
    """
    return ExplanationResult(
        explanations={**fallback.explanations, **primary.explanations},
        usage=primary.usage.plus(fallback.usage),
        degraded=primary.degraded or fallback.degraded,
        degraded_reason=primary.degraded_reason or fallback.degraded_reason,
    )


def fingerprints_of(findings: Iterable[Finding]) -> set[str]:
    return {finding.fingerprint for finding in findings}
