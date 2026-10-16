"""Backend route extraction, across frameworks.

The prefix-resolution tests matter most. A route declared ``/users`` and
mounted at ``/api`` is reachable only at ``/api/users``; reporting the
unmounted path would make every correct frontend call look like a missing
endpoint.
"""

from __future__ import annotations

from pathlib import Path

import pytest

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
    """Handler name -> full path, for compact assertions."""
    return {route.handler_name: route.path for route in routes_of(root)}


class TestFastApiBasics:
    def test_extracts_a_decorated_route(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "main.py": (
                    "from fastapi import FastAPI\n"
                    "app = FastAPI()\n"
                    '@app.get("/users")\n'
                    "def list_users():\n"
                    "    pass\n"
                )
            },
        )

        route = routes_of(tmp_path)[0]

        assert (route.method, route.path, route.handler_name) == (
            "GET",
            "/users",
            "list_users",
        )
        assert route.framework == "fastapi"
        assert route.location.line_start == 3

    @pytest.mark.parametrize("verb", ["get", "post", "put", "patch", "delete", "head", "options"])
    def test_extracts_every_verb(self, tmp_path: Path, verb: str) -> None:
        write(
            tmp_path,
            {
                "main.py": (
                    "from fastapi import FastAPI\n"
                    "app = FastAPI()\n"
                    f'@app.{verb}("/x")\n'
                    "def handler():\n"
                    "    pass\n"
                )
            },
        )

        assert routes_of(tmp_path)[0].method == verb.upper()

    def test_extracts_an_async_handler(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "main.py": (
                    "from fastapi import FastAPI\n"
                    "app = FastAPI()\n"
                    '@app.get("/x")\n'
                    "async def handler():\n"
                    "    pass\n"
                )
            },
        )

        assert routes_of(tmp_path)[0].handler_name == "handler"

    def test_normalises_a_path_parameter(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "main.py": (
                    "from fastapi import FastAPI\n"
                    "app = FastAPI()\n"
                    '@app.get("/users/{user_id}")\n'
                    "def handler(user_id: int):\n"
                    "    pass\n"
                )
            },
        )

        route = routes_of(tmp_path)[0]

        assert route.path == "/users/{}"
        assert route.raw_path == "/users/{user_id}"


