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


# ── Resolution accuracy (import-evidence-gated, never guess) ──────────────────


def _pf(path: str, language: str, symbols: list[Symbol], imports: list[str] | None = None) -> ParsedFile:
    return ParsedFile(path=Path(path), language=language, symbols=symbols, imports=imports or [])


def _fn(name: str, start: int, end: int, kind: str = "function", decorators: list[str] | None = None) -> Symbol:
    return Symbol(
        name=name,
        kind=kind,
        signature=f"def {name}():",
        start_line=start,
        end_line=end,
        decorators=decorators or [],
    )


def test_ambiguous_bare_name_without_import_evidence_is_external() -> None:
    parsed_files = {
        "a/storage.py": _pf("a/storage.py", "python", [_fn("save", 1, 2)]),
        "b/cache.py": _pf("b/cache.py", "python", [_fn("save", 1, 2)]),
        "src/main.py": _pf("src/main.py", "python", [_fn("run", 1, 2)]),
    }
    file_contents = {
        "a/storage.py": "def save():\n    pass\n",
        "b/cache.py": "def save():\n    pass\n",
        "src/main.py": "def run():\n    save()\n",
    }
    graph = build_call_graph(parsed_files, file_contents)
    edges = graph.get_callees("src/main.py", "run")
    assert len(edges) == 1
    assert edges[0].call_kind == "external"
    assert edges[0].callee_file == ""


def test_ambiguous_name_with_import_evidence_resolves_to_imported_file() -> None:
    parsed_files = {
        "a/storage.py": _pf("a/storage.py", "python", [_fn("save", 1, 2)]),
        "b/cache.py": _pf("b/cache.py", "python", [_fn("save", 1, 2)]),
        "src/main.py": _pf(
            "src/main.py", "python", [_fn("run", 1, 2)],
            imports=["from a.storage import save"],
        ),
    }
    file_contents = {
        "a/storage.py": "def save():\n    pass\n",
        "b/cache.py": "def save():\n    pass\n",
        "src/main.py": "def run():\n    save()\n",
    }
    graph = build_call_graph(parsed_files, file_contents)
    edges = graph.get_callees("src/main.py", "run")
    assert [(e.callee_file, e.call_kind) for e in edges] == [("a/storage.py", "local")]


def test_aliased_python_import_resolves() -> None:
    parsed_files = {
        "services/payment.py": _pf("services/payment.py", "python", [_fn("charge", 1, 2)]),
        "src/main.py": _pf(
            "src/main.py", "python", [_fn("run", 1, 2)],
            imports=["from services.payment import charge as do_charge"],
        ),
    }
    file_contents = {
        "services/payment.py": "def charge():\n    pass\n",
        "src/main.py": "def run():\n    do_charge()\n",
    }
    graph = build_call_graph(parsed_files, file_contents)
    edges = graph.get_callees("src/main.py", "run")
    assert [(e.callee_file, e.callee_symbol) for e in edges] == [("services/payment.py", "charge")]


def test_aliased_js_import_resolves() -> None:
    parsed_files = {
        "src/util.js": _pf("src/util.js", "javascript", [_fn("helper", 1, 3)]),
        "src/app.js": _pf(
            "src/app.js", "javascript", [_fn("main", 1, 3)],
            imports=["import { helper as h } from './util'"],
        ),
    }
    file_contents = {
        "src/util.js": "function helper() {\n  return 1;\n}\n",
        "src/app.js": "function main() {\n  h();\n}\n",
    }
    graph = build_call_graph(parsed_files, file_contents)
    edges = graph.get_callees("src/app.js", "main")
    assert [(e.callee_file, e.callee_symbol) for e in edges] == [("src/util.js", "helper")]


def test_reexport_chain_resolves_to_defining_file() -> None:
    parsed_files = {
        "pkg/__init__.py": _pf(
            "pkg/__init__.py", "python", [],
            imports=["from pkg.order import OrderService"],
        ),
        "pkg/order.py": _pf(
            "pkg/order.py", "python",
            [_fn("OrderService", 1, 4, kind="class")],
        ),
        "src/main.py": _pf(
            "src/main.py", "python", [_fn("run", 1, 2)],
            imports=["from pkg import OrderService"],
        ),
    }
    file_contents = {
        "pkg/__init__.py": "from pkg.order import OrderService\n",
        "pkg/order.py": "class OrderService:\n    pass\n",
        "src/main.py": "def run():\n    OrderService()\n",
    }
    graph = build_call_graph(parsed_files, file_contents)
    edges = graph.get_callees("src/main.py", "run")
    assert [(e.callee_file, e.callee_symbol) for e in edges] == [("pkg/order.py", "OrderService")]


