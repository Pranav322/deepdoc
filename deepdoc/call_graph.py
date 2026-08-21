"""Call graph extraction for documentation evidence expansion.

Extracts function-level call relationships from parsed source files to enable
accurate execution-path evidence assembly in the generator.

Instead of following import edges (which over-includes), the call graph follows
actual call *sites* within function bodies — giving the real execution path
rather than "everything this file could theoretically use".

Supports Python (Django/Falcon/DRF/FastAPI), JavaScript/TypeScript
(Express/Fastify/NestJS), Go, and PHP (Laravel).
Celery .delay()/.apply_async() dispatches, Django signal sends, and JS
EventEmitter emits are tracked as distinct edge kinds so the generator can
surface async side-effects.

Import-evidence-gated call-site resolution (never guesses):
same-file → imported (alias-aware, multi-hop re-export, cycle-guarded)
→ unambiguous repo-wide → import-evidence-gated → external.
Member calls resolve only with explicit evidence (self/cls, imported class,
module alias); Python self.method() walks enclosing class's base chain
cross-file (transitive, cycle-guarded).
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
REL_KIND_NESTJS_GUARD = "nestjs_guard"
REL_KIND_NESTJS_INTERCEPTOR = "nestjs_interceptor"


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
    file_symbol_names: dict[str, dict[str, Symbol]] = {}
    file_imports_map: dict[str, _FileImports] = {}
    file_classes: dict[str, list[Symbol]] = {}
    class_bases: dict[tuple[str, str], list[str]] = {}

    for file_path, parsed in parsed_files.items():
        file_node = graph.file_node(file_path)
        file_syms = file_symbol_names.setdefault(file_path, {})
        file_imports_map[file_path] = _parse_file_imports(parsed)
        for sym in parsed.symbols or []:
            sym_index[sym.name].append((file_path, sym))
            file_syms.setdefault(sym.name, sym)
            if sym.kind == "class":
                file_classes.setdefault(file_path, []).append(sym)
                bases = _parse_class_bases(sym.signature)
                if bases:
                    class_bases[(file_path, sym.name)] = bases
            # Also index the last component of dotted names ("Cls.method" → "method")
            if "." in sym.name:
                short = sym.name.split(".")[-1]
                sym_index[short].append((file_path, sym))
                file_syms.setdefault(short, sym)
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

        # Detect Celery task names (decorator-scoped, not whole-file substring)
        content = file_contents.get(file_path, "")
        content_lines = content.splitlines()
        for sym in parsed.symbols or []:
            if sym.kind in _CALLABLE_KINDS and _is_celery_task(sym, content_lines):
                celery_task_names.add(sym.name)

    # Pre-resolve each file's imported repo files for the ambiguity gate.
    imported_files_map: dict[str, set[str]] = {}
    for file_path, imports in file_imports_map.items():
        targets: set[str] = set()
        specs = [spec for spec, _ in imports.names.values()] + list(imports.modules.values())
        for spec in specs:
            resolved = _resolve_import_specifier(file_path, spec, module_index)
            if resolved:
                targets.add(resolved)
        imported_files_map[file_path] = targets

    ctx = _ResolverContext(
        sym_index=sym_index,
        module_index=module_index,
        file_symbol_names=file_symbol_names,
        file_imports_map=file_imports_map,
        imported_files_map=imported_files_map,
        parsed_files=parsed_files,
        class_bases=class_bases,
    )

    # ── Pass 2: extract call sites per function ─────────────────────────
    for file_path, parsed in parsed_files.items():
        if not parsed or not parsed.symbols:
            continue
        content = file_contents.get(file_path, "")
        if not content:
            continue
        lines = content.splitlines()
        lang = (parsed.language or "").lower()
        symbol_starts = sorted(
            s.start_line for s in parsed.symbols if s.start_line > 0
        )

        for sym in parsed.symbols:
            if sym.kind not in _CALLABLE_KINDS:
                continue
            if sym.end_line:
                end_idx = min(len(lines), sym.end_line)
            else:
                nxt = next((s for s in symbol_starts if s > sym.start_line), None)
                end_idx = min(len(lines), (nxt - 1) if nxt else sym.start_line + 400)
            body_lines = lines[max(0, sym.start_line - 1):end_idx]
            if not body_lines:
                continue
            body = _body_without_declaration(body_lines, lang)
            if not body.strip():
                continue

            if lang == "python":
                caller_class = _enclosing_class(sym, file_classes.get(file_path, []))
                _extract_py_calls(
                    graph, file_path, sym.name, body, ctx, celery_task_names, caller_class
                )
            elif lang in ("javascript", "typescript"):
                _extract_js_calls(graph, file_path, sym.name, body, ctx)
            elif lang == "go":
                _extract_go_calls(graph, file_path, sym.name, body, ctx)
            elif lang == "php":
                _extract_php_calls(graph, file_path, sym.name, body, ctx)

    _add_framework_overlay_relations(graph, parsed_files, api_endpoints or [])
    return graph


def _enclosing_class(method_sym: Symbol, classes: list[Symbol]) -> str | None:
    """Return the name of the class whose line range encloses a method, if any."""
    for cls in classes:
        if cls.end_line and cls.start_line <= method_sym.start_line <= cls.end_line:
            return cls.name
    return None


def _body_without_declaration(lines: list[str], lang: str) -> str:
    """Drop declaration signatures while preserving any inline body text."""
    first = lines[0]
    remainder = lines[1:]
    inline = ""
    if lang == "python":
        if ":" in first:
            inline = first.split(":", 1)[1].strip()
    elif lang in ("javascript", "typescript", "go", "php") and "{" in first:
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


@dataclass
class _FileImports:
    """Structured view of a file's raw import statements."""

    # local name → (module_specifier, original_name)
    names: dict[str, tuple[str, str]] = field(default_factory=dict)
    # module alias / last component → module_specifier
    modules: dict[str, str] = field(default_factory=dict)


