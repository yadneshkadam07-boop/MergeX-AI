"""Shared types for parsing and extraction.

:class:`SourceLocation` is the contract every extracted fact must satisfy:
a repo-relative path, a 1-based inclusive line range, and the source text at
that range.

The snippet is captured **at extraction time**, not looked up later, because
the working tree is deleted as soon as an analysis finishes. An issue's
evidence has to survive the sandbox it came from.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "MAX_SNIPPET_LINES",
    "SourceFile",
    "SourceLocation",
    "iter_source_files",
    "load_source_file",
]

# An evidence snippet is for a human reading a finding, not a code listing.
MAX_SNIPPET_LINES = 12


@dataclass(frozen=True, slots=True, order=True)
class SourceLocation:
    """Where a fact was found, and the text that proves it.

    Line numbers are 1-based and inclusive at both ends, matching what editors
    and the ``line_start`` / ``line_end`` columns on ``issues`` expect.
    """

    file_path: str
    line_start: int
    line_end: int
    snippet: str = field(default="", compare=False)
    col_start: int | None = field(default=None, compare=False)
    col_end: int | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if self.line_start < 1:
            raise ValueError(f"line_start must be 1-based, got {self.line_start}")
        if self.line_end < self.line_start:
            raise ValueError(f"line_end ({self.line_end}) precedes line_start ({self.line_start})")

    @property
    def is_single_line(self) -> bool:
        return self.line_start == self.line_end

    def __str__(self) -> str:
        """``src/api/users.ts:12`` or ``src/api/users.ts:12-18``."""
        if self.is_single_line:
            return f"{self.file_path}:{self.line_start}"
        return f"{self.file_path}:{self.line_start}-{self.line_end}"


@dataclass(frozen=True, slots=True)
class SourceFile:
    """A file read into memory, ready to parse."""

    relative_path: str
    text: str
    lines: tuple[str, ...]

    @property
    def data(self) -> bytes:
        """UTF-8 bytes, which is what Tree-sitter parses."""
        return self.text.encode("utf-8")

    @property
    def suffix(self) -> str:
        return Path(self.relative_path).suffix.lower()

    def location(
        self,
        line_start: int,
        line_end: int | None = None,
        *,
        col_start: int | None = None,
        col_end: int | None = None,
    ) -> SourceLocation:
        """Build a location in this file, capturing the snippet.

        Line numbers are clamped to the file, so an off-by-one from a parser
        cannot raise while reporting a finding.
        """
        total = max(len(self.lines), 1)
        start = min(max(line_start, 1), total)
        end = min(max(line_end if line_end is not None else start, start), total)
        return SourceLocation(
            file_path=self.relative_path,
            line_start=start,
            line_end=end,
            snippet=self.snippet(start, end),
            col_start=col_start,
            col_end=col_end,
        )

    def snippet(self, line_start: int, line_end: int) -> str:
        """The source text for a line range, truncated and dedented."""
        selected = self.lines[line_start - 1 : line_end]
        if len(selected) > MAX_SNIPPET_LINES:
            selected = (*selected[:MAX_SNIPPET_LINES], "…")
        # Strip the common indent so a snippet from deep inside a function
        # does not render as a thin column on the right.
        body = [line for line in selected if line.strip()]
        indent = min((len(line) - len(line.lstrip()) for line in body), default=0)
        return "\n".join(line[indent:] if line.strip() else "" for line in selected).rstrip()


def load_source_file(root: Path, path: Path) -> SourceFile | None:
    """Read ``path`` relative to ``root``. Returns None if unreadable.

    Undecodable bytes are replaced rather than raising: a repository with one
    mis-encoded file should still be analysable.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = path.name
    return SourceFile(
        relative_path=relative,
        text=text,
        lines=tuple(text.splitlines()),
    )


def iter_source_files(
    root: Path,
    suffixes: frozenset[str] | set[str],
    *,
    max_bytes: int = 2 * 1024 * 1024,
) -> Iterator[SourceFile]:
    """Yield readable source files under ``root`` with a matching suffix.

    Ignored directories (``node_modules``, ``.git``, build output) are pruned,
    reusing the single policy defined in :mod:`app.services.archive` so that
    what gets analysed matches what got imported.

    Files above ``max_bytes`` are skipped: a 5 MB generated bundle or a vendored
    minified library is not hand-written source, and parsing one costs seconds.
    """
    from app.services.archive import is_ignored_path

    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            try:
                relative = entry.relative_to(root).as_posix()
            except ValueError:  # pragma: no cover - defensive
                continue
            if entry.is_dir():
                if not is_ignored_path(f"{relative}/"):
                    stack.append(entry)
                continue
            if entry.suffix.lower() not in suffixes or is_ignored_path(relative):
                continue
            try:
                if entry.stat().st_size > max_bytes:
                    continue
            except OSError:
                continue
            source = load_source_file(root, entry)
            if source is not None:
                yield source
