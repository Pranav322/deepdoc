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

import click
import pytest

from deepdoc.config import DEFAULT_CONFIG
from deepdoc.llm.token_budget import ModelCapabilities
from deepdoc.plan_contract import validate_plan_contract
from deepdoc.planner import RepoScan
from deepdoc.planner import engine as engine_module
from deepdoc.planner.engine import _allocate_page_budgets, _plan_local, plan_docs
from deepdoc.planner.merge import missing_files
from deepdoc.planner.partitioning import PlanningUnit

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

    with patch("deepdoc.planner.engine.run_phase2_scans", side_effect=lambda s, c, llm_client, repo_root: s), \
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

    with patch("deepdoc.planner.engine.run_phase2_scans", side_effect=lambda s, c, llm_client, repo_root: s), \
         patch("deepdoc.planner.engine._plan_local", side_effect=_record):
        plan = plan_docs(scan, _cfg(), llm)

    assert len(seen_files) == 2
    orders_files = {f for f in scan.file_summaries if "orders" in f}
    payments_files = {f for f in scan.file_summaries if "payments" in f}
    assert sorted(seen_files, key=len) == sorted([orders_files, payments_files], key=len)
    # No unit ever saw the other unit's files.
    assert seen_files[0].isdisjoint(seen_files[1])

    # Each mocked unit's local plan volunteered its own "start-here" page.
    # Merge demotes both to namespaced service overviews; the global stage
    # creates the sole repository-wide introduction from the full scan.
    introductions = [
        b for b in plan.buckets if (b.generation_hints or {}).get("is_introduction_page")
    ]
    assert [b.slug for b in introductions] == ["start-here"]
    demoted = [b for b in plan.buckets if b.title == "Start Here" and b.slug != "start-here"]
    assert sorted(b.slug for b in demoted) == [
        "orders/start-here",
        "payments/start-here",
    ]
    assert set(introductions[0].owned_files) == set(scan.file_summaries)

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

    with patch("deepdoc.planner.engine.run_phase2_scans", side_effect=lambda s, c, llm_client, repo_root: s), \
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


def test_repository_max_pages_is_allocated_across_units() -> None:
    units = [
        PlanningUnit(slug="a", label="a", files=("a.py",)),
        PlanningUnit(slug="b", label="b", files=("b.py", "b2.py")),
        PlanningUnit(slug="c", label="c", files=("c.py",)),
    ]

    budgets = _allocate_page_budgets(units, 10)

    assert sum(budgets) == 10
    assert all(budget >= 1 for budget in budgets)
    assert budgets[1] >= budgets[0]


def test_repository_max_pages_must_cover_every_independent_unit() -> None:
    units = [
        PlanningUnit(slug="a", label="a", files=("a.py",)),
        PlanningUnit(slug="b", label="b", files=("b.py",)),
    ]

    with pytest.raises(click.ClickException, match="cannot cover 2 planning units"):
        _allocate_page_budgets(units, 1)


def test_multi_unit_planner_receives_allocated_not_repository_page_cap() -> None:
    scan = _service_scan({"orders": 2, "payments": 2})
    llm = make_planner_llm()
    cfg = _cfg()
    cfg["max_pages"] = 10
    seen_caps: list[int] = []

    def _record(passed_scan, passed_cfg, passed_llm, repo_root, apply_global_stage=True, unit=None):
        from deepdoc.v2_models import DocBucket, DocPlan

        seen_caps.append(passed_cfg["max_pages"])
        return DocPlan(
            buckets=[
                DocBucket(
                    bucket_type="feature",
                    title="Feature",
                    slug="feature",
                    section="Features",
                    description="d",
                    owned_files=list(passed_scan.file_summaries),
                )
            ],
            nav_structure={"Features": ["feature"]},
            skipped_files=[],
            classification={"repo_profile": {}, "cluster_names": {}},
        )

    with patch("deepdoc.planner.engine.run_phase2_scans", side_effect=lambda s, c, llm_client, repo_root: s), \
         patch("deepdoc.planner.engine._plan_local", side_effect=_record):
        plan_docs(scan, cfg, llm)

    assert seen_caps == [5, 5]
    assert sum(seen_caps) == 10


