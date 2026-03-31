"""FastAPI route detection."""

from __future__ import annotations

import re

from .base import APIEndpoint, RegisteredRouteDetector, RouteResolverContext
from .common import line_number_for_offset
from .python_shared import (
    extract_inline_python_docstring,
    find_following_python_handler,
)


FASTAPI_ROUTE = re.compile(
    r"""@(?:app|router)\s*\.\s*"""
    r"""(get|post|put|patch|delete|options|head)\s*\(\s*"""
    r"""['"]([^'"]+)['"]""",
    re.IGNORECASE | re.MULTILINE,
)


def detect_fastapi(context: RouteResolverContext) -> list[APIEndpoint]:
    content = context.content
    if (
        "fastapi" not in content.lower()
        and "@app." not in content
        and "@router." not in content
    ):
        return []

    endpoints: list[APIEndpoint] = []
    lines = content.splitlines()
    for match in FASTAPI_ROUTE.finditer(content):
        method, route_path = match.group(1).upper(), match.group(2)
        line_num = line_number_for_offset(content, match.start())

        handler, handler_idx = find_following_python_handler(lines, line_num)
        docstring = (
            extract_inline_python_docstring(lines, handler_idx)
            if handler_idx >= 0
            else ""
        )

        response_type = ""
        decorator_line = lines[line_num - 1] if line_num - 1 < len(lines) else ""
        resp_match = re.search(r"response_model\s*=\s*(\w+)", decorator_line)
        if resp_match:
            response_type = resp_match.group(1)

        endpoints.append(
            APIEndpoint(
                method=method,
                path=route_path,
                handler=handler,
                file=str(context.path),
                line=line_num,
                description=docstring,
                response_type=response_type,
            )
        )
    return endpoints


DETECTOR = RegisteredRouteDetector(name="fastapi", detect=detect_fastapi)
