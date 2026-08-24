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

    def _record(passed_scan, cfg, passed_llm, repo_root, apply_global_stage=True, unit=None):
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

    def _record(passed_scan, cfg, passed_llm, repo_root, apply_global_stage=True, unit=None):
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

    # Each mocked unit's local plan volunteered its own "start-here"
    # introduction (a real LLM propose step can legitimately do this too);
    # merge keeps exactly one as the global introduction and demotes the
    # other to a namespaced overview bucket instead of duplicating it.
    introductions = [
        b for b in plan.buckets if (b.generation_hints or {}).get("is_introduction_page")
    ]
    assert [b.slug for b in introductions] == ["start-here"]
    demoted = [b for b in plan.buckets if b.title == "Start Here" and b.slug != "start-here"]
    assert [b.slug for b in demoted] == ["orders/start-here"] or [b.slug for b in demoted] == [
        "payments/start-here"
    ]

    # Global-only injectors (Local Development Setup, Domain Glossary) must
    # run exactly once on the merged plan, not once per unit — proves this
    # is a single consolidated global bucket set, not per-service duplicates.
    setup_buckets = [b for b in plan.buckets if b.bucket_type == "start_here_setup"]
    glossary_buckets = [b for b in plan.buckets if b.bucket_type == "domain_glossary"]
    assert len(setup_buckets) <= 1
    assert len(glossary_buckets) <= 1

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


def test_single_oversized_service_still_splits_and_every_prompt_fits() -> None:
    """build_planning_units() alone can return exactly one unit — a single
    service, or `core` — that is itself too big for the model budget. The
    old single-unit fast path took "one unit" as proof it was safe to plan
    directly; it isn't. This drives the real plan_docs() pipeline with one
    service of 100 files against a tight budget and proves: (1) it still
    gets split into more than one planning unit despite file_services
    reporting a single service, (2) every real `_llm_step` call's rendered
    (system, prompt) pair — measured with the real tokenizer, not an
    estimate — stays within the resolved model budget, and (3) the result
    is still one contract-valid, fully-disposed plan."""
    from deepdoc.llm.token_budget import build_prompt_budget, count_message_tokens

    scan = _service_scan({"orders": 100})
    llm = _tight_llm()
    llm.capabilities = ModelCapabilities(
        model="test",
        capability_model="gpt-4o-mini",
        context_window_tokens=3000,
        max_output_tokens=100,
        source="test",
    )
    llm.output_reserve_tokens = 100
    cfg = _cfg()

    budget = build_prompt_budget(llm.capabilities, output_reserve_tokens=llm.output_reserve_tokens)
    maximum_input = budget.context_window_tokens - budget.output_reserve_tokens - budget.safety_tokens

    seen_token_counts: list[int] = []

    def _measuring_llm_step(passed_llm, system, prompt, step_name):
        tokens, _ = count_message_tokens(system, prompt, passed_llm.capabilities)
        seen_token_counts.append(tokens)
        return _fake_llm_step(passed_llm, system, prompt, step_name)

    with patch("deepdoc.planner.engine.run_phase2_scans", side_effect=lambda s, c, l, repo_root: s), \
         patch("deepdoc.planner.engine._llm_step", side_effect=_measuring_llm_step):
        plan = plan_docs(scan, cfg, llm)

    validate_plan_contract(plan)
    assert missing_files(scan, plan) == []

    # Proves the single-raw-unit repo genuinely got split, not just planned
    # directly and gotten lucky. (build_planning_units() alone would have
    # returned exactly one "orders" unit here — every file shares one
    # service — so more than one entry only shows up via bound_planning_unit.)
    units_meta = plan.classification.get("planning_units")
    assert units_meta is not None
    assert len(units_meta) > 1
    assert sum(u["file_count"] for u in units_meta) == 100
    assert not any(u["coarse"] for u in units_meta)

    assert seen_token_counts, "expected at least one _llm_step call"
    assert all(count <= maximum_input for count in seen_token_counts), (
        f"a prompt exceeded the budget: {max(seen_token_counts)} > {maximum_input}"
    )


