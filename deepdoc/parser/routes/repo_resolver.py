"""Repo-aware endpoint resolution for framework-specific route metadata."""

from __future__ import annotations

import ast
import copy
from dataclasses import dataclass, field
import os
from pathlib import Path
import re

from .base import APIEndpoint
from .common import dedupe_endpoints, join_route_path, parse_string_arg
from .django import (
    extract_django_class_views,
    extract_django_function_methods,
    extract_django_handler_name,
    extract_django_router_endpoints,
    infer_django_handler_methods,
    normalize_django_route,
    unwrap_django_handler_expr,
)
from .falcon import find_falcon_responders
from .js_shared import (
    FASTIFY_REGISTER_CALL,
    JS_USE_CALL,
    extract_fastify_add_hook_map,
    extract_fastify_hooks_from_args,
    extract_fastify_mounts,
    extract_fastify_plugin_aliases,
    extract_js_mounts,
    resolve_js_prefixes,
)


@dataclass
class JSImportIndex:
    """Minimal JS/TS module graph for mount-chain resolution."""

    local_mounts: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    local_fastify_mounts: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    imports: dict[str, str] = field(default_factory=dict)
    incoming_mounts: list[tuple[str, str, str]] = field(default_factory=list)
    fastify_local_hooks: dict[str, list[str]] = field(default_factory=dict)
    incoming_fastify_mounts: list[tuple[str, str, str, list[str]]] = field(
        default_factory=list
    )


@dataclass
class PythonImportIndex:
    """Minimal Python import + constant index for Falcon resolution."""

    imports: dict[str, str] = field(default_factory=dict)
    constants: dict[str, str] = field(default_factory=dict)


@dataclass
class GoResolverIndex:
    """Minimal Go package/import graph for handler ownership resolution."""

    file_imports: dict[str, dict[str, str]] = field(default_factory=dict)
    package_symbols: dict[str, dict[str, str]] = field(default_factory=dict)
    package_files: dict[str, list[str]] = field(default_factory=dict)


def resolve_repo_endpoints(
    repo_root: Path,
    endpoints: list[APIEndpoint],
    file_contents: dict[str, str],
) -> list[APIEndpoint]:
    """Resolve repo-level route metadata without changing the public contract."""
    js_index = _build_js_index(file_contents)
    py_index = _build_python_index(file_contents)
    go_index = _build_go_index(repo_root, file_contents)

    resolved: list[APIEndpoint] = []
    has_django = False
    for endpoint in endpoints:
        framework = (endpoint.framework or "").lower()
        if framework == "express":
            resolved.extend(_resolve_express_endpoint(repo_root, endpoint, js_index))
        elif framework == "fastify":
            resolved.extend(_resolve_fastify_endpoint(repo_root, endpoint, js_index))
        elif framework == "falcon":
            resolved.extend(
                _resolve_falcon_endpoint(repo_root, endpoint, file_contents, py_index)
            )
        elif framework == "go":
            resolved.extend(_resolve_go_endpoint(repo_root, endpoint, go_index))
        elif framework == "django":
            has_django = True
        else:
            resolved.append(_normalize_endpoint(repo_root, endpoint))
    if has_django:
        resolved.extend(
            _resolve_django_repo_endpoints(repo_root, file_contents, py_index)
        )
    return dedupe_endpoints(resolved)


def _normalize_endpoint(repo_root: Path, endpoint: APIEndpoint) -> APIEndpoint:
    resolved = copy.deepcopy(endpoint)
    route_file = _repo_rel_path(repo_root, resolved.route_file or resolved.file)
    handler_file = _repo_rel_path(
        repo_root, resolved.handler_file or resolved.file or route_file
    )
    resolved.route_file = route_file
    resolved.handler_file = handler_file or route_file
    resolved.file = resolved.handler_file or resolved.route_file
    return resolved


def _build_js_index(file_contents: dict[str, str]) -> dict[str, JSImportIndex]:
    index: dict[str, JSImportIndex] = {}
    known_files = set(file_contents)

    for rel_path, content in file_contents.items():
        if Path(rel_path).suffix.lower() not in {
            ".js",
            ".jsx",
            ".ts",
            ".tsx",
            ".mjs",
            ".cjs",
        }:
            continue
        imports = _extract_js_imports(rel_path, content, known_files)
        index[rel_path] = JSImportIndex(
            local_mounts=extract_js_mounts(content),
            local_fastify_mounts=extract_fastify_mounts(
                content,
                extract_fastify_plugin_aliases(content),
            ),
            imports=imports,
            fastify_local_hooks=extract_fastify_add_hook_map(content),
        )

    for rel_path, content in file_contents.items():
        if rel_path not in index:
            continue
        for parent_obj, prefix, alias in _extract_js_mount_calls(content):
            child_file = index[rel_path].imports.get(alias)
            if child_file and child_file in index:
                index[child_file].incoming_mounts.append((rel_path, parent_obj, prefix))
        for parent_obj, prefix, alias, hooks in _extract_fastify_register_calls(
            content, index[rel_path].imports
        ):
            child_file = index[rel_path].imports.get(alias)
            if child_file and child_file in index:
                index[child_file].incoming_fastify_mounts.append(
                    (rel_path, parent_obj, prefix, hooks)
                )

    return index


