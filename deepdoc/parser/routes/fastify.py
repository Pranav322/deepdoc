"""Fastify route detection."""

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
    FASTIFY_ROUTE_CALL,
    JS_ROUTE_CALL,
    extract_fastify_mounts,
    extract_fastify_plugin_aliases,
    extract_fastify_schema,
    extract_fastify_schema_from_args,
    extract_js_handler_details,
    resolve_js_prefixes,
)


def detect_fastify(context: RouteResolverContext) -> list[APIEndpoint]:
    content = context.content
    if "fastify" not in content.lower() and "Fastify" not in content:
        return []

    endpoints: list[APIEndpoint] = []
    seen: set[str] = set()
    plugin_aliases = extract_fastify_plugin_aliases(content)
    mounts = extract_fastify_mounts(content, plugin_aliases)

    for match in JS_ROUTE_CALL.finditer(content):
        obj, method = match.group(1), match.group(2).upper()
        if obj not in mounts and obj.lower() not in {
            "fastify",
            "server",
            "app",
            "instance",
        }:
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
        schema = extract_fastify_schema_from_args(args[1:])
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
                    line=line_num,
                    middleware=details["middleware"],
                    request_body=schema.get("body", ""),
                    response_type=schema.get("response", ""),
                )
            )

    for match in FASTIFY_ROUTE_CALL.finditer(content):
        obj = match.group(1)
        if obj not in mounts and obj.lower() not in {
            "fastify",
            "server",
            "app",
            "instance",
        }:
            continue
        call_text = extract_balanced_segment(content, match.end() - 1)
        if not call_text:
            continue
        body = call_text[1:-1]
        method_match = re.search(
            r"""method\s*:\s*['\"](\w+)['\"]""", body, re.IGNORECASE
        )
        url_match = re.search(r"""url\s*:\s*['\"]([^'\"]+)['\"]""", body, re.IGNORECASE)
        if not method_match or not url_match:
            continue
        method = method_match.group(1).upper()
        route_path = url_match.group(1)
        handler_match = re.search(r"""handler\s*:\s*(\w+(?:\.\w+)*)""", body)
        schema = extract_fastify_schema(body, 0)
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
                    handler=handler_match.group(1) if handler_match else "route()",
                    file=str(context.path),
                    line=line_num,
                    request_body=schema.get("body", ""),
                    response_type=schema.get("response", ""),
                )
            )

    return endpoints


DETECTOR = RegisteredRouteDetector(name="fastify", detect=detect_fastify)
