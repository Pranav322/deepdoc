from __future__ import annotations

from unittest.mock import patch

from deepdoc.call_graph import CallGraph
from deepdoc.llm.token_budget import ModelCapabilities
from deepdoc.planner.partitioning import (
    PlanningUnit,
    bound_planning_unit,
    build_planning_units,
    make_sub_scan,
    split_planning_unit,
    unit_likely_fits_budget,
)
from deepdoc.planner.flow_candidates import EntryPoint, FlowCandidate
from deepdoc.planner.topology import TopologyCluster, TopologyMap
from deepdoc.scanner.common import (
    ArtifactScan,
    ConfigImpact,
    DatabaseGroup,
    DatabaseScan,
    DebugSignal,
    EndpointBundle,
    GraphQLInterface,
    IntegrationIdentity,
    KnexArtifact,
    ModelFileInfo,
    RuntimeScan,
    RuntimeTask,
)
from deepdoc.v2_models import RepoScan


def _llm(context_window_tokens: int = 128000, output_reserve_tokens: int = 16000):
    from types import SimpleNamespace

    return SimpleNamespace(
        capabilities=ModelCapabilities(
            model="test",
            capability_model="gpt-4o-mini",
            context_window_tokens=context_window_tokens,
            max_output_tokens=min(output_reserve_tokens, 16000),
            source="test",
        ),
        output_reserve_tokens=output_reserve_tokens,
    )


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


def test_files_grouped_by_service_and_unclaimed_go_to_core() -> None:
    scan = _scan(
        file_summaries={
            "services/orders/app.py": "s",
            "services/orders/db.py": "s",
            "services/payments/app.py": "s",
            "shared/util.py": "s",
        },
        file_services={
            "services/orders/app.py": "orders",
            "services/orders/db.py": "orders",
            "services/payments/app.py": "payments",
        },
    )

    units = build_planning_units(scan)
    by_slug = {u.slug: u for u in units}

    assert set(by_slug) == {"orders", "payments", "core"}
    assert by_slug["orders"].files == ("services/orders/app.py", "services/orders/db.py")
    assert by_slug["payments"].files == ("services/payments/app.py",)
    assert by_slug["core"].files == ("shared/util.py",)


def test_zero_or_one_service_yields_single_unit() -> None:
    scan = _scan(file_summaries={"a.py": "s", "b.py": "s"})

    units = build_planning_units(scan)

    assert len(units) == 1
    assert units[0].slug == "core"
    assert set(units[0].files) == {"a.py", "b.py"}


def test_single_named_service_with_shared_files_stays_single_unit() -> None:
    """A lone named service plus shared/unclaimed files must NOT enter the
    multi-unit path. Pre-Slice-A such a repo planned as one unit; splitting it
    into api/ + core/ would namespace every page and break every route. Only
    2+ distinct named services should force bounded multi-unit planning."""
    scan = _scan(
        file_summaries={
            "services/api/app.py": "s",
            "services/api/db.py": "s",
            "shared/util.py": "s",
            "config/settings.py": "s",
        },
        file_services={
            "services/api/app.py": "api",
            "services/api/db.py": "api",
        },
    )

    units = build_planning_units(scan)

    assert len(units) == 1, f"one-service+shared repo must collapse to one unit, got {[u.slug for u in units]}"
    assert units[0].slug == "api"
    assert set(units[0].files) == {
        "services/api/app.py",
        "services/api/db.py",
        "shared/util.py",
        "config/settings.py",
    }


def test_unit_order_and_ids_are_deterministic_regardless_of_dict_order() -> None:
    scan_a = _scan(
        file_summaries={"z/a.py": "s", "a/a.py": "s", "m/a.py": "s"},
        file_services={"z/a.py": "zeta", "a/a.py": "alpha", "m/a.py": "mid"},
    )
    # Same data, inserted in a different dict order.
    scan_b = _scan(
        file_summaries={"m/a.py": "s", "z/a.py": "s", "a/a.py": "s"},
        file_services={"m/a.py": "mid", "a/a.py": "alpha", "z/a.py": "zeta"},
    )

    units_a = [u.slug for u in build_planning_units(scan_a)]
    units_b = [u.slug for u in build_planning_units(scan_b)]

    assert units_a == units_b == ["alpha", "mid", "zeta"]


