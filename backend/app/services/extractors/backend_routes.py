"""Extract route definitions from backend source.

Supported, in descending depth:

===========  ===================================================================
FastAPI      decorators, ``APIRouter(prefix=...)``, nested ``include_router``
             chains resolved across files, dependencies from decorators *and*
             from parameter defaults
Flask        ``@app.route`` / ``@app.get``, blueprints and ``url_prefix``
Express      ``app.get`` / ``router.post``, ``app.use(prefix, router)``,
             middleware arguments
Django       ``path()`` / ``re_path()`` in a URLconf; the HTTP method is not
             declared there, so it is recorded as unknown
===========  ===================================================================

**Why prefix resolution is not optional.** In the ``react_fastapi_mismatch``
fixture the routes are declared as ``/users`` and mounted with
``include_router(users.router, prefix="/api")``. A frontend that calls
``/api/users`` is correct. An extractor that reports the route as ``/users``
would make every single call look like a missing endpoint -- hundreds of false
positives on a working application. So the mount graph is walked properly,
including through routers mounted on other routers.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Final

from tree_sitter import Node

from app.core.logging import get_logger
from app.services.extractors.paths import NormalizedPath, join_paths, normalize_path
from app.services.parsers.base import SourceFile, SourceLocation, iter_source_files
from app.services.parsers.js_ts_parser import (
    JS_TS_SUFFIXES,
    ParsedModule,
    node_text,
    parse_source as parse_js,
    string_literal_value,
)
from app.services.parsers.python_parser import (
    PYTHON_SUFFIXES,
    ParsedPythonModule,
    SyntaxErrorInfo,
    call_keyword,
    call_positional,
    decorator_calls,
    dotted_name,
    literal_value,
    parse_source as parse_python,
    string_items,
)

__all__ = [
    "BackendRoute",
    "RouteExtraction",
    "extract_backend_routes",
]

log = get_logger("app.extractors.backend_routes")

HTTP_METHODS: Final[frozenset[str]] = frozenset(
    {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"}
)

# Decorator members that declare a route and imply the verb.
_VERB_MEMBERS: Final[frozenset[str]] = frozenset(m.lower() for m in HTTP_METHODS)

# FastAPI / Flask dependency-injection markers.
_DEPENDENCY_MARKERS: Final[frozenset[str]] = frozenset({"Depends", "Security"})

# Middleware and dependency names that indicate authentication. Used to
# annotate, never to decide: Phase 3 compares a route against its siblings
# rather than trusting this list to be complete.
_AUTH_NAME_HINTS: Final[tuple[str, ...]] = (
    "auth",
    "login",
    "token",
    "jwt",
    "session",
    "permission",
    "current_user",
    "currentuser",
    "require",
    "protect",
    "verify",
    "bearer",
    "oauth",
    "apikey",
    "api_key",
    "admin",
    "scope",
    "guard",
)


@dataclass(frozen=True, slots=True)
class BackendRoute:
    """One route the server actually serves."""

    location: SourceLocation
    method: str | None
    """Upper-case verb, or None when the framework declares it elsewhere."""
    raw_path: str
    """The path as written on the decorator, without any mount prefix."""
    normalized: NormalizedPath
    """The full path a client must call, including every mount prefix."""
    framework: str
    handler_name: str
    mount_prefix: str = ""
    own_dependencies: tuple[str, ...] = ()
    """Dependencies declared on this route, from decorator or parameters."""
    inherited_dependencies: tuple[str, ...] = ()
    """Dependencies from the router or app this route is mounted under."""
    request_model: str | None = None
    response_model: str | None = None
    status_code: int | None = None
    router_variable: str | None = None
    confidence: float = 1.0
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def path(self) -> str:
        return self.normalized.path

    @property
    def all_dependencies(self) -> tuple[str, ...]:
        return (*self.own_dependencies, *self.inherited_dependencies)

    @property
    def is_authenticated(self) -> bool:
        """True when any dependency's name suggests authentication."""
        return any(_looks_like_auth(name) for name in self.all_dependencies)

    def __str__(self) -> str:
        return f"{self.method or 'ANY'} {self.path} ({self.location})"