def _extract_js_imports(
    rel_path: str, content: str, known_files: set[str]
) -> dict[str, str]:
    imports: dict[str, str] = {}
    current_dir = Path(rel_path).parent

    patterns = [
        re.compile(
            r"""(?:const|let|var)\s+(\w+)\s*=\s*require\(\s*['"]([^'"]+)['"]\s*\)"""
        ),
        re.compile(r"""import\s+(\w+)\s+from\s+['"]([^'"]+)['"]"""),
    ]

    for pattern in patterns:
        for match in pattern.finditer(content):
            alias, spec = match.group(1), match.group(2)
            resolved = _resolve_js_module_path(current_dir, spec, known_files)
            if resolved:
                imports[alias] = resolved
    return imports


def _resolve_js_module_path(current_dir: Path, spec: str, known_files: set[str]) -> str:
    if not spec.startswith("."):
        return ""

    base = os.path.normpath((current_dir / spec).as_posix())
    candidates = [
        base,
        f"{base}.js",
        f"{base}.jsx",
        f"{base}.ts",
        f"{base}.tsx",
        f"{base}.mjs",
        f"{base}.cjs",
        f"{base}/index.js",
        f"{base}/index.jsx",
        f"{base}/index.ts",
        f"{base}/index.tsx",
        f"{base}/index.mjs",
        f"{base}/index.cjs",
    ]
    for candidate in candidates:
        normalized = Path(candidate).as_posix()
        if normalized in known_files:
            return normalized
    return ""


def _extract_js_mount_calls(content: str) -> list[tuple[str, str, str]]:
    mounts: list[tuple[str, str, str]] = []
    from .common import extract_balanced_segment, split_top_level_args

    for match in JS_USE_CALL.finditer(content):
        parent_obj = match.group(1)
        call_text = extract_balanced_segment(content, match.end() - 1)
        if not call_text:
            continue
        args = split_top_level_args(call_text[1:-1])
        if len(args) < 2:
            continue
        prefix = parse_string_arg(args[0])
        alias_match = re.match(r"""(\w+)""", args[1].strip())
        if prefix is None or not alias_match:
            continue
        mounts.append((parent_obj, prefix, alias_match.group(1)))
    return mounts


def _resolve_express_endpoint(
    repo_root: Path,
    endpoint: APIEndpoint,
    js_index: dict[str, JSImportIndex],
) -> list[APIEndpoint]:
    resolved = _normalize_endpoint(repo_root, endpoint)
    route_file = resolved.route_file
    info = js_index.get(route_file)
    if not info:
        return [resolved]

    router_object = (resolved.provenance or {}).get("router_object", "")
    route_path = (
        parse_string_arg(resolved.raw_path or "") or resolved.raw_path or resolved.path
    )
    local_prefixes = (
        resolve_js_prefixes(router_object, info.local_mounts) if router_object else [""]
    )
    incoming_prefixes = _resolve_js_file_prefixes(route_file, js_index)

    paths: list[str] = []
    for incoming_prefix in incoming_prefixes:
        for local_prefix in local_prefixes or [""]:
            paths.append(join_route_path(incoming_prefix, local_prefix, route_path))

    resolved_paths = sorted(set(paths or [resolved.path]))
    handler_file = _resolve_express_handler_file(resolved.handler, info, route_file)

    endpoints: list[APIEndpoint] = []
    for path in resolved_paths:
        ep = copy.deepcopy(resolved)
        ep.path = path
        ep.handler_file = handler_file
        ep.file = handler_file
        endpoints.append(ep)
    return endpoints


def _resolve_fastify_endpoint(
    repo_root: Path,
    endpoint: APIEndpoint,
    js_index: dict[str, JSImportIndex],
) -> list[APIEndpoint]:
    resolved = _normalize_endpoint(repo_root, endpoint)
    route_file = resolved.route_file
    info = js_index.get(route_file)
    if not info:
        return [resolved]

    router_object = (resolved.provenance or {}).get("router_object", "")
    route_path = (
        parse_string_arg(resolved.raw_path or "") or resolved.raw_path or resolved.path
    )
    local_prefixes = (
        resolve_js_prefixes(router_object, info.local_fastify_mounts)
        if router_object
        else [""]
    )
    incoming_prefixes = _resolve_fastify_file_prefixes(route_file, js_index)
    inherited_hooks = _resolve_fastify_hooks(route_file, router_object, js_index)
    handler_file = _resolve_express_handler_file(resolved.handler, info, route_file)

    paths: list[str] = []
    for incoming_prefix in incoming_prefixes:
        for local_prefix in local_prefixes or [""]:
            paths.append(join_route_path(incoming_prefix, local_prefix, route_path))

    resolved_paths = sorted(set(paths or [resolved.path]))
    combined_hooks = _ordered_unique(inherited_hooks + list(resolved.middleware or []))

    endpoints: list[APIEndpoint] = []
    for path in resolved_paths:
        ep = copy.deepcopy(resolved)
        ep.path = path
        ep.middleware = combined_hooks
        ep.handler_file = handler_file
        ep.file = handler_file
        endpoints.append(ep)
    return endpoints


