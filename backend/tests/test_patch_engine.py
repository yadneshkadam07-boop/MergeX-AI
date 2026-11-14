"""Unit tests for the Patch Engine (whitespace-insensitive replacement & file resolution)."""

import pytest
from app.services.patch_engine import (
    apply_code_patch,
    detect_newline,
    get_leading_indent,
    reindent_block,
    resolve_target_file_path,
)


def test_detect_newline():
    assert detect_newline("hello\r\nworld") == "\r\n"
    assert detect_newline("hello\nworld") == "\n"


def test_get_leading_indent():
    assert get_leading_indent("    const x = 1;") == "    "
    assert get_leading_indent("\t\tlet y = 2;") == "\t\t"
    assert get_leading_indent("z = 3") == ""


def test_reindent_block():
    block = "const a = 1;\n  const b = 2;"
    reindented = reindent_block(block, "    ")
    assert reindented == "    const a = 1;\n      const b = 2;"


def test_apply_code_patch_exact():
    source = 'function test() {\n  return "/api/users";\n}'
    before = 'return "/api/users";'
    after = 'return "/api/v1/users";'

    result, modified = apply_code_patch(source, before, after)
    assert modified is True
    assert 'return "/api/v1/users";' in result
    assert "function test() {" in result


def test_apply_code_patch_preserves_crlf():
    source = "line 1\r\nline 2\r\nline 3\r\n"
    before = "line 2"
    after = "line 2 patched"

    result, modified = apply_code_patch(source, before, after)
    assert modified is True
    assert "\r\n" in result
    assert "line 2 patched" in result


def test_apply_code_patch_indentation_insensitive():
    # Source file has 8 spaces of indentation
    source = (
        "class Controller {\n"
        "    async handle() {\n"
        "        const res = await api.get('/user');\n"
        "        return res;\n"
        "    }\n"
        "}"
    )
    # Rule engine suggested fix with 0 indentation
    before = "const res = await api.get('/user');"
    after = "const res = await api.get('/users');"

    result, modified = apply_code_patch(source, before, after)
    assert modified is True
    # The patch engine should retain the 8-space indentation!
    assert "        const res = await api.get('/users');" in result


def test_apply_code_patch_multiline_block():
    source = (
        "function connect() {\n"
        "    const opts = {\n"
        "        useNewUrlParser: true,\n"
        "        useUnifiedTopology: true,\n"
        "    };\n"
        "    return opts;\n"
        "}"
    )
    # Before has 2 spaces, after has 2 spaces
    before = "const opts = {\n  useNewUrlParser: true,\n  useUnifiedTopology: true,\n};"
    after = "const opts = {\n  autoIndex: false,\n};"

    result, modified = apply_code_patch(source, before, after)
    assert modified is True
    assert "    const opts = {\n      autoIndex: false,\n    };" in result


def test_apply_code_patch_target_line_fallback():
    source = "line 1\nline 2\nline 3\nline 4"
    before = "completely unmatchable line"
    after = "line 3 modified"

    result, modified = apply_code_patch(source, before, after, target_line=3)
    assert modified is True
    assert "line 3 modified" in result
    assert "line 1\nline 2\nline 3 modified\nline 4" == result


def test_apply_code_patch_new_file_empty_source():
    source = ""
    after = 'PORT=8000\nDATABASE_URL="postgresql://localhost:5432/app"\n'

    result, modified = apply_code_patch(source, None, after)
    assert modified is True
    assert result == after


def test_resolve_target_file_path():
    assert resolve_target_file_path("src/index.ts") == "src/index.ts"
    assert resolve_target_file_path("", "MX-DEP-002") == "package-lock.json"
    assert resolve_target_file_path(None, "MX-SEC-004") == ".env.example"
    assert resolve_target_file_path("Project tree", "MX-DEP-001") == "Dockerfile"
    assert resolve_target_file_path(None, "MX-GENERIC") == "remediation.patch"