_PY_FROM_IMPORT_RE = re.compile(r"from\s+([\w.]+)\s+import\s+(.+)", re.DOTALL)
_PY_IMPORT_RE = re.compile(r"import\s+(.+)", re.DOTALL)
_JS_IMPORT_FROM_RE = re.compile(r"import\s+(.+?)\s+from\s+['\"]([^'\"]+)['\"]", re.DOTALL)
_JS_REQUIRE_RE = re.compile(
    r"(?:const|let|var)\s+(\{[^}]*\}|\w+)\s*=\s*require\(\s*['\"]([^'\"]+)['\"]\s*\)"
)
_GO_IMPORT_LINE_RE = re.compile(r"(?:(\w+)\s+)?\"([^\"]+)\"")
_PHP_USE_RE = re.compile(r"use\s+(?:function\s+|const\s+)?([\w\\]+)(?:\s+as\s+(\w+))?\s*;?")
_PHP_USE_GROUP_RE = re.compile(r"use\s+([\w\\]+)\\\{([^}]*)\}\s*;?")


def _parse_file_imports(parsed: ParsedFile) -> _FileImports:
    """Parse raw import statement strings into a name/module lookup."""
    imports = _FileImports()
    lang = (parsed.language or "").lower()
    for stmt in parsed.imports or []:
        stmt = stmt.strip()
        if lang == "python":
            _parse_py_import(stmt, imports)
        elif lang in ("javascript", "typescript"):
            _parse_js_import(stmt, imports)
        elif lang == "go":
            _parse_go_import(stmt, imports)
        elif lang == "php":
            _parse_php_import(stmt, imports)
    return imports


def _parse_go_import(stmt: str, imports: _FileImports) -> None:
    # Handles single `import "p/q"`, aliased `import alias "p/q"`, and grouped
    # blocks that arrive as one multiline string with quoted paths per line.
    for m in _GO_IMPORT_LINE_RE.finditer(stmt):
        alias, spec = m.group(1), m.group(2)
        if alias and alias != "import":
            imports.modules[alias] = spec
        else:
            imports.modules[spec.split("/")[-1]] = spec


def _parse_php_import(stmt: str, imports: _FileImports) -> None:
    grp = _PHP_USE_GROUP_RE.match(stmt)
    if grp:
        prefix = grp.group(1)
        for item in grp.group(2).split(","):
            parts = item.strip().split()
            if not parts:
                continue
            name = parts[0]
            local = parts[2] if len(parts) == 3 and parts[1] == "as" else name.split("\\")[-1]
            imports.names[local] = (f"{prefix}\\{name}", name.split("\\")[-1])
        return
    m = _PHP_USE_RE.match(stmt)
    if m:
        spec = m.group(1)
        original = spec.split("\\")[-1]
        local = m.group(2) or original
        imports.names[local] = (spec, original)


