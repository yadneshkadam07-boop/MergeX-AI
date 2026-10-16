"""The offline explanation templates.

These are the product when there is no API key, so they are held to the same
bar as model output: every rule has one, every fix names the real file and
line, and every fix shows concrete code rather than advice. A template that
said "use environment variables" without showing the edit would tell the user
less than the rule's own title already does.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.analysis.findings import Finding, make_finding
from app.analysis.taxonomy import REGISTRY
from app.services.explanation_templates import render_template
from app.services.parsers.base import SourceLocation

# Metadata rich enough for every template to render fully.
_METADATA: dict[str, dict[str, object]] = {
    "MX-API-001": {
        "method": "GET",
        "path": "/api/users/export",
        "caller": "exportUsers",
        "nearby_routes": ["/api/users"],
    },
    "MX-API-002": {
        "called_path": "/api/user/{}",
        "suggested_path": "/api/users/{}",
        "raw_path": "/api/user/${id}",
        "method": "GET",
        "handler": "get_user",
    },
    "MX-API-003": {
        "call_method": "POST",
        "route_methods": ["DELETE"],
        "path": "/api/users/{}/deactivate",
    },
    "MX-API-004": {
        "model": "UserCreate",
        "drifted_fields": [{"sent": "fullName", "expected": "full_name"}],
    },
    "MX-API-005": {"handler": "delete_all_tasks", "dependencies": ["require_admin"]},
    "MX-DB-001": {
        "table": "products",
        "column": "warehouse_code",
        "model": "Product",
        "field": "warehouse_code",
        "expected_type": "String",
        "existing_columns": ["id", "sku"],
    },
    "MX-DB-002": {
        "table": "products",
        "column": "unit_price",
        "model_type": "Numeric",
        "database_type": "INTEGER",
        "model_family": "decimal",
        "database_family": "integer",
    },
    "MX-DB-003": {
        "table": "products",
        "column": "last_counted_at",
        "existing_columns": ["id", "sku"],
    },
    "MX-DB-004": {
        "table": "products",
        "column": "supplier_id",
        "references": "suppliers.id",
    },
    "MX-DB-005": {"table": "products", "column": "supplier_id"},
    "MX-SEC-001": {"variable": "ADMIN_PASSWORD", "in_frontend_bundle": False},
    "MX-SEC-002": {
        "handler": "refund_payment",
        "method": "POST",
        "path": "/api/payments/{}/refund",
        "sensitive_terms": ["refund", "payment"],
        "protected_siblings": ["list_payments"],
        "sibling_dependencies": ["require_user"],
    },
    "MX-SEC-003": {"allow_origins": ["*"], "allow_credentials": True},
    "MX-SEC-004": {
        "file": "backend/.env",
        "credential_keys": ["DATABASE_URL"],
        "variable_count": 6,
    },
    "MX-SEC-005": {"factory": "FastAPI"},
    "MX-DEP-001": {
        "package": "PyYAML",
        "version": "5.3.1",
        "advisories": ["CVE-2020-14343"],
        "fixed_versions": ["5.4"],
        "ecosystem": "PyPI",
    },
}

_FILES: dict[str, str] = {
    "MX-API": "frontend/src/api/users.ts",
    "MX-DB": "backend/app/models.py",
    "MX-SEC": "backend/app/auth.py",
    "MX-DEP": "backend/requirements.txt",
}


def build(rule_id: str, *, snippet: str = 'api.get("/api/user/${id}");') -> Finding:
    area = rule_id.rsplit("-", 1)[0]
    metadata = _METADATA[rule_id]
    # A whole-file rule reports the offending file as its location, so the
    # fixture must agree with its own metadata or the rendered fix will cite a
    # path the finding does not point at.
    file_path = str(metadata.get("file") or _FILES[area])
    return make_finding(
        rule_id,
        identity=(rule_id,),
        locations=[SourceLocation(file_path=file_path, line_start=7, line_end=7, snippet=snippet)],
        description="A description of the defect.",
        expected="the expected value",
        actual="the actual value",
        metadata=metadata,
    )


ALL_RULES = sorted(REGISTRY)


class TestCoverage:
    def test_every_registered_rule_has_a_template(self) -> None:
        """Otherwise a rule silently falls back to generic prose."""
        from app.services.explanation_templates import _TEMPLATES

        missing = sorted(set(REGISTRY) - set(_TEMPLATES))

        assert missing == [], f"rules with no explanation template: {missing}"

    def test_no_template_exists_for_an_unregistered_rule(self) -> None:
        from app.services.explanation_templates import _TEMPLATES

        extra = sorted(set(_TEMPLATES) - set(REGISTRY))

        assert extra == [], f"templates for rules that do not exist: {extra}"


class TestQuality:
    @pytest.mark.parametrize("rule_id", ALL_RULES)
    def test_the_explanation_is_substantial(self, rule_id: str) -> None:
        rendered = render_template(build(rule_id))

        assert len(rendered.explanation) > 80, rule_id
        assert rendered.explanation.rstrip().endswith((".", "!"))
        # Many explanations correctly open with a code identifier or a path --
        # `exportUsers requests ...`, `backend/.env is committed ...` -- which
        # must not be capitalised. Anything else should read as a sentence.
        first_word = rendered.explanation.split()[0]
        looks_like_code = bool(re.match(r"^[a-z_][\w.]*$|^[\w./-]+\.[a-z]+$", first_word))
        assert rendered.explanation[0].isupper() or looks_like_code, rule_id

    @pytest.mark.parametrize("rule_id", ALL_RULES)
    def test_the_fix_names_the_real_location(self, rule_id: str) -> None:
        """Generic advice is worth less than the rule's title."""
        finding = build(rule_id)
        rendered = render_template(finding)

        combined = f"{rendered.suggested_fix} {rendered.fix_after or ''}"
        location = str(finding.primary_location)
        file_path = finding.primary_location.file_path
        subject = finding.metadata.get("table") or finding.metadata.get("package")

        # A whole-file finding (a committed .env) is specific enough naming the
        # file; a line-level one must cite file:line.
        assert (
            location in rendered.suggested_fix
            or file_path in combined
            or (subject and str(subject) in combined)
        ), f"{rule_id}: the fix references neither {location} nor {subject}"

    @pytest.mark.parametrize("rule_id", ALL_RULES)
    def test_a_concrete_before_and_after_is_produced(self, rule_id: str) -> None:
        rendered = render_template(build(rule_id))

        assert rendered.fix_before, f"{rule_id}: no before"
        assert rendered.fix_after, f"{rule_id}: no after"
        assert rendered.fix_before != rendered.fix_after

    @pytest.mark.parametrize("rule_id", ALL_RULES)
    def test_the_source_is_marked_as_a_template(self, rule_id: str) -> None:
        assert render_template(build(rule_id)).source == "template"

    @pytest.mark.parametrize("rule_id", ALL_RULES)
    def test_no_unrendered_placeholders(self, rule_id: str) -> None:
        """A template bug shows up as a stray brace or a 'None' in the prose."""
        rendered = render_template(build(rule_id))
        text = " ".join([rendered.explanation, rendered.suggested_fix, rendered.fix_after or ""])

        # A template bug surfaces as a literal None or an unsubstituted
        # str.format placeholder. Braces themselves are legitimate: real code
        # and normalised paths both contain them.
        assert " None" not in text, f"{rule_id}: unrendered value"
        assert not re.search(r"\{(?:rule_id|finding|metadata)", text), rule_id

    @pytest.mark.parametrize("rule_id", ALL_RULES)
    def test_the_fingerprint_is_carried_through(self, rule_id: str) -> None:
        finding = build(rule_id)

        assert render_template(finding).fingerprint == finding.fingerprint