def test_duplicate_slugs_after_slugification_are_disambiguated() -> None:
    scan = _scan(
        file_summaries={"a/x.py": "s", "b/x.py": "s"},
        file_services={"a/x.py": "Order Service", "b/x.py": "order_service"},
    )

    units = build_planning_units(scan)
    slugs = sorted(u.slug for u in units)

    assert slugs == ["order-service", "order-service-2"]


def test_make_sub_scan_filters_file_scoped_state_without_mutating_source() -> None:
    scan = _scan(
        file_tree={"services/orders": ["app.py"], "services/payments": ["app.py"]},
        file_summaries={
            "services/orders/app.py": "orders summary",
            "services/payments/app.py": "payments summary",
        },
        file_services={
            "services/orders/app.py": "orders",
            "services/payments/app.py": "payments",
        },
        file_line_counts={
            "services/orders/app.py": 10,
            "services/payments/app.py": 20,
        },
        config_files=["services/orders/Dockerfile", "services/payments/Dockerfile"],
        entry_points=["services/orders/app.py", "services/payments/app.py"],
    )
    original_file_summaries = dict(scan.file_summaries)

    units = {u.slug: u for u in build_planning_units(scan)}
    sub = make_sub_scan(scan, units["orders"])

    assert sub.file_summaries == {"services/orders/app.py": "orders summary"}
    assert sub.file_line_counts == {"services/orders/app.py": 10}
    assert sub.config_files == ["services/orders/Dockerfile"]
    assert sub.entry_points == ["services/orders/app.py"]
    assert sub.file_tree == {"services/orders": ["app.py"]}
    # Source scan is untouched.
    assert scan.file_summaries == original_file_summaries
    assert scan.file_tree == {
        "services/orders": ["app.py"],
        "services/payments": ["app.py"],
    }


def test_make_sub_scan_preserves_root_level_file_tree_entries() -> None:
    scan = _scan(
        file_tree={".": ["app.py", "shared.py"], "services/api": ["handler.py"]},
        file_summaries={
            "app.py": "root app",
            "shared.py": "root shared",
            "services/api/handler.py": "api handler",
        },
        file_services={"app.py": "api", "services/api/handler.py": "api"},
    )
    unit = PlanningUnit(
        slug="api",
        label="api",
        files=("app.py", "services/api/handler.py"),
    )

    sub = make_sub_scan(scan, unit)

    assert sub.file_tree == {".": ["app.py"], "services/api": ["handler.py"]}


def test_make_sub_scan_topology_map_has_no_out_of_unit_files() -> None:
    topology = TopologyMap(
        clusters=[
            TopologyCluster(
                cluster_id="orders",
                entry_files=["services/orders/app.py"],
                entry_symbols=[],
                all_files=["services/orders/app.py", "services/orders/db.py"],
                min_depth=0,
                max_depth=1,
                side_effects=[],
                external_calls=[],
                shared_dep_files=[],
                avg_indegree=0.0,
                is_foundational=False,
            ),
            TopologyCluster(
                cluster_id="payments",
                entry_files=["services/payments/app.py"],
                entry_symbols=[],
                all_files=["services/payments/app.py"],
                min_depth=0,
                max_depth=0,
                side_effects=[],
                external_calls=[],
                shared_dep_files=[],
                avg_indegree=0.0,
                is_foundational=False,
            ),
        ],
        file_indegree={
            "services/orders/app.py": 1,
            "services/orders/db.py": 0,
            "services/payments/app.py": 0,
        },
        file_call_depth={
            "services/orders/app.py": 0,
            "services/orders/db.py": 1,
            "services/payments/app.py": 0,
        },
        file_cluster_id={
            "services/orders/app.py": "orders",
            "services/orders/db.py": "orders",
            "services/payments/app.py": "payments",
        },
        foundational_files=[],
    )
    scan = _scan(
        file_summaries={
            "services/orders/app.py": "s",
            "services/orders/db.py": "s",
            "services/payments/app.py": "s",
        },
        file_services={
            "services/orders/app.py": "orders",
            "services/orders/db.py": "orders",
            "services/payments/app.py": "payments",
        },
        topology_map=topology,
    )

    units = {u.slug: u for u in build_planning_units(scan)}
    sub = make_sub_scan(scan, units["orders"])

    assert [c.cluster_id for c in sub.topology_map.clusters] == ["orders"]
    assert sub.topology_map.file_cluster_id == {
        "services/orders/app.py": "orders",
        "services/orders/db.py": "orders",
    }
    assert set(sub.topology_map.file_indegree) == {
        "services/orders/app.py",
        "services/orders/db.py",
    }