def test_single_unit_repo_has_no_boundary_stubs() -> None:
    """Slice B semantic refinement/boundary stubs must never engage on the
    single-unit parity path — the `unit` handed to `_plan_local` carries no
    cross-unit evidence."""
    scan = _service_scan({"only": 3})
    llm = make_planner_llm()
    captured_units: list[PlanningUnit] = []

    def _record(passed_scan, cfg, passed_llm, repo_root, apply_global_stage=True, unit=None):
        from deepdoc.v2_models import DocBucket, DocPlan

        captured_units.append(unit)
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

    with patch("deepdoc.planner.engine.run_phase2_scans", side_effect=lambda s, c, llm_client, repo_root: s), \
         patch("deepdoc.planner.engine._plan_local", side_effect=_record):
        plan_docs(scan, _cfg(), llm)

    assert len(captured_units) == 1
    assert captured_units[0].boundary_stubs == ()


def test_multi_unit_units_receive_recomputed_boundary_stubs() -> None:
    """Two coupled services with real call-graph cross edges must each
    receive a compact, reciprocal boundary stub naming the other unit — and
    nothing from that stub payload leaks the other unit's file paths."""
    from deepdoc.call_graph import CallEdge, CallGraph

    scan = _service_scan({"orders": 2, "payments": 2})
    orders_file = "services/orders/module_00/component_00/handler.py"
    payments_file = "services/payments/module_00/component_00/handler.py"
    graph = CallGraph()
    graph.add_edge(
        CallEdge(
            caller_file=orders_file,
            caller_symbol="handle",
            callee_file=payments_file,
            callee_symbol="charge",
        )
    )
    scan.call_graph = graph
    llm = make_planner_llm()
    captured_units: list[PlanningUnit] = []

    def _record(passed_scan, cfg, passed_llm, repo_root, apply_global_stage=True, unit=None):
        from deepdoc.v2_models import DocBucket, DocPlan

        captured_units.append(unit)
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

    with patch("deepdoc.planner.engine.run_phase2_scans", side_effect=lambda s, c, llm_client, repo_root: s), \
         patch("deepdoc.planner.engine._plan_local", side_effect=_record):
        plan_docs(scan, _cfg(), llm)

    by_slug = {u.slug: u for u in captured_units}
    assert set(by_slug) == {"orders", "payments"}
    orders_stubs = by_slug["orders"].boundary_stubs
    payments_stubs = by_slug["payments"].boundary_stubs
    assert [s.remote_unit for s in orders_stubs] == ["payments"]
    assert [s.remote_unit for s in payments_stubs] == ["orders"]
    for stub in (*orders_stubs, *payments_stubs):
        assert orders_file not in repr(stub)
        assert payments_file not in repr(stub)


def test_plan_local_includes_bounded_cross_unit_context_in_classify_prompt() -> None:
    """The compact cross-unit context Slice B attaches to a unit's
    boundary_stubs must actually reach the rendered CLASSIFY prompt as
    optional context — proving the wiring, not just the data structure."""
    from deepdoc.planner.unit_boundaries import BoundaryStub

    scan = _service_scan({"orders": 2})
    llm = make_planner_llm()
    unit = PlanningUnit(
        slug="orders",
        label="orders",
        files=tuple(scan.file_summaries),
        boundary_stubs=(
            BoundaryStub(
                remote_unit="payments",
                direction="outbound",
                score=3.0,
                call_count=3,
                evidence_kinds=("call",),
            ),
        ),
    )
    seen_prompts: list[str] = []

    def _capture(passed_llm, system, prompt, step_name):
        if step_name == "classify":
            seen_prompts.append(prompt)
        return _fake_llm_step(passed_llm, system, prompt, step_name)

    with patch("deepdoc.planner.engine._llm_step", side_effect=_capture):
        _plan_local(scan, _cfg(), llm, Path("."), unit=unit)

    assert seen_prompts, "expected at least one classify _llm_step call"
    assert "payments" in seen_prompts[0]
    assert "outbound" in seen_prompts[0]


