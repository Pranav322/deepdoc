import ast
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
import re
from pathlib import Path
from typing import Any

from .common import (
    DispatchEvidence,
    RealtimeConsumer,
    RuntimeScan,
    RuntimeScheduler,
    RuntimeTask,
)
from .utils import endpoint_owned_files
from ..parser.base import ParsedFile
from ..parser.js_ts_parser import JsBoundCall, js_bound_calls
from ..parser.php_parser import php_class_declarations, php_dispatches
from ..parser.registry import language_for_extension
from ..parser.vue_parser import _extract_script_blocks
from ..source_metadata import classify_source_kind, is_low_trust_source_kind

# Runtime detectors are framework-specific, so each one only sees files whose
# real language can host that framework. Without this, Python runtime code
# quoted inside a TypeScript prompt/example string became a Celery/Django
# surface, and ordinary TS idioms (`.delay(`, `.connect(`) became tasks.
PYTHON_LANGUAGES = frozenset({"python"})
JS_LANGUAGES = frozenset({"javascript", "typescript", "vue"})
PHP_LANGUAGES = frozenset({"php"})
GO_LANGUAGES = frozenset({"go"})


def discover_runtime_surfaces(
    parsed_files: dict[str, ParsedFile],
    file_contents: dict[str, str],
    api_endpoints: list[dict[str, Any]] | None = None,
    source_kind_by_file: dict[str, str] | None = None,
) -> RuntimeScan:
    """Detect first-class background job, scheduler, and realtime surfaces.

    Only product-trust source participates: low-trust kinds (test/fixture/
    example/generated) describe how a runtime *could* look, not what this
    product actually runs. `source_kind_by_file` is the scan-wide classification
    (`RepoScan.source_kind_by_file`); when absent each path is classified with
    the same shared `classify_source_kind()` so there is no second path
    classifier.
    """
    runtime = RuntimeScan()
    eligible = _eligible_contents(file_contents, source_kind_by_file)
    runtime.scan_stats = {
        "input_files": len(file_contents),
        "eligible_files": len(eligible),
        "low_trust_files_skipped": len(file_contents) - len(eligible),
    }
    languages = _language_index(eligible, parsed_files)
    python_files = _by_language(eligible, languages, PYTHON_LANGUAGES)
    js_files = _by_language(eligible, languages, JS_LANGUAGES)
    php_files = _by_language(eligible, languages, PHP_LANGUAGES)
    go_files = _by_language(eligible, languages, GO_LANGUAGES)

    # Python runtime facts all share one strict AST parse per source file. A
    # parse error therefore produces no Celery/Django/scheduler fact instead of
    # leaving a regex to reinterpret broken or quoted source as executable.
    python_trees = _python_ast_trees(python_files)
    celery_tasks, celery_schedulers, celery_task_exports = _discover_celery_tasks(
        python_files, python_trees
    )
    celery_task_definitions = _python_task_definitions_by_path(celery_tasks)
    runtime.tasks.extend(celery_tasks)
    runtime.schedulers.extend(celery_schedulers)
    runtime.tasks.extend(_discover_django_runtime(python_files, python_trees))
    laravel_tasks, laravel_schedulers = _discover_laravel_runtime(php_files)
    runtime.tasks.extend(laravel_tasks)
    runtime.schedulers.extend(laravel_schedulers)
    js_tasks, js_schedulers, js_consumers = _discover_js_runtime(js_files)
    runtime.tasks.extend(js_tasks)
    runtime.schedulers.extend(js_schedulers)
    runtime.realtime_consumers.extend(js_consumers)
    go_tasks, go_schedulers = _discover_go_runtime(go_files)
    runtime.tasks.extend(go_tasks)
    runtime.schedulers.extend(go_schedulers)
    runtime.schedulers.extend(_discover_schedulers(python_files, python_trees))
    runtime.realtime_consumers.extend(
        _discover_python_realtime_consumers(python_files)
    )
    runtime.dispatch_evidence = _collect_dispatch_evidence(
        eligible,
        languages,
        celery_task_definitions,
        _php_runtime_target_identities(runtime.tasks),
        python_exported_task_names_by_path=celery_task_exports,
    )
    runtime.dispatch_evidence.extend(_scheduler_owner_evidence(runtime.schedulers))
    _link_runtime_evidence(runtime, runtime.dispatch_evidence, api_endpoints or [])
    runtime.scan_stats["link_candidate_files"] = len(
        {
            item.file_path
            for item in runtime.dispatch_evidence
            if item.relation != "scheduler_owner"
        }
    )
    runtime.tasks = _dedupe_runtime_tasks(runtime.tasks)
    runtime.schedulers = _dedupe_schedulers(runtime.schedulers)
    runtime.realtime_consumers = _dedupe_consumers(runtime.realtime_consumers)
    return runtime


def _eligible_contents(
    file_contents: dict[str, str],
    source_kind_by_file: dict[str, str] | None,
) -> dict[str, str]:
    """Drop empty and low-trust files, preserving the caller's key order."""
    kinds = source_kind_by_file or {}
    return {
        path: content
        for path, content in file_contents.items()
        if content
        and not is_low_trust_source_kind(kinds.get(path) or classify_source_kind(path))
    }


def _language_index(
    paths: dict[str, str], parsed_files: dict[str, ParsedFile]
) -> dict[str, str]:
    """Real language per file: parser verdict first, extension as fallback."""
    index: dict[str, str] = {}
    for path in paths:
        parsed = parsed_files.get(path)
        language = (getattr(parsed, "language", "") or "").lower()
        index[path] = language or language_for_extension(Path(path).suffix)
    return index


def _by_language(
    eligible: dict[str, str], languages: dict[str, str], wanted: frozenset[str]
) -> dict[str, str]:
    return {
        path: content
        for path, content in eligible.items()
        if languages.get(path) in wanted
    }


def _python_ast_trees(file_contents: dict[str, str]) -> dict[str, ast.Module]:
    """One strict Python AST per source file; syntax errors yield no facts."""
    trees: dict[str, ast.Module] = {}
    for file_path, content in file_contents.items():
        try:
            trees[file_path] = ast.parse(content)
        except SyntaxError:
            continue
    return trees


def _python_task_definitions_by_path(
    tasks: list[RuntimeTask],
) -> dict[str, set[str]]:
    """All AST-proven Celery declarations, regardless of later re-exports."""
    definitions: dict[str, set[str]] = {}
    for task in tasks:
        if (
            task.runtime_kind == "celery"
            and task.decorator
            and task.file_path.endswith(".py")
        ):
            definitions.setdefault(task.file_path, set()).add(task.name)
    return definitions


def _php_runtime_target_identities(tasks: list[RuntimeTask]) -> frozenset[str]:
    """Case-insensitive canonical PHP runtime targets, never display aliases."""
    return frozenset(
        identity.lower()
        for task in tasks
        if task.runtime_kind.startswith("laravel_")
        for identity in task.target_identities
        if identity
    )


def _collect_dispatch_evidence(
    file_contents: dict[str, str],
    languages: dict[str, str],
    python_task_names_by_path: dict[str, set[str]] | None = None,
    php_runtime_targets: frozenset[str] | None = None,
    *,
    python_exported_task_names_by_path: dict[str, set[str]] | None = None,
) -> list[DispatchEvidence]:
    """Collect language-structural evidence only from eligible source files."""
    evidence: list[DispatchEvidence] = []
    task_names = python_task_names_by_path or {}
    exported_task_names = python_exported_task_names_by_path or task_names
    for file_path, content in file_contents.items():
        language = languages.get(file_path)
        if language == "python":
            evidence.extend(
                _python_dispatch_evidence(
                    file_path, content, task_names, exported_task_names
                )
            )
        elif language == "php":
            for dispatch in php_dispatches(content):
                if (
                    php_runtime_targets is not None
                    and dispatch.target.lower() not in php_runtime_targets
                ):
                    continue
                evidence.append(
                    DispatchEvidence(
                        file_path=file_path,
                        language="php",
                        relation="direct",
                        target_aliases=_target_aliases(dispatch.target),
                    )
                )
        elif language in JS_LANGUAGES:
            evidence.extend(_js_dispatch_evidence(file_path, content))
    return evidence


def _ensure_scheduler_owner_keys(schedulers: list[RuntimeScheduler]) -> None:
    """Assign deterministic declaration identities before source-owner linking."""
    ordinals: dict[tuple[str, str, str, str, tuple[str, ...]], int] = {}
    for scheduler in schedulers:
        if scheduler.owner_key:
            continue
        base = (
            scheduler.file_path,
            scheduler.scheduler_type,
            scheduler.name,
            scheduler.cron,
            tuple(scheduler.invoked_targets),
        )
        ordinal = ordinals.get(base, 0) + 1
        ordinals[base] = ordinal
        scheduler.owner_key = "owner:" + "|".join(
            (
                scheduler.scheduler_type,
                scheduler.name,
                scheduler.cron,
                ",".join(scheduler.invoked_targets),
                str(ordinal),
            )
        )


def _scheduler_owner_evidence(
    schedulers: list[RuntimeScheduler],
) -> list[DispatchEvidence]:
    """Declarations themselves are bounded evidence of scheduler ownership."""
    _ensure_scheduler_owner_keys(schedulers)
    return [
        DispatchEvidence(
            file_path=scheduler.file_path,
            language="runtime",
            relation="scheduler_owner",
            target_aliases=(scheduler.owner_key,),
        )
        for scheduler in schedulers
        if scheduler.owner_key and scheduler.file_path
    ]