def _parse_py_import(stmt: str, imports: _FileImports) -> None:
    m = _PY_FROM_IMPORT_RE.match(stmt)
    if m:
        module = m.group(1)
        names_part = m.group(2).replace("(", " ").replace(")", " ")
        for item in names_part.split(","):
            item = item.strip().rstrip("\\").strip()
            if not item or item == "*":
                continue
            parts = item.split()
            if len(parts) == 3 and parts[1] == "as":
                imports.names[parts[2]] = (module, parts[0])
            elif len(parts) == 1:
                imports.names[parts[0]] = (module, parts[0])
        return
    m = _PY_IMPORT_RE.match(stmt)
    if m:
        for item in m.group(1).split(","):
            parts = item.strip().split()
            if not parts:
                continue
            if len(parts) == 3 and parts[1] == "as":
                imports.modules[parts[2]] = parts[0]
            elif len(parts) == 1:
                imports.modules[parts[0].split(".")[-1]] = parts[0]


def _parse_js_import(stmt: str, imports: _FileImports) -> None:
    m = _JS_IMPORT_FROM_RE.search(stmt)
    if m:
        clause, spec = m.group(1), m.group(2)
        star = re.search(r"\*\s+as\s+(\w+)", clause)
        if star:
            imports.modules[star.group(1)] = spec
        braces = re.search(r"\{([^}]*)\}", clause)
        if braces:
            for item in braces.group(1).split(","):
                parts = item.strip().split()
                if len(parts) == 3 and parts[1] == "as":
                    imports.names[parts[2]] = (spec, parts[0])
                elif len(parts) == 1 and parts[0]:
                    imports.names[parts[0]] = (spec, parts[0])
        default = re.match(r"(\w+)\s*(?:,|$)", clause.strip())
        if default and default.group(1) not in ("type",):
            imports.names[default.group(1)] = (spec, "default")
        return
    m = _JS_REQUIRE_RE.search(stmt)
    if m:
        clause, spec = m.group(1), m.group(2)
        if clause.startswith("{"):
            for item in clause.strip("{}").split(","):
                parts = [p.strip() for p in item.split(":")]
                if len(parts) == 2 and parts[0] and parts[1]:
                    imports.names[parts[1]] = (spec, parts[0])
                elif parts[0]:
                    imports.names[parts[0]] = (spec, parts[0])
        else:
            imports.modules[clause] = spec


@dataclass
class _ResolverContext:
    """Shared lookup tables for call-site resolution."""

    sym_index: dict[str, list[tuple[str, Symbol]]]
    module_index: dict[str, str]
    file_symbol_names: dict[str, dict[str, Symbol]]
    file_imports_map: dict[str, _FileImports]
    imported_files_map: dict[str, set[str]]
    parsed_files: dict[str, ParsedFile]
    # (file, class_name) → direct base-class names (last dotted segment)
    class_bases: dict[tuple[str, str], list[str]] = field(default_factory=dict)

    def imports_for(self, file_path: str) -> _FileImports:
        return self.file_imports_map.get(file_path) or _FileImports()


_CLASS_BASES_RE = re.compile(r"class\s+\w+\s*\(([^)]*)\)")


def _parse_class_bases(signature: str) -> list[str]:
    """Extract direct base-class names from a class signature line."""
    m = _CLASS_BASES_RE.search(signature or "")
    if not m:
        return []
    bases: list[str] = []
    for part in m.group(1).split(","):
        part = part.strip()
        if not part or "=" in part:  # skip metaclass=/kwargs
            continue
        bases.append(part.split(".")[-1])
    return bases


_CALLABLE_KINDS = ("function", "method", "async_function")


