"""NestJS decorator-based route detection."""

from __future__ import annotations

import re

from .base import APIEndpoint, RegisteredRouteDetector, RouteResolverContext
from .common import line_number_for_offset

NESTJS_CONTROLLER = re.compile(r"@Controller\s*\(\s*['\"](.*?)['\"]\s*\)")
NESTJS_METHOD = re.compile(
    r"@(Get|Post|Put|Patch|Delete|All|Options|Head)\s*\(\s*(?:['\"](.*?)['\"])?\s*\)"
)


def detect_nestjs(context: RouteResolverContext) -> list[APIEndpoint]:
    content = context.content
    if "@Controller" not in content:
        return []

    endpoints: list[APIEndpoint] = []
    ctrl_match = NESTJS_CONTROLLER.search(content)
    base_path = ctrl_match.group(1) if ctrl_match else ""
    if base_path and not base_path.startswith("/"):
        base_path = "/" + base_path

    lines = content.splitlines()
    for match in NESTJS_METHOD.finditer(content):
        method = match.group(1).upper()
        sub_path = match.group(2) or ""
        if sub_path and not sub_path.startswith("/"):
            sub_path = "/" + sub_path
        full_path = base_path + sub_path
        line_num = line_number_for_offset(content, match.start())

        handler = ""
        for idx in range(line_num, min(line_num + 5, len(lines))):
            line = lines[idx].strip() if idx < len(lines) else ""
            if line and not line.startswith("@"):
                fn_match = re.match(r"(?:async\s+)?(\w+)\s*\(", line)
                if fn_match:
                    handler = fn_match.group(1)
                break

        endpoints.append(
            APIEndpoint(
                method=method,
                path=full_path or "/",
                handler=handler,
                file=str(context.path),
                line=line_num,
            )
        )
    return endpoints


DETECTOR = RegisteredRouteDetector(name="nestjs", detect=detect_nestjs)