_PYTHON_DJANGO_SIGNAL_NAMES = frozenset(
    {
        "pre_init",
        "post_init",
        "pre_save",
        "post_save",
        "pre_delete",
        "post_delete",
        "m2m_changed",
        "class_prepared",
        "request_started",
        "request_finished",
        "got_request_exception",
    }
)


def _python_dispatch_evidence(
    file_path: str,
    content: str,
    task_definitions_by_path: dict[str, set[str]],
    task_exports_by_path: dict[str, set[str]],
) -> list[DispatchEvidence]:
    """Evidence from syntax-proven Celery task/Django signal bindings only."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []
    bindings = _python_runtime_bindings(
        file_path, tree, task_definitions_by_path, task_exports_by_path
    )
    local_shadows_by_call = _python_local_shadows_by_call(tree)
    calls = sorted(
        (node for node in ast.walk(tree) if isinstance(node, ast.Call)),
        key=lambda node: (node.lineno, node.col_offset),
    )
    evidence: list[DispatchEvidence] = []
    for call in calls:
        func = call.func
        if not isinstance(func, ast.Attribute):
            continue
        if _python_call_root_is_shadowed(
            call, func.value, local_shadows_by_call
        ):
            continue
        if func.attr in {"delay", "apply_async"}:
            target = _python_bound_task_target(
                func.value,
                _python_node_position(call),
                bindings,
                task_exports_by_path,
            )
            relation = "direct"
        elif func.attr == "send":
            target = _python_bound_signal_target(
                func.value,
                _python_node_position(call),
                bindings,
            )
            relation = "signal"
        else:
            continue
        if not target:
            continue
        aliases = (
            _python_target_aliases(target)
            if relation == "direct"
            else _target_aliases(target)
        )
        evidence.append(
            DispatchEvidence(
                file_path=file_path,
                language="python",
                relation=relation,
                target_aliases=aliases,
            )
        )
    return evidence


@dataclass(frozen=True)
class _PythonBindingEvent:
    """One source-ordered module binding, or an explicit invalidation."""

    role: str = ""
    target: str = ""


@dataclass(frozen=True)
class _PythonBindingHistory:
    """Binary-searchable source positions for one Python module name."""

    positions: tuple[tuple[int, int], ...]
    events: tuple[_PythonBindingEvent, ...]

    def at(self, position: tuple[int, int]) -> _PythonBindingEvent | None:
        index = bisect_right(self.positions, position) - 1
        return self.events[index] if index >= 0 else None


@dataclass(frozen=True)
class _PythonRuntimeBindings:
    """All top-level bindings relevant to dispatch evidence in one file."""

    histories: dict[str, _PythonBindingHistory]


_PYTHON_TASK_ROLE = "task"
_PYTHON_TASK_MODULE_ROLE = "task_module"
_PYTHON_SIGNAL_ROLE = "signal"
_PYTHON_SIGNAL_MODULE_ROLE = "signal_module"


def _python_runtime_bindings(
    file_path: str,
    tree: ast.Module,
    task_definitions_by_path: dict[str, set[str]],
    task_exports_by_path: dict[str, set[str]],
) -> _PythonRuntimeBindings:
    """Exact-position module binding histories for task and signal receivers."""
    raw_histories: dict[str, list[tuple[tuple[int, int], _PythonBindingEvent]]] = {}

    def record(
        name: str,
        position: tuple[int, int],
        role: str = "",
        target: str = "",
    ) -> None:
        if name:
            raw_histories.setdefault(name, []).append(
                (position, _PythonBindingEvent(role, target))
            )

    local_task_names = task_definitions_by_path.get(file_path, set())
    for node in tree.body:
        position = _python_node_position(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            record(
                node.name,
                position,
                _PYTHON_TASK_ROLE if node.name in local_task_names else "",
                node.name if node.name in local_task_names else "",
            )
            continue
        if isinstance(node, ast.ClassDef):
            record(node.name, position)
            continue
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            task_path = _python_import_module_file(file_path, module, node.level)
            imported_tasks = task_exports_by_path.get(task_path, set())
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                if alias.name in imported_tasks:
                    record(local, position, _PYTHON_TASK_ROLE, alias.name)
                elif (
                    module == "django.db.models.signals"
                    and alias.name in _PYTHON_DJANGO_SIGNAL_NAMES
                ):
                    record(local, position, _PYTHON_SIGNAL_ROLE, alias.name)
                elif module == "django.db.models" and alias.name == "signals":
                    record(local, position, _PYTHON_SIGNAL_MODULE_ROLE)
                else:
                    module_path = _python_import_module_file(
                        file_path,
                        f"{module}.{alias.name}" if module else alias.name,
                        node.level,
                    )
                    if module_path in task_exports_by_path:
                        record(local, position, _PYTHON_TASK_MODULE_ROLE, module_path)
                    else:
                        record(local, position)
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                if alias.name == "django.db.models.signals":
                    record(local, position, _PYTHON_SIGNAL_MODULE_ROLE)
                    continue
                task_path = _python_import_module_file(file_path, alias.name, 0)
                if task_path in task_exports_by_path:
                    record(local, position, _PYTHON_TASK_MODULE_ROLE, task_path)
                else:
                    record(local, position)
            continue
        for name, write_position in _python_module_write_events(node):
            record(name, write_position)

    histories: dict[str, _PythonBindingHistory] = {}
    for name, events in raw_histories.items():
        ordered = sorted(events, key=lambda item: item[0])
        histories[name] = _PythonBindingHistory(
            tuple(position for position, _ in ordered),
            tuple(event for _, event in ordered),
        )
    return _PythonRuntimeBindings(histories)


def _python_module_write_events(node: ast.AST) -> list[tuple[str, tuple[int, int]]]:
    """Potential module writes, excluding nested execution scopes and bare annotations."""
    writes: list[tuple[str, tuple[int, int]]] = []

    def visit(current: ast.AST) -> None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            writes.append((current.name, _python_node_position(current)))
            return
        if isinstance(current, ast.Lambda):
            return
        if isinstance(current, ast.Import):
            for alias in current.names:
                writes.append(
                    (alias.asname or alias.name.split(".", 1)[0], _python_node_position(current))
                )
            return
        if isinstance(current, ast.ImportFrom):
            for alias in current.names:
                if alias.name != "*":
                    writes.append((alias.asname or alias.name, _python_node_position(current)))
            return
        if isinstance(current, ast.AnnAssign) and current.value is None:
            return
        if isinstance(current, ast.Name) and isinstance(current.ctx, (ast.Store, ast.Del)):
            writes.append((current.id, _python_node_position(current)))
        for child in ast.iter_child_nodes(current):
            visit(child)

    visit(node)
    return writes


def _python_binding_at(
    bindings: _PythonRuntimeBindings, name: str, position: tuple[int, int]
) -> _PythonBindingEvent | None:
    history = bindings.histories.get(name)
    return history.at(position) if history is not None else None


def _python_local_shadows_by_call(tree: ast.Module) -> dict[int, frozenset[str]]:
    """Lexical names shadowing an outer runtime binding at each call site."""
    shadows_by_call: dict[int, frozenset[str]] = {}

    def visit(node: ast.AST, scopes: tuple[frozenset[str], ...]) -> None:
        if isinstance(node, ast.Call):
            shadows_by_call[id(node)] = frozenset().union(*scopes)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                visit(decorator, scopes)
            for default in (*node.args.defaults, *node.args.kw_defaults):
                if default is not None:
                    visit(default, scopes)
            local_scope = _python_scope_bound_names(node)
            for statement in node.body:
                visit(statement, (*scopes, local_scope))
            return
        if isinstance(node, ast.Lambda):
            for default in (*node.args.defaults, *node.args.kw_defaults):
                if default is not None:
                    visit(default, scopes)
            visit(node.body, (*scopes, _python_scope_bound_names(node)))
            return
        if isinstance(node, ast.ClassDef):
            for decorator in node.decorator_list:
                visit(decorator, scopes)
            for base in node.bases:
                visit(base, scopes)
            for keyword in node.keywords:
                visit(keyword.value, scopes)
            class_scope = _python_scope_bound_names(node)
            for statement in node.body:
                # Class attributes are not lexical variables inside methods.
                method_scopes = scopes if isinstance(
                    statement, (ast.FunctionDef, ast.AsyncFunctionDef)
                ) else (*scopes, class_scope)
                visit(statement, method_scopes)
            return
        for child in ast.iter_child_nodes(node):
            visit(child, scopes)

    visit(tree, ())
    return shadows_by_call


def _python_scope_bound_names(
    scope: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef,
) -> frozenset[str]:
    """Bindings created in one lexical Python scope, excluding nested bodies."""
    names: set[str] = set()
    if not isinstance(scope, ast.ClassDef):
        for argument in (
            *scope.args.posonlyargs,
            *scope.args.args,
            *scope.args.kwonlyargs,
        ):
            names.add(argument.arg)
        if scope.args.vararg is not None:
            names.add(scope.args.vararg.arg)
        if scope.args.kwarg is not None:
            names.add(scope.args.kwarg.arg)

    def collect(node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            return
        if isinstance(node, ast.Lambda):
            return
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".", 1)[0])
            return
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name)
            return
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            # They can redirect a reference away from the discovered import;
            # suppressing the evidence is safer than guessing the outer value.
            names.update(node.names)
        for child in ast.iter_child_nodes(node):
            collect(child)

    body = scope.body if not isinstance(scope, ast.Lambda) else (scope.body,)
    for statement in body:
        collect(statement)
    return frozenset(names)


def _python_call_root_is_shadowed(
    call: ast.Call,
    receiver: ast.expr,
    shadows_by_call: dict[int, frozenset[str]],
) -> bool:
    """Whether a receiver's root name is bound locally at this call site."""
    dotted = _python_dotted_name(receiver)
    if not dotted:
        return True
    return dotted.split(".", 1)[0] in shadows_by_call.get(id(call), frozenset())


