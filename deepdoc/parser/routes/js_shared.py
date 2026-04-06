"""Shared JavaScript/TypeScript route-detection helpers."""

from __future__ import annotations

import re

from .common import (
    extract_balanced_segment,
    join_route_path,
    parse_string_arg,
    split_top_level_args,
)

JS_ROUTE_CALL = re.compile(
    r"""\b(\w+)\s*\.\s*"""
    r"""(get|post|put|patch|delete|all|options|head)\s*\(""",
    re.IGNORECASE | re.MULTILINE,
)

JS_ROUTE_CHAIN = re.compile(
    r"""\b(\w+)\s*\.\s*route\s*\(""",
    re.IGNORECASE | re.MULTILINE,
)

JS_USE_CALL = re.compile(
    r"""\b(\w+)\s*\.\s*use\s*\(""",
    re.IGNORECASE | re.MULTILINE,
)

FASTIFY_REGISTER_CALL = re.compile(
    r"""\b(\w+)\s*\.\s*register\s*\(""",
    re.IGNORECASE | re.MULTILINE,
)

FASTIFY_PLUGIN_FUNCTION = re.compile(
    r"""(?:async\s+)?function\s+(\w+)\s*\(\s*(\w+)""",
    re.IGNORECASE,
)

FASTIFY_PLUGIN_ARROW = re.compile(
    r"""const\s+(\w+)\s*=\s*(?:async\s*)?"""
    r"""(?:function\s*\(\s*(\w+)"""
    r"""|\(\s*(\w+)\s*(?:,|\)))""",
    re.IGNORECASE,
)

FASTIFY_ROUTE_CALL = re.compile(
    r"""\b(\w+)\s*\.\s*route\s*\(""",
    re.IGNORECASE | re.MULTILINE,
)

FASTIFY_ADDHOOK_CALL = re.compile(
    r"""\b(\w+)\s*\.\s*addHook\s*\(""",
    re.IGNORECASE | re.MULTILINE,
)


def extract_js_mounts(content: str) -> dict[str, list[tuple[str, str]]]:
    mounts: dict[str, list[tuple[str, str]]] = {}
    for match in JS_USE_CALL.finditer(content):
        parent = match.group(1)
        call_text = extract_balanced_segment(content, match.end() - 1)
        if not call_text:
            continue
        args = split_top_level_args(call_text[1:-1])
        if len(args) < 2:
            continue
        prefix = parse_string_arg(args[0])
        child_match = re.match(r"""(\w+)""", args[1].strip())
        if prefix is None or not child_match:
            continue
        mounts.setdefault(child_match.group(1), []).append((parent, prefix))
    return mounts


def resolve_js_prefixes(
    obj: str,
    mounts: dict[str, list[tuple[str, str]]],
    memo: dict[str, list[str]] | None = None,
    stack: set[str] | None = None,
) -> list[str]:
    if memo is None:
        memo = {}
    if stack is None:
        stack = set()
    if obj in memo:
        return memo[obj]
    if obj in stack:
        return [""]
    stack.add(obj)

    links = mounts.get(obj, [])
    if not links:
        memo[obj] = [""]
        stack.discard(obj)
        return memo[obj]

    prefixes: list[str] = []
    for parent, prefix in links:
        for parent_prefix in resolve_js_prefixes(parent, mounts, memo, stack):
            prefixes.append(join_route_path(parent_prefix, prefix))

    stack.discard(obj)
    memo[obj] = prefixes or [""]
    return memo[obj]


def extract_js_handler_details(args: list[str]) -> dict[str, list[str] | str]:
    identifiers: list[str] = []
    for arg in args:
        stripped = arg.strip()
        if not stripped or stripped.startswith("{") or stripped.startswith("["):
            continue
        if "=>" in stripped or stripped.startswith("function"):
            identifiers.append("inline_handler")
            continue
        match = re.match(r"""(\w+(?:\.\w+)*)""", stripped)
        if match:
            identifiers.append(match.group(1))

    if not identifiers:
        return {"handler": "", "middleware": []}
    if len(identifiers) == 1:
        return {"handler": identifiers[0], "middleware": []}
    return {"handler": identifiers[-1], "middleware": identifiers[:-1]}


