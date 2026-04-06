"""Call graph extraction for documentation evidence expansion.

Extracts function-level call relationships from parsed source files to enable
accurate execution-path evidence assembly in the generator.

Instead of following import edges (which over-includes), the call graph follows
actual call *sites* within function bodies — giving the real execution path
rather than "everything this file could theoretically use".

Supports Python (Django/Falcon/DRF) and JavaScript/TypeScript (Express/Node).
Celery .delay()/.apply_async() dispatches and Django signal sends are tracked
as distinct edge kinds so the generator can surface async side-effects.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any

from .parser.base import ParsedFile, Symbol

# ── Edge kinds ────────────────────────────────────────────────────────────────
CALL_KIND_LOCAL = "local"           # calls a repo-local function
CALL_KIND_CELERY = "celery_dispatch"  # .delay() / .apply_async()
CALL_KIND_SIGNAL = "signal_dispatch"  # Django signal .send() / .send_robust()
CALL_KIND_EVENT = "event_dispatch"    # EventEmitter.emit() / socket events
CALL_KIND_EXTERNAL = "external"       # stdlib or third-party

REL_KIND_IMPORTS = "imports"
REL_KIND_DEFINES = "defines"
REL_KIND_CONTAINS = "contains"
REL_KIND_DEFINED_IN = "defined_in"
REL_KIND_REFERENCES = "references"
REL_KIND_ROUTE_DECLARES = "route_declares"
REL_KIND_ROUTE_HANDLER = "route_handler"
REL_KIND_ROUTE_MIDDLEWARE = "route_middleware"
REL_KIND_COMPONENT_USES = "component_uses"
REL_KIND_COMPONENT_PROP = "component_prop"
REL_KIND_COMPONENT_EMITS = "component_emits"


@dataclass
class CallEdge:
    """A directed call edge from one function to another."""
    caller_file: str
    caller_symbol: str       # "ClassName.method" or "function_name"
    callee_file: str         # empty string when external
    callee_symbol: str       # called function / method / task name
    call_kind: str = CALL_KIND_LOCAL
    call_site_line: int = 0


@dataclass(frozen=True)
class GraphRelation:
    """A generic typed relation between graph nodes."""

    src: str
    dst: str
    kind: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CallGraph:
    """Function-level call graph for a single repository."""

    # caller_key → list of outgoing edges
    _callees: dict[str, list[CallEdge]] = field(
        default_factory=lambda: defaultdict(list)
    )
    # callee_key → list of incoming edges (for "who calls me?" queries)
    _callers: dict[str, list[CallEdge]] = field(
        default_factory=lambda: defaultdict(list)
    )
    _relations_out: dict[str, list[GraphRelation]] = field(
        default_factory=lambda: defaultdict(list)
    )
    _relations_in: dict[str, list[GraphRelation]] = field(
        default_factory=lambda: defaultdict(list)
    )

    @staticmethod
    def _key(file_path: str, symbol: str) -> str:
        return f"{file_path}::{symbol}"

    @staticmethod
    def file_node(file_path: str) -> str:
        return f"file:{file_path}"

    @classmethod
    def symbol_node(cls, file_path: str, symbol: str) -> str:
        return f"symbol:{cls._key(file_path, symbol)}"

    @staticmethod
    def import_node(specifier: str) -> str:
        return f"import:{specifier}"

    @staticmethod
    def external_node(name: str) -> str:
        return f"external:{name}"

    @staticmethod
    def route_node(method: str, path: str) -> str:
        return f"route:{method.upper()} {path}"

    @staticmethod
    def middleware_node(name: str) -> str:
        return f"middleware:{name}"

    def add_edge(self, edge: CallEdge) -> None:
        caller_key = self._key(edge.caller_file, edge.caller_symbol)
        callee_key = self._key(edge.callee_file, edge.callee_symbol)
        self._callees[caller_key].append(edge)
        self._callers[callee_key].append(edge)

    def add_relation(self, relation: GraphRelation) -> None:
        if relation in self._relations_out.get(relation.src, []):
            return
        self._relations_out[relation.src].append(relation)
        self._relations_in[relation.dst].append(relation)

    def get_callees(self, file_path: str, symbol: str) -> list[CallEdge]:
        return list(self._callees.get(self._key(file_path, symbol), []))

    def get_callers(self, file_path: str, symbol: str) -> list[CallEdge]:
        return list(self._callers.get(self._key(file_path, symbol), []))

    def get_outgoing_relations(
        self,
        node_id: str,
        *,
        kinds: set[str] | None = None,
    ) -> list[GraphRelation]:
        relations = list(self._relations_out.get(node_id, []))
        if kinds is None:
            return relations
        return [relation for relation in relations if relation.kind in kinds]

    def get_incoming_relations(
        self,
        node_id: str,
        *,
        kinds: set[str] | None = None,
    ) -> list[GraphRelation]:
        relations = list(self._relations_in.get(node_id, []))
        if kinds is None:
            return relations
        return [relation for relation in relations if relation.kind in kinds]

    def get_defined_symbols(self, file_path: str) -> list[str]:
        file_node = self.file_node(file_path)
        return [
            relation.dst
            for relation in self.get_outgoing_relations(file_node, kinds={REL_KIND_DEFINES})
        ]

    def get_import_targets(self, file_path: str) -> list[str]:
        file_node = self.file_node(file_path)
        return [
            relation.dst
            for relation in self.get_outgoing_relations(file_node, kinds={REL_KIND_IMPORTS})
        ]

    def get_execution_chain(
        self,
        file_path: str,
        symbol: str,
        max_depth: int = 4,
        local_only: bool = True,
    ) -> list[tuple[int, CallEdge]]:
        """BFS from an entry point, returning (depth, edge) pairs.

        Args:
            file_path:  source file of the root symbol.
            symbol:     function / method name to start from.
            max_depth:  how many hops to follow (default 4).
            local_only: if True, stop at EXTERNAL edges (don't follow them).
        """
        visited: set[str] = set()
        result: list[tuple[int, CallEdge]] = []
        queue: deque[tuple[str, str, int]] = deque()
        queue.append((file_path, symbol, 0))
        visited.add(self._key(file_path, symbol))

        while queue:
            cur_file, cur_sym, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for edge in self.get_callees(cur_file, cur_sym):
                if local_only and edge.call_kind == CALL_KIND_EXTERNAL:
                    continue
                result.append((depth + 1, edge))
                callee_key = self._key(edge.callee_file, edge.callee_symbol)
                if callee_key not in visited and edge.callee_file:
                    visited.add(callee_key)
                    queue.append((edge.callee_file, edge.callee_symbol, depth + 1))

        return result

    def get_async_side_effects(
        self, file_path: str, symbol: str, max_depth: int = 4
    ) -> list[CallEdge]:
        """Return all Celery dispatches and signal sends reachable from symbol."""
        chain = self.get_execution_chain(file_path, symbol, max_depth=max_depth, local_only=False)
        return [
            edge
            for _, edge in chain
            if edge.call_kind in (CALL_KIND_CELERY, CALL_KIND_SIGNAL, CALL_KIND_EVENT)
        ]

    def files_in_chain(self, file_path: str, symbol: str, max_depth: int = 4) -> list[str]:
        """Return unique file paths reachable from the given entry point."""
        chain = self.get_execution_chain(file_path, symbol, max_depth=max_depth)
        files = []
        seen: set[str] = set()
        for _, edge in chain:
            if edge.callee_file and edge.callee_file not in seen:
                seen.add(edge.callee_file)
                files.append(edge.callee_file)
        return files

    # ── Serialisation ─────────────────────────────────────────────────────

    def serialize(self) -> dict[str, Any]:
        seen: set[tuple] = set()
        edges = []
        for edge_list in self._callees.values():
            for e in edge_list:
                key = (e.caller_file, e.caller_symbol, e.callee_file, e.callee_symbol)
                if key not in seen:
                    seen.add(key)
                    edges.append({
                        "caller_file": e.caller_file,
                        "caller_symbol": e.caller_symbol,
                        "callee_file": e.callee_file,
                        "callee_symbol": e.callee_symbol,
                        "call_kind": e.call_kind,
                        "call_site_line": e.call_site_line,
                    })
        relations = []
        seen_relations: set[tuple[str, str, str]] = set()
        for relation_list in self._relations_out.values():
            for relation in relation_list:
                key = (relation.src, relation.dst, relation.kind)
                if key in seen_relations:
                    continue
                seen_relations.add(key)
                relations.append(
                    {
                        "src": relation.src,
                        "dst": relation.dst,
                        "kind": relation.kind,
                        "metadata": relation.metadata,
                    }
                )
        return {"edges": edges, "relations": relations, "version": 2}

    @classmethod
    def deserialize(cls, data: dict[str, Any]) -> CallGraph:
        g = cls()
        for e in data.get("edges", []):
            g.add_edge(CallEdge(**e))
        for relation in data.get("relations", []):
            g.add_relation(GraphRelation(**relation))
        return g

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.serialize(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> CallGraph:
        return cls.deserialize(json.loads(path.read_text(encoding="utf-8")))

    def __len__(self) -> int:
        return sum(len(v) for v in self._callees.values())

    def stats(self) -> dict[str, int]:
        all_edges = [e for edges in self._callees.values() for e in edges]
        relation_count = sum(len(v) for v in self._relations_out.values())
        stats = {
            "total_edges": len(all_edges),
            "local": sum(1 for e in all_edges if e.call_kind == CALL_KIND_LOCAL),
            "celery_dispatch": sum(1 for e in all_edges if e.call_kind == CALL_KIND_CELERY),
            "signal_dispatch": sum(1 for e in all_edges if e.call_kind == CALL_KIND_SIGNAL),
            "event_dispatch": sum(1 for e in all_edges if e.call_kind == CALL_KIND_EVENT),
            "external": sum(1 for e in all_edges if e.call_kind == CALL_KIND_EXTERNAL),
        }
        if relation_count:
            stats["graph_relations"] = relation_count
        return stats


# ── Extraction ─────────────────────────────────────────────────────────────────

# Python: obj.method(  or  func(
_PY_CALL_RE = re.compile(r"(?:(\w+)\.(\w+)\s*\(|(?<!['\"\w])(\w+)\s*\()")

# Python Celery dispatch
_PY_CELERY_DISPATCH_RE = re.compile(
    r"(\w+)\.(?:delay|apply_async|s|si|signature)\s*\("
)
# Python Django signal
_PY_SIGNAL_RE = re.compile(
    r"(\w+)\.(?:send|send_robust)\s*\(\s*sender"
)

# JS/TS: obj.method(  or  func(  or  await func(
_JS_CALL_RE = re.compile(
    r"(?:(\w+)\.(\w+)\s*\(|(?:await\s+)?(?<!['\"\w])(\w+)\s*\()"
)
# JS EventEmitter
_JS_EMIT_RE = re.compile(r"(?:\.emit|\.dispatch|\.trigger)\s*\(\s*['\"]([\w-]+)['\"]")


def build_call_graph(
    parsed_files: dict[str, ParsedFile],
    file_contents: dict[str, str],
    api_endpoints: list[dict[str, Any]] | None = None,
) -> CallGraph:
    """Build a function-level call graph from all parsed source files.

    Two-pass algorithm:
      Pass 1 — build a symbol index mapping name → (file, Symbol) for resolution.
      Pass 2 — for each function body, extract call sites and resolve them.
    """
    graph = CallGraph()

    # ── Pass 1: symbol index ────────────────────────────────────────────
    # maps short name → [(file_path, Symbol)]
    sym_index: dict[str, list[tuple[str, Symbol]]] = defaultdict(list)
    module_index = _build_module_index(parsed_files)
    celery_task_names: set[str] = set()

    for file_path, parsed in parsed_files.items():
        file_node = graph.file_node(file_path)
        for sym in parsed.symbols or []:
            sym_index[sym.name].append((file_path, sym))
            # Also index the last component of dotted names ("Cls.method" → "method")
            if "." in sym.name:
                short = sym.name.split(".")[-1]
                sym_index[short].append((file_path, sym))
            symbol_node = graph.symbol_node(file_path, sym.name)
            graph.add_relation(
                GraphRelation(src=file_node, dst=symbol_node, kind=REL_KIND_DEFINES)
            )
            graph.add_relation(
                GraphRelation(src=file_node, dst=symbol_node, kind=REL_KIND_CONTAINS)
            )
            graph.add_relation(
                GraphRelation(src=symbol_node, dst=file_node, kind=REL_KIND_DEFINED_IN)
            )

        for import_stmt in parsed.imports or []:
            target_node = _import_target_node(graph, file_path, import_stmt, module_index)
            graph.add_relation(
                GraphRelation(
                    src=file_node,
                    dst=target_node,
                    kind=REL_KIND_IMPORTS,
                    metadata={"import": import_stmt},
                )
            )

        # Detect Celery task names (decorated functions)
        content = file_contents.get(file_path, "")
        if "@shared_task" in content or "@app.task" in content or "@celery" in content:
            for sym in parsed.symbols or []:
                if sym.kind in ("function", "method", "async_function"):
                    celery_task_names.add(sym.name)

    # ── Pass 2: extract call sites per function ─────────────────────────
    for file_path, parsed in parsed_files.items():
        if not parsed or not parsed.symbols:
            continue
        content = file_contents.get(file_path, "")
        if not content:
            continue
        lines = content.splitlines()
        lang = (parsed.language or "").lower()

        for sym in parsed.symbols:
            if sym.kind not in ("function", "method", "async_function"):
                continue
            end_idx = min(len(lines), (sym.end_line or sym.start_line + 60))
            body_lines = lines[max(0, sym.start_line - 1):end_idx]
            if not body_lines:
                continue
            body = _body_without_declaration(body_lines, lang)
            if not body.strip():
                continue

            if lang == "python":
                _extract_py_calls(
                    graph, file_path, sym.name, body, sym_index, celery_task_names
                )
            elif lang in ("javascript", "typescript"):
                _extract_js_calls(graph, file_path, sym.name, body, sym_index)

    _add_framework_overlay_relations(graph, parsed_files, api_endpoints or [])
    return graph


def _body_without_declaration(lines: list[str], lang: str) -> str:
    """Drop declaration signatures while preserving any inline body text."""
    first = lines[0]
    remainder = lines[1:]
    inline = ""
    if lang == "python":
        if ":" in first:
            inline = first.split(":", 1)[1].strip()
    elif lang in ("javascript", "typescript") and "{" in first:
        inline = first.split("{", 1)[1].strip()
    parts = [part for part in ([inline] if inline else []) + remainder if part.strip()]
    return "\n".join(parts)


def _build_module_index(parsed_files: dict[str, ParsedFile]) -> dict[str, str]:
    index: dict[str, str] = {}
    for file_path, _parsed in parsed_files.items():
        normalized = file_path.replace("\\", "/")
        stem = str(Path(normalized).with_suffix(""))
        candidates = {
            stem,
            stem.replace("/", "."),
            Path(normalized).stem,
        }
        if normalized.endswith("/__init__.py"):
            pkg = normalized[: -len("/__init__.py")]
            candidates.add(pkg)
            candidates.add(pkg.replace("/", "."))
        if Path(normalized).stem == "index":
            parent = str(Path(stem).parent)
            if parent and parent != ".":
                candidates.add(parent)
                candidates.add(parent.replace("/", "."))
        for candidate in candidates:
            key = candidate.strip().lower()
            if key and key not in index:
                index[key] = normalized
    return index


def _import_target_node(
    graph: CallGraph,
    importer_file: str,
    import_stmt: str,
    module_index: dict[str, str],
) -> str:
    specifier = _extract_import_specifier(import_stmt)
    if not specifier:
        return graph.import_node(import_stmt.strip())
    resolved = _resolve_import_specifier(importer_file, specifier, module_index)
    if resolved:
        return graph.file_node(resolved)
    return graph.import_node(specifier)


def _extract_import_specifier(import_stmt: str) -> str:
    patterns = (
        r"from\s+['\"]([^'\"]+)['\"]",
        r"require\(\s*['\"]([^'\"]+)['\"]\s*\)",
        r"from\s+([A-Za-z0-9_\.\/]+)\s+import",
        r"import\s+([A-Za-z0-9_\.\/]+)",
        r"use\s+([A-Za-z0-9_\\]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, import_stmt)
        if match:
            return match.group(1).strip()
    return ""


def _resolve_import_specifier(
    importer_file: str,
    specifier: str,
    module_index: dict[str, str],
) -> str | None:
    normalized = specifier.strip()
    if not normalized:
        return None

    if normalized.startswith("."):
        importer_dir = Path(importer_file).parent
        candidates = []
        base = (importer_dir / normalized).as_posix()
        candidates.extend(
            [
                base,
                f"{base}.py",
                f"{base}.js",
                f"{base}.ts",
                f"{base}.tsx",
                f"{base}.jsx",
                f"{base}.php",
                f"{base}.go",
                f"{base}/index.js",
                f"{base}/index.ts",
                f"{base}/__init__.py",
            ]
        )
        for candidate in candidates:
            key = candidate.strip("./").lower()
            if candidate in module_index.values():
                return candidate
            if key in module_index:
                return module_index[key]
        return None

    dotted = normalized.replace("\\", ".")
    slash = normalized.replace(".", "/").replace("\\", "/")
    for candidate in (
        normalized,
        dotted,
        slash,
        Path(slash).stem,
    ):
        key = candidate.lower()
        if key in module_index:
            return module_index[key]
    return None


def _add_framework_overlay_relations(
    graph: CallGraph,
    parsed_files: dict[str, ParsedFile],
    api_endpoints: list[dict[str, Any]],
) -> None:
    for endpoint in api_endpoints:
        method = str(endpoint.get("method", "") or "").upper()
        path = str(endpoint.get("path", "") or "").strip()
        if not method or not path:
            continue
        route_node = graph.route_node(method, path)
        route_file = str(endpoint.get("route_file", "") or endpoint.get("file", "") or "").strip()
        handler_file = str(endpoint.get("handler_file", "") or endpoint.get("file", "") or route_file).strip()
        handler = str(endpoint.get("handler", "") or "").strip()
        framework = str(endpoint.get("framework", "") or "").strip()

        if route_file:
            graph.add_relation(
                GraphRelation(
                    src=graph.file_node(route_file),
                    dst=route_node,
                    kind=REL_KIND_ROUTE_DECLARES,
                    metadata={"framework": framework},
                )
            )

        if handler_file and handler:
            graph.add_relation(
                GraphRelation(
                    src=route_node,
                    dst=graph.symbol_node(handler_file, handler),
                    kind=REL_KIND_ROUTE_HANDLER,
                    metadata={"framework": framework},
                )
            )

        for middleware in endpoint.get("middleware", []) or []:
            name = str(middleware).strip()
            if not name:
                continue
            graph.add_relation(
                GraphRelation(
                    src=route_node,
                    dst=graph.middleware_node(name),
                    kind=REL_KIND_ROUTE_MIDDLEWARE,
                    metadata={"framework": framework},
                )
            )

    for file_path, parsed in parsed_files.items():
        if (parsed.language or "").lower() != "vue":
            continue
        component_symbols = [sym for sym in parsed.symbols or [] if sym.kind == "component"]
        if not component_symbols:
            continue
        component_node = graph.symbol_node(file_path, component_symbols[0].name)
        for symbol in parsed.symbols or []:
            if symbol.name == "props":
                for prop in symbol.props:
                    prop_name = str(prop).strip()
                    if prop_name:
                        graph.add_relation(
                            GraphRelation(
                                src=component_node,
                                dst=graph.external_node(f"vue:prop:{prop_name}"),
                                kind=REL_KIND_COMPONENT_PROP,
                            )
                        )
            elif symbol.name == "emit":
                for event_name in symbol.fields:
                    emitted = str(event_name).strip()
                    if emitted:
                        graph.add_relation(
                            GraphRelation(
                                src=component_node,
                                dst=graph.external_node(f"vue:emit:{emitted}"),
                                kind=REL_KIND_COMPONENT_EMITS,
                            )
                        )
            elif symbol.name in {"router", "route", "pinia", "store", "storeRefs", "composables", "model", "slots", "components"}:
                graph.add_relation(
                    GraphRelation(
                        src=component_node,
                        dst=graph.external_node(f"vue:{symbol.name}"),
                        kind=REL_KIND_COMPONENT_USES,
                    )
                )


# ── Python extraction ──────────────────────────────────────────────────────────

def _extract_py_calls(
    graph: CallGraph,
    file_path: str,
    caller: str,
    body: str,
    sym_index: dict[str, list[tuple[str, Symbol]]],
    celery_tasks: set[str],
) -> None:
    caller_node = graph.symbol_node(file_path, caller)
    # Celery dispatch first (more specific)
    for m in _PY_CELERY_DISPATCH_RE.finditer(body):
        task_name = m.group(1)
        if task_name.lower() in _PY_BUILTINS:
            continue
        candidates = sym_index.get(task_name, [])
        graph.add_edge(CallEdge(
            caller_file=file_path,
            caller_symbol=caller,
            callee_file=candidates[0][0] if candidates else "",
            callee_symbol=task_name,
            call_kind=CALL_KIND_CELERY,
        ))
        graph.add_relation(
            GraphRelation(
                src=caller_node,
                dst=(
                    graph.symbol_node(candidates[0][0], candidates[0][1].name)
                    if candidates
                    else graph.external_node(task_name)
                ),
                kind=REL_KIND_REFERENCES,
                metadata={"call_kind": CALL_KIND_CELERY},
            )
        )

    # Django signal dispatch
    for m in _PY_SIGNAL_RE.finditer(body):
        signal_name = m.group(1)
        graph.add_edge(CallEdge(
            caller_file=file_path,
            caller_symbol=caller,
            callee_file="",
            callee_symbol=f"signal:{signal_name}",
            call_kind=CALL_KIND_SIGNAL,
        ))
        graph.add_relation(
            GraphRelation(
                src=caller_node,
                dst=graph.external_node(f"signal:{signal_name}"),
                kind=REL_KIND_REFERENCES,
                metadata={"call_kind": CALL_KIND_SIGNAL},
            )
        )

    # General calls
    seen: set[str] = set()
    for m in _PY_CALL_RE.finditer(body):
        name = m.group(2) or m.group(3)  # method name or bare function name
        if not name or name in seen or name.lower() in _PY_BUILTINS:
            continue
        seen.add(name)
        candidates = sym_index.get(name, [])
        if candidates:
            for callee_file, callee_sym in candidates[:2]:
                graph.add_edge(CallEdge(
                    caller_file=file_path,
                    caller_symbol=caller,
                    callee_file=callee_file,
                    callee_symbol=callee_sym.name,
                    call_kind=CALL_KIND_LOCAL,
                ))
                graph.add_relation(
                    GraphRelation(
                        src=caller_node,
                        dst=graph.symbol_node(callee_file, callee_sym.name),
                        kind=REL_KIND_REFERENCES,
                        metadata={"call_kind": CALL_KIND_LOCAL},
                    )
                )
        else:
            graph.add_edge(CallEdge(
                caller_file=file_path,
                caller_symbol=caller,
                callee_file="",
                callee_symbol=name,
                call_kind=CALL_KIND_EXTERNAL,
            ))
            graph.add_relation(
                GraphRelation(
                    src=caller_node,
                    dst=graph.external_node(name),
                    kind=REL_KIND_REFERENCES,
                    metadata={"call_kind": CALL_KIND_EXTERNAL},
                )
            )


# ── JS/TS extraction ───────────────────────────────────────────────────────────

def _extract_js_calls(
    graph: CallGraph,
    file_path: str,
    caller: str,
    body: str,
    sym_index: dict[str, list[tuple[str, Symbol]]],
) -> None:
    caller_node = graph.symbol_node(file_path, caller)
    # Event emits
    for m in _JS_EMIT_RE.finditer(body):
        graph.add_edge(CallEdge(
            caller_file=file_path,
            caller_symbol=caller,
            callee_file="",
            callee_symbol=f"event:{m.group(1)}",
            call_kind=CALL_KIND_EVENT,
        ))
        graph.add_relation(
            GraphRelation(
                src=caller_node,
                dst=graph.external_node(f"event:{m.group(1)}"),
                kind=REL_KIND_REFERENCES,
                metadata={"call_kind": CALL_KIND_EVENT},
            )
        )

    seen: set[str] = set()
    for m in _JS_CALL_RE.finditer(body):
        name = m.group(2) or m.group(3)
        if not name or name in seen or name.lower() in _JS_BUILTINS:
            continue
        seen.add(name)
        candidates = sym_index.get(name, [])
        if candidates:
            for callee_file, callee_sym in candidates[:2]:
                graph.add_edge(CallEdge(
                    caller_file=file_path,
                    caller_symbol=caller,
                    callee_file=callee_file,
                    callee_symbol=callee_sym.name,
                    call_kind=CALL_KIND_LOCAL,
                ))
                graph.add_relation(
                    GraphRelation(
                        src=caller_node,
                        dst=graph.symbol_node(callee_file, callee_sym.name),
                        kind=REL_KIND_REFERENCES,
                        metadata={"call_kind": CALL_KIND_LOCAL},
                    )
                )
        else:
            graph.add_edge(CallEdge(
                caller_file=file_path,
                caller_symbol=caller,
                callee_file="",
                callee_symbol=name,
                call_kind=CALL_KIND_EXTERNAL,
            ))
            graph.add_relation(
                GraphRelation(
                    src=caller_node,
                    dst=graph.external_node(name),
                    kind=REL_KIND_REFERENCES,
                    metadata={"call_kind": CALL_KIND_EXTERNAL},
                )
            )


# ── Builtin skip sets ──────────────────────────────────────────────────────────

_PY_BUILTINS = frozenset({
    "print", "len", "range", "enumerate", "zip", "map", "filter", "sorted",
    "list", "dict", "set", "tuple", "str", "int", "float", "bool", "bytes",
    "open", "type", "isinstance", "issubclass", "hasattr", "getattr", "setattr",
    "delattr", "super", "property", "staticmethod", "classmethod",
    "append", "extend", "update", "get", "items", "keys", "values", "format",
    "strip", "split", "join", "replace", "lower", "upper", "encode", "decode",
    "log", "error", "info", "warning", "debug", "exception", "critical",
    "self", "cls", "raise", "return", "yield", "await", "async", "lambda",
    "not", "and", "or", "in", "is", "if", "else", "for", "while",
    "json", "os", "sys", "re", "path", "logger", "console",
})

_JS_BUILTINS = frozenset({
    "console", "log", "error", "warn", "info", "JSON", "parse", "stringify",
    "parseInt", "parseFloat", "toString", "valueOf", "hasOwnProperty",
    "push", "pop", "shift", "unshift", "splice", "slice", "map", "filter",
    "reduce", "forEach", "find", "findIndex", "includes", "some", "every",
    "Object", "Array", "String", "Number", "Boolean", "Promise", "resolve",
    "reject", "then", "catch", "finally", "next", "throw", "await",
    "require", "exports", "module", "process", "setTimeout", "setInterval",
    "clearTimeout", "clearInterval", "res", "req", "send", "json",
    "status", "end", "get", "set", "delete", "keys", "values", "entries",
    "assign", "create", "freeze", "is", "from", "of",
})