@dataclass(slots=True)
class RouteExtraction:
    """Everything route extraction learned about a repository."""

    routes: list[BackendRoute] = field(default_factory=list)
    unparseable_files: list[SyntaxErrorInfo] = field(default_factory=list)
    unresolved_mounts: list[SourceLocation] = field(default_factory=list)
    """Mounts whose router could not be traced to a declaration.

    Routes under these have an incomplete prefix, so the rule engine must not
    report them as missing endpoints.
    """

    def by_method_and_path(self) -> dict[tuple[str | None, str], list[BackendRoute]]:
        grouped: dict[tuple[str | None, str], list[BackendRoute]] = defaultdict(list)
        for route in self.routes:
            grouped[(route.method, route.path)].append(route)
        return dict(grouped)


def _looks_like_auth(name: str) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in _AUTH_NAME_HINTS)


# ---------------------------------------------------------------------------
# Python: internal declaration records
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _RouterDecl:
    """``router = APIRouter(prefix="/x")`` or a Flask ``Blueprint``."""

    file: str
    variable: str
    prefix: str
    dependencies: tuple[str, ...]
    framework: str
    is_app: bool = False


@dataclass(slots=True)
class _Mount:
    """``include_router(child, prefix="/y")`` / ``register_blueprint(bp)``."""

    file: str
    target_variable: str
    source_ref: str
    prefix: str
    dependencies: tuple[str, ...]
    location: SourceLocation


@dataclass(slots=True)
class _RawRoute:
    """A decorated handler, before prefixes are resolved."""

    file: str
    router_variable: str
    method: str | None
    raw_path: str
    handler_name: str
    location: SourceLocation
    own_dependencies: tuple[str, ...]
    request_model: str | None
    response_model: str | None
    status_code: int | None
    framework: str


def extract_backend_routes(
    root: Path,
    *,
    subdirectories: tuple[str, ...] = (),
) -> RouteExtraction:
    """Extract every route under ``root``.

    Args:
        root: The imported working tree.
        subdirectories: Restrict the scan, typically the ``backend_roots``
            from the stack detector. Empty means scan everything.
    """
    extraction = RouteExtraction()
    search_roots = [root / sub for sub in subdirectories] if subdirectories else [root]

    python_modules: list[ParsedPythonModule] = []
    js_modules: list[ParsedModule] = []

    for search_root in search_roots:
        if not search_root.is_dir():
            continue
        for source in iter_source_files(search_root, PYTHON_SUFFIXES | JS_TS_SUFFIXES):
            rebased = _rebase(source, root, search_root)
            if rebased.suffix in PYTHON_SUFFIXES:
                parsed = parse_python(rebased)
                if isinstance(parsed, SyntaxErrorInfo):
                    extraction.unparseable_files.append(parsed)
                elif parsed is not None:
                    python_modules.append(parsed)
            else:
                js_module = parse_js(rebased)
                if js_module is not None:
                    js_modules.append(js_module)

    extraction.routes.extend(_extract_python(python_modules, extraction))
    extraction.routes.extend(_extract_django(python_modules))
    extraction.routes.extend(_extract_express(js_modules))

    extraction.routes.sort(key=lambda r: (r.location.file_path, r.location.line_start))
    log.info(
        "backend_routes_extracted",
        count=len(extraction.routes),
        unparseable=len(extraction.unparseable_files),
        unresolved_mounts=len(extraction.unresolved_mounts),
    )
    return extraction


def _rebase(source: SourceFile, root: Path, search_root: Path) -> SourceFile:
    """Make paths relative to the repository root, not the search subdirectory."""
    if search_root == root:
        return source
    try:
        prefix = search_root.relative_to(root).as_posix()
    except ValueError:  # pragma: no cover - defensive
        return source
    return SourceFile(
        relative_path=f"{prefix}/{source.relative_path}",
        text=source.text,
        lines=source.lines,
    )


# ---------------------------------------------------------------------------
# Python frameworks
# ---------------------------------------------------------------------------


