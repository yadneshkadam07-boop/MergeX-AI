"""Extract HTTP call sites from frontend source.

Recognises the four clients that appear in practice:

* ``fetch(url, { method, headers, body })``
* ``axios.get(url, config)`` / ``axios({ url, method })`` / an instance made
  with ``axios.create({ baseURL })``
* ``ky.post(url, { json })``
* ``$.ajax`` style objects, via the ``axios({...})`` single-object form

What is recorded per call: the HTTP method, the path as written, the
normalised path, whether credentials are attached, the request body's field
names, and the exact location. What is *not* recorded: any judgement about
whether the call is correct. That comparison needs the backend routes and
happens in Phase 3.

The method matters as much as the path. ``api.post`` where the backend
declares ``DELETE`` is a real defect, and it is only visible if the method is
captured from the callee rather than assumed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from tree_sitter import Node

from app.core.logging import get_logger
from app.services.extractors.paths import NormalizedPath, normalize_path
from app.services.parsers.base import SourceFile, SourceLocation, iter_source_files
from app.services.parsers.js_ts_parser import (
    JS_TS_SUFFIXES,
    ParsedModule,
    node_text,
    parse_source,
    string_literal_value,
)

__all__ = [
    "FrontendApiCall",
    "HttpClient",
    "extract_frontend_api_calls",
    "extract_from_module",
]

log = get_logger("app.extractors.frontend_api_calls")

# Method-bearing client members: `axios.get`, `api.post`, `ky.delete`.
_METHOD_MEMBERS: Final[frozenset[str]] = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options"}
)

# Callees that take the method from the call itself rather than the member.
_BARE_CLIENTS: Final[frozenset[str]] = frozenset({"fetch", "axios", "ky", "request"})

# Identifier fragments that suggest a variable holds an HTTP client. Used only
# to decide whether `x.get(...)` is an HTTP call rather than `map.get(...)`.
_CLIENT_NAME_HINTS: Final[tuple[str, ...]] = (
    "api",
    "axios",
    "client",
    "http",
    "ky",
    "request",
    "instance",
    "service",
    "fetcher",
    "agent",
)

# Members that look like HTTP verbs but are not, on well-known types.
_NON_CLIENT_RECEIVERS: Final[frozenset[str]] = frozenset(
    {
        "map",
        "set",
        "cache",
        "headers",
        "params",
        "searchparams",
        "formdata",
        "storage",
        "localstorage",
        "sessionstorage",
        "store",
        "registry",
        "router",
        "history",
        "queryclient",
        "cookies",
    }
)

_AUTH_HEADER_NAMES: Final[frozenset[str]] = frozenset(
    {"authorization", "x-api-key", "apikey", "api-key", "x-auth-token", "cookie"}
)

_AUTH_VALUE_HINTS: Final[tuple[str, ...]] = ("bearer", "token", "jwt", "apikey", "api_key")

_IDENTIFIER_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_$][\w$]*$")


class HttpClient(str):
    """The client a call was made with. A plain string for easy comparison."""

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class FrontendApiCall:
    """One outbound HTTP call found in frontend source."""

    location: SourceLocation
    method: str | None
    """Upper-case verb, or None when it could not be determined statically."""
    raw_path: str
    normalized: NormalizedPath
    client: str
    callee: str
    """The callee as written, e.g. ``api.get`` -- useful in the report."""
    has_auth_header: bool = False
    request_fields: tuple[str, ...] = ()
    """Keys of a statically-known request body object, in source order."""
    enclosing_function: str | None = None
    confidence: float = 1.0
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def path(self) -> str:
        return self.normalized.path

    @property
    def is_comparable(self) -> bool:
        """False when there is nothing a route diff could usefully match."""
        return bool(self.normalized.path) and not self.normalized.is_opaque

    def __str__(self) -> str:
        return f"{self.method or '?'} {self.path} ({self.location})"


# One query covers every call shape; the callee is classified in Python, where
# the logic is testable and readable.
_CALL_QUERY: Final[
    str
] = """
(call_expression
  function: (_) @callee
  arguments: (arguments) @args) @call
