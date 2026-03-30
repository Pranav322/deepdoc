"""API endpoint detection across all supported languages.

Detects routes/endpoints from:
- Express.js / Fastify / Hono / Koa (JS/TS)
- NestJS decorators (TS)
- FastAPI / Flask / Django (Python)
- Gin / Echo / Fiber / Chi / net/http (Go)
- Laravel (PHP)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class APIEndpoint:
    """A detected API endpoint / route."""

    method: str  # GET, POST, PUT, DELETE, PATCH, etc.
    path: str  # /api/v2/users/:id
    handler: str = ""  # function name or controller method
    file: str = ""  # source file path
    line: int = 0  # line number
    description: str = ""  # inline comment or docstring
    middleware: list[str] = field(default_factory=list)
    request_body: str = ""  # inferred from decorators/types
    response_type: str = ""  # inferred from return type

    @property
    def display_method(self) -> str:
        return self.method.upper()

    @property
    def unique_key(self) -> str:
        return f"{self.method.upper()} {self.path}"


def detect_endpoints(path: Path, content: str, language: str) -> list[APIEndpoint]:
    """Detect all API endpoints in a file. Returns empty list if none found."""
    detectors = {
        "javascript": [_detect_express, _detect_fastify, _detect_nestjs],
        "typescript": [_detect_express, _detect_fastify, _detect_nestjs],
        "vue": [
            _detect_express,
            _detect_fastify,
        ],  # Vue script blocks may define routes
        "python": [_detect_fastapi, _detect_flask, _detect_falcon, _detect_django],
        "go": [_detect_go_routes],
        "php": [_detect_laravel],
    }
    fns = detectors.get(language, [])
    endpoints: list[APIEndpoint] = []
    seen: set[str] = set()
    for fn in fns:
        for ep in fn(path, content):
            key = f"{ep.method}:{ep.path}:{ep.line}"
            if key not in seen:
                seen.add(key)
                endpoints.append(ep)
    return endpoints


# ─────────────────────────────────────────────────────────────────────────────
# Express.js / Fastify / Hono / Koa
# ─────────────────────────────────────────────────────────────────────────────

_JS_ROUTE_CALL = re.compile(
    r"""\b(\w+)\s*\.\s*"""
    r"""(get|post|put|patch|delete|all|options|head)\s*\(""",
    re.IGNORECASE | re.MULTILINE,
)

_JS_ROUTE_CHAIN = re.compile(
    r"""\b(\w+)\s*\.\s*route\s*\(""",
    re.IGNORECASE | re.MULTILINE,
)

_JS_USE_CALL = re.compile(
    r"""\b(\w+)\s*\.\s*use\s*\(""",
    re.IGNORECASE | re.MULTILINE,
)

_FASTIFY_REGISTER_CALL = re.compile(
    r"""\b(\w+)\s*\.\s*register\s*\(""",
    re.IGNORECASE | re.MULTILINE,
)

_FASTIFY_PLUGIN_FUNCTION = re.compile(
    r"""(?:async\s+)?function\s+(\w+)\s*\(\s*(\w+)""",
    re.IGNORECASE,
)

_FASTIFY_PLUGIN_ARROW = re.compile(
    r"""const\s+(\w+)\s*=\s*(?:async\s*)?"""
    r"""(?:function\s*\(\s*(\w+)"""
    r"""|\(\s*(\w+)\s*(?:,|\)))""",
    re.IGNORECASE,
)

_FASTIFY_ROUTE_CALL = re.compile(
    r"""\b(\w+)\s*\.\s*route\s*\(""",
    re.IGNORECASE | re.MULTILINE,
)


def _detect_express(path: Path, content: str) -> list[APIEndpoint]:
    lowered = content.lower()
    if "express" not in lowered and "router(" not in lowered and ".use(" not in lowered:
        return []

    mounts = _extract_js_mounts(content)
    endpoints: list[APIEndpoint] = []
    seen: set[str] = set()

    for match in _JS_ROUTE_CALL.finditer(content):
        obj, method = match.group(1), match.group(2).upper()
        if obj.lower() == "fastify":
            continue
        call_text = _extract_balanced_segment(content, match.end() - 1)
        if not call_text:
            continue
        args = _split_top_level_args(call_text[1:-1])
        if not args:
            continue
        route_path = _parse_string_arg(args[0])
        if route_path is None:
            continue
        details = _extract_js_handler_details(args[1:])
        line_num = content[: match.start()].count("\n") + 1
        for prefix in _resolve_js_prefixes(obj, mounts):
            full_path = _join_route_path(prefix, route_path)
            key = f"{method}:{full_path}:{line_num}"
            if key in seen:
                continue
            seen.add(key)
            endpoints.append(
                APIEndpoint(
                    method=method,
                    path=full_path,
                    handler=details["handler"],
                    file=str(path),
                    line=line_num,
                    middleware=details["middleware"],
                )
            )

    for match in _JS_ROUTE_CHAIN.finditer(content):
        obj = match.group(1)
        call_text = _extract_balanced_segment(content, match.end() - 1)
        if not call_text:
            continue
        args = _split_top_level_args(call_text[1:-1])
        if not args:
            continue
        base_path = _parse_string_arg(args[0])
        if base_path is None:
            continue
        line_num = content[: match.start()].count("\n") + 1
        tail = content[
            match.end() - 1 + len(call_text) : match.end() - 1 + len(call_text) + 800
        ]
        for chain_match in re.finditer(
            r"""\.\s*(get|post|put|patch|delete|all|options|head)\s*\(""",
            tail,
            re.IGNORECASE,
        ):
            method = chain_match.group(1).upper()
            chain_call = _extract_balanced_segment(tail, chain_match.end() - 1)
            if not chain_call:
                continue
            details = _extract_js_handler_details(
                _split_top_level_args(chain_call[1:-1])
            )
            for prefix in _resolve_js_prefixes(obj, mounts):
                full_path = _join_route_path(prefix, base_path)
                key = f"{method}:{full_path}:{line_num}"
                if key in seen:
                    continue
                seen.add(key)
                endpoints.append(
                    APIEndpoint(
                        method=method,
                        path=full_path,
                        handler=details["handler"],
                        file=str(path),
                        line=line_num,
                        middleware=details["middleware"],
                    )
                )

    return endpoints


# ─────────────────────────────────────────────────────────────────────────────
# Fastify (dedicated — schema-based routes, register plugins, etc.)
# ─────────────────────────────────────────────────────────────────────────────

_FASTIFY_METHOD = re.compile(
    r"""(?:fastify|server|app|instance|\w+)\s*\.\s*"""
    r"""(get|post|put|patch|delete|head|options)\s*\(\s*"""
    r"""['"`]([^'"`]+)['"`]""",
    re.IGNORECASE | re.MULTILINE,
)


def _detect_fastify(path: Path, content: str) -> list[APIEndpoint]:
    if "fastify" not in content.lower() and "Fastify" not in content:
        return []

    endpoints: list[APIEndpoint] = []
    seen: set[str] = set()
    plugin_aliases = _extract_fastify_plugin_aliases(content)
    mounts = _extract_fastify_mounts(content, plugin_aliases)

    # Method shorthand: fastify.get('/path', handler)
    for m in _JS_ROUTE_CALL.finditer(content):
        obj, method = m.group(1), m.group(2).upper()
        if obj not in mounts and obj.lower() not in {
            "fastify",
            "server",
            "app",
            "instance",
        }:
            continue
        call_text = _extract_balanced_segment(content, m.end() - 1)
        if not call_text:
            continue
        args = _split_top_level_args(call_text[1:-1])
        if not args:
            continue
        route_path = _parse_string_arg(args[0])
        if route_path is None:
            continue
        details = _extract_js_handler_details(args[1:])
        schema = _extract_fastify_schema_from_args(args[1:])
        line_num = content[: m.start()].count("\n") + 1
        for prefix in _resolve_js_prefixes(obj, mounts):
            full_path = _join_route_path(prefix, route_path)
            key = f"{method}:{full_path}:{line_num}"
            if key in seen:
                continue
            seen.add(key)
            endpoints.append(
                APIEndpoint(
                    method=method,
                    path=full_path,
                    handler=details["handler"],
                    file=str(path),
                    line=line_num,
                    middleware=details["middleware"],
                    request_body=schema.get("body", ""),
                    response_type=schema.get("response", ""),
                )
            )

    # fastify.route({ method, url, ... }) syntax
    for m in _FASTIFY_ROUTE_CALL.finditer(content):
        obj = m.group(1)
        if obj not in mounts and obj.lower() not in {
            "fastify",
            "server",
            "app",
            "instance",
        }:
            continue
        call_text = _extract_balanced_segment(content, m.end() - 1)
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
        schema = _extract_fastify_schema(body, 0)
        line_num = content[: m.start()].count("\n") + 1
        for prefix in _resolve_js_prefixes(obj, mounts):
            full_path = _join_route_path(prefix, route_path)
            key = f"{method}:{full_path}:{line_num}"
            if key in seen:
                continue
            seen.add(key)
            endpoints.append(
                APIEndpoint(
                    method=method,
                    path=full_path,
                    handler=handler_match.group(1) if handler_match else "route()",
                    file=str(path),
                    line=line_num,
                    request_body=schema.get("body", ""),
                    response_type=schema.get("response", ""),
                )
            )

    return endpoints


def _extract_fastify_schema(content: str, start_pos: int) -> dict:
    """Try to extract Fastify JSON schema from route options."""
    region = content[start_pos : start_pos + 1000]
    schema = {}
    body_match = re.search(r"body\s*:\s*(\{.*?\})", region, re.DOTALL)
    if body_match:
        schema["body"] = body_match.group(1)[:200]
    resp_match = re.search(r"response\s*:\s*(\{.*?\})", region, re.DOTALL)
    if resp_match:
        schema["response"] = resp_match.group(1)[:200]
    return schema


def _extract_fastify_schema_from_args(args: list[str]) -> dict[str, str]:
    for arg in args:
        stripped = arg.strip()
        if stripped.startswith("{"):
            return _extract_fastify_schema(stripped, 0)
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# NestJS decorators
# ─────────────────────────────────────────────────────────────────────────────

_NESTJS_CONTROLLER = re.compile(r"@Controller\s*\(\s*['\"](.*?)['\"]\s*\)")
_NESTJS_METHOD = re.compile(
    r"@(Get|Post|Put|Patch|Delete|All|Options|Head)\s*\(\s*(?:['\"](.*?)['\"])?\s*\)"
)


def _detect_nestjs(path: Path, content: str) -> list[APIEndpoint]:
    if "@Controller" not in content:
        return []

    endpoints = []
    # Find controller base path
    ctrl_match = _NESTJS_CONTROLLER.search(content)
    base_path = ctrl_match.group(1) if ctrl_match else ""
    if base_path and not base_path.startswith("/"):
        base_path = "/" + base_path

    lines = content.splitlines()
    for m in _NESTJS_METHOD.finditer(content):
        method = m.group(1).upper()
        sub_path = m.group(2) or ""
        if sub_path and not sub_path.startswith("/"):
            sub_path = "/" + sub_path
        full_path = base_path + sub_path
        line_num = content[: m.start()].count("\n") + 1

        # Find the method name on the next non-decorator line
        handler = ""
        for i in range(line_num, min(line_num + 5, len(lines))):
            line = lines[i].strip() if i < len(lines) else ""
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
                file=str(path),
                line=line_num,
            )
        )
    return endpoints


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI
# ─────────────────────────────────────────────────────────────────────────────

_FASTAPI_ROUTE = re.compile(
    r"""@(?:app|router)\s*\.\s*"""
    r"""(get|post|put|patch|delete|options|head)\s*\(\s*"""
    r"""['"]([^'"]+)['"]""",
    re.IGNORECASE | re.MULTILINE,
)

_FASTAPI_INCLUDE_ROUTER = re.compile(r"""app\.include_router\s*\(\s*(\w+)""")


def _detect_fastapi(path: Path, content: str) -> list[APIEndpoint]:
    if (
        "fastapi" not in content.lower()
        and "@app." not in content
        and "@router." not in content
    ):
        return []

    endpoints = []
    lines = content.splitlines()
    for m in _FASTAPI_ROUTE.finditer(content):
        method, route_path = m.group(1).upper(), m.group(2)
        line_num = content[: m.start()].count("\n") + 1

        # Find function name after the decorator
        handler = ""
        docstring = ""
        for i in range(line_num, min(line_num + 5, len(lines))):
            line = lines[i].strip() if i < len(lines) else ""
            if line.startswith(("def ", "async def ")):
                fn_match = re.match(r"(?:async\s+)?def\s+(\w+)\s*\(", line)
                if fn_match:
                    handler = fn_match.group(1)
                # Check for docstring
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line.startswith(('"""', "'''")):
                        docstring = next_line.strip("\"' ")[:200]
                break

        # Try to extract response model
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
                file=str(path),
                line=line_num,
                description=docstring,
                response_type=response_type,
            )
        )
    return endpoints


# ─────────────────────────────────────────────────────────────────────────────
# Flask
# ─────────────────────────────────────────────────────────────────────────────

_FLASK_ROUTE = re.compile(
    r"""@(?:app|bp|blueprint)\s*\.route\s*\(\s*"""
    r"""['"]([^'"]+)['"]"""
    r"""(?:\s*,\s*methods\s*=\s*\[([^\]]+)\])?""",
    re.IGNORECASE | re.MULTILINE,
)


def _detect_flask(path: Path, content: str) -> list[APIEndpoint]:
    if (
        "flask" not in content.lower()
        and "@app.route" not in content
        and ".route(" not in content
    ):
        return []

    endpoints = []
    lines = content.splitlines()
    for m in _FLASK_ROUTE.finditer(content):
        route_path = m.group(1)
        methods_str = m.group(2)
        if methods_str:
            methods = [m.strip().strip("'\"").upper() for m in methods_str.split(",")]
        else:
            methods = ["GET"]

        line_num = content[: m.start()].count("\n") + 1
        handler = ""
        for i in range(line_num, min(line_num + 5, len(lines))):
            line = lines[i].strip() if i < len(lines) else ""
            if line.startswith("def "):
                fn_match = re.match(r"def\s+(\w+)\s*\(", line)
                if fn_match:
                    handler = fn_match.group(1)
                break

        for method in methods:
            endpoints.append(
                APIEndpoint(
                    method=method,
                    path=route_path,
                    handler=handler,
                    file=str(path),
                    line=line_num,
                )
            )
    return endpoints


# ─────────────────────────────────────────────────────────────────────────────
# Falcon
# ─────────────────────────────────────────────────────────────────────────────

_FALCON_ADD_ROUTE = re.compile(
    r"""(?:app|api)\s*\.\s*add_route\s*\(\s*['"]([^'"]+)['"]\s*,\s*(\w+(?:\(\))?)\s*\)""",
    re.MULTILINE,
)

_FALCON_RESPONDER = re.compile(
    r"""def\s+(on_(?:get|post|put|patch|delete|head|options))\s*\(\s*self""",
    re.IGNORECASE,
)


def _detect_falcon(path: Path, content: str) -> list[APIEndpoint]:
    if "falcon" not in content.lower() and "add_route" not in content:
        return []

    endpoints = []
    lines = content.splitlines()

    # app.add_route('/things', ThingsResource())
    for m in _FALCON_ADD_ROUTE.finditer(content):
        route_path, resource_class = m.group(1), m.group(2).rstrip("()")
        line_num = content[: m.start()].count("\n") + 1

        # Try to find the resource class and its responders
        methods = _find_falcon_responders(content, resource_class)
        if methods:
            for method in methods:
                endpoints.append(
                    APIEndpoint(
                        method=method,
                        path=route_path,
                        handler=f"{resource_class}.on_{method.lower()}",
                        file=str(path),
                        line=line_num,
                    )
                )
        else:
            # Can't determine methods, add as ANY
            endpoints.append(
                APIEndpoint(
                    method="ANY",
                    path=route_path,
                    handler=resource_class,
                    file=str(path),
                    line=line_num,
                )
            )

    # Also detect responder methods in resource classes (for when the route
    # is defined in a separate file and no add_route is present in this file)
    if (
        not endpoints
        and "class " in content
        and ("on_get" in content or "on_post" in content)
    ):
        # Only add standalone responders if we found no add_route calls
        all_classes = re.finditer(r"class\s+(\w+)", content)
        for cls_match in all_classes:
            class_name = cls_match.group(1)
            class_methods = _find_falcon_responders(content, class_name)
            for http_method in class_methods:
                method_name = f"on_{http_method.lower()}"
                endpoints.append(
                    APIEndpoint(
                        method=http_method,
                        path=f"(see add_route for {class_name})",
                        handler=f"{class_name}.{method_name}",
                        file=str(path),
                        line=0,
                    )
                )

    return endpoints


def _find_falcon_responders(content: str, class_name: str) -> list[str]:
    """Find all on_* methods in a Falcon resource class."""
    methods = []
    # Look for the class definition
    class_pattern = re.compile(
        rf"class\s+{re.escape(class_name)}\b.*?(?=\nclass\s|\Z)",
        re.DOTALL,
    )
    class_match = class_pattern.search(content)
    if class_match:
        class_body = class_match.group(0)
        for m in _FALCON_RESPONDER.finditer(class_body):
            method_name = m.group(1)
            http_method = method_name.replace("on_", "").upper()
            methods.append(http_method)
    return methods


# ─────────────────────────────────────────────────────────────────────────────
# Django (urls.py)
# ─────────────────────────────────────────────────────────────────────────────

_DJANGO_PATH = re.compile(
    r"""\b(path|re_path)\s*\(""",
    re.MULTILINE,
)


def _detect_django(path: Path, content: str) -> list[APIEndpoint]:
    if (
        "urlpatterns" not in content
        and "path(" not in content
        and "re_path(" not in content
        and ".register(" not in content
    ):
        return []

    endpoints: list[APIEndpoint] = []
    function_methods = _extract_django_function_methods(content)
    class_views = _extract_django_class_views(content)
    routers = _extract_django_router_endpoints(content, class_views)

    for m in _DJANGO_PATH.finditer(content):
        route_type = m.group(1)
        call_text = _extract_balanced_segment(content, m.end() - 1)
        if not call_text:
            continue
        args = _split_top_level_args(call_text[1:-1])
        if len(args) < 2:
            continue
        raw_path = _parse_string_arg(args[0])
        if raw_path is None:
            continue
        route_path = _normalize_django_route(raw_path, is_regex=route_type == "re_path")
        handler_expr = args[1].strip()
        line_num = content[: m.start()].count("\n") + 1

        include_router = _extract_django_include_router(handler_expr)
        if include_router and include_router in routers:
            for ep in routers[include_router]:
                endpoints.append(
                    APIEndpoint(
                        method=ep.method,
                        path=_join_route_path(route_path, ep.path),
                        handler=ep.handler,
                        file=str(path),
                        line=line_num,
                        description=ep.description,
                    )
                )
            continue

        methods = _infer_django_handler_methods(
            handler_expr, function_methods, class_views
        )
        handler = _extract_django_handler_name(handler_expr)
        for method in methods:
            endpoints.append(
                APIEndpoint(
                    method=method,
                    path=route_path,
                    handler=handler,
                    file=str(path),
                    line=line_num,
                )
            )

    if not endpoints and routers:
        for router_eps in routers.values():
            endpoints.extend(router_eps)

    return endpoints


# ─────────────────────────────────────────────────────────────────────────────
# Go (gin, echo, fiber, chi, net/http)
# ─────────────────────────────────────────────────────────────────────────────

_GO_ROUTE = re.compile(
    r"""(?:r|router|e|engine|app|g|group|api|v\d+)\s*\.\s*"""
    r"""(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|Any|Handle)\s*\(\s*"""
    r"""['"]([^'"]+)['"]""",
    re.IGNORECASE | re.MULTILINE,
)

_GO_HANDLEFUNC = re.compile(
    r"""(?:http|mux|r|router)\s*\.\s*HandleFunc\s*\(\s*"""
    r"""['"]([^'"]+)['"]""",
    re.MULTILINE,
)

_GO_FIBER = re.compile(
    r"""(?:app|group|api|v\d+)\s*\.\s*"""
    r"""(Get|Post|Put|Patch|Delete|All)\s*\(\s*"""
    r"""['"]([^'"]+)['"]""",
    re.MULTILINE,
)


def _detect_go_routes(path: Path, content: str) -> list[APIEndpoint]:
    endpoints = []
    lines = content.splitlines()

    # Gin / Echo style
    for m in _GO_ROUTE.finditer(content):
        method, route_path = m.group(1).upper(), m.group(2)
        line_num = content[: m.start()].count("\n") + 1
        handler = _find_go_handler(lines, line_num - 1, content, m.end())
        endpoints.append(
            APIEndpoint(
                method=method,
                path=route_path,
                handler=handler,
                file=str(path),
                line=line_num,
            )
        )

    # net/http HandleFunc style
    for m in _GO_HANDLEFUNC.finditer(content):
        route_path = m.group(1)
        line_num = content[: m.start()].count("\n") + 1
        endpoints.append(
            APIEndpoint(
                method="ANY",
                path=route_path,
                handler="HandleFunc",
                file=str(path),
                line=line_num,
            )
        )

    # Fiber style
    for m in _GO_FIBER.finditer(content):
        method, route_path = m.group(1).upper(), m.group(2)
        line_num = content[: m.start()].count("\n") + 1
        handler = _find_go_handler(lines, line_num - 1, content, m.end())
        endpoints.append(
            APIEndpoint(
                method=method,
                path=route_path,
                handler=handler,
                file=str(path),
                line=line_num,
            )
        )

    return endpoints


def _find_go_handler(lines, line_idx, content, match_end):
    """Extract handler function name from Go route definition."""
    # Look for the handler argument after the path
    remaining = content[match_end : match_end + 200]
    fn_match = re.search(r",\s*(\w+(?:\.\w+)*)\s*[,)]", remaining)
    if fn_match:
        return fn_match.group(1)
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Laravel (PHP)
# ─────────────────────────────────────────────────────────────────────────────

_LARAVEL_ROUTE = re.compile(
    r"""Route\s*::\s*(get|post|put|patch|delete|any|match|options)\s*\(\s*"""
    r"""['"]([^'"]+)['"]""",
    re.IGNORECASE | re.MULTILINE,
)

_LARAVEL_RESOURCE = re.compile(
    r"""Route\s*::\s*(?:api)?resource\s*\(\s*"""
    r"""['"]([^'"]+)['"]""",
    re.IGNORECASE | re.MULTILINE,
)

_LARAVEL_CONTROLLER = re.compile(
    r"""['"]([\w\\]+Controller)(?:@(\w+))?['"]""",
)

# Laravel 4 / Route::group prefix detection
_LARAVEL_GROUP = re.compile(
    r"""Route\s*::\s*group\s*\(\s*(?:array\s*\(|)"""
    r"""[^)]*?['"]prefix['"]\s*(?:=>|:)\s*['"]([^'"]+)['"]""",
    re.IGNORECASE | re.DOTALL,
)


def _detect_laravel(path: Path, content: str) -> list[APIEndpoint]:
    if "Route::" not in content:
        return []

    endpoints = []
    lines = content.splitlines()

    # Build prefix map: char_offset → prefix string
    # Handles Route::group(array('prefix' => 'soul'), function() { ... })
    group_prefixes = _build_laravel_group_prefixes(content)

    # Regular routes
    for m in _LARAVEL_ROUTE.finditer(content):
        method, route_path = m.group(1).upper(), m.group(2)
        line_num = content[: m.start()].count("\n") + 1

        # Resolve prefix from enclosing Route::group
        prefix = _resolve_prefix(m.start(), group_prefixes, content)
        if prefix:
            route_path = prefix.rstrip("/") + "/" + route_path.lstrip("/")
        if not route_path.startswith("/"):
            route_path = "/" + route_path

        # Find controller/handler — supports both modern and Laravel 4 array syntax
        handler_region = content[m.start() : m.start() + 500]
        ctrl_match = _LARAVEL_CONTROLLER.search(handler_region)
        handler = (
            f"{ctrl_match.group(1)}@{ctrl_match.group(2)}"
            if ctrl_match and ctrl_match.group(2)
            else (ctrl_match.group(1) if ctrl_match else "")
        )

        # Find middleware — both ->middleware() and 'before'/'middleware' in array
        middleware = []
        mw_match = re.search(r"->middleware\s*\(\s*\[?([^\])\n]+)", handler_region)
        if mw_match:
            middleware = [m.strip().strip("'\"") for m in mw_match.group(1).split(",")]
        else:
            # Laravel 4: 'before' => 'auth|admin'
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
                file=str(path),
                line=line_num,
                middleware=middleware,
            )
        )

    # Resource routes (expands to standard CRUD)
    for m in _LARAVEL_RESOURCE.finditer(content):
        resource = m.group(1)
        line_num = content[: m.start()].count("\n") + 1
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
                    file=str(path),
                    line=line_num,
                )
            )

    return endpoints


# ─────────────────────────────────────────────────────────────────────────────
# Laravel group prefix helpers
# ─────────────────────────────────────────────────────────────────────────────


def _build_laravel_group_prefixes(content: str) -> list[tuple[int, int, str]]:
    """Build list of (start, end, prefix) for each Route::group in the file.

    Uses brace counting to find the closing } of each group's closure.
    """
    groups = []
    for m in _LARAVEL_GROUP.finditer(content):
        prefix = m.group(1)
        # Find the opening { of the closure after the group call
        brace_start = content.find("{", m.end())
        if brace_start == -1:
            continue
        # Count braces to find matching close
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


def _resolve_prefix(
    offset: int, groups: list[tuple[int, int, str]], content: str
) -> str:
    """Resolve the full prefix for a route at the given offset.

    Handles nested groups by concatenating prefixes from outermost to innermost.
    """
    prefixes = []
    for start, end, prefix in groups:
        if start < offset < end:
            prefixes.append(prefix)
    if not prefixes:
        return ""
    return "/" + "/".join(p.strip("/") for p in prefixes)


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────


def _find_handler_name(lines: list[str], line_idx: int) -> str:
    """Try to find handler function name from route line."""
    if line_idx < len(lines):
        line = lines[line_idx]
        # Look for last argument that's a function name
        fn_match = re.search(r",\s*(\w+)\s*\)?\s*;?\s*$", line)
        if fn_match:
            return fn_match.group(1)
    return ""


def _find_middleware(lines: list[str], line_idx: int) -> list[str]:
    """Detect Express-style middleware."""
    if line_idx < len(lines):
        line = lines[line_idx]
        # Express: app.get('/path', auth, validate, handler)
        parts = re.findall(r",\s*(\w+)", line)
        if len(parts) > 1:
            return parts[:-1]  # everything except the last one (handler)
    return []


def _extract_balanced_segment(
    content: str, start_idx: int, open_char: str = "(", close_char: str = ")"
) -> str:
    """Return the balanced segment beginning at start_idx, including delimiters."""
    if start_idx < 0 or start_idx >= len(content) or content[start_idx] != open_char:
        return ""

    depth = 0
    quote = ""
    escape = False
    for idx in range(start_idx, len(content)):
        ch = content[idx]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
            continue
        if ch in {'"', "'", "`"}:
            quote = ch
            continue
        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return content[start_idx : idx + 1]
    return ""


def _split_top_level_args(text: str) -> list[str]:
    """Split a comma-delimited argument list, ignoring nested structures."""
    args: list[str] = []
    buf: list[str] = []
    stack: list[str] = []
    quote = ""
    escape = False

    for ch in text:
        if quote:
            buf.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
            continue

        if ch in {'"', "'", "`"}:
            quote = ch
            buf.append(ch)
            continue

        if ch in "([{":
            stack.append(ch)
            buf.append(ch)
            continue
        if ch in ")]}":
            if stack:
                stack.pop()
            buf.append(ch)
            continue
        if ch == "," and not stack:
            arg = "".join(buf).strip()
            if arg:
                args.append(arg)
            buf = []
            continue
        buf.append(ch)

    tail = "".join(buf).strip()
    if tail:
        args.append(tail)
    return args


def _parse_string_arg(arg: str) -> str | None:
    stripped = arg.strip()
    if (
        len(stripped) >= 2
        and stripped[0] in {'"', "'", "`"}
        and stripped[-1] == stripped[0]
    ):
        return stripped[1:-1]
    if (
        len(stripped) >= 3
        and stripped[0] in {"r", "u"}
        and stripped[1] in {'"', "'"}
        and stripped[-1] == stripped[1]
    ):
        return stripped[2:-1]
    return None


def _extract_js_mounts(content: str) -> dict[str, list[tuple[str, str]]]:
    mounts: dict[str, list[tuple[str, str]]] = {}
    for match in _JS_USE_CALL.finditer(content):
        parent = match.group(1)
        call_text = _extract_balanced_segment(content, match.end() - 1)
        if not call_text:
            continue
        args = _split_top_level_args(call_text[1:-1])
        if len(args) < 2:
            continue
        prefix = _parse_string_arg(args[0])
        child_match = re.match(r"""(\w+)""", args[1].strip())
        if prefix is None or not child_match:
            continue
        mounts.setdefault(child_match.group(1), []).append((parent, prefix))
    return mounts


def _resolve_js_prefixes(
    obj: str,
    mounts: dict[str, list[tuple[str, str]]],
    memo: dict[str, list[str]] | None = None,
    stack: set[str] | None = None,
) -> list[str]:
    if memo is None:
        memo = {}
    if stack is None:
        stack = set()
    if obj in memo:
        return memo[obj]
    if obj in stack:
        return [""]
    stack.add(obj)

    links = mounts.get(obj, [])
    if not links:
        memo[obj] = [""]
        stack.discard(obj)
        return memo[obj]

    prefixes: list[str] = []
    for parent, prefix in links:
        for parent_prefix in _resolve_js_prefixes(parent, mounts, memo, stack):
            prefixes.append(_join_route_path(parent_prefix, prefix))

    stack.discard(obj)
    memo[obj] = prefixes or [""]
    return memo[obj]


def _join_route_path(*parts: str) -> str:
    cleaned = [p.strip() for p in parts if p and p.strip()]
    if not cleaned:
        return "/"
    joined = "/" + "/".join(part.strip("/") for part in cleaned if part.strip("/"))
    return re.sub(r"/+", "/", joined) or "/"


def _extract_js_handler_details(args: list[str]) -> dict[str, list[str] | str]:
    identifiers: list[str] = []
    for arg in args:
        stripped = arg.strip()
        if not stripped or stripped.startswith("{") or stripped.startswith("["):
            continue
        if "=>" in stripped or stripped.startswith("function"):
            identifiers.append("inline_handler")
            continue
        match = re.match(r"""(\w+(?:\.\w+)*)""", stripped)
        if match:
            identifiers.append(match.group(1))

    if not identifiers:
        return {"handler": "", "middleware": []}
    if len(identifiers) == 1:
        return {"handler": identifiers[0], "middleware": []}
    return {"handler": identifiers[-1], "middleware": identifiers[:-1]}


def _extract_fastify_plugin_aliases(content: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for match in _FASTIFY_PLUGIN_FUNCTION.finditer(content):
        aliases[match.group(1)] = match.group(2)
    for match in _FASTIFY_PLUGIN_ARROW.finditer(content):
        aliases[match.group(1)] = match.group(2) or match.group(3) or "instance"
    return aliases


def _extract_fastify_mounts(
    content: str, plugin_aliases: dict[str, str]
) -> dict[str, list[tuple[str, str]]]:
    mounts: dict[str, list[tuple[str, str]]] = {}
    for match in _FASTIFY_REGISTER_CALL.finditer(content):
        parent = match.group(1)
        call_text = _extract_balanced_segment(content, match.end() - 1)
        if not call_text:
            continue
        args = _split_top_level_args(call_text[1:-1])
        if not args:
            continue
        plugin_name_match = re.match(r"""(\w+)""", args[0].strip())
        if not plugin_name_match:
            continue
        plugin_name = plugin_name_match.group(1)
        child_alias = plugin_aliases.get(plugin_name)
        if not child_alias:
            continue
        prefix = ""
        for arg in args[1:]:
            prefix_match = re.search(r"""prefix\s*:\s*['\"]([^'\"]+)['\"]""", arg)
            if prefix_match:
                prefix = prefix_match.group(1)
                break
        mounts.setdefault(child_alias, []).append((parent, prefix))
    return mounts


def _extract_django_handler_name(handler_expr: str) -> str:
    if ".as_view" in handler_expr:
        return handler_expr.split(".as_view", 1)[0].split(".")[-1]
    return handler_expr.split(".")[-1].split("(", 1)[0].strip()


def _extract_django_function_methods(content: str) -> dict[str, list[str]]:
    methods: dict[str, list[str]] = {}
    decorator = None
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


def _extract_django_class_views(content: str) -> dict[str, dict[str, object]]:
    views: dict[str, dict[str, object]] = {}
    class_pattern = re.compile(
        r"""class\s+(\w+)\s*\(([^)]*)\)\s*:\s*(.*?)(?=^class\s+|\Z)""",
        re.MULTILINE | re.DOTALL,
    )
    for match in class_pattern.finditer(content):
        class_name, bases, body = match.group(1), match.group(2), match.group(3)
        http_methods = {
            method.upper()
            for method in re.findall(
                r"""^\s*def\s+(get|post|put|patch|delete|options|head)\s*\(""",
                body,
                re.MULTILINE | re.IGNORECASE,
            )
        }
        action_routes: list[dict[str, object]] = []
        action_pattern = re.compile(
            r"""@action\s*\((.*?)\)\s*\n\s*def\s+(\w+)\s*\(""",
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
            "is_viewset": "ViewSet" in bases,
            "actions": action_routes,
            "crud_methods": {
                name
                for name in re.findall(
                    r"""^\s*def\s+(list|retrieve|create|update|partial_update|destroy)\s*\(""",
                    body,
                    re.MULTILINE,
                )
            },
        }
    return views


def _extract_django_router_endpoints(
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
        collection_path = _join_route_path(base_path)
        detail_path = _join_route_path(base_path, "{id}")
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
            action_path = _join_route_path(
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


def _extract_django_include_router(handler_expr: str) -> str | None:
    match = re.search(r"""include\s*\(\s*(\w+)\.urls""", handler_expr)
    return match.group(1) if match else None


def _infer_django_handler_methods(
    handler_expr: str,
    function_methods: dict[str, list[str]],
    class_views: dict[str, dict[str, object]],
) -> list[str]:
    as_view_mapping = re.search(r"""\.as_view\s*\(\s*\{([^}]*)\}\s*\)""", handler_expr)
    if as_view_mapping:
        mapped = re.findall(
            r"""['\"](get|post|put|patch|delete|options|head)['\"]\s*:""",
            as_view_mapping.group(1),
            re.IGNORECASE,
        )
        return [method.upper() for method in mapped] or ["ANY"]

    if ".as_view" in handler_expr:
        class_name = _extract_django_handler_name(handler_expr)
        methods = class_views.get(class_name, {}).get("http_methods", [])
        return methods or ["ANY"]

    handler_name = _extract_django_handler_name(handler_expr)
    return function_methods.get(handler_name, ["ANY"])


def _normalize_django_route(route: str, *, is_regex: bool) -> str:
    if not is_regex:
        return _join_route_path(route)
    normalized = route.strip()
    normalized = normalized.lstrip("r")
    normalized = normalized.lstrip("^").rstrip("$")
    normalized = re.sub(r"""\(\?P<(\w+)>[^)]+\)""", r"{\1}", normalized)
    normalized = re.sub(r"""\[[^\]]+\]\+?""", "{param}", normalized)
    normalized = normalized.replace("\\/", "/")
    normalized = normalized.replace("\\", "")
    return _join_route_path(normalized)
