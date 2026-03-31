"""Express.js / Hono / Koa-style route detection."""

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
from .js_shared import (
    JS_ROUTE_CALL,
    JS_ROUTE_CHAIN,
    extract_js_handler_details,
    extract_js_mounts,
    resolve_js_prefixes,
)


def detect_express(context: RouteResolverContext) -> list[APIEndpoint]:
    content = context.content
    lowered = content.lower()
    if "express" not in lowered and "router(" not in lowered and ".use(" not in lowered:
        return []

    mounts = extract_js_mounts(content)
    endpoints: list[APIEndpoint] = []
    seen: set[str] = set()

    for match in JS_ROUTE_CALL.finditer(content):
        obj, method = match.group(1), match.group(2).upper()
        if obj.lower() == "fastify":
            continue
        call_text = extract_balanced_segment(content, match.end() - 1)
        if not call_text:
            continue
        args = split_top_level_args(call_text[1:-1])
        if not args:
            continue
        route_path = parse_string_arg(args[0])
        if route_path is None:
            continue
        details = extract_js_handler_details(args[1:])
        line_num = line_number_for_offset(content, match.start())
        for prefix in resolve_js_prefixes(obj, mounts):
            full_path = join_route_path(prefix, route_path)
            key = f"{method}:{full_path}:{line_num}"
            if key in seen:
                continue
            seen.add(key)
            endpoints.append(
                APIEndpoint(
                    method=method,
                    path=full_path,
                    handler=details["handler"],
                    file=str(context.path),
                    route_file=str(context.path),
                    handler_file=str(context.path),
                    line=line_num,
                    middleware=details["middleware"],
                    raw_path=route_path,
                    provenance={"router_object": obj},
                )
            )

    for match in JS_ROUTE_CHAIN.finditer(content):
        obj = match.group(1)
        call_text = extract_balanced_segment(content, match.end() - 1)
        if not call_text:
            continue
        args = split_top_level_args(call_text[1:-1])
        if not args:
            continue
        base_path = parse_string_arg(args[0])
        if base_path is None:
            continue
        line_num = line_number_for_offset(content, match.start())
        tail = content[
            match.end() - 1 + len(call_text) : match.end() - 1 + len(call_text) + 800
        ]
        for chain_match in re.finditer(
            r"""\.\s*(get|post|put|patch|delete|all|options|head)\s*\(""",
            tail,
            re.IGNORECASE,
        ):
            method = chain_match.group(1).upper()
            chain_call = extract_balanced_segment(tail, chain_match.end() - 1)
            if not chain_call:
                continue
            details = extract_js_handler_details(
                split_top_level_args(chain_call[1:-1])
            )
            for prefix in resolve_js_prefixes(obj, mounts):
                full_path = join_route_path(prefix, base_path)
                key = f"{method}:{full_path}:{line_num}"
                if key in seen:
                    continue
                seen.add(key)
                endpoints.append(
                    APIEndpoint(
                        method=method,
                        path=full_path,
                        handler=details["handler"],
                        file=str(context.path),
                        route_file=str(context.path),
                        handler_file=str(context.path),
                        line=line_num,
                        middleware=details["middleware"],
                        raw_path=base_path,
                        provenance={"router_object": obj},
                    )
                )

    return endpoints


DETECTOR = RegisteredRouteDetector(name="express", detect=detect_express)