def _resolve_js_file_prefixes(
    rel_path: str,
    js_index: dict[str, JSImportIndex],
    memo: dict[str, list[str]] | None = None,
    stack: set[str] | None = None,
) -> list[str]:
    if memo is None:
        memo = {}
    if stack is None:
        stack = set()
    if rel_path in memo:
        return memo[rel_path]
    if rel_path in stack:
        return [""]

    stack.add(rel_path)
    info = js_index.get(rel_path)
    if not info or not info.incoming_mounts:
        memo[rel_path] = [""]
    else:
        prefixes: list[str] = []
        for parent_file, parent_obj, mount_prefix in info.incoming_mounts:
            parent_info = js_index.get(parent_file)
            local_parent_prefixes = (
                resolve_js_prefixes(parent_obj, parent_info.local_fastify_mounts)
                if parent_info
                else [""]
            )
            repo_parent_prefixes = _resolve_js_file_prefixes(
                parent_file, js_index, memo, stack
            )
            for repo_prefix in repo_parent_prefixes:
                for local_prefix in local_parent_prefixes or [""]:
                    prefixes.append(
                        join_route_path(repo_prefix, local_prefix, mount_prefix)
                    )
        memo[rel_path] = sorted(set(prefixes or [""]))

    stack.discard(rel_path)
    return memo[rel_path]


def _resolve_fastify_file_prefixes(
    rel_path: str,
    js_index: dict[str, JSImportIndex],
    memo: dict[str, list[str]] | None = None,
    stack: set[str] | None = None,
) -> list[str]:
    if memo is None:
        memo = {}
    if stack is None:
        stack = set()
    if rel_path in memo:
        return memo[rel_path]
    if rel_path in stack:
        return [""]

    stack.add(rel_path)
    info = js_index.get(rel_path)
    if not info or not info.incoming_fastify_mounts:
        memo[rel_path] = [""]
    else:
        prefixes: list[str] = []
        for (
            parent_file,
            parent_obj,
            mount_prefix,
            _hooks,
        ) in info.incoming_fastify_mounts:
            parent_prefixes = _resolve_fastify_file_prefixes(
                parent_file, js_index, memo, stack
            )
            parent_info = js_index.get(parent_file)
            local_parent_prefixes = (
                resolve_js_prefixes(parent_obj, parent_info.local_mounts)
                if parent_info
                else [""]
            )
            for repo_prefix in parent_prefixes:
                for local_prefix in local_parent_prefixes or [""]:
                    prefixes.append(
                        join_route_path(repo_prefix, local_prefix, mount_prefix)
                    )
        memo[rel_path] = sorted(set(prefixes or [""]))

    stack.discard(rel_path)
    return memo[rel_path]


def _resolve_fastify_hooks(
    rel_path: str,
    router_object: str,
    js_index: dict[str, JSImportIndex],
    memo: dict[tuple[str, str], list[str]] | None = None,
    stack: set[tuple[str, str]] | None = None,
) -> list[str]:
    if memo is None:
        memo = {}
    if stack is None:
        stack = set()
    key = (rel_path, router_object)
    if key in memo:
        return memo[key]
    if key in stack:
        return []

    stack.add(key)
    info = js_index.get(rel_path)
    hooks: list[str] = []
    if info:
        for (
            parent_file,
            parent_obj,
            _mount_prefix,
            register_hooks,
        ) in info.incoming_fastify_mounts:
            hooks.extend(
                _resolve_fastify_hooks(parent_file, parent_obj, js_index, memo, stack)
            )
            hooks.extend(register_hooks)
    if info and router_object:
        hooks.extend(info.fastify_local_hooks.get(router_object, []))
    hooks = _ordered_unique(hooks)
    memo[key] = hooks
    stack.discard(key)
    return hooks


def _resolve_express_handler_file(
    handler: str, info: JSImportIndex, route_file: str
) -> str:
    if not handler:
        return route_file
    alias = handler.split(".", 1)[0]
    return info.imports.get(alias, route_file)


def _extract_fastify_register_calls(
    content: str, imports: dict[str, str]
) -> list[tuple[str, str, str, list[str]]]:
    calls: list[tuple[str, str, str, list[str]]] = []
    from .common import extract_balanced_segment, split_top_level_args

    for match in FASTIFY_REGISTER_CALL.finditer(content):
        parent_obj = match.group(1)
        call_text = extract_balanced_segment(content, match.end() - 1)
        if not call_text:
            continue
        args = split_top_level_args(call_text[1:-1])
        if not args:
            continue
        alias_match = re.match(r"""(\w+)""", args[0].strip())
        if not alias_match:
            continue
        alias = alias_match.group(1)
        if alias not in imports:
            continue
        prefix = ""
        hooks: list[str] = []
        for arg in args[1:]:
            prefix_match = re.search(r"""prefix\s*:\s*['\"]([^'\"]+)['\"]""", arg)
            if prefix_match:
                prefix = prefix_match.group(1)
            for name in extract_fastify_hooks_from_args([arg]):
                if name not in hooks:
                    hooks.append(name)
        calls.append((parent_obj, prefix, alias, hooks))
    return calls


