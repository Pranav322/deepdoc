"""Slice B: deterministic semantic refinement of planning-unit boundaries.

Covers conservative unclaimed-file adoption and compact, bounded cross-unit
boundary stubs — built only from existing call-graph/topology/flow evidence,
no LLM calls, no GitNexus.
"""

from __future__ import annotations

import pytest

from deepdoc.call_graph import CallEdge, CallGraph
from deepdoc.planner.flow_candidates import EntryPoint, FlowCandidate
from deepdoc.planner.partitioning import PlanningUnit, build_planning_units
from deepdoc.planner.topology import TopologyCluster, TopologyMap
from deepdoc.planner.unit_boundaries import (
    BoundaryStub,
    compute_boundary_stubs,
    format_boundary_stubs,
    local_call_edges,
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
    # `core` held nothing but this helper, so refinement empties it and the
    # zero-file unit is dropped rather than planned.
    assert "core" not in by_slug
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
    assert "services/payments" not in repr(stub)
    assert ".py" not in repr(stub)
    assert stub.remote_unit == "payments"
    # Only aggregate flow evidence survives — never the flow's ID or title.
    assert "flow" in stub.evidence_kinds


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
    )
    import dataclasses

    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        stub.remote_unit = "orders"


def test_refinement_and_stub_computation_are_deterministic_under_shuffled_input() -> None:
    """Every collection refinement reads is an insertion-ordered Python
    container built by upstream scanners, whose order is not contractual.
    Two semantically identical scans whose file summaries, service map, call
    edges, topology clusters/cluster map, endpoint bundles, and flow
    candidates were each independently shuffled must produce byte-identical
    `(slug, files, boundary stubs)` output."""
    import random

    orders = "services/orders/app.py"
    payments = "services/payments/app.py"
    helper = "shared/orders_helper.py"
    files = [orders, payments, helper]
    services = [(orders, "orders"), (payments, "payments")]
    edges = [
        (orders, "handle", helper, "helper"),
        (orders, "handle2", helper, "helper2"),
        (orders, "handle3", helper, "helper3"),
        (orders, "handle", payments, "charge"),
    ]
    clusters = [
        TopologyCluster(
            cluster_id=cid,
            entry_files=[entry],
            entry_symbols=["handle"],
            all_files=[entry],
            min_depth=0,
            max_depth=1,
            side_effects=[],
            external_calls=[],
            shared_dep_files=[],
            avg_indegree=1.0,
            is_foundational=False,
        )
        for cid, entry in (("orders", orders), ("payments", payments))
    ]
    cluster_map = [(orders, "orders"), (payments, "payments"), (helper, "orders")]
    bundles = [
        _endpoint_bundle("orders", orders, [helper]),
        _endpoint_bundle("payments", payments, []),
    ]
    flows = [
        FlowCandidate(
            flow_id=flow_id,
            title=f"{flow_id} title",
            entry_kind="http",
            entry_points=[],
            involved_files=list(involved),
        )
        # Several co-occurring flows so the aggregate flow score is built
        # from more than one hit — a shuffled input order would otherwise
        # show up in the accumulated total.
        for flow_id, involved in (
            ("checkout", (orders, payments)),
            ("refund", (payments, orders)),
            ("dispute", (orders, payments)),
            ("settlement", (payments, orders)),
        )
    ]

    def _build(seed: int) -> list[tuple[str, tuple[str, ...], tuple]]:
        rnd = random.Random(seed)

        def rng(items):
            """One independently shuffled copy per collection (the same RNG
            advances between calls, so no two collections share a
            permutation)."""
            shuffled = list(items)
            rnd.shuffle(shuffled)
            return shuffled

        graph = CallGraph()
        for caller_file, caller_symbol, callee_file, callee_symbol in rng(edges):
            graph.add_edge(
                CallEdge(
                    caller_file=caller_file,
                    caller_symbol=caller_symbol,
                    callee_file=callee_file,
                    callee_symbol=callee_symbol,
                )
            )
        scan = _scan(
            file_summaries={f: "s" for f in rng(files)},
            file_services=dict(rng(services)),
            call_graph=graph,
            endpoint_bundles=rng(bundles),
            flow_candidates=rng(flows),
            topology_map=TopologyMap(
                clusters=rng(clusters),
                file_indegree={},
                file_call_depth={},
                file_cluster_id=dict(rng(cluster_map)),
                foundational_files=[],
            ),
        )
        refined = refine_unit_ownership(scan, build_planning_units(scan))
        baseline = {u.slug: frozenset(u.files) for u in refined}
        return [
            (
                u.slug,
                u.files,
                compute_boundary_stubs(scan, baseline[u.slug], u.slug, baseline),
            )
            for u in refined
        ]

    # Seed pair chosen so *every* one of the seven shuffled collections
    # genuinely lands in a different order between the two builds.
    a, b = _build(1), _build(36)

    assert a == b
    # ...and the shuffled evidence actually drove a decision worth locking:
    # the helper was adopted, and the two services see each other.
    orders_row = next(row for row in a if row[0] == "orders")
    assert helper in orders_row[1]
    assert [stub.remote_unit for stub in orders_row[2]] == ["payments"]
    assert "flow" in orders_row[2][0].evidence_kinds
    # Four co-occurring flows, each weighted `_STUB_FLOW_WEIGHT`, plus the
    # call edges — a stable aggregate regardless of input order.
    assert orders_row[2][0].score == pytest.approx(
        orders_row[2][0].call_count + 4 * 3.0
    )