def _python_import_module_file(file_path: str, module: str, level: int) -> str:
    """Conservative .py path for a source-level import module."""
    parent_parts = list(Path(file_path).parent.parts)
    if level:
        climb = level - 1
        if climb > len(parent_parts):
            return ""
        parts = parent_parts[: len(parent_parts) - climb]
    else:
        parts = []
    if module:
        parts.extend(module.split("."))
    return Path(*parts).with_suffix(".py").as_posix() if parts else ""


def _python_bound_task_target(
    node: ast.expr,
    position: tuple[int, int],
    bindings: _PythonRuntimeBindings,
    task_exports_by_path: dict[str, set[str]],
) -> str:
    dotted = _python_dotted_name(node)
    if not dotted:
        return ""
    parts = dotted.split(".")
    binding = _python_binding_at(bindings, parts[0], position)
    if binding is None:
        return ""
    if len(parts) == 1:
        return binding.target if binding.role == _PYTHON_TASK_ROLE else ""
    if binding.role != _PYTHON_TASK_MODULE_ROLE:
        return ""
    candidate = parts[-1]
    return dotted if candidate in task_exports_by_path.get(binding.target, set()) else ""


def _python_bound_signal_target(
    node: ast.expr,
    position: tuple[int, int],
    bindings: _PythonRuntimeBindings,
) -> str:
    dotted = _python_dotted_name(node)
    if not dotted:
        return ""
    parts = dotted.split(".")
    binding = _python_binding_at(bindings, parts[0], position)
    if binding is None:
        return ""
    if len(parts) == 1:
        return binding.target if binding.role == _PYTHON_SIGNAL_ROLE else ""
    candidate = parts[-1]
    return (
        candidate
        if binding.role == _PYTHON_SIGNAL_MODULE_ROLE
        and candidate in _PYTHON_DJANGO_SIGNAL_NAMES
        else ""
    )


def _python_dotted_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _python_dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else ""
    return ""


def _python_target_aliases(target: str) -> tuple[str, ...]:
    """Preserve a dotted task reference plus its terminal callable name."""
    aliases = list(_target_aliases(target))
    terminal = target.rsplit(".", 1)[-1]
    if terminal and terminal not in aliases:
        aliases.append(terminal)
    return tuple(aliases)


def _invoked_target_aliases(target: str) -> tuple[str, ...]:
    """Canonical scheduler target aliases, including dotted Celery paths."""
    aliases = list(_target_aliases(target))
    terminal = target.rsplit(".", 1)[-1]
    if terminal and terminal not in aliases:
        aliases.append(terminal)
    return tuple(aliases)


def _link_runtime_evidence(
    runtime: RuntimeScan,
    evidence: list[DispatchEvidence],
    api_endpoints: list[dict[str, Any]],
) -> None:
    """Link syntax-proven direct dispatches through bounded target indexes.

    Collection is deliberately separate: evidence must exist before a file can
    affect a runtime surface. A direct target resolving to multiple task records
    is ambiguous—not a reason to enumerate every record in that bucket.
    """
    endpoint_keys_by_file, endpoint_source_cap_rejections = (
        _published_endpoint_keys_by_file(api_endpoints)
    )
    _ensure_scheduler_owner_keys(runtime.schedulers)
    # Direct, queue, and scheduler relations are one-to-one claims. Store only
    # a unique object or an ambiguity sentinel, never a candidate bucket that a
    # producer site could enumerate. Signals intentionally retain a list because
    # their dispatch grammar explicitly means a broadcast to matching handlers.
    tasks_by_alias: dict[str, Any] = {}
    php_tasks_by_identity: dict[str, Any] = {}
    queues_by_alias: dict[str, Any] = {}
    signals_by_alias: dict[str, list[RuntimeTask] | object] = {}
    schedulers_by_target: dict[str, Any] = {}
    schedulers_by_terminal_target: dict[str, Any] = {}
    schedulers_by_generated_owner: dict[tuple[str, str], Any] = {}
    schedulers_by_legacy_owner: dict[tuple[str, str], Any] = {}
    for task in runtime.tasks:
        if task.runtime_kind.startswith("laravel_"):
            for identity in task.target_identities:
                normalized = identity.strip().lstrip("\\").lower()
                if normalized:
                    _add_exact_candidate(php_tasks_by_identity, normalized, task)
        else:
            for alias in _target_aliases(task.name):
                _add_exact_candidate(tasks_by_alias, alias, task)
        for trigger in task.triggers:
            for alias in _target_aliases(trigger):
                _add_bounded_signal_candidate(signals_by_alias, alias, task)
        # Queue evidence may resolve only against an explicitly declared queue;
        # task display names are not a cross-runtime queue identity.
        if task.queue:
            _add_exact_candidate(queues_by_alias, task.queue, task)
    for scheduler in runtime.schedulers:
        _add_exact_candidate(
            schedulers_by_generated_owner,
            (scheduler.file_path, scheduler.owner_key),
            scheduler,
        )
        # Legacy hand-authored evidence resolves by display name only in its own
        # namespace. Generated owner keys can never collide with this index.
        for alias in _target_aliases(scheduler.name):
            _add_exact_candidate(
                schedulers_by_legacy_owner, (scheduler.file_path, alias), scheduler
            )
        for target in scheduler.invoked_targets:
            aliases = _invoked_target_aliases(target)
            if not aliases:
                continue
            _add_exact_candidate(schedulers_by_target, aliases[0], scheduler)
            if len(aliases) > 1:
                _add_exact_candidate(
                    schedulers_by_terminal_target, aliases[-1], scheduler
                )

    producer_sets = {
        id(task): set(task.producer_files) for task in runtime.tasks
    }
    producer_orders = {
        id(task): list(dict.fromkeys(task.producer_files)) for task in runtime.tasks
    }
    linked_endpoint_sets = {
        id(item): set(item.linked_endpoints)
        for item in [*runtime.tasks, *runtime.schedulers]
    }
    producer_cap_rejections = 0
    endpoint_cap_rejections = endpoint_source_cap_rejections

    def attach_producer(task: RuntimeTask, file_path: str) -> None:
        nonlocal producer_cap_rejections
        values = producer_sets.setdefault(id(task), set())
        if file_path in values:
            return
        if len(values) >= MAX_RUNTIME_PRODUCER_FILES:
            producer_cap_rejections += 1
            return
        values.add(file_path)
        producer_orders.setdefault(id(task), []).append(file_path)

    def attach_endpoints(
        item: RuntimeTask | RuntimeScheduler, endpoint_keys: tuple[str, ...]
    ) -> None:
        nonlocal endpoint_cap_rejections
        if not endpoint_keys:
            return
        values = linked_endpoint_sets.setdefault(id(item), set())
        for key in endpoint_keys:
            if key in values:
                continue
            if len(values) >= MAX_RUNTIME_LINKED_ENDPOINTS:
                endpoint_cap_rejections += 1
                continue
            values.add(key)

    task_checks = 0
    scheduler_checks = 0
    signal_broadcast_edges = 0
    signal_fanout_rejections = 0
    ambiguous_task_targets = 0
    index_probes = 0
    for item in evidence:
        if item.relation == "scheduler_owner":
            endpoint_keys = endpoint_keys_by_file.get(item.file_path, ())
            if endpoint_keys:
                index_probes += 1
                owner_index = (
                    schedulers_by_generated_owner
                    if item.language == "runtime"
                    else schedulers_by_legacy_owner
                )
                scheduler = _resolve_owner_candidate(
                    owner_index, item.file_path, item.target_aliases
                )
                if scheduler is not None and scheduler is not _AMBIGUOUS:
                    scheduler_checks += 1
                    attach_endpoints(scheduler, endpoint_keys)
            continue
        if item.relation == "signal":
            index_probes += 1
            signal_candidates = _indexed_candidates(
                signals_by_alias, item.target_aliases
            )
            if signal_candidates is None:
                signal_fanout_rejections += 1
                continue
            endpoint_keys = endpoint_keys_by_file.get(item.file_path, ())
            for task in signal_candidates:
                task_checks += 1
                signal_broadcast_edges += 1
                attach_producer(task, item.file_path)
                if endpoint_keys:
                    attach_endpoints(task, endpoint_keys)
            continue
        if item.relation == "direct":
            task = (
                _resolve_php_task_candidate(php_tasks_by_identity, item.target_aliases)
                if item.language == "php"
                else _resolve_exact_candidate(tasks_by_alias, item.target_aliases)
            )
        elif item.relation == "queue":
            task = _resolve_queue_candidate(queues_by_alias, item.target_aliases)
        else:
            continue
        index_probes += 1
        if task is _AMBIGUOUS:
            ambiguous_task_targets += 1
        elif task is not None:
            task_checks += 1
            attach_producer(task, item.file_path)
            endpoint_keys = endpoint_keys_by_file.get(item.file_path, ())
            if endpoint_keys:
                attach_endpoints(task, endpoint_keys)

        # Schedulers are invoked by direct task targets, never by a queue name.
        if item.relation != "direct":
            continue
        endpoint_keys = endpoint_keys_by_file.get(item.file_path, ())
        if not endpoint_keys:
            continue
        index_probes += 1
        scheduler = _resolve_scheduler_candidate(
            schedulers_by_target, schedulers_by_terminal_target, item.target_aliases
        )
        if scheduler is not None and scheduler is not _AMBIGUOUS:
            scheduler_checks += 1
            attach_endpoints(scheduler, endpoint_keys)

    for task in runtime.tasks:
        task.producer_files = producer_orders.get(id(task), [])
        task.linked_endpoints = sorted(linked_endpoint_sets.get(id(task), set()))
    for scheduler in runtime.schedulers:
        scheduler.linked_endpoints = sorted(linked_endpoint_sets.get(id(scheduler), set()))

    runtime.scan_stats.update(
        {
            "link_evidence_count": len(evidence),
            "link_task_checks": task_checks,
            "link_scheduler_checks": scheduler_checks,
            "link_signal_broadcast_edges": signal_broadcast_edges,
            "link_signal_fanout_rejections": signal_fanout_rejections,
            "link_producer_cap_rejections": producer_cap_rejections,
            "link_endpoint_cap_rejections": endpoint_cap_rejections,
            "link_ambiguous_task_targets": ambiguous_task_targets,
            "link_index_probes": index_probes,
        }
    )