def test_circular_reexport_does_not_hang() -> None:
    parsed_files = {
        "x/a.py": _pf("x/a.py", "python", [], imports=["from x.b import thing"]),
        "x/b.py": _pf("x/b.py", "python", [], imports=["from x.a import thing"]),
        "src/main.py": _pf(
            "src/main.py", "python", [_fn("run", 1, 2)],
            imports=["from x.a import thing"],
        ),
    }
    file_contents = {
        "x/a.py": "from x.b import thing\n",
        "x/b.py": "from x.a import thing\n",
        "src/main.py": "def run():\n    thing()\n",
    }
    graph = build_call_graph(parsed_files, file_contents)
    edges = graph.get_callees("src/main.py", "run")
    assert [e.call_kind for e in edges] == ["external"]


def test_calls_inside_strings_and_comments_are_ignored() -> None:
    parsed_files = {
        "src/other.py": _pf("src/other.py", "python", [_fn("process_order", 1, 2)]),
        "src/main.py": _pf("src/main.py", "python", [_fn("run", 1, 5)]),
    }
    file_contents = {
        "src/other.py": "def process_order():\n    pass\n",
        "src/main.py": (
            "def run():\n"
            '    """Docstring mentions process_order() here."""\n'
            '    msg = "call process_order() now"\n'
            "    # process_order()\n"
            "    return msg\n"
        ),
    }
    graph = build_call_graph(parsed_files, file_contents)
    edges = graph.get_callees("src/main.py", "run")
    assert all(e.callee_symbol != "process_order" for e in edges)


def test_member_call_on_imported_class_resolves_into_class_range() -> None:
    parsed_files = {
        "services/order.py": _pf(
            "services/order.py", "python",
            [
                _fn("OrderService", 1, 6, kind="class"),
                _fn("create", 2, 3, kind="method"),
                _fn("create", 8, 9),  # same-name module-level fn outside the class
            ],
        ),
        "src/main.py": _pf(
            "src/main.py", "python", [_fn("run", 1, 2)],
            imports=["from services.order import OrderService"],
        ),
    }
    file_contents = {
        "services/order.py": (
            "class OrderService:\n"
            "    def create(self):\n"
            "        pass\n\n\n\n\n"
            "def create():\n"
            "    pass\n"
        ),
        "src/main.py": "def run():\n    OrderService.create()\n",
    }
    graph = build_call_graph(parsed_files, file_contents)
    edges = [e for e in graph.get_callees("src/main.py", "run") if e.callee_symbol == "create"]
    assert [(e.callee_file, e.call_kind) for e in edges] == [("services/order.py", "local")]


def test_ambiguous_member_call_is_unresolved_not_both() -> None:
    parsed_files = {
        "a/repo.py": _pf("a/repo.py", "python", [_fn("save", 1, 2)]),
        "b/cache.py": _pf("b/cache.py", "python", [_fn("save", 1, 2)]),
        "src/svc.py": _pf("src/svc.py", "python", [_fn("run", 1, 3)]),
    }
    file_contents = {
        "a/repo.py": "def save():\n    pass\n",
        "b/cache.py": "def save():\n    pass\n",
        "src/svc.py": "def run():\n    self.repo.save()\n    self.cache.save()\n",
    }
    graph = build_call_graph(parsed_files, file_contents)
    save_edges = [e for e in graph.get_callees("src/svc.py", "run") if e.callee_symbol == "save"]
    assert all(e.call_kind == "external" and e.callee_file == "" for e in save_edges)


