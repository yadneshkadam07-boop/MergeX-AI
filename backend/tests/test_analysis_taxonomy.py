"""The rule registry, and its agreement with the fixture manifests.

This is the test that stops the manifests becoming fiction. Two directions
are enforced:

* a manifest claiming ``implemented: true`` for a rule that does not exist
  fails -- the claim is false;
* a rule in the registry that no manifest exercises fails -- it has no
  fixture proving it works, and an untested rule is an unverified one.

Both are easy to get wrong by accident: adding a rule and forgetting the
fixture, or writing the fixture first and never implementing the rule.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.analysis.taxonomy import REGISTRY, RuleDefinition, implemented_rule_ids, rule
from app.models.enums import IssueCategory, Severity

FIXTURES = [
    "react_fastapi_mismatch",
    "react_fastapi_schema_drift",
    "react_fastapi_insecure",
]

ManifestLoader = Callable[[str], dict[str, Any]]
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def manifest_rule_entries() -> list[tuple[str, dict[str, Any]]]:
    """Every ``findings`` entry across every manifest, with its fixture name."""
    entries: list[tuple[str, dict[str, Any]]] = []
    for name in FIXTURES:
        path = FIXTURES_DIR / name / "expected_findings.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for entry in data.get("findings", []):
            entries.append((name, entry))
    return entries


class TestRegistryIntegrity:
    def test_ids_follow_the_naming_scheme(self) -> None:
        for rule_id in REGISTRY:
            area = rule_id.split("-")[1]
            assert rule_id.startswith("MX-"), rule_id
            assert area in {"API", "DB", "SEC", "DEP"}, rule_id
            assert rule_id.split("-")[2].isdigit(), rule_id

    def test_the_id_matches_the_dictionary_key(self) -> None:
        for key, definition in REGISTRY.items():
            assert key == definition.rule_id

    def test_area_matches_category(self) -> None:
        expected = {
            "API": IssueCategory.API_CONTRACT,
            "DB": IssueCategory.SCHEMA,
            "SEC": IssueCategory.SECURITY,
            "DEP": IssueCategory.DEPENDENCY,
        }
        for rule_id, definition in REGISTRY.items():
            area = rule_id.split("-")[1]
            assert definition.category is expected[area], rule_id

    def test_every_rule_documents_itself(self) -> None:
        """A rule a user cannot understand is a rule they will disable."""
        for definition in REGISTRY.values():
            assert definition.title.strip()
            assert len(definition.summary) > 20, definition.rule_id
            assert len(definition.rationale) > 40, definition.rule_id

    def test_confidence_is_a_probability(self) -> None:
        for definition in REGISTRY.values():
            assert 0.0 < definition.base_confidence <= 1.0, definition.rule_id

    def test_severity_is_a_known_level(self) -> None:
        for definition in REGISTRY.values():
            assert definition.default_severity in set(Severity)

    def test_lookup_rejects_an_unknown_id(self) -> None:
        with pytest.raises(KeyError, match="MX-NOPE-999"):
            rule("MX-NOPE-999")

    def test_lookup_returns_the_definition(self) -> None:
        assert rule("MX-API-001").category is IssueCategory.API_CONTRACT

    def test_duplicate_ids_are_rejected_at_construction(self) -> None:
        from app.analysis.taxonomy import _define

        definition = RuleDefinition(
            rule_id="MX-API-001",
            title="t",
            category=IssueCategory.API_CONTRACT,
            default_severity=Severity.LOW,
            summary="s" * 30,
            rationale="r" * 50,
        )
        with pytest.raises(ValueError, match="duplicate rule id"):
            _define(definition, definition)

    def test_invalid_confidence_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="base_confidence"):
            RuleDefinition(
                rule_id="MX-API-900",
                title="t",
                category=IssueCategory.API_CONTRACT,
                default_severity=Severity.LOW,
                summary="s" * 30,
                rationale="r" * 50,
                base_confidence=1.5,
            )


class TestManifestAgreement:
    """The two directions of the manifest/registry contract."""

    def test_no_manifest_claims_an_unimplemented_rule(self) -> None:
        """``implemented: true`` for a rule that does not exist is a lie."""
        claimed: list[str] = []
        for fixture, entry in manifest_rule_entries():
            if entry.get("implemented") is True and entry["rule_id"] not in REGISTRY:
                claimed.append(f"{fixture}:{entry['rule_id']}")

        assert claimed == [], (
            "These manifests claim implemented: true for rules that are not in the "
            f"registry: {claimed}"
        )

    def test_no_manifest_understates_an_implemented_rule(self) -> None:
        """``implemented: false`` for a rule that *is* implemented is stale."""
        stale: list[str] = []
        for fixture, entry in manifest_rule_entries():
            if entry.get("implemented") is False and entry["rule_id"] in REGISTRY:
                stale.append(f"{fixture}:{entry['rule_id']}")

        assert stale == [], (
            "These rules are implemented but their manifest still says "
            f"implemented: false — flip them in the commit that adds the rule: {stale}"
        )

    def test_every_implemented_rule_appears_in_a_manifest(self) -> None:
        """A rule with no fixture has nothing proving it works."""
        in_manifests = {entry["rule_id"] for _, entry in manifest_rule_entries()}

        missing = sorted(implemented_rule_ids() - in_manifests)

        assert missing == [], (
            "These rules are implemented but no fixture exercises them, so nothing "
            f"demonstrates they fire correctly: {missing}"
        )

    def test_every_manifest_entry_declares_implemented(self) -> None:
        for fixture, entry in manifest_rule_entries():
            assert "implemented" in entry, f"{fixture}:{entry.get('rule_id')}"

    def test_manifest_severity_matches_the_registry(self) -> None:
        """A manifest promising 'critical' for a medium rule misleads a reader."""
        mismatched: list[str] = []
        for fixture, entry in manifest_rule_entries():
            rule_id = entry["rule_id"]
            if rule_id not in REGISTRY or "severity" not in entry:
                continue
            if entry["severity"] != REGISTRY[rule_id].default_severity.value:
                mismatched.append(
                    f"{fixture}:{rule_id} manifest={entry['severity']} "
                    f"registry={REGISTRY[rule_id].default_severity.value}"
                )

        assert mismatched == []

    def test_manifest_category_matches_the_registry(self) -> None:
        for fixture, entry in manifest_rule_entries():
            rule_id = entry["rule_id"]
            if rule_id not in REGISTRY or "category" not in entry:
                continue
            assert entry["category"] == REGISTRY[rule_id].category.value, f"{fixture}:{rule_id}"

    def test_every_manifest_has_must_not_report_cases(self) -> None:
        """Precision is asserted, not assumed, so every fixture needs them."""
        for name in FIXTURES:
            data = json.loads(
                (FIXTURES_DIR / name / "expected_findings.json").read_text(encoding="utf-8")
            )
            assert data.get("must_not_report"), f"{name} declares no must_not_report cases"

    def test_all_four_categories_are_covered_by_fixtures(self) -> None:
        in_manifests = {entry["rule_id"] for _, entry in manifest_rule_entries()}
        covered = {REGISTRY[rule_id].category for rule_id in in_manifests if rule_id in REGISTRY}

        assert covered == set(IssueCategory)
