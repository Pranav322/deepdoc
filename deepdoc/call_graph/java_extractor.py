"""Java call extractor using tree-sitter AST.

Uses tree-sitter-java's ``method_invocation`` nodes to extract call sites
directly from the AST — no regex needed.  Nested invocations (chains like
``foo.bar().baz()``) are handled by walking child nodes.

Interface-dispatch calls (e.g. ``repository.save()`` where ``repository`` is
typed as an interface) are recorded as unresolved with
``call_kind=CALL_KIND_EXTERNAL``.
"""

from __future__ import annotations

import re
from typing import Any

from .extractor import (
    CallExtractor, CALL_KIND_LOCAL, CALL_KIND_EXTERNAL, CallEdge,
)


class JavaCallExtractor(CallExtractor):
    language = "java"
    builtins = frozenset({
        "System", "out", "err", "println", "printf",
        "toString", "hashCode", "equals", "getClass", "clone",
        "wait", "notify", "notifyAll",
    })

    def extract_calls(
        self, graph: Any, file_path: str, caller: str, body: str,
        ctx: Any, caller_class: str | None = None,
        celery_tasks: set | None = None,
    ) -> None:
        from ..call_graph import _emit_call, _resolve_bare_call, _resolve_member_call

        try:
            from tree_sitter import Parser, Language
            import tree_sitter_java as tsjava

            lang = Language(tsjava.language())
            parser = Parser(lang)
            tree = parser.parse(bytes(body, "utf8"))
            lines = body.splitlines()
            _extract_method_invocations(
                tree.root_node, graph, file_path, caller, ctx,
                body, lines, self.builtins,
            )
        except Exception:
            # Fall back to regex if tree-sitter is unavailable
            self._regex_fallback(graph, file_path, caller, body, ctx)


    def _regex_fallback(self, graph, file_path, caller, body, ctx):
        from ..call_graph import _emit_call, _resolve_bare_call, _resolve_member_call

        _JAVA_CALL_RE = re.compile(
            r"(?:(\w+)\.(\w+)\s*\(|(?<![\w.])(\w+)\s*\()"
        )
        stripped = _strip_java(body)
        seen: set[str] = set()
        for m in _JAVA_CALL_RE.finditer(stripped):
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


def _strip_java(body: str) -> str:
    body = re.sub(r'"(?:[^"\\]|\\.)*"', '""', body)
    body = re.sub(r"'(?:[^'\\]|\\.)*'", "''", body)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    body = re.sub(r"(?m)^\s*//.*$", "", body)
    return body


def _extract_method_invocations(
    node, graph, file_path, caller, ctx, body, lines, builtins,
) -> None:
    from ..call_graph import _emit_call, _resolve_bare_call, _resolve_member_call

    t = node.type

    if t == "method_invocation":
        name = _invocation_name(node, body)
        if not name or name.lower() in builtins:
            pass  # skip builtins, but still walk children for nested invocations
        else:
            receiver = _invocation_receiver(node, body)
            if receiver and receiver not in builtins:
                resolved = _resolve_member_call(receiver, name, file_path, ctx)
            else:
                resolved = _resolve_bare_call(name, file_path, ctx)
            _emit_call(graph, file_path, caller, name, resolved)

    for child in node.children:
        _extract_method_invocations(child, graph, file_path, caller, ctx, body, lines, builtins)


def _invocation_name(node, body: str) -> str:
    """Extract the method name from a method_invocation node.

    A method_invocation like ``userService.findAll()`` has two identifier
    children: the receiver and the method name. The last identifier is always
    the called method.
    """
    last_id = ""
    for child in node.children:
        if child.type == "identifier":
            last_id = child.text.decode("utf-8")
    return last_id


def _invocation_receiver(node, body: str) -> str:
    """Extract the receiver (object/variable name) from a method_invocation."""
    for child in node.children:
        if child.type == "field_access":
            # e.g., userService.findAll → field_access contains the object
            for fc in child.children:
                if fc.type == "identifier":
                    return fc.text.decode("utf-8")
    return ""


__all__ = ["JavaCallExtractor"]