def _extract_python(
    modules: list[ParsedPythonModule], extraction: RouteExtraction
) -> list[BackendRoute]:
    """Collect declarations, then resolve mount prefixes across files."""
    routers: dict[tuple[str, str], _RouterDecl] = {}
    mounts: list[_Mount] = []
    raw_routes: list[_RawRoute] = []
    module_index = _build_module_index(modules)

    for module in modules:
        _collect_python_declarations(module, routers, mounts, raw_routes)

    # Index mounts by the router they attach, so a route can walk upwards.
    mounts_by_child: dict[tuple[str, str], list[_Mount]] = defaultdict(list)
    for mount in mounts:
        resolved = _resolve_router_ref(mount, module_index, routers)
        if resolved is None:
            extraction.unresolved_mounts.append(mount.location)
            continue
        mounts_by_child[resolved].append(mount)

    routes: list[BackendRoute] = []
    for raw in raw_routes:
        key = (raw.file, raw.router_variable)
        declaration = routers.get(key)
        prefix, inherited, complete = _resolve_prefix_chain(
            key, routers, mounts_by_child, module_index
        )
        own_prefix = declaration.prefix if declaration else ""
        mount_prefix = join_paths(prefix, own_prefix) if (prefix or own_prefix) else ""
        if mount_prefix == "/":
            mount_prefix = ""

        notes: tuple[str, ...] = () if complete else ("mount_prefix_incomplete",)
        routes.append(
            BackendRoute(
                location=raw.location,
                method=raw.method,
                raw_path=raw.raw_path,
                normalized=normalize_path(raw.raw_path, prefix=mount_prefix),
                framework=raw.framework,
                handler_name=raw.handler_name,
                mount_prefix=mount_prefix,
                own_dependencies=raw.own_dependencies,
                inherited_dependencies=inherited,
                request_model=raw.request_model,
                response_model=raw.response_model,
                status_code=raw.status_code,
                router_variable=raw.router_variable,
                confidence=1.0 if complete else 0.6,
                notes=notes,
            )
        )
    return routes


def _build_module_index(modules: list[ParsedPythonModule]) -> dict[str, str]:
    """Map importable module names to file paths.

    ``backend/app/routers/users.py`` is registered under ``users``,
    ``routers.users``, ``app.routers.users`` and the full path, so an import
    written any of those ways resolves. A name that would be ambiguous between
    two files is dropped rather than guessed at.
    """
    candidates: dict[str, set[str]] = defaultdict(set)
    for module in modules:
        path = PurePosixPath(module.source.relative_path)
        parts = list(path.parts[:-1]) + [path.stem]
        if path.stem == "__init__":
            parts = list(path.parts[:-1])
        if not parts:
            continue
        for start in range(len(parts)):
            name = ".".join(parts[start:])
            if name:
                candidates[name].add(module.source.relative_path)

    return {name: next(iter(files)) for name, files in candidates.items() if len(files) == 1}


