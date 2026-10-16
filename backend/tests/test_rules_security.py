"""Security rules.

Secret detection lives or dies on its false-positive rate, so the exclusion
tests outnumber the detection tests. A scanner that flags UUIDs, test
fixtures and placeholder values gets muted, and a muted scanner finds nothing.

The redaction tests are themselves security tests: a finding that quotes the
credential it found has moved the secret into a database that is served over
an API.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.analysis.findings import Finding
from app.analysis.rules.security import (
    SecurityInput,
    is_placeholder,
    looks_like_secret_value,
    run_security_rules,
    shannon_entropy,
)
from app.models.enums import Severity
from app.services.extractors.backend_routes import extract_backend_routes


def write(root: Path, files: dict[str, str]) -> Path:
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def findings_of(root: Path) -> list[Finding]:
    return run_security_rules(SecurityInput(root=root, routes=extract_backend_routes(root)))


def analyse(root: Path) -> list[str]:
    return sorted(finding.rule_id for finding in findings_of(root))


class TestEntropy:
    def test_random_tokens_score_high(self) -> None:
        assert shannon_entropy("aB3dEfGhIjKlMnOpQrStUv") > 3.5

    def test_repeated_characters_score_zero(self) -> None:
        assert shannon_entropy("aaaaaaaaaa") == 0.0

    def test_an_empty_string_is_zero(self) -> None:
        assert shannon_entropy("") == 0.0


class TestPlaceholderExclusions:
    @pytest.mark.parametrize(
        "value",
        [
            "changeme",
            "CHANGEME",
            "your-api-key-here",
            "your_secret",
            "<your-token>",
            "${API_KEY}",
            "xxxxxxxxxxxx",
            "aaaaaaaaaaaa",
            "placeholder",
            "example",
            "1.2.3",
            "2.11.2",
            "https://example.com/callback",
            "postgresql://user:pass@localhost:5432/db",
        ],
    )
    def test_these_are_not_secrets(self, value: str) -> None:
        assert is_placeholder(value) or not looks_like_secret_value(value)

    @pytest.mark.parametrize(
        "value",
        [
            "short",
            "abc123",
            "a b c d e f g h",
            "/usr/local/share/config",
            "application/json",
        ],
    )
    def test_these_do_not_look_like_credentials(self, value: str) -> None:
        assert not looks_like_secret_value(value)

    @pytest.mark.parametrize(
        "value",
        [
            "Adm1n!Payments2024",
            "p0stgr3s-prod-pw",
            "super-secret-dev-key-do-not-ship",
            "8f4a9c2e1b7d3f6a0e5c8b2d9f1a4e7c",
        ],
    )
    def test_these_do_look_like_credentials(self, value: str) -> None:
        assert looks_like_secret_value(value)


class TestProviderPatterns:
    @pytest.mark.parametrize(
        ("line", "label"),
        [
            ('KEY = "sk_live_51H8xQ2KmNvR7pLdX4bWcZaYeTfUgIhJkOm"', "Stripe"),
            ('AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"', "AWS"),
            ('GH = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"', "GitHub"),
            ('SG = "SG.aB3dEfGhIjKlMnOpQrSt.WxYz1234567890AbCdEfGh"', "SendGrid"),
            (
                'JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.abcd"',
                "JWT",
            ),
        ],
    )
    def test_detects_provider_prefixed_credentials(
        self, tmp_path: Path, line: str, label: str
    ) -> None:
        write(tmp_path, {"config.py": f"{line}\n"})

        findings = findings_of(tmp_path)

        assert [finding.rule_id for finding in findings] == ["MX-SEC-001"], label
        assert findings[0].confidence > 0.9

    def test_a_provider_match_is_near_certain(self, tmp_path: Path) -> None:
        write(tmp_path, {"c.py": 'K = "sk_live_51H8xQ2KmNvR7pLdX4bWcZaYeTfUgIhJkOm"\n'})

        assert findings_of(tmp_path)[0].confidence >= 0.95


class TestNamedCredentials:
    def test_detects_a_credential_shaped_name(self, tmp_path: Path) -> None:
        write(tmp_path, {"auth.py": 'ADMIN_PASSWORD = "Adm1n!Payments2024"\n'})

        findings = findings_of(tmp_path)

        assert [finding.rule_id for finding in findings] == ["MX-SEC-001"]
        assert findings[0].metadata["variable"] == "ADMIN_PASSWORD"

    def test_a_named_match_carries_lower_confidence(self, tmp_path: Path) -> None:
        """It is an inference, not a provider-issued format."""
        write(tmp_path, {"auth.py": 'ADMIN_PASSWORD = "Adm1n!Payments2024"\n'})

        assert findings_of(tmp_path)[0].confidence < 0.95

    def test_detects_a_committed_environment_fallback(self, tmp_path: Path) -> None:
        """The literal default is what runs whenever the variable is unset."""
        write(
            tmp_path,
            {
                "main.py": (
                    "import os\n"
                    'JWT_SIGNING_KEY = os.getenv("JWT_SIGNING_KEY", '
                    '"super-secret-dev-key-do-not-ship")\n'
                )
            },
        )

        findings = findings_of(tmp_path)

        assert [finding.rule_id for finding in findings] == ["MX-SEC-001"]

    def test_an_environment_lookup_with_no_default_is_silent(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {"main.py": 'import os\nJWT_SIGNING_KEY = os.getenv("JWT_SIGNING_KEY")\n'},
        )

        assert analyse(tmp_path) == []

    def test_a_non_credential_name_is_silent(self, tmp_path: Path) -> None:
        """A high-entropy value under an innocent name is not reported."""
        write(tmp_path, {"c.py": 'BUILD_HASH = "8f4a9c2e1b7d3f6a0e5c8b2d9f1a4e7c"\n'})

        assert analyse(tmp_path) == []

    def test_a_public_url_is_not_a_secret(self, tmp_path: Path) -> None:
        write(
            tmp_path, {"c.ts": 'export const API_BASE_URL = "https://api.payments.example.com";\n'}
        )

        assert analyse(tmp_path) == []

    def test_a_placeholder_under_a_secret_name_is_silent(self, tmp_path: Path) -> None:
        write(tmp_path, {"c.py": 'API_KEY = "your-api-key-here"\n'})

        assert analyse(tmp_path) == []

    def test_a_minified_line_is_skipped(self, tmp_path: Path) -> None:
        """A bundle is not hand-written source."""
        write(tmp_path, {"bundle.js": 'var SECRET_KEY="' + "a1b2c3d4" * 90 + '";\n'})

        assert analyse(tmp_path) == []


class TestRedaction:
    SECRET = "sk_live_51H8xQ2KmNvR7pLdX4bWcZaYeTfUgIhJkOm"

    def test_the_secret_never_appears_in_the_finding(self, tmp_path: Path) -> None:
        write(tmp_path, {"c.py": f'STRIPE_KEY = "{self.SECRET}"\n'})

        finding = findings_of(tmp_path)[0]
        rendered = " ".join(
            [finding.description, finding.evidence, finding.actual or "", str(finding.metadata)]
        )

        assert self.SECRET not in rendered

    def test_the_evidence_still_shows_the_code(self, tmp_path: Path) -> None:
        write(tmp_path, {"c.py": f'STRIPE_KEY = "{self.SECRET}"\n'})

        assert "STRIPE_KEY" in findings_of(tmp_path)[0].evidence

    def test_a_frontend_secret_says_so(self, tmp_path: Path) -> None:
        write(tmp_path, {"config.ts": f'export const K = "{self.SECRET}";\n'})

        finding = findings_of(tmp_path)[0]

        assert finding.metadata["in_frontend_bundle"] is True
        assert "browser" in finding.description


class TestCommittedEnvFile:
    def test_reports_a_committed_env(self, tmp_path: Path) -> None:
        write(tmp_path, {".env": "DATABASE_PASSWORD=xK9mPq2wRtY7\nDEBUG=true\n"})

        findings = findings_of(tmp_path)

        assert [finding.rule_id for finding in findings] == ["MX-SEC-004"]

    def test_the_values_are_masked(self, tmp_path: Path) -> None:
        write(tmp_path, {".env": "DATABASE_PASSWORD=xK9mPq2wRtY7xyz\n"})

        finding = findings_of(tmp_path)[0]

        assert "xK9mPq2wRtY7xyz" not in finding.evidence
        assert "xK9mPq2wRtY7xyz" not in str(finding.metadata)

    def test_only_keys_are_recorded_in_metadata(self, tmp_path: Path) -> None:
        write(tmp_path, {".env": "SECRET_TOKEN=abcdefghijklmnop\n"})

        finding = findings_of(tmp_path)[0]

        assert finding.metadata["all_keys"] == ["SECRET_TOKEN"]
        assert "credential_keys" in finding.metadata

    def test_an_env_example_is_not_reported(self, tmp_path: Path) -> None:
        """A template is meant to be committed."""
        write(tmp_path, {".env.example": "DATABASE_PASSWORD=\n"})

        assert analyse(tmp_path) == []

    def test_individual_env_lines_are_not_double_reported(self, tmp_path: Path) -> None:
        """One root cause -- the file is committed -- so one finding."""
        write(
            tmp_path,
            {
                ".env": (
                    "STRIPE_SECRET_KEY=sk_live_51H8xQ2KmNvR7pLdX4bWcZaYeTfUgIhJkOm\n"
                    "ADMIN_PASSWORD=Adm1n!Payments2024\n"
                )
            },
        )

        assert analyse(tmp_path) == ["MX-SEC-004"]


class TestCors:
    def test_reports_a_wildcard_with_credentials(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "main.py": (
                    "from fastapi import FastAPI\n"
                    "from fastapi.middleware.cors import CORSMiddleware\n"
                    "app = FastAPI()\n"
                    "app.add_middleware(\n"
                    "    CORSMiddleware,\n"
                    '    allow_origins=["*"],\n'
                    "    allow_credentials=True,\n"
                    ")\n"
                )
            },
        )

        findings = findings_of(tmp_path)

        assert [finding.rule_id for finding in findings] == ["MX-SEC-003"]
        assert findings[0].severity is Severity.HIGH

    def test_a_wildcard_without_credentials_is_lower_severity(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "main.py": (
                    "from fastapi import FastAPI\n"
                    "from fastapi.middleware.cors import CORSMiddleware\n"
                    "app = FastAPI()\n"
                    'app.add_middleware(CORSMiddleware, allow_origins=["*"])\n'
                )
            },
        )

        assert findings_of(tmp_path)[0].severity is Severity.MEDIUM

    def test_an_explicit_origin_list_is_silent(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "main.py": (
                    "from fastapi import FastAPI\n"
                    "from fastapi.middleware.cors import CORSMiddleware\n"
                    "app = FastAPI()\n"
                    "app.add_middleware(\n"
                    "    CORSMiddleware,\n"
                    '    allow_origins=["http://localhost:5173"],\n'
                    "    allow_credentials=True,\n"
                    ")\n"
                )
            },
        )

        assert analyse(tmp_path) == []

    def test_other_middleware_is_ignored(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "main.py": (
                    "from fastapi import FastAPI\n"
                    "app = FastAPI()\n"
                    'app.add_middleware(GZipMiddleware, allow_origins=["*"])\n'
                )
            },
        )

        assert analyse(tmp_path) == []


class TestDebugMode:
    @pytest.mark.parametrize("factory", ["FastAPI", "Flask", "Starlette"])
    def test_reports_debug_true(self, tmp_path: Path, factory: str) -> None:
        write(tmp_path, {"main.py": f"app = {factory}(debug=True)\n"})

        assert analyse(tmp_path) == ["MX-SEC-005"]

    def test_reports_run_with_debug(self, tmp_path: Path) -> None:
        write(tmp_path, {"main.py": "app.run(debug=True)\n"})

        assert analyse(tmp_path) == ["MX-SEC-005"]

    def test_debug_false_is_silent(self, tmp_path: Path) -> None:
        write(tmp_path, {"main.py": "app = FastAPI(debug=False)\n"})

        assert analyse(tmp_path) == []

    def test_a_debug_variable_is_silent(self, tmp_path: Path) -> None:
        """`debug=settings.debug` is configuration, not a hardcoded mistake."""
        write(tmp_path, {"main.py": "app = FastAPI(debug=settings.debug)\n"})

        assert analyse(tmp_path) == []


class TestUnprotectedRoutes:
    PROTECTED_SIBLINGS = (
        "from fastapi import Depends, FastAPI\n"
        "app = FastAPI()\n"
        '@app.get("/payments")\n'
        "def list_payments(user = Depends(require_user)):\n"
        "    pass\n"
        '@app.delete("/payments/{pid}")\n'
        "def delete_payment(pid: str, user = Depends(require_user)):\n"
        "    pass\n"
    )

    def test_reports_a_sensitive_route_among_protected_siblings(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "routes.py": (
                    self.PROTECTED_SIBLINGS + '@app.post("/payments/{pid}/refund")\n'
                    "def refund_payment(pid: str):\n"
                    "    pass\n"
                )
            },
        )

        findings = findings_of(tmp_path)

        assert [finding.rule_id for finding in findings] == ["MX-SEC-002"]
        assert findings[0].metadata["handler"] == "refund_payment"
        assert "refund" in findings[0].metadata["sensitive_terms"]

    def test_the_finding_names_the_protected_siblings(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "routes.py": (
                    self.PROTECTED_SIBLINGS + '@app.get("/customers/export")\n'
                    "def export_customers():\n"
                    "    pass\n"
                )
            },
        )

        finding = findings_of(tmp_path)[0]

        assert set(finding.metadata["protected_siblings"]) == {
            "list_payments",
            "delete_payment",
        }
        assert finding.metadata["sibling_dependencies"] == ["require_user"]

    def test_an_entirely_public_api_is_silent(self, tmp_path: Path) -> None:
        """No inconsistency to report; a public API is a design choice."""
        write(
            tmp_path,
            {
                "routes.py": (
                    "from fastapi import FastAPI\n"
                    "app = FastAPI()\n"
                    '@app.post("/payments/{pid}/refund")\n'
                    "def refund_payment(pid: str):\n"
                    "    pass\n"
                    '@app.get("/payments")\n'
                    "def list_payments():\n"
                    "    pass\n"
                )
            },
        )

        assert analyse(tmp_path) == []

    def test_an_ordinary_crud_route_is_silent(self, tmp_path: Path) -> None:
        """`create_task` beside a protected route is not a security finding."""
        write(
            tmp_path,
            {
                "routes.py": (
                    "from fastapi import Depends, FastAPI\n"
                    "app = FastAPI()\n"
                    '@app.delete("/tasks/all")\n'
                    "def delete_all_tasks(token = Depends(require_admin)):\n"
                    "    pass\n"
                    '@app.post("/tasks")\n'
                    "def create_task():\n"
                    "    pass\n"
                    '@app.get("/tasks")\n'
                    "def list_tasks():\n"
                    "    pass\n"
                )
            },
        )

        assert analyse(tmp_path) == []

    def test_a_protected_sensitive_route_is_silent(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "routes.py": (
                    self.PROTECTED_SIBLINGS + '@app.post("/payments/{pid}/refund")\n'
                    "def refund_payment(pid: str, user = Depends(require_user)):\n"
                    "    pass\n"
                )
            },
        )

        assert analyse(tmp_path) == []

    def test_routers_are_separate_scopes(self, tmp_path: Path) -> None:
        """A protected route in one module does not implicate another."""
        write(
            tmp_path,
            {
                "admin.py": (
                    "from fastapi import APIRouter, Depends\n"
                    "admin_router = APIRouter()\n"
                    '@admin_router.get("/admin/stats")\n'
                    "def stats(user = Depends(require_user)):\n"
                    "    pass\n"
                ),
                "public.py": (
                    "from fastapi import APIRouter\n"
                    "public_router = APIRouter()\n"
                    '@public_router.post("/payments/refund")\n'
                    "def refund():\n"
                    "    pass\n"
                ),
            },
        )

        assert analyse(tmp_path) == []


class TestFindingShape:
    def test_findings_carry_everything_the_issue_schema_needs(self, tmp_path: Path) -> None:
        write(tmp_path, {"c.py": 'ADMIN_PASSWORD = "Adm1n!Payments2024"\n'})

        finding = findings_of(tmp_path)[0]

        assert finding.primary_location.file_path == "c.py"
        assert finding.primary_location.line_start == 1
        assert finding.evidence.strip()
        assert finding.expected and finding.actual
        assert 0.0 < finding.confidence <= 1.0

    @pytest.mark.parametrize(
        "rule_id",
        ["MX-SEC-001", "MX-SEC-002", "MX-SEC-003", "MX-SEC-004", "MX-SEC-005"],
    )
    def test_every_rule_is_registered(self, rule_id: str) -> None:
        from app.analysis.taxonomy import REGISTRY

        assert rule_id in REGISTRY
