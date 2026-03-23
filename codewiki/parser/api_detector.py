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

    method: str              # GET, POST, PUT, DELETE, PATCH, etc.
    path: str                # /api/v2/users/:id
    handler: str = ""        # function name or controller method
    file: str = ""           # source file path
    line: int = 0            # line number
    description: str = ""    # inline comment or docstring
    middleware: list[str] = field(default_factory=list)
    request_body: str = ""   # inferred from decorators/types
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
        "vue": [_detect_express, _detect_fastify],  # Vue script blocks may define routes
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

_EXPRESS_ROUTE = re.compile(
    r"""(?:app|router|server|route|api)\s*\.\s*"""
    r"""(get|post|put|patch|delete|all|options|head)\s*\(\s*"""
    r"""['"`]([^'"`]+)['"`]""",
    re.IGNORECASE | re.MULTILINE,
)

_FASTIFY_ROUTE = re.compile(
    r"""(?:fastify|server|app)\s*\.\s*"""
    r"""(get|post|put|patch|delete)\s*\(\s*"""
    r"""['"`]([^'"`]+)['"`]""",
    re.IGNORECASE | re.MULTILINE,
)


def _detect_express(path: Path, content: str) -> list[APIEndpoint]:
    endpoints = []
    lines = content.splitlines()
    for pattern in [_EXPRESS_ROUTE, _FASTIFY_ROUTE]:
        for m in pattern.finditer(content):
            method, route_path = m.group(1).upper(), m.group(2)
            line_num = content[:m.start()].count("\n") + 1
            handler = _find_handler_name(lines, line_num - 1)
            endpoints.append(APIEndpoint(
                method=method,
                path=route_path,
                handler=handler,
                file=str(path),
                line=line_num,
                middleware=_find_middleware(lines, line_num - 1),
            ))
    return endpoints


# ─────────────────────────────────────────────────────────────────────────────
# Fastify (dedicated — schema-based routes, register plugins, etc.)
# ─────────────────────────────────────────────────────────────────────────────

_FASTIFY_METHOD = re.compile(
    r"""(?:fastify|server|app|instance)\s*\.\s*"""
    r"""(get|post|put|patch|delete|head|options)\s*\(\s*"""
    r"""['"`]([^'"`]+)['"`]""",
    re.IGNORECASE | re.MULTILINE,
)

_FASTIFY_ROUTE_OPTS = re.compile(
    r"""(?:fastify|server|app|instance)\s*\.route\s*\(\s*\{[^}]*"""
    r"""method\s*:\s*['"](\w+)['"][^}]*"""
    r"""url\s*:\s*['"]([^'"]+)['"]""",
    re.IGNORECASE | re.DOTALL,
)

_FASTIFY_ROUTE_OPTS_ALT = re.compile(
    r"""(?:fastify|server|app|instance)\s*\.route\s*\(\s*\{[^}]*"""
    r"""url\s*:\s*['"]([^'"]+)['"][^}]*"""
    r"""method\s*:\s*['"](\w+)['"]""",
    re.IGNORECASE | re.DOTALL,
)


def _detect_fastify(path: Path, content: str) -> list[APIEndpoint]:
    if "fastify" not in content.lower() and "Fastify" not in content:
        return []

    endpoints = []
    seen = set()
    lines = content.splitlines()

    # Method shorthand: fastify.get('/path', handler)
    for m in _FASTIFY_METHOD.finditer(content):
        method, route_path = m.group(1).upper(), m.group(2)
        key = f"{method}:{route_path}"
        if key in seen:
            continue
        seen.add(key)
        line_num = content[:m.start()].count("\n") + 1

        # Check for schema in options
        schema = _extract_fastify_schema(content, m.end())
        handler = _find_handler_name(lines, line_num - 1)

        endpoints.append(APIEndpoint(
            method=method,
            path=route_path,
            handler=handler,
            file=str(path),
            line=line_num,
            request_body=schema.get("body", ""),
            response_type=schema.get("response", ""),
        ))

    # fastify.route({ method, url, ... }) syntax
    for pattern in [_FASTIFY_ROUTE_OPTS, _FASTIFY_ROUTE_OPTS_ALT]:
        for m in pattern.finditer(content):
            if pattern == _FASTIFY_ROUTE_OPTS_ALT:
                route_path, method = m.group(1), m.group(2).upper()
            else:
                method, route_path = m.group(1).upper(), m.group(2)
            key = f"{method}:{route_path}"
            if key in seen:
                continue
            seen.add(key)
            line_num = content[:m.start()].count("\n") + 1
            endpoints.append(APIEndpoint(
                method=method,
                path=route_path,
                handler="route()",
                file=str(path),
                line=line_num,
            ))

    return endpoints


