"""Go call extractor — with receiver type tracking fix."""

from __future__ import annotations

import re
from typing import Any

from .extractor import (
    CallExtractor, CALL_KIND_LOCAL,
    _strip_strings_and_comments, LANGUAGE_BUILTINS,
)

_GO_CALL_RE = re.compile(r"(?:(\w+)\.(\w+)\s*\(|(?<![\w.])(\w+)\s*\()")


class GoCallExtractor(CallExtractor):
    language = "go"
    builtins = LANGUAGE_BUILTINS["go"]

    def extract_calls(
        self, graph: Any, file_path: str, caller: str, body: str,
        ctx: Any, caller_class: str | None = None,
    ) -> None:
        from ..call_graph import (
            _emit_call, _resolve_bare_call, _resolve_member_call,
        )

        stripped = _strip_strings_and_comments(body, "go")
        seen: set[str] = set()

        file_symbols = ctx.file_symbol_names.get(file_path, {})
        go_structs = {
            sname for sname in file_symbols
            if ctx.sym_index.get(sname) and any(
                sf.kind == "class" for _, sf in ctx.sym_index.get(sname, [])
            )
        }

        for m in _GO_CALL_RE.finditer(stripped):
            receiver, method, bare = m.group(1), m.group(2), m.group(3)
            name = method or bare
            if not name or name.lower() in self.builtins:
                continue
            seen_key = f"{receiver}.{name}" if receiver else name
            if seen_key in seen:
                continue
            seen.add(seen_key)
            if receiver:
                if receiver in go_structs:
                    recv_file, recv_target = _resolve_bare_call(name, file_path, ctx)
                    if recv_file:
                        resolved = (recv_file, recv_target)
                    else:
                        resolved = _resolve_member_call(receiver, name, file_path, ctx)
                else:
                    resolved = _resolve_member_call(receiver, name, file_path, ctx)
            else:
                resolved = _resolve_bare_call(name, file_path, ctx)
            _emit_call(graph, file_path, caller, name, resolved)


__all__ = ["GoCallExtractor"]