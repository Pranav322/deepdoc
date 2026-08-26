# DeepDoc-Only Planning-Scale Gap-Fill — Slices A then B

> **Scope lock:** DeepDoc's *own* scanning/planning only. GitNexus is a later, optional upgrade and is NOT a prerequisite for any of this. Everything here must work on DeepDoc's existing `call_graph.py` / `topology.py` / `service_boundaries` signals alone. GitHub-issue commits stay scoped; nothing merges to `main` until Pranav visually approves a planned output.

## Why this, in one line

DeepDoc already computes (`service_boundaries`, `file_services`) and persists them, but **nothing consumes them for planning** — and the planner's `ASSIGN` step (`engine.py:310,338-341`) still requires the *entire* unresolved-repo file list in one prompt, which is the whole-repo ceiling. Slice A wires the already-computed service split into per-service planning (kills the wall, low risk). Slice B then improves the *quality* of those service boundaries by fusing the owner call graph + topology.

---

## Slice A — Make `file_services` load-bearing (per-service unit planning)

### Problem (verified, live code)
- `_detect_service_boundaries()` (`planner/engine.py:950`) and `_service_for_path()` (`engine.py:1002`) already assign `scan.file_services[rel] = service` during `scan_repo` (`engine.py:710-712`).
- `persistence_v2.py:547-548` persists both `service_boundaries` and `file_services`.
- **Nobody reads them** in the planner. `plan_docs` (`engine.py:21`) runs classify/propose/assign over the whole `scan`.
- `ASSIGN` requires the full `unresolved_files` list (`engine.py:310` `all_files_str`), so a repo whose unresolved set exceeds the model budget is unplannable (`fit_prompt_sections` raises, `token_budget.py:272-278`).

### Goal
Consume `scan.file_services` to partition the repo into **planning units**, run the existing classify→propose→assign per unit, merge into one `DocPlan`, and keep `validate_plan_contract` as the final global gate. Small repos (1 unit) must be byte-for-byte the today-path (regression-provable).