def test_flow_evidence_never_leaks_a_remote_path_even_from_a_hostile_title() -> None:
    """A flow title/ID is arbitrary upstream text — `endpoint_family` can be
    a route like `POST /orders/process`, and nothing stops a scanner (or a
    malicious repo) from putting a remote file path in it. No such string
    may reach a `BoundaryStub` or the local prompt, so no flow-derived
    string is carried at all."""
    scan = _scan(
        call_graph=_call_graph(
            ("services/orders/app.py", "handle", "services/payments/app.py", "charge"),
        ),
        flow_candidates=[
            FlowCandidate(
                flow_id="services/payments/app.py-flow",
                title="Remote file services/payments/app.py",
                entry_kind="http",
                entry_points=[],
                involved_files=["services/orders/app.py", "services/payments/app.py"],
            ),
            FlowCandidate(
                flow_id="checkout",
                title=r"C:\remote\payments\app.py",
                entry_kind="http",
                entry_points=[],
                involved_files=["services/orders/app.py", "services/payments/app.py"],
            ),
        ],
    )
    baseline = {
        "orders": frozenset({"services/orders/app.py"}),
        "payments": frozenset({"services/payments/app.py"}),
    }

    stubs = compute_boundary_stubs(scan, baseline["orders"], "orders", baseline)
    rendered = format_boundary_stubs(stubs)

    assert len(stubs) == 1
    for haystack in (repr(stubs[0]), rendered):
        assert "payments/app" not in haystack
        assert "services/" not in haystack
        assert "\\" not in haystack
        assert ".py" not in haystack
    # The flow co-occurrence still counts as aggregate evidence.
    assert "flow" in stubs[0].evidence_kinds


def _endpoint_bundle(family: str, handler_file: str, evidence_files: list[str]):
    from deepdoc.scanner.common import EndpointBundle, EvidenceUnit

    return EndpointBundle(
        endpoint_family=family,
        methods_paths=[f"POST /{family}"],
        handler_file=handler_file,
        handler_symbols=["handle"],
        evidence=[
            EvidenceUnit(file_path=f, role="service") for f in evidence_files
        ],
    )


def _two_service_scan(**overrides):
    base = dict(
        file_summaries={
            "services/orders/app.py": "s",
            "services/payments/app.py": "s",
            "shared/helper.py": "s",
        },
        file_services={
            "services/orders/app.py": "orders",
            "services/payments/app.py": "payments",
        },
    )
    base.update(overrides)
    return _scan(**base)


def test_endpoint_bundle_evidence_alone_can_adopt_an_unclaimed_helper() -> None:
    """Endpoint bundles are required to be an *independent* deterministic
    signal: a helper that only ever shows up as bounded evidence for one
    service's endpoint must join that service even with no call graph, no
    topology, and no flow candidates at all."""
    scan = _two_service_scan(
        endpoint_bundles=[
            _endpoint_bundle("orders", "services/orders/app.py", ["shared/helper.py"]),
        ],
    )
    units = build_planning_units(scan)

    refined = {u.slug: u.files for u in refine_unit_ownership(scan, units)}

    assert "shared/helper.py" in refined["orders"]
    assert "shared/helper.py" not in refined.get("core", ())


