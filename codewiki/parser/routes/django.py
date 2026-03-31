"""Django route detection."""

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


DJANGO_PATH = re.compile(
    r"""\b(path|re_path)\s*\(""",
    re.MULTILINE,
)

DJANGO_VIEW_WRAPPERS = re.compile(
    r"^(?:csrf_exempt|login_required|permission_required|cache_page\([^)]*\)|never_cache|require_http_methods\([^)]*\)|require_GET|require_POST)\s*\(\s*(.+)\s*\)\s*$",
    re.DOTALL,
)

DJANGO_FIRST_ARG_WRAPPERS = {
    "sync_to_async",
    "database_sync_to_async",
}

DJANGO_GENERIC_GET_ONLY_BASES = {
    "ListView",
    "DetailView",
    "TemplateView",
    "RedirectView",
    "ArchiveIndexView",
    "DateDetailView",
    "DayArchiveView",
    "MonthArchiveView",
    "TodayArchiveView",
    "WeekArchiveView",
    "YearArchiveView",
    "BaseListView",
    "BaseDetailView",
}

DJANGO_GENERIC_GET_POST_BASES = {
    "FormView",
    "CreateView",
    "UpdateView",
    "DeleteView",
    "PasswordChangeView",
    "BaseFormView",
    "ProcessFormView",
}


def detect_django(context: RouteResolverContext) -> list[APIEndpoint]:
    content = context.content
    if (
        "urlpatterns" not in content
        and "path(" not in content
        and "re_path(" not in content
        and ".register(" not in content
    ):
        return []

    endpoints: list[APIEndpoint] = []
    function_methods = extract_django_function_methods(content)
    class_views = extract_django_class_views(content)
    routers = extract_django_router_endpoints(content, class_views)

    for match in DJANGO_PATH.finditer(content):
        route_type = match.group(1)
        call_text = extract_balanced_segment(content, match.end() - 1)
        if not call_text:
            continue
        args = split_top_level_args(call_text[1:-1])
        if len(args) < 2:
            continue
        raw_path = parse_string_arg(args[0])
        if raw_path is None:
            continue
        route_path = normalize_django_route(raw_path, is_regex=route_type == "re_path")
        handler_expr = args[1].strip()
        line_num = line_number_for_offset(content, match.start())

        include_router = extract_django_include_router(handler_expr)
        if include_router and include_router in routers:
            for ep in routers[include_router]:
                endpoints.append(
                    APIEndpoint(
                        method=ep.method,
                        path=join_route_path(route_path, ep.path),
                        handler=ep.handler,
                        file=str(context.path),
                        line=line_num,
                        description=ep.description,
                    )
                )
            continue

        methods = infer_django_handler_methods(
            handler_expr, function_methods, class_views
        )
        handler = extract_django_handler_name(handler_expr)
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

    if not endpoints and routers:
        for router_eps in routers.values():
            endpoints.extend(router_eps)

    return endpoints


def extract_django_handler_name(handler_expr: str) -> str:
    expr = unwrap_django_handler_expr(handler_expr)
    if ".as_view" in expr:
        return expr.split(".as_view", 1)[0].split(".")[-1]
    return expr.split(".")[-1].split("(", 1)[0].strip()


def extract_django_function_methods(content: str) -> dict[str, list[str]]:
    methods: dict[str, list[str]] = {}
    decorator = None
    function_pattern = re.compile(
        r"""(^\s*@api_view\s*\([^)]*\)\s*)?(^\s*(?:async\s+def|def)\s+(\w+)\s*\([^)]*\)\s*:\s*)(.*?)(?=^\s*@api_view\s*\([^)]*\)\s*|^\s*(?:async\s+def|def|class)\s+\w+\s*\(|\Z)""",
        re.MULTILINE | re.DOTALL,
    )
    for match in function_pattern.finditer(content):
        inline_decorator = match.group(1)
        fn_name = match.group(3)
        body = match.group(4)
        active_decorator = inline_decorator or decorator
        if active_decorator:
            found = [
                m.upper()
                for m in re.findall(
                    r"""['\"](GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)['\"]""",
                    active_decorator,
                    re.IGNORECASE,
                )
            ]
            methods[fn_name] = found or ["ANY"]
            decorator = None
            continue

        inferred = infer_django_function_http_methods(body)
        methods[fn_name] = sorted(inferred) if inferred else ["ANY"]

    if methods:
        return methods

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("@api_view"):
            decorator = stripped
            continue
        fn_match = re.match(r"""(?:async\s+)?def\s+(\w+)\s*\(""", stripped)
        if not fn_match:
            continue
        fn_name = fn_match.group(1)
        if decorator:
            found = [
                m.upper()
                for m in re.findall(
                    r"""['\"](GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)['\"]""",
                    decorator,
                    re.IGNORECASE,
                )
            ]
            methods[fn_name] = found or ["ANY"]
            decorator = None
        else:
            methods.setdefault(fn_name, ["ANY"])
    return methods