class TestFastApiPrefixResolution:
    def test_applies_a_router_prefix(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "main.py": (
                    "from fastapi import FastAPI\n"
                    "from routers import users\n"
                    "app = FastAPI()\n"
                    "app.include_router(users.router)\n"
                ),
                "routers/users.py": (
                    "from fastapi import APIRouter\n"
                    'router = APIRouter(prefix="/users")\n'
                    '@router.get("/")\n'
                    "def list_users():\n"
                    "    pass\n"
                ),
            },
        )

        assert route_map(tmp_path)["list_users"] == "/users"

    def test_applies_an_include_router_prefix_across_files(self, tmp_path: Path) -> None:
        """The fixture's shape: routes say /users, main.py mounts them at /api."""
        write(
            tmp_path,
            {
                "main.py": (
                    "from fastapi import FastAPI\n"
                    "from routers import users\n"
                    "app = FastAPI()\n"
                    'app.include_router(users.router, prefix="/api")\n'
                ),
                "routers/users.py": (
                    "from fastapi import APIRouter\n"
                    "router = APIRouter()\n"
                    '@router.get("/users")\n'
                    "def list_users():\n"
                    "    pass\n"
                ),
            },
        )

        assert route_map(tmp_path)["list_users"] == "/api/users"

    def test_combines_a_router_prefix_and_a_mount_prefix(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "main.py": (
                    "from fastapi import FastAPI\n"
                    "from routers import users\n"
                    "app = FastAPI()\n"
                    'app.include_router(users.router, prefix="/api")\n'
                ),
                "routers/users.py": (
                    "from fastapi import APIRouter\n"
                    'router = APIRouter(prefix="/users")\n'
                    '@router.get("/{user_id}")\n'
                    "def get_user(user_id: int):\n"
                    "    pass\n"
                ),
            },
        )

        assert route_map(tmp_path)["get_user"] == "/api/users/{}"

    def test_resolves_a_nested_router_chain(self, tmp_path: Path) -> None:
        """A router mounted on a router mounted on the app."""
        write(
            tmp_path,
            {
                "main.py": (
                    "from fastapi import FastAPI\n"
                    "from api import api_router\n"
                    "app = FastAPI()\n"
                    'app.include_router(api_router, prefix="/api")\n'
                ),
                "api.py": (
                    "from fastapi import APIRouter\n"
                    "from routers import users\n"
                    'api_router = APIRouter(prefix="/v1")\n'
                    "api_router.include_router(users.router)\n"
                ),
                "routers/users.py": (
                    "from fastapi import APIRouter\n"
                    'router = APIRouter(prefix="/users")\n'
                    '@router.get("/")\n'
                    "def list_users():\n"
                    "    pass\n"
                ),
            },
        )

        assert route_map(tmp_path)["list_users"] == "/api/v1/users"

    def test_resolves_a_router_imported_by_name(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "main.py": (
                    "from fastapi import FastAPI\n"
                    "from routers.users import router\n"
                    "app = FastAPI()\n"
                    'app.include_router(router, prefix="/api")\n'
                ),
                "routers/users.py": (
                    "from fastapi import APIRouter\n"
                    "router = APIRouter()\n"
                    '@router.get("/users")\n'
                    "def list_users():\n"
                    "    pass\n"
                ),
            },
        )

        assert route_map(tmp_path)["list_users"] == "/api/users"

    def test_an_unmounted_router_is_flagged_as_incomplete(self, tmp_path: Path) -> None:
        """Its path is unknowable, so it must not be compared as authoritative."""
        write(
            tmp_path,
            {
                "routers/users.py": (
                    "from fastapi import APIRouter\n"
                    "router = APIRouter()\n"
                    '@router.get("/users")\n'
                    "def list_users():\n"
                    "    pass\n"
                )
            },
        )

        route = routes_of(tmp_path)[0]

        assert "mount_prefix_incomplete" in route.notes
        assert route.confidence < 1.0

    def test_a_mount_cycle_does_not_hang(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "a.py": (
                    "from fastapi import APIRouter\n"
                    "import b\n"
                    'router_a = APIRouter(prefix="/a")\n'
                    "router_a.include_router(b.router_b)\n"
                    '@router_a.get("/x")\n'
                    "def handler_a():\n"
                    "    pass\n"
                ),
                "b.py": (
                    "from fastapi import APIRouter\n"
                    "import a\n"
                    'router_b = APIRouter(prefix="/b")\n'
                    "router_b.include_router(a.router_a)\n"
                ),
            },
        )

        assert len(routes_of(tmp_path)) == 1


class TestFastApiDependencies:
    def test_reads_a_parameter_default_dependency(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "main.py": (
                    "from fastapi import Depends, FastAPI\n"
                    "app = FastAPI()\n"
                    '@app.get("/x")\n'
                    "def handler(user = Depends(require_user)):\n"
                    "    pass\n"
                )
            },
        )

        route = routes_of(tmp_path)[0]

        assert route.own_dependencies == ("require_user",)
        assert route.is_authenticated

    def test_reads_an_annotated_dependency(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "main.py": (
                    "from typing import Annotated\n"
                    "from fastapi import Depends, FastAPI\n"
                    "app = FastAPI()\n"
                    '@app.get("/x")\n'
                    "def handler(user: Annotated[User, Depends(require_user)]):\n"
                    "    pass\n"
                )
            },
        )

        assert routes_of(tmp_path)[0].own_dependencies == ("require_user",)

    def test_reads_a_decorator_dependency(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "main.py": (
                    "from fastapi import Depends, FastAPI\n"
                    "app = FastAPI()\n"
                    '@app.get("/x", dependencies=[Depends(require_admin)])\n'
                    "def handler():\n"
                    "    pass\n"
                )
            },
        )

        assert routes_of(tmp_path)[0].own_dependencies == ("require_admin",)

    def test_reads_a_security_dependency(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "main.py": (
                    "from fastapi import FastAPI, Security\n"
                    "app = FastAPI()\n"
                    '@app.get("/x")\n'
                    "def handler(scopes = Security(oauth2_scheme)):\n"
                    "    pass\n"
                )
            },
        )

        assert routes_of(tmp_path)[0].is_authenticated

    def test_inherits_a_router_level_dependency(self, tmp_path: Path) -> None:
        """A route protected only by its router is still protected."""
        write(
            tmp_path,
            {
                "main.py": (
                    "from fastapi import Depends, FastAPI\n"
                    "from routers import admin\n"
                    "app = FastAPI()\n"
                    "app.include_router(\n"
                    '    admin.router, prefix="/admin",\n'
                    "    dependencies=[Depends(require_admin)],\n"
                    ")\n"
                ),
                "routers/admin.py": (
                    "from fastapi import APIRouter\n"
                    "router = APIRouter()\n"
                    '@router.get("/stats")\n'
                    "def stats():\n"
                    "    pass\n"
                ),
            },
        )

        route = routes_of(tmp_path)[0]

        assert route.own_dependencies == ()
        assert route.inherited_dependencies == ("require_admin",)
        assert route.is_authenticated

    def test_an_unprotected_route_reports_no_dependencies(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "main.py": (
                    "from fastapi import FastAPI\n"
                    "app = FastAPI()\n"
                    '@app.get("/x")\n'
                    "def handler(limit: int = 10):\n"
                    "    pass\n"
                )
            },
        )

        route = routes_of(tmp_path)[0]

        assert route.all_dependencies == ()
        assert not route.is_authenticated


