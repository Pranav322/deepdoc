"""Falcon route detection."""

from __future__ import annotations

import re

from .base import APIEndpoint, RegisteredRouteDetector, RouteResolverContext
from .common import (
    extract_balanced_segment,
    line_number_for_offset,
    parse_string_arg,
    split_top_level_args,
)


FALCON_ADD_ROUTE = re.compile(r"""(?:app|api)\s*\.\s*add_route\s*\(""", re.MULTILINE)

FALCON_RESPONDER = re.compile(
    r"""def\s+(on_(?:get|post|put|patch|delete|head|options))\s*\(\s*self""",
    re.IGNORECASE,
)


def detect_falcon(context: RouteResolverContext) -> list[APIEndpoint]:
    content = context.content
    if "falcon" not in content.lower() and "add_route" not in content:
        return []

    endpoints: list[APIEndpoint] = []

    for match in FALCON_ADD_ROUTE.finditer(content):
        line_start = content.rfind("\n", 0, match.start()) + 1
        prefix = content[line_start:match.start()]
        if prefix.lstrip().startswith("#"):
            continue
        call_text = extract_balanced_segment(content, match.end() - 1)
        if not call_text:
            continue
        args = split_top_level_args(call_text[1:-1])
        if len(args) < 2:
            continue
        path_expr = args[0].strip()
        resource_ref = re.sub(r"""\(\s*\)\s*$""", "", args[1].strip())
        route_path = parse_string_arg(path_expr) or _fallback_falcon_path(path_expr)
        line_num = line_number_for_offset(content, match.start())
        resource_class = resource_ref.split(".")[-1]

        methods = find_falcon_responders(content, resource_class)
        if methods:
            for method in methods:
                endpoints.append(
                    APIEndpoint(
                        method=method,
                        path=route_path,
                        handler=f"{resource_ref}.on_{method.lower()}",
                        file=str(context.path),
                        route_file=str(context.path),
                        handler_file=str(context.path),
                        line=line_num,
                        raw_path=path_expr,
                        provenance={"resource_ref": resource_ref},
                    )
                )
        else:
            endpoints.append(
                APIEndpoint(
                    method="ANY",
                    path=route_path,
                    handler=resource_ref,
                    file=str(context.path),
                    route_file=str(context.path),
                    handler_file=str(context.path),
                    line=line_num,
                    raw_path=path_expr,
                    provenance={"resource_ref": resource_ref},
                )
            )

    if (
        not endpoints
        and "class " in content
        and ("on_get" in content or "on_post" in content)
    ):
        all_classes = re.finditer(r"class\s+(\w+)", content)
        for cls_match in all_classes:
            class_name = cls_match.group(1)
            class_methods = find_falcon_responders(content, class_name)
            for http_method in class_methods:
                method_name = f"on_{http_method.lower()}"
                endpoints.append(
                    APIEndpoint(
                        method=http_method,
                        path=f"(see add_route for {class_name})",
                        handler=f"{class_name}.{method_name}",
                        file=str(context.path),
                        route_file=str(context.path),
                        handler_file=str(context.path),
                        line=0,
                        raw_path=f"(see add_route for {class_name})",
                        provenance={"resource_ref": class_name},
                    )
                )

    return endpoints


def _fallback_falcon_path(path_expr: str) -> str:
    string_parts = re.findall(r"""['"]([^'"]+)['"]""", path_expr)
    if not string_parts:
        return path_expr
    return "".join(string_parts)


def find_falcon_responders(content: str, class_name: str) -> list[str]:
    """Find all on_* methods in a Falcon resource class."""
    methods: list[str] = []
    class_pattern = re.compile(
        rf"class\s+{re.escape(class_name)}\b.*?(?=\nclass\s|\Z)",
        re.DOTALL,
    )
    class_match = class_pattern.search(content)
    if class_match:
        class_body = class_match.group(0)
        for match in FALCON_RESPONDER.finditer(class_body):
            method_name = match.group(1)
            http_method = method_name.replace("on_", "").upper()
            methods.append(http_method)
    return methods


DETECTOR = RegisteredRouteDetector(name="falcon", detect=detect_falcon)
