"""FastAPI route detection."""

from __future__ import annotations

import re

from .base import APIEndpoint, RegisteredRouteDetector, RouteResolverContext
from .common import (
    extract_balanced_segment,
    line_number_for_offset,
    parse_string_arg,
    split_top_level_args,
)
from .python_shared import find_following_python_handler

# @app.get("/path"), @router.post("/items")
FASTAPI_DECORATOR_ROUTE = re.compile(
    r"""@(\w+)\s*\.\s*(get|post|put|patch|delete|head|options|api_route|websocket)\s*\(""",
    re.IGNORECASE | re.MULTILINE,
)

# app.add_api_route("/path", handler, ...)
FASTAPI_ADD_ROUTE = re.compile(
    r"""(\w+)\s*\.\s*add_api_route\s*\(""",
    re.MULTILINE,
)

def detect_fastapi(context: RouteResolverContext) -> list[APIEndpoint]:
    content = context.content
    if "fastapi" not in content.lower() and "APIRouter" not in content and "@" not in content and "add_api_route" not in content:
        return []

    endpoints: list[APIEndpoint] = []
    lines = content.splitlines()

    for match in FASTAPI_DECORATOR_ROUTE.finditer(content):
        line_start = content.rfind("\n", 0, match.start()) + 1
        prefix = content[line_start : match.start()]
        if prefix.lstrip().startswith("#"):
            continue

        router_var = match.group(1)
        method_str = match.group(2).upper()
        
        call_text = extract_balanced_segment(content, match.end() - 1)
        if not call_text:
            continue
            
        args = split_top_level_args(call_text[1:-1])
        if not args:
            continue
            
        path_expr = args[0].strip()
        route_path = parse_string_arg(path_expr) or path_expr.strip('"\'')
        
        methods = [method_str]
        if method_str == "API_ROUTE":
            methods = _extract_methods_from_args(args) or ["ANY"]
        elif method_str == "WEBSOCKET":
            methods = ["WEBSOCKET"]

        line_num = line_number_for_offset(content, match.start())
        handler_name, _ = find_following_python_handler(lines, line_num - 1, limit=10)
        
        dependencies = _extract_dependencies(args)

        for method in methods:
            endpoints.append(
                APIEndpoint(
                    method=method,
                    path=route_path,
                    handler=handler_name,
                    file=str(context.path),
                    route_file=str(context.path),
                    handler_file=str(context.path),
                    line=line_num,
                    middleware=dependencies,
                    raw_path=path_expr,
                    provenance={"router_var": router_var},
                )
            )

    for match in FASTAPI_ADD_ROUTE.finditer(content):
        line_start = content.rfind("\n", 0, match.start()) + 1
        prefix = content[line_start : match.start()]
        if prefix.lstrip().startswith("#"):
            continue

        router_var = match.group(1)
        
        call_text = extract_balanced_segment(content, match.end() - 1)
        if not call_text:
            continue
            
        args = split_top_level_args(call_text[1:-1])
        if len(args) < 2:
            continue
            
        path_expr = args[0].strip()
        route_path = parse_string_arg(path_expr) or path_expr.strip('"\'')
        handler_name = args[1].strip()
        
        methods = _extract_methods_from_args(args) or ["ANY"]
        line_num = line_number_for_offset(content, match.start())
        dependencies = _extract_dependencies(args)

        for method in methods:
            endpoints.append(
                APIEndpoint(
                    method=method,
                    path=route_path,
                    handler=handler_name,
                    file=str(context.path),
                    route_file=str(context.path),
                    handler_file=str(context.path),
                    line=line_num,
                    middleware=dependencies,
                    raw_path=path_expr,
                    provenance={"router_var": router_var},
                )
            )

    return endpoints


def _extract_methods_from_args(args: list[str]) -> list[str]:
    for arg in args:
        arg = arg.strip()
        if arg.startswith("methods="):
            list_match = re.search(r"methods=\s*\[(.*?)\]", arg)
            if list_match:
                parts = list_match.group(1).split(",")
                return [p.strip().strip("'\"").upper() for p in parts if p.strip()]
    return []

def _extract_dependencies(args: list[str]) -> list[str]:
    deps = []
    for arg in args:
        arg = arg.strip()
        if arg.startswith("dependencies="):
            list_match = re.search(r"dependencies=\s*\[(.*?)\]", arg)
            if list_match:
                deps_content = list_match.group(1)
                for dep_match in re.finditer(r"Depends\(\s*([\w\.]+)\s*\)", deps_content):
                    deps.append(dep_match.group(1))
    return deps

DETECTOR = RegisteredRouteDetector(name="fastapi", detect=detect_fastapi)