def _extract_fastify_schema(content: str, start_pos: int) -> dict:
    """Try to extract Fastify JSON schema from route options."""
    region = content[start_pos:start_pos + 1000]
    schema = {}
    body_match = re.search(r"body\s*:\s*\{([^}]+)\}", region)
    if body_match:
        schema["body"] = body_match.group(0)[:200]
    resp_match = re.search(r"response\s*:\s*\{([^}]+)\}", region)
    if resp_match:
        schema["response"] = resp_match.group(0)[:200]
    return schema


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
        line_num = content[:m.start()].count("\n") + 1

        # Find the method name on the next non-decorator line
        handler = ""
        for i in range(line_num, min(line_num + 5, len(lines))):
            line = lines[i].strip() if i < len(lines) else ""
            if line and not line.startswith("@"):
                fn_match = re.match(r"(?:async\s+)?(\w+)\s*\(", line)
                if fn_match:
                    handler = fn_match.group(1)
                break

        endpoints.append(APIEndpoint(
            method=method,
            path=full_path or "/",
            handler=handler,
            file=str(path),
            line=line_num,
        ))
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

_FASTAPI_INCLUDE_ROUTER = re.compile(
    r"""app\.include_router\s*\(\s*(\w+)"""
)


def _detect_fastapi(path: Path, content: str) -> list[APIEndpoint]:
    if "fastapi" not in content.lower() and "@app." not in content and "@router." not in content:
        return []

    endpoints = []
    lines = content.splitlines()
    for m in _FASTAPI_ROUTE.finditer(content):
        method, route_path = m.group(1).upper(), m.group(2)
        line_num = content[:m.start()].count("\n") + 1

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

        endpoints.append(APIEndpoint(
            method=method,
            path=route_path,
            handler=handler,
            file=str(path),
            line=line_num,
            description=docstring,
            response_type=response_type,
        ))
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
    if "flask" not in content.lower() and "@app.route" not in content and ".route(" not in content:
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

        line_num = content[:m.start()].count("\n") + 1
        handler = ""
        for i in range(line_num, min(line_num + 5, len(lines))):
            line = lines[i].strip() if i < len(lines) else ""
            if line.startswith("def "):
                fn_match = re.match(r"def\s+(\w+)\s*\(", line)
                if fn_match:
                    handler = fn_match.group(1)
                break

        for method in methods:
            endpoints.append(APIEndpoint(
                method=method,
                path=route_path,
                handler=handler,
                file=str(path),
                line=line_num,
            ))
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
        line_num = content[:m.start()].count("\n") + 1

        # Try to find the resource class and its responders
        methods = _find_falcon_responders(content, resource_class)
        if methods:
            for method in methods:
                endpoints.append(APIEndpoint(
                    method=method,
                    path=route_path,
                    handler=f"{resource_class}.on_{method.lower()}",
                    file=str(path),
                    line=line_num,
                ))
        else:
            # Can't determine methods, add as ANY
            endpoints.append(APIEndpoint(
                method="ANY",
                path=route_path,
                handler=resource_class,
                file=str(path),
                line=line_num,
            ))

    # Also detect responder methods in resource classes (for when the route
    # is defined in a separate file and no add_route is present in this file)
    if not endpoints and "class " in content and ("on_get" in content or "on_post" in content):
        # Only add standalone responders if we found no add_route calls
        all_classes = re.finditer(r"class\s+(\w+)", content)
        for cls_match in all_classes:
            class_name = cls_match.group(1)
            class_methods = _find_falcon_responders(content, class_name)
            for http_method in class_methods:
                method_name = f"on_{http_method.lower()}"
                endpoints.append(APIEndpoint(
                    method=http_method,
                    path=f"(see add_route for {class_name})",
                    handler=f"{class_name}.{method_name}",
                    file=str(path),
                    line=0,
                ))

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
    r"""path\s*\(\s*['"]([^'"]*)['"]\s*,\s*(\w+(?:\.\w+)*)""",
    re.MULTILINE,
)