def test_endpoint_evidence_from_two_services_leaves_the_helper_in_core() -> None:
    """Equivalent endpoint evidence from two named services is ambiguous —
    the helper is shared infrastructure and stays unclaimed."""
    scan = _two_service_scan(
        endpoint_bundles=[
            _endpoint_bundle("orders", "services/orders/app.py", ["shared/helper.py"]),
            _endpoint_bundle(
                "payments", "services/payments/app.py", ["shared/helper.py"]
            ),
        ],
    )
    units = build_planning_units(scan)

    refined = {u.slug: u.files for u in refine_unit_ownership(scan, units)}

    assert "shared/helper.py" in refined["core"]
    assert "shared/helper.py" not in refined["orders"]
    assert "shared/helper.py" not in refined["payments"]


def test_endpoint_bundle_spanning_two_named_services_never_adopts() -> None:
    """A bundle whose own evidence already belongs to two different named
    services is not anchored to one unit — it must not vote at all."""
    scan = _two_service_scan(
        endpoint_bundles=[
            _endpoint_bundle(
                "orders",
                "services/orders/app.py",
                ["services/payments/app.py", "shared/helper.py"],
            ),
        ],
    )
    units = build_planning_units(scan)

    refined = {u.slug: u.files for u in refine_unit_ownership(scan, units)}

    assert "shared/helper.py" in refined["core"]


def test_runtime_task_producer_evidence_can_adopt_an_unclaimed_file() -> None:
    """Runtime evidence is the second independent signal: `RuntimeTask`
    carries bounded `producer_files`, so a task anchored to exactly one
    named unit can adopt its producer.

    Schedulers (`invoked_targets`) and realtime consumers expose no bounded
    dependent *file* list in the live model, so they intentionally
    contribute nothing — see `_runtime_affinity`."""
    from deepdoc.scanner.common import RuntimeScan, RuntimeTask

    scan = _two_service_scan(
        file_summaries={
            "services/orders/app.py": "s",
            "services/payments/app.py": "s",
            "shared/producer.py": "s",
        },
        runtime_scan=RuntimeScan(
            tasks=[
                RuntimeTask(
                    name="reindex",
                    file_path="services/orders/app.py",
                    runtime_kind="celery",
                    producer_files=["shared/producer.py"],
                )
            ]
        ),
    )
    units = build_planning_units(scan)

    refined = {u.slug: u.files for u in refine_unit_ownership(scan, units)}

    assert "shared/producer.py" in refined["orders"]


def test_endpoint_evidence_never_overrides_explicit_service_ownership() -> None:
    """A file `file_services` assigns is a hard anchor — endpoint evidence
    from another service cannot pull it across."""
    scan = _two_service_scan(
        endpoint_bundles=[
            _endpoint_bundle(
                "orders", "services/orders/app.py", ["services/payments/app.py"]
            ),
        ],
    )
    units = build_planning_units(scan)

    refined = {u.slug: u.files for u in refine_unit_ownership(scan, units)}

    assert refined["payments"] == ("services/payments/app.py",)
    assert "services/payments/app.py" not in refined["orders"]