def test_module_alias_member_call_resolves() -> None:
    parsed_files = {
        "utils.py": _pf("utils.py", "python", [_fn("save", 1, 2)]),
        "other.py": _pf("other.py", "python", [_fn("save", 1, 2)]),
        "src/main.py": _pf(
            "src/main.py", "python", [_fn("run", 1, 2)],
            imports=["import utils"],
        ),
    }
    file_contents = {
        "utils.py": "def save():\n    pass\n",
        "other.py": "def save():\n    pass\n",
        "src/main.py": "def run():\n    utils.save()\n",
    }
    graph = build_call_graph(parsed_files, file_contents)
    edges = [e for e in graph.get_callees("src/main.py", "run") if e.callee_symbol == "save"]
    assert [(e.callee_file, e.call_kind) for e in edges] == [("utils.py", "local")]


def test_celery_tasks_scoped_to_decorated_functions() -> None:
    parsed_files = {
        "tasks.py": _pf(
            "tasks.py", "python",
            [
                _fn("send_email", 2, 4, decorators=["@shared_task"]),
                _fn("plain_helper", 6, 8),
            ],
        ),
        "src/main.py": _pf("src/main.py", "python", [_fn("run", 1, 3)]),
    }
    file_contents = {
        "tasks.py": (
            "\n@shared_task\ndef send_email():\n    pass\n\n"
            "def plain_helper():\n    pass\n"
        ),
        "src/main.py": "def run():\n    send_email.delay()\n    plain_helper.delay()\n",
    }
    graph = build_call_graph(parsed_files, file_contents)
    celery_edges = [
        e for e in graph.get_callees("src/main.py", "run") if e.call_kind == "celery_dispatch"
    ]
    resolved = {e.callee_symbol: e.callee_file for e in celery_edges}
    assert resolved.get("send_email") == "tasks.py"
    assert resolved.get("plain_helper") == ""


def test_missing_end_line_body_extends_past_60_lines() -> None:
    body_lines = ["def big():"] + ["    x = 1"] * 78 + ["    late_call()"]
    parsed_files = {
        "src/big.py": _pf(
            "src/big.py", "python",
            [Symbol(name="big", kind="function", signature="def big():", start_line=1, end_line=0)],
        ),
        "src/late.py": _pf("src/late.py", "python", [_fn("late_call", 1, 2)]),
    }
    file_contents = {
        "src/big.py": "\n".join(body_lines) + "\n",
        "src/late.py": "def late_call():\n    pass\n",
    }
    graph = build_call_graph(parsed_files, file_contents)
    edges = graph.get_callees("src/big.py", "big")
    assert any(e.callee_symbol == "late_call" and e.callee_file == "src/late.py" for e in edges)


def test_serialize_roundtrip_schema_unchanged() -> None:
    parsed_files = {
        "src/util.py": _pf("src/util.py", "python", [_fn("helper", 1, 2)]),
        "src/main.py": _pf(
            "src/main.py", "python", [_fn("run", 1, 2)],
            imports=["from src.util import helper"],
        ),
    }
    file_contents = {
        "src/util.py": "def helper():\n    pass\n",
        "src/main.py": "def run():\n    helper()\n",
    }
    graph = build_call_graph(parsed_files, file_contents)
    data = graph.serialize()
    assert data["version"] == 2
    assert set(data["edges"][0].keys()) == {
        "caller_file", "caller_symbol", "callee_file", "callee_symbol",
        "call_kind", "call_site_line",
    }
    from deepdoc.call_graph import CallGraph

    restored = CallGraph.deserialize(data)
    assert restored.get_callees("src/main.py", "run")[0].callee_file == "src/util.py"


# ── Go call extraction ────────────────────────────────────────────────────────


def test_go_package_qualified_call_resolves() -> None:
    parsed_files = {
        "svc/worker.go": _pf(
            "svc/worker.go", "go",
            [Symbol(name="Run", kind="function", signature="func Run() {", start_line=1, end_line=3)],
            imports=['import (\n\thelper "app/helper"\n)'],
        ),
        "helper/helper.go": _pf(
            "helper/helper.go", "go",
            [Symbol(name="DoWork", kind="function", signature="func DoWork() {", start_line=1, end_line=3)],
        ),
    }
    file_contents = {
        "svc/worker.go": "func Run() {\n\thelper.DoWork()\n}\n",
        "helper/helper.go": "func DoWork() {\n\treturn\n}\n",
    }
    graph = build_call_graph(parsed_files, file_contents)
    edges = graph.get_callees("svc/worker.go", "Run")
    assert ("helper/helper.go", "DoWork", "local") in [
        (e.callee_file, e.callee_symbol, e.call_kind) for e in edges
    ]


