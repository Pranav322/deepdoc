"""Flask route detection."""

from __future__ import annotations

import re

from .base import APIEndpoint, RegisteredRouteDetector, RouteResolverContext
from .common import line_number_for_offset
from .python_shared import find_following_python_handler


FLASK_ROUTE = re.compile(
    r"""@(?:app|bp|blueprint)\s*\.route\s*\(\s*"""
    r"""['"]([^'"]+)['"]"""
    r"""(?:\s*,\s*methods\s*=\s*\[([^\]]+)\])?""",
    re.IGNORECASE | re.MULTILINE,
)


def detect_flask(context: RouteResolverContext) -> list[APIEndpoint]:
    content = context.content
    if (
        "flask" not in content.lower()
        and "@app.route" not in content
        and ".route(" not in content
    ):
        return []

    endpoints: list[APIEndpoint] = []
    lines = content.splitlines()
    for match in FLASK_ROUTE.finditer(content):
        route_path = match.group(1)
        methods_str = match.group(2)
        if methods_str:
            methods = [m.strip().strip("'\"").upper() for m in methods_str.split(",")]
        else:
            methods = ["GET"]

        line_num = line_number_for_offset(content, match.start())
        handler, _ = find_following_python_handler(lines, line_num)

        for method in methods:
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


DETECTOR = RegisteredRouteDetector(name="flask", detect=detect_flask)