def _build_go_index(repo_root: Path, file_contents: dict[str, str]) -> GoResolverIndex:
    module_name = _read_go_module_name(file_contents.get("go.mod", ""))
    if not module_name:
        go_mod_path = repo_root / "go.mod"
        if go_mod_path.exists():
            try:
                module_name = _read_go_module_name(
                    go_mod_path.read_text(encoding="utf-8", errors="replace")
                )
            except Exception:
                module_name = ""
    package_symbols: dict[str, dict[str, str]] = {}
    package_files: dict[str, list[str]] = {}
    file_imports: dict[str, dict[str, str]] = {}

    for rel_path, content in file_contents.items():
        if Path(rel_path).suffix.lower() != ".go":
            continue
        package_dir = Path(rel_path).parent.as_posix()
        package_files.setdefault(package_dir, []).append(rel_path)
        symbols = package_symbols.setdefault(package_dir, {})
        for symbol in _extract_go_declared_symbols(content):
            symbols.setdefault(symbol, rel_path)
        file_imports[rel_path] = _extract_go_imports(
            repo_root,
            rel_path,
            content,
            file_contents,
            module_name,
        )

    for files in package_files.values():
        files.sort()
    return GoResolverIndex(
        file_imports=file_imports,
        package_symbols=package_symbols,
        package_files=package_files,
    )


def _read_go_module_name(go_mod_content: str) -> str:
    match = re.search(r"""^\s*module\s+(.+?)\s*$""", go_mod_content, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _extract_go_declared_symbols(content: str) -> list[str]:
    symbols: list[str] = []
    for pattern in (
        re.compile(r"""^\s*func\s+(\w+)\s*\(""", re.MULTILINE),
        re.compile(r"""^\s*func\s*\([^)]*\)\s*(\w+)\s*\(""", re.MULTILINE),
    ):
        for match in pattern.finditer(content):
            name = match.group(1)
            if name not in symbols:
                symbols.append(name)
    return symbols


def _extract_go_imports(
    repo_root: Path,
    rel_path: str,
    content: str,
    file_contents: dict[str, str],
    module_name: str,
) -> dict[str, str]:
    imports: dict[str, str] = {}
    current_dir = Path(rel_path).parent
    known_files = set(file_contents)

    import_specs: list[tuple[str, str]] = []
    block_match = re.search(r"""import\s*\((.*?)\)""", content, re.DOTALL)
    if block_match:
        for line in block_match.group(1).splitlines():
            parsed = _parse_go_import_line(line)
            if parsed:
                import_specs.append(parsed)
    else:
        for match in re.finditer(
            r"""^\s*import\s+(?:(\w+)\s+)?['\"]([^'\"]+)['\"]""",
            content,
            re.MULTILINE,
        ):
            alias = match.group(1) or Path(match.group(2)).name
            import_specs.append((alias, match.group(2)))

    for alias, spec in import_specs:
        resolved = _resolve_go_import_path(
            repo_root, current_dir, spec, known_files, module_name
        )
        if resolved:
            imports[alias] = resolved
    return imports


def _parse_go_import_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("//"):
        return None
    match = re.match(r"""(?:(\w+)\s+)?['\"]([^'\"]+)['\"]""", stripped)
    if not match:
        return None
    alias = match.group(1) or Path(match.group(2)).name
    return alias, match.group(2)


def _resolve_go_import_path(
    repo_root: Path,
    current_dir: Path,
    spec: str,
    known_files: set[str],
    module_name: str,
) -> str:
    if spec.startswith("."):
        candidate_dir = (current_dir / spec).as_posix()
    elif module_name and (spec == module_name or spec.startswith(f"{module_name}/")):
        candidate_dir = spec[len(module_name) :].lstrip("/")
    else:
        return ""

    normalized_dir = Path(candidate_dir).as_posix()
    if any(
        path.startswith(f"{normalized_dir}/") and path.endswith(".go")
        for path in known_files
    ):
        return normalized_dir
    if normalized_dir.endswith(".go") and normalized_dir in known_files:
        return str(Path(normalized_dir).parent.as_posix())
    return ""


def _resolve_go_endpoint(
    repo_root: Path,
    endpoint: APIEndpoint,
    go_index: GoResolverIndex,
) -> list[APIEndpoint]:
    resolved = _normalize_endpoint(repo_root, endpoint)
    handler_file = _resolve_go_handler_file(
        resolved.route_file, resolved.handler, go_index
    )
    resolved.handler_file = handler_file or resolved.handler_file
    resolved.file = resolved.handler_file or resolved.file
    return [resolved]


def _resolve_go_handler_file(
    route_file: str,
    handler: str,
    go_index: GoResolverIndex,
) -> str:
    if not handler:
        return route_file

    handler_symbol = handler.split(".")[-1]
    qualifier = handler.split(".", 1)[0] if "." in handler else ""
    imports = go_index.file_imports.get(route_file, {})
    if qualifier and qualifier in imports:
        package_dir = imports[qualifier]
        symbol_file = go_index.package_symbols.get(package_dir, {}).get(handler_symbol)
        if symbol_file:
            return symbol_file
        package_files = go_index.package_files.get(package_dir, [])
        if package_files:
            return package_files[0]

    package_dir = Path(route_file).parent.as_posix()
    symbol_file = go_index.package_symbols.get(package_dir, {}).get(handler_symbol)
    if symbol_file:
        return symbol_file
    return route_file


def _build_python_index(file_contents: dict[str, str]) -> dict[str, PythonImportIndex]:
    index: dict[str, PythonImportIndex] = {}
    known_files = set(file_contents)
    for rel_path, content in file_contents.items():
        if Path(rel_path).suffix.lower() != ".py":
            continue
        imports: dict[str, str] = {}
        constants: dict[str, str] = {}
        try:
            module = ast.parse(content)
        except SyntaxError:
            index[rel_path] = PythonImportIndex(imports=imports, constants=constants)
            continue

        for node in module.body:
            if isinstance(node, ast.Import):
                for alias_node in node.names:
                    module_spec = alias_node.name
                    alias = alias_node.asname or module_spec.split(".")[-1]
                    resolved = _resolve_python_module_path(
                        rel_path, module_spec, known_files, imported_name=None
                    )
                    if resolved:
                        imports[alias] = resolved
            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                module_spec = f"{'.' * node.level}{module_name}"
                for alias_node in node.names:
                    if alias_node.name == "*":
                        continue
                    clean_name = alias_node.name
                    alias = alias_node.asname or clean_name
                    resolved = _resolve_python_module_path(
                        rel_path, module_spec, known_files, imported_name=clean_name
                    )
                    if resolved:
                        imports[alias] = resolved
            elif isinstance(node, ast.Assign):
                value = node.value
                if not (
                    isinstance(value, ast.Constant) and isinstance(value.value, str)
                ):
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name) and re.match(
                        r"""^[A-Z][A-Z0-9_]*$""", target.id
                    ):
                        constants[target.id] = value.value
            elif isinstance(node, ast.AnnAssign):
                value = node.value
                target = node.target
                if (
                    isinstance(target, ast.Name)
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                    and re.match(r"""^[A-Z][A-Z0-9_]*$""", target.id)
                ):
                    constants[target.id] = value.value

        index[rel_path] = PythonImportIndex(imports=imports, constants=constants)
    return index


