"""Safe ZIP extraction.

A ZIP upload is the most hostile input MergeX accepts: the archive controls
every member name, every declared size and the compression ratio. Python's
``ZipFile.extractall`` is not safe for this -- it will happily write outside
the destination given a crafted name.

Every archive is therefore inspected in full *before* a single byte is
written, and each member is then extracted individually through the path
guards in :mod:`app.core.security`.

Defences, and what each one stops:

============================  ===============================================
Guard                         Attack
============================  ===============================================
``safe_archive_member_path``  zip slip (``../../etc/passwd``, ``C:\\evil``)
declared-size budget          disk exhaustion via a large archive
compression-ratio ceiling     zip bomb (42.zip: kilobytes to petabytes)
member-count ceiling          inode exhaustion, analysis timeout
written-bytes accounting      a member lying about its uncompressed size
symlink rejection             escaping the sandbox after extraction
nested-archive policy         recursive bombs
============================  ===============================================
"""

from __future__ import annotations

import stat
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from app.core.logging import get_logger
from app.core.security import UnsafePathError, safe_archive_member_path

__all__ = [
    "ArchiveLimits",
    "ExtractionResult",
    "InvalidArchiveError",
    "IGNORED_DIRECTORIES",
    "IGNORED_FILE_SUFFIXES",
    "extract_zip",
    "is_ignored_path",
]

log = get_logger("app.archive")

# Directories that are never analysis input: version-control internals,
# installed dependencies, build output and caches. Skipping them keeps the
# size and file-count limits meaningful -- a `node_modules` tree is routinely
# larger than the source it belongs to. Manifests and lockfiles live at the
# project root, so dependency scanning is unaffected.
IGNORED_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".bzr",
        "node_modules",
        "bower_components",
        "jspm_packages",
        ".venv",
        "venv",
        "env",
        "virtualenv",
        "site-packages",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "dist",
        "build",
        "out",
        ".next",
        ".nuxt",
        ".svelte-kit",
        ".output",
        ".turbo",
        ".parcel-cache",
        ".cache",
        ".gradle",
        "target",
        ".idea",
        ".vscode",
        ".DS_Store",
        "coverage",
        "htmlcov",
        ".nyc_output",
        "vendor",
    }
)

IGNORED_FILE_SUFFIXES = frozenset(
    {
        ".pyc",
        ".pyo",
        ".pyd",
        ".so",
        ".dylib",
        ".dll",
        ".o",
        ".a",
        ".obj",
        ".class",
        ".jar",
        ".war",
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",  # nested archives
        ".exe",
        ".msi",
        ".dmg",
        ".deb",
        ".rpm",
        ".bin",
        ".mp4",
        ".mov",
        ".avi",
        ".mkv",
        ".webm",
        ".mp3",
        ".wav",
        ".flac",
        ".psd",
        ".ai",
        ".sketch",
        ".fig",
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".otf",
        ".pack",
        ".idx",
        ".db",
        ".sqlite",
        ".sqlite3",
    }
)

# A legitimate source archive compresses well, but not absurdly. Text at 10:1
# is normal; 42.zip reaches 10^9:1. The ratio is only consulted once the
# declared output is large enough for the ratio to be meaningful.
_MAX_COMPRESSION_RATIO = 150.0
_RATIO_CHECK_THRESHOLD_BYTES = 32 * 1024 * 1024


class InvalidArchiveError(ValueError):
    """The upload is not a usable ZIP archive, or violates a safety limit."""


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    """Caps applied to one archive."""

    max_total_bytes: int
    max_file_count: int
    # Any single member larger than this is refused outright.
    max_member_bytes: int | None = None

    def member_ceiling(self) -> int:
        return self.max_member_bytes or self.max_total_bytes


@dataclass(slots=True)
class ExtractionResult:
    """What extraction produced."""

    root: Path
    file_count: int = 0
    size_bytes: int = 0
    skipped_paths: int = 0
    stripped_prefix: str | None = None
    rejected: list[str] = field(default_factory=list)


def is_ignored_path(relative_path: str) -> bool:
    """True when a path lies in an ignored directory or has an ignored suffix.

    ``relative_path`` uses forward slashes, as ZIP members do.
    """
    pure = PurePosixPath(relative_path)
    if any(part in IGNORED_DIRECTORIES for part in pure.parts[:-1]):
        return True
    if pure.name in IGNORED_DIRECTORIES:
        return True
    return pure.suffix.lower() in IGNORED_FILE_SUFFIXES


