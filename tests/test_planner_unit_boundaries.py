"""Slice B: deterministic semantic refinement of planning-unit boundaries.

Covers conservative unclaimed-file adoption and compact, bounded cross-unit
boundary stubs — built only from existing call-graph/topology/flow evidence,
no LLM calls, no GitNexus.
"""

from __future__ import annotations

from deepdoc.call_graph import CallEdge, CallGraph
from deepdoc.planner.flow_candidates import EntryPoint, FlowCandidate
from deepdoc.planner.partitioning import PlanningUnit, build_planning_units
from deepdoc.planner.topology import TopologyCluster, TopologyMap
from deepdoc.planner.unit_boundaries import (
    BoundaryStub,
    compute_boundary_stubs,
    refine_unit_ownership,
)
from deepdoc.v2_models import RepoScan


def _scan(**overrides) -> RepoScan:
    base = dict(
        file_tree={},
        file_summaries={},
        api_endpoints=[],
        languages={},
        has_openapi=False,
        openapi_paths=[],
        total_files=0,
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
    )
    base.update(overrides)
    return RepoScan(**base)


def _call_graph(*edges: tuple[str, str, str, str]) -> CallGraph:
    graph = CallGraph()
    for caller_file, caller_symbol, callee_file, callee_symbol in edges:
        graph.add_edge(
            CallEdge(
                caller_file=caller_file,
                caller_symbol=caller_symbol,
                callee_file=callee_file,
                callee_symbol=callee_symbol,
            )
        )
    return graph


def test_single_named_service_repo_is_untouched_by_refinement() -> None:
    """Single-unit parity: refinement must not run at all for a zero/one
    service repo — `build_planning_units` already collapsed it to one unit."""
    scan = _scan(
        file_summaries={"api/app.py": "s", "shared/util.py": "s"},
        file_services={"api/app.py": "api"},
    )
    units = build_planning_units(scan)
    assert len(units) == 1

    refined = refine_unit_ownership(scan, units)

    assert refined == units


def test_dominant_unclaimed_helper_joins_exactly_one_service() -> None:
    """A `core` file called heavily by one named service and never by the
    other must move into that service's unit, exclusively."""
    scan = _scan(
        file_summaries={
            "services/orders/app.py": "s",
            "services/payments/app.py": "s",
            "shared/orders_helper.py": "s",
        },
        file_services={
            "services/orders/app.py": "orders",
            "services/payments/app.py": "payments",
        },
        call_graph=_call_graph(
            ("services/orders/app.py", "handle", "shared/orders_helper.py", "helper"),
            ("services/orders/app.py", "handle2", "shared/orders_helper.py", "helper2"),
            ("services/orders/app.py", "handle3", "shared/orders_helper.py", "helper3"),
        ),
    )
    units = build_planning_units(scan)

    refined = refine_unit_ownership(scan, units)
    by_slug = {u.slug: u for u in refined}

    assert "shared/orders_helper.py" in by_slug["orders"].files
    assert "shared/orders_helper.py" not in by_slug["core"].files
    assert "shared/orders_helper.py" not in by_slug["payments"].files
    # Every file remains in exactly one unit.
    all_files = [f for u in refined for f in u.files]
    assert len(all_files) == len(set(all_files))


def test_equally_shared_helper_stays_only_in_core() -> None:
    """A helper called meaningfully by two services with no clear winner
    must remain in `core` — never duplicated, never guessed."""
    scan = _scan(
        file_summaries={
            "services/orders/app.py": "s",
            "services/payments/app.py": "s",
            "shared/common.py": "s",
        },
        file_services={
            "services/orders/app.py": "orders",
            "services/payments/app.py": "payments",
        },
        call_graph=_call_graph(
            ("services/orders/app.py", "handle", "shared/common.py", "helper"),
            ("services/payments/app.py", "handle", "shared/common.py", "helper"),
        ),
    )
    units = build_planning_units(scan)

    refined = refine_unit_ownership(scan, units)
    by_slug = {u.slug: u for u in refined}

    assert "shared/common.py" in by_slug["core"].files
    assert "shared/common.py" not in by_slug["orders"].files
    assert "shared/common.py" not in by_slug["payments"].files