class TestSpecificFixes:
    """The fixes a user will actually copy."""

    def test_a_path_typo_becomes_a_corrected_line(self) -> None:
        rendered = render_template(
            build("MX-API-002", snippet="const r = await api.get(`/api/user/${id}`);")
        )

        assert rendered.fix_before == "const r = await api.get(`/api/user/${id}`);"
        assert rendered.fix_after == "const r = await api.get(`/api/users/${id}`);"

    def test_the_interpolation_survives_the_correction(self) -> None:
        """Replacing `${id}` with `{}` would make the fix uncopyable."""
        rendered = render_template(build("MX-API-002"))

        assert "${id}" in (rendered.fix_after or "")

    def test_a_method_mismatch_swaps_the_verb(self) -> None:
        rendered = render_template(
            build("MX-API-003", snippet="await api.post(`/api/users/${id}/deactivate`);")
        )

        assert rendered.fix_after == "await api.delete(`/api/users/${id}/deactivate`);"

    def test_field_drift_shows_the_renamed_key(self) -> None:
        rendered = render_template(
            build("MX-API-004", snippet="api.post('/api/users', { email, fullName });")
        )

        assert "full_name: fullName" in (rendered.fix_after or "")

    def test_a_missing_column_produces_an_alter_table(self) -> None:
        rendered = render_template(build("MX-DB-001"))

        assert "ALTER TABLE products ADD COLUMN warehouse_code VARCHAR(255);" in (
            rendered.fix_after or ""
        )

    def test_a_missing_foreign_key_produces_a_constraint(self) -> None:
        rendered = render_template(build("MX-DB-004"))

        after = rendered.fix_after or ""
        assert "FOREIGN KEY (supplier_id) REFERENCES suppliers(id)" in after

    def test_an_unindexed_key_produces_a_create_index(self) -> None:
        rendered = render_template(build("MX-DB-005"))

        assert rendered.fix_after == (
            "CREATE INDEX ix_products_supplier_id ON products (supplier_id);"
        )

    def test_a_python_secret_is_moved_to_the_environment(self) -> None:
        rendered = render_template(build("MX-SEC-001", snippet='ADMIN_PASSWORD = "********2024"'))

        assert 'os.environ["ADMIN_PASSWORD"]' in (rendered.fix_after or "")
        assert "Rotate" in rendered.suggested_fix

    def test_a_frontend_secret_says_it_reaches_the_browser(self) -> None:
        finding = make_finding(
            "MX-SEC-001",
            identity=("config.ts", "STRIPE_KEY"),
            locations=[
                SourceLocation(
                    file_path="frontend/src/config.ts",
                    line_start=3,
                    line_end=3,
                    snippet='export const STRIPE_KEY = "********JkOm";',
                )
            ],
            description="d",
            metadata={"variable": "STRIPE_KEY", "in_frontend_bundle": True},
        )

        rendered = render_template(finding)

        assert "browser" in rendered.explanation
        assert "backend" in (rendered.fix_after or "")

    def test_an_unprotected_route_gains_its_siblings_dependency(self) -> None:
        rendered = render_template(build("MX-SEC-002"))

        assert "Depends(require_user)" in (rendered.fix_after or "")

    def test_a_committed_env_shows_the_git_command(self) -> None:
        rendered = render_template(build("MX-SEC-004"))

        after = rendered.fix_after or ""
        assert "git rm --cached backend/.env" in after
        assert ".gitignore" in after

    def test_a_vulnerable_pin_is_raised_to_the_fixed_version(self) -> None:
        rendered = render_template(build("MX-DEP-001"))

        assert rendered.fix_before == "PyYAML==5.3.1"
        assert rendered.fix_after == "PyYAML==5.4"

    def test_an_npm_pin_uses_json_syntax(self) -> None:
        finding = make_finding(
            "MX-DEP-001",
            identity=("npm", "axios", "1.6.0"),
            locations=[
                SourceLocation(
                    file_path="frontend/package.json",
                    line_start=5,
                    line_end=5,
                    snippet='"axios": "1.6.0",',
                )
            ],
            description="d",
            metadata={
                "package": "axios",
                "version": "1.6.0",
                "advisories": ["CVE-x"],
                "fixed_versions": ["1.7.4"],
                "ecosystem": "npm",
            },
        )

        rendered = render_template(finding)

        assert rendered.fix_before == '"axios": "1.6.0"'
        assert rendered.fix_after == '"axios": "1.7.4"'

    def test_a_vulnerability_with_no_fix_says_so(self) -> None:
        finding = make_finding(
            "MX-DEP-001",
            identity=("PyPI", "thing", "1.0"),
            locations=[
                SourceLocation(
                    file_path="requirements.txt", line_start=1, line_end=1, snippet="thing==1.0"
                )
            ],
            description="d",
            metadata={
                "package": "thing",
                "version": "1.0",
                "advisories": ["CVE-y"],
                "fixed_versions": [],
                "ecosystem": "PyPI",
            },
        )

        rendered = render_template(finding)

        assert "No fixed version" in rendered.suggested_fix
        assert not rendered.fix_after


