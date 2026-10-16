"""Frontend ↔ backend API contract rules (``MX-API-001`` … ``MX-API-005``).

**Precision is the design constraint.** A false positive on correct code
destroys trust in the whole tool far faster than a missed defect does, because
the user can verify a false positive in seconds and from then on disbelieves
everything else. So every rule here starts from a *reason to be silent*:

* Nothing is reported when the comparison itself is unsound -- no routes were
  found at all, a mount prefix could not be resolved, the call's URL is not
  statically known, or the request targets a third-party host.
* A call that matches a route exactly is not examined further.
* Where a weaker signal could explain the finding away (an auth interceptor,
  a Pydantic alias, a model that accepts extra fields), the finding is
  withheld rather than reported with a caveat.

The guards are tested as hard as the detections: ``must_not_report`` in every
fixture manifest is asserted, not hoped for.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Final

from app.analysis.findings import Finding, make_finding
from app.core.logging import get_logger
from app.services.extractors.backend_routes import BackendRoute, RouteExtraction
from app.services.extractors.frontend_api_calls import FrontendApiCall
from app.services.extractors.paths import paths_differ_by_one_edit
from app.services.extractors.request_models import RequestModel, to_snake_case

__all__ = ["ApiContractInput", "run_api_contract_rules"]

log = get_logger("app.analysis.api_contract")

# A call to one of these is talking to someone else's API, not to this
# project's backend, so no route should exist for it.
_THIRD_PARTY_HOST_HINTS: Final[tuple[str, ...]] = (
    "googleapis.com",
    "stripe.com",
    "amazonaws.com",
    "supabase.co",
    "sentry.io",
    "segment.io",
    "auth0.com",
    "clerk.",
    "github.com",
    "openai.com",
    "anthropic.com",
    "cloudflare.com",
    "algolia",
    "mapbox.com",
    "twilio.com",
    "sendgrid",
    "posthog.com",
    "mixpanel.com",
)


@dataclass(frozen=True, slots=True)
class ApiContractInput:
    """Everything the API rules compare."""

    calls: list[FrontendApiCall]
    routes: RouteExtraction
    request_models: dict[str, RequestModel]


def run_api_contract_rules(data: ApiContractInput) -> list[Finding]:
    """Run every API contract rule.

    Returns findings in no particular order; the caller deduplicates and
    sorts them.
    """
    routes = data.routes.routes

    if not routes:
        # Nothing to compare against. A frontend-only repository is not a
        # repository full of missing endpoints.
        log.info("api_contract_skipped", reason="no_backend_routes")
        return []

    if data.routes.unresolved_mounts:
        # At least one router could not be traced to its mount point, so some
        # route paths are incomplete. Absence of a matching route is no longer
        # evidence that the endpoint is missing.
        log.info(
            "api_contract_absence_checks_skipped",
            unresolved_mounts=len(data.routes.unresolved_mounts),
        )
        return _run_match_only_rules(data)

    findings: list[Finding] = []
    by_path = _routes_by_path(routes)

    for call in data.calls:
        if not _is_comparable(call):
            continue

        same_path = by_path.get(call.path, [])
        if same_path:
            findings.extend(_check_matched_call(call, same_path, data.request_models))
            continue

        findings.extend(_check_unmatched_call(call, routes))

    return findings


def _run_match_only_rules(data: ApiContractInput) -> list[Finding]:
    """Rules that only need a route that *was* found, not proof of absence."""
    findings: list[Finding] = []
    by_path = _routes_by_path(data.routes.routes)
    for call in data.calls:
        if not _is_comparable(call):
            continue
        same_path = by_path.get(call.path, [])
        if same_path:
            findings.extend(_check_matched_call(call, same_path, data.request_models))
    return findings


def _routes_by_path(routes: list[BackendRoute]) -> dict[str, list[BackendRoute]]:
    grouped: dict[str, list[BackendRoute]] = defaultdict(list)
    for route in routes:
        grouped[route.path].append(route)
    return dict(grouped)


def _is_comparable(call: FrontendApiCall) -> bool:
    """Whether a call can be compared against routes at all."""
    if not call.is_comparable:
        # The URL was a variable or an expression; its value is unknown.
        return False
    if call.method is None:
        return False
    base = call.normalized.base_url or ""
    if base.startswith("${"):
        # An interpolated origin, which is the normal way to point at *this*
        # backend. Comparable.
        return True

    # A request to someone else's API, which no route here should serve.
    is_third_party = bool(base) and any(hint in base.lower() for hint in _THIRD_PARTY_HOST_HINTS)
    # An explicit external origin that is not this project's own dev server.
    is_external = base.startswith(("http://", "https://", "//")) and not _is_local_origin(base)
    return not (is_third_party or is_external)


# Hosts that mean "this project's own backend" when they appear as an origin.
# These are recognised, never bound to, so the usual warning about binding to
# all interfaces does not apply.
_LOCAL_ORIGIN_MARKERS: Final[tuple[str, ...]] = (
    "localhost",
    "127.0.0.1",
    "0.0.0.0",  # noqa: S104 - matched against a URL, not used as a bind address
    "[::1]",
    "host.docker.internal",
)


def _is_local_origin(base_url: str) -> bool:
    lowered = base_url.lower()
    return any(marker in lowered for marker in _LOCAL_ORIGIN_MARKERS)


# ---------------------------------------------------------------------------
# A call whose path matches a route
# ---------------------------------------------------------------------------


def _check_matched_call(
    call: FrontendApiCall,
    same_path: list[BackendRoute],
    models: dict[str, RequestModel],
) -> list[Finding]:
    """Rules for a call whose path exists: method, body fields, credentials."""
    exact = [route for route in same_path if route.method == call.method]

    if not exact:
        method_finding = _method_mismatch(call, same_path)
        return [method_finding] if method_finding is not None else []

    findings: list[Finding] = []

    field_finding = _request_field_drift(call, exact[0], models)
    if field_finding is not None:
        findings.append(field_finding)

    auth_finding = _missing_credentials(call, exact)
    if auth_finding is not None:
        findings.append(auth_finding)

    return findings


def _method_mismatch(call: FrontendApiCall, same_path: list[BackendRoute]) -> Finding | None:
    """MX-API-003: the path exists but not for this method."""
    declared = [route.method for route in same_path if route.method is not None]
    if not declared:
        # Django and similar declare the method in the view, so a path with no
        # method is not evidence of a mismatch.
        return None

    route = same_path[0]
    return make_finding(
        "MX-API-003",
        identity=(call.method, call.path),
        locations=[call.location, route.location],
        description=(
            f"The frontend sends {call.method} to {call.path}, but the backend declares "
            f"that path for {', '.join(sorted(set(declared)))} only. The request will "
            f"fail with 405 Method Not Allowed."
        ),
        expected=f"{'/'.join(sorted(set(declared)))} {call.path}",
        actual=f"{call.method} {call.path}",
        metadata={
            "path": call.path,
            "call_method": call.method,
            "route_methods": sorted(set(declared)),
            "handler": route.handler_name,
        },
    )


def _request_field_drift(
    call: FrontendApiCall,
    route: BackendRoute,
    models: dict[str, RequestModel],
) -> Finding | None:
    """MX-API-004: a sent field the request model does not accept.

    Reported only in the high-confidence case: the field is **not** accepted
    under any name, but the *same field under a different casing* is. That is
    camelCase/snake_case drift, which is a real defect with an obvious fix.

    A field the model simply does not have could be many things -- an extra
    field the server ignores, a field added to the model later, a union of
    models -- so it is not reported.
    """
    if not call.request_fields or route.request_model is None:
        return None

    model = models.get(route.request_model)
    if model is None or not model.is_comparable:
        # The model was not found, or it accepts names that cannot be
        # enumerated (an alias generator, or extra="allow").
        return None

    accepted = model.accepted_names
    drifted: list[tuple[str, str]] = []
    for sent in call.request_fields:
        if sent in accepted:
            continue
        snake = to_snake_case(sent)
        if snake == sent:
            # Not a casing difference, so not this rule's business.
            continue
        if snake in accepted:
            drifted.append((sent, snake))

    if not drifted:
        return None

    sent_names = ", ".join(sent for sent, _ in drifted)
    expected_names = ", ".join(expected for _, expected in drifted)
    model_field = model.field_for(drifted[0][0])
    locations = [call.location]
    if model_field is not None:
        locations.append(model_field.location)

    return make_finding(
        "MX-API-004",
        identity=(call.method, call.path, sent_names),
        locations=locations,
        description=(
            f"The request body sends {sent_names}, but {route.request_model} declares "
            f"{expected_names}. Pydantic will reject the request as missing a required "
            f"field, or silently drop the value — the same field name in two casings is "
            f"the usual cause."
        ),
        expected=f"{{ {expected_names} }} per {route.request_model}",
        actual=f"{{ {sent_names} }}",
        metadata={
            "path": call.path,
            "method": call.method,
            "model": route.request_model,
            "drifted_fields": [{"sent": sent, "expected": expected} for sent, expected in drifted],
            "sent_fields": list(call.request_fields),
            "model_fields": sorted(accepted),
        },
    )


def _missing_credentials(call: FrontendApiCall, routes: list[BackendRoute]) -> Finding | None:
    """MX-API-005: the route requires auth and the call attaches none."""
    authenticated = [route for route in routes if route.is_authenticated]
    if not authenticated:
        return None
    if call.has_auth_header:
        return None
    if call.ambient_auth_possible:
        # The client may attach credentials through a default header or an
        # interceptor. Reporting here would be wrong on a correct client.
        return None

    route = authenticated[0]
    dependencies = ", ".join(route.all_dependencies) or "an authentication dependency"
    return make_finding(
        "MX-API-005",
        identity=(call.method, call.path),
        locations=[call.location, route.location],
        description=(
            f"{route.handler_name} is protected by {dependencies}, but this request "
            f"attaches no credentials and the client sets no default Authorization "
            f"header. The call will fail with 401."
        ),
        expected=f"An Authorization header, since the route depends on {dependencies}",
        actual="No credentials on the request or the client",
        metadata={
            "path": call.path,
            "method": call.method,
            "handler": route.handler_name,
            "dependencies": list(route.all_dependencies),
        },
    )


# ---------------------------------------------------------------------------
# A call whose path matches no route
# ---------------------------------------------------------------------------


def _check_unmatched_call(call: FrontendApiCall, routes: list[BackendRoute]) -> list[Finding]:
    """MX-API-002 if a near match exists, otherwise MX-API-001."""
    near = _near_matches(call, routes)
    if near:
        return [_path_typo(call, near)]
    return [_missing_endpoint(call, routes)]


def _near_matches(call: FrontendApiCall, routes: list[BackendRoute]) -> list[BackendRoute]:
    """Routes one character edit from the call's path.

    Restricted to routes with the same method, and to routes with the same
    number of path parameters: ``/users`` and ``/users/{}`` are one edit apart
    as strings but are different endpoints, and conflating them would turn a
    genuine missing-endpoint into a bogus typo suggestion.
    """
    return [
        route
        for route in routes
        if route.method == call.method
        and route.normalized.param_count == call.normalized.param_count
        and paths_differ_by_one_edit(call.path, route.path)
    ]


def _path_typo(call: FrontendApiCall, near: list[BackendRoute]) -> Finding:
    """MX-API-002: one character from a route that exists."""
    suggestion = min(near, key=lambda route: (route.location.file_path, route.path))
    return make_finding(
        "MX-API-002",
        identity=(call.method, call.path),
        locations=[call.location, suggestion.location],
        description=(
            f"No route serves {call.method} {call.path}, but "
            f"{suggestion.method} {suggestion.path} exists and differs by a single "
            f"character. The request returns 404; this is almost certainly a typo."
        ),
        expected=f"{suggestion.method} {suggestion.path}",
        actual=f"{call.method} {call.path} (raw: {call.raw_path})",
        metadata={
            "called_path": call.path,
            "suggested_path": suggestion.path,
            "method": call.method,
            "handler": suggestion.handler_name,
            "raw_path": call.raw_path,
            "caller": call.enclosing_function,
        },
    )


def _missing_endpoint(call: FrontendApiCall, routes: list[BackendRoute]) -> Finding:
    """MX-API-001: nothing serves this path."""
    same_prefix = sorted(
        {route.path for route in routes if _shares_first_segment(route.path, call.path)}
    )
    return make_finding(
        "MX-API-001",
        identity=(call.method, call.path),
        locations=[call.location],
        description=(
            f"The frontend calls {call.method} {call.path}, but no backend route "
            f"defines it. The request returns 404 at runtime; neither a type checker "
            f"nor a linter can see across the two layers."
        ),
        expected=f"A backend route matching {call.method} {call.path}",
        actual="No route is declared for that path",
        metadata={
            "path": call.path,
            "method": call.method,
            "raw_path": call.raw_path,
            "caller": call.enclosing_function,
            "nearby_routes": same_prefix[:10],
        },
    )


def _shares_first_segment(left: str, right: str) -> bool:
    """Whether two paths start with the same segment, for a helpful hint."""
    left_parts = [part for part in left.split("/") if part]
    right_parts = [part for part in right.split("/") if part]
    return bool(left_parts) and bool(right_parts) and left_parts[0] == right_parts[0]
