"""PHP call extractor."""

from __future__ import annotations

import re
from typing import Any

from .extractor import (
    CallExtractor, CALL_KIND_LOCAL, CALL_KIND_EXTERNAL,
    _strip_strings_and_comments, LANGUAGE_BUILTINS,
)

_PHP_CALL_RE = re.compile(
    r"new\s+(\w+)\s*\("          # g1: new Class(
    r"|(\w+)::(\w+)\s*\("        # g2::g3: Class::method(
    r"|\$\w+->(\w+)\s*\("        # g4: $var->method(
    r"|(?<![\w$>:])(\w+)\s*\("   # g5: bare func(
)


class PHPCallExtractor(CallExtractor):
    language = "php"
    builtins = LANGUAGE_BUILTINS["php"]

    def extract_calls(
        self, graph: Any, file_path: str, caller: str, body: str,
        ctx: Any, caller_class: str | None = None,
    ) -> None:
        from ..call_graph import (
            _emit_call, _resolve_bare_call, _resolve_member_call,
            CallEdge,
        )

        stripped = _strip_strings_and_comments(body, "php")
        seen: set[str] = set()

        for m in _PHP_CALL_RE.finditer(stripped):
            new_cls, stat_cls, stat_m, inst_m, bare = m.groups()
            if new_cls:
                resolved = _resolve_bare_call(new_cls, file_path, ctx)
                _emit_call(graph, file_path, caller, new_cls, resolved)
                continue
            if stat_cls and stat_m:
                if stat_m.lower() in self.builtins:
                    continue
                key = f"{stat_cls}::{stat_m}"
                if key in seen:
                    continue
                seen.add(key)
                resolved = _resolve_member_call(stat_cls, stat_m, file_path, ctx)
                _emit_call(graph, file_path, caller, stat_m, resolved)
                continue
            if inst_m:
                if inst_m.lower() in self.builtins:
                    continue
                if inst_m in seen:
                    continue
                seen.add(inst_m)
                graph.add_edge(CallEdge(
                    caller_file=file_path, caller_symbol=caller,
                    callee_file="", callee_symbol=inst_m,
                    call_kind=CALL_KIND_EXTERNAL,
                ))
                continue
            if bare:
                if bare.lower() in self.builtins:
                    continue
                if bare in seen:
                    continue
                seen.add(bare)
                resolved = _resolve_bare_call(bare, file_path, ctx)
                _emit_call(graph, file_path, caller, bare, resolved)


__all__ = ["PHPCallExtractor"]