class TestAgainstRealFindings:
    """Rendered against findings the engine actually produced."""

    async def test_every_fixture_finding_renders(self, fixture_repo: object) -> None:
        from app.analysis.engine import analyse
        from app.services.osv import StaticVulnerabilityClient

        for name in (
            "react_fastapi_mismatch",
            "react_fastapi_schema_drift",
            "react_fastapi_insecure",
        ):
            root: Path = fixture_repo(name)  # type: ignore[operator]
            result = await analyse(root, vulnerability_client=StaticVulnerabilityClient({}))

            for finding in result.findings:
                rendered = render_template(finding)
                assert rendered.explanation.strip(), f"{name} {finding.rule_id}"
                assert rendered.suggested_fix.strip(), f"{name} {finding.rule_id}"
                combined = f"{rendered.suggested_fix} {rendered.fix_after or ''}"
                assert (
                    str(finding.primary_location) in rendered.suggested_fix
                    or finding.primary_location.file_path in combined
                    or finding.metadata.get("table")
                    or finding.metadata.get("package")
                ), f"{name} {finding.rule_id}: fix is not specific"

    async def test_no_rendered_fix_leaks_a_secret(self, fixture_repo: object) -> None:
        from app.analysis.engine import analyse
        from app.services.osv import StaticVulnerabilityClient

        root: Path = fixture_repo("react_fastapi_insecure")  # type: ignore[operator]
        result = await analyse(root, vulnerability_client=StaticVulnerabilityClient({}))

        literals = [
            "sk_live_51H8xQ2KmNvR7pLdX4bWcZaYeTfUgIhJkOm",
            "Adm1n!Payments2024",
            "p0stgr3s-prod-pw",
            "super-secret-dev-key-do-not-ship",
        ]
        for finding in result.findings:
            rendered = render_template(finding)
            text = " ".join(
                [
                    rendered.explanation,
                    rendered.suggested_fix,
                    rendered.fix_before or "",
                    rendered.fix_after or "",
                ]
            )
            for literal in literals:
                assert literal not in text, f"{finding.rule_id} leaked {literal!r}"
