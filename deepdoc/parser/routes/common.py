"""Framework-agnostic helpers for route detection."""

from __future__ import annotations

import re

from .base import APIEndpoint


def dedupe_endpoints(endpoints: list[APIEndpoint]) -> list[APIEndpoint]:
    """Keep the first endpoint for each method/path/line combination."""
    deduped: list[APIEndpoint] = []
    seen: set[str] = set()
    for ep in endpoints:
        key = f"{ep.method}:{ep.path}:{ep.line}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ep)
    return deduped


def line_number_for_offset(content: str, offset: int) -> int:
    return content[:offset].count("\n") + 1


def extract_balanced_segment(
    content: str, start_idx: int, open_char: str = "(", close_char: str = ")"
) -> str:
    """Return the balanced segment beginning at start_idx, including delimiters."""
    if start_idx < 0 or start_idx >= len(content) or content[start_idx] != open_char:
        return ""

    depth = 0
    quote = ""
    escape = False
    for idx in range(start_idx, len(content)):
        ch = content[idx]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
            continue
        if ch in {'"', "'", "`"}:
            quote = ch
            continue
        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return content[start_idx : idx + 1]
    return ""


def split_top_level_args(text: str) -> list[str]:
    """Split a comma-delimited argument list, ignoring nested structures."""
    args: list[str] = []
    buf: list[str] = []
    stack: list[str] = []
    quote = ""
    escape = False

    for ch in text:
        if quote:
            buf.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
            continue

        if ch in {'"', "'", "`"}:
            quote = ch
            buf.append(ch)
            continue

        if ch in "([{":
            stack.append(ch)
            buf.append(ch)
            continue
        if ch in ")]}":
            if stack:
                stack.pop()
            buf.append(ch)
            continue
        if ch == "," and not stack:
            arg = "".join(buf).strip()
            if arg:
                args.append(arg)
            buf = []
            continue
        buf.append(ch)

    tail = "".join(buf).strip()
    if tail:
        args.append(tail)
    return args


def parse_string_arg(arg: str) -> str | None:
    stripped = arg.strip()
    if (
        len(stripped) >= 2
        and stripped[0] in {'"', "'", "`"}
        and stripped[-1] == stripped[0]
    ):
        return stripped[1:-1]
    if (
        len(stripped) >= 3
        and stripped[0] in {"r", "u"}
        and stripped[1] in {'"', "'"}
        and stripped[-1] == stripped[1]
    ):
        return stripped[2:-1]
    return None


def join_route_path(*parts: str) -> str:
    cleaned = [p.strip() for p in parts if p and p.strip()]
    if not cleaned:
        return "/"
    joined = "/" + "/".join(part.strip("/") for part in cleaned if part.strip("/"))
    return re.sub(r"/+", "/", joined) or "/"