def _resolve_bare_call(
    name: str, caller_file: str, ctx: _ResolverContext
) -> tuple[str, Symbol] | None:
    """Resolve a bare call name. Never guesses: same-file → imported (alias-aware,
    multi-hop re-export) → unambiguous repo-wide → import-evidence-gated → None."""
    # 1. Same-file definition
    sym = ctx.file_symbol_names.get(caller_file, {}).get(name)
    if sym is not None:
        return (caller_file, sym)

    # 2. Imported name (alias-aware, follow re-export chains with a cycle guard)
    imports = ctx.imports_for(caller_file)
    if name in imports.names:
        spec, original = imports.names[name]
        resolved = _resolve_import_specifier(caller_file, spec, ctx.module_index)
        seen: set[str] = {caller_file}
        local_name = name
        while resolved and resolved not in seen:
            seen.add(resolved)
            target_syms = ctx.file_symbol_names.get(resolved, {})
            for candidate_name in (original, local_name):
                target = target_syms.get(candidate_name)
                if target is not None:
                    return (resolved, target)
            reexports = ctx.imports_for(resolved)
            if original not in reexports.names:
                return None
            spec, next_original = reexports.names[original]
            next_resolved = _resolve_import_specifier(resolved, spec, ctx.module_index)
            original = next_original
            resolved = next_resolved
        return None

    # 3. Repo-wide, gated on ambiguity
    dedup: dict[tuple[str, str], tuple[str, Symbol]] = {}
    for cand_file, cand_sym in ctx.sym_index.get(name, []):
        dedup[(cand_file, cand_sym.name)] = (cand_file, cand_sym)
    unique = list(dedup.values())
    if len(unique) == 1:
        return unique[0]
    if len(unique) > 1:
        # Ambiguous: resolve only if import evidence collapses to exactly one.
        imported_files = ctx.imported_files_map.get(caller_file, set())
        evidence = [cand for cand in unique if cand[0] in imported_files]
        if len(evidence) == 1:
            return evidence[0]
    return None


def _resolve_member_call(
    receiver: str,
    method: str,
    caller_file: str,
    ctx: _ResolverContext,
    caller_class: str | None = None,
) -> tuple[str, Symbol] | None:
    """Resolve `receiver.method()` only with explicit evidence; never repo-wide."""
    if receiver in ("self", "cls"):
        sym = ctx.file_symbol_names.get(caller_file, {}).get(method)
        if sym is not None:
            return (caller_file, sym)
        # Not in this file — walk the enclosing class's base chain (cross-file).
        if caller_class:
            return _resolve_inherited_method(caller_file, caller_class, method, ctx)
        return None

    # Same-file class
    recv_sym = ctx.file_symbol_names.get(caller_file, {}).get(receiver)
    if recv_sym is not None and recv_sym.kind == "class":
        method_sym = _find_method_in_class(
            ctx.parsed_files.get(caller_file), recv_sym, method
        )
        return (caller_file, method_sym) if method_sym is not None else None

    imports = ctx.imports_for(caller_file)
    # Imported class
    if receiver in imports.names:
        spec, original = imports.names[receiver]
        resolved = _resolve_import_specifier(caller_file, spec, ctx.module_index)
        if resolved:
            target_syms = ctx.file_symbol_names.get(resolved, {})
            cls_sym = target_syms.get(original) or target_syms.get(receiver)
            if cls_sym is not None and cls_sym.kind == "class":
                method_sym = _find_method_in_class(
                    ctx.parsed_files.get(resolved), cls_sym, method
                )
                return (resolved, method_sym) if method_sym is not None else None
        return None

    # Module alias (import utils; utils.save())
    if receiver in imports.modules:
        resolved = _resolve_import_specifier(
            caller_file, imports.modules[receiver], ctx.module_index
        )
        if resolved:
            sym = ctx.file_symbol_names.get(resolved, {}).get(method)
            return (resolved, sym) if sym is not None else None
    return None


def _find_method_in_class(
    parsed: ParsedFile | None, class_sym: Symbol, method: str
) -> Symbol | None:
    """Find a method Symbol positionally inside a class's line range."""
    if parsed is None:
        return None

    def _matches(sym: Symbol) -> bool:
        return sym.kind in _CALLABLE_KINDS and (
            sym.name == method or sym.name.endswith(f".{method}")
        )

    if class_sym.end_line:
        for sym in parsed.symbols or []:
            if _matches(sym) and class_sym.start_line <= sym.start_line <= class_sym.end_line:
                return sym
        return None
    # Class range unknown (regex-fallback parse) — fall back to name-in-file.
    for sym in parsed.symbols or []:
        if _matches(sym):
            return sym
    return None


