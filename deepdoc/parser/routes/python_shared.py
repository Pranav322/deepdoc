"""Shared Python route-detection helpers."""

from __future__ import annotations

import re


def find_following_python_handler(
    lines: list[str], start_line: int, *, limit: int = 5
) -> tuple[str, int]:
    """Find the next Python function definition after a decorator block."""
    for idx in range(start_line, min(start_line + limit, len(lines))):
        line = lines[idx].strip()
        if line.startswith(("def ", "async def ")):
            fn_match = re.match(r"(?:async\s+)?def\s+(\w+)\s*\(", line)
            if fn_match:
                return fn_match.group(1), idx
            break
    return "", -1


def extract_inline_python_docstring(lines: list[str], function_line_idx: int) -> str:
    """Read a simple one-line docstring immediately after a function definition."""
    next_idx = function_line_idx + 1
    if 0 <= next_idx < len(lines):
        next_line = lines[next_idx].strip()
        if next_line.startswith(('"""', "'''")):
            return next_line.strip("\"' ")[:200]
    return ""
