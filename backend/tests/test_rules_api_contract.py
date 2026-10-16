"""API contract rules.

Roughly half of these assert *silence*. A false positive on correct code is
the failure this engine is built to avoid, so each guard gets its own test:
an unresolved mount, a third-party host, an unknown URL, an auth interceptor,
a Pydantic alias.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.analysis.findings import Finding
from app.analysis.rules.api_contract import ApiContractInput, run_api_contract_rules
from app.services.extractors.backend_routes import extract_backend_routes
from app.services.extractors.frontend_api_calls import extract_frontend_api_calls
from app.services.extractors.request_models import extract_request_models
from app.services.parsers.base import SourceLocation


def write(root: Path, files: dict[str, str]) -> Path:
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def analyse(root: Path) -> list[str]:
    """Rule IDs produced for a tree, sorted."""
    data = ApiContractInput(
        calls=extract_frontend_api_calls(root, subdirectories=("frontend",)),
        routes=extract_backend_routes(root, subdirectories=("backend",)),
        request_models=extract_request_models(root, subdirectories=("backend",)),
    )
    return sorted(finding.rule_id for finding in run_api_contract_rules(data))


def findings_of(root: Path) -> list[Finding]:
    data = ApiContractInput(
        calls=extract_frontend_api_calls(root, subdirectories=("frontend",)),
        routes=extract_backend_routes(root, subdirectories=("backend",)),
        request_models=extract_request_models(root, subdirectories=("backend",)),
    )
    return run_api_contract_rules(data)


def backend(routes: str, *, schemas: str = "") -> dict[str, str]:
    files = {
        "backend/main.py": ("from fastapi import Depends, FastAPI\n" "app = FastAPI()\n" + routes)
    }
    if schemas:
        files["backend/schemas.py"] = schemas
    return files


class TestMissingEndpoint:
    def test_reports_a_path_no_route_serves(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                **backend('@app.get("/api/users")\ndef list_users():\n    pass\n'),
                "frontend/api.ts": 'api.get("/api/reports");\n',
            },
        )

        assert analyse(tmp_path) == ["MX-API-001"]

    def test_the_finding_names_the_path_and_method(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                **backend('@app.get("/api/users")\ndef list_users():\n    pass\n'),
                "frontend/api.ts": 'api.post("/api/reports", {});\n',
            },
        )

        finding = findings_of(tmp_path)[0]

        assert "POST /api/reports" in (finding.expected or "")
        assert finding.metadata["method"] == "POST"
        assert finding.primary_location.file_path == "frontend/api.ts"

    def test_a_matching_call_is_silent(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                **backend('@app.get("/api/users")\ndef list_users():\n    pass\n'),
                "frontend/api.ts": 'api.get("/api/users");\n',
            },
        )

        assert analyse(tmp_path) == []

    def test_a_parameterised_path_matches(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                **backend(
                    '@app.get("/api/users/{user_id}")\ndef get_user(user_id: int):\n    pass\n'
                ),
                "frontend/api.ts": "api.get(`/api/users/${id}`);\n",
            },
        )

        assert analyse(tmp_path) == []

    def test_a_mount_prefix_is_respected(self, tmp_path: Path) -> None:
        """The route says /users; it is mounted at /api. The call is correct."""
        write(
            tmp_path,
            {
                "backend/main.py": (
                    "from fastapi import FastAPI\n"
                    "from routers import users\n"
                    "app = FastAPI()\n"
                    'app.include_router(users.router, prefix="/api")\n'
                ),
                "backend/routers/users.py": (
                    "from fastapi import APIRouter\n"
                    "router = APIRouter()\n"
                    '@router.get("/users")\n'
                    "def list_users():\n"
                    "    pass\n"
                ),
                "frontend/api.ts": 'api.get("/api/users");\n',
            },
        )

        assert analyse(tmp_path) == []


class TestSilenceConditions:
    """Each of these would otherwise produce false positives."""

    def test_no_routes_at_all_reports_nothing(self, tmp_path: Path) -> None:
        """A frontend-only repository is not full of missing endpoints."""
        write(tmp_path, {"frontend/api.ts": 'api.get("/api/users");\n'})

        assert analyse(tmp_path) == []

    def test_an_unresolved_mount_suppresses_absence_checks(self, tmp_path: Path) -> None:
        """A router mounted from a name this scan cannot trace."""
        write(
            tmp_path,
            {
                "backend/main.py": (
                    "from fastapi import FastAPI\n"
                    "app = FastAPI()\n"
                    "app.include_router(unknown_module.router)\n"
                    '@app.get("/api/users")\n'
                    "def list_users():\n"
                    "    pass\n"
                ),
                "frontend/api.ts": 'api.get("/api/reports");\n',
            },
        )

        extraction = extract_backend_routes(tmp_path, subdirectories=("backend",))
        assert extraction.unresolved_mounts, "test setup: expected an unresolved mount"

        assert analyse(tmp_path) == []

    def test_a_third_party_host_is_ignored(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                **backend('@app.get("/api/users")\ndef list_users():\n    pass\n'),
                "frontend/api.ts": 'api.get("https://api.stripe.com/v1/charges");\n',
            },
        )

        assert analyse(tmp_path) == []

    def test_an_arbitrary_external_host_is_ignored(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                **backend('@app.get("/api/users")\ndef list_users():\n    pass\n'),
                "frontend/api.ts": 'api.get("https://example.org/data");\n',
            },
        )

        assert analyse(tmp_path) == []

    def test_a_localhost_origin_is_still_checked(self, tmp_path: Path) -> None:
        """A dev-server origin points at this project's own backend."""
        write(
            tmp_path,
            {
                **backend('@app.get("/api/users")\ndef list_users():\n    pass\n'),
                "frontend/api.ts": 'api.get("http://localhost:8000/api/reports");\n',
            },
        )

        assert analyse(tmp_path) == ["MX-API-001"]

    def test_an_unknown_url_is_ignored(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                **backend('@app.get("/api/users")\ndef list_users():\n    pass\n'),
                "frontend/api.ts": "api.get(endpoint);\n",
            },
        )

        assert analyse(tmp_path) == []

    def test_an_interpolated_base_url_is_still_checked(self, tmp_path: Path) -> None:
        """`${API_BASE}/api/x` is the normal way to address this backend."""
        write(
            tmp_path,
            {
                **backend('@app.get("/api/users")\ndef list_users():\n    pass\n'),
                "frontend/api.ts": "api.get(`${API_BASE}/api/reports`);\n",
            },
        )

        assert analyse(tmp_path) == ["MX-API-001"]