def _collect_python_declarations(
    module: ParsedPythonModule,
    routers: dict[tuple[str, str], _RouterDecl],
    mounts: list[_Mount],
    raw_routes: list[_RawRoute],
) -> None:
    file = module.source.relative_path
    imports = module.imported_names()

    # `app = FastAPI()` / `router = APIRouter(prefix=...)` / Flask equivalents.
    for node in ast.walk(module.tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        factory = dotted_name(node.value.func)
        if factory is None:
            continue
        base = factory.rpartition(".")[2]
        framework = _framework_for_factory(base, imports.get(base, ""))
        if framework is None:
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            prefix = _string_kwarg(node.value, "prefix") or _string_kwarg(node.value, "url_prefix")
            routers[(file, target.id)] = _RouterDecl(
                file=file,
                variable=target.id,
                prefix=(prefix or "").rstrip("/"),
                dependencies=_dependency_names_from_list(call_keyword(node.value, "dependencies")),
                framework=framework,
                is_app=base in {"FastAPI", "Flask", "Starlette"},
            )

    # `app.include_router(x, prefix=...)` / `app.register_blueprint(bp, ...)`
    for call in module.calls():
        callee = dotted_name(call.func)
        if callee is None or "." not in callee:
            continue
        target_variable, _, member = callee.rpartition(".")
        if member not in {"include_router", "register_blueprint"}:
            continue
        child = call_positional(call, 0)
        source_ref = dotted_name(child)
        if source_ref is None:
            continue
        mounts.append(
            _Mount(
                file=file,
                target_variable=target_variable,
                source_ref=source_ref,
                prefix=(
                    _string_kwarg(call, "prefix") or _string_kwarg(call, "url_prefix") or ""
                ).rstrip("/"),
                dependencies=_dependency_names_from_list(call_keyword(call, "dependencies")),
                location=module.location_of(call),
            )
        )

    # Decorated handlers.
    for function in module.functions():
        for name, decorator_call, decorator_node in decorator_calls(function):
            if decorator_call is None or "." not in name:
                continue
            router_variable, _, member = name.rpartition(".")
            raw_paths, methods, framework = _decorator_route_spec(member, decorator_call)
            if framework is None:
                continue
            location = module.location_of(decorator_node)
            dependencies = (
                *_dependency_names_from_list(call_keyword(decorator_call, "dependencies")),
                *_dependency_names_from_parameters(function),
            )
            for raw_path in raw_paths:
                for method in methods:
                    raw_routes.append(
                        _RawRoute(
                            file=file,
                            router_variable=router_variable,
                            method=method,
                            raw_path=raw_path,
                            handler_name=function.name,
                            location=location,
                            own_dependencies=tuple(dict.fromkeys(dependencies)),
                            request_model=_request_model(function),
                            response_model=_annotation_name(
                                call_keyword(decorator_call, "response_model")
                            ),
                            status_code=_int_kwarg(decorator_call, "status_code"),
                            framework=framework,
                        )
                    )


def _framework_for_factory(base: str, origin: str) -> str | None:
    """Identify the framework a router factory belongs to."""
    if base in {"FastAPI", "APIRouter"}:
        return "fastapi"
    if base in {"Flask", "Blueprint"}:
        return "flask"
    if base == "Starlette":
        return "starlette"
    if "fastapi" in origin:
        return "fastapi"
    if "flask" in origin:
        return "flask"
    return None


def _decorator_route_spec(
    member: str, call: ast.Call
) -> tuple[list[str], list[str | None], str | None]:
    """Read paths, methods and framework from a route decorator.

    ``@router.get("/x")``                -> (["/x"], ["GET"], fastapi)
    ``@app.route("/x", methods=["POST"])`` -> (["/x"], ["POST"], flask)
    ``@app.route("/x")``                 -> (["/x"], ["GET"], flask)
    """
    path_value = literal_value(call_positional(call, 0))
    if not isinstance(path_value, str):
        return ([], [], None)

    if member in _VERB_MEMBERS:
        return ([path_value], [member.upper()], "fastapi")

    if member in {"route", "add_url_rule"}:
        declared = [m.upper() for m in string_items(call_keyword(call, "methods"))]
        methods: list[str | None] = [m for m in declared if m in HTTP_METHODS] or ["GET"]
        return ([path_value], methods, "flask")

    if member in {"websocket"}:
        return ([path_value], [None], "fastapi")

    return ([], [], None)


def _resolve_router_ref(
    mount: _Mount,
    module_index: dict[str, str],
    routers: dict[tuple[str, str], _RouterDecl],
) -> tuple[str, str] | None:
    """Resolve the router a mount attaches to ``(file, variable)``.

    Handles the two ways it is written:

    ``include_router(users.router)``  -- module alias plus attribute
    ``include_router(router)``        -- a name imported into this file, or
                                        declared in it
    """
    ref = mount.source_ref

    if "." in ref:
        module_alias, _, variable = ref.rpartition(".")
        target_file = _resolve_module(module_alias, mount.file, module_index)
        if target_file is not None and (target_file, variable) in routers:
            return (target_file, variable)

    # A bare name declared in the same file.
    if (mount.file, ref) in routers:
        return (mount.file, ref)

    # A bare name imported from elsewhere: find the single declaration with
    # that variable name.
    matches = [key for key in routers if key[1] == ref]
    if len(matches) == 1:
        return matches[0]
    return None


def _resolve_module(alias: str, importing_file: str, module_index: dict[str, str]) -> str | None:
    """Resolve an imported module alias to a file path."""
    if alias in module_index:
        return module_index[alias]
    # `from . import users` inside app/routers/__init__.py-style packages:
    # try the alias relative to the importing file's package.
    package = PurePosixPath(importing_file).parent.as_posix()
    while package and package != ".":
        candidate = f"{package.replace('/', '.')}.{alias}"
        if candidate in module_index:
            return module_index[candidate]
        package = PurePosixPath(package).parent.as_posix()
        if package == PurePosixPath(package).parent.as_posix():
            break
    return None


def _resolve_prefix_chain(
    key: tuple[str, str],
    routers: dict[tuple[str, str], _RouterDecl],
    mounts_by_child: dict[tuple[str, str], list[_Mount]],
    module_index: dict[str, str],
) -> tuple[str, tuple[str, ...], bool]:
    """Walk upwards from a router to the application, accumulating prefixes.

    Returns ``(prefix, inherited_dependencies, is_complete)``. ``is_complete``
    is False when the chain could not be followed all the way to an app, in
    which case the computed prefix may be missing a segment and comparisons
    must not treat it as authoritative.
    """
    prefixes: list[str] = []
    inherited: list[str] = []
    visited: set[tuple[str, str]] = {key}
    current = key
    complete = True

    declaration = routers.get(current)
    if declaration is None:
        # A route on an undeclared variable -- most likely `app` created in a
        # module this scan did not reach.
        return ("", (), False)

    while True:
        if declaration is not None and declaration.is_app:
            break
        parent_mounts = mounts_by_child.get(current, [])
        if not parent_mounts:
            # Not mounted anywhere. For an APIRouter that means it is unreachable
            # as written, so the path cannot be trusted.
            complete = declaration is None or declaration.is_app
            break
        # If a router is mounted more than once the paths genuinely differ;
        # the first mount in file order is used and the ambiguity is flagged.
        mount = sorted(parent_mounts, key=lambda m: (m.file, m.location.line_start))[0]
        if len(parent_mounts) > 1:
            complete = False
        prefixes.append(mount.prefix)
        inherited.extend(mount.dependencies)

        parent_key = _resolve_parent_key(mount, routers, module_index)
        if parent_key is None or parent_key in visited:
            complete = complete and parent_key is not None
            break
        visited.add(parent_key)
        current = parent_key
        declaration = routers.get(current)
        if declaration is not None:
            prefixes.append(declaration.prefix)
            inherited.extend(declaration.dependencies)

    combined = join_paths(*reversed([p for p in prefixes if p]))
    return (combined if combined != "/" else "", tuple(dict.fromkeys(inherited)), complete)


def _resolve_parent_key(
    mount: _Mount,
    routers: dict[tuple[str, str], _RouterDecl],
    module_index: dict[str, str],
) -> tuple[str, str] | None:
    """The ``(file, variable)`` of the router a mount attaches *to*."""
    target = mount.target_variable
    if (mount.file, target) in routers:
        return (mount.file, target)
    if "." in target:
        module_alias, _, variable = target.rpartition(".")
        target_file = _resolve_module(module_alias, mount.file, module_index)
        if target_file is not None and (target_file, variable) in routers:
            return (target_file, variable)
    matches = [key for key in routers if key[1] == target]
    if len(matches) == 1:
        return matches[0]
    return None


def _string_kwarg(call: ast.Call, name: str) -> str | None:
    value = literal_value(call_keyword(call, name))
    return value if isinstance(value, str) else None


def _int_kwarg(call: ast.Call, name: str) -> int | None:
    value = literal_value(call_keyword(call, name))
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _dependency_names_from_list(node: ast.expr | None) -> tuple[str, ...]:
    """Names inside ``dependencies=[Depends(a), Security(b)]``."""
    if not isinstance(node, (ast.List, ast.Tuple)):
        return ()
    names: list[str] = []
    for element in node.elts:
        name = _dependency_target(element)
        if name is not None:
            names.append(name)
    return tuple(names)


def _dependency_target(node: ast.expr) -> str | None:
    """The callable inside ``Depends(x)``, or None if this is not a dependency."""
    if not isinstance(node, ast.Call):
        return None
    callee = dotted_name(node.func)
    if callee is None or callee.rpartition(".")[2] not in _DEPENDENCY_MARKERS:
        return None
    inner = call_positional(node, 0)
    if inner is None:
        # `Depends()` with no argument relies on the parameter's annotation.
        return "Depends"
    return dotted_name(inner) or "Depends"


def _dependency_names_from_parameters(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[str, ...]:
    """Dependencies declared as parameter defaults or in ``Annotated``.

    Both forms appear constantly and either one protects a route:

        def h(user = Depends(require_user)): ...
        def h(user: Annotated[User, Depends(require_user)]): ...
    """
    names: list[str] = []
    arguments = function.args

    defaults = list(arguments.defaults)
    positional = list(arguments.posonlyargs) + list(arguments.args)
    # Defaults align to the tail of the positional parameters.
    for argument, default in zip(
        positional[len(positional) - len(defaults) :], defaults, strict=True
    ):
        name = _dependency_target(default)
        if name is not None:
            names.append(name)
        annotated = _annotated_dependency(argument.annotation)
        if annotated is not None:
            names.append(annotated)

    # `kw_defaults` is sparse: it holds None for a keyword-only parameter with
    # no default, so it cannot share a name with the positional loop above.
    for argument, kw_default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True):
        if kw_default is not None:
            name = _dependency_target(kw_default)
            if name is not None:
                names.append(name)
        annotated = _annotated_dependency(argument.annotation)
        if annotated is not None:
            names.append(annotated)

    # Parameters with no default can still be annotated dependencies.
    for argument in positional[: len(positional) - len(defaults)]:
        annotated = _annotated_dependency(argument.annotation)
        if annotated is not None:
            names.append(annotated)

    return tuple(dict.fromkeys(names))


def _annotated_dependency(annotation: ast.expr | None) -> str | None:
    """Pull ``Depends(x)`` out of ``Annotated[T, Depends(x)]``."""
    if not isinstance(annotation, ast.Subscript):
        return None
    base = dotted_name(annotation.value)
    if base is None or base.rpartition(".")[2] != "Annotated":
        return None
    slice_node = annotation.slice
    elements = slice_node.elts if isinstance(slice_node, ast.Tuple) else [slice_node]
    for element in elements:
        name = _dependency_target(element)
        if name is not None:
            return name
    return None


def _request_model(function: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """The annotation of the body parameter, if one is identifiable.

    A body parameter is one annotated with a non-builtin type and not supplied
    by dependency injection. Needed for the request-field comparison, which
    checks the frontend's payload keys against the model's fields.
    """
    skip = {"int", "str", "float", "bool", "bytes", "dict", "list", "Request", "Response"}
    arguments = list(function.args.posonlyargs) + list(function.args.args)
    defaults = list(function.args.defaults)
    defaulted = set(range(len(arguments) - len(defaults), len(arguments)))

    for index, argument in enumerate(arguments):
        if argument.arg in {"self", "cls"} or argument.annotation is None:
            continue
        if index in defaulted:
            # Has a default: query parameter or dependency, not a body.
            continue
        name = _annotation_name(argument.annotation)
        if name is None or name in skip or _annotated_dependency(argument.annotation):
            continue
        return name
    return None


def _annotation_name(node: ast.expr | None) -> str | None:
    """Render a type annotation as a readable name."""
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Subscript):
        base = _annotation_name(node.value)
        inner = _annotation_name(
            node.slice.elts[0]
            if isinstance(node.slice, ast.Tuple) and node.slice.elts
            else node.slice
        )
        if base and inner:
            return f"{base}[{inner}]"
        return base
    return dotted_name(node)


# ---------------------------------------------------------------------------
# Django
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _DjangoEntry:
    """One element of a ``urlpatterns`` list."""

    file: str
    route: str
    location: SourceLocation
    view_name: str | None = None
    include_module: str | None = None
    """Set when this entry is ``include("other.urls")`` rather than a view."""
    include_variable: str | None = None
    """Set when it is ``include(other_patterns)`` -- a name, not a module."""


_DJANGO_REGEX_GROUP: Final[re.Pattern[str]] = re.compile(r"\(\?P<[^>]+>[^)]*\)|\([^)]*\)")


def _extract_django(modules: list[ParsedPythonModule]) -> list[BackendRoute]:
    """Extract routes from Django URLconfs.

    Django declares *paths* in ``urls.py`` and *methods* in the view, so the
    method is reported as None rather than guessed. A route with an unknown
    method still finds a missing endpoint, which is the more valuable check.

    ``include()`` chains are resolved so a path mounted under
    ``path("api/", include("users.urls"))`` reports as ``/api/...``.
    """
    entries_by_file: dict[str, list[_DjangoEntry]] = defaultdict(list)
    module_index = _build_module_index(modules)
    variable_files: dict[str, str] = {}

    for module in modules:
        for name, entries in _django_urlpatterns(module).items():
            if entries:
                entries_by_file[module.source.relative_path].extend(entries)
                variable_files.setdefault(name, module.source.relative_path)

    if not entries_by_file:
        return []

    # Prefix contributed to each file by whoever includes it.
    prefixes: dict[str, str] = dict.fromkeys(entries_by_file, "")
    for _ in range(len(entries_by_file) + 1):
        changed = False
        for file, entries in entries_by_file.items():
            for entry in entries:
                target = _django_include_target(entry, module_index, variable_files)
                if target is None or target not in prefixes:
                    continue
                candidate = join_paths(prefixes[file], entry.route)
                if candidate != "/" and prefixes[target] != candidate:
                    prefixes[target] = candidate
                    changed = True
        if not changed:
            break

    routes: list[BackendRoute] = []
    for file, entries in entries_by_file.items():
        for entry in entries:
            if entry.include_module or entry.include_variable:
                continue
            routes.append(
                BackendRoute(
                    location=entry.location,
                    method=None,
                    raw_path=entry.route,
                    normalized=normalize_path(
                        _django_route_to_path(entry.route), prefix=prefixes.get(file, "")
                    ),
                    framework="django",
                    handler_name=entry.view_name or "<view>",
                    mount_prefix=prefixes.get(file, ""),
                    notes=("method_declared_in_view",),
                )
            )
    return routes


def _django_urlpatterns(module: ParsedPythonModule) -> dict[str, list[_DjangoEntry]]:
    """Read every ``urlpatterns``-style list in a module."""
    found: dict[str, list[_DjangoEntry]] = {}

    for node in ast.walk(module.tree):
        if not isinstance(node, ast.Assign):
            continue
        names = [
            target.id
            for target in node.targets
            if isinstance(target, ast.Name) and "urlpattern" in target.id.lower()
        ]
        if not names or not isinstance(node.value, (ast.List, ast.Tuple)):
            continue

        entries: list[_DjangoEntry] = []
        for element in node.value.elts:
            entry = _django_entry(module, element)
            if entry is not None:
                entries.append(entry)
        for name in names:
            found[name] = entries
    return found


def _django_entry(module: ParsedPythonModule, element: ast.expr) -> _DjangoEntry | None:
    """Read one ``path(...)`` / ``re_path(...)`` element."""
    if not isinstance(element, ast.Call):
        return None
    callee = dotted_name(element.func)
    if callee is None or callee.rpartition(".")[2] not in {"path", "re_path", "url"}:
        return None

    route = literal_value(call_positional(element, 0))
    if not isinstance(route, str):
        return None

    second = call_positional(element, 1)
    entry = _DjangoEntry(
        file=module.source.relative_path,
        route=route,
        location=module.location_of(element),
    )

    if isinstance(second, ast.Call):
        inner = dotted_name(second.func)
        if inner is not None and inner.rpartition(".")[2] == "include":
            included = call_positional(second, 0)
            target = literal_value(included)
            if isinstance(target, str):
                entry.include_module = target
            else:
                entry.include_variable = dotted_name(included)
            return entry
        # `path("x/", MyView.as_view())`
        entry.view_name = inner
        return entry

    entry.view_name = dotted_name(second)
    return entry


def _django_include_target(
    entry: _DjangoEntry,
    module_index: dict[str, str],
    variable_files: dict[str, str],
) -> str | None:
    """The file an ``include()`` points at."""
    if entry.include_module:
        return _resolve_module(entry.include_module, entry.file, module_index)
    if entry.include_variable:
        name = entry.include_variable.rpartition(".")[2]
        return variable_files.get(name)
    return None


def _django_route_to_path(route: str) -> str:
    """Convert a Django route to a comparable path.

    ``users/<int:pk>/`` passes through to the normaliser, which already knows
    the ``<...>`` syntax. A ``re_path`` regex needs its anchors stripped and
    its groups turned into segments first.
    """
    text = route.strip()
    if text.startswith("^"):
        text = text[1:]
    if text.endswith("$"):
        text = text[:-1]
    text = _DJANGO_REGEX_GROUP.sub("{}", text)
    # Regex escapes that survive into a literal segment.
    return text.replace(r"\.", ".").replace(r"\-", "-").replace(r"\/", "/")


# ---------------------------------------------------------------------------
# Express
# ---------------------------------------------------------------------------

_EXPRESS_ROUTE_QUERY: Final[
    str
] = """
(call_expression
  function: (member_expression) @callee
  arguments: (arguments) @args) @call
"""


def _extract_express(modules: list[ParsedModule]) -> list[BackendRoute]:
    """Extract Express routes, resolving ``app.use(prefix, router)`` mounts."""
    routes: list[BackendRoute] = []

    for module in modules:
        prefixes = _express_mount_prefixes(module)
        for captures in module.query(_EXPRESS_ROUTE_QUERY):
            callee = node_text(module.source, captures["callee"][0])
            receiver, _, member = callee.rpartition(".")
            if member.lower() not in _VERB_MEMBERS:
                continue
            arguments = [
                child for child in captures["args"][0].named_children if child.type != "comment"
            ]
            if len(arguments) < 2:
                # `res.json(x)` and friends: a route needs a path and a handler.
                continue
            raw_path = string_literal_value(module.source, arguments[0])
            if raw_path is None or not raw_path.startswith("/"):
                continue

            middleware = tuple(
                name
                for name in (
                    _express_callable_name(module, argument) for argument in arguments[1:-1]
                )
                if name is not None
            )
            handler = _express_callable_name(module, arguments[-1]) or "<anonymous>"
            prefix = prefixes.get(receiver, "")

            routes.append(
                BackendRoute(
                    location=module.location_of(captures["call"][0]),
                    method=member.upper(),
                    raw_path=raw_path,
                    normalized=normalize_path(raw_path, prefix=prefix),
                    framework="express",
                    handler_name=handler,
                    mount_prefix=prefix,
                    own_dependencies=middleware,
                    router_variable=receiver,
                )
            )
    return routes


def _express_mount_prefixes(module: ParsedModule) -> dict[str, str]:
    """Map router variable -> mount prefix from ``app.use("/api", router)``."""
    pattern = """
    (call_expression
      function: (member_expression) @callee
      arguments: (arguments (string) @prefix (identifier) @router))
    """
    prefixes: dict[str, str] = {}
    for captures in module.query(pattern):
        callee = node_text(module.source, captures["callee"][0])
        if not callee.endswith(".use"):
            continue
        prefix = string_literal_value(module.source, captures["prefix"][0])
        router = node_text(module.source, captures["router"][0])
        if prefix and prefix.startswith("/"):
            prefixes[router] = prefix.rstrip("/")
    return prefixes


def _express_callable_name(module: ParsedModule, node: Node) -> str | None:
    """A readable name for a handler or middleware argument."""
    if node.type in {"identifier", "member_expression"}:
        return node_text(module.source, node)
    if node.type == "call_expression":
        function_node = node.child_by_field_name("function")
        if function_node is not None:
            return node_text(module.source, function_node)
    if node.type in {"arrow_function", "function_expression"}:
        return "<anonymous>"
    return None
