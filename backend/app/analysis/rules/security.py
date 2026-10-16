"""Security rules (``MX-SEC-001`` … ``MX-SEC-005``).

Secret detection is where a scanner earns or loses its credibility. Entropy
alone flags UUIDs, hashes, minified code, base64 images and test fixtures, and
a tool that cries wolf on those gets muted. Two signals are therefore required
before anything is reported:

1. a **provider-specific prefix** (``sk_live_``, ``AKIA``, ``eyJ``, …), which
   is nearly conclusive on its own; or
2. a **credential-shaped name** (``*_PASSWORD``, ``*_SECRET``, ``*_TOKEN``)
   assigned a literal that is long enough and random enough to be real.

Everything that looks like a secret but is not gets an explicit exclusion:
placeholders, environment lookups without a literal default, plain URLs,
repeated characters, and version strings.

``MX-SEC-002`` is reported only on an *inconsistency* -- a sensitive route
whose siblings are protected -- never on "this route has no auth", which would
flag every public endpoint in every project.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from app.analysis.findings import Finding, make_finding
from app.core.logging import get_logger
from app.core.security import mask_secret
from app.models.enums import Severity
from app.services.extractors.backend_routes import BackendRoute, RouteExtraction
from app.services.parsers.base import SourceFile, iter_source_files
from app.services.parsers.js_ts_parser import JS_TS_SUFFIXES
from app.services.parsers.python_parser import (
    PYTHON_SUFFIXES,
    ParsedPythonModule,
    call_keyword,
    dotted_name,
    literal_value,
    parse_source as parse_python,
    string_items,
)

__all__ = ["SecurityInput", "run_security_rules"]

log = get_logger("app.analysis.security")

# ---------------------------------------------------------------------------
# Secret detection
# ---------------------------------------------------------------------------

# Provider-issued credential formats. A match is near-conclusive: these
# prefixes are reserved and do not occur by accident.

_PROVIDER_RULES: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("Stripe live secret key", re.compile(r"\bsk_live_[A-Za-z0-9]{16,}")),
    ("Stripe test secret key", re.compile(r"\bsk_test_[A-Za-z0-9]{16,}")),
    ("Stripe restricted key", re.compile(r"\brk_live_[A-Za-z0-9]{16,}")),
    ("AWS access key ID", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("GitHub personal access token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("SendGrid API key", re.compile(r"\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}")),
    ("OpenAI API key", re.compile(r"\bsk-[A-Za-z0-9]{32,}")),
    ("Twilio account SID", re.compile(r"\bAC[0-9a-f]{32}\b")),
    ("npm access token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("Mailgun API key", re.compile(r"\bkey-[0-9a-f]{32}\b")),
    (
        "JSON Web Token",
        re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{4,}"),
    ),
    ("Private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)

# Identifier shapes that mean "the value is a credential".
_CREDENTIAL_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:^|_)(?:"
    r"secret|password|passwd|pwd|token|apikey|api_key|privatekey|private_key"
    r"|access_key|accesskey|secret_key|secretkey|credential|auth_token"
    r"|client_secret|signing_key|encryption_key|session_key|master_key"
    r")(?:$|_)",
    re.IGNORECASE,
)

# Values that look like credentials but are deliberately not.
_PLACEHOLDER_VALUES: Final[frozenset[str]] = frozenset(
    {
        "",
        "changeme",
        "change_me",
        "change-me",
        "password",
        "passwd",
        "secret",
        "mysecret",
        "topsecret",
        "token",
        "apikey",
        "api_key",
        "key",
        "value",
        "none",
        "null",
        "nil",
        "undefined",
        "empty",
        "todo",
        "fixme",
        "tbd",
        "placeholder",
        "example",
        "sample",
        "dummy",
        "fake",
        "test",
        "testing",
        "foo",
        "bar",
        "baz",
        "qux",
        "abc123",
        "123456",
        "password123",
        "redacted",
        "hidden",
        "masked",
        "removed",
        "unset",
        "notset",
        "your_api_key",
        "your-api-key",
        "yourkeyhere",
        "insert_key_here",
    }
)

_PLACEHOLDER_PREFIXES: Final[tuple[str, ...]] = (
    "your-",
    "your_",
    "yours",
    "<",
    "{{",
    "${",
    "$(",
    "xxx",
    "aaa",
    "...",
    "insert",
    "replace",
    "enter-",
    "enter_",
    "my-",
    "my_",
    "dummy",
    "example",
    "sample-",
    "sample_",
    "test-",
    "test_",
    "fake-",
    "fake_",
    "placeholder",
)

_URL_RE: Final[re.Pattern[str]] = re.compile(r"^(?:https?|ws|wss|ftp)://", re.IGNORECASE)
_VERSION_RE: Final[re.Pattern[str]] = re.compile(r"^[\d]+\.[\d.]+[\w.\-+]*$")
_REPEATED_RE: Final[re.Pattern[str]] = re.compile(r"^(.)\1*$")
# A path, a mime type, a header name: punctuation-heavy, not credential-shaped.
_NOT_A_SECRET_RE: Final[re.Pattern[str]] = re.compile(r"^[/.\\]|\s{2,}|^[a-z]+/[a-z]+$")

# Below this the string is too short to be a real credential; above the
# entropy floor it is random enough to be one.
_MIN_SECRET_LENGTH: Final[int] = 12
_MIN_ENTROPY_BITS: Final[float] = 2.6

# Suffixes worth scanning for secrets. Lockfiles, minified bundles and binary
# assets are excluded by the shared ignore policy.
_SCANNED_SUFFIXES: Final[frozenset[str]] = (
    PYTHON_SUFFIXES
    | JS_TS_SUFFIXES
    | frozenset({".yml", ".yaml", ".toml", ".ini", ".cfg", ".json", ".tf", ".sh"})
)

# Files whose entire purpose is to hold credentials. Reported once as
# MX-SEC-004 rather than once per line as MX-SEC-001.
_ENV_FILE_RE: Final[re.Pattern[str]] = re.compile(r"(?:^|/)\.env(?:\.[\w.-]+)?$")
_ENV_TEMPLATE_RE: Final[re.Pattern[str]] = re.compile(
    r"\.(?:example|sample|template|dist|tpl)$|(?:^|/)\.env\.(?:example|sample|template)$"
)


@dataclass(frozen=True, slots=True)
class SecurityInput:
    """Everything the security rules need."""

    root: Path
    routes: RouteExtraction
    subdirectories: tuple[str, ...] = ()


def run_security_rules(data: SecurityInput) -> list[Finding]:
    """Run every security rule."""
    findings: list[Finding] = []
    search_roots = (
        [data.root / sub for sub in data.subdirectories] if data.subdirectories else [data.root]
    )

    env_files: list[SourceFile] = []
    python_modules: list[ParsedPythonModule] = []

    for search_root in search_roots:
        if not search_root.is_dir():
            continue
        for source in _iter_scannable(search_root, data.root):
            if _ENV_FILE_RE.search(source.relative_path):
                if not _ENV_TEMPLATE_RE.search(source.relative_path):
                    env_files.append(source)
                continue

            findings.extend(_scan_for_secrets(source))

            if source.suffix in PYTHON_SUFFIXES:
                parsed = parse_python(source)
                if isinstance(parsed, ParsedPythonModule):
                    python_modules.append(parsed)

    findings.extend(_committed_env_files(env_files))
    findings.extend(_cors_findings(python_modules))
    findings.extend(_debug_findings(python_modules))
    findings.extend(_unprotected_route_findings(data.routes))

    return findings


def _iter_scannable(search_root: Path, root: Path) -> list[SourceFile]:
    """Source files worth scanning, with repo-relative paths.

    ``.env`` files are collected explicitly: they have no suffix, so the
    suffix-driven walk will not yield them.
    """
    sources = [
        _rebase(source, root, search_root)
        for source in iter_source_files(search_root, _SCANNED_SUFFIXES)
    ]

    for candidate in sorted(search_root.rglob(".env*")):
        if not candidate.is_file() or candidate.is_symlink():
            continue
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            relative = candidate.relative_to(root).as_posix()
        except ValueError:  # pragma: no cover - defensive
            relative = candidate.name
        sources.append(
            SourceFile(relative_path=relative, text=text, lines=tuple(text.splitlines()))
        )

    return sources


def _rebase(source: SourceFile, root: Path, search_root: Path) -> SourceFile:
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


def shannon_entropy(value: str) -> float:
    """Bits of entropy per character.

    Random tokens land near 4-6; English words and identifiers near 2-3.5.
    Used as a floor, never as the only signal.
    """
    if not value:
        return 0.0
    counts = Counter(value)
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def is_placeholder(value: str) -> bool:
    """True when a credential-shaped value is deliberately not a credential."""
    lowered = value.strip().lower()
    if lowered in _PLACEHOLDER_VALUES:
        return True
    if lowered.startswith(_PLACEHOLDER_PREFIXES):
        return True
    if _REPEATED_RE.match(lowered):
        return True
    if _VERSION_RE.match(lowered):
        return True
    return "example.com" in lowered or "localhost" in lowered


def looks_like_secret_value(value: str) -> bool:
    """Whether a literal is plausibly a real credential."""
    candidate = value.strip()
    if len(candidate) < _MIN_SECRET_LENGTH:
        return False
    if is_placeholder(candidate):
        return False
    if _URL_RE.match(candidate):
        # A URL is not a secret. Credentials *inside* one are caught by the
        # .env scan, where the host is also known.
        return False
    if _NOT_A_SECRET_RE.search(candidate):
        return False
    if " " in candidate and len(candidate.split()) > 3:
        # A sentence, not a token.
        return False
    return shannon_entropy(candidate) >= _MIN_ENTROPY_BITS


def _scan_for_secrets(source: SourceFile) -> list[Finding]:
    """MX-SEC-001 over one file."""
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()

    for index, line in enumerate(source.lines, start=1):
        if len(line) > 500:
            # A minified bundle or an embedded data URI. Not hand-written.
            continue

        for label, pattern in _PROVIDER_RULES:
            match = pattern.search(line)
            if match is None:
                continue
            secret = match.group(0)
            key = (secret[:24], label)
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                _secret_finding(
                    source=source,
                    line=index,
                    secret=secret,
                    name=_name_near(source, index),
                    detector=label,
                    confidence=0.98,
                )
            )

        named = _credential_assignment(line) or _credential_env_default(line)
        if named is None:
            continue
        name, value = named
        if (name, value[:24]) in seen or not looks_like_secret_value(value):
            continue
        # Already reported by a provider pattern on this line.
        if any(pattern.search(value) for _, pattern in _PROVIDER_RULES):
            continue
        seen.add((name, value[:24]))
        findings.append(
            _secret_finding(
                source=source,
                line=index,
                secret=value,
                name=name,
                detector="credential-shaped name with a high-entropy literal",
                confidence=0.8,
            )
        )

    return findings


_ASSIGNMENT_RE: Final[re.Pattern[str]] = re.compile(
    r"""(?P<name>[A-Za-z_][\w.\[\]"']*)       # identifier, possibly a dict key
        \s*[:=]\s*                             # = or :
        (?P<quote>["'`])(?P<value>[^"'`]{8,})(?P=quote)""",
    re.VERBOSE,
)

# An assignment whose value continues on the next line:
#     const SUPABASE_SERVICE_ROLE_KEY =
#       "eyJ...";
_DANGLING_ASSIGNMENT_RE: Final[re.Pattern[str]] = re.compile(
    r"(?P<name>[A-Za-z_][\w.]*)\s*[:=]\s*(?:\\)?$"
)

# A credential-shaped environment lookup with a literal fallback. The fallback
# is a committed secret: it is what runs whenever the variable is unset, which
# in practice means local development and any forgotten deployment.
_ENV_DEFAULT_RE: Final[re.Pattern[str]] = re.compile(
    r"""(?:getenv|environ\.get|env\.get|get)\s*\(\s*
        (?P<quote>["'])(?P<key>[^"']+)(?P=quote)\s*,\s*
        (?P<vquote>["'])(?P<value>[^"']{8,})(?P=vquote)""",
    re.VERBOSE,
)


def _credential_assignment(line: str) -> tuple[str, str] | None:
    """A ``NAME = "literal"`` pair whose name is credential-shaped."""
    for match in _ASSIGNMENT_RE.finditer(line):
        name = match.group("name").strip("\"'")
        if _CREDENTIAL_NAME_RE.search(name):
            return (name, match.group("value"))
    return None


def _credential_env_default(line: str) -> tuple[str, str] | None:
    """A ``getenv("KEY", "literal")`` whose key or target is credential-shaped."""
    for match in _ENV_DEFAULT_RE.finditer(line):
        key = match.group("key")
        assigned = _assigned_name(line)
        if _CREDENTIAL_NAME_RE.search(key) or (
            assigned is not None and _CREDENTIAL_NAME_RE.search(assigned)
        ):
            return (assigned or key, match.group("value"))
    return None


def _assigned_name(line: str) -> str | None:
    """The identifier being assigned on a line, if any."""
    match = _ASSIGNMENT_RE.search(line)
    if match is not None:
        return match.group("name").strip("\"'")
    # `NAME = os.getenv(...)` has no quoted value, so the strict pattern misses
    # it; take the left-hand side directly.
    head, separator, _ = line.partition("=")
    if separator and head.strip():
        candidate = head.strip().split()[-1].strip("\"'")
        if re.fullmatch(r"[A-Za-z_][\w.]*", candidate):
            return candidate
    return None


def _name_near(source: SourceFile, line: int) -> str | None:
    """The variable a literal belongs to, looking back over continuations.

    A long credential is routinely wrapped onto its own line, which leaves the
    name two lines above the value. Without this the finding reports the
    detector's label as the variable name, which reads as nonsense.
    """
    for offset in range(0, 3):
        index = line - 1 - offset
        if index < 0 or index >= len(source.lines):
            continue
        text = source.lines[index]
        if offset == 0:
            name = _assigned_name(text)
            if name is not None:
                return name
            continue
        dangling = _DANGLING_ASSIGNMENT_RE.search(text.rstrip())
        if dangling is not None:
            return dangling.group("name")
    return None


def _secret_finding(
    *,
    source: SourceFile,
    line: int,
    secret: str,
    name: str | None,
    detector: str,
    confidence: float,
) -> Finding:
    location = source.location(line)
    is_frontend = source.suffix in JS_TS_SUFFIXES
    extra = (
        " This file is part of the frontend bundle, so the value is served to "
        "every visitor and readable in the browser."
        if is_frontend
        else ""
    )
    # The variable name is not always recoverable -- a credential passed
    # straight into a call has none. The message has to read correctly either
    # way, so the subject changes rather than printing a placeholder name.
    subject = name or f"A {detector.lower()}"
    return make_finding(
        "MX-SEC-001",
        # Falls back to the line when there is no name, so two unnamed secrets
        # in one file stay distinct defects.
        identity=(source.relative_path, name or f"line:{line}"),
        locations=[location],
        description=(
            f"{subject} is a credential committed in source ({detector}). Anyone with "
            f"repository access has it, and git history keeps it after deletion, so "
            f"rotating the credential is the only complete fix.{extra}"
        ),
        expected=(
            f"{name} read from the environment, with no literal fallback"
            if name
            else "The credential read from the environment at runtime"
        ),
        actual=f"{name} = {mask_secret(secret)}" if name else mask_secret(secret),
        # The literal is passed so it is masked out of the stored evidence.
        secrets=(secret,),
        confidence=confidence,
        metadata={
            "variable": name,  # may be None when the credential is passed inline
            "detector": detector,
            "masked_value": mask_secret(secret),
            "in_frontend_bundle": is_frontend,
        },
    )


# ---------------------------------------------------------------------------
# MX-SEC-004: committed .env
# ---------------------------------------------------------------------------


def _committed_env_files(env_files: list[SourceFile]) -> list[Finding]:
    """One finding per committed ``.env``, listing its keys with values masked."""
    findings: list[Finding] = []

    for source in env_files:
        entries = _env_entries(source)
        credential_keys = [
            key
            for key, value in entries
            if _CREDENTIAL_NAME_RE.search(key) or looks_like_secret_value(value)
        ]
        keys_text = ", ".join(credential_keys[:12]) or "no recognised credentials"

        findings.append(
            make_finding(
                "MX-SEC-004",
                identity=(source.relative_path,),
                locations=[source.location(1, min(len(source.lines) or 1, 1))],
                description=(
                    f"{source.relative_path} is committed to the repository. A .env file "
                    f"exists precisely to stay out of version control, so every value in "
                    f"it is shared with everyone who can read the repository and remains "
                    f"in git history after deletion. Credential keys present: {keys_text}."
                ),
                expected=f"{source.relative_path} listed in .gitignore and the values rotated",
                actual=(
                    f"{len(entries)} variables committed, "
                    f"{len(credential_keys)} credential-shaped"
                ),
                # Every value is masked out of the evidence snippet.
                secrets=tuple(value for _, value in entries if len(value) >= 8),
                metadata={
                    "file": source.relative_path,
                    "variable_count": len(entries),
                    "credential_keys": credential_keys,
                    # Keys only. The values are what we are trying not to spread.
                    "all_keys": [key for key, _ in entries],
                },
            )
        )

    return findings


def _env_entries(source: SourceFile) -> list[tuple[str, str]]:
    """``KEY=value`` pairs from a dotenv file."""
    entries: list[tuple[str, str]] = []
    for raw in source.lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        entries.append((key.strip(), value.strip().strip("\"'")))
    return entries


# ---------------------------------------------------------------------------
# MX-SEC-003: CORS
# ---------------------------------------------------------------------------


def _cors_findings(modules: list[ParsedPythonModule]) -> list[Finding]:
    """A wildcard origin, reported harder when credentials are also allowed."""
    findings: list[Finding] = []

    for module in modules:
        for call in module.calls():
            callee = dotted_name(call.func)
            if callee is None or "add_middleware" not in callee:
                continue

            middleware = call.args[0] if call.args else None
            middleware_name = dotted_name(middleware) if middleware is not None else None
            if middleware_name is None or "CORS" not in middleware_name:
                continue

            origins = string_items(call_keyword(call, "allow_origins"))
            if "*" not in origins:
                continue

            credentials = literal_value(call_keyword(call, "allow_credentials")) is True
            severity = Severity.HIGH if credentials else Severity.MEDIUM
            consequence = (
                "Combined with allow_credentials=True, any website can make "
                "authenticated cross-origin requests using a logged-in user's "
                "cookies. Browsers reject this combination, so the practical effect "
                "is often a broken app plus a misleading sense of permissiveness."
                if credentials
                else "Any origin can read responses from this API."
            )

            findings.append(
                make_finding(
                    "MX-SEC-003",
                    identity=(module.source.relative_path, "cors"),
                    locations=[module.location_of(call)],
                    description=f"CORS is configured with a wildcard origin. {consequence}",
                    expected="An explicit list of allowed origins",
                    actual=(
                        f"allow_origins=['*']"
                        f"{', allow_credentials=True' if credentials else ''}"
                    ),
                    severity=severity,
                    metadata={
                        "allow_origins": origins,
                        "allow_credentials": credentials,
                        "file": module.source.relative_path,
                    },
                )
            )

    return findings


# ---------------------------------------------------------------------------
# MX-SEC-005: debug mode
# ---------------------------------------------------------------------------

_APP_FACTORIES: Final[frozenset[str]] = frozenset({"FastAPI", "Flask", "Starlette", "Quart"})


def _debug_findings(modules: list[ParsedPythonModule]) -> list[Finding]:
    """``FastAPI(debug=True)`` / ``app.run(debug=True)``."""
    findings: list[Finding] = []

    for module in modules:
        for call in module.calls():
            callee = dotted_name(call.func)
            if callee is None:
                continue
            short = callee.rpartition(".")[2]
            if short not in _APP_FACTORIES and not callee.endswith(".run"):
                continue
            if literal_value(call_keyword(call, "debug")) is not True:
                continue

            findings.append(
                make_finding(
                    "MX-SEC-005",
                    identity=(module.source.relative_path, short),
                    locations=[module.location_of(call)],
                    description=(
                        f"{short} is constructed with debug=True. Debug handlers render "
                        f"stack traces, source fragments and local variables to anyone "
                        f"who can trigger an error, which routinely includes credentials "
                        f"held in local variables."
                    ),
                    expected="debug driven by an environment variable, defaulting to off",
                    actual=f"{short}(debug=True)",
                    metadata={"factory": short, "file": module.source.relative_path},
                )
            )

    return findings


# ---------------------------------------------------------------------------
# MX-SEC-002: unprotected sensitive route
# ---------------------------------------------------------------------------

# Words that mark a route as handling money, identity or bulk personal data.
# Deliberately narrow: `user` and `item` are far too common to carry signal,
# and including them would flag ordinary CRUD in every project.
_SENSITIVE_WORDS: Final[frozenset[str]] = frozenset(
    {
        "refund",
        "payment",
        "payout",
        "charge",
        "invoice",
        "billing",
        "transfer",
        "withdraw",
        "subscription",
        "card",
        "bank",
        "admin",
        "superuser",
        "impersonate",
        "sudo",
        "export",
        "download-all",
        "bulk",
        "dump",
        "backup",
        "customer",
        "credential",
        "password",
        "secret",
        "token",
        "apikey",
        "permission",
        "role",
        "privilege",
        "grant",
        "ssn",
        "tax",
        "salary",
        "payroll",
        "medical",
        "delete-all",
        "purge",
        "truncate",
        "wipe",
    }
)


def _unprotected_route_findings(extraction: RouteExtraction) -> list[Finding]:
    """A sensitive route with no auth, whose siblings have some.

    The inconsistency is the signal. "This route has no authentication" is
    true of every public endpoint in every project and carries no information;
    "this route handles refunds and its three neighbours all require a user"
    is nearly always a mistake.
    """
    findings: list[Finding] = []
    groups = _group_by_router(extraction.routes)

    for routes in groups.values():
        protected = [route for route in routes if route.is_authenticated]
        if not protected:
            # Nothing on this router is protected, so there is no inconsistency
            # to report. An entirely public API is a design choice.
            continue

        for route in routes:
            if route.is_authenticated:
                continue
            matched = _sensitive_words_in(route)
            if not matched:
                continue

            findings.append(
                make_finding(
                    "MX-SEC-002",
                    identity=(route.method, route.path, route.handler_name),
                    locations=[route.location, *(r.location for r in protected[:2])],
                    description=(
                        f"{route.handler_name} ({route.method} {route.path}) declares no "
                        f"authentication, while {len(protected)} of the "
                        f"{len(routes)} routes on the same router do. The path or handler "
                        f"names {', '.join(sorted(matched))}, so this is a sensitive "
                        f"operation left open rather than a deliberately public endpoint."
                    ),
                    expected=(
                        "An authentication dependency, matching the sibling routes: "
                        + ", ".join(sorted({d for r in protected for d in r.all_dependencies}))
                    ),
                    actual="No authentication dependency on the route or its router",
                    metadata={
                        "method": route.method,
                        "path": route.path,
                        "handler": route.handler_name,
                        "sensitive_terms": sorted(matched),
                        "protected_siblings": [r.handler_name for r in protected],
                        "sibling_dependencies": sorted(
                            {d for r in protected for d in r.all_dependencies}
                        ),
                    },
                )
            )

    return findings


def _group_by_router(
    routes: list[BackendRoute],
) -> dict[tuple[str, str | None], list[BackendRoute]]:
    """Group routes by the router they are declared on.

    Keyed on file *and* router variable: two routers in one module are
    separate scopes, and the same variable name in two modules is too.
    """
    grouped: dict[tuple[str, str | None], list[BackendRoute]] = defaultdict(list)
    for route in routes:
        grouped[(route.location.file_path, route.router_variable)].append(route)
    return dict(grouped)


def _sensitive_words_in(route: BackendRoute) -> set[str]:
    """Sensitive terms appearing in a route's path or handler name."""
    haystack = f"{route.path} {route.handler_name}".lower().replace("_", "-")
    return {word for word in _SENSITIVE_WORDS if word in haystack}
