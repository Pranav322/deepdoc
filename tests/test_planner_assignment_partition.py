from __future__ import annotations

import pytest

from deepdoc.llm import LLMOutputTruncatedError
from deepdoc.planner.heuristics import (
    _llm_step,
    _merge_partial_assignment,
    _partition_topology_assignment,
)
from deepdoc.planner.topology import TopologyMap
from deepdoc.v2_models import RepoScan


def _scan(files: list[str], clusters: dict[str, str]) -> RepoScan:
    return RepoScan(
        file_tree={},
        file_summaries={path: f"summary for {path}" for path in files},
        api_endpoints=[],
        languages={"python": len(files)},
        has_openapi=False,
        openapi_paths=[],
        total_files=len(files),
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
        source_kind_by_file={path: "product" for path in files},
        topology_map=TopologyMap(
            clusters=[],
            file_indegree={},
            file_call_depth={},
            file_cluster_id=clusters,
            foundational_files=[],
        ),
    )


def test_unique_matching_topology_candidate_is_preassigned() -> None:
    scan = _scan(["orders.py", "payments.py"], {"orders.py": "orders", "payments.py": "payments"})
    proposal = {
        "buckets": [
            {"slug": "orders", "cluster_id": "orders", "candidate_files": ["orders.py"]},
            {"slug": "payments", "cluster_id": "payments", "candidate_files": ["payments.py"]},
        ]
    }

    deterministic, unresolved = _partition_topology_assignment(proposal, scan)

    assert unresolved == []
    assert deterministic["file_to_buckets"] == {
        "orders.py": ["orders"],
        "payments.py": ["payments"],
    }


def test_overlapping_or_mismatched_candidates_remain_unresolved() -> None:
    scan = _scan(["shared.py", "wrong.py"], {"shared.py": "one", "wrong.py": "one"})
    proposal = {
        "buckets": [
            {
                "slug": "one",
                "cluster_id": "one",
                "candidate_files": ["shared.py"],
            },
            {
                "slug": "two",
                "cluster_id": "two",
                "candidate_files": ["shared.py", "wrong.py"],
            },
        ]
    }

    deterministic, unresolved = _partition_topology_assignment(proposal, scan)

    assert deterministic["buckets"] == []
    assert unresolved == ["shared.py", "wrong.py"]


def test_foundational_giant_config_and_endpoint_files_remain_unresolved() -> None:
    files = ["base.py", "giant.py", "config.py", "handler.py"]
    scan = _scan(files, {path: "core" for path in files})
    scan.topology_map.foundational_files = ["base.py"]
    scan.giant_file_clusters = {"giant.py": object()}
    scan.config_files = ["config.py"]
    scan.api_endpoints = [
        {
            "route_file": "handler.py",
            "handler_file": "handler.py",
            "file": "handler.py",
        }
    ]
    proposal = {
        "buckets": [
            {
                "slug": "core",
                "cluster_id": "core",
                "candidate_files": files,
            }
        ]
    }

    deterministic, unresolved = _partition_topology_assignment(proposal, scan)

    assert deterministic["buckets"] == []
    assert unresolved == sorted(files)


def test_supporting_source_kinds_remain_unresolved() -> None:
    scan = _scan(["src/app.py", "tests/test_app.py"], {"src/app.py": "app", "tests/test_app.py": "app"})
    scan.source_kind_by_file["tests/test_app.py"] = "test"
    proposal = {
        "buckets": [
            {
                "slug": "app",
                "cluster_id": "app",
                "candidate_files": ["src/app.py", "tests/test_app.py"],
            }
        ]
    }

    deterministic, unresolved = _partition_topology_assignment(proposal, scan)

    assert deterministic["file_to_buckets"] == {"src/app.py": ["app"]}
    assert unresolved == ["tests/test_app.py"]


def test_partial_assignment_merge_filters_preassigned_and_unknown_files() -> None:
    proposal = {"buckets": [{"slug": "orders"}, {"slug": "shared"}]}
    deterministic = {
        "buckets": [{"slug": "orders", "owned_files": ["orders.py"]}],
    }
    llm_assignment = {
        "buckets": [
            {
                "slug": "orders",
                "owned_files": ["orders.py", "shared.py", "invented.py"],
                "owned_symbols": ["handle"],
                "priority": 2,
            },
            {"slug": "shared", "owned_files": ["shared.py"]},
        ],
        "skipped_files": ["invented.py", "test.py"],
    }

    merged = _merge_partial_assignment(
        proposal,
        deterministic,
        llm_assignment,
        ["shared.py", "test.py"],
    )

    assert merged["buckets"][0]["owned_files"] == ["orders.py", "shared.py"]
    assert merged["buckets"][0]["owned_symbols"] == ["handle"]
    assert merged["buckets"][1]["owned_files"] == ["shared.py"]
    assert merged["skipped_files"] == ["test.py"]


def test_missing_topology_leaves_complete_inventory_for_llm() -> None:
    scan = _scan(["b.py", "a.py"], {})

    deterministic, unresolved = _partition_topology_assignment(
        {"buckets": []}, scan
    )

    assert deterministic["buckets"] == []
    assert unresolved == ["a.py", "b.py"]


def test_planner_propagates_truncated_llm_output() -> None:
    class _TruncatedLLM:
        telemetry = None

        def complete(self, system: str, prompt: str) -> str:
            raise LLMOutputTruncatedError("output was truncated")

    with pytest.raises(LLMOutputTruncatedError, match="output was truncated"):
        _llm_step(_TruncatedLLM(), "system", "prompt", "propose")