def _resolve_python_module_path(
    current_file: str,
    module_spec: str,
    known_files: set[str],
    imported_name: str | None,
) -> str:
    current_dir = Path(current_file).parent
    if module_spec.startswith("."):
        parts = current_dir.parts
        relative = module_spec
        level = len(relative) - len(relative.lstrip("."))
        tail = relative[level:]
        base_parts = list(parts[: max(0, len(parts) - max(level - 1, 0))])
        if tail:
            base_parts.extend(part for part in tail.split(".") if part)
        module_parts = base_parts
    else:
        module_parts = [part for part in module_spec.split(".") if part]

    candidates: list[str] = []
    if module_parts:
        module_path = "/".join(module_parts)
        package_dir = Path(module_path)
        if imported_name:
            candidates.extend(
                [
                    f"{package_dir.as_posix()}/{imported_name}.py",
                    f"{package_dir.as_posix()}/{imported_name}/__init__.py",
                ]
            )
        candidates.extend([f"{module_path}.py", f"{module_path}/__init__.py"])
    elif imported_name:
        candidates.extend([f"{imported_name}.py", f"{imported_name}/__init__.py"])

    for candidate in candidates:
        if candidate in known_files:
            return candidate
    return ""


def _resolve_falcon_endpoint(
    repo_root: Path,
    endpoint: APIEndpoint,
    file_contents: dict[str, str],
    py_index: dict[str, PythonImportIndex],
) -> list[APIEndpoint]:
    resolved = _normalize_endpoint(repo_root, endpoint)
    route_file = resolved.route_file
    py_index.get(route_file, PythonImportIndex())
    resource_ref = (resolved.provenance or {}).get("resource_ref") or re.sub(
        r"""\.on_[a-z]+$""", "", resolved.handler
    )
    resolved_path = (
        _resolve_python_path_expr(
            resolved.raw_path or resolved.path, route_file, py_index
        )
        or resolved.path
    )
    handler_file = _resolve_falcon_handler_file(
        route_file, resource_ref, file_contents, py_index
    )
    methods = _resolve_falcon_methods(
        handler_file, resource_ref, file_contents, fallback_method=resolved.method
    )

    if not methods:
        resolved.path = resolved_path
        resolved.handler_file = handler_file or resolved.handler_file
        resolved.file = resolved.handler_file or resolved.file
        return [resolved]

    endpoints: list[APIEndpoint] = []
    base_handler = resource_ref or resolved.handler
    for method in methods:
        ep = copy.deepcopy(resolved)
        ep.method = method
        ep.path = resolved_path
        ep.handler = (
            f"{base_handler}.on_{method.lower()}"
            if base_handler and ".on_" not in base_handler
            else base_handler
        )
        ep.handler_file = handler_file or ep.handler_file
        ep.file = ep.handler_file or ep.file
        endpoints.append(ep)
    return endpoints


def _resolve_python_path_expr(
    expr: str, current_file: str, py_index: dict[str, PythonImportIndex]
) -> str:
    stripped = expr.strip()
    literal = parse_string_arg(stripped)
    if literal is not None:
        return literal

    parts = _split_python_concat(stripped)
    if not parts:
        return ""

    resolved: list[str] = []
    for part in parts:
        literal = parse_string_arg(part)
        if literal is not None:
            resolved.append(literal)
            continue

        const_value = _resolve_python_constant(part, current_file, py_index)
        if const_value is None:
            return ""
        resolved.append(const_value)
    return "".join(resolved)


