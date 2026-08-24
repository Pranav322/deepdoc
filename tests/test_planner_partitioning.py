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
    unit_fits_model_budget,
)
from deepdoc.planner.topology import TopologyCluster, TopologyMap
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


def test_unit_fits_model_budget_true_for_small_unit_false_for_huge_unit() -> None:
    small = _scan(file_summaries={"a.py": "handler | lines=10"})
    assert unit_fits_model_budget(small, _llm()) is True

    huge = _scan(
        file_summaries={
            f"services/orders/module_{i:02d}/component_{i:02d}/handler.py": f"handler #{i} | lines=20"
            for i in range(200)
        }
    )
    tight = _llm(context_window_tokens=1200, output_reserve_tokens=100)
    assert unit_fits_model_budget(huge, tight) is False


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
    assert not unit_fits_model_budget(make_sub_scan(scan, raw_unit), llm)

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
        assert unit_fits_model_budget(make_sub_scan(scan, part), llm)


def test_bound_planning_unit_marks_an_indivisible_oversized_file_as_coarse() -> None:
    """A single file whose own content still exceeds the budget can't be
    split any further — it must come back explicitly marked `coarse=True`
    rather than looping forever or silently being handed to the LLM anyway."""
    unit = PlanningUnit(slug="giant", label="giant", files=("giant/one_file.py",))
    scan = _scan(file_summaries={"giant/one_file.py": "x" * 50})

    with patch(
        "deepdoc.planner.partitioning.unit_fits_model_budget", return_value=False
    ):
        parts = bound_planning_unit(unit, scan, _llm())

    assert len(parts) == 1
    assert parts[0].coarse is True
    assert parts[0].files == ("giant/one_file.py",)