def test_split_retry_recomputes_boundary_stubs_without_stale_parent_leak() -> None:
    """When a unit splits after a genuine `UnitNeedsSplit`, each resulting
    child must get its own freshly computed boundary stubs — never a copy
    of the parent's pre-split aggregate."""
    from deepdoc.call_graph import CallEdge, CallGraph
    from deepdoc.planner.engine import _plan_unit_with_retry

    orders_files = tuple(f"services/orders/file_{i}.py" for i in range(4))
    payments_file = "services/payments/app.py"
    graph = CallGraph()
    # Only the first orders file calls into payments.
    graph.add_edge(
        CallEdge(
            caller_file=orders_files[0],
            caller_symbol="handle",
            callee_file=payments_file,
            callee_symbol="charge",
        )
    )
    scan = _service_scan({"orders": 0})
    scan.file_summaries = {f: "s | lines=5" for f in orders_files}
    scan.file_summaries[payments_file] = "s | lines=5"
    scan.file_services = {f: "orders" for f in orders_files}
    scan.file_services[payments_file] = "payments"
    scan.call_graph = graph
    scan.total_files = len(scan.file_summaries)

    unit = PlanningUnit(slug="orders", label="orders", files=orders_files)
    baseline_unit_files = {
        "orders": frozenset(orders_files),
        "payments": frozenset({payments_file}),
    }
    llm = make_planner_llm()

    calls = 0

    def _fail_then_split(passed_scan, cfg, passed_llm, repo_root, apply_global_stage=True, unit=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            from deepdoc.planner.partitioning import UnitNeedsSplit

            raise UnitNeedsSplit(unit, "classify", "forced overflow for test")
        from deepdoc.v2_models import DocPlan

        return DocPlan(buckets=[], nav_structure={}, skipped_files=[])

    results = []
    with patch("deepdoc.planner.engine._plan_local", side_effect=_fail_then_split):
        results = _plan_unit_with_retry(
            unit,
            scan,
            _cfg(),
            llm,
            Path("."),
            max_files_seed_cap=0,
            page_budget=0,
            baseline_unit_files=baseline_unit_files,
        )

    final_units = [u for u, _plan in results]
    assert len(final_units) > 1, "the failing unit must have been split"
    with_stub = [u for u in final_units if u.boundary_stubs]
    without_stub = [u for u in final_units if not u.boundary_stubs]
    assert len(with_stub) == 1, "only the child owning the calling file should get a stub"
    assert len(without_stub) >= 1
    assert with_stub[0].boundary_stubs[0].remote_unit == "payments"
    assert payments_file not in repr(with_stub[0].boundary_stubs)


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

    with patch("deepdoc.planner.engine.run_phase2_scans", side_effect=lambda s, c, llm_client, repo_root: s), \
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
    from deepdoc.planner.partitioning import (
        build_planning_units,
        unit_likely_fits_budget,
    )

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

    with patch("deepdoc.planner.engine.run_phase2_scans", side_effect=lambda s, c, llm_client, repo_root: s), \
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


def test_proposal_dependent_split_gives_only_the_calling_child_a_boundary_stub() -> None:
    """The realistic overflow case combined with cross-unit boundaries: two
    coupled services, a genuine proposal-dependent ASSIGN overflow (the
    preflight sees a unit that fits; the verbose PROPOSE response is what
    blows the real ASSIGN prompt), and a split of the unit that owns the
    cross-unit call. Proves the stub recomputation is driven by a real
    `UnitNeedsSplit` — not a mocked one — and that after the split only the
    child that actually contains the calling file carries the stub, no
    child carries the parent's pre-split aggregate, and no LLM request that
    goes out exceeds the budget."""
    from deepdoc.call_graph import CallEdge, CallGraph
    from deepdoc.llm.token_budget import build_prompt_budget, count_message_tokens
    from deepdoc.planner.engine import _plan_local as _real_plan_local
    from deepdoc.planner.partitioning import (
        build_planning_units,
        unit_likely_fits_budget,
    )

    scan = _service_scan({"orders": 6, "payments": 1})
    caller = "services/orders/module_00/component_00/handler.py"
    callee = "services/payments/module_00/component_00/handler.py"
    graph = CallGraph()
    # Three distinct call sites from one orders file: the parent unit's
    # aggregate is call_count=3, so a stale copy on a sibling child is
    # visible rather than coincidentally identical.
    for symbol in ("charge", "refund", "capture"):
        graph.add_edge(
            CallEdge(
                caller_file=caller,
                caller_symbol=f"handle_{symbol}",
                callee_file=callee,
                callee_symbol=symbol,
            )
        )
    scan.call_graph = graph

    llm = make_planner_llm()
    llm.capabilities = ModelCapabilities(
        model="test", capability_model="gpt-4o-mini", context_window_tokens=3000,
        max_output_tokens=100, source="test",
    )
    llm.output_reserve_tokens = 100
    cfg = _cfg()

    # The two services are the raw units, and the cheap preflight has no way
    # to know PROPOSE will come back verbose.
    raw_units = build_planning_units(scan)
    assert {u.slug for u in raw_units} == {"orders", "payments"}
    assert unit_likely_fits_budget(scan, llm) is True

    budget = build_prompt_budget(llm.capabilities, output_reserve_tokens=llm.output_reserve_tokens)
    maximum_input = budget.context_window_tokens - budget.output_reserve_tokens - budget.safety_tokens

    def _verbose_fake_llm_step(passed_llm, system, prompt, step_name):
        if step_name == "propose":
            files = sorted(set(_PATH_RE.findall(prompt)))
            return {
                "buckets": [
                    {
                        "slug": f"group-{i}",
                        "title": f"Group {i}",
                        "bucket_type": "feature",
                        "section": "Features",
                        "candidate_files": [f],
                        "description": "d",
                        "generation_hints": {
                            "padding": " ".join(
                                f"proposal_padding_{i}_{j}" for j in range(160)
                            )
                        },
                    }
                    for i, f in enumerate(files)
                ],
                "nav_structure": {
                    "Features": [f"group-{i}" for i, _f in enumerate(files)]
                },
            }
        if step_name == "assign":
            files = sorted(set(_PATH_RE.findall(prompt)))
            return {
                "buckets": [
                    {"slug": f"group-{i}", "owned_files": [f]}
                    for i, f in enumerate(files)
                ]
            }
        return _fake_llm_step(passed_llm, system, prompt, step_name)

    seen_token_counts: list[int] = []
    planned_units: list[PlanningUnit] = []

    def _measuring_llm_step(passed_llm, system, prompt, step_name):
        tokens, _ = count_message_tokens(system, prompt, passed_llm.capabilities)
        seen_token_counts.append(tokens)
        return _verbose_fake_llm_step(passed_llm, system, prompt, step_name)

    def _recording_plan_local(*args, **kwargs):
        planned_units.append(kwargs["unit"])
        return _real_plan_local(*args, **kwargs)

    with patch("deepdoc.planner.engine.run_phase2_scans", side_effect=lambda s, c, llm_client, repo_root: s), \
         patch("deepdoc.planner.engine._plan_local", side_effect=_recording_plan_local), \
         patch("deepdoc.planner.engine._llm_step", side_effect=_measuring_llm_step):
        plan = plan_docs(scan, cfg, llm)

    validate_plan_contract(plan)
    assert missing_files(scan, plan) == []

    units_meta = plan.classification.get("planning_units")
    assert units_meta is not None
    assert len(units_meta) > 2, "the overflowing orders unit must have been split"
    assert sum(u["file_count"] for u in units_meta) == 7

    # The pre-split orders unit really did get a 3-call aggregate stub...
    parent = next(u for u in planned_units if u.slug == "orders")
    assert [(s.remote_unit, s.call_count) for s in parent.boundary_stubs] == [
        ("payments", 3)
    ]
    # ...and every leaf child of it was recomputed from its own files only.
    # (Splitting is recursive, so an intermediate child that overflowed again
    # was itself planned before being split — only the leaves are final.)
    all_slugs = {u.slug for u in planned_units}
    leaves = [
        u
        for u in planned_units
        if u.slug.startswith("orders/part-")
        and not any(other.startswith(f"{u.slug}/part-") for other in all_slugs)
    ]
    assert len(leaves) > 1
    with_stub = [u for u in leaves if u.boundary_stubs]
    assert len(with_stub) == 1, "a stale parent aggregate would stub every child"
    assert caller in with_stub[0].files
    assert [(s.remote_unit, s.call_count) for s in with_stub[0].boundary_stubs] == [
        ("payments", 3)
    ]
    for child in leaves:
        if child is not with_stub[0]:
            assert child.boundary_stubs == ()
            assert caller not in child.files

    assert seen_token_counts, "expected at least one real _llm_step call"
    assert all(count <= maximum_input for count in seen_token_counts), (
        f"a real LLM request exceeded the budget: {max(seen_token_counts)} > {maximum_input}"
    )


def test_flow_candidates_are_built_before_unit_refinement() -> None:
    """The flow co-occurrence signal is only real if `scan.flow_candidates` is
    populated *before* refinement reads it. Its other builder lives in the
    global plan stage, which runs after every unit is planned — so without an
    earlier build the signal is silently dead in production."""
    from deepdoc.call_graph import CallEdge, CallGraph
    from deepdoc.scanner.common import EndpointBundle, EvidenceUnit

    scan = _service_scan({"orders": 2, "payments": 2})
    handler = next(p for p in scan.file_summaries if "/orders/" in p)
    other = next(p for p in scan.file_summaries if "/payments/" in p)
    scan.file_summaries["shared/helper.py"] = "shared helper | lines=10"

    # Phase 2 rebuilds the call graph from `parsed_files`, so inject it there
    # rather than assigning `scan.call_graph` up front.
    graph = CallGraph()
    for caller, symbol in ((handler, "handle"), (other, "charge")):
        graph.add_edge(
            CallEdge(
                caller_file=caller,
                caller_symbol=symbol,
                callee_file="shared/helper.py",
                callee_symbol="util",
            )
        )
    scan.endpoint_bundles = [
        EndpointBundle(
            endpoint_family="orders",
            methods_paths=["POST /orders"],
            handler_file=handler,
            handler_symbols=["handle"],
            evidence=[EvidenceUnit(file_path=handler, role="service")],
        )
    ]

    seen_counts: list[int] = []
    real_refine = engine_module.refine_unit_ownership

    def _spy(spied_scan, units, **kwargs):
        seen_counts.append(len(spied_scan.flow_candidates or []))
        return real_refine(spied_scan, units, **kwargs)

    with (
        patch("deepdoc.planner.engine.build_call_graph", return_value=graph),
        patch("deepdoc.planner.engine.refine_unit_ownership", side_effect=_spy),
        patch("deepdoc.planner.engine._llm_step", side_effect=_fake_llm_step),
    ):
        plan_docs(scan, _cfg(), make_planner_llm(), Path("."))

    assert seen_counts, "expected refine_unit_ownership to be called"
    assert seen_counts[0] > 0, (
        "flow candidates must already exist when refinement reads them"
    )


def test_cross_unit_context_is_offered_before_the_unbounded_inventories() -> None:
    """`fit_prompt_sections` fills optional sections greedily in list order and
    each one consumes the remaining budget, so the compact cross-unit stub
    section must be offered *before* the unbounded `file_summaries`/`endpoints`
    inventories — otherwise a tight budget can drop it on exactly the large
    multi-unit repos it exists for.

    Asserted on the section order rather than on a starved prompt: the additive
    per-record estimate in `fit_prompt_sections` overshoots the exact recount,
    so a saturating inventory usually still leaves enough slack for five lines
    to slip in. The ordering is the actual guarantee.
    """
    from deepdoc.planner.unit_boundaries import BoundaryStub

    scan = _service_scan({"orders": 3})
    unit = PlanningUnit(
        slug="orders",
        label="orders",
        files=tuple(scan.file_summaries),
        boundary_stubs=(
            BoundaryStub(
                remote_unit="payments",
                direction="outbound",
                score=3.0,
                call_count=3,
                evidence_kinds=("call",),
            ),
        ),
    )
    real_fit = engine_module.fit_prompt_sections
    orders: list[list[str]] = []

    def _spy(*args, **kwargs):
        optional = kwargs.get("optional_sections") or []
        orders.append([name for name, _ in optional])
        return real_fit(*args, **kwargs)

    with (
        patch("deepdoc.planner.engine.fit_prompt_sections", side_effect=_spy),
        patch("deepdoc.planner.engine._llm_step", side_effect=_fake_llm_step),
    ):
        _plan_local(scan, _cfg(), make_planner_llm(), Path("."), unit=unit)

    classify_order = next(o for o in orders if "cross_unit_context" in o)
    assert classify_order.index("cross_unit_context") < classify_order.index(
        "file_summaries"
    )
    assert classify_order.index("cross_unit_context") < classify_order.index(
        "endpoints"
    )
