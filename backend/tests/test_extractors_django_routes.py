"""Django URLconf extraction.

Django splits the contract in two: ``urls.py`` declares the *path*, the view
declares the *method*. The method is therefore reported as None rather than
guessed. A route with an unknown method still answers "does this endpoint
exist", which is the question that catches the most defects.

Kept in its own module because the URLconf model -- a list of ``path()``
entries with ``include()`` chaining -- has nothing in common with the
decorator-based frameworks.
"""

from __future__ import annotations

from pathlib import Path

from app.services.extractors.backend_routes import BackendRoute, extract_backend_routes


def write(root: Path, files: dict[str, str]) -> Path:
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def routes_of(root: Path) -> list[BackendRoute]:
    return extract_backend_routes(root).routes


def route_map(root: Path) -> dict[str, str]:
    return {route.handler_name: route.path for route in routes_of(root)}


class TestPathEntries:
    def test_extracts_a_path(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "urls.py": (
                    "from django.urls import path\n"
                    "from . import views\n"
                    "urlpatterns = [\n"
                    "    path('users/', views.user_list),\n"
                    "]\n"
                )
            },
        )

        route = routes_of(tmp_path)[0]

        assert route.framework == "django"
        assert route.path == "/users"
        assert route.handler_name == "views.user_list"
        assert route.location.line_start == 4

    def test_the_method_is_unknown_not_guessed(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "urls.py": (
                    "from django.urls import path\n"
                    "urlpatterns = [path('users/', views.user_list)]\n"
                )
            },
        )

        route = routes_of(tmp_path)[0]

        assert route.method is None
        assert "method_declared_in_view" in route.notes

    def test_normalises_a_path_converter(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "urls.py": (
                    "from django.urls import path\n"
                    "urlpatterns = [path('users/<int:pk>/', views.detail)]\n"
                )
            },
        )

        assert routes_of(tmp_path)[0].path == "/users/{}"

    def test_normalises_an_untyped_converter(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "urls.py": (
                    "from django.urls import path\n"
                    "urlpatterns = [path('users/<pk>/', views.detail)]\n"
                )
            },
        )

        assert routes_of(tmp_path)[0].path == "/users/{}"

    def test_reads_a_class_based_view(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "urls.py": (
                    "from django.urls import path\n"
                    "urlpatterns = [path('profile/', ProfileView.as_view())]\n"
                )
            },
        )

        assert routes_of(tmp_path)[0].handler_name == "ProfileView.as_view"

    def test_extracts_several_entries(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "urls.py": (
                    "from django.urls import path\n"
                    "urlpatterns = [\n"
                    "    path('a/', views.a),\n"
                    "    path('b/', views.b),\n"
                    "]\n"
                )
            },
        )

        assert sorted(route_map(tmp_path)) == ["views.a", "views.b"]


class TestRePath:
    def test_strips_anchors_and_converts_a_named_group(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "urls.py": (
                    "from django.urls import re_path\n"
                    "urlpatterns = [re_path(r'^users/(?P<pk>[0-9]+)/$', views.detail)]\n"
                )
            },
        )

        assert routes_of(tmp_path)[0].path == "/users/{}"

    def test_converts_an_unnamed_group(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "urls.py": (
                    "from django.urls import re_path\n"
                    "urlpatterns = [re_path(r'^users/([0-9]+)/$', views.detail)]\n"
                )
            },
        )

        assert routes_of(tmp_path)[0].path == "/users/{}"

    def test_handles_a_static_regex_route(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "urls.py": (
                    "from django.urls import re_path\n"
                    "urlpatterns = [re_path(r'^health/$', views.health)]\n"
                )
            },
        )

        assert routes_of(tmp_path)[0].path == "/health"


class TestIncludeChaining:
    def test_resolves_an_include_prefix(self, tmp_path: Path) -> None:
        """Without this, every route under the include reports the wrong path."""
        write(
            tmp_path,
            {
                "project/urls.py": (
                    "from django.urls import include, path\n"
                    "urlpatterns = [path('api/', include('users.urls'))]\n"
                ),
                "users/urls.py": (
                    "from django.urls import path\n"
                    "urlpatterns = [path('users/', views.user_list)]\n"
                ),
            },
        )

        assert route_map(tmp_path)["views.user_list"] == "/api/users"

    def test_an_include_entry_is_not_itself_a_route(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "project/urls.py": (
                    "from django.urls import include, path\n"
                    "urlpatterns = [path('api/', include('users.urls'))]\n"
                ),
                "users/urls.py": (
                    "from django.urls import path\n"
                    "urlpatterns = [path('users/', views.user_list)]\n"
                ),
            },
        )

        assert len(routes_of(tmp_path)) == 1

    def test_resolves_a_two_level_include(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "project/urls.py": (
                    "from django.urls import include, path\n"
                    "urlpatterns = [path('api/', include('api.urls'))]\n"
                ),
                "api/urls.py": (
                    "from django.urls import include, path\n"
                    "urlpatterns = [path('v1/', include('users.urls'))]\n"
                ),
                "users/urls.py": (
                    "from django.urls import path\n"
                    "urlpatterns = [path('users/', views.user_list)]\n"
                ),
            },
        )

        assert route_map(tmp_path)["views.user_list"] == "/api/v1/users"

    def test_a_route_beside_an_include_keeps_the_outer_prefix(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "project/urls.py": (
                    "from django.urls import include, path\n"
                    "urlpatterns = [\n"
                    "    path('api/', include('users.urls')),\n"
                    "    path('health/', views.health),\n"
                    "]\n"
                ),
                "users/urls.py": (
                    "from django.urls import path\n"
                    "urlpatterns = [path('users/', views.user_list)]\n"
                ),
            },
        )

        mapping = route_map(tmp_path)

        assert mapping["views.health"] == "/health"
        assert mapping["views.user_list"] == "/api/users"


class TestRobustness:
    def test_ignores_a_list_that_is_not_urlpatterns(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "settings.py": (
                    "from django.urls import path\n" "MIDDLEWARE = [path('x/', views.x)]\n"
                )
            },
        )

        assert routes_of(tmp_path) == []

    def test_ignores_a_non_literal_route(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "urls.py": (
                    "from django.urls import path\n" "urlpatterns = [path(PREFIX, views.x)]\n"
                )
            },
        )

        assert routes_of(tmp_path) == []

    def test_ignores_non_path_entries(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "urls.py": (
                    "from django.urls import path\n"
                    "urlpatterns = [some_helper(), path('a/', views.a)]\n"
                )
            },
        )

        assert len(routes_of(tmp_path)) == 1

    def test_an_empty_urlpatterns_yields_nothing(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {"urls.py": "from django.urls import path\nurlpatterns = []\n"},
        )

        assert routes_of(tmp_path) == []

    def test_does_not_interfere_with_fastapi_extraction(self, tmp_path: Path) -> None:
        """Both frameworks in one tree must each be read correctly."""
        write(
            tmp_path,
            {
                "urls.py": (
                    "from django.urls import path\n"
                    "urlpatterns = [path('legacy/', views.legacy)]\n"
                ),
                "main.py": (
                    "from fastapi import FastAPI\n"
                    "app = FastAPI()\n"
                    '@app.get("/new")\n'
                    "def new():\n"
                    "    pass\n"
                ),
            },
        )

        frameworks = {route.framework for route in routes_of(tmp_path)}

        assert frameworks == {"django", "fastapi"}
