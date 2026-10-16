"""The issue taxonomy: every rule MergeX can report, by stable ID.

A rule ID is a **public contract**. It appears in stored issues, in the API,
in fixture manifests and eventually in users' CI configuration, so an ID is
never reused or repurposed once shipped. Retiring a rule means marking it
retired, not deleting it.

The registry is also what makes the fixture manifests enforceable: a rule
listed in a manifest as ``implemented: true`` must exist here, and a rule here
must appear in at least one manifest. ``tests/test_analysis_taxonomy.py``
fails on either mismatch, which is what stops the manifests drifting into
fiction.

Naming: ``MX-<AREA>-<NNN>``, where AREA is API, DB, SEC or DEP.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.models.enums import IssueCategory, Severity

__all__ = [
    "REGISTRY",
    "RuleDefinition",
    "implemented_rule_ids",
    "rule",
]


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    """What a rule is, independent of any particular finding."""

    rule_id: str
    title: str
    category: IssueCategory
    default_severity: Severity
    summary: str
    """One sentence, shown in the UI's rule reference."""
    rationale: str
    """Why this is worth reporting -- the thing a user asks when they disagree."""
    # Rules differ in how certain they can be even when they fire. A path that
    # matches no route is a fact; a high-entropy string that *looks* like a
    # secret is an inference.
    base_confidence: float = 1.0

    def __post_init__(self) -> None:
        if not 0.0 < self.base_confidence <= 1.0:
            raise ValueError(f"{self.rule_id}: base_confidence must be in (0, 1]")


def _define(*definitions: RuleDefinition) -> dict[str, RuleDefinition]:
    registry: dict[str, RuleDefinition] = {}
    for definition in definitions:
        if definition.rule_id in registry:
            raise ValueError(f"duplicate rule id {definition.rule_id}")
        registry[definition.rule_id] = definition
    return registry


# ---------------------------------------------------------------------------
# The registry. A rule appears here only once it is implemented *and* tested.
# ---------------------------------------------------------------------------