### Approach — repackage, don't rewrite
1. **New module `deepdoc/planner/partitioning.py`.**
   - `build_planning_units(scan, cfg) -> list[PlanningUnit]` (Slice A source = `scan.file_services`; if it's empty → a single `core` unit = today path).
   - `make_sub_scan(scan, unit_files) -> RepoScan` — read-only projection restricting the file-scoped collections (`file_contents`, `file_summaries`, `file_line_counts`, `source_kind_by_file`, `file_frameworks`, `entry_points`, `config_files`, `api_endpoints`, `topology_map` subgraph, `languages`) to `unit_files`; keep global (framework priorities etc.) as-is.
   - **Exact-token sizing, not `lines*17`:** per-unit candidates are accepted only after `count_message_tokens(render_unit_prompt(unit)) <= unit_budget`, with `fit_prompt_sections` kept as the backstop.
2. **Extract the current body** of `plan_docs` (*after* `run_phase2_scans`, before the global merge polish) into `_plan_one_unit(sub_scan, cfg, llm, ...) -> LocalPlan`.
3. **`plan_docs`** becomes: partition → loop `_plan_one_unit` per unit (serial first) → `merge` → existing global post-processing → `validate_plan_contract`.
4. **New module `deepdoc/planner/merge.py`.**
   - Deterministic slug namespacing: `{unit-slug}/{slug}` for multi-unit repos (only when >1 unit, so small-repo slugs are unchanged).
   - Union `orphaned_files` / `skipped_files` across units for the global coverage report.
   - `validate_plan_contract` runs unchanged, globally.

### Files touched (Slice A, grounded)
- `deepdoc/planner/partitioning.py` (new)
- `deepdoc/planner/merge.py` (new)
- `deepdoc/planner/engine.py` (extract `_plan_one_unit`; repackage `plan_docs`)
- `deepdoc/config.py` (partition.* keys: `unit_budget_fraction`≈0.7, `min_unit_files`, `max_units`, `namespacing` toggle)
- `deepdoc/pipeline_v2.py` (per-unit + global coverage panel)

### Tests (Slice A)
- One-service repo → output equals today's plan (regression; reuse existing `test_planner_*`).
- Two-service synthetic fixture → namespaced slugs, `validate_plan_contract` passes.
- Forced low-context model path → a repo that previously hard-failed now completes with per-service coverage.
- `count_message_tokens` gate: an indivisible oversized leaf must go coarse, never overflow or hard-fail. Track units already tested in `tests/`.

### Acceptance (Slice A)
- No `ModelCapabilityError` for a repo that used to raise on `ASSIGN`.
- 100% of in-scope files end up owned by a plan bucket or explicitly reported skipped/orphaned — nothing silently dropped.
- Multi-unit repo produces coherent global nav + service sections; coverage panel reports per-service.

---

## Slice B — Improve service boundaries via call graph + topology fusion

> Builds on A. Still DeepDoc-only — fuses DeepDoc's *existing* `call_graph.py` + `topology.py` output, not GitNexus.

### Problem
`_detect_service_boundaries` (Slice A source) is currently filesystem/config-driven. A big repo where services aren't nicely separated by directory (shared lib, monolith, framework glue) will yield weak/absent service tags → poor unit boundaries.

### Goal
Give `build_planning_units` a second, DeepDoc-owned signal: **services inferred from call-graph connectivity + topology clusters + entry/flow overlap** — used to *refine* `scan.file_services`, not replace them.

### Approach
1. After `scan.call_graph` / `scan.topology_map` are built, compute a connectivity-based refinement:
   - Use `topology_map` clusters (`build_topology_map`, `topology.py`) + `flow_candidates` (`build_flow_candidates`) as candidate grouping evidence.
   - Levy the existing `_foundational_files` handling (avoid a shared `BaseController`/`db.py` gluing every cluster).
   - Merge/detect a service boundary when a cluster has high internal call density and low cross-cluster call ratio to other service roots (reuse `topology.py`'s Jaccard / cross-edge-density spirit).
2. Represent a `PlanningUnit` with multiple evidence signals and a confidence:
   ```python
   @dataclass(frozen=True)
   class PlanningUnit:
       unit_id: str
       title: str
       parent_id: str | None
       file_paths: tuple[str, ...]
       symbol_ids: tuple[str, ...]
       entry_points: tuple[str, ...]
       process_ids: tuple[str, ...]
       incoming_edges: tuple[BoundaryEdge, ...]
       outgoing_edges: tuple[BoundaryEdge, ...]
       child_ids: tuple[str, ...]
       planning_mode: Literal["semantic","structural","coarse","unsupported"]
       confidence: float
       truncation_reasons: tuple[str, ...]
   ```
   (Deterministic + auditable; a pure provider-neutral unit card the planner consumes.)
3. Preserve cross-unit edges in the sub-scan so the planner doesn't lose `renderer→RPC→extension-host` relationships — Slice A's `make_sub_scan` should carry boundary stubs.

### Files touched (Slice B)
- `deepdoc/planner/partitioning.py` (connectivity refinement; boundary stubs)
- `deepdoc/planner/engine.py` (call the refinement where `call_graph`/`topology_map` exist)
- `deepdoc/v2_models.py` (`TopologyMap`/`flow` access already present)

### Tests (Slice B)
- A synthetic repo with a shared library + two caller services → correct boundary split despite the shared glue.
- Cross-unit edge stub preserved in sub-scan (assert the `RPC`/call boundary survives projection).
- Determinism: two runs → identical units.

---

## Sequencing
1. **A1:** `partitioning.py` + `make_sub_scan` + token gate; assert sub-scan correctness on a fixture.
2. **A2:** extract `_plan_one_unit`; prove one-unit output is byte-identical to today (`git diff` of generated plan on a small fixed repo).
3. **A3:** `merge.py` + namespacing; two-service fixture end-to-end with `validate_plan_contract`.
4. **A4:** coarse never-fails, per-unit + global coverage panel, config surface.
5. **B1:** connectivity refinement + `PlanningUnit` + boundary stubs; shared-glue fixture.
6. **B2:** full DeepDoc suite green (`.venv/bin/python -m pytest tests/ -q`), real mid-size monorepo end-to-end, coverage honest.

## Hard rules
- **No GitNexus dependency** in A or B. Provider seam left open for a later optional GitNexus unit-source, but nothing imports/requires it.
- **Nothing merges to `main` until Pranav reviews the planned output** (visual + plan contract).
- Every commit scoped; `.venv/bin/python` for tests.
- No silent degradation — coarse/incomplete units are flagged, never quiet.