def extract_django_class_views(content: str) -> dict[str, dict[str, object]]:
    views: dict[str, dict[str, object]] = {}
    class_pattern = re.compile(
        r"""class\s+(\w+)\s*\(([^)]*)\)\s*:\s*(.*?)(?=^class\s+|\Z)""",
        re.MULTILINE | re.DOTALL,
    )
    for match in class_pattern.finditer(content):
        class_name, bases, body = match.group(1), match.group(2), match.group(3)
        base_names = [
            base.strip().split(".")[-1]
            for base in bases.split(",")
            if base.strip()
        ]
        http_methods = {
            method.upper()
            for method in re.findall(
                r"""^\s*(?:async\s+def|def)\s+(get|post|put|patch|delete|options|head)\s*\(""",
                body,
                re.MULTILINE | re.IGNORECASE,
            )
        }
        if not http_methods:
            http_methods = infer_django_generic_http_methods(base_names)
        action_routes: list[dict[str, object]] = []
        action_pattern = re.compile(
            r"""@action\s*\((.*?)\)\s*\n\s*(?:async\s+def|def)\s+(\w+)\s*\(""",
            re.DOTALL,
        )
        for action_match in action_pattern.finditer(body):
            args_text = action_match.group(1)
            name = action_match.group(2)
            methods = [
                value.upper()
                for value in re.findall(
                    r"""['\"](GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)['\"]""",
                    args_text,
                    re.IGNORECASE,
                )
            ] or ["GET"]
            detail_match = re.search(r"""detail\s*=\s*(True|False)""", args_text)
            url_path_match = re.search(
                r"""url_path\s*=\s*['\"]([^'\"]+)['\"]""", args_text
            )
            action_routes.append(
                {
                    "name": name,
                    "methods": methods,
                    "detail": detail_match.group(1) == "True"
                    if detail_match
                    else False,
                    "url_path": url_path_match.group(1) if url_path_match else name,
                }
            )

        views[class_name] = {
            "http_methods": sorted(http_methods),
            "base_names": base_names,
            "is_viewset": "ViewSet" in bases,
            "actions": action_routes,
            "crud_methods": {
                name
                for name in re.findall(
                    r"""^\s*(?:async\s+def|def)\s+(list|retrieve|create|update|partial_update|destroy)\s*\(""",
                    body,
                    re.MULTILINE,
                )
            },
        }
    return views


def extract_django_router_endpoints(
    content: str,
    class_views: dict[str, dict[str, object]],
) -> dict[str, list[APIEndpoint]]:
    routers: dict[str, list[APIEndpoint]] = {}
    register_pattern = re.compile(
        r"""(\w+)\s*\.\s*register\s*\(\s*(?:r)?['\"]([^'\"]+)['\"]\s*,\s*(\w+)""",
        re.IGNORECASE,
    )
    for match in register_pattern.finditer(content):
        router_name, base_path, view_class = (
            match.group(1),
            match.group(2),
            match.group(3),
        )
        view_meta = class_views.get(view_class, {})
        crud_methods = view_meta.get("crud_methods") or {
            "list",
            "retrieve",
            "create",
            "update",
            "partial_update",
            "destroy",
        }
        router_eps = routers.setdefault(router_name, [])
        collection_path = join_route_path(base_path)
        detail_path = join_route_path(base_path, "{id}")
        if "list" in crud_methods:
            router_eps.append(
                APIEndpoint(
                    method="GET", path=collection_path, handler=f"{view_class}.list"
                )
            )
        if "create" in crud_methods:
            router_eps.append(
                APIEndpoint(
                    method="POST", path=collection_path, handler=f"{view_class}.create"
                )
            )
        if "retrieve" in crud_methods:
            router_eps.append(
                APIEndpoint(
                    method="GET", path=detail_path, handler=f"{view_class}.retrieve"
                )
            )
        if "update" in crud_methods:
            router_eps.append(
                APIEndpoint(
                    method="PUT", path=detail_path, handler=f"{view_class}.update"
                )
            )
        if "partial_update" in crud_methods:
            router_eps.append(
                APIEndpoint(
                    method="PATCH",
                    path=detail_path,
                    handler=f"{view_class}.partial_update",
                )
            )
        if "destroy" in crud_methods:
            router_eps.append(
                APIEndpoint(
                    method="DELETE", path=detail_path, handler=f"{view_class}.destroy"
                )
            )
        for action in view_meta.get("actions", []):
            action_path = join_route_path(
                base_path, "{id}" if action["detail"] else "", action["url_path"]
            )
            for method in action["methods"]:
                router_eps.append(
                    APIEndpoint(
                        method=method,
                        path=action_path,
                        handler=f"{view_class}.{action['name']}",
                    )
                )
    return routers