def test_topology_shared_dependency_is_never_forced_into_one_service() -> None:
    """`TopologyCluster.shared_dep_files` are foundational by construction
    (topology only records callees inside `foundational_set`). Even with
    endpoint evidence from one service on top, a shared dependency stays
    core."""
    scan = _two_service_scan(
        endpoint_bundles=[
            _endpoint_bundle("orders", "services/orders/app.py", ["shared/helper.py"]),
        ],
        call_graph=_call_graph(
            ("services/orders/app.py", "handle", "shared/helper.py", "util"),
            ("services/payments/app.py", "charge", "shared/helper.py", "util"),
        ),
        topology_map=TopologyMap(
            clusters=[
                TopologyCluster(
                    cluster_id="orders",
                    entry_files=["services/orders/app.py"],
                    entry_symbols=["handle"],
                    all_files=["services/orders/app.py"],
                    min_depth=0,
                    max_depth=0,
                    side_effects=[],
                    external_calls=[],
                    shared_dep_files=["shared/helper.py"],
                    avg_indegree=0.0,
                    is_foundational=False,
                ),
                TopologyCluster(
                    cluster_id="payments",
                    entry_files=["services/payments/app.py"],
                    entry_symbols=["charge"],
                    all_files=["services/payments/app.py"],
                    min_depth=0,
                    max_depth=0,
                    side_effects=[],
                    external_calls=[],
                    shared_dep_files=["shared/helper.py"],
                    avg_indegree=0.0,
                    is_foundational=False,
                ),
            ],
            file_indegree={"shared/helper.py": 2},
            file_call_depth={},
            file_cluster_id={
                "services/orders/app.py": "orders",
                "services/payments/app.py": "payments",
                "shared/helper.py": "foundational",
            },
            foundational_files=["shared/helper.py"],
        ),
    )
    units = build_planning_units(scan)

    refined = {u.slug: u.files for u in refine_unit_ownership(scan, units)}

    assert "shared/helper.py" in refined["core"]
    assert "shared/helper.py" not in refined["orders"]


def test_boundary_stub_never_carries_a_slugified_remote_path() -> None:
    """`FlowCandidate.flow_id` is often produced by slugifying upstream text,
    so a remote source path can arrive already stripped of `/` and `.` —
    `services-payments-private-handler-py-flow`. No character-level sanitizer
    can tell that apart from a legitimate identifier, so no flow-derived
    string may reach a `BoundaryStub` or the local prompt at all."""
    scan = _scan(
        call_graph=_call_graph(
            ("services/orders/app.py", "handle", "services/payments/app.py", "charge"),
        ),
        flow_candidates=[
            FlowCandidate(
                flow_id=flow_id,
                title=f"{flow_id} title",
                entry_kind="http",
                entry_points=[],
                involved_files=["services/orders/app.py", "services/payments/app.py"],
            )
            for flow_id in (
                "services-payments-private-handler-py-flow",
                "services-payments-secret-config-flow",
            )
        ],
    )
    baseline = {
        "orders": frozenset({"services/orders/app.py"}),
        "payments": frozenset({"services/payments/app.py"}),
    }

    stubs = compute_boundary_stubs(scan, baseline["orders"], "orders", baseline)
    rendered = format_boundary_stubs(stubs)

    assert len(stubs) == 1
    for haystack in (repr(stubs[0]), rendered):
        for leaked in (
            "services-payments-private-handler-py-flow",
            "services-payments-secret-config-flow",
            "private-handler",
            "secret-config",
            "-py-",
            "services-",
        ):
            assert leaked not in haystack
    # The aggregate flow evidence still survives — only the labels are gone.
    assert "flow" in stubs[0].evidence_kinds


def test_service_literally_named_core_keeps_its_explicit_files() -> None:
    """A repo where every file is claimed and one service happens to be named
    `core` must not have that service treated as the unclaimed bucket. The
    unclaimed unit is identified by `PlanningUnit.unclaimed`, never by its
    slug, so a `file_services` anchor stays a hard anchor."""
    scan = _scan(
        file_summaries={
            "core/util.py": "s",
            "services/orders/app.py": "s",
            "services/payments/app.py": "s",
        },
        file_services={
            "core/util.py": "core",
            "services/orders/app.py": "orders",
            "services/payments/app.py": "payments",
        },
        # Heavy one-sided affinity that would otherwise drag the file away.
        call_graph=_call_graph(
            ("services/orders/app.py", "handle", "core/util.py", "helper"),
            ("services/orders/app.py", "handle2", "core/util.py", "helper2"),
            ("services/orders/app.py", "handle3", "core/util.py", "helper3"),
        ),
    )
    units = build_planning_units(scan)
    assert not any(u.unclaimed for u in units)

    refined = refine_unit_ownership(scan, units)
    by_slug = {u.slug: u for u in refined}

    assert by_slug["core"].files == ("core/util.py",)
    assert "core/util.py" not in by_slug["orders"].files
    assert "core/util.py" not in by_slug["payments"].files


