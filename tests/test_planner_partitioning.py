from __future__ import annotations

from deepdoc.planner.partitioning import (
    PlanningUnit,
    build_planning_units,
    make_sub_scan,
    split_planning_unit,
)
from deepdoc.planner.topology import TopologyCluster, TopologyMap
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
