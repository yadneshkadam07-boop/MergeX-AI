"""Robust Code Patch Engine for MergeX AI automated remediations.

Handles whitespace-insensitive, indentation-preserving code replacements and
new missing file creation for automated pull requests and local diffs.
"""

from __future__ import annotations

import re


def detect_newline(content: str) -> str:
    """Detect predominant line endings in content."""
    if "\r\n" in content:
        return "\r\n"
    return "\n"


def get_leading_indent(line: str) -> str:
    """Extract leading whitespace/indentation from a line."""
    match = re.match(r"^([ \t]*)", line)
    return match.group(1) if match else ""


def reindent_block(block: str, target_indent: str) -> str:
    """Reindent a block of text to match target_indent while preserving relative indentation."""
    lines = block.split("\n")
    if not lines:
        return block

    # Find the minimum indentation across non-empty lines in the source block
    non_empty = [l for l in lines if l.strip()]
    if not non_empty:
        return block

    base_indent = len(get_leading_indent(non_empty[0]))
    for l in non_empty[1:]:
        curr = len(get_leading_indent(l))
        if curr < base_indent:
            base_indent = curr

    reindented: list[str] = []
    for l in lines:
        if not l.strip():
            reindented.append("")
        else:
            curr_indent = get_leading_indent(l)
            stripped_content = l[len(curr_indent) :]
            extra_indent = curr_indent[base_indent:] if len(curr_indent) >= base_indent else ""
            reindented.append(f"{target_indent}{extra_indent}{stripped_content}")

    return "\n".join(reindented)


def apply_code_patch(
    source_content: str,
    fix_before: str | None,
    fix_after: str,
    *,
    target_line: int | None = None,
) -> tuple[str, bool]:
    """Apply a code fix patch to source_content with whitespace and indentation tolerance.

    Returns:
        tuple[str, bool]: (updated_content, modified_flag)
    """
    if not source_content:
        return fix_after, True

    if not fix_after:
        return source_content, False

    newline = detect_newline(source_content)
    norm_content = source_content.replace("\r\n", "\n")
    norm_before = (fix_before or "").replace("\r\n", "\n")
    norm_after = fix_after.replace("\r\n", "\n")

    # 1. Exact Substring Match
    if norm_before and norm_before in norm_content:
        updated = norm_content.replace(norm_before, norm_after, 1)
        return updated.replace("\n", newline), True

    # 2. Trimmed Substring Match
    trimmed_before = norm_before.strip()
    if trimmed_before and trimmed_before in norm_content:
        idx = norm_content.find(trimmed_before)
        line_start = norm_content.rfind("\n", 0, idx) + 1
        indent = get_leading_indent(norm_content[line_start:idx])
        adjusted_after = reindent_block(norm_after, indent) if indent else norm_after
        updated = norm_content[:line_start] + adjusted_after + norm_content[idx + len(trimmed_before) :]
        return updated.replace("\n", newline), True

    # 3. Line-by-Line Whitespace/Indentation Insensitive Matching
    content_lines = norm_content.split("\n")
    before_lines = norm_before.split("\n")
    stripped_before = [l.strip() for l in before_lines if l.strip()]

    if stripped_before:
        m = len(stripped_before)
        best_match_idx = -1
        min_dist = float("inf")

        for i in range(len(content_lines) - m + 1):
            window = [content_lines[i + j].strip() for j in range(m)]
            if window == stripped_before:
                dist = abs((i + 1) - target_line) if target_line else i
                if dist < min_dist:
                    min_dist = dist
                    best_match_idx = i

        if best_match_idx >= 0:
            first_line = content_lines[best_match_idx]
            indent = get_leading_indent(first_line)
            reindented_after = reindent_block(norm_after, indent)

            new_lines = (
                content_lines[:best_match_idx]
                + reindented_after.split("\n")
                + content_lines[best_match_idx + m :]
            )
            return "\n".join(new_lines).replace("\n", newline), True

    # 4. Target Line Fallback
    if target_line and 1 <= target_line <= len(content_lines):
        idx = target_line - 1
        indent = get_leading_indent(content_lines[idx])
        reindented_after = reindent_block(norm_after, indent)
        new_lines = (
            content_lines[:idx]
            + reindented_after.split("\n")
            + content_lines[idx + 1 :]
        )
        return "\n".join(new_lines).replace("\n", newline), True

    # 5. Fallback: if source was completely replaced or cannot match before
    return source_content, False


def resolve_target_file_path(
    file_path: str | None,
    rule_id: str | None = None,
    category: str | None = None,
) -> str:
    """Resolve target file path, inferring filenames for new file creation rules."""
    if file_path and file_path.strip() and file_path.strip().lower() != "project tree":
        return file_path.strip()

    r_id = (rule_id or "").upper()
    if "DEP-002" in r_id:
        return "package-lock.json"
    if "SEC-004" in r_id:
        return ".env.example"
    if "DEP-001" in r_id:
        return "Dockerfile"

    return "remediation.patch"
