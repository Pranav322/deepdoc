"""Call graph extraction package."""

from .extractor import (
    CallEdge, GraphRelation,
    CALL_KIND_LOCAL, CALL_KIND_CELERY, CALL_KIND_SIGNAL,
    CALL_KIND_EVENT, CALL_KIND_EXTERNAL,
    REL_KIND_IMPORTS, REL_KIND_DEFINES, REL_KIND_CONTAINS,
    REL_KIND_DEFINED_IN, REL_KIND_REFERENCES,
    REL_KIND_ROUTE_DECLARES, REL_KIND_ROUTE_HANDLER,
    REL_KIND_ROUTE_MIDDLEWARE,
    REL_KIND_COMPONENT_USES, REL_KIND_COMPONENT_PROP,
    REL_KIND_COMPONENT_EMITS,
    REL_KIND_NESTJS_GUARD, REL_KIND_NESTJS_INTERCEPTOR,
    CallExtractor, LANGUAGE_BUILTINS, _strip_strings_and_comments,
)
from .go_extractor import GoCallExtractor
from .java_extractor import JavaCallExtractor
from .js_ts_extractor import JSTSCallExtractor
from .php_extractor import PHPCallExtractor
from .python_extractor import PythonCallExtractor

EXTRACTOR_REGISTRY = {
    "python": PythonCallExtractor(),
    "javascript": JSTSCallExtractor(),
    "typescript": JSTSCallExtractor(),
    "go": GoCallExtractor(),
    "php": PHPCallExtractor(),
    "java": JavaCallExtractor(),
}


def get_extractor(language: str) -> CallExtractor | None:
    return EXTRACTOR_REGISTRY.get(language)


# Re-export the graph builder (formerly call_graph.py)
from .graph_builder import (
    build_call_graph, CallGraph,
    _resolve_bare_call, _resolve_member_call, _emit_call,
    _enclosing_class, _body_without_declaration, _build_module_index,
    _parse_file_imports, _FileImports,
    _is_celery_task, _parse_class_bases,
    _add_framework_overlay_relations, _add_nestjs_decorator_edges,
    _extract_py_calls, _extract_js_calls, _extract_go_calls, _extract_php_calls,
)


__all__ = [
    "CallEdge", "GraphRelation",
    "CALL_KIND_LOCAL", "CALL_KIND_CELERY", "CALL_KIND_SIGNAL",
    "CALL_KIND_EVENT", "CALL_KIND_EXTERNAL",
    "CallExtractor", "get_extractor", "EXTRACTOR_REGISTRY",
    "GoCallExtractor", "JSTSCallExtractor", "PHPCallExtractor",
    "PythonCallExtractor", "JavaCallExtractor", "LANGUAGE_BUILTINS", "_strip_strings_and_comments",
    "build_call_graph", "CallGraph",
    "_resolve_bare_call", "_resolve_member_call", "_emit_call",
]