def extract_django_include_router(handler_expr: str) -> str | None:
    match = re.search(r"""include\s*\(\s*(\w+)\.urls""", handler_expr)
    if match:
        return match.group(1)
    match = re.search(r"""include\s*\(\s*['"](\w+)\.urls['"]""", handler_expr)
    return match.group(1) if match else None


def infer_django_handler_methods(
    handler_expr: str,
    function_methods: dict[str, list[str]],
    class_views: dict[str, dict[str, object]],
) -> list[str]:
    handler_expr = unwrap_django_handler_expr(handler_expr)
    as_view_mapping = re.search(r"""\.as_view\s*\(\s*\{([^}]*)\}\s*\)""", handler_expr)
    if as_view_mapping:
        mapped = re.findall(
            r"""['\"](get|post|put|patch|delete|options|head)['\"]\s*:""",
            as_view_mapping.group(1),
            re.IGNORECASE,
        )
        return [method.upper() for method in mapped] or ["ANY"]

    if ".as_view" in handler_expr:
        class_name = extract_django_handler_name(handler_expr)
        methods = class_views.get(class_name, {}).get("http_methods", [])
        return methods or ["ANY"]

    handler_name = extract_django_handler_name(handler_expr)
    return function_methods.get(handler_name, ["ANY"])


def unwrap_django_handler_expr(handler_expr: str) -> str:
    expr = handler_expr.strip()
    previous = None
    while expr and expr != previous:
        previous = expr
        match = DJANGO_VIEW_WRAPPERS.match(expr)
        if match:
            expr = match.group(1).strip()
            continue

        call_match = re.match(r"""^([A-Za-z_][\w.]*)\s*\(""", expr)
        if not call_match:
            break
        wrapper_name = call_match.group(1).split(".")[-1]
        if wrapper_name not in DJANGO_FIRST_ARG_WRAPPERS:
            break
        call_text = extract_balanced_segment(expr, call_match.end() - 1)
        if not call_text:
            break
        suffix = expr[call_match.start(1) + len(call_match.group(1)) :]
        if suffix.strip() != call_text:
            break
        args = split_top_level_args(call_text[1:-1])
        if not args:
            break
        expr = args[0].strip()

    return expr


def infer_django_generic_http_methods(base_names: list[str]) -> set[str]:
    if any(base in DJANGO_GENERIC_GET_POST_BASES for base in base_names):
        return {"GET", "POST"}
    if any(base in DJANGO_GENERIC_GET_ONLY_BASES for base in base_names):
        return {"GET"}
    return set()


def infer_django_function_http_methods(body: str) -> set[str]:
    inferred: set[str] = set()
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"):
        if re.search(
            rf"""request\.method\s*([!=]=|in)\s*['\"]{method}['\"]""",
            body,
            re.IGNORECASE,
        ):
            inferred.add(method)
    if "request.POST" in body:
        inferred.add("POST")
    if "request.GET" in body:
        inferred.add("GET")
    return inferred


def normalize_django_route(route: str, *, is_regex: bool) -> str:
    if not is_regex:
        normalized = route.strip()
        normalized = re.sub(r"""<(?:(\w+):)?(\w+)>""", r"{\2}", normalized)
        return join_route_path(normalized)
    normalized = route.strip()
    normalized = normalized.lstrip("r")
    normalized = normalized.lstrip("^").rstrip("$")
    normalized = re.sub(r"""\(\?P<(\w+)>[^)]+\)""", r"{\1}", normalized)
    normalized = re.sub(r"""\[[^\]]+\]\+?""", "{param}", normalized)
    normalized = normalized.replace("\\/", "/")
    normalized = normalized.replace("\\", "")
    return join_route_path(normalized)


DETECTOR = RegisteredRouteDetector(name="django", detect=detect_django)