"""


def extract_frontend_api_calls(
    root: Path,
    *,
    subdirectories: tuple[str, ...] = (),
) -> list[FrontendApiCall]:
    """Extract every HTTP call under ``root``.

    Args:
        root: The imported working tree.
        subdirectories: Restrict the scan to these, typically the
            ``frontend_roots`` reported by the stack detector. Empty means
            scan everything.

    Returns:
        Calls in file then line order, so output is deterministic.
    """
    calls: list[FrontendApiCall] = []
    search_roots = [root / sub for sub in subdirectories] if subdirectories else [root]

    for search_root in search_roots:
        if not search_root.is_dir():
            continue
        for source in iter_source_files(search_root, JS_TS_SUFFIXES):
            module = parse_source(_rebase(source, root, search_root))
            if module is None:
                continue
            calls.extend(extract_from_module(module))

    calls.sort(key=lambda call: (call.location.file_path, call.location.line_start))
    log.info("frontend_api_calls_extracted", count=len(calls))
    return calls


def _rebase(source: SourceFile, root: Path, search_root: Path) -> SourceFile:
    """Rewrite a path to be relative to the repository root, not the subdir.

    Findings must cite ``frontend/src/api/users.ts``, which is what a
    developer sees, not ``src/api/users.ts``.
    """
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


def extract_from_module(module: ParsedModule) -> list[FrontendApiCall]:
    """Extract calls from one parsed module."""
    source = module.source
    base_urls = _axios_base_urls(module)
    results: list[FrontendApiCall] = []

    for captures in module.query(_CALL_QUERY):
        call_node = captures["call"][0]
        callee_node = captures["callee"][0]
        args_node = captures["args"][0]

        callee = node_text(source, callee_node).strip()
        classified = _classify_callee(callee)
        if classified is None:
            continue
        client, method = classified

        arguments = [child for child in args_node.named_children if child.type != "comment"]
        extracted = _build_call(
            module=module,
            call_node=call_node,
            callee=callee,
            client=client,
            method=method,
            arguments=arguments,
            base_urls=base_urls,
        )
        if extracted is not None:
            results.append(extracted)

    return results


def _classify_callee(callee: str) -> tuple[str, str | None] | None:
    """Decide whether a callee is an HTTP client, and which method it implies.

    Returns ``(client, method)``, where ``method`` is None when the verb comes
    from the options object instead. Returns None when the callee is not an
    HTTP client, which is the common case and must stay cheap.
    """
    if not callee or "(" in callee:
        # A callee that is itself a call, e.g. `makeClient().get`. The receiver
        # cannot be identified by name, so it is skipped rather than guessed.
        return None

    lowered = callee.lower()

    if "." not in callee:
        if lowered in _BARE_CLIENTS:
            return (lowered, None)
        return None

    receiver, _, member = callee.rpartition(".")
    member_lower = member.lower()
    receiver_tail = receiver.rpartition(".")[2].lower()

    if member_lower not in _METHOD_MEMBERS:
        # `axios.request({...})`, `ky.extend(...)` are not path-bearing calls.
        return None
    if receiver_tail in _NON_CLIENT_RECEIVERS:
        return None
    if not _IDENTIFIER_RE.match(receiver_tail):
        return None

    if any(hint in receiver_tail for hint in _CLIENT_NAME_HINTS):
        return (receiver_tail, member_lower.upper())

    # An unrecognised receiver with an HTTP-verb member. Reported with reduced
    # confidence only if the first argument turns out to be a URL-ish string;
    # that check happens in _build_call.
    return (receiver_tail, member_lower.upper())


def _build_call(
    *,
    module: ParsedModule,
    call_node: Node,
    callee: str,
    client: str,
    method: str | None,
    arguments: list[Node],
    base_urls: dict[str, str],
) -> FrontendApiCall | None:
    source = module.source

    if not arguments:
        return None

    first = arguments[0]

    # `axios({ url, method })` -- everything is in one object.
    if method is None and first.type == "object":
        return _from_options_object(module, call_node, callee, client, first, base_urls)

    raw_path = string_literal_value(source, first)
    if raw_path is None:
        # The URL is a variable or an expression. Recorded as unresolved so
        # coverage of a file is honest, but never compared against routes.
        return _unresolved_call(module, call_node, callee, client, method, first)

    if not _looks_like_url(raw_path):
        return None

    resolved_method = (
        method
        or _method_from_options(module, arguments[1] if len(arguments) > 1 else None)
        or "GET"
    ).upper()
    body_node, config_node = _split_body_and_config(arguments, client, resolved_method)
    prefix = base_urls.get(client, "")

    return FrontendApiCall(
        location=module.location_of(call_node),
        method=resolved_method,
        raw_path=raw_path,
        normalized=normalize_path(raw_path, prefix=prefix),
        client=client,
        callee=callee,
        # Auth can be declared on the config object or, for fetch/ky, on the
        # same object that carries the body.
        has_auth_header=_has_auth(module, config_node) or _has_auth(module, body_node),
        request_fields=_request_fields(module, body_node, resolved_method),
        enclosing_function=_enclosing_function_name(module, call_node),
    )


# Verbs that carry a request body. A GET's second argument is configuration,
# never a payload, so reading field names from it invents a body that the
# request does not have.
_BODY_METHODS: Final[frozenset[str]] = frozenset({"POST", "PUT", "PATCH"})


def _split_body_and_config(
    arguments: list[Node], client: str, method: str
) -> tuple[Node | None, Node | None]:
    """Work out which argument is the body and which is the configuration.

    The clients disagree, and getting this wrong loses real findings:

    ``axios.get(url, config)``            2 args, no body
    ``axios.post(url, data, config)``     3 args -- the auth header is in the
                                          *third*, which is why a 2-argument
                                          assumption misses it
    ``fetch(url, { method, headers, body })``   one object does both jobs
    ``ky.post(url, { json, headers })``        likewise
    """
    rest = arguments[1:]
    if not rest:
        return (None, None)

    if client == "fetch" or client == "ky":
        # A single options object serves as both.
        return (rest[0], rest[0])

    # axios-style positional convention.
    if method in _BODY_METHODS:
        body = rest[0]
        config = rest[1] if len(rest) > 1 else None
        return (body, config)

    return (None, rest[0])


def _unresolved_call(
    module: ParsedModule,
    call_node: Node,
    callee: str,
    client: str,
    method: str | None,
    first: Node,
) -> FrontendApiCall | None:
    """Record a call whose URL is not statically known."""
    text = node_text(module.source, first)
    # Only worth recording if it plausibly is a URL argument at all.
    if first.type not in {
        "identifier",
        "member_expression",
        "binary_expression",
        "call_expression",
    }:
        return None
    return FrontendApiCall(
        location=module.location_of(call_node),
        method=(method or "GET").upper(),
        raw_path=text,
        normalized=normalize_path("", prefix=""),
        client=client,
        callee=callee,
        enclosing_function=_enclosing_function_name(module, call_node),
        confidence=0.3,
        notes=("url_not_statically_known",),
    )


def _from_options_object(
    module: ParsedModule,
    call_node: Node,
    callee: str,
    client: str,
    options: Node,
    base_urls: dict[str, str],
) -> FrontendApiCall | None:
    """Handle ``axios({ url: "/x", method: "post" })``."""
    pairs = _object_pairs(module, options)
    url_node = pairs.get("url")
    if url_node is None:
        return None
    raw_path = string_literal_value(module.source, url_node)
    if raw_path is None or not _looks_like_url(raw_path):
        return None

    method_node = pairs.get("method")
    method = string_literal_value(module.source, method_node) if method_node else None

    return FrontendApiCall(
        location=module.location_of(call_node),
        method=(method or "GET").upper(),
        raw_path=raw_path,
        normalized=normalize_path(raw_path, prefix=base_urls.get(client, "")),
        client=client,
        callee=callee,
        has_auth_header=_has_auth(module, options),
        request_fields=_request_fields(module, options, client),
        enclosing_function=_enclosing_function_name(module, call_node),
    )


def _looks_like_url(value: str) -> bool:
    """Reject strings that are clearly not request paths.

    A call like ``cache.get("user-settings")`` must not be read as a request
    to ``/user-settings``, so a path-like shape is required: a leading slash,
    a scheme, or a template interpolation.
    """
    text = value.strip()
    if not text:
        return False
    if text.startswith(("/", "http://", "https://", "//")):
        return True
    # `${base}/api/users` -- an interpolated prefix followed by a path.
    return "${" in text and "/" in text


def _object_pairs(module: ParsedModule, node: Node) -> dict[str, Node]:
    """Map the statically-known keys of an object literal to their values."""
    pairs: dict[str, Node] = {}
    if node.type != "object":
        return pairs
    for child in node.named_children:
        if child.type != "pair":
            continue
        key_node = child.child_by_field_name("key")
        value_node = child.child_by_field_name("value")
        if key_node is None or value_node is None:
            continue
        key = _property_key(module, key_node)
        if key is not None:
            pairs[key.lower()] = value_node
    return pairs


def _property_key(module: ParsedModule, node: Node) -> str | None:
    if node.type in {"property_identifier", "identifier"}:
        return node_text(module.source, node)
    if node.type == "string":
        return string_literal_value(module.source, node)
    return None


def _method_from_options(module: ParsedModule, options: Node | None) -> str | None:
    if options is None:
        return None
    method_node = _object_pairs(module, options).get("method")
    if method_node is None:
        return None
    value = string_literal_value(module.source, method_node)
    return value.upper() if value else None


def _has_auth(module: ParsedModule, options: Node | None) -> bool:
    """True when the call attaches credentials.

    Checks the headers object for a known auth header, and also
    ``withCredentials`` / ``credentials: "include"``, which send cookies.
    """
    if options is None:
        return False
    pairs = _object_pairs(module, options)

    if "withcredentials" in pairs or "credentials" in pairs:
        return True

    headers_node = pairs.get("headers")
    if headers_node is None:
        return False

    if headers_node.type != "object":
        # `headers: authHeaders()` -- a call that plausibly supplies auth.
        text = node_text(module.source, headers_node).lower()
        return any(hint in text for hint in ("auth", "token", "apikey", "api_key"))

    for key, value_node in _object_pairs(module, headers_node).items():
        if key in _AUTH_HEADER_NAMES:
            return True
        value = string_literal_value(module.source, value_node)
        if value and any(hint in value.lower() for hint in _AUTH_VALUE_HINTS):
            return True
    return False


# Keys that mark an object as request *configuration* rather than a payload.
_CONFIG_KEYS: Final[frozenset[str]] = frozenset(
    {
        "headers",
        "method",
        "params",
        "timeout",
        "signal",
        "responsetype",
        "withcredentials",
        "credentials",
        "mode",
        "cache",
        "redirect",
        "referrer",
        "integrity",
        "keepalive",
        "validatestatus",
        "onuploadprogress",
        "ondownloadprogress",
        "searchparams",
        "retry",
        "throwhttperrors",
        "prefixurl",
        "hooks",
    }
)


def _request_fields(module: ParsedModule, body: Node | None, method: str) -> tuple[str, ...]:
    """Field names of a statically-known request body.

    Returns empty for a verb that has no body, so a GET's configuration object
    cannot be mistaken for a payload -- ``api.get(url, { responseType: "blob" })``
    must not be reported as sending a ``responseType`` field.
    """
    if body is None or method not in _BODY_METHODS:
        return ()

    if body.type == "object":
        pairs = _object_pairs(module, body)
        # fetch and ky nest the payload under a known key.
        for key in ("json", "data", "body"):
            nested = pairs.get(key)
            if nested is not None:
                return _fields_of(module, nested)
        # axios passes the payload positionally, so the object is the body --
        # unless it is plainly a configuration object.
        if pairs.keys() & _CONFIG_KEYS:
            return ()
        return _fields_of(module, body)

    return _fields_of(module, body)


def _fields_of(module: ParsedModule, node: Node) -> tuple[str, ...]:
    """Keys of an object literal, unwrapping ``JSON.stringify(...)``."""
    target = node
    if node.type == "call_expression":
        callee_node = node.child_by_field_name("function")
        if callee_node is not None:
            callee = node_text(module.source, callee_node)
            if callee in {"JSON.stringify", "stringify"}:
                args = node.child_by_field_name("arguments")
                if args is not None and args.named_children:
                    target = args.named_children[0]

    if target.type != "object":
        return ()

    names: list[str] = []
    for child in target.named_children:
        if child.type == "pair":
            key_node = child.child_by_field_name("key")
            if key_node is not None:
                key = _property_key(module, key_node)
                if key is not None:
                    names.append(key)
        elif child.type == "shorthand_property_identifier":
            # `{ email, fullName }` -- the shorthand form.
            names.append(node_text(module.source, child))
    return tuple(names)


def _axios_base_urls(module: ParsedModule) -> dict[str, str]:
    """Map client variable -> its ``baseURL`` path, for instances created here.

    ``axios.create({ baseURL: "http://localhost:8000" })`` contributes no
    prefix, because the origin is not part of the route path. A relative
    ``baseURL: "/api"`` does, and missing it would make every call under that
    client look like a mismatch.
    """
    pattern = """
    (variable_declarator
      name: (identifier) @name
      value: (call_expression
        function: (member_expression) @factory
        arguments: (arguments (object) @config)))
    """
    base_urls: dict[str, str] = {}
    for captures in module.query(pattern):
        factory = node_text(module.source, captures["factory"][0])
        if not factory.endswith(".create"):
            continue
        name = node_text(module.source, captures["name"][0]).lower()
        config = _object_pairs(module, captures["config"][0])
        base_node = config.get("baseurl") or config.get("prefixurl")
        if base_node is None:
            continue
        value = string_literal_value(module.source, base_node)
        if value is None:
            continue
        _, _, path_part = value.partition("://")
        candidate = value if "://" not in value else f"/{path_part.partition('/')[2]}"
        candidate = candidate.rstrip("/")
        if candidate and candidate != "/" and not candidate.startswith("${"):
            base_urls[name] = candidate
    return base_urls


def _enclosing_function_name(module: ParsedModule, node: Node) -> str | None:
    """The name of the function a call sits in, for the report's benefit."""
    current: Node | None = node.parent
    while current is not None:
        if current.type in {"function_declaration", "generator_function_declaration"}:
            name_node = current.child_by_field_name("name")
            if name_node is not None:
                return node_text(module.source, name_node)
        if current.type in {"method_definition"}:
            name_node = current.child_by_field_name("name")
            if name_node is not None:
                return node_text(module.source, name_node)
        if current.type in {"arrow_function", "function_expression"}:
            # `const getUser = async () => {...}` -- the name is on the
            # declarator, one level up.
            parent = current.parent
            if parent is not None and parent.type == "variable_declarator":
                name_node = parent.child_by_field_name("name")
                if name_node is not None:
                    return node_text(module.source, name_node)
        current = current.parent
    return None
