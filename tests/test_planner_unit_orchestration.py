"""End-to-end orchestration tests for bounded multi-unit planning.

Drives the real `plan_docs()` pipeline (real token counting via
`fit_prompt_sections`/`count_message_tokens`, real bucket injectors) with a
scripted fake `_llm_step` standing in for the network call, so these prove
the partitioning/merge wiring without needing a live LLM.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from deepdoc.config import DEFAULT_CONFIG
from deepdoc.llm.token_budget import ModelCapabilities
from deepdoc.planner import RepoScan
from deepdoc.planner.engine import _plan_local, plan_docs
from deepdoc.planner.merge import missing_files
from deepdoc.plan_contract import validate_plan_contract
from .conftest import make_planner_llm

_PATH_RE = re.compile(r"[\w./-]+\.py")


def _fake_llm_step(llm, system, prompt, step_name):
    if step_name == "classify":
        return {"repo_profile": {}, "cluster_names": {}}
    if step_name == "propose":
        # Chunk whatever files are visible in this prompt into small buckets
        # (well under decompose_threshold) so decompose/consolidate never
        # need their own LLM call.
        files = sorted(set(_PATH_RE.findall(prompt)))
        chunks = [files[i : i + 5] for i in range(0, len(files), 5)] or [[]]
        buckets = [
            {
                "slug": f"group-{i}",
                "title": f"Group {i}",
                "bucket_type": "feature",
                "section": "Features",
                "candidate_files": chunk,
                "description": "d",
            }
            for i, chunk in enumerate(chunks)
        ]
        return {
            "buckets": buckets,
            "nav_structure": {"Features": [b["slug"] for b in buckets]},
        }
    if step_name == "assign":
        files = sorted(set(_PATH_RE.findall(prompt)))
        chunks = [files[i : i + 5] for i in range(0, len(files), 5)] or [[]]
        return {
            "buckets": [
                {"slug": f"group-{i}", "owned_files": chunk}
                for i, chunk in enumerate(chunks)
            ]
        }
    return None  # decompose-*, etc.: decline gracefully like a real LLM failure


def _service_scan(services: dict[str, int]) -> RepoScan:
    file_summaries: dict[str, str] = {}
    file_services: dict[str, str] = {}
    for service, count in services.items():
        for i in range(count):
            path = f"services/{service}/module_{i:02d}/component_{i:02d}/handler.py"
            file_summaries[path] = f"handler for {service} #{i} | lines=20"
            file_services[path] = service
    return RepoScan(
        file_tree={},
        file_summaries=file_summaries,
        api_endpoints=[],
        languages={"python": len(file_summaries)},
        has_openapi=False,
        openapi_paths=[],
        total_files=len(file_summaries),
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
        file_services=file_services,
    )


def _cfg() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg["max_pages"] = 0
    return cfg


def _tight_llm():
    llm = make_planner_llm()
    llm.capabilities = ModelCapabilities(
        model="test",
        capability_model="gpt-4o-mini",
        context_window_tokens=3050,
        max_output_tokens=100,
        source="test",
    )
    llm.output_reserve_tokens = 100
    return llm


def test_single_unit_repo_uses_the_original_scan_with_no_prefixing() -> None:
    """Zero/one meaningful service must plan exactly as before: one _plan_local
    call against the original (unfiltered) scan object, no merge/prefixing."""
    scan = _service_scan({"only": 3})
    llm = make_planner_llm()

    calls: list[RepoScan] = []

    def _record(passed_scan, cfg, passed_llm, repo_root):
        calls.append(passed_scan)
        from deepdoc.v2_models import DocBucket, DocPlan

        return DocPlan(
            buckets=[
                DocBucket(
                    bucket_type="start_here_index",
                    title="Start Here",
                    slug="start-here",
                    section="Start Here",
                    description="d",
                    owned_files=list(passed_scan.file_summaries),
                    generation_hints={"is_introduction_page": True},
                )
            ],
            nav_structure={"Start Here": ["start-here"]},
            skipped_files=[],
        )

    with patch("deepdoc.planner.engine.run_phase2_scans", side_effect=lambda s, c, l, repo_root: s), \
         patch("deepdoc.planner.engine._plan_local", side_effect=_record) as mock_plan_local:
        plan = plan_docs(scan, _cfg(), llm)

    assert mock_plan_local.call_count == 1
    assert calls[0] is scan  # same object identity: no sub-scan projection
    assert [b.slug for b in plan.buckets] == ["start-here"]  # no namespacing applied


def test_multi_unit_repo_bounds_each_unit_to_its_own_files() -> None:
    """Each unit must only ever see its own files — proves the partition is real,
    not just cosmetic slug prefixing over the same global inventory."""
    scan = _service_scan({"orders": 4, "payments": 3})
    llm = make_planner_llm()
    seen_files: list[set[str]] = []

    def _record(passed_scan, cfg, passed_llm, repo_root):
        from deepdoc.v2_models import DocBucket, DocPlan

        seen_files.append(set(passed_scan.file_summaries))
        return DocPlan(
            buckets=[
                DocBucket(
                    bucket_type="start_here_index",
                    title="Start Here",
                    slug="start-here",
                    section="Start Here",
                    description="d",
                    owned_files=list(passed_scan.file_summaries),
                    generation_hints={"is_introduction_page": True},
                )
            ],
            nav_structure={"Start Here": ["start-here"]},
            skipped_files=[],
        )

    with patch("deepdoc.planner.engine.run_phase2_scans", side_effect=lambda s, c, l, repo_root: s), \
         patch("deepdoc.planner.engine._plan_local", side_effect=_record):
        plan = plan_docs(scan, _cfg(), llm)

    assert len(seen_files) == 2
    orders_files = {f for f in scan.file_summaries if "orders" in f}
    payments_files = {f for f in scan.file_summaries if "payments" in f}
    assert sorted(seen_files, key=len) == sorted([orders_files, payments_files], key=len)
    # No unit ever saw the other unit's files.
    assert seen_files[0].isdisjoint(seen_files[1])

    slugs = sorted(b.slug for b in plan.buckets)
    assert slugs == ["orders/start-here", "start-here"] or slugs == ["payments/start-here", "start-here"]
    validate_plan_contract(plan)


def test_bounded_multi_unit_planning_fits_where_one_global_inventory_would_not() -> None:
    """The real regression this slice targets: a combined ASSIGN inventory for
    both services blows the (tiny, deliberately small) model budget, but each
    service's own inventory fits — so real end-to-end planning must still
    complete without raising `ModelCapabilityError`, and no single `_llm_step`
    call may ever be handed a prompt exceeding the resolved budget."""
    scan = _service_scan({"orders": 50, "payments": 50})
    llm = _tight_llm()
    cfg = _cfg()

    with patch("deepdoc.planner.engine.run_phase2_scans", side_effect=lambda s, c, l, repo_root: s), \
         patch("deepdoc.planner.engine._llm_step", side_effect=_fake_llm_step):
        plan = plan_docs(scan, cfg, llm)

        validate_plan_contract(plan)
        assert missing_files(scan, plan) == []

        # Proof this genuinely required partitioning: feeding the exact same
        # (unpartitioned) 100-file scan straight to the single-unit planning
        # core — what today's whole-repo-only pipeline would do — blows the
        # same tiny budget that bounded per-unit planning just satisfied
        # above. PROPOSE's required `named_clusters` section is the
        # bottleneck here (no topology map => falls back to compressed file
        # summaries for the whole inventory).
        from deepdoc.llm import ModelCapabilityError

        with pytest.raises(ModelCapabilityError):
            _plan_local(scan, cfg, llm, Path("."))
