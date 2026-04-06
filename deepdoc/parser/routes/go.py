"""Go route detection."""

from __future__ import annotations

import re

from .base import APIEndpoint, RegisteredRouteDetector, RouteResolverContext
from .common import (
    extract_balanced_segment,
    join_route_path,
    line_number_for_offset,
    parse_string_arg,
    split_top_level_args,
)

GO_ASSIGN_GROUP = re.compile(
    r"""\b(\w+)\s*(?::=|=)\s*(\w+)\s*\.\s*(Group|Route|With)\s*\(""",
    re.IGNORECASE | re.MULTILINE,
)
GO_USE_CALL = re.compile(r"""\b(\w+)\s*\.\s*Use\s*\(""", re.IGNORECASE | re.MULTILINE)
GO_ROUTE_CALL = re.compile(
    r"""\b(\w+)\s*\.\s*(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|Any|Handle|Get|Post|Put|Patch|Delete|All)\s*\(""",
    re.IGNORECASE | re.MULTILINE,
)
GO_WITH_ROUTE_CALL = re.compile(
    r"""\b(\w+)\s*\.\s*With\s*\(""",
    re.IGNORECASE | re.MULTILINE,
)
GO_HANDLEFUNC = re.compile(
    r"""\b(?:http|mux|router|r)\s*\.\s*HandleFunc\s*\(""",
    re.IGNORECASE | re.MULTILINE,
)

ROOT_ROUTE_OBJECTS = {
    "r",
    "router",
    "mux",
    "app",
    "engine",
    "e",
    "server",
}

METHOD_NAME_MAP = {
    "GET": "GET",
    "POST": "POST",
    "PUT": "PUT",
    "PATCH": "PATCH",
    "DELETE": "DELETE",
    "HEAD": "HEAD",
    "OPTIONS": "OPTIONS",
    "ANY": "ANY",
    "ALL": "ANY",
    "HANDLE": "ANY",
}


def detect_go_routes(context: RouteResolverContext) -> list[APIEndpoint]:
    content = context.content
    endpoints: list[APIEndpoint] = []
    alias_state = _build_go_alias_state(content)

    for match in GO_ROUTE_CALL.finditer(content):
        endpoints.extend(
            _route_endpoints_from_call(context, content, match, alias_state)
        )

    for match in GO_WITH_ROUTE_CALL.finditer(content):
        endpoints.extend(
            _route_endpoints_from_with_call(context, content, match, alias_state)
        )

    for match in GO_HANDLEFUNC.finditer(content):
        endpoints.extend(
            _route_endpoints_from_handlefunc(context, content, match, alias_state)
        )

    return endpoints


def _build_go_alias_state(content: str) -> dict[str, dict[str, list[str] | str]]:
    state: dict[str, dict[str, list[str] | str]] = {
        name: {"prefix": "", "middleware": []} for name in ROOT_ROUTE_OBJECTS
    }

    for match in GO_ASSIGN_GROUP.finditer(content):
        alias, parent, method = match.group(1), match.group(2), match.group(3).lower()
        call_text = extract_balanced_segment(content, match.end() - 1)
        if not call_text:
            continue
        args = split_top_level_args(call_text[1:-1])
        parent_state = state.get(parent, {"prefix": "", "middleware": []})
        prefix = str(parent_state.get("prefix", "") or "")
        middleware = list(parent_state.get("middleware", []) or [])

        if method in {"group", "route"}:
            group_path = parse_string_arg(args[0]) if args else None
            if group_path:
                prefix = join_route_path(prefix, group_path)
            middleware.extend(_extract_go_identifier_names(args[1:]))
        elif method == "with":
            middleware.extend(_extract_go_identifier_names(args))

        state[alias] = {
            "prefix": prefix,
            "middleware": _ordered_unique(middleware),
        }

    for match in GO_USE_CALL.finditer(content):
        obj = match.group(1)
        call_text = extract_balanced_segment(content, match.end() - 1)
        if not call_text:
            continue
        args = split_top_level_args(call_text[1:-1])
        if not args:
            continue
        current = state.setdefault(obj, {"prefix": "", "middleware": []})
        current["middleware"] = _ordered_unique(
            list(current.get("middleware", []) or [])
            + _extract_go_identifier_names(args)
        )

    return state


def _route_endpoints_from_call(
    context: RouteResolverContext,
    content: str,
    match: re.Match[str],
    alias_state: dict[str, dict[str, list[str] | str]],
) -> list[APIEndpoint]:
    obj = match.group(1)
    method_name = match.group(2)
    call_text = extract_balanced_segment(content, match.end() - 1)
    if not call_text:
        return []

    args = split_top_level_args(call_text[1:-1])
    if len(args) < 2:
        return []

    route_path = parse_string_arg(args[0])
    if route_path is None:
        return []

    line_num = line_number_for_offset(content, match.start())
    method_tokens = _normalize_go_methods(method_name)
    if method_tokens == ["ANY"]:
        method_tokens = _extract_go_chained_methods(
            content, match.end() - 1 + len(call_text)
        ) or ["ANY"]

    state = alias_state.get(obj, {"prefix": "", "middleware": []})
    details = _extract_go_handler_details(args[1:])
    middleware = _ordered_unique(
        list(state.get("middleware", []) or []) + list(details["middleware"])
    )
    full_path = join_route_path(str(state.get("prefix", "") or ""), route_path)

    return [
        APIEndpoint(
            method=method,
            path=full_path,
            handler=str(details["handler"]),
            file=str(context.path),
            route_file=str(context.path),
            handler_file=str(context.path),
            line=line_num,
            middleware=middleware,
            raw_path=args[0].strip(),
            provenance={"router_object": obj},
        )
        for method in method_tokens
    ]


