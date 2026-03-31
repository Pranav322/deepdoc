"""Go route detection."""

from __future__ import annotations

import re

from .base import APIEndpoint, RegisteredRouteDetector, RouteResolverContext
from .common import line_number_for_offset


GO_ROUTE = re.compile(
    r"""(?:r|router|e|engine|app|g|group|api|v\d+)\s*\.\s*"""
    r"""(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|Any|Handle)\s*\(\s*"""
    r"""['"]([^'"]+)['"]""",
    re.IGNORECASE | re.MULTILINE,
)

GO_HANDLEFUNC = re.compile(
    r"""(?:http|mux|r|router)\s*\.\s*HandleFunc\s*\(\s*"""
    r"""['"]([^'"]+)['"]""",
    re.MULTILINE,
)

GO_FIBER = re.compile(
    r"""(?:app|group|api|v\d+)\s*\.\s*"""
    r"""(Get|Post|Put|Patch|Delete|All)\s*\(\s*"""
    r"""['"]([^'"]+)['"]""",
    re.MULTILINE,
)


def detect_go_routes(context: RouteResolverContext) -> list[APIEndpoint]:
    content = context.content
    endpoints: list[APIEndpoint] = []
    lines = content.splitlines()

    for match in GO_ROUTE.finditer(content):
        method, route_path = match.group(1).upper(), match.group(2)
        line_num = line_number_for_offset(content, match.start())
        handler = find_go_handler(lines, line_num - 1, content, match.end())
        endpoints.append(
            APIEndpoint(
                method=method,
                path=route_path,
                handler=handler,
                file=str(context.path),
                line=line_num,
            )
        )

    for match in GO_HANDLEFUNC.finditer(content):
        route_path = match.group(1)
        line_num = line_number_for_offset(content, match.start())
        endpoints.append(
            APIEndpoint(
                method="ANY",
                path=route_path,
                handler="HandleFunc",
                file=str(context.path),
                line=line_num,
            )
        )

    for match in GO_FIBER.finditer(content):
        method, route_path = match.group(1).upper(), match.group(2)
        line_num = line_number_for_offset(content, match.start())
        handler = find_go_handler(lines, line_num - 1, content, match.end())
        endpoints.append(
            APIEndpoint(
                method=method,
                path=route_path,
                handler=handler,
                file=str(context.path),
                line=line_num,
            )
        )

    return endpoints


def find_go_handler(lines, line_idx, content, match_end):
    """Extract handler function name from Go route definition."""
    del lines, line_idx
    remaining = content[match_end : match_end + 200]
    fn_match = re.search(r",\s*(\w+(?:\.\w+)*)\s*[,)]", remaining)
    if fn_match:
        return fn_match.group(1)
    return ""


DETECTOR = RegisteredRouteDetector(name="go", detect=detect_go_routes)