class TestPathTypo:
    def test_reports_a_one_character_difference(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                **backend('@app.get("/api/users")\ndef list_users():\n    pass\n'),
                "frontend/api.ts": 'api.get("/api/user");\n',
            },
        )

        assert analyse(tmp_path) == ["MX-API-002"]

    def test_the_finding_suggests_the_real_route(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                **backend('@app.get("/api/users")\ndef list_users():\n    pass\n'),
                "frontend/api.ts": 'api.get("/api/user");\n',
            },
        )

        finding = findings_of(tmp_path)[0]

        assert finding.metadata["suggested_path"] == "/api/users"
        assert finding.expected == "GET /api/users"

    def test_it_takes_precedence_over_missing_endpoint(self, tmp_path: Path) -> None:
        """A near match is a typo, not an absent endpoint; the fix differs."""
        write(
            tmp_path,
            {
                **backend('@app.get("/api/users")\ndef list_users():\n    pass\n'),
                "frontend/api.ts": 'api.get("/api/user");\n',
            },
        )

        assert "MX-API-001" not in analyse(tmp_path)

    def test_a_different_parameter_count_is_not_a_typo(self, tmp_path: Path) -> None:
        """`/users` and `/users/{}` are one edit apart but different endpoints."""
        write(
            tmp_path,
            {
                **backend(
                    '@app.get("/api/users/{user_id}")\ndef get_user(user_id: int):\n    pass\n'
                ),
                "frontend/api.ts": 'api.get("/api/users");\n',
            },
        )

        assert analyse(tmp_path) == ["MX-API-001"]

    def test_a_near_match_on_a_different_method_is_not_a_typo(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                **backend('@app.post("/api/users")\ndef create():\n    pass\n'),
                "frontend/api.ts": 'api.get("/api/user");\n',
            },
        )

        assert analyse(tmp_path) == ["MX-API-001"]