def extract_fastify_plugin_aliases(content: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for match in FASTIFY_PLUGIN_FUNCTION.finditer(content):
        aliases[match.group(1)] = match.group(2)
    for match in FASTIFY_PLUGIN_ARROW.finditer(content):
        aliases[match.group(1)] = match.group(2) or match.group(3) or "instance"
    return aliases


def extract_fastify_mounts(
    content: str, plugin_aliases: dict[str, str]
) -> dict[str, list[tuple[str, str]]]:
    mounts: dict[str, list[tuple[str, str]]] = {}
    for match in FASTIFY_REGISTER_CALL.finditer(content):
        parent = match.group(1)
        call_text = extract_balanced_segment(content, match.end() - 1)
        if not call_text:
            continue
        args = split_top_level_args(call_text[1:-1])
        if not args:
            continue
        plugin_name_match = re.match(r"""(\w+)""", args[0].strip())
        if not plugin_name_match:
            continue
        plugin_name = plugin_name_match.group(1)
        child_alias = plugin_aliases.get(plugin_name)
        if not child_alias:
            continue
        prefix = ""
        for arg in args[1:]:
            prefix_match = re.search(r"""prefix\s*:\s*['\"]([^'\"]+)['\"]""", arg)
            if prefix_match:
                prefix = prefix_match.group(1)
                break
        mounts.setdefault(child_alias, []).append((parent, prefix))
    return mounts


def extract_fastify_schema(content: str, start_pos: int) -> dict[str, str]:
    """Try to extract Fastify JSON schema from route options."""
    region = content[start_pos : start_pos + 1000]
    schema: dict[str, str] = {}
    body_match = re.search(r"body\s*:\s*(\{.*?\})", region, re.DOTALL)
    if body_match:
        schema["body"] = body_match.group(1)[:200]
    resp_match = re.search(r"response\s*:\s*(\{.*?\})", region, re.DOTALL)
    if resp_match:
        schema["response"] = resp_match.group(1)[:200]
    return schema


def extract_fastify_schema_from_args(args: list[str]) -> dict[str, str]:
    for arg in args:
        stripped = arg.strip()
        if stripped.startswith("{"):
            return extract_fastify_schema(stripped, 0)
    return {}


def extract_fastify_hooks(text: str) -> list[str]:
    """Extract Fastify hook/preHandler identifiers from route options."""
    hooks: list[str] = []
    for field in ("preHandler", "onRequest", "preValidation", "preParsing"):
        pattern = re.compile(rf"""{field}\s*:\s*(\[[^\]]*\]|[^,\n}}]+)""")
        for match in pattern.finditer(text):
            value = match.group(1).strip()
            for name in _extract_identifier_list(value):
                if name not in hooks:
                    hooks.append(name)
    return hooks


def extract_fastify_hooks_from_args(args: list[str]) -> list[str]:
    for arg in args:
        stripped = arg.strip()
        if stripped.startswith("{"):
            return extract_fastify_hooks(stripped)
    return []


def extract_fastify_add_hook_map(content: str) -> dict[str, list[str]]:
    """Extract Fastify addHook registrations keyed by instance alias."""
    hook_map: dict[str, list[str]] = {}
    for match in FASTIFY_ADDHOOK_CALL.finditer(content):
        obj = match.group(1)
        call_text = extract_balanced_segment(content, match.end() - 1)
        if not call_text:
            continue
        args = split_top_level_args(call_text[1:-1])
        if len(args) < 2:
            continue
        hook_name = parse_string_arg(args[0])
        if hook_name not in {"preHandler", "onRequest", "preValidation", "preParsing"}:
            continue
        names = _extract_identifier_list(args[1])
        if not names:
            continue
        existing = hook_map.setdefault(obj, [])
        for name in names:
            if name not in existing:
                existing.append(name)
    return hook_map


def _extract_identifier_list(value: str) -> list[str]:
    identifiers: list[str] = []
    if value.startswith("[") and value.endswith("]"):
        parts = split_top_level_args(value[1:-1])
    else:
        parts = [value]

    for part in parts:
        stripped = part.strip()
        if not stripped:
            continue
        if stripped.startswith("function") or "=>" in stripped:
            name = "inline_hook"
        else:
            name_match = re.search(r"""(\w+(?:\.\w+)*)""", stripped)
            if not name_match:
                continue
            name = name_match.group(1)
        if name not in identifiers:
            identifiers.append(name)
    return identifiers
