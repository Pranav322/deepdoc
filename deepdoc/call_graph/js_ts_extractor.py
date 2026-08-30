"""JS/TS call extractor."""

from __future__ import annotations

import re
from typing import Any

from .extractor import (
    CallExtractor, CALL_KIND_EVENT, CALL_KIND_LOCAL,
    _strip_strings_and_comments, LANGUAGE_BUILTINS,
    CallEdge, GraphRelation,
    REL_KIND_REFERENCES,
)

_JS_EMIT_RE = re.compile(r"\.(emit|dispatch|trigger)\s*\(\s*['\"]([\w-]+)['\"]")
_JS_CALL_RE = re.compile(
    r"(?:await\s*)?(?:(\w+(?:\.\w+)*)\.(\w+)\s*\(|(?<![\w.])(\w+)\s*\()"
)


class JSTSCallExtractor(CallExtractor):
    language = "javascript"
    builtins = LANGUAGE_BUILTINS["javascript"]

    def extract_calls(
        self, graph: Any, file_path: str, caller: str, body: str,
        ctx: Any, caller_class: str | None = None,
    ) -> None:
        from ..call_graph import (
            _emit_call, _resolve_bare_call, _resolve_member_call,
        )

        caller_node = graph.symbol_node(file_path, caller)

        # Event emits
        for m in _JS_EMIT_RE.finditer(body):
            event_name = m.group(2)
            graph.add_edge(CallEdge(
                caller_file=file_path, caller_symbol=caller,
                callee_file="", callee_symbol=f"event:{event_name}",
                call_kind=CALL_KIND_EVENT,
            ))
            graph.add_relation(GraphRelation(
                src=caller_node,
                dst=graph.external_node(f"event:{event_name}"),
                kind=REL_KIND_REFERENCES,
                metadata={"call_kind": CALL_KIND_EVENT},
            ))

        stripped = _strip_strings_and_comments(body, "javascript")
        seen: set[str] = set()
        for m in _JS_CALL_RE.finditer(stripped):
            receiver, method, bare = m.group(1), m.group(2), m.group(3)
            name = method or bare
            if not name or name.lower() in self.builtins:
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


__all__ = ["JSTSCallExtractor"]