def test_split_planning_unit_groups_by_deepest_path_when_it_fits() -> None:
    unit = PlanningUnit(
        slug="big",
        label="big",
        files=tuple(f"big/group{i}/file.py" for i in range(6)),
    )

    parts = split_planning_unit(unit, max_files=1)

    assert len(parts) == 6
    assert all(len(p.files) == 1 for p in parts)
    assert len({p.slug for p in parts}) == 6


def test_split_planning_unit_falls_back_to_numbered_chunks() -> None:
    # All files share one directory — path grouping cannot separate them.
    unit = PlanningUnit(
        slug="flat",
        label="flat",
        files=tuple(f"flat/file{i}.py" for i in range(5)),
    )

    parts = split_planning_unit(unit, max_files=2)

    assert [p.slug for p in parts] == ["flat/part-1", "flat/part-2", "flat/part-3"]
    assert sum(len(p.files) for p in parts) == 5


def test_split_planning_unit_is_noop_under_threshold() -> None:
    unit = PlanningUnit(slug="small", label="small", files=("a.py", "b.py"))

    parts = split_planning_unit(unit, max_files=10)

    assert parts == [unit]


def test_filter_topology_map_trims_overlapping_cluster_files_and_drops_empty_clusters() -> None:
    """A single cluster whose `all_files` spans two units must come out of
    `make_sub_scan` with only this unit's files — the old behavior kept the
    whole cluster object (with the other unit's files still inside
    `all_files`/`entry_files`) as long as *any* file overlapped."""
    topology = TopologyMap(
        clusters=[
            TopologyCluster(
                cluster_id="shared",
                entry_files=["services/orders/app.py", "services/payments/app.py"],
                entry_symbols=[],
                all_files=[
                    "services/orders/app.py",
                    "services/orders/db.py",
                    "services/payments/app.py",
                ],
                min_depth=0,
                max_depth=1,
                side_effects=[],
                external_calls=[],
                shared_dep_files=["services/payments/app.py"],
                avg_indegree=0.0,
                is_foundational=False,
            ),
            TopologyCluster(
                cluster_id="payments-only",
                entry_files=["services/payments/other.py"],
                entry_symbols=[],
                all_files=["services/payments/other.py"],
                min_depth=0,
                max_depth=0,
                side_effects=[],
                external_calls=[],
                shared_dep_files=[],
                avg_indegree=0.0,
                is_foundational=False,
            ),
        ],
        file_indegree={},
        file_call_depth={},
        file_cluster_id={},
        foundational_files=[],
    )
    scan = _scan(
        file_summaries={
            "services/orders/app.py": "s",
            "services/orders/db.py": "s",
            "services/payments/app.py": "s",
            "services/payments/other.py": "s",
        },
        file_services={
            "services/orders/app.py": "orders",
            "services/orders/db.py": "orders",
            "services/payments/app.py": "payments",
            "services/payments/other.py": "payments",
        },
        topology_map=topology,
    )

    units = {u.slug: u for u in build_planning_units(scan)}
    sub = make_sub_scan(scan, units["orders"])

    # The "shared" cluster survives (it owns orders files) but must be
    # trimmed to just this unit's files — no payments file anywhere in it.
    assert [c.cluster_id for c in sub.topology_map.clusters] == ["shared"]
    shared = sub.topology_map.clusters[0]
    assert shared.all_files == ["services/orders/app.py", "services/orders/db.py"]
    assert shared.entry_files == ["services/orders/app.py"]
    assert shared.shared_dep_files == []
    # The cluster that owned nothing but payments files must be dropped
    # entirely, not kept empty or left referencing foreign files.
    assert "payments-only" not in {c.cluster_id for c in sub.topology_map.clusters}