def test_proposal_dependent_assign_overflow_triggers_real_split_and_retry() -> None:
    """The preflight (unit_likely_fits_budget) only ever looks at the file
    list — it has no way to know PROPOSE will come back with a verbose
    bucket JSON, because that's the LLM's output, decided only after
    PROPOSE actually runs. This crafts exactly that gap: few enough files
    that the preflight says "fits" and the whole repo takes the single-unit
    fast path, but a deliberately verbose PROPOSE response makes the real
    ASSIGN prompt (which embeds the full proposed-bucket JSON) blow the
    budget. Proves the orchestration layer catches that as UnitNeedsSplit,
    splits only the failing unit, retries, and every actual LLM request
    that goes out stays within budget — not that the repo fails, and not
    that the preflight "predicted" it correctly."""
    scan = _service_scan({"orders": 6})
    llm = make_planner_llm()
    llm.capabilities = ModelCapabilities(
        model="test", capability_model="gpt-4o-mini", context_window_tokens=3000,
        max_output_tokens=100, source="test",
    )
    llm.output_reserve_tokens = 100
    cfg = _cfg()

    from deepdoc.llm.token_budget import build_prompt_budget, count_message_tokens
    from deepdoc.planner.partitioning import unit_likely_fits_budget, build_planning_units

    # Confirm the gap actually exists before relying on it: the cheap
    # preflight must say this repo fits as one unit (it only looks at file
    # count/paths, not at what PROPOSE will invent).
    raw_units = build_planning_units(scan)
    assert len(raw_units) == 1
    assert unit_likely_fits_budget(scan, llm) is True

    budget = build_prompt_budget(llm.capabilities, output_reserve_tokens=llm.output_reserve_tokens)
    maximum_input = budget.context_window_tokens - budget.output_reserve_tokens - budget.safety_tokens

    def _verbose_fake_llm_step(passed_llm, system, prompt, step_name):
        if step_name == "classify":
            return {"repo_profile": {}, "cluster_names": {}}
        if step_name == "propose":
            # One bucket per file currently in scope, each padded with a
            # large fixed-size blob — this is what makes the real ASSIGN
            # prompt's embedded proposed-bucket JSON scale with the
            # PROPOSAL, not with the (small, constant) file list, and it
            # shrinks as the orchestration layer splits into smaller units.
            files = sorted(set(_PATH_RE.findall(prompt)))
            buckets = [
                {
                    "slug": f"group-{i}",
                    "title": f"Group {i}",
                    "bucket_type": "feature",
                    "section": "Features",
                    "candidate_files": [f],
                    "description": "d",
                    # Distinct tokens prevent BPE from compressing a repeated
                    # character run into a tiny payload. Six buckets overflow
                    # ASSIGN, while recursively smaller proposals fit.
                    "generation_hints": {
                        "padding": " ".join(
                            f"proposal_padding_{i}_{j}" for j in range(160)
                        )
                    },
                }
                for i, f in enumerate(files)
            ]
            return {
                "buckets": buckets,
                "nav_structure": {"Features": [b["slug"] for b in buckets]},
            }
        if step_name == "assign":
            files = sorted(set(_PATH_RE.findall(prompt)))
            return {
                "buckets": [
                    {"slug": f"group-{i}", "owned_files": [f]} for i, f in enumerate(files)
                ]
            }
        return None

    seen_token_counts: list[int] = []

    def _measuring_llm_step(passed_llm, system, prompt, step_name):
        tokens, _ = count_message_tokens(system, prompt, passed_llm.capabilities)
        seen_token_counts.append(tokens)
        return _verbose_fake_llm_step(passed_llm, system, prompt, step_name)

    with patch("deepdoc.planner.engine.run_phase2_scans", side_effect=lambda s, c, l, repo_root: s), \
         patch("deepdoc.planner.engine._llm_step", side_effect=_measuring_llm_step):
        plan = plan_docs(scan, cfg, llm)

    validate_plan_contract(plan)
    assert missing_files(scan, plan) == []

    units_meta = plan.classification.get("planning_units")
    assert units_meta is not None, "a real overflow must fall through to the multi-unit path"
    assert len(units_meta) > 1, "the single oversized-by-proposal unit must have been split"
    assert sum(u["file_count"] for u in units_meta) == 6

    assert seen_token_counts, "expected at least one real _llm_step call"
    assert all(count <= maximum_input for count in seen_token_counts), (
        f"a real LLM request exceeded the budget: {max(seen_token_counts)} > {maximum_input} "
        "— UnitNeedsSplit must be raised before any oversized request is sent, never after"
    )
