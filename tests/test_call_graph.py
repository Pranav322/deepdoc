from __future__ import annotations

from pathlib import Path

from deepdoc.call_graph import (
    REL_KIND_COMPONENT_EMITS,
    REL_KIND_COMPONENT_PROP,
    REL_KIND_COMPONENT_USES,
    REL_KIND_DEFINES,
    REL_KIND_IMPORTS,
    REL_KIND_REFERENCES,
    REL_KIND_ROUTE_DECLARES,
    REL_KIND_ROUTE_HANDLER,
    REL_KIND_ROUTE_MIDDLEWARE,
    build_call_graph,
)
from deepdoc.parser.base import ParsedFile, Symbol


def test_call_graph_ignores_function_declaration_self_edges() -> None:
    parsed_files = {
        "src/auth.py": ParsedFile(
            path=Path("src/auth.py"),
            language="python",
            symbols=[
                Symbol(
                    name="login",
                    kind="function",
                    signature="def login():",
                    start_line=1,
                    end_line=3,
                )
            ],
        )
    }
    file_contents = {
        "src/auth.py": "def login():\n    return 1\n",
    }

    graph = build_call_graph(parsed_files, file_contents)

    assert graph.get_callees("src/auth.py", "login") == []


def test_call_graph_captures_hyphenated_js_events() -> None:
    parsed_files = {
        "src/events.js": ParsedFile(
            path=Path("src/events.js"),
            language="javascript",
            symbols=[
                Symbol(
                    name="publishEvent",
                    kind="function",
                    signature="function publishEvent()",
                    start_line=1,
                    end_line=3,
                )
            ],
        )
    }
    file_contents = {
        "src/events.js": "function publishEvent() {\n  emitter.emit('user-login');\n}\n",
    }

    graph = build_call_graph(parsed_files, file_contents)
    effects = graph.get_async_side_effects("src/events.js", "publishEvent")

    assert [edge.callee_symbol for edge in effects] == ["event:user-login"]


def test_call_graph_builds_definition_and_import_relations() -> None:
    parsed_files = {
        "src/auth.py": ParsedFile(
            path=Path("src/auth.py"),
            language="python",
            imports=["from services.order_service import OrderService"],
            symbols=[
                Symbol(
                    name="login",
                    kind="function",
                    signature="def login():",
                    start_line=1,
                    end_line=3,
                )
            ],
        ),
        "services/order_service.py": ParsedFile(
            path=Path("services/order_service.py"),
            language="python",
            imports=[],
            symbols=[
                Symbol(
                    name="OrderService",
                    kind="class",
                    signature="class OrderService:",
                    start_line=1,
                    end_line=4,
                )
            ],
        ),
    }
    file_contents = {
        "src/auth.py": "def login():\n    return 1\n",
        "services/order_service.py": "class OrderService:\n    pass\n",
    }

    graph = build_call_graph(parsed_files, file_contents)

    file_node = graph.file_node("src/auth.py")
    symbol_node = graph.symbol_node("src/auth.py", "login")
    defined_symbols = graph.get_defined_symbols("src/auth.py")
    import_targets = graph.get_import_targets("src/auth.py")

    assert symbol_node in defined_symbols
    assert any(
        relation.dst == graph.file_node("services/order_service.py")
        for relation in graph.get_outgoing_relations(file_node, kinds={REL_KIND_IMPORTS})
    )
    assert any(relation.dst == symbol_node for relation in graph.get_outgoing_relations(file_node, kinds={REL_KIND_DEFINES}))
    assert graph.file_node("services/order_service.py") in import_targets


def test_call_graph_builds_reference_relations_from_local_calls() -> None:
    parsed_files = {
        "src/auth.py": ParsedFile(
            path=Path("src/auth.py"),
            language="python",
            symbols=[
                Symbol(
                    name="login",
                    kind="function",
                    signature="def login():",
                    start_line=1,
                    end_line=2,
                ),
                Symbol(
                    name="authenticate",
                    kind="function",
                    signature="def authenticate():",
                    start_line=4,
                    end_line=5,
                ),
            ],
        )
    }
    file_contents = {
        "src/auth.py": "def login():\n    authenticate()\n\ndef authenticate():\n    return True\n",
    }

    graph = build_call_graph(parsed_files, file_contents)

    refs = graph.get_outgoing_relations(
        graph.symbol_node("src/auth.py", "login"),
        kinds={REL_KIND_REFERENCES},
    )

    assert graph.symbol_node("src/auth.py", "authenticate") in [relation.dst for relation in refs]


def test_call_graph_adds_framework_overlay_relations() -> None:
    parsed_files = {
        "src/routes/users.js": ParsedFile(
            path=Path("src/routes/users.js"),
            language="javascript",
            symbols=[
                Symbol(
                    name="listUsers",
                    kind="function",
                    signature="function listUsers(req, res)",
                    start_line=1,
                    end_line=3,
                )
            ],
        ),
        "src/components/UserList.vue": ParsedFile(
            path=Path("src/components/UserList.vue"),
            language="vue",
            symbols=[
                Symbol(name="UserList", kind="component", signature="defineOptions({ name: 'UserList' })"),
                Symbol(name="props", kind="constant", signature="defineProps()", props=["teamId"]),
                Symbol(name="emit", kind="constant", signature="defineEmits()", fields=["select"]),
                Symbol(name="router", kind="constant", signature="useRouter()"),
            ],
        ),
    }
    file_contents = {
        "src/routes/users.js": "function listUsers(req, res) {\n  return []\n}\n",
        "src/components/UserList.vue": "<script setup></script>\n",
    }
    api_endpoints = [
        {
            "method": "GET",
            "path": "/api/users",
            "handler": "listUsers",
            "route_file": "src/routes/users.js",
            "handler_file": "src/routes/users.js",
            "file": "src/routes/users.js",
            "middleware": ["auth"],
            "framework": "express",
        }
    ]

    graph = build_call_graph(parsed_files, file_contents, api_endpoints)

    route_node = graph.route_node("GET", "/api/users")
    route_file_node = graph.file_node("src/routes/users.js")
    handler_node = graph.symbol_node("src/routes/users.js", "listUsers")
    component_node = graph.symbol_node("src/components/UserList.vue", "UserList")

    assert any(
        relation.dst == route_node
        for relation in graph.get_outgoing_relations(route_file_node, kinds={REL_KIND_ROUTE_DECLARES})
    )
    assert any(
        relation.dst == handler_node
        for relation in graph.get_outgoing_relations(route_node, kinds={REL_KIND_ROUTE_HANDLER})
    )
    assert any(
        relation.dst == graph.middleware_node("auth")
        for relation in graph.get_outgoing_relations(route_node, kinds={REL_KIND_ROUTE_MIDDLEWARE})
    )
    assert any(
        relation.kind == REL_KIND_COMPONENT_PROP and relation.dst == graph.external_node("vue:prop:teamId")
        for relation in graph.get_outgoing_relations(component_node)
    )
    assert any(
        relation.kind == REL_KIND_COMPONENT_EMITS and relation.dst == graph.external_node("vue:emit:select")
        for relation in graph.get_outgoing_relations(component_node)
    )
    assert any(
        relation.kind == REL_KIND_COMPONENT_USES and relation.dst == graph.external_node("vue:router")
        for relation in graph.get_outgoing_relations(component_node)
    )