def _route_endpoints_from_with_call(
    context: RouteResolverContext,
    content: str,
    match: re.Match[str],
    alias_state: dict[str, dict[str, list[str] | str]],
) -> list[APIEndpoint]:
    obj = match.group(1)
    call_text = extract_balanced_segment(content, match.end() - 1)
    if not call_text:
        return []

    with_call_end = match.end() - 1 + len(call_text)
    suffix = content[with_call_end : with_call_end + 120]
    method_match = re.match(
        r"""\s*\.\s*(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|Any|Handle|Get|Post|Put|Patch|Delete|All)\s*\(""",
        suffix,
        re.IGNORECASE,
    )
    if not method_match:
        return []

    method_name = method_match.group(1)
    call_start = with_call_end + method_match.end() - 1
    route_call = extract_balanced_segment(content, call_start)
    if not route_call:
        return []

    args = split_top_level_args(route_call[1:-1])
    if len(args) < 2:
        return []

    route_path = parse_string_arg(args[0])
    if route_path is None:
        return []

    inline_middleware = _extract_go_identifier_names(
        split_top_level_args(call_text[1:-1])
    )
    state = alias_state.get(obj, {"prefix": "", "middleware": []})
    details = _extract_go_handler_details(args[1:])
    middleware = _ordered_unique(
        list(state.get("middleware", []) or [])
        + inline_middleware
        + list(details["middleware"])
    )
    full_path = join_route_path(str(state.get("prefix", "") or ""), route_path)
    line_num = line_number_for_offset(content, match.start())
    method_tokens = _normalize_go_methods(method_name)
    if method_tokens == ["ANY"]:
        method_tokens = _extract_go_chained_methods(
            content, call_start + len(route_call)
        ) or ["ANY"]

    return [
        APIEndpoint(
            method=method,
            path=full_path,
            handler=str(details["handler"]),
            file=str(context.path),
            route_file=str(context.path),
            handler_file=str(context.path),
            line=line_num,
            middleware=middleware,
            raw_path=args[0].strip(),
            provenance={"router_object": obj},
        )
        for method in method_tokens
    ]


def _route_endpoints_from_handlefunc(
    context: RouteResolverContext,
    content: str,
    match: re.Match[str],
    alias_state: dict[str, dict[str, list[str] | str]],
) -> list[APIEndpoint]:
    call_text = extract_balanced_segment(content, match.end() - 1)
    if not call_text:
        return []

    args = split_top_level_args(call_text[1:-1])
    if len(args) < 2:
        return []

    route_path = parse_string_arg(args[0])
    if route_path is None:
        return []

    details = _extract_go_handler_details(args[1:])
    obj_match = re.search(
        r"""\b(http|mux|router|r)\s*\.\s*HandleFunc\s*\($""",
        match.group(0),
        re.IGNORECASE,
    )
    obj = obj_match.group(1) if obj_match else "router"
    state = alias_state.get(obj, {"prefix": "", "middleware": []})
    methods = _extract_go_chained_methods(
        content, match.end() - 1 + len(call_text)
    ) or ["ANY"]
    full_path = join_route_path(str(state.get("prefix", "") or ""), route_path)
    line_num = line_number_for_offset(content, match.start())

    return [
        APIEndpoint(
            method=method,
            path=full_path,
            handler=str(details["handler"]),
            file=str(context.path),
            route_file=str(context.path),
            handler_file=str(context.path),
            line=line_num,
            middleware=list(state.get("middleware", []) or []),
            raw_path=args[0].strip(),
            provenance={"router_object": obj},
        )
        for method in methods
    ]


def _extract_go_handler_details(args: list[str]) -> dict[str, list[str] | str]:
    identifiers = _extract_go_identifier_names(args)
    if not identifiers:
        return {"handler": "", "middleware": []}
    if len(identifiers) == 1:
        return {"handler": identifiers[0], "middleware": []}
    return {"handler": identifiers[-1], "middleware": identifiers[:-1]}


def _extract_go_identifier_names(parts: list[str]) -> list[str]:
    identifiers: list[str] = []
    for part in parts:
        stripped = part.strip()
        if not stripped:
            continue
        if stripped.startswith("func"):
            name = "inline_handler"
        else:
            match = re.search(r"""(\w+(?:\.\w+)*)""", stripped)
            if not match:
                continue
            name = match.group(1)
        if name not in identifiers:
            identifiers.append(name)
    return identifiers


def _extract_go_chained_methods(content: str, start: int) -> list[str]:
    tail = content[start : start + 180]
    methods_match = re.search(r"""\.\s*Methods\s*\(([^)]*)\)""", tail, re.IGNORECASE)
    if not methods_match:
        return []
    methods: list[str] = []
    for method_match in re.finditer(r"""['\"](\w+)['\"]""", methods_match.group(1)):
        method = method_match.group(1).upper()
        if method and method not in methods:
            methods.append(method)
    return methods


def _normalize_go_methods(method_name: str) -> list[str]:
    method = METHOD_NAME_MAP.get(method_name.upper(), method_name.upper())
    return [method]


def _ordered_unique(items: list[str]) -> list[str]:
    ordered: list[str] = []
    for item in items:
        if item and item not in ordered:
            ordered.append(item)
    return ordered


DETECTOR = RegisteredRouteDetector(name="go", detect=detect_go_routes)