def _published_endpoint_keys_by_file(
    api_endpoints: list[dict[str, Any]],
) -> tuple[dict[str, tuple[str, ...]], int]:
    """Bounded, deterministic published endpoint keys for each owning file.

    The scan must inspect every endpoint record once, but never retain or sort an
    unbounded file-local set merely because a runtime link references that file
    repeatedly. The retained tuple matches the old lexical-first behavior.
    """
    selected_by_file: dict[str, list[str]] = {}
    source_cap_rejections = 0
    for ep in api_endpoints:
        if not ep.get("publication_ready", True):
            continue
        key = f"{str(ep.get('method', 'GET')).upper()} {ep.get('path', '')}"
        for owned in endpoint_owned_files(ep):
            selected = selected_by_file.setdefault(owned, [])
            index = bisect_left(selected, key)
            if index < len(selected) and selected[index] == key:
                continue
            if len(selected) < MAX_RUNTIME_LINKED_ENDPOINTS:
                selected.insert(index, key)
                continue
            source_cap_rejections += 1
            if index < len(selected):
                selected.insert(index, key)
                selected.pop()
    return {
        file_path: tuple(keys) for file_path, keys in selected_by_file.items()
    }, source_cap_rejections


def _target_aliases(target: str) -> tuple[str, ...]:
    """Stable canonical aliases for namespaced runtime targets."""
    normalized = target.strip().lstrip("\\")
    if not normalized:
        return ()
    short = normalized.rsplit("\\", 1)[-1]
    return (normalized,) if short == normalized else (normalized, short)


_AMBIGUOUS = object()
_SIGNAL_FANOUT_OVERFLOW = object()

# Runtime relationship lists feed planner ownership, so they must remain bounded
# even for generated projects with many handlers or endpoint declarations.
MAX_SIGNAL_BROADCAST_FANOUT = 32
MAX_RUNTIME_PRODUCER_FILES = 64
MAX_RUNTIME_LINKED_ENDPOINTS = 64


def _add_exact_candidate(index: dict[Any, Any], key: Any, candidate: Any) -> None:
    """Record one exact candidate, degrading duplicate identities to ambiguity."""
    current = index.get(key)
    if current is None:
        index[key] = candidate
    elif current is not candidate:
        index[key] = _AMBIGUOUS


def _resolve_exact_candidate(index: dict[Any, Any], aliases: tuple[Any, ...]) -> Any:
    """Resolve primary spelling first, then a bounded unique fallback set.

    A qualified evidence spelling is authoritative when it has a direct index
    hit. Otherwise its explicit aliases may recover short-form task discovery,
    but duplicate buckets remain one sentinel lookup rather than a fan-out.
    """
    if not aliases:
        return None
    primary = index.get(aliases[0])
    if primary is _AMBIGUOUS:
        return _AMBIGUOUS
    if primary is not None:
        return primary
    fallback = None
    for alias in aliases[1:]:
        candidate = index.get(alias)
        if candidate is _AMBIGUOUS:
            return _AMBIGUOUS
        if candidate is None:
            continue
        if fallback is None:
            fallback = candidate
        elif fallback is not candidate:
            return _AMBIGUOUS
    return fallback


def _resolve_php_task_candidate(
    index: dict[str, Any], aliases: tuple[str, ...]
) -> Any:
    """Resolve PHP direct evidence only by its parser-proven canonical FQCN."""
    if not aliases:
        return None
    return index.get(aliases[0].strip().lstrip("\\").lower())


