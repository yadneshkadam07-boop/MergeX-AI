"""URL path normalisation.

The whole point of MergeX is comparing a frontend call site against a backend
route, and the two are almost never written the same way:

===========================  ================  =====================
Written as                   Where             Normalises to
===========================  ================  =====================
``/users/{user_id}``         FastAPI           ``/users/{}``
``/users/:id``               Express           ``/users/{}``
``` `/users/${id}` ```       fetch / axios     ``/users/{}``
``/users/<int:user_id>``     Flask             ``/users/{}``
``/users/%s``                printf-style      ``/users/{}``
``/users/5``                 a literal id      ``/users/{}``
===========================  ================  =====================

Parameter *names* are deliberately discarded: a frontend has no obligation to
name a path parameter the same as the backend does, so comparing names would
produce constant false positives. Position and count are what must match.

A numeric literal is treated as a parameter because ``/users/5`` in a test or
a hardcoded call is the same endpoint as ``/users/{id}``. That is a judgement
call and it is the conservative one: it prevents a false "missing endpoint".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

__all__ = [
    "PARAM",
    "NormalizedPath",
    "join_paths",
    "normalize_path",
    "paths_differ_by_one_edit",
]

# The placeholder every dynamic segment collapses to.
PARAM: Final[str] = "{}"

# A whole segment that is a parameter in some framework's syntax.
_PARAM_SEGMENT_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"^\{[^}]*\}$"),  # FastAPI / Starlette: {user_id}
    re.compile(r"^:[A-Za-z_][\w-]*\??$"),  # Express / NestJS:    :id, :id?
    re.compile(r"^<[^>]*>$"),  # Flask:               <int:user_id>
    re.compile(r"^\$\{[^}]*\}$"),  # JS template:         ${id}
    re.compile(r"^%[sd]$"),  # printf style:        %s
    re.compile(r"^\*$"),  # wildcard
    re.compile(r"^\d+$"),  # a hardcoded id
    re.compile(r"^\(\?P<[^>]+>.*\)$"),  # Django re_path group
)

# A parameter embedded inside a larger segment, e.g. `user-${id}.json` or
# `{id}.json`. Replaced in place so the surrounding literal text still
# participates in the comparison.
_INLINE_PARAM_RE: Final[re.Pattern[str]] = re.compile(
    r"\$\{[^}]*\}"  # ${id}
    r"|\{[^}]*\}"  # {id}
    r"|<[^>]*>"  # <int:id>
    r"|%[sd]"  # %s
)

# Segments that mean "this value is not statically knowable", which makes the
# whole path unusable for comparison.
_OPAQUE_RE: Final[re.Pattern[str]] = re.compile(r"\$\{|\{\{")

# An interpolation at the very start of a template, e.g. `${API_BASE_URL}` in
# `${API_BASE_URL}/api/users`. Treated as the origin, not a path segment.
_LEADING_INTERPOLATION_RE: Final[re.Pattern[str]] = re.compile(r"^\$\{[^}]*\}")

# A value that is nothing but an interpolation: no path information at all.
_WHOLE_INTERPOLATION_RE: Final[re.Pattern[str]] = re.compile(r"^\s*\$\{[^}]*\}\s*$")


@dataclass(frozen=True, slots=True)
class NormalizedPath:
    """A path reduced to a comparable form."""

    raw: str
    path: str
    segments: tuple[str, ...]
    param_count: int
    base_url: str | None = None
    # True when the path could not be fully resolved -- for example the whole
    # path came from a variable. Comparisons must not report a mismatch for
    # these; there is nothing to compare.
    is_opaque: bool = False

    @property
    def is_dynamic(self) -> bool:
        return self.param_count > 0

    @property
    def is_absolute_url(self) -> bool:
        """True when the call targeted an explicit host."""
        return self.base_url is not None

    def __str__(self) -> str:
        return self.path


def normalize_path(raw: str, *, prefix: str = "") -> NormalizedPath:
    """Reduce a written path to its comparable form.

    Args:
        raw: The path as it appears in source, possibly a full URL, possibly
            with a query string, possibly containing framework-specific
            parameter syntax.
        prefix: A mount prefix to prepend (a FastAPI router prefix, an Express
            ``app.use`` path).

    Returns:
        A :class:`NormalizedPath`. Never raises: unparseable input comes back
        marked ``is_opaque`` so callers can skip it rather than guess.
    """
    text = (raw or "").strip()
    if not text:
        return NormalizedPath(raw=raw, path="", segments=(), param_count=0, is_opaque=True)

    base_url, path_part = _split_base_url(text)

    # A URL that is *entirely* an interpolation -- `fetch(url)` written as
    # ``fetch(`${endpoint}`)`` -- names no path at all. It must be opaque
    # rather than normalise to `/{}`, which would otherwise match any
    # single-segment route and invent findings.
    if _WHOLE_INTERPOLATION_RE.match(path_part):
        return NormalizedPath(
            raw=raw,
            path="",
            segments=(),
            param_count=0,
            base_url=base_url,
            is_opaque=True,
        )

    # Drop the query string and fragment: they are not part of route identity.
    path_part = path_part.split("?", 1)[0].split("#", 1)[0]

    combined = join_paths(prefix, path_part) if prefix else path_part
    if not combined.startswith("/"):
        combined = f"/{combined}"

    normalized_segments: list[str] = []
    param_count = 0
    opaque = False

    for segment in combined.split("/"):
        if not segment:
            continue
        if _is_param_segment(segment):
            normalized_segments.append(PARAM)
            param_count += 1
            continue
        replaced, substitutions = _INLINE_PARAM_RE.subn(PARAM, segment)
        if substitutions:
            param_count += substitutions
            normalized_segments.append(replaced)
            continue
        if _OPAQUE_RE.search(segment):
            opaque = True
            normalized_segments.append(PARAM)
            param_count += 1
            continue
        normalized_segments.append(segment)

    path = "/" + "/".join(normalized_segments)
    return NormalizedPath(
        raw=raw,
        path=path,
        segments=tuple(normalized_segments),
        param_count=param_count,
        base_url=base_url,
        is_opaque=opaque,
    )


def _split_base_url(text: str) -> tuple[str | None, str]:
    """Separate a URL's origin from its path.

    Three cases, and the third is the one that matters:

    ``https://api.test/v1/users``   -> origin + ``/v1/users``
    ``//api.test/v1/users``         -> protocol-relative, same treatment
    ``${API_BASE_URL}/api/users``   -> the *interpolation* is the origin

    That last form is how nearly every real frontend is written. Treating the
    leading ``${...}`` as a path segment would normalise the call to
    ``/{}/api/users`` and make it mismatch every route on the server -- a
    false positive on correct code, which is the worst failure mode this
    product has.
    """
    if "://" in text:
        parts = urlsplit(text)
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}", parts.path or "/"
    if text.startswith("//"):
        parts = urlsplit(f"https:{text}")
        if parts.netloc:
            return f"//{parts.netloc}", parts.path or "/"

    leading = _LEADING_INTERPOLATION_RE.match(text)
    if leading is not None:
        remainder = text[leading.end() :]
        # Only an origin if a path actually follows; `${endpoint}` alone is an
        # entire unresolved URL, not a base.
        if remainder.startswith("/"):
            return leading.group(0), remainder
    return None, text


def _is_param_segment(segment: str) -> bool:
    return any(pattern.match(segment) for pattern in _PARAM_SEGMENT_PATTERNS)


def join_paths(*parts: str) -> str:
    """Join URL path fragments without doubling or dropping slashes."""
    cleaned = [part.strip("/") for part in parts if part and part.strip("/")]
    joined = "/".join(cleaned)
    return f"/{joined}" if joined else "/"


def paths_differ_by_one_edit(left: str, right: str) -> bool:
    """True when two paths differ by a single character edit.

    This is what separates "you have a typo" from "that endpoint does not
    exist", and the difference matters: a near match should be reported with
    the suggestion rather than as a missing route. ``/api/user/{}`` against
    ``/api/users/{}`` is one insertion.

    One edit means a substitution, an insertion, a deletion, **or a
    transposition of two adjacent characters** -- Damerau-Levenshtein rather
    than plain Levenshtein, because ``/usres`` for ``/users`` is one of the
    most common typos there is and counts as two substitutions otherwise.

    Bounded: it returns as soon as the distance exceeds one, so it is cheap
    enough to run against every route for every call.
    """
    if left == right:
        return False
    if abs(len(left) - len(right)) > 1:
        return False

    if len(left) == len(right):
        differing = [index for index, (a, b) in enumerate(zip(left, right, strict=True)) if a != b]
        if len(differing) == 1:
            return True
        # Adjacent transposition: exactly two neighbouring positions differ,
        # and swapping them makes the strings equal.
        if len(differing) == 2 and differing[1] == differing[0] + 1:
            first, second = differing
            return left[first] == right[second] and left[second] == right[first]
        return False

    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    # One insertion: skip a single character in the longer string and the
    # remainder must match exactly.
    index = 0
    while index < len(shorter) and shorter[index] == longer[index]:
        index += 1
    return shorter[index:] == longer[index + 1 :]
