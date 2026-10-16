"""Frontend HTTP call extraction.

Half of these tests are about what must *not* be extracted. An HTTP-verb
member on a non-client receiver (``cache.get``, ``map.set``) is the obvious
trap, and treating one as a request would invent an endpoint that was never
called.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.extractors.frontend_api_calls import (
    FrontendApiCall,
    extract_from_module,
    extract_frontend_api_calls,
)
from app.services.parsers.base import SourceFile
from app.services.parsers.js_ts_parser import parse_source


def calls_in(text: str, path: str = "src/api.ts") -> list[FrontendApiCall]:
    module = parse_source(SourceFile(path, text, tuple(text.splitlines())))
    assert module is not None
    return extract_from_module(module)


def one_call(text: str, path: str = "src/api.ts") -> FrontendApiCall:
    found = calls_in(text, path)
    assert len(found) == 1, f"expected exactly one call, got {[str(c) for c in found]}"
    return found[0]


class TestClients:
    def test_extracts_a_fetch_call(self) -> None:
        call = one_call('fetch("/api/users");\n')

        assert (call.method, call.path, call.client) == ("GET", "/api/users", "fetch")

    def test_fetch_method_comes_from_the_options(self) -> None:
        call = one_call('fetch("/api/users", { method: "POST" });\n')

        assert call.method == "POST"

    def test_fetch_method_is_upper_cased(self) -> None:
        assert one_call('fetch("/a", { method: "delete" });\n').method == "DELETE"

    @pytest.mark.parametrize(
        ("source", "method"),
        [
            ('axios.get("/a")', "GET"),
            ('axios.post("/a", {})', "POST"),
            ('axios.put("/a", {})', "PUT"),
            ('axios.patch("/a", {})', "PATCH"),
            ('axios.delete("/a")', "DELETE"),
            ('api.get("/a")', "GET"),
            ('apiClient.post("/a", {})', "POST"),
            ('httpClient.get("/a")', "GET"),
            ('ky.post("/a", {})', "POST"),
        ],
    )
    def test_extracts_method_bearing_members(self, source: str, method: str) -> None:
        call = one_call(f"{source};\n")

        assert call.method == method
        assert call.path == "/a"

    def test_extracts_the_axios_single_object_form(self) -> None:
        call = one_call('axios({ url: "/api/users", method: "PUT" });\n')

        assert (call.method, call.path) == ("PUT", "/api/users")

    def test_the_single_object_form_defaults_to_get(self) -> None:
        assert one_call('axios({ url: "/api/users" });\n').method == "GET"


class TestNotHttpCalls:
    @pytest.mark.parametrize(
        "source",
        [
            'cache.get("user-settings")',
            'map.get("key")',
            'headers.get("content-type")',
            'localStorage.get("token")',
            'searchParams.get("page")',
            'queryClient.get("key")',
            'cookies.get("session")',
            'store.get("state")',
        ],
    )
    def test_ignores_verb_members_on_non_clients(self, source: str) -> None:
        """`cache.get("x")` is not a request to /x."""
        assert calls_in(f"{source};\n") == []

    @pytest.mark.parametrize(
        "source",
        [
            'api.get("user-settings")',
            'api.get("not a path")',
            'api.get("")',
        ],
    )
    def test_ignores_arguments_that_are_not_paths(self, source: str) -> None:
        """A client method called with a non-path string is not a request."""
        assert calls_in(f"{source};\n") == []

    @pytest.mark.parametrize(
        "source",
        [
            "response.json()",
            "array.map(f)",
            "promise.then(f)",
            'console.log("/api/users")',
            "axios.create({ baseURL: '/api' })",
            "api.interceptors.response.use(f)",
        ],
    )
    def test_ignores_unrelated_calls(self, source: str) -> None:
        assert calls_in(f"{source};\n") == []

    def test_ignores_a_call_with_no_arguments(self) -> None:
        assert calls_in("fetch();\n") == []


class TestRequestBodies:
    def test_reads_axios_body_fields(self) -> None:
        call = one_call('api.post("/api/users", { email, fullName });\n')

        assert call.request_fields == ("email", "fullName")

    def test_reads_explicit_keys(self) -> None:
        call = one_call('api.post("/a", { email: e, full_name: n });\n')

        assert call.request_fields == ("email", "full_name")

    def test_unwraps_json_stringify_for_fetch(self) -> None:
        call = one_call('fetch("/a", { method: "POST", body: JSON.stringify({ a: 1, b: 2 }) });\n')

        assert call.request_fields == ("a", "b")

    def test_reads_the_ky_json_option(self) -> None:
        call = one_call('ky.post("/a", { json: { a: 1 } });\n')

        assert call.request_fields == ("a",)

    def test_a_get_has_no_body_fields(self) -> None:
        """A GET's second argument is configuration, never a payload."""
        call = one_call('api.get("/a", { responseType: "blob" });\n')

        assert call.request_fields == ()

    def test_a_config_object_is_not_read_as_a_body(self) -> None:
        call = one_call('api.post("/a", { headers: { X: "1" }, timeout: 5 });\n')

        assert call.request_fields == ()

    def test_a_non_literal_body_yields_no_fields(self) -> None:
        call = one_call('api.post("/a", payload);\n')

        assert call.request_fields == ()


