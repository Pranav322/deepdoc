from __future__ import annotations

from pathlib import Path

from deepdoc.call_graph import CallEdge, CallGraph, CALL_KIND_CELERY, CALL_KIND_LOCAL
from deepdoc.parser.base import ParsedFile, Symbol
from deepdoc.planner.flow_candidates import build_flow_candidates
from deepdoc.scanner.common import EndpointBundle, EvidenceUnit, RuntimeScan, RuntimeTask
from deepdoc.v2_models import RepoScan


def _scan_base() -> RepoScan:
    return RepoScan(
        file_tree={},
        file_summaries={},
        api_endpoints=[],
        languages={"python": 1},
        has_openapi=False,
        openapi_paths=[],
        total_files=0,
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
        parsed_files={},
        file_contents={},
    )


def _add_symbol(scan: RepoScan, file_path: str, name: str) -> None:
    scan.parsed_files[file_path] = ParsedFile(
        path=Path(file_path),
        language="python",
        imports=[],
        symbols=[Symbol(name=name, kind="function", signature=f"def {name}():")],
    )


def test_flow_candidates_seed_from_endpoint_bundle() -> None:
    scan = _scan_base()
    scan.endpoint_bundles = [
        EndpointBundle(
            endpoint_family="orders",
            methods_paths=["POST /orders"],
            handler_file="orders/handlers.py",
            handler_symbols=["create_order"],
            evidence=[EvidenceUnit(file_path="orders/handlers.py", role="handler")],
        )
    ]
    _add_symbol(scan, "orders/handlers.py", "create_order")

    graph = CallGraph()
    graph.add_edge(
        CallEdge(
            caller_file="orders/handlers.py",
            caller_symbol="create_order",
            callee_file="orders/service.py",
            callee_symbol="create",
            call_kind=CALL_KIND_LOCAL,
        )
    )
    scan.call_graph = graph

    flows = build_flow_candidates(scan, max_flows=5)

    assert flows
    assert flows[0].entry_kind == "endpoint_family"
    assert any(ep.label == "POST /orders" for ep in flows[0].entry_points)


def test_flow_candidates_seed_from_runtime_task() -> None:
    scan = _scan_base()
    scan.runtime_scan = RuntimeScan(
        tasks=[
            RuntimeTask(
                name="sync_orders",
                file_path="tasks.py",
                runtime_kind="celery",
            )
        ]
    )
    _add_symbol(scan, "tasks.py", "sync_orders")

    graph = CallGraph()
    graph.add_edge(
        CallEdge(
            caller_file="tasks.py",
            caller_symbol="sync_orders",
            callee_file="orders/service.py",
            callee_symbol="sync_all",
            call_kind=CALL_KIND_LOCAL,
        )
    )
    scan.call_graph = graph

    flows = build_flow_candidates(scan, max_flows=5)

    assert any(flow.entry_kind == "runtime_task" for flow in flows)


def test_flow_candidates_capture_side_effects() -> None:
    scan = _scan_base()
    scan.endpoint_bundles = [
        EndpointBundle(
            endpoint_family="orders",
            methods_paths=["POST /orders"],
            handler_file="orders/handlers.py",
            handler_symbols=["create_order"],
        )
    ]
    _add_symbol(scan, "orders/handlers.py", "create_order")

    graph = CallGraph()
    graph.add_edge(
        CallEdge(
            caller_file="orders/handlers.py",
            caller_symbol="create_order",
            callee_file="",
            callee_symbol="sync_orders",
            call_kind=CALL_KIND_CELERY,
        )
    )
    scan.call_graph = graph

    flows = build_flow_candidates(scan, max_flows=5)

    assert flows
    assert any("celery_dispatch:sync_orders" == entry for entry in flows[0].side_effects)