def test_go_receiver_method_call_is_unresolved() -> None:
    parsed_files = {
        "a/server.go": _pf(
            "a/server.go", "go",
            [Symbol(name="Handle", kind="method", signature="func (s *Server) Handle() {", start_line=1, end_line=3)],
        ),
        "b/other.go": _pf(
            "b/other.go", "go",
            [Symbol(name="Persist", kind="method", signature="func (s *Store) Persist() {", start_line=1, end_line=3),
             Symbol(name="caller", kind="function", signature="func caller() {", start_line=5, end_line=7)],
        ),
    }
    file_contents = {
        "a/server.go": "func (s *Server) Handle() {\n\treturn\n}\n",
        "b/other.go": "func (s *Store) Persist() {\n\treturn\n}\n\nfunc caller() {\n\ts.Persist()\n}\n",
    }
    graph = build_call_graph(parsed_files, file_contents)
    edges = [e for e in graph.get_callees("b/other.go", "caller") if e.callee_symbol == "Persist"]
    assert all(e.call_kind == "external" for e in edges)


def test_go_string_and_comment_calls_ignored() -> None:
    parsed_files = {
        "m/main.go": _pf(
            "m/main.go", "go",
            [Symbol(name="Run", kind="function", signature="func Run() {", start_line=1, end_line=5)],
        ),
        "m/work.go": _pf(
            "m/work.go", "go",
            [Symbol(name="Work", kind="function", signature="func Work() {", start_line=1, end_line=2)],
        ),
    }
    file_contents = {
        "m/main.go": 'func Run() {\n\ts := "call Work() here"\n\t// Work()\n\t_ = s\n}\n',
        "m/work.go": "func Work() {\n}\n",
    }
    graph = build_call_graph(parsed_files, file_contents)
    edges = graph.get_callees("m/main.go", "Run")
    assert all(e.callee_symbol != "Work" for e in edges)


# ── PHP call extraction ───────────────────────────────────────────────────────


def test_php_static_call_via_use_resolves() -> None:
    parsed_files = {
        "app/Controllers/UserController.php": _pf(
            "app/Controllers/UserController.php", "php",
            [Symbol(name="store", kind="method", signature="public function store()", start_line=3, end_line=5)],
            imports=["use App\\Services\\Mailer;"],
        ),
        "app/Services/Mailer.php": _pf(
            "app/Services/Mailer.php", "php",
            [Symbol(name="Mailer", kind="class", signature="class Mailer", start_line=1, end_line=6),
             Symbol(name="send", kind="method", signature="public static function send()", start_line=2, end_line=4)],
        ),
    }
    file_contents = {
        "app/Controllers/UserController.php": "<?php\nclass UserController {\npublic function store() {\nMailer::send();\n}\n}\n",
        "app/Services/Mailer.php": "<?php\nclass Mailer {\npublic static function send() {\nreturn;\n}\n}\n",
    }
    graph = build_call_graph(parsed_files, file_contents)
    edges = [e for e in graph.get_callees("app/Controllers/UserController.php", "store") if e.callee_symbol == "send"]
    assert [(e.callee_file, e.call_kind) for e in edges] == [("app/Services/Mailer.php", "local")]


def test_php_instance_arrow_call_is_unresolved() -> None:
    parsed_files = {
        "a/One.php": _pf("a/One.php", "php",
            [Symbol(name="run", kind="method", signature="function run()", start_line=1, end_line=2)]),
        "b/Two.php": _pf("b/Two.php", "php",
            [Symbol(name="run", kind="method", signature="function run()", start_line=1, end_line=2),
             Symbol(name="go", kind="method", signature="function go()", start_line=4, end_line=6)]),
    }
    file_contents = {
        "a/One.php": "<?php\nfunction run() {}\n",
        "b/Two.php": "<?php\nfunction run() {}\n\nfunction go() {\n$this->run();\n}\n",
    }
    graph = build_call_graph(parsed_files, file_contents)
    edges = [e for e in graph.get_callees("b/Two.php", "go") if e.callee_symbol == "run"]
    assert all(e.call_kind == "external" for e in edges)