class TestAuthDetection:
    @pytest.mark.parametrize(
        "source",
        [
            'api.get("/a", { headers: { Authorization: "Bearer x" } })',
            'api.get("/a", { headers: { authorization: "Bearer x" } })',
            'api.get("/a", { headers: { "X-API-Key": "x" } })',
            'api.get("/a", { headers: { apikey: "x" } })',
            'api.get("/a", { withCredentials: true })',
            'fetch("/a", { credentials: "include" })',
            'api.get("/a", { headers: authHeaders() })',
        ],
    )
    def test_detects_credentials(self, source: str) -> None:
        assert one_call(f"{source};\n").has_auth_header is True

    def test_detects_auth_in_the_axios_third_argument(self) -> None:
        """`axios.post(url, data, config)` -- the header is in the *third* arg."""
        call = one_call(
            'api.post("/a", { amount: 1 }, { headers: { Authorization: "Bearer x" } });\n'
        )

        assert call.has_auth_header is True
        assert call.request_fields == ("amount",)

    @pytest.mark.parametrize(
        "source",
        [
            'api.get("/a")',
            'api.get("/a", { timeout: 5 })',
            'api.get("/a", { headers: { "Content-Type": "application/json" } })',
        ],
    )
    def test_reports_no_credentials_when_there_are_none(self, source: str) -> None:
        assert one_call(f"{source};\n").has_auth_header is False


class TestBaseUrls:
    def test_a_relative_base_url_becomes_a_prefix(self) -> None:
        """Missing this would make every call under the client mismatch."""
        source = """
        const api = axios.create({ baseURL: "/api/v1" });
        api.get("/users");
        """
        call = one_call(source)

        assert call.path == "/api/v1/users"

    def test_an_absolute_base_url_contributes_only_its_path(self) -> None:
        source = """
        const api = axios.create({ baseURL: "http://localhost:8000" });
        api.get("/users");
        """
        call = one_call(source)

        assert call.path == "/users"

    def test_an_absolute_base_url_with_a_path_prefixes_it(self) -> None:
        source = """
        const api = axios.create({ baseURL: "http://localhost:8000/api" });
        api.get("/users");
        """
        call = one_call(source)

        assert call.path == "/api/users"

    def test_an_interpolated_base_url_is_not_a_prefix(self) -> None:
        source = """
        const api = axios.create({ baseURL: `${process.env.URL}` });
        api.get("/users");
        """
        call = one_call(source)

        assert call.path == "/users"


class TestTemplateLiterals:
    def test_a_path_parameter_is_normalised(self) -> None:
        call = one_call("api.get(`/api/users/${id}`);\n")

        assert call.path == "/api/users/{}"
        assert call.raw_path == "/api/users/${id}"

    def test_an_interpolated_base_is_not_a_segment(self) -> None:
        call = one_call("api.get(`${API_BASE}/api/users`);\n")

        assert call.path == "/api/users"
        assert call.normalized.base_url == "${API_BASE}"


class TestUnresolvedUrls:
    def test_a_variable_url_is_recorded_with_low_confidence(self) -> None:
        """Recorded so coverage is honest, but never compared against routes."""
        call = one_call("api.get(endpoint);\n")

        assert call.confidence < 0.5
        assert "url_not_statically_known" in call.notes
        assert call.is_comparable is False

    def test_a_concatenated_url_is_not_comparable(self) -> None:
        call = one_call("api.get(BASE + path);\n")

        assert call.is_comparable is False


class TestEnclosingFunction:
    def test_names_a_function_declaration(self) -> None:
        source = 'export async function getUser(id) {\n  return api.get("/a");\n}\n'

        assert one_call(source).enclosing_function == "getUser"

    def test_names_an_arrow_function_assigned_to_a_const(self) -> None:
        source = 'const getUser = async (id) => {\n  return api.get("/a");\n};\n'

        assert one_call(source).enclosing_function == "getUser"

    def test_a_top_level_call_has_no_enclosing_function(self) -> None:
        assert one_call('api.get("/a");\n').enclosing_function is None


class TestLocationsAndOrdering:
    def test_each_call_reports_its_own_line(self) -> None:
        source = 'api.get("/a");\n\napi.post("/b", {});\n\napi.get("/c");\n'

        found = calls_in(source)

        assert [call.location.line_start for call in found] == [1, 3, 5]

    def test_results_are_sorted_by_file_then_line(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "b.ts").write_text('api.get("/b");\n', encoding="utf-8")
        (tmp_path / "src" / "a.ts").write_text(
            'api.get("/a1");\napi.get("/a2");\n', encoding="utf-8"
        )

        found = extract_frontend_api_calls(tmp_path)

        assert [(c.location.file_path, c.location.line_start) for c in found] == [
            ("src/a.ts", 1),
            ("src/a.ts", 2),
            ("src/b.ts", 1),
        ]

    def test_paths_are_relative_to_the_repository_root(self, tmp_path: Path) -> None:
        """A finding must cite the path a developer sees."""
        (tmp_path / "frontend" / "src").mkdir(parents=True)
        (tmp_path / "frontend" / "src" / "api.ts").write_text('api.get("/a");\n', encoding="utf-8")

        found = extract_frontend_api_calls(tmp_path, subdirectories=("frontend",))

        assert found[0].location.file_path == "frontend/src/api.ts"

    def test_a_missing_subdirectory_is_skipped_quietly(self, tmp_path: Path) -> None:
        assert extract_frontend_api_calls(tmp_path, subdirectories=("nope",)) == []