def _resolve_class(
    name: str, caller_file: str, ctx: _ResolverContext
) -> tuple[str, Symbol] | None:
    """Resolve a class name to its defining (file, Symbol) via same-file → imports."""
    sym = ctx.file_symbol_names.get(caller_file, {}).get(name)
    if sym is not None and sym.kind == "class":
        return (caller_file, sym)
    imports = ctx.imports_for(caller_file)
    if name in imports.names:
        spec, original = imports.names[name]
        resolved = _resolve_import_specifier(caller_file, spec, ctx.module_index)
        if resolved:
            target = ctx.file_symbol_names.get(resolved, {})
            cls = target.get(original) or target.get(name)
            if cls is not None and cls.kind == "class":
                return (resolved, cls)
    return None


def _resolve_inherited_method(
    file_path: str,
    class_name: str,
    method: str,
    ctx: _ResolverContext,
    seen: set[tuple[str, str]] | None = None,
    depth: int = 0,
) -> tuple[str, Symbol] | None:
    """Walk a class's base chain (cross-file, transitive) to find an inherited
    method. One base at a time, cycle-guarded, depth-capped — no MRO simulation.
    Third-party bases (unresolvable imports) simply stop that branch."""
    if depth > 5:
        return None
    seen = seen if seen is not None else set()
    key = (file_path, class_name)
    if key in seen:
        return None
    seen.add(key)
    for base in ctx.class_bases.get(key, []):
        resolved = _resolve_class(base, file_path, ctx)
        if resolved is None:
            continue
        base_file, base_sym = resolved
        method_sym = _find_method_in_class(ctx.parsed_files.get(base_file), base_sym, method)
        if method_sym is not None:
            return (base_file, method_sym)
        deeper = _resolve_inherited_method(base_file, base_sym.name, method, ctx, seen, depth + 1)
        if deeper is not None:
            return deeper
    return None


# ── String/comment stripping (general-call regex input only) ──────────────────

_PY_TRIPLE_STR_RE = re.compile(r"'''[\s\S]*?'''|\"\"\"[\s\S]*?\"\"\"")
_QUOTED_STR_RE = re.compile(r"'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\"")
_PY_COMMENT_RE = re.compile(r"#[^\n]*")
_JS_TEMPLATE_RE = re.compile(r"`[\s\S]*?`")
_JS_BLOCK_COMMENT_RE = re.compile(r"/\*[\s\S]*?\*/")
_JS_LINE_COMMENT_RE = re.compile(r"//[^\n]*")


def _strip_strings_and_comments(body: str, lang: str) -> str:
    """Remove string literals and comments so the call regex can't match inside
    them. Strings first, so comment markers inside strings can't truncate lines.
    Accepted loss: call sites inside f-string braces / JS template ${...}."""
    if lang == "python":
        body = _PY_TRIPLE_STR_RE.sub('""', body)
        body = _QUOTED_STR_RE.sub('""', body)
        return _PY_COMMENT_RE.sub("", body)
    # js/ts/go: backtick (JS template / Go raw string), quotes, block + line comments
    body = _JS_TEMPLATE_RE.sub('""', body)
    body = _QUOTED_STR_RE.sub('""', body)
    body = _JS_BLOCK_COMMENT_RE.sub("", body)
    body = _JS_LINE_COMMENT_RE.sub("", body)
    if lang == "php":
        body = _PY_COMMENT_RE.sub("", body)  # PHP also has # line comments
    return body


# ── Celery task detection (decorator-scoped) ───────────────────────────────────

_CELERY_DECORATOR_RE = re.compile(r"@?(?:[\w.]+\.)?(?:shared_task|task)\b")


def _is_celery_task(sym: Symbol, lines: list[str]) -> bool:
    """True only for symbols actually carrying a Celery task decorator."""
    if any(_CELERY_DECORATOR_RE.search(dec) for dec in sym.decorators or []):
        return True
    if not sym.decorators and sym.start_line > 1:
        # Regex-fallback parses leave decorators empty — scan the lines above.
        window = lines[max(0, sym.start_line - 4):sym.start_line - 1]
        return any(
            _CELERY_DECORATOR_RE.search(line) for line in window if line.lstrip().startswith("@")
        )
    return False