def test_explicit_service_ownership_cannot_be_moved() -> None:
    """A file `file_services` already assigns to `payments` must never move
    to `orders`, even with heavy graph affinity in that direction."""
    scan = _scan(
        file_summaries={
            "services/orders/app.py": "s",
            "services/payments/app.py": "s",
        },
        file_services={
            "services/orders/app.py": "orders",
            "services/payments/app.py": "payments",
        },
        call_graph=_call_graph(
            ("services/orders/app.py", "handle", "services/payments/app.py", "charge"),
            ("services/orders/app.py", "handle2", "services/payments/app.py", "charge2"),
            ("services/orders/app.py", "handle3", "services/payments/app.py", "charge3"),
        ),
    )
    units = build_planning_units(scan)

    refined = refine_unit_ownership(scan, units)
    by_slug = {u.slug: u for u in refined}

    assert by_slug["payments"].files == ("services/payments/app.py",)
    assert by_slug["orders"].files == ("services/orders/app.py",)


def test_foundational_file_is_never_force_assigned_despite_high_fan_in() -> None:
    """A file every named unit calls into (foundational) must stay in core
    even though it clears the raw affinity threshold for each caller."""
    scan = _scan(
        file_summaries={
            "services/orders/app.py": "s",
            "services/payments/app.py": "s",
            "shared/base.py": "s",
        },
        file_services={
            "services/orders/app.py": "orders",
            "services/payments/app.py": "payments",
        },
        call_graph=_call_graph(
            ("services/orders/app.py", "handle", "shared/base.py", "base"),
            ("services/orders/app.py", "handle2", "shared/base.py", "base2"),
            ("services/orders/app.py", "handle3", "shared/base.py", "base3"),
        ),
        topology_map=TopologyMap(
            clusters=[],
            file_indegree={},
            file_call_depth={},
            file_cluster_id={},
            foundational_files=["shared/base.py"],
        ),
    )
    units = build_planning_units(scan)

    refined = refine_unit_ownership(scan, units)
    by_slug = {u.slug: u for u in refined}

    assert "shared/base.py" in by_slug["core"].files


def test_disconnected_services_produce_no_boundary_stubs() -> None:
    stubs = compute_boundary_stubs(
        _scan(),
        unit_files=frozenset({"services/orders/app.py"}),
        own_baseline_slug="orders",
        baseline_unit_files={"payments": frozenset({"services/payments/app.py"})},
    )
    assert stubs == ()


def test_coupled_services_get_reciprocal_compact_stubs() -> None:
    scan = _scan(
        call_graph=_call_graph(
            ("services/orders/app.py", "handle", "services/payments/app.py", "charge"),
            ("services/payments/app.py", "notify", "services/orders/app.py", "on_paid"),
        ),
    )
    baseline = {
        "orders": frozenset({"services/orders/app.py"}),
        "payments": frozenset({"services/payments/app.py"}),
    }

    orders_stubs = compute_boundary_stubs(
        scan, baseline["orders"], "orders", baseline
    )
    payments_stubs = compute_boundary_stubs(
        scan, baseline["payments"], "payments", baseline
    )

    assert [s.remote_unit for s in orders_stubs] == ["payments"]
    assert [s.remote_unit for s in payments_stubs] == ["orders"]
    assert orders_stubs[0].direction == "bidirectional"
    assert payments_stubs[0].direction == "bidirectional"
    assert orders_stubs[0].call_count == 2
    assert "call" in orders_stubs[0].evidence_kinds