def _resolve_queue_candidate(index: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    """Resolve queue evidence by its exact primary literal only."""
    return index.get(aliases[0]) if aliases else None


def _resolve_scheduler_candidate(
    exact_index: dict[str, Any],
    terminal_index: dict[str, Any],
    aliases: tuple[str, ...],
) -> Any:
    """Resolve scheduler targets without matching qualified suffix collisions."""
    if not aliases:
        return None
    primary = aliases[0]
    candidate = exact_index.get(primary)
    if candidate is _AMBIGUOUS or candidate is not None:
        return candidate
    # A qualified producer must match the same qualified scheduled target. Only
    # an unqualified producer spelling may use a unique terminal fallback.
    if "." in primary or "\\" in primary:
        return None
    return terminal_index.get(primary)


def _add_bounded_signal_candidate(
    index: dict[str, list[RuntimeTask] | object],
    alias: str,
    task: RuntimeTask,
) -> None:
    """Retain at most the explicit broadcast fanout cap per signal alias."""
    bucket = index.get(alias)
    if bucket is _SIGNAL_FANOUT_OVERFLOW:
        return
    if bucket is None:
        index[alias] = [task]
        return
    assert isinstance(bucket, list)
    if any(item is task for item in bucket):
        return
    if len(bucket) >= MAX_SIGNAL_BROADCAST_FANOUT:
        index[alias] = _SIGNAL_FANOUT_OVERFLOW
        return
    bucket.append(task)


def _indexed_candidates(
    index: dict[str, list[Any] | object], aliases: tuple[str, ...]
) -> list[Any] | None:
    """Bounded, identity-deduplicated candidates or overflow for a broadcast."""
    candidates: list[Any] = []
    seen: set[int] = set()
    for alias in aliases:
        bucket = index.get(alias, ())
        if bucket is _SIGNAL_FANOUT_OVERFLOW:
            return None
        assert isinstance(bucket, (tuple, list))
        for item in bucket:
            if id(item) not in seen:
                seen.add(id(item))
                candidates.append(item)
                if len(candidates) > MAX_SIGNAL_BROADCAST_FANOUT:
                    return None
    return candidates


def _resolve_owner_candidate(
    index: dict[tuple[str, str], Any],
    file_path: str,
    aliases: tuple[str, ...],
) -> Any:
    """Resolve one scheduler declaration owned by the evidence source file."""
    return _resolve_exact_candidate(
        index, tuple((file_path, alias) for alias in aliases)
    )


_CELERY_DECORATOR_MEMBERS = frozenset({"shared_task", "task"})
_CELERY_RETRY_KEYWORDS = (
    "autoretry_for",
    "max_retries",
    "retry_backoff",
    "default_retry_delay",
)


def _discover_celery_tasks(
    file_contents: dict[str, str],
    trees: dict[str, ast.Module] | None = None,
) -> tuple[list[RuntimeTask], list[RuntimeScheduler], dict[str, set[str]]]:
    """Discover Celery declarations from valid AST nodes and proven bindings."""
    tasks: list[RuntimeTask] = []
    schedulers: list[RuntimeScheduler] = []
    task_exports: dict[str, set[str]] = {}
    for file_path, tree in (trees or _python_ast_trees(file_contents)).items():
        content = file_contents[file_path]
        file_tasks, file_schedulers, file_task_exports = _discover_celery_file_runtime(
            file_path, content, tree
        )
        tasks.extend(file_tasks)
        schedulers.extend(file_schedulers)
        task_exports[file_path] = file_task_exports
    return _dedupe_runtime_tasks(tasks), _dedupe_schedulers(schedulers), task_exports


def _discover_celery_file_runtime(
    file_path: str, content: str, tree: ast.Module
) -> tuple[list[RuntimeTask], list[RuntimeScheduler], set[str]]:
    """Celery facts for one valid module in exact top-level source order."""
    tasks: list[RuntimeTask] = []
    schedulers: list[RuntimeScheduler] = []
    decorator_names: set[str] = set()
    celery_module_names: set[str] = set()
    constructor_names: set[str] = set()
    app_names: set[str] = set()
    task_exports: set[str] = set()

    def revoke(names: set[str]) -> None:
        decorator_names.difference_update(names)
        celery_module_names.difference_update(names)
        constructor_names.difference_update(names)
        app_names.difference_update(names)
        task_exports.difference_update(names)

    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                revoke({local})
                if module == "celery" and alias.name in _CELERY_DECORATOR_MEMBERS:
                    decorator_names.add(local)
                elif module == "celery" and alias.name == "Celery":
                    constructor_names.add(local)
                elif module == "celery" and alias.name == "current_app":
                    app_names.add(local)
                elif module.startswith("celery.") and alias.name in _CELERY_DECORATOR_MEMBERS:
                    decorator_names.add(local)
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                revoke({local})
                if alias.name == "celery" or alias.name.startswith("celery."):
                    celery_module_names.add(local)
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            names = _python_assignment_names(node)
            if names and _python_is_celery_app_factory(
                _python_assignment_value(node), constructor_names, celery_module_names
            ):
                revoke(names)
                app_names.update(names)
            else:
                revoke(names)
            if _python_is_beat_schedule_assignment(node):
                for target, schedule in _python_beat_entries(
                    _python_assignment_value(node), content
                ):
                    runtime_name = target.rsplit(".", 1)[-1]
                    tasks.append(
                        RuntimeTask(
                            name=runtime_name,
                            file_path=file_path,
                            runtime_kind="celery",
                            schedule_sources=[schedule],
                        )
                    )
                    schedulers.append(
                        RuntimeScheduler(
                            name=runtime_name,
                            file_path=file_path,
                            scheduler_type="beat",
                            cron=schedule,
                            invoked_targets=[target],
                        )
                    )
            continue
        if isinstance(node, ast.AugAssign):
            revoke(_python_assignment_names(node))
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decorator = _python_celery_decorator(
                node, decorator_names, celery_module_names, app_names
            )
            revoke({node.name})
            if decorator is not None:
                queue, retry_policy = _python_celery_decorator_metadata(decorator)
                tasks.append(
                    RuntimeTask(
                        name=node.name,
                        file_path=file_path,
                        runtime_kind="celery",
                        decorator=_python_dotted_name(
                            decorator.func
                            if isinstance(decorator, ast.Call)
                            else decorator
                        ),
                        queue=queue,
                        retry_policy=retry_policy,
                    )
                )
                task_exports.add(node.name)
            continue
        if isinstance(node, ast.ClassDef):
            revoke({node.name})
            continue
        # Any remaining top-level construct that may bind/delete a task name is
        # dynamic from this scanner's perspective, so its export fails closed.
        revoke({name for name, _ in _python_module_write_events(node)})
    return tasks, schedulers, task_exports


def _python_assignment_value(node: ast.Assign | ast.AnnAssign) -> ast.expr | None:
    return node.value


def _python_assignment_names(
    node: ast.Assign | ast.AnnAssign | ast.AugAssign,
) -> set[str]:
    targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
    return {
        item.id
        for target in targets
        for item in ast.walk(target)
        if isinstance(item, ast.Name) and isinstance(item.ctx, (ast.Store, ast.Del))
    }


def _python_is_celery_app_factory(
    value: ast.expr | None,
    constructor_names: set[str],
    celery_module_names: set[str],
) -> bool:
    if not isinstance(value, ast.Call):
        return False
    dotted = _python_dotted_name(value.func)
    if dotted in constructor_names:
        return True
    parts = dotted.split(".") if dotted else []
    return (
        len(parts) == 2
        and parts[0] in celery_module_names
        and parts[1] == "Celery"
    )


def _python_celery_decorator(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    decorator_names: set[str],
    celery_module_names: set[str],
    app_names: set[str],
) -> ast.expr | None:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        dotted = _python_dotted_name(target)
        if dotted in decorator_names:
            return decorator
        parts = dotted.split(".") if dotted else []
        if (
            len(parts) == 2
            and parts[0] in celery_module_names
            and parts[1] in _CELERY_DECORATOR_MEMBERS
        ):
            return decorator
        if len(parts) == 2 and parts[0] in app_names and parts[1] == "task":
            return decorator
    return None


def _python_celery_decorator_metadata(decorator: ast.expr) -> tuple[str, str]:
    if not isinstance(decorator, ast.Call):
        return "", ""
    queue = ""
    retry_values: list[str] = []
    for keyword in decorator.keywords:
        if keyword.arg in {"queue", "routing_key"}:
            value = _python_string_literal(keyword.value)
            if value:
                queue = value
        if keyword.arg in _CELERY_RETRY_KEYWORDS:
            retry_values.append(keyword.arg)
    return queue, ", ".join(retry_values[:4])


def _python_string_literal(node: ast.AST | None) -> str:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else ""


def _python_is_beat_schedule_assignment(node: ast.Assign | ast.AnnAssign) -> bool:
    targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
    return any(isinstance(target, ast.Attribute) and target.attr == "beat_schedule" for target in targets)


def _python_beat_entries(value: ast.expr | None, content: str) -> list[tuple[str, str]]:
    if not isinstance(value, ast.Dict):
        return []
    entries: list[tuple[str, str]] = []
    for entry in value.values:
        if not isinstance(entry, ast.Dict):
            continue
        fields = {
            _python_string_literal(key): item
            for key, item in zip(entry.keys, entry.values)
            if _python_string_literal(key)
        }
        target = _python_string_literal(fields.get("task"))
        schedule_node = fields.get("schedule")
        schedule = ast.get_source_segment(content, schedule_node) if schedule_node else ""
        if target and schedule:
            entries.append((target, schedule.strip()[:120]))
    return entries


def _discover_schedulers(
    file_contents: dict[str, str],
    trees: dict[str, ast.Module] | None = None,
) -> list[RuntimeScheduler]:
    """Discover proven Celery ``crontab(...)`` calls from valid Python ASTs."""
    schedulers: list[RuntimeScheduler] = []
    for file_path, tree in (trees or _python_ast_trees(file_contents)).items():
        bindings = _python_crontab_bindings(tree)
        count = 0
        for call in sorted(
            (node for node in ast.walk(tree) if isinstance(node, ast.Call)),
            key=_python_node_position,
        ):
            dotted = _python_dotted_name(call.func)
            binding = bindings.get(dotted)
            if binding is None or binding > _python_node_position(call):
                continue
            count += 1
            source = ast.get_source_segment(file_contents[file_path], call) or ""
            schedulers.append(
                RuntimeScheduler(
                    name=f"crontab-{count}",
                    file_path=file_path,
                    scheduler_type="crontab",
                    cron=source.strip()[:120],
                )
            )
    return _dedupe_schedulers(schedulers)


def _python_node_position(node: ast.AST) -> tuple[int, int]:
    return (getattr(node, "lineno", 0), getattr(node, "col_offset", 0))


def _python_crontab_bindings(tree: ast.Module) -> dict[str, tuple[int, int]]:
    """Top-level names that are structurally imported from Celery schedules."""
    bindings: dict[str, tuple[int, int]] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                bindings.pop(local, None)
                if module == "celery.schedules" and alias.name == "crontab":
                    bindings[local] = _python_node_position(node)
                elif module == "celery" and alias.name == "schedules":
                    bindings[f"{local}.crontab"] = _python_node_position(node)
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                bindings.pop(local, None)
                bindings.pop(f"{local}.crontab", None)
                if alias.name == "celery.schedules":
                    bindings[f"{local}.crontab"] = _python_node_position(node)
            continue
        for name in _python_assignment_names_if_any(node):
            bindings.pop(name, None)
            bindings.pop(f"{name}.crontab", None)
    return bindings


def _python_assignment_names_if_any(node: ast.AST) -> set[str]:
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        if isinstance(node, ast.AnnAssign) and node.value is None:
            return set()
        return _python_assignment_names(node)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    return set()


def _discover_django_runtime(
    file_contents: dict[str, str],
    trees: dict[str, ast.Module] | None = None,
) -> list[RuntimeTask]:
    """Discover Django commands/signals only through proven AST bindings."""
    tasks: list[RuntimeTask] = []
    for file_path, tree in (trees or _python_ast_trees(file_contents)).items():
        tasks.extend(_discover_django_file_runtime(file_path, tree))
    return _dedupe_runtime_tasks(tasks)


def _discover_django_file_runtime(
    file_path: str, tree: ast.Module
) -> list[RuntimeTask]:
    """Django module facts in source order, rejecting generic lookalikes."""
    tasks: list[RuntimeTask] = []
    receiver_names: set[str] = set()
    signal_names: dict[str, str] = {}
    signal_module_names: set[str] = set()
    base_command_names: set[str] = set()

    def revoke(names: set[str]) -> None:
        receiver_names.difference_update(names)
        signal_module_names.difference_update(names)
        base_command_names.difference_update(names)
        for name in names:
            signal_names.pop(name, None)

    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                revoke({local})
                if module == "django.dispatch" and alias.name == "receiver":
                    receiver_names.add(local)
                elif (
                    module == "django.db.models.signals"
                    and alias.name in _PYTHON_DJANGO_SIGNAL_NAMES
                ):
                    signal_names[local] = alias.name
                elif module == "django.db.models" and alias.name == "signals":
                    signal_module_names.add(local)
                elif (
                    module == "django.core.management.base"
                    and alias.name == "BaseCommand"
                ):
                    base_command_names.add(local)
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                revoke({local})
                if alias.name == "django.db.models.signals":
                    signal_module_names.add(local)
            continue
        if isinstance(node, ast.ClassDef):
            if any(
                _python_dotted_name(base) in base_command_names
                for base in node.bases
            ):
                tasks.append(
                    RuntimeTask(
                        name=Path(file_path).stem.replace("_", "-"),
                        file_path=file_path,
                        runtime_kind="django_command",
                        decorator="BaseCommand",
                        triggers=["manage.py"],
                    )
                )
            revoke({node.name})
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            signal = _python_receiver_signal(
                node, receiver_names, signal_names, signal_module_names
            )
            if signal:
                tasks.append(
                    RuntimeTask(
                        name=node.name,
                        file_path=file_path,
                        runtime_kind="django_signal",
                        decorator="receiver",
                        triggers=[signal],
                    )
                )
            revoke({node.name})
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            signal, handler = _python_signal_connect(
                node.value, signal_names, signal_module_names
            )
            if signal and handler:
                tasks.append(
                    RuntimeTask(
                        name=handler,
                        file_path=file_path,
                        runtime_kind="django_signal",
                        decorator="connect",
                        triggers=[signal],
                    )
                )
            continue
        revoke(_python_assignment_names_if_any(node))
    return tasks


def _python_receiver_signal(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    receiver_names: set[str],
    signal_names: dict[str, str],
    signal_module_names: set[str],
) -> str:
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        if _python_dotted_name(decorator.func) not in receiver_names:
            continue
        if decorator.args:
            return _python_django_signal_name(
                decorator.args[0], signal_names, signal_module_names
            )
    return ""


def _python_signal_connect(
    call: ast.Call,
    signal_names: dict[str, str],
    signal_module_names: set[str],
) -> tuple[str, str]:
    if not isinstance(call.func, ast.Attribute) or call.func.attr != "connect":
        return "", ""
    signal = _python_django_signal_name(
        call.func.value, signal_names, signal_module_names
    )
    handler = call.args[0].id if call.args and isinstance(call.args[0], ast.Name) else ""
    return signal, handler


def _python_django_signal_name(
    node: ast.expr,
    signal_names: dict[str, str],
    signal_module_names: set[str],
) -> str:
    dotted = _python_dotted_name(node)
    if dotted in signal_names:
        return signal_names[dotted]
    parts = dotted.split(".") if dotted else []
    if (
        len(parts) == 2
        and parts[0] in signal_module_names
        and parts[1] in _PYTHON_DJANGO_SIGNAL_NAMES
    ):
        return parts[1]
    return ""


def _discover_laravel_runtime(
    file_contents: dict[str, str],
) -> tuple[list[RuntimeTask], list[RuntimeScheduler]]:
    tasks: list[RuntimeTask] = []
    schedulers: list[RuntimeScheduler] = []
    class_pattern = re.compile(r"class\s+([A-Za-z_][A-Za-z0-9_]*)")
    should_queue_pattern = re.compile(
        r"class\s+([A-Za-z_][A-Za-z0-9_]*)\s+implements\s+ShouldQueue"
    )
    handle_event_pattern = re.compile(
        r"function\s+handle\s*\(\s*([\\A-Za-z_][\\A-Za-z0-9_]*)",
    )
    queue_pattern = re.compile(
        r"(?:public|protected)\s+\$queue\s*=\s*['\"]([^'\"]+)['\"]"
    )
    command_schedule_pattern = re.compile(
        r"\$schedule->command\(\s*['\"]([^'\"]+)['\"][^\)]*\)(?P<chain>(?:\s*->\s*[A-Za-z_][A-Za-z0-9_]*\([^\)]*\))+)",
    )
    job_schedule_pattern = re.compile(
        r"\$schedule->job\(\s*(?:new\s+)?([\\A-Za-z_][\\A-Za-z0-9_]*)[^\)]*\)(?P<chain>(?:\s*->\s*[A-Za-z_][A-Za-z0-9_]*\([^\)]*\))+)",
    )
    call_schedule_pattern = re.compile(
        r"\$schedule->call\([^\)]*\)(?P<chain>(?:\s*->\s*[A-Za-z_][A-Za-z0-9_]*\([^\)]*\))+)",
    )

    for file_path, content in file_contents.items():
        lower_file = file_path.lower()
        class_targets = {
            declaration.name.lower(): declaration.target
            for declaration in php_class_declarations(content)
        }
        queue_match = queue_pattern.search(content)

        if "shouldqueue" in content.lower() or "/jobs/" in lower_file:
            for job_name in should_queue_pattern.findall(content):
                tasks.append(
                    RuntimeTask(
                        name=job_name,
                        file_path=file_path,
                        runtime_kind="laravel_job",
                        decorator="ShouldQueue",
                        queue=queue_match.group(1) if queue_match else "",
                        target_identities=_php_task_identities(class_targets, job_name),
                    )
                )

        if "/listeners/" in lower_file and "function handle(" in content:
            class_match = class_pattern.search(content)
            event_match = handle_event_pattern.search(content)
            if class_match:
                tasks.append(
                    RuntimeTask(
                        name=class_match.group(1),
                        file_path=file_path,
                        runtime_kind="laravel_listener",
                        decorator="listener",
                        queue=queue_match.group(1) if queue_match else "",
                        triggers=[event_match.group(1).split("\\")[-1]]
                        if event_match
                        else [],
                        target_identities=_php_task_identities(
                            class_targets, class_match.group(1)
                        ),
                    )
                )

        if "/events/" in lower_file:
            class_match = class_pattern.search(content)
            if class_match:
                tasks.append(
                    RuntimeTask(
                        name=class_match.group(1),
                        file_path=file_path,
                        runtime_kind="laravel_event",
                        decorator="event",
                        target_identities=_php_task_identities(
                            class_targets, class_match.group(1)
                        ),
                    )
                )

        for idx, match in enumerate(
            command_schedule_pattern.finditer(content), start=1
        ):
            command_name = match.group(1)
            schedulers.append(
                RuntimeScheduler(
                    name=f"laravel-command-{idx}",
                    file_path=file_path,
                    scheduler_type="laravel_schedule",
                    cron=_schedule_chain_summary(match.group("chain")),
                    invoked_targets=[command_name],
                )
            )

        for idx, match in enumerate(job_schedule_pattern.finditer(content), start=1):
            job_name = match.group(1).split("\\")[-1]
            schedulers.append(
                RuntimeScheduler(
                    name=f"laravel-job-{idx}",
                    file_path=file_path,
                    scheduler_type="laravel_schedule",
                    cron=_schedule_chain_summary(match.group("chain")),
                    invoked_targets=[job_name],
                )
            )

        for idx, match in enumerate(call_schedule_pattern.finditer(content), start=1):
            schedulers.append(
                RuntimeScheduler(
                    name=f"laravel-call-{idx}",
                    file_path=file_path,
                    scheduler_type="laravel_schedule",
                    cron=_schedule_chain_summary(match.group("chain")),
                    invoked_targets=["closure"],
                )
            )

    return _dedupe_runtime_tasks(tasks), _dedupe_schedulers(schedulers)


def _php_task_identities(
    class_targets: dict[str, str], class_name: str
) -> tuple[str, ...]:
    """Canonical parser-proven FQCN for one discovered Laravel class."""
    identity = class_targets.get(class_name.lower())
    return (identity,) if identity else ()


def _schedule_chain_summary(chain: str) -> str:
    method_match = re.search(r"->\s*([A-Za-z_][A-Za-z0-9_]*)\(([^\)]*)\)", chain)
    cron_match = re.search(r"->\s*cron\(\s*['\"]([^'\"]+)['\"]\s*\)", chain)
    if cron_match:
        return cron_match.group(1)
    if method_match:
        method = method_match.group(1)
        args = method_match.group(2).strip()
        return f"{method}({args})" if args else method
    return chain.strip()[:120]


# `new Worker(...)`, `.process(...)` and `.consume(...)` are ordinary JS/TS
# idioms - browser/Node workers and plain domain methods - so they only describe
# a queue job when that specific callee or receiver resolves, inside the same
# file, to a symbol imported from one of these libraries. A library import alone
# vouches for nothing: it left `codec.process()` and `new Worker('browser')`
# reading as background jobs next to an unrelated `bullmq` import.
# Importing a library is also not the same as using the part of it that runs
# jobs, so each rule below names the API role that consumes rather than the
# module: BullMQ's `Queue` only produces and has no `.process()`, and an AMQP
# connection is not the channel it opens. Roles come from `JsBoundCall.receiver`:
# `""` is the module's own export, and `X()`/`X().Y()` a value that bound call
# returned. Anything unlisted - another export, another shape, a value from
# another file - makes no claim.
JS_BULLMQ_MODULES = frozenset({"bullmq"})
# The single class Bull v3 and Bee-Queue construct both produces and consumes;
# Kue hands its queue out from the module instead. BullMQ is absent by design.
JS_QUEUE_INSTANCE_ROLES = {
    "bull": ("default()",),
    "bee-queue": ("default()",),
    "kue": ("createQueue()",),
}
# BullMQ's Queue only produces, while the older queue APIs can both produce and
# consume. Producer linkage accepts only these verified receiver roles.
JS_QUEUE_PRODUCER_ROLES = {"bullmq": ("Queue()",), **JS_QUEUE_INSTANCE_ROLES}
JS_AMQP_MODULES = frozenset({"amqplib", "amqp-connection-manager"})
JS_AMQP_CHANNEL_ROLE = "connect().createChannel()"
JS_AGENDA_MODULES = frozenset({"agenda", "@hokify/agenda"})
# `new Agenda(...)`, whether the constructor arrived as the module export or as
# a named `Agenda` import.
JS_AGENDA_INSTANCE_ROLES = ("default()", "Agenda()")
JS_SCHEDULER_MODULES = frozenset({"node-cron"})
JS_REALTIME_MODULES = frozenset({"socket.io", "ws"})
JS_SOCKET_IO_INSTANCE_ROLES = ("Server()", "default()")
JS_WS_INSTANCE_ROLE = "WebSocketServer()"
JS_RUNTIME_MODULES = (
    JS_BULLMQ_MODULES
    | frozenset(JS_QUEUE_INSTANCE_ROLES)
    | JS_AMQP_MODULES
    | JS_AGENDA_MODULES
)
# The parser runs once per JS/TS/Vue candidate and returns only executable calls
# bound to these supported modules. Scheduler/realtime roles join the same
# evidence path so template literals and comments cannot create runtime facts.
JS_BOUND_RUNTIME_MODULES = (
    JS_RUNTIME_MODULES | JS_SCHEDULER_MODULES | JS_REALTIME_MODULES
)
# Binding cannot succeed unless the module name appears literally, and every
# fact below needs one of these call shapes. This keeps tree-sitter off files
# that were never candidates while retaining legal whitespace before `(`.
JS_EVIDENCE_TOKENS = tuple(sorted(JS_BOUND_RUNTIME_MODULES))
JS_CALL_SHAPE_RE = re.compile(
    r"\bworker\b|\bschedule\s*\(|\.\s*(?:process|consume|define|every|schedule|on|add)\s*\(",
    re.IGNORECASE,
)


def _js_may_have_bound_runtime_call(content: str, lowered: str) -> bool:
    """Keep fast filtering without discarding renamed node-cron exports."""
    return bool(JS_CALL_SHAPE_RE.search(content)) or "node-cron" in lowered


def _js_str_arg(call: JsBoundCall, index: int) -> str:
    """Quoted-literal argument at `index`, or "" when it is not a literal."""
    if index >= len(call.args):
        return ""
    kind, value = call.args[index]
    return value if kind == "str" else ""


def _js_parse_inputs(file_path: str, content: str) -> tuple[tuple[str, str], ...]:
    """Independent executable JS/TS scopes for one source file or Vue SFC."""
    suffix = Path(file_path).suffix.lower()
    if suffix == ".vue":
        return tuple(
            (script, "typescript" if lang in ("ts", "tsx") else "javascript")
            for script, lang, _ in _extract_script_blocks(content)
        )
    return ((content, language_for_extension(suffix)),)


def _js_bound_runtime_calls(
    file_path: str, content: str
) -> tuple[tuple[str, JsBoundCall], ...]:
    """Bound calls from each real script scope, never merged across Vue blocks."""
    found: list[tuple[str, JsBoundCall]] = []
    for source, language in _js_parse_inputs(file_path, content):
        calls = js_bound_calls(
            Path(file_path), source, language, JS_BOUND_RUNTIME_MODULES
        )
        if calls:
            found.extend((language, call) for call in calls)
    return tuple(found)


def _js_dispatch_evidence(file_path: str, content: str) -> list[DispatchEvidence]:
    """Literal queue enqueues proven by a bound JS/TS/Vue queue API role."""
    lowered = content.lower()
    if not any(token in lowered for token in JS_EVIDENCE_TOKENS):
        return []
    if not _js_may_have_bound_runtime_call(content, lowered):
        return []
    calls = _js_bound_runtime_calls(file_path, content)
    if not calls:
        return []
    evidence: list[DispatchEvidence] = []
    for language, call in calls:
        if (
            call.is_new
            or call.symbol != "add"
            or call.receiver not in JS_QUEUE_PRODUCER_ROLES.get(call.module, ())
        ):
            continue
        # Bull/BullMQ `.add(jobName, data)` names a job. The dispatch target is
        # instead the literal identity of its proven Queue receiver.
        queue_name = call.receiver_identity
        if queue_name:
            evidence.append(
                DispatchEvidence(
                    file_path=file_path,
                    language=language,
                    relation="queue",
                    target_aliases=(queue_name,),
                )
            )
    return evidence


def _discover_js_runtime(
    file_contents: dict[str, str],
) -> tuple[list[RuntimeTask], list[RuntimeScheduler], list[RealtimeConsumer]]:
    """Discover JS/TS/Vue runtime facts only from syntax-bound API calls."""
    tasks: list[RuntimeTask] = []
    schedulers: list[RuntimeScheduler] = []
    realtime_routes: dict[tuple[str, str], set[str]] = {}

    for file_path, content in file_contents.items():
        node_cron_count = 0
        lowered = content.lower()
        if not any(token in lowered for token in JS_EVIDENCE_TOKENS):
            continue
        if not _js_may_have_bound_runtime_call(content, lowered):
            continue

        # Fail closed without syntax nodes: raw text cannot tell executable code
        # from library examples quoted in template literals or comments.
        calls = _js_bound_runtime_calls(file_path, content)
        if not calls:
            continue

        for language, call in calls:
            if call.is_new:
                # BullMQ names the queue in the `Worker` constructor itself.
                if (
                    call.symbol == "Worker"
                    and not call.receiver
                    and call.module in JS_BULLMQ_MODULES
                ):
                    queue_name = _js_str_arg(call, 0)
                    if queue_name:
                        tasks.append(
                            RuntimeTask(
                                name=queue_name,
                                file_path=file_path,
                                runtime_kind="js_worker",
                                decorator="Worker",
                                queue=queue_name,
                            )
                        )
                continue
            agenda_job = (
                call.module in JS_AGENDA_MODULES
                and call.receiver in JS_AGENDA_INSTANCE_ROLES
            )
            if (
                call.symbol == "process"
                and call.receiver in JS_QUEUE_INSTANCE_ROLES.get(call.module, ())
            ) or (
                call.symbol == "consume"
                and call.module in JS_AMQP_MODULES
                and call.receiver == JS_AMQP_CHANNEL_ROLE
            ):
                kind, value = call.args[0] if call.args else ("", "")
                queue_name = value if kind == "str" else ""
                tasks.append(
                    RuntimeTask(
                        name=queue_name or value or "queue-worker",
                        file_path=file_path,
                        runtime_kind="js_worker",
                        decorator="queue_process",
                        queue=queue_name,
                    )
                )
            elif agenda_job and call.symbol == "define":
                job_name = _js_str_arg(call, 0)
                if job_name:
                    tasks.append(
                        RuntimeTask(
                            name=job_name,
                            file_path=file_path,
                            runtime_kind="js_worker",
                            decorator="agenda.define",
                            queue=job_name,
                        )
                    )
            elif agenda_job and call.symbol == "every":
                cadence, job_name = _js_str_arg(call, 0), _js_str_arg(call, 1)
                if cadence and job_name:
                    schedulers.append(
                        RuntimeScheduler(
                            name=f"agenda-{job_name}",
                            file_path=file_path,
                            scheduler_type="agenda",
                            cron=cadence,
                            invoked_targets=[job_name],
                        )
                    )
            elif (
                call.module in JS_SCHEDULER_MODULES
                and call.symbol == "schedule"
                and not call.receiver
            ):
                cron = _js_str_arg(call, 0)
                if cron:
                    node_cron_count += 1
                    kind, target = call.args[1] if len(call.args) > 1 else ("", "")
                    schedulers.append(
                        RuntimeScheduler(
                            name=f"node-cron-{node_cron_count}",
                            file_path=file_path,
                            scheduler_type="node_cron",
                            cron=cron,
                            invoked_targets=[target] if kind == "name" and target else [],
                        )
                    )
            elif call.symbol == "on":
                event = _js_str_arg(call, 0)
                consumer_type = ""
                if (
                    call.module == "socket.io"
                    and call.receiver in JS_SOCKET_IO_INSTANCE_ROLES
                ):
                    consumer_type = "socket_io"
                elif call.module == "ws" and call.receiver == JS_WS_INSTANCE_ROLE:
                    consumer_type = "websocket"
                if event and consumer_type:
                    realtime_routes.setdefault((file_path, consumer_type), set()).add(
                        event
                    )

    consumers = [
        RealtimeConsumer(
            name=Path(file_path).stem,
            file_path=file_path,
            consumer_type=consumer_type,
            routes=sorted(routes),
            groups=[],
            auth_hints=["socket_connection"] if "connection" in routes else [],
        )
        for (file_path, consumer_type), routes in sorted(realtime_routes.items())
        if "connection" in routes
    ]
    return (
        _dedupe_runtime_tasks(tasks),
        _dedupe_schedulers(schedulers),
        _dedupe_consumers(consumers),
    )


def _discover_nestjs_runtime(file_contents: dict[str, str]) -> list[RuntimeTask]:
    tasks: list[RuntimeTask] = []
    cron_pattern = re.compile(
        r"""@Cron\s*\(\s*['"]([^'"]+)['"]\s*(?:,\s*\{[^}]*\})?\s*\)\s*\n\s*(?:async\s+)?(\w+)\s*\(""",
    )
    interval_pattern = re.compile(
        r"""@Interval\s*\(\s*(\d+)\s*\)\s*\n\s*(?:async\s+)?(\w+)\s*\(""",
    )
    timeout_pattern = re.compile(
        r"""@Timeout\s*\(\s*(\d+)\s*\)\s*\n\s*(?:async\s+)?(\w+)\s*\(""",
    )
    bull_inject_pattern = re.compile(
        r"""@InjectQueue\s*\(\s*['"]([^'"]+)['"]?\s*\)"""
    )
    bull_processor_pattern = re.compile(
        r"""@Processor\s*\(\s*['"]([^'"]+)['"]?\s*\)"""
    )
    bull_process_pattern = re.compile(
        r"""@Process\s*\(\s*(?:['"]([^'"]+)['"]?\s*)?\)\s*\n\s*(?:async\s+)?(\w+)\s*\(""",
    )

    for file_path, content in file_contents.items():
        if Path(file_path).suffix.lower() not in {".ts", ".js"}:
            continue
        is_nestjs = (
            "@nestjs" in content
            or "@Cron(" in content
            or "@InjectQueue(" in content
            or "@Processor(" in content
        )
        if not is_nestjs:
            continue

        for cron_expr, handler in cron_pattern.findall(content):
            tasks.append(
                RuntimeTask(
                    name=handler,
                    file_path=file_path,
                    runtime_kind="nestjs_cron",
                    triggers=[cron_expr],
                )
            )

        for interval_ms, handler in interval_pattern.findall(content):
            tasks.append(
                RuntimeTask(
                    name=handler,
                    file_path=file_path,
                    runtime_kind="nestjs_interval",
                    triggers=[f"every_{interval_ms}ms"],
                )
            )

        for timeout_ms, handler in timeout_pattern.findall(content):
            tasks.append(
                RuntimeTask(
                    name=handler,
                    file_path=file_path,
                    runtime_kind="nestjs_timeout",
                    triggers=[f"after_{timeout_ms}ms"],
                )
            )

        for queue_name in bull_inject_pattern.findall(content):
            tasks.append(
                RuntimeTask(
                    name=f"bull_queue_{queue_name}",
                    file_path=file_path,
                    runtime_kind="nestjs_bull_producer",
                    queue=queue_name,
                    triggers=["injected"],
                )
            )

        for queue_name in bull_processor_pattern.findall(content):
            tasks.append(
                RuntimeTask(
                    name=f"bull_processor_{queue_name}",
                    file_path=file_path,
                    runtime_kind="nestjs_bull_consumer",
                    queue=queue_name,
                    triggers=["queue_message"],
                )
            )

        for job_name, handler in bull_process_pattern.findall(content):
            name = job_name or handler or "unknown"
            tasks.append(
                RuntimeTask(
                    name=handler or name,
                    file_path=file_path,
                    runtime_kind="nestjs_bull_handler",
                    triggers=[f"job:{name}"],
                )
            )

    return _dedupe_runtime_tasks(tasks)


def _discover_go_runtime(
    file_contents: dict[str, str],
) -> tuple[list[RuntimeTask], list[RuntimeScheduler]]:
    tasks: list[RuntimeTask] = []
    schedulers: list[RuntimeScheduler] = []
    goroutine_pattern = re.compile(r"\bgo\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
    add_func_pattern = re.compile(
        r"\.AddFunc\(\s*['\"]([^'\"]+)['\"]\s*,\s*([A-Za-z_][A-Za-z0-9_]*)",
    )
    every_pattern = re.compile(
        r"\.Every\(\s*([0-9]+\s*\*\s*time\.[A-Za-z_]+)\s*\)\.Do\(\s*([A-Za-z_][A-Za-z0-9_]*)",
    )

    for file_path, content in file_contents.items():
        if not file_path.endswith(".go"):
            continue

        for worker_name in goroutine_pattern.findall(content):
            tasks.append(
                RuntimeTask(
                    name=worker_name,
                    file_path=file_path,
                    runtime_kind="go_worker",
                    decorator="goroutine",
                )
            )

        for cron_expr, target in add_func_pattern.findall(content):
            schedulers.append(
                RuntimeScheduler(
                    name=target,
                    file_path=file_path,
                    scheduler_type="go_cron",
                    cron=cron_expr,
                    invoked_targets=[target],
                )
            )
            tasks.append(
                RuntimeTask(
                    name=target,
                    file_path=file_path,
                    runtime_kind="go_worker",
                    decorator="cron.AddFunc",
                    schedule_sources=[cron_expr],
                )
            )

        for cadence, target in every_pattern.findall(content):
            schedulers.append(
                RuntimeScheduler(
                    name=target,
                    file_path=file_path,
                    scheduler_type="go_schedule",
                    cron=cadence,
                    invoked_targets=[target],
                )
            )
            tasks.append(
                RuntimeTask(
                    name=target,
                    file_path=file_path,
                    runtime_kind="go_worker",
                    decorator="Every.Do",
                    schedule_sources=[cadence],
                )
            )

    return _dedupe_runtime_tasks(tasks), _dedupe_schedulers(schedulers)


def _discover_python_realtime_consumers(
    file_contents: dict[str, str],
) -> list[RealtimeConsumer]:
    """Discover Django Channels consumers from Python source only.

    JavaScript realtime detection is intentionally handled by
    ``_discover_js_runtime`` through syntax-bound API roles. Keeping this
    function Python-only prevents raw JS-like text in templates or comments
    from creating a Socket.IO/WebSocket runtime fact.
    """
    consumers: list[RealtimeConsumer] = []
    consumer_pattern = re.compile(
        r"class\s+(\w+)\((AsyncWebsocketConsumer|WebsocketConsumer)\)\s*:"
    )
    route_pattern = re.compile(
        r"re_path\s*\(\s*r?['\"]([^'\"]+)['\"]|path\s*\(\s*['\"]([^'\"]+)['\"]"
    )
    group_pattern = re.compile(r"group_(?:add|discard|send)\s*\(\s*['\"]([^'\"]+)['\"]")

    for file_path, content in file_contents.items():
        if (
            "WebsocketConsumer" not in content
            and "AsyncWebsocketConsumer" not in content
            and "ProtocolTypeRouter" not in content
        ):
            continue

        routes = []
        for match in route_pattern.finditer(content):
            route = match.group(1) or match.group(2)
            if route:
                routes.append(route)
        groups = group_pattern.findall(content)
        auth_hints = []
        if "AuthMiddlewareStack" in content:
            auth_hints.append("AuthMiddlewareStack")
        if "scope['user']" in content or 'scope["user"]' in content:
            auth_hints.append("scope_user")

        for match in consumer_pattern.finditer(content):
            consumers.append(
                RealtimeConsumer(
                    name=match.group(1),
                    file_path=file_path,
                    consumer_type=match.group(2),
                    routes=sorted(set(routes))[:10],
                    groups=sorted(set(groups))[:10],
                    auth_hints=auth_hints,
                )
            )
    return _dedupe_consumers(consumers)


def _dedupe_runtime_tasks(tasks: list[RuntimeTask]) -> list[RuntimeTask]:
    by_key: dict[tuple[str, str, str], RuntimeTask] = {}
    for task in tasks:
        key = (task.file_path, task.name, task.runtime_kind)
        existing = by_key.get(key)
        if not existing:
            by_key[key] = task
            continue
        existing.schedule_sources = sorted(
            set(existing.schedule_sources + task.schedule_sources)
        )
        existing.triggers = sorted(set(existing.triggers + task.triggers))
        existing.producer_files = sorted(
            set(existing.producer_files + task.producer_files)
        )
        existing.linked_endpoints = sorted(
            set(existing.linked_endpoints + task.linked_endpoints)
        )
        if not existing.queue:
            existing.queue = task.queue
        if not existing.retry_policy:
            existing.retry_policy = task.retry_policy
        if not existing.decorator:
            existing.decorator = task.decorator
    return list(by_key.values())


def _dedupe_schedulers(schedulers: list[RuntimeScheduler]) -> list[RuntimeScheduler]:
    seen: dict[tuple[str, str, str, str], RuntimeScheduler] = {}
    for scheduler in schedulers:
        key = (
            scheduler.file_path,
            scheduler.name,
            scheduler.scheduler_type,
            scheduler.cron,
        )
        existing = seen.get(key)
        if not existing:
            seen[key] = scheduler
            continue
        existing.invoked_targets = sorted(
            set(existing.invoked_targets + scheduler.invoked_targets)
        )
        existing.linked_endpoints = sorted(
            set(existing.linked_endpoints + scheduler.linked_endpoints)
        )
    return list(seen.values())


def _dedupe_consumers(consumers: list[RealtimeConsumer]) -> list[RealtimeConsumer]:
    seen: dict[tuple[str, str], RealtimeConsumer] = {}
    for consumer in consumers:
        seen[(consumer.file_path, consumer.name)] = consumer
    return list(seen.values())
