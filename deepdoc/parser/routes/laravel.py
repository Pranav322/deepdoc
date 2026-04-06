"""Laravel route detection."""

from __future__ import annotations

import re

from .base import APIEndpoint, RegisteredRouteDetector, RouteResolverContext
from .common import line_number_for_offset

LARAVEL_ROUTE = re.compile(
    r"""Route\s*::\s*(get|post|put|patch|delete|any|match|options)\s*\(\s*"""
    r"""['"]([^'"]+)['"]""",
    re.IGNORECASE | re.MULTILINE,
)

LARAVEL_RESOURCE = re.compile(
    r"""Route\s*::\s*(?:api)?resource\s*\(\s*"""
    r"""['"]([^'"]+)['"]""",
    re.IGNORECASE | re.MULTILINE,
)

LARAVEL_CONTROLLER = re.compile(
    r"""['"]([\w\\]+Controller)(?:@(\w+))?['"]""",
)

LARAVEL_GROUP = re.compile(
    r"""Route\s*::\s*group\s*\(\s*(?:array\s*\(|)"""
    r"""[^)]*?['"]prefix['"]\s*(?:=>|:)\s*['"]([^'"]+)['"]""",
    re.IGNORECASE | re.DOTALL,
)


def detect_laravel(context: RouteResolverContext) -> list[APIEndpoint]:
    content = context.content
    if "Route::" not in content:
        return []

    endpoints: list[APIEndpoint] = []
    group_prefixes = build_laravel_group_prefixes(content)

    for match in LARAVEL_ROUTE.finditer(content):
        method, route_path = match.group(1).upper(), match.group(2)
        line_num = line_number_for_offset(content, match.start())

        prefix = resolve_prefix(match.start(), group_prefixes)
        if prefix:
            route_path = prefix.rstrip("/") + "/" + route_path.lstrip("/")
        if not route_path.startswith("/"):
            route_path = "/" + route_path

        handler_region = content[match.start() : match.start() + 500]
        ctrl_match = LARAVEL_CONTROLLER.search(handler_region)
        handler = (
            f"{ctrl_match.group(1)}@{ctrl_match.group(2)}"
            if ctrl_match and ctrl_match.group(2)
            else (ctrl_match.group(1) if ctrl_match else "")
        )

        middleware: list[str] = []
        mw_match = re.search(r"->middleware\s*\(\s*\[?([^\])\n]+)", handler_region)
        if mw_match:
            middleware = [m.strip().strip("'\"") for m in mw_match.group(1).split(",")]
        else:
            mw_match4 = re.search(
                r"['\"](before|middleware)['\"]\s*=>\s*['\"]([^'\"]+)['\"]",
                handler_region,
            )
            if mw_match4:
                middleware = [m.strip() for m in mw_match4.group(2).split("|")]

        endpoints.append(
            APIEndpoint(
                method=method,
                path=route_path,
                handler=handler,
                file=str(context.path),
                line=line_num,
                middleware=middleware,
            )
        )

    for match in LARAVEL_RESOURCE.finditer(content):
        resource = match.group(1)
        line_num = line_number_for_offset(content, match.start())
        base = "/" + resource if not resource.startswith("/") else resource

        for method, suffix in [
            ("GET", ""),
            ("GET", "/{id}"),
            ("POST", ""),
            ("PUT", "/{id}"),
            ("DELETE", "/{id}"),
        ]:
            endpoints.append(
                APIEndpoint(
                    method=method,
                    path=base + suffix,
                    handler=f"{resource.title()}Controller",
                    file=str(context.path),
                    line=line_num,
                )
            )

    return endpoints


def build_laravel_group_prefixes(content: str) -> list[tuple[int, int, str]]:
    """Build list of (start, end, prefix) for each Route::group in the file."""
    groups: list[tuple[int, int, str]] = []
    for match in LARAVEL_GROUP.finditer(content):
        prefix = match.group(1)
        brace_start = content.find("{", match.end())
        if brace_start == -1:
            continue
        depth = 1
        pos = brace_start + 1
        while pos < len(content) and depth > 0:
            if content[pos] == "{":
                depth += 1
            elif content[pos] == "}":
                depth -= 1
            pos += 1
        groups.append((brace_start, pos, prefix))
    return groups


def resolve_prefix(offset: int, groups: list[tuple[int, int, str]]) -> str:
    """Resolve the full prefix for a route at the given offset."""
    prefixes: list[str] = []
    for start, end, prefix in groups:
        if start < offset < end:
            prefixes.append(prefix)
    if not prefixes:
        return ""
    return "/" + "/".join(p.strip("/") for p in prefixes)


DETECTOR = RegisteredRouteDetector(name="laravel", detect=detect_laravel)