def test_unclaimed_unit_is_dropped_when_every_file_is_reassigned() -> None:
    """When refinement finds a confident owner for every unclaimed file the
    emptied unit is dropped, not planned with zero files — an empty unit still
    reserves a page budget and burns LLM calls on an empty sub-scan."""
    scan = _scan(
        file_summaries={
            "services/orders/app.py": "s",
            "services/payments/app.py": "s",
            "shared/orders_util.py": "s",
            "shared/payments_util.py": "s",
        },
        file_services={
            "services/orders/app.py": "orders",
            "services/payments/app.py": "payments",
        },
        call_graph=_call_graph(
            ("services/orders/app.py", "a", "shared/orders_util.py", "x"),
            ("services/orders/app.py", "b", "shared/orders_util.py", "y"),
            ("services/orders/app.py", "c", "shared/orders_util.py", "z"),
            ("services/payments/app.py", "a", "shared/payments_util.py", "x"),
            ("services/payments/app.py", "b", "shared/payments_util.py", "y"),
            ("services/payments/app.py", "c", "shared/payments_util.py", "z"),
        ),
    )
    units = build_planning_units(scan)
    assert any(u.unclaimed for u in units)

    refined = refine_unit_ownership(scan, units)
    by_slug = {u.slug: u.files for u in refined}

    assert all(u.files for u in refined)
    assert not any(u.unclaimed for u in refined)
    assert "shared/orders_util.py" in by_slug["orders"]
    assert "shared/payments_util.py" in by_slug["payments"]


def test_cluster_comembership_alone_never_moves_a_file() -> None:
    """Topology clustering assigns leftover files by best-guess and finally to
    the biggest cluster, so cluster co-membership can only corroborate real
    evidence — on its own it must never move a file out of `core`."""
    scan = _two_service_scan(
        topology_map=TopologyMap(
            clusters=[],
            file_indegree={},
            file_call_depth={},
            file_cluster_id={
                "services/orders/app.py": "orders",
                # Same cluster as orders, but with zero call, endpoint or
                # runtime evidence to back it up.
                "shared/helper.py": "orders",
            },
            foundational_files=[],
        ),
    )
    units = build_planning_units(scan)

    refined = {u.slug: u.files for u in refine_unit_ownership(scan, units)}

    assert "shared/helper.py" in refined["core"]
    assert "shared/helper.py" not in refined["orders"]


def test_precomputed_call_edges_match_and_are_actually_consulted() -> None:
    """`plan_docs` derives the local call-edge list once and threads it through
    refinement and every boundary-stub call rather than re-serializing the whole
    graph per unit and per retry-split. Passing it must be equivalent to letting
    the callee derive it — and must genuinely be used, not ignored."""
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
    edges = local_call_edges(scan)
    assert edges, "expected local call edges for this scan"

    # Equivalent to deriving it internally...
    assert refine_unit_ownership(scan, units, call_edges=edges) == refine_unit_ownership(
        scan, units
    )
    # ...and genuinely consulted: with no edges the call-edge-only evidence
    # disappears and nothing is adopted.
    assert refine_unit_ownership(scan, units, call_edges=[]) == units

    baseline = {u.slug: frozenset(u.files) for u in units}
    own = frozenset(scan.file_services)
    assert compute_boundary_stubs(
        scan, own, "orders", baseline, call_edges=edges
    ) == compute_boundary_stubs(scan, own, "orders", baseline)
    assert compute_boundary_stubs(scan, own, "orders", baseline, call_edges=()) == ()


def test_cluster_comembership_plus_one_call_edge_still_adopts() -> None:
    """Guards the other direction of the corroborating-only weight: cluster
    co-membership must still be *meaningful* evidence, so pairing it with a
    single real call edge is enough to reach the minimum affinity score."""
    scan = _two_service_scan(
        call_graph=_call_graph(
            ("services/orders/app.py", "handle", "shared/helper.py", "util"),
        ),
        topology_map=TopologyMap(
            clusters=[],
            file_indegree={},
            file_call_depth={},
            file_cluster_id={
                "services/orders/app.py": "orders",
                "shared/helper.py": "orders",
            },
            foundational_files=[],
        ),
    )
    units = build_planning_units(scan)

    refined = {u.slug: u.files for u in refine_unit_ownership(scan, units)}

    assert "shared/helper.py" in refined["orders"]
    assert "core" not in refined