def _emit_call(
    graph: CallGraph,
    file_path: str,
    caller: str,
    name: str,
    resolved: tuple[str, Symbol] | None,
) -> None:
    """Emit one LOCAL edge on a resolution hit, one EXTERNAL edge on a miss."""
    caller_node = graph.symbol_node(file_path, caller)
    if resolved is not None:
        callee_file, callee_sym = resolved
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

    _add_nestjs_decorator_edges(graph, parsed_files)


def _add_nestjs_decorator_edges(
    graph: CallGraph,
    parsed_files: dict[str, ParsedFile],
) -> None:
    import re

    guard_re = re.compile(r"@UseGuards\s*\(\s*(\w+(?:\s*,\s*\w+)*)\s*\)")
    interceptor_re = re.compile(r"@UseInterceptors\s*\(\s*(\w+(?:\s*,\s*\w+)*)\s*\)")

    for file_path, parsed in parsed_files.items():
        if parsed.language not in ("typescript", "javascript"):
            continue
        content_str = "\n".join(
            getattr(sym, "signature", "") or "" for sym in parsed.symbols or []
        )
        if not content_str:
            continue

        controller_symbols = [
            s for s in parsed.symbols or []
            if s.kind in ("class", "function", "method")
        ]
        if not controller_symbols:
            continue

        for cls in controller_symbols:
            cls_node = graph.symbol_node(file_path, cls.name)
            for m in guard_re.finditer(content_str):
                for guard_name in m.group(1).split(","):
                    guard_name = guard_name.strip()
                    if guard_name:
                        graph.add_relation(
                            GraphRelation(
                                src=cls_node,
                                dst=graph.external_node(f"nestjs:guard:{guard_name}"),
                                kind=REL_KIND_NESTJS_GUARD,
                            )
                        )
            for m in interceptor_re.finditer(content_str):
                for name in m.group(1).split(","):
                    name = name.strip()
                    if name:
                        graph.add_relation(
                            GraphRelation(
                                src=cls_node,
                                dst=graph.external_node(f"nestjs:interceptor:{name}"),
                                kind=REL_KIND_NESTJS_INTERCEPTOR,
                            )
                        )


# ── Python extraction ──────────────────────────────────────────────────────────

def _extract_py_calls(
    graph: CallGraph,
    file_path: str,
    caller: str,
    body: str,
    ctx: _ResolverContext,
    celery_tasks: set[str],
    caller_class: str | None = None,
) -> None:
    caller_node = graph.symbol_node(file_path, caller)
    # Celery dispatch first (more specific) — raw body (regex needs call text)
    for m in _PY_CELERY_DISPATCH_RE.finditer(body):
        task_name = m.group(1)
        if task_name.lower() in _PY_BUILTINS:
            continue
        resolved = _resolve_bare_call(task_name, file_path, ctx)
        if resolved is not None and resolved[1].name in celery_tasks:
            candidates = [resolved]
        else:
            candidates = [
                cand for cand in ctx.sym_index.get(task_name, [])
                if cand[1].name in celery_tasks
            ]
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

    # General calls — stripped body (strings/comments can't produce call sites)
    stripped = _strip_strings_and_comments(body, "python")
    seen: set[str] = set()
    for m in _PY_CALL_RE.finditer(stripped):
        receiver, method, bare = m.group(1), m.group(2), m.group(3)
        name = method or bare
        if not name or name.lower() in _PY_BUILTINS:
            continue
        seen_key = f"{receiver}.{name}" if receiver else name
        if seen_key in seen:
            continue
        seen.add(seen_key)
        if receiver:
            resolved = _resolve_member_call(receiver, name, file_path, ctx, caller_class)
        else:
            resolved = _resolve_bare_call(name, file_path, ctx)
        _emit_call(graph, file_path, caller, name, resolved)


# ── JS/TS extraction ───────────────────────────────────────────────────────────