def test_make_sub_scan_drops_call_graph_and_recomputes_languages() -> None:
    """A unit's sub-scan must not carry the global call_graph (a whole-repo
    structure with no per-unit boundary) or the global `languages` counts —
    both would leak other-unit information into local planning."""
    scan = _scan(
        file_summaries={
            "services/orders/app.py": "s",
            "services/payments/app.py": "s",
            "services/payments/worker.go": "s",
        },
        file_services={
            "services/orders/app.py": "orders",
            "services/payments/app.py": "payments",
            "services/payments/worker.go": "payments",
        },
        languages={"python": 2, "go": 1},
        call_graph=CallGraph(),
    )

    units = {u.slug: u for u in build_planning_units(scan)}
    orders_sub = make_sub_scan(scan, units["orders"])
    payments_sub = make_sub_scan(scan, units["payments"])

    assert orders_sub.call_graph is None
    assert payments_sub.call_graph is None
    assert orders_sub.languages == {"python": 1}
    assert payments_sub.languages == {"python": 1, "go": 1}
    # The global scan itself is untouched.
    assert scan.call_graph is not None
    assert scan.languages == {"python": 2, "go": 1}


def test_unit_likely_fits_budget_true_for_small_unit_false_for_huge_unit() -> None:
    small = _scan(file_summaries={"a.py": "handler | lines=10"})
    assert unit_likely_fits_budget(small, _llm()) is True

    huge = _scan(
        file_summaries={
            f"services/orders/module_{i:02d}/component_{i:02d}/handler.py": f"handler #{i} | lines=20"
            for i in range(200)
        }
    )
    tight = _llm(context_window_tokens=1200, output_reserve_tokens=100)
    assert unit_likely_fits_budget(huge, tight) is False


def test_bound_planning_unit_splits_an_oversized_single_service_until_it_fits() -> None:
    """The core regression this fix targets: build_planning_units() alone can
    return exactly one (service or core) unit that is itself too large — the
    old code took that as proof the whole-repo single-unit path was safe.
    bound_planning_unit must keep splitting until every part's real required
    prompts fit, using make_sub_scan (real per-unit content), not raw file
    counts."""
    scan = _scan(
        file_summaries={
            f"services/orders/module_{i:02d}/component_{i:02d}/handler.py": f"handler #{i} | lines=20"
            for i in range(200)
        },
        file_services={
            f"services/orders/module_{i:02d}/component_{i:02d}/handler.py": "orders"
            for i in range(200)
        },
    )
    llm = _llm(context_window_tokens=3000, output_reserve_tokens=100)
    (raw_unit,) = build_planning_units(scan)
    assert raw_unit.slug == "orders"
    assert not unit_likely_fits_budget(make_sub_scan(scan, raw_unit), llm)

    parts = bound_planning_unit(raw_unit, scan, llm)

    assert len(parts) > 1
    assert not any(p.coarse for p in parts)
    assert sorted(f for p in parts for f in p.files) == sorted(scan.file_summaries)
    # No overlap between parts.
    seen: set[str] = set()
    for part in parts:
        assert seen.isdisjoint(part.files)
        seen.update(part.files)
    # Every part's own real required sections must fit the same tight budget.
    for part in parts:
        assert unit_likely_fits_budget(make_sub_scan(scan, part), llm)