def extract_zip(
    archive_path: Path,
    destination: Path,
    limits: ArchiveLimits,
    *,
    strip_top_level: bool = True,
) -> ExtractionResult:
    """Extract ``archive_path`` into ``destination``, safely.

    Args:
        archive_path: The uploaded ZIP.
        destination: An existing, empty directory inside the sandbox.
        limits: Size and count caps, enforced before and during extraction.
        strip_top_level: Remove the single wrapping directory that GitHub's
            "Download ZIP" adds (``repo-main/``), so paths in findings match
            the paths a developer sees.

    Raises:
        InvalidArchiveError: if the file is not a ZIP, or a limit is exceeded.
    """
    if not zipfile.is_zipfile(archive_path):
        raise InvalidArchiveError("The uploaded file is not a valid ZIP archive.")

    with zipfile.ZipFile(archive_path) as archive:
        members = _analysable_members(archive)
        if not members:
            raise InvalidArchiveError("The archive contains no analysable source files.")

        _enforce_declared_limits(members, limits)
        prefix = _common_top_level(members) if strip_top_level else None

        result = ExtractionResult(root=destination, stripped_prefix=prefix)
        for member in members:
            relative = _strip_prefix(member.filename, prefix)
            if not relative:
                continue
            _extract_member(archive, member, destination, relative, limits, result)

    log.info(
        "archive_extracted",
        files=result.file_count,
        bytes=result.size_bytes,
        skipped=result.skipped_paths,
        stripped_prefix=result.stripped_prefix,
    )
    return result


def _analysable_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Members worth extracting: real files, not ignored, not symlinks."""
    return [member for member in archive.infolist() if _should_extract(member)]


def _should_extract(member: zipfile.ZipInfo) -> bool:
    if member.is_dir():
        return False
    # A symlink in a ZIP is stored with S_IFLNK in the upper external_attr
    # bits. Extracting one would place a pointer to an arbitrary absolute path
    # inside the sandbox, which later reads would follow.
    mode = member.external_attr >> 16
    if mode and stat.S_ISLNK(mode):
        return False
    return not is_ignored_path(member.filename)


def _enforce_declared_limits(members: list[zipfile.ZipInfo], limits: ArchiveLimits) -> None:
    """Check the archive's own metadata before writing anything."""
    if len(members) > limits.max_file_count:
        raise InvalidArchiveError(
            f"Archive contains {len(members)} files, which exceeds the limit of "
            f"{limits.max_file_count}."
        )

    declared_total = sum(member.file_size for member in members)
    if declared_total > limits.max_total_bytes:
        raise InvalidArchiveError(
            f"Archive expands to {_mb(declared_total)} MB, which exceeds the limit of "
            f"{_mb(limits.max_total_bytes)} MB."
        )

    ceiling = limits.member_ceiling()
    for member in members:
        if member.file_size > ceiling:
            raise InvalidArchiveError(
                f"Archive member {member.filename!r} is {_mb(member.file_size)} MB, "
                f"which exceeds the per-file limit of {_mb(ceiling)} MB."
            )

    compressed_total = sum(member.compress_size for member in members)
    if declared_total > _RATIO_CHECK_THRESHOLD_BYTES and compressed_total > 0:
        ratio = declared_total / compressed_total
        if ratio > _MAX_COMPRESSION_RATIO:
            raise InvalidArchiveError(
                f"Archive compression ratio {ratio:.0f}:1 is implausible for source "
                "code and was rejected as a potential zip bomb."
            )


def _extract_member(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    destination: Path,
    relative: str,
    limits: ArchiveLimits,
    result: ExtractionResult,
) -> None:
    """Write one member, re-checking the budget against real bytes."""
    try:
        target = safe_archive_member_path(destination, relative)
    except UnsafePathError as exc:
        # Record and skip rather than abort: one hostile entry in an otherwise
        # legitimate archive should not fail the whole import.
        result.skipped_paths += 1
        if len(result.rejected) < 20:
            result.rejected.append(member.filename)
        log.warning("archive_member_rejected", member=member.filename, reason=str(exc))
        return

    target.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    with archive.open(member) as source, target.open("wb") as sink:
        # Streamed in chunks, and counted as it goes: a member may declare a
        # small file_size in its header and then supply far more data.
        for chunk in _read_chunks(source):
            written += len(chunk)
            if result.size_bytes + written > limits.max_total_bytes:
                sink.close()
                target.unlink(missing_ok=True)
                raise InvalidArchiveError(
                    f"Archive exceeded the {_mb(limits.max_total_bytes)} MB limit while "
                    "being extracted; the declared size was understated."
                )
            sink.write(chunk)

    result.file_count += 1
    result.size_bytes += written


def _read_chunks(source: object, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
    read = source.read  # type: ignore[attr-defined]
    while True:
        chunk = read(chunk_size)
        if not chunk:
            return
        yield chunk


def _common_top_level(members: list[zipfile.ZipInfo]) -> str | None:
    """The single wrapping directory shared by every member, if there is one."""
    first_segments = set()
    for member in members:
        parts = PurePosixPath(member.filename.replace("\\", "/")).parts
        if len(parts) < 2:
            # A file at the archive root means there is no wrapper to strip.
            return None
        first_segments.add(parts[0])
        if len(first_segments) > 1:
            return None
    return next(iter(first_segments)) if first_segments else None


def _strip_prefix(filename: str, prefix: str | None) -> str:
    normalised = filename.replace("\\", "/")
    if prefix is None:
        return normalised
    marker = f"{prefix}/"
    return normalised[len(marker) :] if normalised.startswith(marker) else normalised


def _mb(num_bytes: int) -> int:
    return max(1, round(num_bytes / (1024 * 1024)))
