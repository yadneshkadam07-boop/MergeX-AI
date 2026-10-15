"""Platform-side security primitives.

MergeX ingests untrusted repositories: arbitrary archive members, arbitrary
file names, arbitrary symlinks. These helpers keep every filesystem operation
inside the analysis sandbox and keep credentials out of logs.

Nothing here analyses user code; it protects the platform that does.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

__all__ = [
    "UnsafePathError",
    "is_within",
    "mask_secret",
    "redact_url_credentials",
    "safe_archive_member_path",
    "safe_join",
]

# Characters and names that are illegal or dangerous as path components.
_FORBIDDEN_CHARS = frozenset({"\x00", "\n", "\r"})
_WINDOWS_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)


class UnsafePathError(ValueError):
    """Raised when a path would escape the sandbox or is otherwise illegal."""


def is_within(base: Path, candidate: Path) -> bool:
    """Return True when ``candidate`` resolves to a location inside ``base``.

    Both paths are fully resolved first, so ``..`` segments and symlinks are
    accounted for. Neither path needs to exist.
    """
    try:
        resolved_base = base.resolve()
        resolved_candidate = candidate.resolve()
    except OSError:  # pragma: no cover - unreachable on supported platforms
        return False
    return resolved_candidate == resolved_base or resolved_base in resolved_candidate.parents


def safe_join(base: Path, *parts: str) -> Path:
    """Join ``parts`` onto ``base``, refusing anything that escapes ``base``.

    Raises:
        UnsafePathError: on absolute parts, ``..`` traversal, NUL bytes, or any
            result landing outside ``base``.
    """
    for part in parts:
        if not part:
            continue
        if _FORBIDDEN_CHARS & set(part):
            raise UnsafePathError(f"path component contains illegal characters: {part!r}")
        candidate_part = PurePosixPath(part.replace("\\", "/"))
        if candidate_part.is_absolute() or part.startswith(("/", "\\")):
            raise UnsafePathError(f"absolute path component is not allowed: {part!r}")
        if ".." in candidate_part.parts:
            raise UnsafePathError(f"parent traversal is not allowed: {part!r}")

    joined = base.joinpath(*parts)
    if not is_within(base, joined):
        raise UnsafePathError(f"resolved path escapes the sandbox: {joined}")
    return joined


def safe_archive_member_path(base: Path, member_name: str) -> Path:
    r"""Map an archive member name to a safe destination inside ``base``.

    This is the zip-slip guard. It rejects absolute names, drive-qualified
    names (``C:\evil``), UNC paths and ``..`` traversal, and normalises the
    separators that ZIP files may legitimately contain.

    Raises:
        UnsafePathError: if the member cannot be extracted safely.
    """
    name = member_name.strip().replace("\\", "/")
    if not name or name in {".", "./"}:
        raise UnsafePathError("archive member has an empty name")
    if _FORBIDDEN_CHARS & set(name):
        raise UnsafePathError(f"archive member name contains illegal characters: {member_name!r}")
    if name.startswith("//"):
        raise UnsafePathError(f"UNC archive member name is not allowed: {member_name!r}")
    # Windows drive qualifier, e.g. "C:/Windows" or "C:evil.txt".
    if len(name) >= 2 and name[1] == ":" and name[0].isalpha():
        raise UnsafePathError(f"drive-qualified archive member name: {member_name!r}")

    pure = PurePosixPath(name)
    parts = [p for p in pure.parts if p not in {"", "."}]
    if not parts:
        raise UnsafePathError(f"archive member resolves to nothing: {member_name!r}")
    if ".." in parts:
        raise UnsafePathError(f"archive member escapes the sandbox: {member_name!r}")
    if any(Path(p).stem.upper() in _WINDOWS_RESERVED for p in parts):
        raise UnsafePathError(f"archive member uses a reserved device name: {member_name!r}")

    return safe_join(base, *parts)


def mask_secret(value: str | None, *, keep: int = 4) -> str:
    """Render a credential for logs: ``ghp_1234…`` becomes ``ghp_…abcd``."""
    if not value:
        return "<unset>"
    if len(value) <= keep:
        return "*" * len(value)
    return f"{'*' * 8}{value[-keep:]}"


def redact_url_credentials(url: str) -> str:
    """Strip ``user:password@`` from a URL so it is safe to log."""
    scheme_sep = "://"
    if scheme_sep not in url:
        return url
    scheme, _, remainder = url.partition(scheme_sep)
    if "@" not in remainder:
        return url
    _, _, host_part = remainder.rpartition("@")
    return f"{scheme}{scheme_sep}***:***@{host_part}"