def _split_python_concat(expr: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    quote = ""
    escape = False
    depth = 0

    for ch in expr:
        if quote:
            buf.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
            continue

        if ch in {'"', "'"}:
            quote = ch
            buf.append(ch)
            continue
        if ch in "([{":
            depth += 1
            buf.append(ch)
            continue
        if ch in ")]}":
            depth = max(depth - 1, 0)
            buf.append(ch)
            continue
        if ch == "+" and depth == 0:
            part = "".join(buf).strip()
            if part:
                parts.append(part)
            buf = []
            continue
        buf.append(ch)

    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _resolve_python_constant(
    ref: str,
    current_file: str,
    py_index: dict[str, PythonImportIndex],
    stack: set[tuple[str, str]] | None = None,
) -> str | None:
    if stack is None:
        stack = set()

    stripped = ref.strip()
    if "." in stripped:
        alias, name = stripped.split(".", 1)
        alias_file = py_index.get(current_file, PythonImportIndex()).imports.get(alias)
        if not alias_file:
            return None
        return _resolve_python_constant(name, alias_file, py_index, stack)

    key = (current_file, stripped)
    if key in stack:
        return None
    stack.add(key)

    info = py_index.get(current_file, PythonImportIndex())
    if stripped in info.constants:
        return info.constants[stripped]

    imported_file = info.imports.get(stripped)
    if imported_file:
        imported_info = py_index.get(imported_file, PythonImportIndex())
        if stripped in imported_info.constants:
            return imported_info.constants[stripped]
    return None


def _resolve_falcon_handler_file(
    route_file: str,
    resource_ref: str,
    file_contents: dict[str, str],
    py_index: dict[str, PythonImportIndex],
) -> str:
    if not resource_ref:
        return route_file

    current_content = file_contents.get(route_file, "")
    class_name = resource_ref.split(".")[-1]
    if re.search(
        rf"""^\s*class\s+{re.escape(class_name)}\b""", current_content, re.MULTILINE
    ):
        return route_file

    imports = py_index.get(route_file, PythonImportIndex()).imports
    if "." in resource_ref:
        alias = resource_ref.split(".", 1)[0]
        alias_file = imports.get(alias)
        resolved = _resolve_python_class_file(
            alias_file or "", class_name, file_contents
        )
        return resolved or alias_file or route_file

    imported_file = imports.get(resource_ref)
    resolved = _resolve_python_class_file(
        imported_file or "", class_name, file_contents
    )
    return resolved or imported_file or route_file


def _resolve_python_class_file(
    imported_file: str,
    class_name: str,
    file_contents: dict[str, str],
) -> str:
    if not imported_file or not class_name:
        return ""

    content = file_contents.get(imported_file, "")
    if content and re.search(
        rf"""^\s*class\s+{re.escape(class_name)}\b""",
        content,
        re.MULTILINE,
    ):
        return imported_file

    candidate_dirs: list[str] = []
    imported_path = Path(imported_file)
    if imported_path.name == "__init__.py":
        candidate_dirs.append(imported_path.parent.as_posix())
    else:
        candidate_dirs.append(imported_path.parent.as_posix())

    for candidate_dir in candidate_dirs:
        for rel_path in sorted(file_contents):
            if Path(rel_path).suffix.lower() != ".py":
                continue
            if Path(rel_path).parent.as_posix() != candidate_dir:
                continue
            if re.search(
                rf"""^\s*class\s+{re.escape(class_name)}\b""",
                file_contents.get(rel_path, ""),
                re.MULTILINE,
            ):
                return rel_path
    return ""


def _resolve_falcon_methods(
    handler_file: str,
    resource_ref: str,
    file_contents: dict[str, str],
    fallback_method: str,
) -> list[str]:
    handler_content = file_contents.get(handler_file, "")
    if not handler_content:
        return [] if fallback_method == "ANY" else [fallback_method]

    class_name = resource_ref.split(".")[-1] if resource_ref else ""
    methods = find_falcon_responders(handler_content, class_name) if class_name else []
    if methods:
        return methods
    return [] if fallback_method == "ANY" else [fallback_method]


def _resolve_django_repo_endpoints(
    repo_root: Path,
    file_contents: dict[str, str],
    py_index: dict[str, PythonImportIndex],
) -> list[APIEndpoint]:
    """Resolve Django URL trees with settings prefixes, includes, and view ownership."""
    root_files = _find_django_root_url_files(file_contents, py_index)
    if not root_files:
        return []

    known_files = set(file_contents)
    resolved: list[APIEndpoint] = []
    for root_file in root_files:
        resolved.extend(
            _expand_django_urlpatterns(
                repo_root,
                root_file,
                prefix="",
                file_contents=file_contents,
                py_index=py_index,
                known_files=known_files,
                stack=set(),
            )
        )
    return dedupe_endpoints(resolved)


def _find_django_root_url_files(
    file_contents: dict[str, str],
    py_index: dict[str, PythonImportIndex],
) -> list[str]:
    known_files = set(file_contents)
    root_files: list[str] = []

    for rel_path in sorted(file_contents):
        if not rel_path.endswith("settings.py"):
            continue
        root_module = _resolve_python_constant("ROOT_URLCONF", rel_path, py_index)
        if not root_module:
            continue
        root_file = _resolve_python_module_path(
            rel_path,
            root_module,
            known_files,
            imported_name=None,
        )
        if root_file:
            root_files.append(root_file)

    if root_files:
        return sorted(set(root_files))

    return sorted(
        rel_path
        for rel_path in file_contents
        if rel_path.endswith("/urls.py") or rel_path == "urls.py"
    )


def _expand_django_urlpatterns(
    repo_root: Path,
    rel_path: str,
    *,
    prefix: str,
    file_contents: dict[str, str],
    py_index: dict[str, PythonImportIndex],
    known_files: set[str],
    stack: set[str],
) -> list[APIEndpoint]:
    if rel_path in stack:
        return []
    stack.add(rel_path)

    content = file_contents.get(rel_path, "")
    if not content:
        stack.discard(rel_path)
        return []

    try:
        module = ast.parse(content)
    except SyntaxError:
        stack.discard(rel_path)
        return []

    bindings = _collect_python_bindings(module)
    class_views = extract_django_class_views(content)
    routers = extract_django_router_endpoints(content, class_views)
    route_nodes = _extract_urlpattern_nodes(module)

    endpoints: list[APIEndpoint] = []
    for node in route_nodes:
        endpoints.extend(
            _expand_django_pattern_node(
                repo_root,
                rel_path,
                content,
                node,
                prefix=prefix,
                file_contents=file_contents,
                py_index=py_index,
                known_files=known_files,
                bindings=bindings,
                routers=routers,
                stack=stack,
            )
        )

    stack.discard(rel_path)
    return endpoints


def _extract_urlpattern_nodes(module: ast.Module) -> list[ast.AST]:
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "urlpatterns":
                    return _flatten_urlpattern_value(node.value)
        if isinstance(node, ast.AnnAssign):
            target = node.target
            if (
                isinstance(target, ast.Name)
                and target.id == "urlpatterns"
                and node.value
            ):
                return _flatten_urlpattern_value(node.value)
    return []


def _flatten_urlpattern_value(value: ast.AST) -> list[ast.AST]:
    if isinstance(value, ast.List):
        return list(value.elts)
    if isinstance(value, ast.Tuple):
        return list(value.elts)
    return []


def _collect_python_bindings(module: ast.Module) -> dict[str, ast.AST]:
    bindings: dict[str, ast.AST] = {}
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bindings[target.id] = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value
        ):
            bindings[node.target.id] = node.value
    return bindings