class TestMethodMismatch:
    def test_reports_a_wrong_method(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                **backend('@app.delete("/api/users/{uid}")\ndef remove(uid: int):\n    pass\n'),
                "frontend/api.ts": "api.post(`/api/users/${id}`, {});\n",
            },
        )

        assert analyse(tmp_path) == ["MX-API-003"]

    def test_the_finding_names_both_methods(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                **backend('@app.delete("/api/users/{uid}")\ndef remove(uid: int):\n    pass\n'),
                "frontend/api.ts": "api.post(`/api/users/${id}`, {});\n",
            },
        )

        finding = findings_of(tmp_path)[0]

        assert finding.metadata["call_method"] == "POST"
        assert finding.metadata["route_methods"] == ["DELETE"]

    def test_a_path_with_an_unknown_method_is_silent(self, tmp_path: Path) -> None:
        """Django declares the method in the view, so a mismatch is unprovable."""
        write(
            tmp_path,
            {
                "backend/urls.py": (
                    "from django.urls import path\n"
                    "urlpatterns = [path('api/users/', views.users)]\n"
                ),
                "frontend/api.ts": 'api.post("/api/users", {});\n',
            },
        )

        assert analyse(tmp_path) == []


class TestRequestFieldDrift:
    MODEL = (
        "from pydantic import BaseModel\n"
        "class UserCreate(BaseModel):\n"
        "    email: str\n"
        "    full_name: str\n"
    )

    def test_reports_camel_case_drift(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                **backend(
                    '@app.post("/api/users")\n' "def create(payload: UserCreate):\n" "    pass\n",
                    schemas=self.MODEL,
                ),
                "frontend/api.ts": 'api.post("/api/users", { email, fullName });\n',
            },
        )

        assert analyse(tmp_path) == ["MX-API-004"]

    def test_the_finding_names_both_spellings(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                **backend(
                    '@app.post("/api/users")\ndef create(payload: UserCreate):\n    pass\n',
                    schemas=self.MODEL,
                ),
                "frontend/api.ts": 'api.post("/api/users", { email, fullName });\n',
            },
        )

        finding = findings_of(tmp_path)[0]

        assert finding.metadata["drifted_fields"] == [{"sent": "fullName", "expected": "full_name"}]

    def test_matching_fields_are_silent(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                **backend(
                    '@app.post("/api/users")\ndef create(payload: UserCreate):\n    pass\n',
                    schemas=self.MODEL,
                ),
                "frontend/api.ts": 'api.post("/api/users", { email, full_name });\n',
            },
        )

        assert analyse(tmp_path) == []

    def test_an_alias_makes_the_camel_case_name_correct(self, tmp_path: Path) -> None:
        """`Field(alias="fullName")` means the frontend is right, not wrong."""
        aliased = (
            "from pydantic import BaseModel, Field\n"
            "class UserCreate(BaseModel):\n"
            "    email: str\n"
            '    full_name: str = Field(alias="fullName")\n'
        )
        write(
            tmp_path,
            {
                **backend(
                    '@app.post("/api/users")\ndef create(payload: UserCreate):\n    pass\n',
                    schemas=aliased,
                ),
                "frontend/api.ts": 'api.post("/api/users", { email, fullName });\n',
            },
        )

        assert analyse(tmp_path) == []

    def test_an_alias_generator_suppresses_the_rule(self, tmp_path: Path) -> None:
        """The accepted names cannot be enumerated, so comparison is invalid."""
        generated = (
            "from pydantic import BaseModel, ConfigDict\n"
            "class UserCreate(BaseModel):\n"
            "    model_config = ConfigDict(alias_generator=to_camel)\n"
            "    email: str\n"
            "    full_name: str\n"
        )
        write(
            tmp_path,
            {
                **backend(
                    '@app.post("/api/users")\ndef create(payload: UserCreate):\n    pass\n',
                    schemas=generated,
                ),
                "frontend/api.ts": 'api.post("/api/users", { email, fullName });\n',
            },
        )

        assert analyse(tmp_path) == []

    def test_extra_allow_suppresses_the_rule(self, tmp_path: Path) -> None:
        permissive = (
            "from pydantic import BaseModel, ConfigDict\n"
            "class UserCreate(BaseModel):\n"
            '    model_config = ConfigDict(extra="allow")\n'
            "    email: str\n"
            "    full_name: str\n"
        )
        write(
            tmp_path,
            {
                **backend(
                    '@app.post("/api/users")\ndef create(payload: UserCreate):\n    pass\n',
                    schemas=permissive,
                ),
                "frontend/api.ts": 'api.post("/api/users", { email, fullName });\n',
            },
        )

        assert analyse(tmp_path) == []

    def test_a_field_absent_in_both_casings_is_not_reported(self, tmp_path: Path) -> None:
        """A simply-unknown field could be many benign things."""
        write(
            tmp_path,
            {
                **backend(
                    '@app.post("/api/users")\ndef create(payload: UserCreate):\n    pass\n',
                    schemas=self.MODEL,
                ),
                "frontend/api.ts": 'api.post("/api/users", { email, nickname });\n',
            },
        )

        assert analyse(tmp_path) == []

    def test_a_missing_model_suppresses_the_rule(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                **backend('@app.post("/api/users")\ndef create(payload: Unknown):\n    pass\n'),
                "frontend/api.ts": 'api.post("/api/users", { fullName });\n',
            },
        )

        assert analyse(tmp_path) == []