def _extract_js_calls(
    graph: CallGraph,
    file_path: str,
    caller: str,
    body: str,
    ctx: _ResolverContext,
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

    # General calls — stripped body (strings/comments can't produce call sites)
    stripped = _strip_strings_and_comments(body, "javascript")
    seen: set[str] = set()
    for m in _JS_CALL_RE.finditer(stripped):
        receiver, method, bare = m.group(1), m.group(2), m.group(3)
        name = method or bare
        if not name or name.lower() in _JS_BUILTINS:
            continue
        seen_key = f"{receiver}.{name}" if receiver else name
        if seen_key in seen:
            continue
        seen.add(seen_key)
        if receiver:
            resolved = _resolve_member_call(receiver, name, file_path, ctx)
        else:
            resolved = _resolve_bare_call(name, file_path, ctx)
        _emit_call(graph, file_path, caller, name, resolved)


# ── Go extraction ────────────────────────────────────────────────────────────

# pkg.Func(  or  recv.Method(  or  Func(
_GO_CALL_RE = re.compile(r"(?:(\w+)\.(\w+)\s*\(|(?<![\w.])(\w+)\s*\()")


def _extract_go_calls(
    graph: CallGraph,
    file_path: str,
    caller: str,
    body: str,
    ctx: _ResolverContext,
) -> None:
    stripped = _strip_strings_and_comments(body, "go")
    seen: set[str] = set()
    for m in _GO_CALL_RE.finditer(stripped):
        receiver, method, bare = m.group(1), m.group(2), m.group(3)
        name = method or bare
        if not name or name.lower() in _GO_BUILTINS:
            continue
        seen_key = f"{receiver}.{name}" if receiver else name
        if seen_key in seen:
            continue
        seen.add(seen_key)
        if receiver:
            # pkg.Func() resolves via a module import; recv.Method() has no
            # receiver type available → unresolved (external), never guessed.
            resolved = _resolve_member_call(receiver, name, file_path, ctx)
        else:
            resolved = _resolve_bare_call(name, file_path, ctx)
        _emit_call(graph, file_path, caller, name, resolved)


# ── PHP extraction ───────────────────────────────────────────────────────────

_PHP_CALL_RE = re.compile(
    r"new\s+(\w+)\s*\("          # g1: new Class(
    r"|(\w+)::(\w+)\s*\("        # g2::g3: Class::method(
    r"|\$\w+->(\w+)\s*\("        # g4: $var->method(
    r"|(?<![\w$>:])(\w+)\s*\("   # g5: bare func(
)


def _extract_php_calls(
    graph: CallGraph,
    file_path: str,
    caller: str,
    body: str,
    ctx: _ResolverContext,
) -> None:
    stripped = _strip_strings_and_comments(body, "php")
    seen: set[str] = set()
    for m in _PHP_CALL_RE.finditer(stripped):
        new_cls, stat_cls, stat_m, inst_m, bare = m.groups()
        if new_cls:
            name, resolved = new_cls, _resolve_bare_call(new_cls, file_path, ctx)
        elif stat_cls:
            name, resolved = stat_m, _resolve_member_call(stat_cls, stat_m, file_path, ctx)
        elif inst_m:
            name, resolved = inst_m, None  # $var->method(): no receiver type → unresolved
        else:
            name, resolved = bare, _resolve_bare_call(bare, file_path, ctx)
        if not name or name.lower() in _PHP_BUILTINS:
            continue
        seen_key = name if resolved is None else f"{resolved[0]}::{name}"
        if seen_key in seen:
            continue
        seen.add(seen_key)
        _emit_call(graph, file_path, caller, name, resolved)


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

_GO_BUILTINS = frozenset({
    "make", "len", "cap", "new", "append", "copy", "delete", "close",
    "panic", "recover", "print", "println", "min", "max", "complex",
    "real", "imag", "clear", "if", "for", "return", "go", "defer",
    "range", "func", "var", "const", "type", "map", "struct", "switch",
    "error", "string", "int", "bool", "byte", "rune",
})

_PHP_BUILTINS = frozenset({
    "array", "count", "isset", "unset", "empty", "echo", "print", "die",
    "exit", "implode", "explode", "strlen", "str_replace", "sprintf",
    "printf", "in_array", "array_map", "array_filter", "array_merge",
    "array_keys", "array_values", "json_encode", "json_decode", "is_array",
    "is_string", "is_null", "is_numeric", "gettype", "intval", "strval",
    "trim", "substr", "strpos", "preg_match", "preg_replace", "date", "time",
    "if", "for", "foreach", "while", "return", "function", "class", "new",
})