def test_bound_planning_unit_marks_an_indivisible_oversized_file_as_coarse() -> None:
    """A single file whose own content still exceeds the budget can't be
    split any further — it must come back explicitly marked `coarse=True`
    rather than looping forever or silently being handed to the LLM anyway."""
    unit = PlanningUnit(slug="giant", label="giant", files=("giant/one_file.py",))
    scan = _scan(file_summaries={"giant/one_file.py": "x" * 50})

    with patch(
        "deepdoc.planner.partitioning.unit_likely_fits_budget", return_value=False
    ):
        parts = bound_planning_unit(unit, scan, _llm())

    assert len(parts) == 1
    assert parts[0].coarse is True
    assert parts[0].files == ("giant/one_file.py",)


def test_make_sub_scan_isolates_every_phase2_record_between_two_services() -> None:
    """A local unit's sub-scan must not see, and cannot claim ownership of,
    another unit's Phase-2 evidence — endpoint bundles, integration
    identities, artifact/database/runtime scans, graphql interfaces, knex
    artifacts, research contexts, the semantic token cache, config impacts,
    debug signals, flow candidates, and service boundaries."""
    orders_file = "services/orders/app.py"
    payments_file = "services/payments/app.py"

    orders_bundle = EndpointBundle(
        endpoint_family="orders", methods_paths=["POST /orders"], handler_file=orders_file, handler_symbols=["create_order"]
    )
    payments_bundle = EndpointBundle(
        endpoint_family="payments", methods_paths=["POST /payments"], handler_file=payments_file, handler_symbols=["charge"]
    )

    orders_integration = IntegrationIdentity(
        name="orders_gateway", display_name="Orders Gateway", description="d", files=[orders_file]
    )
    payments_integration = IntegrationIdentity(
        name="payments_gateway", display_name="Payments Gateway", description="d", files=[payments_file]
    )
    # One identity spans both services — must be trimmed, not just kept whole.
    shared_integration = IntegrationIdentity(
        name="shared_sdk", display_name="Shared SDK", description="d", files=[orders_file, payments_file]
    )

    artifact_scan = ArtifactScan(
        setup_artifacts=[orders_file, payments_file],
        database_scan=DatabaseScan(
            model_files=[
                ModelFileInfo(file_path=orders_file, orm_framework="django", model_names=["Order"]),
                ModelFileInfo(file_path=payments_file, orm_framework="django", model_names=["Payment"]),
            ],
            groups=[
                DatabaseGroup(key="core", label="Core", file_paths=[orders_file, payments_file]),
            ],
            graphql_interfaces=[
                GraphQLInterface(name="Order", file_path=orders_file, kind="object_type"),
                GraphQLInterface(name="Payment", file_path=payments_file, kind="object_type"),
            ],
            knex_artifacts=[
                KnexArtifact(file_path=orders_file, artifact_type="schema", table_name="orders"),
                KnexArtifact(file_path=payments_file, artifact_type="schema", table_name="payments"),
            ],
        ),
    )
    runtime_scan = RuntimeScan(
        tasks=[
            RuntimeTask(name="sync_orders", file_path=orders_file, runtime_kind="celery"),
            RuntimeTask(name="sync_payments", file_path=payments_file, runtime_kind="celery"),
        ]
    )
    config_impacts = [
        ConfigImpact(key="ORDERS_URL", kind="env_var", file_path=orders_file, related_files=[orders_file, payments_file]),
        ConfigImpact(key="PAYMENTS_URL", kind="env_var", file_path=payments_file, related_files=[payments_file]),
    ]
    debug_signals = [
        DebugSignal(signal_type="logger", name="orders_log", file_path=orders_file, description="d", files=[orders_file, payments_file]),
        DebugSignal(signal_type="logger", name="payments_log", file_path=payments_file, description="d", files=[payments_file]),
    ]
    flow_candidates = [
        FlowCandidate(
            flow_id="checkout",
            title="Checkout",
            entry_kind="http",
            entry_points=[EntryPoint(kind="http", label="checkout", handler_file=orders_file, handler_symbol="create_order")],
            involved_files=[orders_file, payments_file],
        ),
        FlowCandidate(
            flow_id="payments_only",
            title="Payments only",
            entry_kind="http",
            entry_points=[EntryPoint(kind="http", label="charge", handler_file=payments_file, handler_symbol="charge")],
            involved_files=[payments_file],
        ),
    ]
    service_boundaries = [
        {"name": "orders", "root": "services/orders", "source": "auto"},
        {"name": "payments", "root": "services/payments", "source": "auto"},
    ]

    scan = _scan(
        file_summaries={orders_file: "s", payments_file: "s"},
        file_services={orders_file: "orders", payments_file: "payments"},
        endpoint_bundles=[orders_bundle, payments_bundle],
        integration_identities=[orders_integration, payments_integration, shared_integration],
        artifact_scan=artifact_scan,
        runtime_scan=runtime_scan,
        graphql_interfaces=list(artifact_scan.database_scan.graphql_interfaces),
        knex_artifacts=list(artifact_scan.database_scan.knex_artifacts),
        research_contexts=[
            {"kind": "notes", "title": "Orders", "file_path": orders_file, "summary": "s", "headings": []},
            {"kind": "notes", "title": "Payments", "file_path": payments_file, "summary": "s", "headings": []},
        ],
        semantic_file_token_cache={orders_file: {"order"}, payments_file: {"payment"}},
        config_impacts=config_impacts,
        debug_signals=debug_signals,
        flow_candidates=flow_candidates,
        service_boundaries=service_boundaries,
    )

    units = {u.slug: u for u in build_planning_units(scan)}
    orders_sub = make_sub_scan(scan, units["orders"])

    assert [b.handler_file for b in orders_sub.endpoint_bundles] == [orders_file]

    integration_names = {i.name for i in orders_sub.integration_identities}
    assert integration_names == {"orders_gateway", "shared_sdk"}
    shared = next(i for i in orders_sub.integration_identities if i.name == "shared_sdk")
    assert shared.files == [orders_file]  # trimmed, not left spanning both services

    assert orders_sub.artifact_scan.setup_artifacts == [orders_file]
    db = orders_sub.artifact_scan.database_scan
    assert [m.file_path for m in db.model_files] == [orders_file]
    assert db.groups[0].file_paths == [orders_file]
    assert [g.file_path for g in db.graphql_interfaces] == [orders_file]
    assert [k.file_path for k in db.knex_artifacts] == [orders_file]

    assert orders_sub.runtime_scan.tasks[0].file_path == orders_file
    assert len(orders_sub.runtime_scan.tasks) == 1

    assert [g.file_path for g in orders_sub.graphql_interfaces] == [orders_file]
    assert [k.file_path for k in orders_sub.knex_artifacts] == [orders_file]

    assert [c["file_path"] for c in orders_sub.research_contexts] == [orders_file]
    assert set(orders_sub.semantic_file_token_cache) == {orders_file}

    assert [c.file_path for c in orders_sub.config_impacts] == [orders_file]
    assert orders_sub.config_impacts[0].related_files == [orders_file]  # trimmed

    assert [d.file_path for d in orders_sub.debug_signals] == [orders_file]
    assert orders_sub.debug_signals[0].files == [orders_file]  # trimmed

    assert [f.flow_id for f in orders_sub.flow_candidates] == ["checkout"]
    assert orders_sub.flow_candidates[0].involved_files == [orders_file]  # trimmed

    assert [b["name"] for b in orders_sub.service_boundaries] == ["orders"]

    assert orders_sub.scan_timings == {}
    assert orders_sub.planner_timings == {}

    # Global scan is completely untouched.
    assert len(scan.endpoint_bundles) == 2
    assert len(scan.integration_identities) == 3
    assert scan.artifact_scan.database_scan.model_files[1].file_path == payments_file
