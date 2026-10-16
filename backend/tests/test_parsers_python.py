"""Python parsing helpers, built on the standard library's ast."""

from __future__ import annotations

import ast

import pytest

from app.services.parsers.base import SourceFile
from app.services.parsers.python_parser import (
    ParsedPythonModule,
    SyntaxErrorInfo,
    call_keyword,
    call_positional,
    decorator_calls,
    dotted_name,
    literal_value,
    parse_source,
    string_items,
)


def make_file(text: str, path: str = "app/main.py") -> SourceFile:
    return SourceFile(relative_path=path, text=text, lines=tuple(text.splitlines()))


def parse(text: str, path: str = "app/main.py") -> ParsedPythonModule:
    result = parse_source(make_file(text, path))
    assert isinstance(result, ParsedPythonModule), result
    return result


def first_call(text: str) -> ast.Call:
    module = parse(text)
    return module.calls()[0]


class TestParsing:
    def test_parses_a_module(self) -> None:
        module = parse("x = 1\n")

        assert isinstance(module.tree, ast.Module)

    def test_returns_none_for_a_non_python_file(self) -> None:
        assert parse_source(make_file("x = 1", "a.ts")) is None

    def test_a_syntax_error_is_returned_not_raised(self) -> None:
        """One unparseable file must not abort a repository's analysis."""
        result = parse_source(make_file("def f(:\n  pass\n"))

        assert isinstance(result, SyntaxErrorInfo)
        assert result.location.line_start == 1
        assert result.message

    def test_a_syntax_error_reports_its_line(self) -> None:
        result = parse_source(make_file("x = 1\ny = 2\ndef f(:\n"))

        assert isinstance(result, SyntaxErrorInfo)
        assert result.location.line_start == 3

    def test_handles_nul_bytes(self) -> None:
        result = parse_source(make_file("x = 1\x00\n"))

        assert isinstance(result, SyntaxErrorInfo)


class TestLocations:
    def test_locations_are_one_based(self) -> None:
        module = parse("x = 1\ndef handler():\n    pass\n")

        function = module.functions()[0]

        assert module.location_of(function).line_start == 2

    def test_a_multiline_node_spans_its_lines(self) -> None:
        module = parse("def handler(\n    a,\n    b,\n):\n    pass\n")

        location = module.location_of(module.functions()[0])

        assert location.line_start == 1
        assert location.line_end == 5

    def test_snippet_matches_the_source(self) -> None:
        module = parse("x = 1\ny = 2\n")

        assign = next(n for n in ast.walk(module.tree) if isinstance(n, ast.Assign))

        assert module.location_of(assign).snippet == "x = 1"


class TestDottedName:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("router.get(1)", "router.get"),
            ("app.routers.users.router.get(1)", "app.routers.users.router.get"),
            ("get(1)", "get"),
        ],
    )
    def test_renders_attribute_chains(self, source: str, expected: str) -> None:
        assert dotted_name(first_call(source).func) == expected

    def test_handles_a_call_in_the_chain(self) -> None:
        """`APIRouter().get` keeps the callee name."""
        assert dotted_name(first_call("APIRouter().get(1)").func) == "APIRouter.get"

    @pytest.mark.parametrize("source", ["items[0].get(1)", "(a or b).get(1)"])
    def test_returns_none_for_dynamic_chains(self, source: str) -> None:
        assert dotted_name(first_call(source).func) is None

    def test_returns_none_for_none(self) -> None:
        assert dotted_name(None) is None


class TestLiteralValue:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [('f("/x")', "/x"), ("f(42)", 42), ("f(True)", True), ("f(1.5)", 1.5)],
    )
    def test_reads_constants(self, source: str, expected: object) -> None:
        assert literal_value(call_positional(first_call(source), 0)) == expected

    def test_merges_implicitly_concatenated_strings(self) -> None:
        """CPython merges these at parse time, which is how multi-line SQL arrives."""
        call = first_call('f("SELECT a " "FROM t " "WHERE x = 1")')

        assert literal_value(call_positional(call, 0)) == "SELECT a FROM t WHERE x = 1"

    @pytest.mark.parametrize("source", ["f(name)", 'f(f"{x}")', "f(a + b)", "f([1])"])
    def test_returns_none_for_runtime_expressions(self, source: str) -> None:
        assert literal_value(call_positional(first_call(source), 0)) is None


