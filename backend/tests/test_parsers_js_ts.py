"""Tree-sitter JS/TS parsing: dialect selection, queries, literal reading."""

from __future__ import annotations

import pytest

from app.services.parsers.base import SourceFile
from app.services.parsers.js_ts_parser import (
    Dialect,
    ParsedModule,
    dialect_for,
    node_text,
    parse_source,
    string_literal_value,
)


def make_file(text: str, path: str = "src/app.ts") -> SourceFile:
    return SourceFile(relative_path=path, text=text, lines=tuple(text.splitlines()))


def parse(text: str, path: str = "src/app.ts") -> ParsedModule:
    module = parse_source(make_file(text, path))
    assert module is not None
    return module


class TestDialectSelection:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("a.js", Dialect.JAVASCRIPT),
            ("a.jsx", Dialect.JAVASCRIPT),
            ("a.mjs", Dialect.JAVASCRIPT),
            ("a.cjs", Dialect.JAVASCRIPT),
            ("a.ts", Dialect.TYPESCRIPT),
            ("a.mts", Dialect.TYPESCRIPT),
            ("a.tsx", Dialect.TSX),
        ],
    )
    def test_maps_extension_to_grammar(self, path: str, expected: Dialect) -> None:
        assert dialect_for(path) is expected

    @pytest.mark.parametrize("path", ["a.py", "a.md", "a", "a.json"])
    def test_rejects_non_js_files(self, path: str) -> None:
        assert dialect_for(path) is None

    def test_parse_returns_none_for_a_non_js_file(self) -> None:
        assert parse_source(make_file("x = 1", "a.py")) is None

    def test_tsx_grammar_parses_jsx(self) -> None:
        """The TypeScript grammar would mangle this; TSX is a separate grammar."""
        module = parse('const a = <div className="x">hi</div>;\n', "a.tsx")

        assert not module.has_syntax_errors

    def test_typescript_grammar_parses_type_assertions(self) -> None:
        """`<T>x` is a cast in .ts and would look like JSX to the TSX grammar."""
        module = parse("const a = <string>value;\n", "a.ts")

        assert not module.has_syntax_errors


class TestErrorTolerance:
    def test_a_syntax_error_is_reported_not_raised(self) -> None:
        """An AI-generated repo with one broken file must still be analysable."""
        module = parse("function f( {\n  const x = ;\n}\n")

        assert module.has_syntax_errors

    def test_the_rest_of_a_broken_file_is_still_queryable(self) -> None:
        module = parse('const a = ;\nfetch("/api/users");\n')

        matches = module.query("(call_expression function: (_) @callee) @call")

        assert any(module.text_of(m["callee"][0]) == "fetch" for m in matches)


class TestQueries:
    def test_returns_captures_per_match(self) -> None:
        module = parse('fetch("/a");\naxios.get("/b");\n')

        matches = module.query("(call_expression function: (_) @callee) @call")

        assert [module.text_of(m["callee"][0]) for m in matches] == ["fetch", "axios.get"]

    def test_results_are_in_source_order(self) -> None:
        """Deterministic output matters: findings are compared across runs."""
        module = parse('fetch("/z");\nfetch("/a");\nfetch("/m");\n')

        matches = module.query("(call_expression arguments: (arguments (string) @arg))")
        values = [string_literal_value(module.source, m["arg"][0]) for m in matches]

        assert values == ["/z", "/a", "/m"]

    def test_no_matches_yields_an_empty_list(self) -> None:
        assert parse("const a = 1;\n").query("(class_declaration) @c") == []


class TestLocations:
    def test_line_numbers_are_one_based(self) -> None:
        module = parse('const a = 1;\nfetch("/api/users");\n')

        match = module.query("(call_expression) @call")[0]
        location = module.location_of(match["call"][0])

        assert location.line_start == 2
        assert location.file_path == "src/app.ts"

    def test_a_multiline_call_spans_its_lines(self) -> None:
        module = parse('axios.get(\n  "/api/users",\n  { timeout: 1 },\n);\n')

        location = module.location_of(module.query("(call_expression) @call")[0]["call"][0])

        assert location.line_start == 1
        assert location.line_end == 4

    def test_the_snippet_is_the_real_source(self) -> None:
        module = parse('const a = 1;\nfetch("/api/users");\n')

        location = module.location_of(module.query("(call_expression) @call")[0]["call"][0])

        assert location.snippet == 'fetch("/api/users");'

    def test_node_text_is_exact(self) -> None:
        module = parse('axios.get("/api/users");\n')

        callee = module.query("(call_expression function: (_) @callee)")[0]["callee"][0]

        assert node_text(module.source, callee) == "axios.get"


class TestStringLiterals:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ('f("/api/users")', "/api/users"),
            ("f('/api/users')", "/api/users"),
            ("f(`/api/users`)", "/api/users"),
        ],
    )
    def test_reads_plain_strings(self, source: str, expected: str) -> None:
        module = parse(f"{source};\n")

        argument = module.query("(call_expression arguments: (arguments . (_) @arg))")[0]["arg"][0]

        assert string_literal_value(module.source, argument) == expected

    def test_preserves_template_substitutions(self) -> None:
        """`${id}` must survive so the path normaliser can see a parameter.

        Dropping it would collapse `/users/${id}` to `/users/`, which matches
        a different route entirely.
        """
        module = parse("f(`/api/users/${id}/posts`);\n")

        argument = module.query("(call_expression arguments: (arguments . (_) @arg))")[0]["arg"][0]

        assert string_literal_value(module.source, argument) == "/api/users/${id}/posts"

    def test_handles_several_substitutions(self) -> None:
        module = parse("f(`/a/${x}/b/${y}`);\n")

        argument = module.query("(call_expression arguments: (arguments . (_) @arg))")[0]["arg"][0]

        assert string_literal_value(module.source, argument) == "/a/${x}/b/${y}"

    @pytest.mark.parametrize(
        "source",
        [
            "f(url)",
            "f(BASE + path)",
            "f(getUrl())",
            "f(123)",
        ],
    )
    def test_returns_none_for_non_literals(self, source: str) -> None:
        """A value that needs execution to know is not statically known."""
        module = parse(f"{source};\n")

        argument = module.query("(call_expression arguments: (arguments . (_) @arg))")[0]["arg"][0]

        assert string_literal_value(module.source, argument) is None