# ── Inheritance-aware self.method() resolution (Python) ────────────────────────


def _cls(name: str, start: int, end: int, signature: str) -> Symbol:
    return Symbol(name=name, kind="class", signature=signature, start_line=start, end_line=end)


def test_inherited_responder_resolves_cross_file() -> None:
    parsed_files = {
        "resources/base.py": _pf(
            "resources/base.py", "python",
            [_cls("BaseResource", 1, 4, "class BaseResource:"),
             Symbol(name="validate", kind="method", signature="def validate(self):", start_line=2, end_line=3)],
        ),
        "resources/user.py": _pf(
            "resources/user.py", "python",
            [_cls("UserResource", 1, 4, "class UserResource(BaseResource):"),
             Symbol(name="on_post", kind="method", signature="def on_post(self):", start_line=2, end_line=3)],
            imports=["from resources.base import BaseResource"],
        ),
    }
    file_contents = {
        "resources/base.py": "class BaseResource:\n    def validate(self):\n        return True\n\n",
        "resources/user.py": "class UserResource(BaseResource):\n    def on_post(self):\n        self.validate()\n\n",
    }
    graph = build_call_graph(parsed_files, file_contents)
    edges = [e for e in graph.get_callees("resources/user.py", "on_post") if e.callee_symbol == "validate"]
    assert [(e.callee_file, e.call_kind) for e in edges] == [("resources/base.py", "local")]


def test_inherited_method_resolves_transitively() -> None:
    parsed_files = {
        "h/c.py": _pf("h/c.py", "python",
            [_cls("C", 1, 4, "class C:"),
             Symbol(name="deep", kind="method", signature="def deep(self):", start_line=2, end_line=3)]),
        "h/b.py": _pf("h/b.py", "python",
            [_cls("B", 1, 3, "class B(C):")],
            imports=["from h.c import C"]),
        "h/a.py": _pf("h/a.py", "python",
            [_cls("A", 1, 4, "class A(B):"),
             Symbol(name="run", kind="method", signature="def run(self):", start_line=2, end_line=3)],
            imports=["from h.b import B"]),
    }
    file_contents = {
        "h/c.py": "class C:\n    def deep(self):\n        return 1\n\n",
        "h/b.py": "class B(C):\n    pass\n\n",
        "h/a.py": "class A(B):\n    def run(self):\n        self.deep()\n\n",
    }
    graph = build_call_graph(parsed_files, file_contents)
    edges = [e for e in graph.get_callees("h/a.py", "run") if e.callee_symbol == "deep"]
    assert [(e.callee_file, e.call_kind) for e in edges] == [("h/c.py", "local")]


def test_third_party_base_method_is_unresolved() -> None:
    parsed_files = {
        "views.py": _pf("views.py", "python",
            [_cls("ReportView", 1, 4, "class ReportView(ModelViewSet):"),
             Symbol(name="list", kind="method", signature="def list(self):", start_line=2, end_line=3)],
            imports=["from rest_framework.viewsets import ModelViewSet"]),
    }
    file_contents = {
        "views.py": "class ReportView(ModelViewSet):\n    def list(self):\n        self.get_queryset()\n\n",
    }
    graph = build_call_graph(parsed_files, file_contents)
    edges = [e for e in graph.get_callees("views.py", "list") if e.callee_symbol == "get_queryset"]
    assert all(e.call_kind == "external" for e in edges)


def test_cyclic_inheritance_does_not_hang() -> None:
    parsed_files = {
        "cyc.py": _pf("cyc.py", "python",
            [_cls("A", 1, 4, "class A(B):"),
             Symbol(name="run", kind="method", signature="def run(self):", start_line=2, end_line=3),
             _cls("B", 6, 8, "class B(A):")]),
    }
    file_contents = {
        "cyc.py": "class A(B):\n    def run(self):\n        self.missing()\n\n\nclass B(A):\n    pass\n\n",
    }
    graph = build_call_graph(parsed_files, file_contents)
    edges = [e for e in graph.get_callees("cyc.py", "run") if e.callee_symbol == "missing"]
    assert all(e.call_kind == "external" for e in edges)
