"""Per-language call extractors + shared types.

Each language has a CallExtractor implementation that strips comments/strings
from function bodies and produces raw call edges. Resolution is handled by
``call_graph.py`` using import-evidence-gated matching.

Data types (``CallEdge``, ``GraphRelation``, constants) live here so
extractors and call_graph.py can share them without circular imports.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CallEdge:
    caller_file: str
    caller_symbol: str
    callee_file: str
    callee_symbol: str
    call_kind: str = "local"
    call_site_line: int = 0


@dataclass(frozen=True)
class GraphRelation:
    src: str
    dst: str
    kind: str
    metadata: dict[str, Any] = field(default_factory=dict)


CALL_KIND_LOCAL = "local"
CALL_KIND_CELERY = "celery_dispatch"
CALL_KIND_SIGNAL = "signal_dispatch"
CALL_KIND_EVENT = "event_dispatch"
CALL_KIND_EXTERNAL = "external"

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

_PY_BUILTINS = frozenset({
    "print", "len", "range", "int", "str", "float", "bool", "list", "dict",
    "tuple", "set", "type", "isinstance", "hasattr", "getattr", "setattr",
    "open", "input", "enumerate", "zip", "map", "filter", "sorted", "reversed",
    "abs", "all", "any", "sum", "min", "max", "round", "id", "repr", "chr",
    "ord", "hex", "oct", "bin", "format", "super", "next", "iter", "object",
    "property", "staticmethod", "classmethod", "vars", "dir", "help",
})
_JS_BUILTINS = frozenset({
    "console", "Math", "JSON", "parseInt", "parseFloat", "Array", "Object",
    "String", "Number", "Boolean", "Date", "RegExp", "Map", "Set", "Error",
    "Promise", "setTimeout", "setInterval", "clearTimeout", "clearInterval",
})
_GO_BUILTINS = frozenset({
    "real", "imag", "clear", "make", "len", "cap", "append", "copy", "delete",
    "close", "panic", "recover", "new", "complex",
})
_PHP_BUILTINS = frozenset({
    "echo", "print", "var_dump", "empty", "isset", "unset",
    "array", "count", "strlen", "trim", "sprintf",
})

LANGUAGE_BUILTINS = {
    "python": _PY_BUILTINS,
    "javascript": _JS_BUILTINS,
    "typescript": _JS_BUILTINS,
    "go": _GO_BUILTINS,
    "php": _PHP_BUILTINS,
}


class CallExtractor(ABC):
    language: str
    builtins: frozenset[str] = frozenset()

    @abstractmethod
    def extract_calls(
        self, graph: Any, file_path: str, caller: str, body: str,
        ctx: Any, caller_class: str | None = None,
        celery_tasks: set | None = None,
    ) -> None: ...


def _strip_strings_and_comments(body: str, lang: str) -> str:
    import re
    if lang in ("python",):
        body = re.sub(r'""".*?"""', "", body, flags=re.DOTALL)
        body = re.sub(r"'''.*?'''", "", body, flags=re.DOTALL)
        body = re.sub(r'(?m)^\s*#.*$', "", body)
        body = re.sub(r'"(?:[^"\\]|\\.)*"', '""', body)
        body = re.sub(r"'(?:[^'\\]|\\.)*'", "''", body)
    elif lang in ("javascript", "typescript", "go", "php"):
        body = re.sub(r"`(?:[^`\\]|\\.)*`", "``", body)
        body = re.sub(r'"(?:[^"\\]|\\.)*"', '""', body)
        body = re.sub(r"'(?:[^'\\]|\\.)*'", "''", body)
        body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
        body = re.sub(r"(?m)^\s*//.*$", "", body)
        if lang == "php":
            body = re.sub(r"(?m)^\s*#.*$", "", body)
    return body


__all__ = [
    "CallEdge", "GraphRelation",
    "CALL_KIND_LOCAL", "CALL_KIND_CELERY", "CALL_KIND_SIGNAL",
    "CALL_KIND_EVENT", "CALL_KIND_EXTERNAL",
    "REL_KIND_IMPORTS", "REL_KIND_DEFINES", "REL_KIND_CONTAINS",
    "REL_KIND_DEFINED_IN", "REL_KIND_REFERENCES",
    "REL_KIND_ROUTE_DECLARES", "REL_KIND_ROUTE_HANDLER",
    "REL_KIND_ROUTE_MIDDLEWARE",
    "REL_KIND_COMPONENT_USES", "REL_KIND_COMPONENT_PROP",
    "REL_KIND_COMPONENT_EMITS",
    "REL_KIND_NESTJS_GUARD", "REL_KIND_NESTJS_INTERCEPTOR",
    "LANGUAGE_BUILTINS", "CallExtractor", "_strip_strings_and_comments",
]