class TestMissingCredentials:
    PROTECTED = (
        '@app.delete("/api/admin/purge")\n'
        "def purge(user = Depends(require_user)):\n"
        "    pass\n"
    )

    def test_reports_a_call_with_no_credentials(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                **backend(self.PROTECTED),
                "frontend/api.ts": 'api.delete("/api/admin/purge");\n',
            },
        )

        assert "MX-API-005" in analyse(tmp_path)

    def test_a_call_with_an_auth_header_is_silent(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                **backend(self.PROTECTED),
                "frontend/api.ts": (
                    'api.delete("/api/admin/purge", '
                    '{ headers: { Authorization: "Bearer x" } });\n'
                ),
            },
        )

        assert "MX-API-005" not in analyse(tmp_path)

    def test_an_interceptor_suppresses_the_rule(self, tmp_path: Path) -> None:
        """A request interceptor may add the header to every call."""
        write(
            tmp_path,
            {
                **backend(self.PROTECTED),
                "frontend/api.ts": (
                    "api.interceptors.request.use((config) => config);\n"
                    'api.delete("/api/admin/purge");\n'
                ),
            },
        )

        assert "MX-API-005" not in analyse(tmp_path)

    def test_a_client_default_header_suppresses_the_rule(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                **backend(self.PROTECTED),
                "frontend/api.ts": (
                    'const api = axios.create({ headers: { Authorization: "Bearer x" } });\n'
                    'api.delete("/api/admin/purge");\n'
                ),
            },
        )

        assert "MX-API-005" not in analyse(tmp_path)

    def test_an_unprotected_route_is_silent(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                **backend('@app.get("/api/public")\ndef public():\n    pass\n'),
                "frontend/api.ts": 'api.get("/api/public");\n',
            },
        )

        assert analyse(tmp_path) == []


class TestFindingShape:
    """Every finding must carry what the issue schema needs."""

    def test_findings_carry_location_snippet_and_comparison(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                **backend('@app.get("/api/users")\ndef list_users():\n    pass\n'),
                "frontend/api.ts": 'api.get("/api/user");\n',
            },
        )

        finding = findings_of(tmp_path)[0]

        assert isinstance(finding.primary_location, SourceLocation)
        assert finding.primary_location.snippet.strip()
        assert finding.evidence.strip()
        assert finding.expected and finding.actual
        assert finding.description
        assert 0.0 < finding.confidence <= 1.0
        assert finding.fingerprint

    @pytest.mark.parametrize(
        "rule_id", ["MX-API-001", "MX-API-002", "MX-API-003", "MX-API-004", "MX-API-005"]
    )
    def test_every_rule_is_registered(self, rule_id: str) -> None:
        from app.analysis.taxonomy import REGISTRY

        assert rule_id in REGISTRY
