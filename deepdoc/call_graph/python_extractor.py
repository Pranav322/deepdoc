"""Python call extractor."""

from __future__ import annotations

import re
from typing import Any

from .extractor import (
    CallExtractor, CALL_KIND_LOCAL, CALL_KIND_CELERY, CALL_KIND_SIGNAL,
    _strip_strings_and_comments, LANGUAGE_BUILTINS, CallEdge, GraphRelation,
)

_PY_CALL_RE = re.compile(
    r"(?:(\w+)\.(\w+)\s*\(|(?<![\w.])(\w+)\s*\()"
)
_PY_CELERY_DISPATCH_RE = re.compile(r"(\w+)\.(delay|apply_async)\s*\(")
_PY_SIGNAL_RE = re.compile(r"\.(send|send_robust)\s*\(")


class PythonCallExtractor(CallExtractor):
    language = "python"
    builtins = LANGUAGE_BUILTINS["python"]

    def extract_calls(
        self, graph: Any, file_path: str, caller: str, body: str,
        ctx: Any, caller_class: str | None = None,
        celery_tasks: set | None = None,
    ) -> None:
        from ..call_graph import (
            _emit_call, _resolve_bare_call, _resolve_member_call,
        )

        caller_node = graph.symbol_node(file_path, caller)

        # Celery dispatch detection
        for m in _PY_CELERY_DISPATCH_RE.finditer(body):
            task_name = m.group(1)
            if task_name.lower() in self.builtins:
                continue
            resolved = _resolve_bare_call(task_name, file_path, ctx)
            is_task = resolved is not None and celery_tasks and resolved[1].name in celery_tasks
            if is_task:
                graph.add_edge(CallEdge(
                    caller_file=file_path, caller_symbol=caller,
                    callee_file=resolved[0], callee_symbol=task_name,
                    call_kind=CALL_KIND_CELERY,
                ))
            else:
                graph.add_edge(CallEdge(
                    caller_file=file_path, caller_symbol=caller,
                    callee_file="", callee_symbol=task_name,
                    call_kind=CALL_KIND_CELERY,
                ))

        # Django signal detection
        for m in _PY_SIGNAL_RE.finditer(body):
            graph.add_edge(CallEdge(
                caller_file=file_path, caller_symbol=caller,
                callee_file="", callee_symbol=f"signal:{m.group(1)}",
                call_kind=CALL_KIND_SIGNAL,
            ))

        stripped = _strip_strings_and_comments(body, "python")
        seen: set[str] = set()
        for m in _PY_CALL_RE.finditer(stripped):
            receiver, method, bare = m.group(1), m.group(2), m.group(3)
            name = method or bare
            if not name or name.lower() in self.builtins:
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


__all__ = ["PythonCallExtractor"]