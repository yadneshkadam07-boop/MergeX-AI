"""Path normalisation -- the basis of every cross-layer comparison.

A bug here produces false positives on correct code, which is the worst
failure mode this product has, so the framework syntaxes are enumerated
explicitly rather than assumed.
"""

from __future__ import annotations

import pytest

from app.services.extractors.paths import (
    join_paths,
    normalize_path,
    paths_differ_by_one_edit,
)


class TestFrameworkParameterSyntax:
    @pytest.mark.parametrize(
        ("raw", "note"),
        [
            ("/users/{user_id}", "FastAPI"),
            ("/users/:id", "Express"),
            ("/users/:id?", "Express optional"),
            ("/users/<int:user_id>", "Flask typed"),
            ("/users/<user_id>", "Flask untyped"),
            ("/users/${id}", "JS template"),
            ("/users/%s", "printf"),
            ("/users/5", "hardcoded id"),
            ("/users/*", "wildcard"),
        ],
    )
    def test_all_syntaxes_normalise_identically(self, raw: str, note: str) -> None:
        """This equivalence is what lets a frontend call match a backend route."""
        assert normalize_path(raw).path == "/users/{}", note

    def test_parameter_names_are_discarded(self) -> None:
        """A frontend need not name a parameter the way the backend does."""
        assert normalize_path("/users/{id}").path == normalize_path("/users/{user_id}").path

    def test_several_parameters_are_counted(self) -> None:
        result = normalize_path("/users/{id}/posts/{post_id}/comments")

        assert result.path == "/users/{}/posts/{}/comments"
        assert result.param_count == 2
        assert result.is_dynamic

    def test_a_static_path_has_no_parameters(self) -> None:
        result = normalize_path("/api/users")

        assert result.param_count == 0
        assert not result.is_dynamic


class TestInlineParameters:
    def test_a_parameter_inside_a_segment_is_replaced_in_place(self) -> None:
        """The surrounding literal still participates in the comparison."""
        assert normalize_path("/files/report-${id}.pdf").path == "/files/report-{}.pdf"

    def test_fastapi_style_inline_parameter(self) -> None:
        assert normalize_path("/files/{name}.json").path == "/files/{}.json"


class TestNormalisation:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("/api/users/", "/api/users"),
            ("/api//users", "/api/users"),
            ("api/users", "/api/users"),
            ("/api/users?page=2", "/api/users"),
            ("/api/users#section", "/api/users"),
            ("  /api/users  ", "/api/users"),
        ],
    )
    def test_cleans_up_a_path(self, raw: str, expected: str) -> None:
        assert normalize_path(raw).path == expected

    def test_the_root_path_survives(self) -> None:
        assert normalize_path("/").path == "/"

    def test_an_empty_path_is_opaque(self) -> None:
        result = normalize_path("")

        assert result.is_opaque


class TestAbsoluteUrls:
    def test_splits_an_origin_from_the_path(self) -> None:
        result = normalize_path("https://api.example.com/v1/users")

        assert result.path == "/v1/users"
        assert result.base_url == "https://api.example.com"
        assert result.is_absolute_url

    def test_handles_a_protocol_relative_url(self) -> None:
        result = normalize_path("//api.example.com/v1/users")

        assert result.path == "/v1/users"
        assert result.base_url == "//api.example.com"

    def test_a_leading_double_slash_is_a_host_not_a_path(self) -> None:
        """Matches what a browser does, which is the behaviour that matters.

        ``fetch("//api/users")`` requests host ``api``, not path
        ``/api/users``. Reading it as a path would compare it against the
        wrong route.
        """
        result = normalize_path("//api/users")

        assert result.base_url == "//api"
        assert result.path == "/users"

    def test_an_origin_with_no_path_becomes_root(self) -> None:
        assert normalize_path("https://api.example.com").path == "/"

    def test_a_leading_interpolation_is_the_origin_not_a_segment(self) -> None:
        """`${API_BASE_URL}/api/users` is how real frontends are written.

        Treating the interpolation as a path segment would normalise this to
        `/{}/api/users` and mismatch every route on the server.
        """
        result = normalize_path("${API_BASE_URL}/api/users")

        assert result.path == "/api/users"
        assert result.base_url == "${API_BASE_URL}"
        assert result.param_count == 0

    def test_a_leading_interpolation_with_a_parameter_later(self) -> None:
        result = normalize_path("${BASE}/api/users/${id}")

        assert result.path == "/api/users/{}"
        assert result.param_count == 1

    def test_an_interpolation_that_is_the_whole_url_stays_opaque(self) -> None:
        """`${endpoint}` alone is an unknown URL, not a base plus a path."""
        result = normalize_path("${endpoint}")

        assert result.is_opaque


class TestPrefixes:
    def test_prepends_a_mount_prefix(self) -> None:
        assert normalize_path("/users", prefix="/api").path == "/api/users"

    def test_does_not_double_slashes(self) -> None:
        assert normalize_path("/users", prefix="/api/").path == "/api/users"

    def test_handles_a_nested_prefix(self) -> None:
        assert normalize_path("/users", prefix="/api/v1").path == "/api/v1/users"

    def test_an_empty_prefix_changes_nothing(self) -> None:
        assert normalize_path("/users", prefix="").path == "/users"

    def test_a_prefix_applies_to_a_parameterised_path(self) -> None:
        assert normalize_path("/users/{id}", prefix="/api").path == "/api/users/{}"


class TestJoinPaths:
    @pytest.mark.parametrize(
        ("parts", "expected"),
        [
            (("/api", "/users"), "/api/users"),
            (("api", "users"), "/api/users"),
            (("/api/", "/users/"), "/api/users"),
            (("", "/users"), "/users"),
            (("/api", ""), "/api"),
            ((), "/"),
            (("", ""), "/"),
        ],
    )
    def test_joins_without_doubling_or_dropping(
        self, parts: tuple[str, ...], expected: str
    ) -> None:
        assert join_paths(*parts) == expected


class TestOneEditDistance:
    """Separates "you have a typo" from "that endpoint does not exist"."""

    def test_the_seeded_typo_is_one_edit(self) -> None:
        assert paths_differ_by_one_edit("/api/user/{}", "/api/users/{}")

    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("/users", "/user"),
            ("/users", "/usres"),
            ("/api/tasks", "/api/task"),
            ("/profile", "/profiles"),
        ],
    )
    def test_detects_single_edits(self, left: str, right: str) -> None:
        assert paths_differ_by_one_edit(left, right)

    def test_identical_paths_are_not_an_edit_away(self) -> None:
        """They match exactly, which is a different outcome entirely."""
        assert not paths_differ_by_one_edit("/api/users", "/api/users")

    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("/api/users/export", "/api/users/{}"),
            ("/users", "/accounts"),
            ("/api/users", "/api/users/{}/posts"),
            ("/a", "/abc"),
        ],
    )
    def test_rejects_larger_differences(self, left: str, right: str) -> None:
        assert not paths_differ_by_one_edit(left, right)

    def test_is_symmetric(self) -> None:
        assert paths_differ_by_one_edit("/user", "/users")
        assert paths_differ_by_one_edit("/users", "/user")

    def test_handles_empty_strings(self) -> None:
        assert paths_differ_by_one_edit("", "/")
        assert not paths_differ_by_one_edit("", "/ab")