def _expand_django_pattern_node(
    repo_root: Path,
    rel_path: str,
    content: str,
    node: ast.AST,
    *,
    prefix: str,
    file_contents: dict[str, str],
    py_index: dict[str, PythonImportIndex],
    known_files: set[str],
    bindings: dict[str, ast.AST],
    routers: dict[str, list[APIEndpoint]],
    stack: set[str],
) -> list[APIEndpoint]:
    if not isinstance(node, ast.Call):
        return []

    call_name = _ast_call_name(node.func)
    if call_name not in {"path", "re_path"} or len(node.args) < 2:
        return []

    route_raw = _resolve_django_ast_string(node.args[0], rel_path, bindings, py_index)
    if route_raw is None:
        return []

    route_path = normalize_django_route(route_raw, is_regex=call_name == "re_path")
    full_prefix = join_route_path(prefix, route_path)
    handler_node = node.args[1]
    line_num = getattr(node, "lineno", 0)

    include_info = _extract_django_include_info(
        handler_node,
        rel_path,
        bindings,
        py_index,
        known_files,
        routers,
    )
    if include_info["kind"] == "module":
        child_file = include_info["file"]
        if not child_file:
            return []
        return _expand_django_urlpatterns(
            repo_root,
            child_file,
            prefix=full_prefix,
            file_contents=file_contents,
            py_index=py_index,
            known_files=known_files,
            stack=stack,
        )
    if include_info["kind"] == "inline":
        endpoints: list[APIEndpoint] = []
        for child in include_info["nodes"]:
            endpoints.extend(
                _expand_django_pattern_node(
                    repo_root,
                    rel_path,
                    content,
                    child,
                    prefix=full_prefix,
                    file_contents=file_contents,
                    py_index=py_index,
                    known_files=known_files,
                    bindings=bindings,
                    routers=routers,
                    stack=stack,
                )
            )
        return endpoints
    if include_info["kind"] == "router":
        endpoints: list[APIEndpoint] = []
        for endpoint in include_info["endpoints"]:
            ep = copy.deepcopy(endpoint)
            ep.path = join_route_path(full_prefix, endpoint.path)
            ep.route_file = rel_path
            ep.handler_file = rel_path
            ep.file = rel_path
            ep.line = line_num
            ep.framework = "django"
            ep.raw_path = route_raw
            endpoints.append(_normalize_endpoint(repo_root, ep))
        return endpoints

    handler_expr = ast.get_source_segment(content, handler_node) or ""
    handler_file = _resolve_django_handler_file(
        rel_path, handler_expr, file_contents, py_index
    )
    handler_content = file_contents.get(handler_file, "")
    function_methods = extract_django_function_methods(handler_content)
    class_views = extract_django_class_views(handler_content)
    methods = infer_django_handler_methods(handler_expr, function_methods, class_views)
    handler_name = extract_django_handler_name(handler_expr)

    endpoints: list[APIEndpoint] = []
    for method in methods:
        endpoints.append(
            _normalize_endpoint(
                repo_root,
                APIEndpoint(
                    method=method,
                    path=full_prefix,
                    handler=handler_name,
                    file=handler_file,
                    route_file=rel_path,
                    handler_file=handler_file,
                    line=line_num,
                    raw_path=route_raw,
                    framework="django",
                    provenance={"mount_prefix": prefix},
                ),
            )
        )
    return endpoints


