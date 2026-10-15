"""GitHub source parsing.

Only ``github.com`` is accepted. That is a security boundary, not a product
limitation: the importer hands this URL to ``git clone``, so accepting an
arbitrary host would turn the import endpoint into a server-side request
forgery primitive against anything the backend can reach -- including cloud
metadata services and databases on the internal network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

__all__ = [
    "GITHUB_HOSTS",
    "GitHubRepoRef",
    "InvalidGitHubUrlError",
    "parse_github_url",
]

GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})

# GitHub's own rules: owners are alphanumeric with single hyphens; repository
# names additionally allow dots and underscores.
_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
# A ref may not contain these; git itself rejects most, but we check first so
# a malformed ref never reaches the command line.
_REF_RE = re.compile(r"^[A-Za-z0-9._/-]{1,255}$")

# Path segments that mean "this is a GitHub page, not a repository".
_RESERVED_OWNERS = frozenset(
    {
        "settings",
        "notifications",
        "explore",
        "topics",
        "trending",
        "collections",
        "events",
        "sponsors",
        "features",
        "pricing",
        "marketplace",
        "apps",
        "orgs",
        "login",
        "join",
        "about",
        "contact",
        "search",
        "new",
        "codespaces",
        "pulls",
        "issues",
        "dashboard",
    }
)

# Where a ref can appear in a pasted URL: /owner/repo/tree/<ref>/...
_REF_BEARING_SEGMENTS = frozenset({"tree", "blob", "commit", "releases", "commits"})


class InvalidGitHubUrlError(ValueError):
    """Raised when a string is not a usable public GitHub repository URL."""


@dataclass(frozen=True, slots=True)
class GitHubRepoRef:
    """A parsed, normalised reference to a GitHub repository."""

    owner: str
    repo: str
    ref: str | None = None

    @property
    def full_name(self) -> str:
        """``owner/repo``, as the GitHub REST API expects it."""
        return f"{self.owner}/{self.repo}"

    @property
    def canonical_url(self) -> str:
        """The https URL this reference normalises to."""
        return f"https://github.com/{self.owner}/{self.repo}"

    @property
    def clone_url(self) -> str:
        """The URL to pass to ``git clone``."""
        return f"{self.canonical_url}.git"

    def authenticated_clone_url(self, token: str) -> str:
        """Clone URL carrying ``token``, for private repositories.

        The result contains a credential: never log it, and never store it.
        """
        return f"https://x-access-token:{token}@github.com/{self.owner}/{self.repo}.git"

    @property
    def default_project_name(self) -> str:
        """A sensible project name when the user supplies none."""
        return self.repo


def parse_github_url(raw: str, *, ref: str | None = None) -> GitHubRepoRef:
    """Parse and normalise a GitHub repository URL.

    Accepts the forms people actually paste: with or without a scheme, with or
    without ``www.``, with a trailing ``.git`` or slash, and deep links such as
    ``/owner/repo/tree/develop/src`` (from which the ref is recovered).

    Args:
        raw: The URL or ``github.com/owner/repo`` string.
        ref: An explicit branch, tag or commit. Overrides one found in ``raw``.

    Raises:
        InvalidGitHubUrlError: if ``raw`` is not a GitHub repository URL, or if
            the host is anything other than github.com.
    """
    candidate = (raw or "").strip()
    if not candidate:
        raise InvalidGitHubUrlError("Repository URL must not be empty.")
    if any(char.isspace() for char in candidate):
        raise InvalidGitHubUrlError("Repository URL must not contain whitespace.")

    candidate = _normalise_scheme(candidate)
    parts = urlsplit(candidate)

    if parts.scheme not in {"http", "https"}:
        raise InvalidGitHubUrlError(
            f"Unsupported URL scheme {parts.scheme!r}; use an https github.com URL."
        )
    # Embedded credentials would be passed straight to git.
    if "@" in parts.netloc:
        raise InvalidGitHubUrlError("Repository URL must not embed credentials.")
    if parts.hostname is None or parts.hostname.lower() not in GITHUB_HOSTS:
        raise InvalidGitHubUrlError(
            f"Only github.com repositories are supported, got {parts.hostname!r}."
        )
    if parts.port is not None:
        raise InvalidGitHubUrlError("Repository URL must not specify a port.")

    segments = [segment for segment in parts.path.split("/") if segment]
    if len(segments) < 2:
        raise InvalidGitHubUrlError(
            "Repository URL must include an owner and a repository, e.g. "
            "https://github.com/owner/repo."
        )

    owner, repo = segments[0], segments[1]
    if repo.lower().endswith(".git"):
        repo = repo[: -len(".git")]

    _validate_owner(owner)
    _validate_repo(repo)

    resolved_ref = ref if ref is not None else _ref_from_segments(segments[2:])
    if resolved_ref is not None:
        _validate_ref(resolved_ref)

    return GitHubRepoRef(owner=owner, repo=repo, ref=resolved_ref)


def _normalise_scheme(candidate: str) -> str:
    """Add an https scheme when the user omitted one, and convert SSH form."""
    # git@github.com:owner/repo.git -> https://github.com/owner/repo.git
    if candidate.startswith("git@"):
        _, _, remainder = candidate.partition("@")
        host, _, path = remainder.partition(":")
        return f"https://{host}/{path}"
    if candidate.startswith("ssh://"):
        raise InvalidGitHubUrlError("SSH URLs are not supported; use the https URL.")
    if "://" not in candidate:
        return f"https://{candidate}"
    return candidate


def _validate_owner(owner: str) -> None:
    if owner.lower() in _RESERVED_OWNERS:
        raise InvalidGitHubUrlError(f"{owner!r} is a GitHub site path, not a repository owner.")
    if not _OWNER_RE.match(owner):
        raise InvalidGitHubUrlError(f"Invalid repository owner {owner!r}.")
    if "--" in owner:
        raise InvalidGitHubUrlError(f"Invalid repository owner {owner!r}.")


def _validate_repo(repo: str) -> None:
    if repo in {".", ".."} or not _REPO_RE.match(repo):
        raise InvalidGitHubUrlError(f"Invalid repository name {repo!r}.")


def _validate_ref(ref: str) -> None:
    if not _REF_RE.match(ref):
        raise InvalidGitHubUrlError(f"Invalid git ref {ref!r}.")
    # `--upload-pack=...` style arguments, and refs git itself rejects.
    if ref.startswith("-") or ".." in ref or ref.endswith((".lock", "/")):
        raise InvalidGitHubUrlError(f"Invalid git ref {ref!r}.")


def _ref_from_segments(segments: list[str]) -> str | None:
    """Recover a ref from a deep link such as ``/tree/release/v2/src``."""
    if len(segments) < 2 or segments[0] not in _REF_BEARING_SEGMENTS:
        return None
    # `/tree/<ref>` -- a ref may itself contain slashes (release/v2), but so
    # may the trailing path, and the two are ambiguous. Take one segment,
    # which is correct for the overwhelmingly common case.
    return segments[1]