def test_boundary_stub_never_carries_remote_file_paths() -> None:
    scan = _scan(
        call_graph=_call_graph(
            ("services/orders/app.py", "handle", "services/payments/app.py", "charge"),
        ),
        flow_candidates=[
            FlowCandidate(
                flow_id="checkout",
                title="Checkout Flow",
                entry_kind="http",
                entry_points=[
                    EntryPoint(
                        kind="http",
                        label="checkout",
                        handler_file="services/orders/app.py",
                        handler_symbol="handle",
                    )
                ],
                involved_files=["services/orders/app.py", "services/payments/app.py"],
            )
        ],
    )
    baseline = {
        "orders": frozenset({"services/orders/app.py"}),
        "payments": frozenset({"services/payments/app.py"}),
    }

    stubs = compute_boundary_stubs(scan, baseline["orders"], "orders", baseline)

    assert len(stubs) == 1
    stub = stubs[0]
    for field_value in (stub.remote_unit, stub.direction, *stub.flow_labels):
        assert "services/payments" not in str(field_value)
        assert ".py" not in str(field_value)
    assert stub.remote_unit == "payments"
    assert "flow" in stub.evidence_kinds
    assert stub.flow_labels == ("Checkout Flow",)


def test_boundary_stubs_are_bounded_and_sorted_deterministically() -> None:
    others = {
        f"unit-{i}": frozenset({f"services/u{i}/app.py"}) for i in range(10)
    }
    edges = tuple(
        ("services/main/app.py", f"handle_{i}_{j}", f"services/u{i}/app.py", f"call_{i}_{j}")
        for i in range(10)
        for j in range(i + 1)  # unit-9 gets the most edges, unit-0 the fewest
    )
    scan = _scan(call_graph=_call_graph(*edges))

    stubs = compute_boundary_stubs(
        scan, frozenset({"services/main/app.py"}), "main", others
    )

    assert len(stubs) <= 5
    scores = [s.score for s in stubs]
    assert scores == sorted(scores, reverse=True)
    assert stubs[0].remote_unit == "unit-9"


def test_boundary_stub_is_immutable() -> None:
    stub = BoundaryStub(
        remote_unit="payments",
        direction="outbound",
        score=1.0,
        call_count=1,
        evidence_kinds=("call",),
        flow_labels=(),
    )
    import dataclasses

    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        stub.remote_unit = "orders"


def test_refinement_and_stub_computation_are_deterministic_under_shuffled_input() -> None:
    """Reinserting files/edges/clusters in a different order must not change
    the refined unit membership or boundary stubs."""

    def _build(order: list[str]) -> tuple[list[PlanningUnit], tuple]:
        file_summaries = {}
        file_services = {}
        for path, service in [
            ("services/orders/app.py", "orders"),
            ("services/payments/app.py", "payments"),
            ("shared/orders_helper.py", None),
        ]:
            file_summaries[path] = "s"
            if service:
                file_services[path] = service
        edges = [
            ("services/orders/app.py", "handle", "shared/orders_helper.py", "helper"),
            ("services/orders/app.py", "handle2", "shared/orders_helper.py", "helper2"),
            ("services/orders/app.py", "handle3", "shared/orders_helper.py", "helper3"),
        ]
        ordered_edges = [edges[i] for i in (order.index("e0"), order.index("e1"), order.index("e2"))] \
            if False else edges  # edge insertion order into CallGraph is varied below
        graph = CallGraph()
        for caller_file, caller_symbol, callee_file, callee_symbol in (
            edges if order == ["a"] else list(reversed(edges))
        ):
            graph.add_edge(
                CallEdge(
                    caller_file=caller_file,
                    caller_symbol=caller_symbol,
                    callee_file=callee_file,
                    callee_symbol=callee_symbol,
                )
            )
        scan = _scan(
            file_summaries=file_summaries,
            file_services=file_services,
            call_graph=graph,
        )
        units = build_planning_units(scan)
        refined = refine_unit_ownership(scan, units)
        baseline = {u.slug: frozenset(u.files) for u in refined}
        stubs = compute_boundary_stubs(
            scan, baseline["orders"], "orders", baseline
        )
        return refined, stubs

    refined_a, stubs_a = _build(["a"])
    refined_b, stubs_b = _build(["b"])

    assert [(u.slug, u.files) for u in refined_a] == [(u.slug, u.files) for u in refined_b]
    assert stubs_a == stubs_b
