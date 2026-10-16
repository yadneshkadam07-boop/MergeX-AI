"""The deterministic finding: what a rule produces before any model sees it.

A :class:`Finding` is complete on its own. It names the rule that produced it,
where the defect is, what was expected, what was found, and how certain the
rule is. ``explanation`` and ``suggested_fix`` are *absent* here by design --
those are the only language-model contributions, added in Phase 4, and an
analysis run with no API key stores exactly these facts with those two fields
empty.

Two details that matter more than they look:

**Fingerprints identify a root cause, not an occurrence.** A typo'd path
called from three components is one defect with three locations, so the
fingerprint is computed from the defect's identity (rule + what is wrong) and
never from the file or line. :func:`deduplicate` then merges occurrences.

**Evidence is redacted.** A tool that finds a hardcoded API key and then
stores that key in its own database has moved the secret, not reported it.
Every finding's evidence passes through
:func:`app.core.security.redact_secrets`.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.analysis.taxonomy import RuleDefinition, rule
from app.core.security import redact_secrets
from app.models.enums import IssueCategory, Severity
from app.services.parsers.base import SourceLocation

__all__ = [
    "Finding",
    "deduplicate",
    "make_finding",
]

# A finding's evidence is for a human reading a report, not a code listing.
_MAX_EVIDENCE_CHARS = 2000


@dataclass(frozen=True, slots=True)
class Finding:
    """One defect, found deterministically."""

    rule_id: str
    category: IssueCategory
    severity: Severity
    title: str
    description: str
    locations: tuple[SourceLocation, ...]
    """Every place this one defect appears. Never empty; the first is primary."""
    fingerprint: str
    confidence: float
    expected: str | None = None
    actual: str | None = None
    evidence: str = ""
    """Redacted source text for the primary location."""
    metadata: dict[str, Any] = field(default_factory=dict)
    """Structured detail for the UI and for the Phase 4 explanation prompt."""

    def __post_init__(self) -> None:
        if not self.locations:
            raise ValueError(f"{self.rule_id}: a finding needs at least one location")
        if not 0.0 < self.confidence <= 1.0:
            raise ValueError(f"{self.rule_id}: confidence must be in (0, 1]")

    @property
    def primary_location(self) -> SourceLocation:
        return self.locations[0]

    @property
    def occurrence_count(self) -> int:
        return len(self.locations)

    @property
    def definition(self) -> RuleDefinition:
        return rule(self.rule_id)

    @property
    def score_penalty(self) -> int:
        return self.severity.score_penalty

    def __str__(self) -> str:
        return f"{self.rule_id} [{self.severity.value}] {self.title} ({self.primary_location})"


def make_finding(
    rule_id: str,
    *,
    identity: tuple[str | int | None, ...],
    locations: list[SourceLocation],
    description: str,
    expected: str | None = None,
    actual: str | None = None,
    severity: Severity | None = None,
    confidence: float | None = None,
    secrets: tuple[str, ...] = (),
    metadata: dict[str, Any] | None = None,
    title: str | None = None,
) -> Finding:
    """Build a finding, filling in everything the taxonomy already knows.

    Args:
        rule_id: Must be registered in :mod:`app.analysis.taxonomy`.
        identity: What makes this defect *this* defect -- for an API rule the
            method and path, for a schema rule the table and column. It must
            not include a file or line, or the same root cause found in two
            places would fingerprint as two defects.
        locations: Where it appears. The first is the primary location.
        secrets: Literal values to mask out of the evidence, for rules that
            find credentials.
        severity: Overrides the rule's default, for rules whose severity comes
            from data (a dependency advisory, say).
        confidence: Overrides the rule's base confidence, for rules that
            weaken it on weaker signals.
    """
    definition = rule(rule_id)
    ordered = _ordered_locations(locations)

    return Finding(
        rule_id=rule_id,
        category=definition.category,
        severity=severity or definition.default_severity,
        title=title or definition.title,
        description=description,
        locations=ordered,
        fingerprint=_fingerprint(rule_id, identity),
        confidence=confidence if confidence is not None else definition.base_confidence,
        expected=expected,
        actual=actual,
        evidence=_evidence(ordered[0], secrets),
        metadata=dict(metadata or {}),
    )


def _ordered_locations(locations: list[SourceLocation]) -> tuple[SourceLocation, ...]:
    """De-duplicate and order locations so output is deterministic."""
    unique = list(dict.fromkeys(locations))
    if not unique:
        return ()
    primary, *rest = unique
    return (primary, *sorted(rest))


def _fingerprint(rule_id: str, identity: tuple[str | int | None, ...]) -> str:
    """A stable hash of a defect's identity.

    Deliberately excludes file and line: the same root cause reported from two
    call sites must collapse to one finding, and a finding should keep the same
    fingerprint when surrounding code moves, so it can be recognised across
    runs.
    """
    parts = [rule_id, *("" if part is None else str(part) for part in identity)]
    digest = hashlib.sha256("\u001f".join(parts).encode("utf-8")).hexdigest()
    # 32 hex characters fits the `issues.fingerprint` column with room spare
    # and leaves collisions implausible.
    return digest[:32]


def _evidence(location: SourceLocation, secrets: tuple[str, ...]) -> str:
    """Redacted, length-capped evidence for a location."""
    text = redact_secrets(location.snippet, secrets)
    if len(text) > _MAX_EVIDENCE_CHARS:
        return f"{text[:_MAX_EVIDENCE_CHARS]}\n…"
    return text


def deduplicate(findings: list[Finding]) -> list[Finding]:
    """Merge findings that share a fingerprint into one, keeping all locations.

    This is where "a typo'd path hit by two components" becomes one issue with
    two locations. The merged finding keeps the highest severity and the
    highest confidence seen, because a defect is as bad as its worst
    occurrence, and the union of metadata.

    Output is ordered by severity then rule ID then primary location, so two
    runs over the same code produce byte-identical reports.
    """
    grouped: dict[str, list[Finding]] = defaultdict(list)
    for finding in findings:
        grouped[finding.fingerprint].append(finding)

    merged: list[Finding] = []
    for group in grouped.values():
        merged.append(group[0] if len(group) == 1 else _merge(group))

    severity_rank = {
        Severity.CRITICAL: 0,
        Severity.HIGH: 1,
        Severity.MEDIUM: 2,
        Severity.LOW: 3,
    }
    merged.sort(
        key=lambda found: (
            severity_rank[found.severity],
            found.rule_id,
            found.primary_location.file_path,
            found.primary_location.line_start,
        )
    )
    return merged


def _merge(group: list[Finding]) -> Finding:
    """Combine findings that describe the same defect."""
    severity_rank = {
        Severity.CRITICAL: 0,
        Severity.HIGH: 1,
        Severity.MEDIUM: 2,
        Severity.LOW: 3,
    }
    primary = min(
        group,
        key=lambda found: (
            severity_rank[found.severity],
            found.primary_location.file_path,
            found.primary_location.line_start,
        ),
    )

    locations: list[SourceLocation] = [primary.primary_location]
    for finding in group:
        for location in finding.locations:
            if location not in locations:
                locations.append(location)

    metadata: dict[str, Any] = {}
    for finding in group:
        metadata.update(finding.metadata)
    if len(locations) > 1:
        metadata["occurrences"] = [str(location) for location in locations]

    return Finding(
        rule_id=primary.rule_id,
        category=primary.category,
        severity=min(group, key=lambda f: severity_rank[f.severity]).severity,
        title=primary.title,
        description=primary.description,
        locations=_ordered_locations(locations),
        fingerprint=primary.fingerprint,
        confidence=max(finding.confidence for finding in group),
        expected=primary.expected,
        actual=primary.actual,
        evidence=primary.evidence,
        metadata=metadata,
    )