class TestFastApiModels:
    def test_reads_the_request_model(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "main.py": (
                    "from fastapi import FastAPI\n"
                    "app = FastAPI()\n"
                    '@app.post("/users")\n'
                    "def create(payload: UserCreate):\n"
                    "    pass\n"
                )
            },
        )

        assert routes_of(tmp_path)[0].request_model == "UserCreate"

    def test_ignores_builtin_annotations_as_models(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "main.py": (
                    "from fastapi import FastAPI\n"
                    "app = FastAPI()\n"
                    '@app.get("/users/{user_id}")\n'
                    "def get_user(user_id: int):\n"
                    "    pass\n"
                )
            },
        )

        assert routes_of(tmp_path)[0].request_model is None

    def test_reads_the_response_model_and_status(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "main.py": (
                    "from fastapi import FastAPI\n"
                    "app = FastAPI()\n"
                    '@app.post("/users", response_model=UserOut, status_code=201)\n'
                    "def create(payload: UserCreate):\n"
                    "    pass\n"
                )
            },
        )

        route = routes_of(tmp_path)[0]

        assert route.response_model == "UserOut"
        assert route.status_code == 201


class TestFlask:
    def test_extracts_a_route_with_default_method(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "app.py": (
                    "from flask import Flask\n"
                    "app = Flask(__name__)\n"
                    '@app.route("/users")\n'
                    "def list_users():\n"
                    "    pass\n"
                )
            },
        )

        route = routes_of(tmp_path)[0]

        assert (route.method, route.path, route.framework) == ("GET", "/users", "flask")

    def test_expands_declared_methods(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "app.py": (
                    "from flask import Flask\n"
                    "app = Flask(__name__)\n"
                    '@app.route("/users", methods=["GET", "POST"])\n'
                    "def users():\n"
                    "    pass\n"
                )
            },
        )

        assert sorted(route.method or "" for route in routes_of(tmp_path)) == ["GET", "POST"]

    def test_normalises_a_flask_converter(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "app.py": (
                    "from flask import Flask\n"
                    "app = Flask(__name__)\n"
                    '@app.route("/users/<int:user_id>")\n'
                    "def get_user(user_id):\n"
                    "    pass\n"
                )
            },
        )

        assert routes_of(tmp_path)[0].path == "/users/{}"

    def test_applies_a_blueprint_url_prefix(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "app.py": (
                    "from flask import Flask\n"
                    "from views import bp\n"
                    "app = Flask(__name__)\n"
                    "app.register_blueprint(bp)\n"
                ),
                "views.py": (
                    "from flask import Blueprint\n"
                    'bp = Blueprint("api", __name__, url_prefix="/api")\n'
                    '@bp.route("/users")\n'
                    "def list_users():\n"
                    "    pass\n"
                ),
            },
        )

        assert route_map(tmp_path)["list_users"] == "/api/users"

    def test_applies_a_register_blueprint_prefix(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "app.py": (
                    "from flask import Flask\n"
                    "from views import bp\n"
                    "app = Flask(__name__)\n"
                    'app.register_blueprint(bp, url_prefix="/v2")\n'
                ),
                "views.py": (
                    "from flask import Blueprint\n"
                    'bp = Blueprint("api", __name__)\n'
                    '@bp.route("/users")\n'
                    "def list_users():\n"
                    "    pass\n"
                ),
            },
        )

        assert route_map(tmp_path)["list_users"] == "/v2/users"