def _detect_django(path: Path, content: str) -> list[APIEndpoint]:
    if "urlpatterns" not in content and "path(" not in content:
        return []

    endpoints = []
    for m in _DJANGO_PATH.finditer(content):
        route_path = "/" + m.group(1) if not m.group(1).startswith("/") else m.group(1)
        handler = m.group(2)
        line_num = content[:m.start()].count("\n") + 1
        endpoints.append(APIEndpoint(
            method="ANY",
            path=route_path,
            handler=handler,
            file=str(path),
            line=line_num,
        ))
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
        line_num = content[:m.start()].count("\n") + 1
        handler = _find_go_handler(lines, line_num - 1, content, m.end())
        endpoints.append(APIEndpoint(
            method=method,
            path=route_path,
            handler=handler,
            file=str(path),
            line=line_num,
        ))

    # net/http HandleFunc style
    for m in _GO_HANDLEFUNC.finditer(content):
        route_path = m.group(1)
        line_num = content[:m.start()].count("\n") + 1
        endpoints.append(APIEndpoint(
            method="ANY",
            path=route_path,
            handler="HandleFunc",
            file=str(path),
            line=line_num,
        ))

    # Fiber style
    for m in _GO_FIBER.finditer(content):
        method, route_path = m.group(1).upper(), m.group(2)
        line_num = content[:m.start()].count("\n") + 1
        handler = _find_go_handler(lines, line_num - 1, content, m.end())
        endpoints.append(APIEndpoint(
            method=method,
            path=route_path,
            handler=handler,
            file=str(path),
            line=line_num,
        ))

    return endpoints


def _find_go_handler(lines, line_idx, content, match_end):
    """Extract handler function name from Go route definition."""
    # Look for the handler argument after the path
    remaining = content[match_end:match_end + 200]
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
        line_num = content[:m.start()].count("\n") + 1

        # Resolve prefix from enclosing Route::group
        prefix = _resolve_prefix(m.start(), group_prefixes, content)
        if prefix:
            route_path = prefix.rstrip("/") + "/" + route_path.lstrip("/")
        if not route_path.startswith("/"):
            route_path = "/" + route_path

        # Find controller/handler — supports both modern and Laravel 4 array syntax
        handler_region = content[m.start():m.start() + 500]
        ctrl_match = _LARAVEL_CONTROLLER.search(handler_region)
        handler = f"{ctrl_match.group(1)}@{ctrl_match.group(2)}" if ctrl_match and ctrl_match.group(2) else (ctrl_match.group(1) if ctrl_match else "")

        # Find middleware — both ->middleware() and 'before'/'middleware' in array
        middleware = []
        mw_match = re.search(r"->middleware\s*\(\s*\[?([^\])\n]+)", handler_region)
        if mw_match:
            middleware = [m.strip().strip("'\"") for m in mw_match.group(1).split(",")]
        else:
            # Laravel 4: 'before' => 'auth|admin'
            mw_match4 = re.search(r"['\"](before|middleware)['\"]\s*=>\s*['\"]([^'\"]+)['\"]", handler_region)
            if mw_match4:
                middleware = [m.strip() for m in mw_match4.group(2).split("|")]

        endpoints.append(APIEndpoint(
            method=method,
            path=route_path,
            handler=handler,
            file=str(path),
            line=line_num,
            middleware=middleware,
        ))

    # Resource routes (expands to standard CRUD)
    for m in _LARAVEL_RESOURCE.finditer(content):
        resource = m.group(1)
        line_num = content[:m.start()].count("\n") + 1
        base = "/" + resource if not resource.startswith("/") else resource

        for method, suffix in [
            ("GET", ""), ("GET", "/{id}"), ("POST", ""),
            ("PUT", "/{id}"), ("DELETE", "/{id}"),
        ]:
            endpoints.append(APIEndpoint(
                method=method,
                path=base + suffix,
                handler=f"{resource.title()}Controller",
                file=str(path),
                line=line_num,
            ))

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


def _resolve_prefix(offset: int, groups: list[tuple[int, int, str]],
                     content: str) -> str:
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