class TestCallArguments:
    def test_reads_a_keyword(self) -> None:
        call = first_call('APIRouter(prefix="/api", tags=["x"])')

        assert literal_value(call_keyword(call, "prefix")) == "/api"

    def test_missing_keyword_is_none(self) -> None:
        assert call_keyword(first_call("APIRouter()"), "prefix") is None

    def test_reads_a_positional(self) -> None:
        call = first_call('router.get("/users", response_model=None)')

        assert literal_value(call_positional(call, 0)) == "/users"

    def test_out_of_range_positional_is_none(self) -> None:
        assert call_positional(first_call("f()"), 0) is None

    def test_starred_positional_is_none(self) -> None:
        """`f(*args)` has no knowable positional 0."""
        assert call_positional(first_call("f(*args)"), 0) is None

    def test_string_items_reads_a_list(self) -> None:
        call = first_call('f(methods=["GET", "POST"])')

        assert string_items(call_keyword(call, "methods")) == ["GET", "POST"]

    def test_string_items_skips_non_literals(self) -> None:
        call = first_call('f(methods=["GET", verb])')

        assert string_items(call_keyword(call, "methods")) == ["GET"]

    def test_string_items_of_a_non_list_is_empty(self) -> None:
        assert string_items(call_keyword(first_call('f(methods="GET")'), "methods")) == []


class TestDecorators:
    def test_reads_an_invoked_decorator(self) -> None:
        module = parse('@router.get("/users")\ndef handler():\n    pass\n')

        decorators = decorator_calls(module.functions()[0])

        assert len(decorators) == 1
        name, call, _ = decorators[0]
        assert name == "router.get"
        assert call is not None
        assert literal_value(call_positional(call, 0)) == "/users"

    def test_reads_a_bare_decorator(self) -> None:
        module = parse("@login_required\ndef handler():\n    pass\n")

        name, call, _ = decorator_calls(module.functions()[0])[0]

        assert name == "login_required"
        assert call is None

    def test_reads_stacked_decorators(self) -> None:
        module = parse('@router.get("/a")\n@router.get("/b")\ndef handler():\n    pass\n')

        assert len(decorator_calls(module.functions()[0])) == 2

    def test_an_undecorated_function_has_none(self) -> None:
        module = parse("def handler():\n    pass\n")

        assert decorator_calls(module.functions()[0]) == []


class TestModuleIntrospection:
    def test_finds_async_functions(self) -> None:
        module = parse("async def handler():\n    pass\n")

        assert [f.name for f in module.functions()] == ["handler"]

    def test_finds_nested_functions(self) -> None:
        module = parse("def outer():\n    def inner():\n        pass\n")

        assert sorted(f.name for f in module.functions()) == ["inner", "outer"]

    def test_finds_classes(self) -> None:
        module = parse("class A:\n    pass\nclass B:\n    pass\n")

        assert [c.name for c in module.classes()] == ["A", "B"]

    def test_maps_plain_imports(self) -> None:
        module = parse("import os\nimport os.path as p\n")

        names = module.imported_names()

        assert names["os"] == "os"
        assert names["p"] == "os.path"

    def test_maps_from_imports_with_aliases(self) -> None:
        module = parse("from fastapi import APIRouter as R, Depends\n")

        names = module.imported_names()

        assert names["R"] == "fastapi.APIRouter"
        assert names["Depends"] == "fastapi.Depends"

    def test_maps_relative_imports(self) -> None:
        module = parse("from .routers import users\n")

        assert module.imported_names()["users"] == "routers.users"