class TestExpress:
    def test_extracts_an_app_route(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {"server.js": 'app.get("/users", listUsers);\n'},
        )

        route = routes_of(tmp_path)[0]

        assert (route.method, route.path, route.framework) == ("GET", "/users", "express")
        assert route.handler_name == "listUsers"

    def test_normalises_an_express_parameter(self, tmp_path: Path) -> None:
        write(tmp_path, {"server.js": 'app.get("/users/:id", getUser);\n'})

        assert routes_of(tmp_path)[0].path == "/users/{}"

    def test_applies_an_app_use_prefix(self, tmp_path: Path) -> None:
        source = (
            "const router = express.Router();\n"
            'router.get("/users", listUsers);\n'
            'app.use("/api", router);\n'
        )
        write(tmp_path, {"server.js": source})

        assert route_map(tmp_path)["listUsers"] == "/api/users"

    def test_records_middleware_as_dependencies(self, tmp_path: Path) -> None:
        write(tmp_path, {"server.js": 'app.post("/users", requireAuth, createUser);\n'})

        route = routes_of(tmp_path)[0]

        assert route.own_dependencies == ("requireAuth",)
        assert route.is_authenticated

    def test_ignores_a_response_method(self, tmp_path: Path) -> None:
        """`res.json(x)` has one argument and is not a route."""
        write(tmp_path, {"server.js": "res.json({ ok: true });\n"})

        assert routes_of(tmp_path) == []

    def test_ignores_a_non_path_first_argument(self, tmp_path: Path) -> None:
        write(tmp_path, {"server.js": 'emitter.on("data", handler);\n'})

        assert routes_of(tmp_path) == []


class TestRobustness:
    def test_an_unparseable_file_is_reported_not_raised(self, tmp_path: Path) -> None:
        write(tmp_path, {"broken.py": "def f(:\n    pass\n"})

        extraction = extract_backend_routes(tmp_path)

        assert len(extraction.unparseable_files) == 1
        assert extraction.unparseable_files[0].location.file_path == "broken.py"

    def test_one_broken_file_does_not_stop_the_others(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "broken.py": "def f(:\n",
                "main.py": (
                    "from fastapi import FastAPI\n"
                    "app = FastAPI()\n"
                    '@app.get("/x")\n'
                    "def handler():\n"
                    "    pass\n"
                ),
            },
        )

        extraction = extract_backend_routes(tmp_path)

        assert len(extraction.routes) == 1
        assert len(extraction.unparseable_files) == 1

    def test_a_dynamic_route_path_is_skipped(self, tmp_path: Path) -> None:
        """`@app.get(PATH)` has no statically knowable path."""
        write(
            tmp_path,
            {
                "main.py": (
                    "from fastapi import FastAPI\n"
                    "app = FastAPI()\n"
                    "@app.get(USERS_PATH)\n"
                    "def handler():\n"
                    "    pass\n"
                )
            },
        )

        assert routes_of(tmp_path) == []

    def test_results_are_sorted_by_file_then_line(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "b.py": (
                    "from fastapi import FastAPI\n"
                    "app = FastAPI()\n"
                    '@app.get("/b")\n'
                    "def b():\n"
                    "    pass\n"
                ),
                "a.py": (
                    "from fastapi import FastAPI\n"
                    "app2 = FastAPI()\n"
                    '@app2.get("/a1")\n'
                    "def a1():\n"
                    "    pass\n"
                    '@app2.get("/a2")\n'
                    "def a2():\n"
                    "    pass\n"
                ),
            },
        )

        found = routes_of(tmp_path)

        assert [route.handler_name for route in found] == ["a1", "a2", "b"]

    def test_an_empty_tree_yields_nothing(self, tmp_path: Path) -> None:
        extraction = extract_backend_routes(tmp_path)

        assert extraction.routes == []
        assert extraction.unparseable_files == []
