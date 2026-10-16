"""Source locations, snippets and file discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.parsers.base import (
    MAX_SNIPPET_LINES,
    SourceFile,
    SourceLocation,
    iter_source_files,
    load_source_file,
)


def make_file(text: str, path: str = "src/app.ts") -> SourceFile:
    return SourceFile(relative_path=path, text=text, lines=tuple(text.splitlines()))


class TestSourceLocation:
    def test_single_line_renders_compactly(self) -> None:
        location = SourceLocation(file_path="a.ts", line_start=7, line_end=7)

        assert str(location) == "a.ts:7"
        assert location.is_single_line

    def test_range_renders_with_both_ends(self) -> None:
        location = SourceLocation(file_path="a.ts", line_start=7, line_end=9)

        assert str(location) == "a.ts:7-9"
        assert not location.is_single_line

    @pytest.mark.parametrize("line_start", [0, -1])
    def test_rejects_zero_based_lines(self, line_start: int) -> None:
        """Editors and the issues table are both 1-based."""
        with pytest.raises(ValueError, match="1-based"):
            SourceLocation(file_path="a.ts", line_start=line_start, line_end=5)

    def test_rejects_an_inverted_range(self) -> None:
        with pytest.raises(ValueError, match="precedes"):
            SourceLocation(file_path="a.ts", line_start=9, line_end=4)

    def test_equality_ignores_the_snippet(self) -> None:
        """Two references to the same place are the same location."""
        first = SourceLocation(file_path="a.ts", line_start=1, line_end=1, snippet="x")
        second = SourceLocation(file_path="a.ts", line_start=1, line_end=1, snippet="y")

        assert first == second

    def test_locations_sort_by_file_then_line(self) -> None:
        unsorted = [
            SourceLocation(file_path="b.ts", line_start=1, line_end=1),
            SourceLocation(file_path="a.ts", line_start=9, line_end=9),
            SourceLocation(file_path="a.ts", line_start=2, line_end=2),
        ]

        assert [str(location) for location in sorted(unsorted)] == ["a.ts:2", "a.ts:9", "b.ts:1"]


class TestSnippets:
    def test_captures_the_requested_lines(self) -> None:
        source = make_file("one\ntwo\nthree\nfour")

        assert source.snippet(2, 3) == "two\nthree"

    def test_dedents_to_the_common_indent(self) -> None:
        """A snippet from inside a function should not render as a thin column."""
        source = make_file("function f() {\n        const a = 1;\n        return a;\n}")

        assert source.snippet(2, 3) == "const a = 1;\nreturn a;"

    def test_truncates_a_long_range(self) -> None:
        source = make_file("\n".join(f"line{index}" for index in range(40)))

        snippet = source.snippet(1, 40)

        assert len(snippet.splitlines()) == MAX_SNIPPET_LINES + 1
        assert snippet.endswith("…")

    def test_blank_lines_are_preserved_not_dedented(self) -> None:
        source = make_file("    a = 1\n\n    b = 2")

        assert source.snippet(1, 3) == "a = 1\n\nb = 2"


class TestLocationClamping:
    def test_clamps_a_line_past_the_end_of_the_file(self) -> None:
        """An off-by-one in a parser must not crash a report."""
        source = make_file("one\ntwo")

        location = source.location(99)

        assert location.line_start == 2
        assert location.line_end == 2

    def test_clamps_a_zero_line(self) -> None:
        location = make_file("one\ntwo").location(0)

        assert location.line_start == 1

    def test_end_before_start_is_corrected(self) -> None:
        location = make_file("one\ntwo\nthree").location(3, 1)

        assert (location.line_start, location.line_end) == (3, 3)

    def test_an_empty_file_still_yields_a_valid_location(self) -> None:
        location = make_file("").location(1)

        assert location.line_start == 1
        assert location.snippet == ""


class TestLoadSourceFile:
    def test_reads_a_file_relative_to_the_root(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        target = tmp_path / "src" / "app.ts"
        target.write_text("export const x = 1;\n", encoding="utf-8")

        source = load_source_file(tmp_path, target)

        assert source is not None
        assert source.relative_path == "src/app.ts"
        assert source.suffix == ".ts"
        assert source.data == b"export const x = 1;\n"

    def test_replaces_undecodable_bytes(self, tmp_path: Path) -> None:
        """One mis-encoded file must not fail the repository."""
        target = tmp_path / "weird.py"
        target.write_bytes(b"x = '\xff\xfe'\n")

        source = load_source_file(tmp_path, target)

        assert source is not None
        assert "x =" in source.text

    def test_returns_none_for_a_missing_file(self, tmp_path: Path) -> None:
        assert load_source_file(tmp_path, tmp_path / "nope.py") is None


class TestIterSourceFiles:
    def test_yields_only_matching_suffixes(self, tmp_path: Path) -> None:
        (tmp_path / "a.ts").write_text("", encoding="utf-8")
        (tmp_path / "b.py").write_text("", encoding="utf-8")
        (tmp_path / "c.md").write_text("", encoding="utf-8")

        found = {source.relative_path for source in iter_source_files(tmp_path, {".ts", ".py"})}

        assert found == {"a.ts", "b.py"}

    def test_prunes_ignored_directories(self, tmp_path: Path) -> None:
        """Reuses the import-time ignore policy, so analysis sees what was imported."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.ts").write_text("", encoding="utf-8")
        for ignored in ("node_modules", ".git", "dist", "__pycache__"):
            directory = tmp_path / ignored
            directory.mkdir()
            (directory / "x.ts").write_text("", encoding="utf-8")

        found = {source.relative_path for source in iter_source_files(tmp_path, {".ts"})}

        assert found == {"src/app.ts"}

    def test_skips_oversized_files(self, tmp_path: Path) -> None:
        """A generated bundle is not hand-written source."""
        (tmp_path / "small.ts").write_text("x", encoding="utf-8")
        (tmp_path / "huge.ts").write_text("x" * 5000, encoding="utf-8")

        found = {
            source.relative_path for source in iter_source_files(tmp_path, {".ts"}, max_bytes=1000)
        }

        assert found == {"small.ts"}

    def test_is_deterministic(self, tmp_path: Path) -> None:
        """Extraction output order must be stable across runs."""
        for name in ("c.ts", "a.ts", "b.ts"):
            (tmp_path / name).write_text("", encoding="utf-8")

        first = [source.relative_path for source in iter_source_files(tmp_path, {".ts"})]
        second = [source.relative_path for source in iter_source_files(tmp_path, {".ts"})]

        assert first == second

    def test_an_empty_tree_yields_nothing(self, tmp_path: Path) -> None:
        assert list(iter_source_files(tmp_path, {".ts"})) == []