def _ast_call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _resolve_django_ast_string(
    expr: ast.AST,
    current_file: str,
    bindings: dict[str, ast.AST],
    py_index: dict[str, PythonImportIndex],
    stack: set[str] | None = None,
) -> str | None:
    if stack is None:
        stack = set()

    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    if isinstance(expr, ast.Name):
        if expr.id in stack:
            return None
        if expr.id in bindings:
            stack.add(expr.id)
            return _resolve_django_ast_string(
                bindings[expr.id], current_file, bindings, py_index, stack
            )
        return _resolve_python_constant(expr.id, current_file, py_index)
    if isinstance(expr, ast.Attribute):
        chain = _ast_attribute_chain(expr)
        if chain:
            if chain.startswith("settings."):
                setting_value = _resolve_django_project_setting(
                    chain.split(".", 1)[1], py_index
                )
                if setting_value is not None:
                    return setting_value
            return _resolve_python_constant(chain, current_file, py_index)
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        left = _resolve_django_ast_string(
            expr.left, current_file, bindings, py_index, stack
        )
        right = _resolve_django_ast_string(
            expr.right, current_file, bindings, py_index, stack
        )
        if left is not None and right is not None:
            return left + right
    return None


def _ast_attribute_chain(node: ast.AST) -> str:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return ""


def _extract_django_include_info(
    handler_node: ast.AST,
    current_file: str,
    bindings: dict[str, ast.AST],
    py_index: dict[str, PythonImportIndex],
    known_files: set[str],
    routers: dict[str, list[APIEndpoint]],
) -> dict[str, object]:
    if (
        not isinstance(handler_node, ast.Call)
        or _ast_call_name(handler_node.func) != "include"
    ):
        return {"kind": "none"}
    if not handler_node.args:
        return {"kind": "none"}

    include_arg = handler_node.args[0]
    if isinstance(include_arg, ast.List):
        return {"kind": "inline", "nodes": list(include_arg.elts)}
    if isinstance(include_arg, ast.Tuple):
        return {"kind": "inline", "nodes": list(include_arg.elts)}
    if isinstance(include_arg, ast.Constant) and isinstance(include_arg.value, str):
        module_file = _resolve_python_module_path(
            current_file,
            include_arg.value,
            known_files,
            imported_name=None,
        )
        return {"kind": "module", "file": module_file}
    if isinstance(include_arg, ast.Attribute):
        chain = _ast_attribute_chain(include_arg)
        if chain and chain.endswith(".urls"):
            router_name = chain.split(".", 1)[0]
            if router_name in routers:
                return {"kind": "router", "endpoints": routers[router_name]}
            module_name = chain[: -len(".urls")]
            module_file = _resolve_python_module_path(
                current_file,
                module_name,
                known_files,
                imported_name="urls",
            )
            if module_file:
                return {"kind": "module", "file": module_file}
    if isinstance(include_arg, ast.Name) and include_arg.id in bindings:
        bound = bindings[include_arg.id]
        if isinstance(bound, (ast.List, ast.Tuple)):
            return {"kind": "inline", "nodes": list(bound.elts)}

    return {"kind": "none"}


def _resolve_django_project_setting(
    name: str,
    py_index: dict[str, PythonImportIndex],
) -> str | None:
    for rel_path, info in py_index.items():
        if rel_path.endswith("settings.py") and name in info.constants:
            return info.constants[name]
    return None


def _resolve_django_handler_file(
    route_file: str,
    handler_expr: str,
    file_contents: dict[str, str],
    py_index: dict[str, PythonImportIndex],
) -> str:
    expr = unwrap_django_handler_expr(handler_expr.strip())

    current_content = file_contents.get(route_file, "")
    handler_name = extract_django_handler_name(expr)
    if re.search(
        rf"""^\s*(?:async\s+def|def|class)\s+{re.escape(handler_name)}\b""",
        current_content,
        re.MULTILINE,
    ):
        return route_file

    if "." in expr:
        alias = expr.split(".", 1)[0]
        alias_file = py_index.get(route_file, PythonImportIndex()).imports.get(alias)
        if alias_file:
            return alias_file

    imported_file = py_index.get(route_file, PythonImportIndex()).imports.get(
        handler_name
    )
    if imported_file:
        return imported_file

    sibling_views = Path(route_file).with_name("views.py").as_posix()
    sibling_viewsets = Path(route_file).with_name("viewsets.py").as_posix()
    for candidate in (sibling_views, sibling_viewsets):
        if candidate in file_contents and re.search(
            rf"""^\s*(?:async\s+def|def|class)\s+{re.escape(handler_name)}\b""",
            file_contents[candidate],
            re.MULTILINE,
        ):
            return candidate

    return route_file


def _repo_rel_path(repo_root: Path, path_str: str) -> str:
    if not path_str:
        return ""
    path = Path(path_str)
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def _ordered_unique(items: list[str]) -> list[str]:
    ordered: list[str] = []
    for item in items:
        if item and item not in ordered:
            ordered.append(item)
    return ordered