REGISTRY: Final[dict[str, RuleDefinition]] = _define(
    # -- Frontend <-> backend API contract ----------------------------------
    RuleDefinition(
        rule_id="MX-API-001",
        title="Frontend calls an endpoint the backend does not define",
        category=IssueCategory.API_CONTRACT,
        default_severity=Severity.CRITICAL,
        summary="A request is made to a path no backend route serves.",
        rationale=(
            "The call returns 404 at runtime. Nothing in a type checker or a "
            "linter sees across the two layers, so this survives review and "
            "CI and fails only when a user hits the feature."
        ),
    ),
    RuleDefinition(
        rule_id="MX-API-002",
        title="Frontend request path looks like a typo of a real route",
        category=IssueCategory.API_CONTRACT,
        default_severity=Severity.CRITICAL,
        summary="The path matches no route but is one character edit from one that exists.",
        rationale=(
            "Reported separately from a missing endpoint because the fix is "
            "different and obvious: the near match is almost certainly the "
            "intended target, and naming it turns a hunt into a one-character "
            "correction."
        ),
    ),
    RuleDefinition(
        rule_id="MX-API-003",
        title="HTTP method mismatch between the call and the route",
        category=IssueCategory.API_CONTRACT,
        default_severity=Severity.HIGH,
        summary="The path exists but is declared for a different HTTP method.",
        rationale=(
            "Returns 405, and is easy to miss in review because the path -- "
            "the part people read -- is correct."
        ),
    ),
    RuleDefinition(
        rule_id="MX-API-004",
        title="Request body field names do not match the backend schema",
        category=IssueCategory.API_CONTRACT,
        default_severity=Severity.HIGH,
        summary="The payload sends a field the request model does not declare.",
        rationale=(
            "camelCase/snake_case drift across the layer boundary. The field "
            "is silently dropped or the request fails validation, and the "
            "frontend's own types are self-consistent so nothing local catches it."
        ),
        # Only reported when the same field exists under the other casing,
        # which makes the inference strong but not certain -- an alias
        # configuration could reconcile them.
        base_confidence=0.9,
    ),
    RuleDefinition(
        rule_id="MX-API-005",
        title="Call to an authenticated route sends no credentials",
        category=IssueCategory.API_CONTRACT,
        default_severity=Severity.HIGH,
        summary="The route declares an auth dependency; the request attaches nothing.",
        rationale=(
            "Returns 401. Reported only when the client cannot be attaching "
            "credentials ambiently through a default header or an interceptor."
        ),
        base_confidence=0.8,
    ),
    # -- Backend <-> database schema ----------------------------------------
    RuleDefinition(
        rule_id="MX-DB-001",
        title="ORM model field has no corresponding database column",
        category=IssueCategory.SCHEMA,
        default_severity=Severity.CRITICAL,
        summary="A mapped field names a column the migrations never create.",
        rationale=(
            "Breaks every query against the table, not just writes to that "
            "column, because the ORM names it in the SELECT list."
        ),
    ),
    RuleDefinition(
        rule_id="MX-DB-002",
        title="Column type differs between the model and the database",
        category=IssueCategory.SCHEMA,
        default_severity=Severity.HIGH,
        summary="The model and the migration disagree about a column's type.",
        rationale=(
            "Often silent rather than loud: NUMERIC read as INTEGER truncates "
            "money instead of raising, which is worse than a crash because "
            "nobody notices."
        ),
    ),
    RuleDefinition(
        rule_id="MX-DB-003",
        title="Query references a column that does not exist",
        category=IssueCategory.SCHEMA,
        default_severity=Severity.CRITICAL,
        summary="Raw SQL names a column absent from both the model and the schema.",
        rationale=(
            "Raw SQL bypasses every check the ORM would have made, so this "
            "fails at execution time with no earlier warning."
        ),
    ),
    RuleDefinition(
        rule_id="MX-DB-004",
        title="Model declares a relationship with no foreign key in the database",
        category=IssueCategory.SCHEMA,
        default_severity=Severity.MEDIUM,
        summary="A ForeignKey exists in the model but not in the migration.",
        rationale=(
            "The database cannot enforce the reference, so orphaned rows "
            "become possible and cascade behaviour silently does nothing."
        ),
    ),
    RuleDefinition(
        rule_id="MX-DB-005",
        title="Foreign key column is not indexed",
        category=IssueCategory.SCHEMA,
        default_severity=Severity.LOW,
        summary="A column used as a foreign key has no index.",
        rationale=(
            "Every join through it is a sequential scan. Low severity because "
            "it is a performance issue, not a correctness one."
        ),
        base_confidence=0.9,
    ),
    # -- Security -----------------------------------------------------------
    RuleDefinition(
        rule_id="MX-SEC-001",
        title="Hardcoded secret in source",
        category=IssueCategory.SECURITY,
        default_severity=Severity.CRITICAL,
        summary="A credential is committed in source rather than read from the environment.",
        rationale=(
            "Anyone with repository access has the credential, and frontend "
            "secrets additionally ship to every browser. Git history keeps it "
            "after deletion, so rotation is the only real fix."
        ),
        # Provider-prefixed matches are near-certain; entropy-only matches are
        # an inference. The rule sets per-finding confidence accordingly.
        base_confidence=0.95,
    ),
    RuleDefinition(
        rule_id="MX-SEC-002",
        title="Sensitive route has no authentication",
        category=IssueCategory.SECURITY,
        default_severity=Severity.CRITICAL,
        summary=(
            "A route handling money or personal data declares no auth "
            "dependency while its siblings do."
        ),
        rationale=(
            "Reported only on the *inconsistency*: a route whose neighbours "
            "are protected and which touches a sensitive domain is almost "
            "always an oversight rather than a deliberate public endpoint."
        ),
        base_confidence=0.85,
    ),
    RuleDefinition(
        rule_id="MX-SEC-003",
        title="CORS allows any origin",
        category=IssueCategory.SECURITY,
        default_severity=Severity.HIGH,
        summary="A wildcard origin is configured, and credentials may be sent with it.",
        rationale=(
            "With credentials enabled, any site can make authenticated "
            "cross-origin requests on a logged-in user's behalf."
        ),
    ),
    RuleDefinition(
        rule_id="MX-SEC-004",
        title="Environment file committed to version control",
        category=IssueCategory.SECURITY,
        default_severity=Severity.CRITICAL,
        summary="A .env file is present in the repository.",
        rationale=(
            "A .env is the file whose entire purpose is to stay out of version "
            "control. Its presence means every credential in it is shared with "
            "everyone who can read the repository."
        ),
    ),
    RuleDefinition(
        rule_id="MX-SEC-005",
        title="Debug mode enabled on the application",
        category=IssueCategory.SECURITY,
        default_severity=Severity.MEDIUM,
        summary="The application is constructed with debug mode on.",
        rationale=(
            "Debug handlers expose stack traces, source fragments and local "
            "variables to anyone who can trigger an error."
        ),
    ),
    # -- Dependencies -------------------------------------------------------
    RuleDefinition(
        rule_id="MX-DEP-001",
        title="Dependency has a known vulnerability",
        category=IssueCategory.DEPENDENCY,
        default_severity=Severity.HIGH,
        summary="A pinned dependency version has a published advisory.",
        rationale=(
            "Resolved against OSV.dev, which aggregates GitHub advisories, "
            "CVEs and ecosystem databases. Severity follows the advisory."
        ),
    ),
)


def rule(rule_id: str) -> RuleDefinition:
    """Look up a rule, failing loudly on an unknown ID.

    Raises:
        KeyError: if the ID is not registered. A finding with an unregistered
            rule ID is a programming error, not a user-visible condition.
    """
    try:
        return REGISTRY[rule_id]
    except KeyError:
        raise KeyError(
            f"Unknown rule id {rule_id!r}. Register it in app.analysis.taxonomy."
        ) from None


def implemented_rule_ids() -> frozenset[str]:
    """Every rule the engine can currently report."""
    return frozenset(REGISTRY)
