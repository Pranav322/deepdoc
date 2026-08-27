import ast
import re
from pathlib import Path
from typing import Any

from .common import *
from .common import (
    DispatchEvidence,
    RealtimeConsumer,
    RuntimeScan,
    RuntimeScheduler,
    RuntimeTask,
)
from ..parser.base import ParsedFile
from ..parser.js_ts_parser import JsBoundCall, js_bound_calls
from ..parser.php_parser import php_dispatches
from ..parser.registry import language_for_extension
from ..parser.vue_parser import _extract_script_block
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

    celery_tasks, celery_schedulers = _discover_celery_tasks(python_files)
    runtime.tasks.extend(celery_tasks)
    runtime.schedulers.extend(celery_schedulers)
    runtime.tasks.extend(_discover_django_runtime(python_files))
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
    runtime.schedulers.extend(_discover_schedulers(python_files))
    runtime.realtime_consumers.extend(
        _discover_python_realtime_consumers(python_files)
    )
    runtime.dispatch_evidence = _collect_dispatch_evidence(
        eligible,
        languages,
        _python_task_names_by_path(runtime.tasks),
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


def _python_task_names_by_path(tasks: list[RuntimeTask]) -> dict[str, set[str]]:
    """Celery task names keyed by their defining Python source file."""
    names: dict[str, set[str]] = {}
    for task in tasks:
        if task.runtime_kind == "celery" and task.file_path.endswith(".py"):
            names.setdefault(task.file_path, set()).add(task.name)
    return names


def _collect_dispatch_evidence(
    file_contents: dict[str, str],
    languages: dict[str, str],
    python_task_names_by_path: dict[str, set[str]] | None = None,
) -> list[DispatchEvidence]:
    """Collect language-structural evidence only from eligible source files."""
    evidence: list[DispatchEvidence] = []
    task_names = python_task_names_by_path or {}
    for file_path, content in file_contents.items():
        language = languages.get(file_path)
        if language == "python":
            evidence.extend(_python_dispatch_evidence(file_path, content, task_names))
        elif language == "php":
            evidence.extend(
                DispatchEvidence(
                    file_path=file_path,
                    language="php",
                    relation="direct",
                    target_aliases=_target_aliases(dispatch.target),
                )
                for dispatch in php_dispatches(content)
            )
        elif language in JS_LANGUAGES:
            evidence.extend(_js_dispatch_evidence(file_path, content))
    return evidence


def _scheduler_owner_evidence(
    schedulers: list[RuntimeScheduler],
) -> list[DispatchEvidence]:
    """Declarations themselves are bounded evidence of scheduler ownership."""
    return [
        DispatchEvidence(
            file_path=scheduler.file_path,
            language="runtime",
            relation="scheduler_owner",
            target_aliases=_target_aliases(scheduler.name),
        )
        for scheduler in schedulers
        if scheduler.name and scheduler.file_path
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
    task_names_by_path: dict[str, set[str]],
) -> list[DispatchEvidence]:
    """Evidence from syntax-proven Celery task/Django signal bindings only."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []
    (
        task_aliases,
        task_modules,
        signal_aliases,
        signal_modules,
        module_write_lines,
    ) = _python_runtime_bindings(file_path, tree, task_names_by_path)
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
                call.lineno,
                task_aliases,
                task_modules,
                task_names_by_path,
                module_write_lines,
            )
            relation = "direct"
        elif func.attr == "send":
            target = _python_bound_signal_target(
                func.value,
                call.lineno,
                signal_aliases,
                signal_modules,
                module_write_lines,
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


def _python_runtime_bindings(
    file_path: str,
    tree: ast.Module,
    task_names_by_path: dict[str, set[str]],
) -> tuple[
    dict[str, tuple[str, int]],
    dict[str, tuple[str, int]],
    dict[str, tuple[str, int]],
    dict[str, int],
    dict[str, tuple[int, ...]],
]:
    """Top-level bindings that prove a task or Django signal receiver role."""
    task_aliases: dict[str, tuple[str, int]] = {}
    task_modules: dict[str, tuple[str, int]] = {}
    signal_aliases: dict[str, tuple[str, int]] = {}
    signal_modules: dict[str, int] = {}
    module_write_lines = _python_module_write_lines(tree)
    local_task_names = task_names_by_path.get(file_path, set())

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if (
                node.name in local_task_names
                and _python_is_celery_task_declaration(node)
            ):
                task_aliases[node.name] = (node.name, node.lineno)
            continue
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            task_path = _python_import_module_file(file_path, module, node.level)
            imported_tasks = task_names_by_path.get(task_path, set())
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                if alias.name in imported_tasks:
                    task_aliases[local] = (alias.name, node.lineno)
                if (
                    module == "django.db.models.signals"
                    and alias.name in _PYTHON_DJANGO_SIGNAL_NAMES
                ):
                    signal_aliases[local] = (alias.name, node.lineno)
                elif module == "django.db.models" and alias.name == "signals":
                    signal_modules[local] = node.lineno
                if not module:
                    module_path = _python_import_module_file(
                        file_path, alias.name, node.level
                    )
                    if module_path in task_names_by_path:
                        task_modules[local] = (module_path, node.lineno)
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or ""
                if not local:
                    continue
                if alias.name == "django.db.models.signals":
                    signal_modules[local] = node.lineno
                    continue
                task_path = _python_import_module_file(file_path, alias.name, 0)
                if task_path in task_names_by_path:
                    task_modules[local] = (task_path, node.lineno)
    return (
        task_aliases,
        task_modules,
        signal_aliases,
        signal_modules,
        module_write_lines,
    )


def _python_module_write_lines(tree: ast.Module) -> dict[str, tuple[int, ...]]:
    """Module-scope binding writes keyed by source line for temporal resolution."""
    lines_by_name: dict[str, list[int]] = {}

    def add(name: str, line: int) -> None:
        if name:
            lines_by_name.setdefault(name, []).append(line)

    def visit(node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            add(node.name, node.lineno)
            return
        if isinstance(node, ast.ClassDef):
            add(node.name, node.lineno)
            return
        if isinstance(node, ast.Lambda):
            return
        if isinstance(node, ast.Import):
            for alias in node.names:
                add(alias.asname or alias.name.split(".", 1)[0], node.lineno)
            return
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    add(alias.asname or alias.name, node.lineno)
            return
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            add(node.id, node.lineno)
        for child in ast.iter_child_nodes(node):
            visit(child)

    for statement in tree.body:
        visit(statement)
    return {
        name: tuple(sorted(lines)) for name, lines in lines_by_name.items()
    }


def _python_binding_is_current(
    name: str,
    binding_line: int,
    call_line: int,
    module_write_lines: dict[str, tuple[int, ...]],
) -> bool:
    """A top-level binding remains trusted until a later write to its name."""
    if binding_line > call_line:
        return False
    writes = module_write_lines.get(name, ())
    if sum(write == binding_line for write in writes) > 1:
        # Same-line semicolon ordering is unavailable from this compact index.
        # Reject rather than assuming the import won the race.
        return False
    return not any(binding_line < write <= call_line for write in writes)


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


def _python_is_celery_task_declaration(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        dotted = _python_dotted_name(target)
        if dotted.rsplit(".", 1)[-1] in {"task", "shared_task"}:
            return True
    return False


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
    line: int,
    task_aliases: dict[str, tuple[str, int]],
    task_modules: dict[str, tuple[str, int]],
    task_names_by_path: dict[str, set[str]],
    module_write_lines: dict[str, tuple[int, ...]],
) -> str:
    dotted = _python_dotted_name(node)
    if not dotted:
        return ""
    parts = dotted.split(".")
    if len(parts) == 1:
        binding = task_aliases.get(parts[0])
        return (
            binding[0]
            if binding is not None
            and _python_binding_is_current(
                parts[0], binding[1], line, module_write_lines
            )
            else ""
        )
    module_binding = task_modules.get(parts[0])
    if (
        module_binding is None
        or not _python_binding_is_current(
            parts[0], module_binding[1], line, module_write_lines
        )
    ):
        return ""
    candidate = parts[-1]
    return dotted if candidate in task_names_by_path.get(module_binding[0], set()) else ""


def _python_bound_signal_target(
    node: ast.expr,
    line: int,
    signal_aliases: dict[str, tuple[str, int]],
    signal_modules: dict[str, int],
    module_write_lines: dict[str, tuple[int, ...]],
) -> str:
    dotted = _python_dotted_name(node)
    if not dotted:
        return ""
    parts = dotted.split(".")
    if len(parts) == 1:
        binding = signal_aliases.get(parts[0])
        return (
            binding[0]
            if binding is not None
            and _python_binding_is_current(
                parts[0], binding[1], line, module_write_lines
            )
            else ""
        )
    module_line = signal_modules.get(parts[0])
    candidate = parts[-1]
    if (
        module_line is not None
        and _python_binding_is_current(
            parts[0], module_line, line, module_write_lines
        )
        and candidate in _PYTHON_DJANGO_SIGNAL_NAMES
    ):
        return candidate
    return ""


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
    endpoint_keys_by_file = _published_endpoint_keys_by_file(api_endpoints)
    # Direct, queue, and scheduler relations are one-to-one claims. Store only
    # a unique object or an ambiguity sentinel, never a candidate bucket that a
    # producer site could enumerate. Signals intentionally retain a list because
    # their dispatch grammar explicitly means a broadcast to matching handlers.
    tasks_by_alias: dict[str, Any] = {}
    queues_by_alias: dict[str, Any] = {}
    signals_by_alias: dict[str, list[RuntimeTask]] = {}
    schedulers_by_target: dict[str, Any] = {}
    schedulers_by_terminal_target: dict[str, Any] = {}
    schedulers_by_owner: dict[tuple[str, str], Any] = {}
    for task in runtime.tasks:
        for alias in _target_aliases(task.name):
            _add_exact_candidate(tasks_by_alias, alias, task)
        for trigger in task.triggers:
            for alias in _target_aliases(trigger):
                signals_by_alias.setdefault(alias, []).append(task)
        # Queue evidence may resolve only against an explicitly declared queue;
        # task display names are not a cross-runtime queue identity.
        if task.queue:
            _add_exact_candidate(queues_by_alias, task.queue, task)
    for scheduler in runtime.schedulers:
        for alias in _target_aliases(scheduler.name):
            _add_exact_candidate(
                schedulers_by_owner, (scheduler.file_path, alias), scheduler
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

    task_checks = 0
    scheduler_checks = 0
    signal_broadcast_edges = 0
    ambiguous_task_targets = 0
    index_probes = 0
    for item in evidence:
        if item.relation == "scheduler_owner":
            endpoint_keys = endpoint_keys_by_file.get(item.file_path, ())
            if endpoint_keys:
                scheduler = _resolve_owner_candidate(
                    schedulers_by_owner, item.file_path, item.target_aliases
                )
                if scheduler is not None and scheduler is not _AMBIGUOUS:
                    scheduler_checks += 1
                    scheduler.linked_endpoints = sorted(
                        set(scheduler.linked_endpoints) | set(endpoint_keys)
                    )
            continue
        if item.relation == "signal":
            signal_candidates = _indexed_candidates(
                signals_by_alias, item.target_aliases
            )
            endpoint_keys = endpoint_keys_by_file.get(item.file_path, ())
            for task in signal_candidates:
                task_checks += 1
                signal_broadcast_edges += 1
                if item.file_path not in task.producer_files:
                    task.producer_files.append(item.file_path)
                if endpoint_keys:
                    task.linked_endpoints = sorted(
                        set(task.linked_endpoints) | set(endpoint_keys)
                    )
            continue
        if item.relation == "direct":
            task = _resolve_exact_candidate(tasks_by_alias, item.target_aliases)
        elif item.relation == "queue":
            task = _resolve_queue_candidate(queues_by_alias, item.target_aliases)
        else:
            continue
        index_probes += 1
        if task is _AMBIGUOUS:
            ambiguous_task_targets += 1
        elif task is not None:
            task_checks += 1
            if item.file_path not in task.producer_files:
                task.producer_files.append(item.file_path)
            endpoint_keys = endpoint_keys_by_file.get(item.file_path, ())
            if endpoint_keys:
                task.linked_endpoints = sorted(
                    set(task.linked_endpoints) | set(endpoint_keys)
                )

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
            scheduler.linked_endpoints = sorted(
                set(scheduler.linked_endpoints) | set(endpoint_keys)
            )

    runtime.scan_stats.update(
        {
            "link_evidence_count": len(evidence),
            "link_task_checks": task_checks,
            "link_scheduler_checks": scheduler_checks,
            "link_signal_broadcast_edges": signal_broadcast_edges,
            "link_ambiguous_task_targets": ambiguous_task_targets,
            "link_index_probes": index_probes,
        }
    )


def _published_endpoint_keys_by_file(
    api_endpoints: list[dict[str, Any]],
) -> dict[str, set[str]]:
    """Published endpoint keys owned by each file, failing closed on raw input."""
    endpoint_keys_by_file: dict[str, set[str]] = {}
    for ep in api_endpoints:
        if not ep.get("publication_ready", True):
            continue
        key = f"{str(ep.get('method', 'GET')).upper()} {ep.get('path', '')}"
        for owned in endpoint_owned_files(ep):
            endpoint_keys_by_file.setdefault(owned, set()).add(key)
    return endpoint_keys_by_file


def _target_aliases(target: str) -> tuple[str, ...]:
    """Stable canonical aliases for namespaced runtime targets."""
    normalized = target.strip().lstrip("\\")
    if not normalized:
        return ()
    short = normalized.rsplit("\\", 1)[-1]
    return (normalized,) if short == normalized else (normalized, short)


_AMBIGUOUS = object()


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


def _indexed_candidates(index: dict[str, list[Any]], aliases: tuple[str, ...]) -> list[Any]:
    """Stable, identity-deduplicated candidates for explicit signal broadcasts."""
    candidates: list[Any] = []
    seen: set[int] = set()
    for alias in aliases:
        for item in index.get(alias, ()):
            if id(item) not in seen:
                seen.add(id(item))
                candidates.append(item)
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


def _discover_celery_tasks(
    file_contents: dict[str, str],
) -> tuple[list[RuntimeTask], list[RuntimeScheduler]]:
    tasks: list[RuntimeTask] = []
    schedulers: list[RuntimeScheduler] = []
    task_pattern = re.compile(
        r"@(?P<decorator>(?:\w+\.)?(?:task|shared_task))(?P<args>\([^\n]*\))?\s*\n(?:async\s+)?def\s+(?P<name>\w+)\s*\(",
        re.MULTILINE,
    )
    queue_pattern = re.compile(r"(?:queue|routing_key)\s*=\s*['\"]([^'\"]+)['\"]")
    beat_dict_pattern = re.compile(
        r"['\"]task['\"]\s*:\s*['\"]([^'\"]+)['\"].*?['\"]schedule['\"]\s*:\s*([^,}\n]+)",
        re.DOTALL,
    )

    for file_path, content in file_contents.items():
        if (
            "celery" not in content
            and "@shared_task" not in content
            and ".delay(" not in content
            and ".apply_async(" not in content
        ):
            continue

        for match in task_pattern.finditer(content):
            args = match.group("args") or ""
            queue_match = queue_pattern.search(args)
            retry_values = [
                key
                for key in (
                    "autoretry_for",
                    "max_retries",
                    "retry_backoff",
                    "default_retry_delay",
                )
                if key in args
            ]
            tasks.append(
                RuntimeTask(
                    name=match.group("name"),
                    file_path=file_path,
                    runtime_kind="celery",
                    decorator=match.group("decorator"),
                    queue=queue_match.group(1) if queue_match else "",
                    retry_policy=", ".join(retry_values[:4]),
                )
            )

        for beat_task, schedule in beat_dict_pattern.findall(content):
            runtime_name = beat_task.split(".")[-1]
            tasks.append(
                RuntimeTask(
                    name=runtime_name,
                    file_path=file_path,
                    runtime_kind="celery",
                    schedule_sources=[schedule.strip()[:120]],
                )
            )
            schedulers.append(
                RuntimeScheduler(
                    name=runtime_name,
                    file_path=file_path,
                    scheduler_type="beat",
                    cron=schedule.strip()[:120],
                    invoked_targets=[beat_task],
                )
            )

    return _dedupe_runtime_tasks(tasks), _dedupe_schedulers(schedulers)


def _discover_schedulers(file_contents: dict[str, str]) -> list[RuntimeScheduler]:
    """Discover Python crontab declarations after JS uses structural binding."""
    schedulers: list[RuntimeScheduler] = []
    crontab_pattern = re.compile(r"crontab\s*\(([^)]*)\)")

    for file_path, content in file_contents.items():
        if "crontab(" in content:
            for idx, match in enumerate(crontab_pattern.finditer(content), start=1):
                schedulers.append(
                    RuntimeScheduler(
                        name=f"crontab-{idx}",
                        file_path=file_path,
                        scheduler_type="crontab",
                        cron=match.group(1).strip()[:120],
                    )
                )
    return _dedupe_schedulers(schedulers)


def _discover_django_runtime(file_contents: dict[str, str]) -> list[RuntimeTask]:
    tasks: list[RuntimeTask] = []
    command_pattern = re.compile(r"class\s+Command\s*\([^)]*BaseCommand[^)]*\)\s*:")
    receiver_pattern = re.compile(
        r"@receiver\s*\(\s*([A-Za-z_][A-Za-z0-9_.]*)[^\)]*\)\s*\n(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        re.MULTILINE,
    )
    connect_pattern = re.compile(
        r"\b([A-Za-z_][A-Za-z0-9_.]*)\.connect\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)",
    )

    for file_path, content in file_contents.items():
        if "BaseCommand" in content and command_pattern.search(content):
            tasks.append(
                RuntimeTask(
                    name=Path(file_path).stem.replace("_", "-"),
                    file_path=file_path,
                    runtime_kind="django_command",
                    decorator="BaseCommand",
                    triggers=["manage.py"],
                )
            )

        if "@receiver" in content:
            for signal_name, handler_name in receiver_pattern.findall(content):
                tasks.append(
                    RuntimeTask(
                        name=handler_name,
                        file_path=file_path,
                        runtime_kind="django_signal",
                        decorator="receiver",
                        triggers=[signal_name.split(".")[-1]],
                    )
                )

        if ".connect(" in content:
            for signal_name, handler_name in connect_pattern.findall(content):
                tasks.append(
                    RuntimeTask(
                        name=handler_name,
                        file_path=file_path,
                        runtime_kind="django_signal",
                        decorator="connect",
                        triggers=[signal_name.split(".")[-1]],
                    )
                )

    return _dedupe_runtime_tasks(tasks)


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


def _js_parse_input(file_path: str, content: str) -> tuple[str, str]:
    """Source text and grammar language for one JS/TS/Vue candidate file.

    A Vue SFC is markup wrapped around a script block, so only the script is
    real JS - handing the whole file to a JS grammar would not be executable
    evidence.
    """
    suffix = Path(file_path).suffix.lower()
    if suffix == ".vue":
        script, script_lang, _ = _extract_script_block(content)
        return script, "typescript" if script_lang in ("ts", "tsx") else "javascript"
    return content, language_for_extension(suffix)


def _js_dispatch_evidence(file_path: str, content: str) -> list[DispatchEvidence]:
    """Literal queue enqueues proven by a bound JS/TS/Vue queue API role."""
    lowered = content.lower()
    if not any(token in lowered for token in JS_EVIDENCE_TOKENS):
        return []
    if not _js_may_have_bound_runtime_call(content, lowered):
        return []
    source, language = _js_parse_input(file_path, content)
    calls = js_bound_calls(
        Path(file_path), source, language, JS_BOUND_RUNTIME_MODULES
    )
    if not calls:
        return []
    evidence: list[DispatchEvidence] = []
    for call in calls:
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

        source, language = _js_parse_input(file_path, content)
        # Fail closed without syntax nodes: raw text cannot tell executable code
        # from library examples quoted in template literals or comments.
        calls = js_bound_calls(
            Path(file_path), source, language, JS_BOUND_RUNTIME_MODULES
        )
        if not calls:
            continue

        for call in calls:
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


from .utils import endpoint_owned_files
