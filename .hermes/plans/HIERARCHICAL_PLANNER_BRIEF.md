# DeepDoc Hierarchical Planner — Design Brief (Phase 2: "make it any-repo")

> Design document for breaking the single-prompt, whole-repo planning ceiling so DeepDoc can
> plan arbitrarily large and monorepo repositories. This is the **north-star architectural
> change** — everything else (language breadth, cost, hosted scale) depends on it.
>
> **Read this fully. VERIFY every `file:` seam against the live code before trusting it.**
> This is a *design* brief: it defines the architecture and the seam refactors. It is **not**
> yet a Claude-execution brief — get architecture sign-off first (see "Open decision gates"
> at the end), then this doc becomes the basis for a code brief.
> Ground truth: `CONCEPTS.md` (semantic map) + the repo `AGENTS.md`.

---

## 1. Problem (verified)

`COVERAGE_AUDIT.md` §4: the planner is **single-prompt and whole-repo**. The three planning
steps — classify, propose, assign — each build a prompt from the **entire** `scan`:

- classify: `planner/engine.py:87` `required_sections={"topology_clusters": ...}`
- propose: `planner/engine.py:260` `required_sections={"named_clusters": ...}`
- assign: **`planner/engine.py:310,338-342`** — `all_files_str = "\n".join(f"- {f}" for f in unresolved_files)` is a **REQUIRED** section; only `endpoints` is optional/trimmable.

`llm/token_budget.py:233-239` hard-fails when required sections exceed the model budget:
```python
if input_tokens > maximum_input:
    raise ModelCapabilityError(...)
```
There is **no chunking, no partition, no fallback.** Verified: `dde4ef5` (Phase 1) made the
failure *clean* (O(N), never overflows, clear error) but did **not** remove the wall — a
10k-file repo (e.g. `shopware/shopware`, 8,603 files) still dies in planning. `shopware's`
5%-then-fail profile is the anchor case (audit Addendum 3).

The **single most important fact**: the blocker is not language support or parser count — it
is that planning is single-prompt whole-repo. Fixing planning is the unlock.

---

## 2. Goal & non-goals

### Goal
Plan **repositories of any size / any service layout** by partitioning into planning units
that each fit the model budget, planning each unit with the **existing planner unchanged at
unit scope**, and merging into **one coherent `DocPlan`** — with `validate_plan_contract` kept
as the final global gate and **no silent degradation** (per-unit coverage surfaced).

### Non-goals (do NOT build in this phase)
- Language parsers / fallback source reader (separate workstream).
- Generation cost/affordability model (separate workstream).
- Route/framework correctness (Phase 1 delivered the discipline).
- Hosted product surface (separate workstream).
- Changing the per-page generate/evidence pipeline; the merge must be **plan-only**.

---

## 3. Approach — three new pieces, existing planner reused

The audit's Tier-3 item 9 wording is the contract: *"Plan per service/subtree, then merge:
partition → run classify/propose/assign per unit → merge into one `DocPlan` with
service-namespaced slugs → keep `validate_plan_contract` as the final global gate. This
reuses the existing planner unchanged and makes repo size bounded by **unit** size."*

That gives three new components and **one refactor seam**:

```
repo_scan ──► Partitioner ──► [Unit₁ sub_scan, Unit₂ sub_scan, …]   (new)
                       │
                       ▼
        existing plan_docs core (classify→propose→assign) run PER UNIT,  (reuse, unchanged)
        each call fed `unit.sub_scan` instead of the whole scan
                       │
                       ▼
        [unit DocPlan₁, unit DocPlan₂, …] ──► PlanMerger ──► global DocPlan  (new)
                       │                                           │
                       ▼                                           ▼
         global-only buckets (overview/intro/glossary/endpoint-refs)
                                                          validate_plan_contract (existing gate)
```

### 3.1 Partitioner — decide the units (new module: `deepdoc/planner/partitioning.py`)

**Input:** `RepoScan` (already carries `service_boundaries` + `file_services` — computed in
`planner/engine.py` scan_repo and persisted, but **currently read by nothing**; this work
makes it load-bearing).

**Unit = a set of rel-paths + a name + a service tag.** Strategy, in order of precedence:
1. **By detected/configured service boundary.** Use `scan.file_services` (dict rel→service)
   and `scan.service_boundaries` (list of {name, root}). Files not claimed by any service
   (root files, shared libs, top-level config) go into a **`core` unit**.
2. **Else by top-level directory.** Group the inventory by top-level dir under repo_root.
3. **Then greedy budget-fit.** Within each service/top-dir group, accumulate files into units
   up to a **per-unit target size** (see 3.3). A group that alone exceeds the target is split
   recursively on the next directory level (2nd-level dirs), then 3rd, down to leaf. A group
   that is **still oversized at leaf level** must NOT fail — it becomes its own unit and is
   planned with a **coarse/fallback policy** (see 3.4).
4. **Global-only unit.** A synthetic `core`/`global` unit holds repo-wide concerns: intro /
   getting-started, glossary, debug, and the cross-service API-reference / endpoint buckets.

Deterministic, recorded partitioning (log + telemetry: `partition->unit->files`), so a run is
reproducible and unit membership is auditable.

### 3.2 Sub-scan projection — the reuse seam (new function, e.g. `deepdoc/planner/partitioning.py:make_sub_scan(scan, unit_files)`)

The cleanest way to run the **existing** classify/propose/assign on a unit **without touching
their internals** is a thin, read-only projection of `scan` restricted to `unit_files`:

- `file_contents`, `file_summaries`, `file_line_counts`, `source_kind_by_file`,
  `file_frameworks` → filtered to `unit_files`.
- `entry_points`, `config_files`, `api_endpoints`/`published_api_endpoints` → filtered to
  entries whose file ∈ `unit_files`.
- `languages` → recomputed from the unit's files' suffixes.
- `topology_map` → **subgraph**: keep only clusters/nodes whose files ∈ `unit_files`; drop
  clusters that become empty. (Verify the exact shape of `TopologyMap` in
  `planner/topology.py` — clusters carry `file` lists; a filtered copy suffices.)
- `total_files` → len(unit_files). `file_services`/`service_boundaries` → preserved
  (the unit is one service).
- Everything the planner steps read that isn't file-scoped stays as-is (framework priorities,
  integration identities — those can be per-unit or global; decide at the merge).

Because classify/propose/assign only read these `scan.<attr>` collections, feeding them a
subset **reuses them unchanged** — they never know the repo is truncated. This is the
audit's "unchanged" requirement and it keeps Phase-1 correctness (slug dedupe, coverage,
fit-guarantee) intact automatically.

### 3.3 Per-unit token budget

Each unit must fit: `build_prompt_budget` (token_budget) yields `maximum_input`. Reserve a
**global slice** (used by final merge + global buckets) and size each unit so classify /
propose / assign stay under the per-unit budget. Simple deterministic target:
**`unit_target = int(maximum_input * unit_budget_fraction)`** (default ~0.7, configurable),
minus the fixed prompt/template overhead the steps carry. Feasibility estimate from line
counts (`file_line_counts` × ~15–20 tokens/line) so the partitioner sizes groups before any
LLM call. Keep `fit_prompt_sections` as the runtime backstop — if a unit still
can't fit even with a coarse policy, we degrade to a fallback page for it, **never** a
hard failure.

### 3.4 Coarse / fallback policy for an un-compressible unit

A single leaf directory that alone exceeds the budget (a giant monolith submodule) is planned
at coarse granularity instead of failing: one bucket per top-2-level subtree with deterministic
grouping and **no** expensive classify/propose per-file detail. These coarse buckets are
**explicitly flagged** in the plan metadata and surface in the coverage panel as
"planned-coursely" so the user sees it — no silent degradation. (For the full "fallback
reader" upgrade this unit later gets real prose; out of scope here.)

### 3.5 PlanMerger — combine unit plans into one global DocPlan (new module: `deepdoc/planner/merge.py`)

- **Slug namespacing (the load-bearing merge rule).** Each unit's proposed slugs are prefixed
  deterministically: `{unit_name}/{slug}` for service/top-dir units, unbounded for the global
  unit. This **prevents cross-unit collisions by construction** (two services both have an
  `auth` module → `service-auth/auth` vs `service-billing/auth`), which makes the Phase-1
  `_deduplicate_bucket_slugs` a genuine last-resort safety net rather than the collision arbiter.
  Verify slug charset/URL rules (site is Next.js/Fumadocs, root-absolute `/slug` paths).
- **Global buckets.** Intro/getting-started/glossary/debug and cross-service API-reference are
  planned once (global or `core` unit) and merged with their slugs *un*prefixed. Introduction
  invariant stays: exactly one intro bucket globally.
- **Nav assembly.** Per-unit nav sections are merged into the global nav. Section ordering uses
  the existing topology-depth logic (`nav_shaping.py::_section_sort_key`) with a per-unit depth
  base; configurable grouping so service-level sections read naturally (Start Here / Service A
  / Service B / …). Decide (open gate G4) whether nav is strictly per-service-siloed or
  merged by shared section names.
- **Cross-unit integrity.** `orphaned_files` and `skipped_files` are unioned across units for
  the global coverage report. Cross-unit links/`See also` are the **generation-time**
  consistency pass's job, not the planner's (Addendum §A: generation only needs source).
- **Global gate.** Run `validate_plan_contract` over the merged plan — unchanged, final.

### 3.6 Orchestration refactor (`planner/engine.py::plan_docs`)

Repackage, don't rewrite: the current classify→propose→assign body becomes a
**`_plan_one_unit(sub_scan, cfg, llm, ...) -> LocalPlan`** helper; `plan_docs` becomes:
partition → loop `_plan_one_unit` per unit → merge → global refine steps
(`_refine_bucket_ownership`, `_decompose_buckets`, bucket injection, endpoint refs) →
`validate_plan_contract`. When exactly **one unit** results (small repo, no services), the
path is functionally the today-path (regression-provable).

Fallback ladder (never crash): unit fits → classify; unit misses → coarse policy (3.4);
planning LLM fails → current `_fallback_plan` per unit, then merge.

---

## 4. Instrumentation & acceptance

- **Coverage per unit + global.** Reuse/extend the Phase-1 `_print_coverage` panel: show
  documented / skipped / orphaned per service, then repo-total. A large repo must report
  meaningful (>~60% of source documented or explicitly skipped/unsupported) coverage instead
  of a 5%-and-pretend-ok result.
- **Telemetry.** Partition → unit → step timings; per-unit LLM calls/tokens; merged bucket
  count. (Follow `telemetry.py` + SPEED_AUDIT_P0.1 conventions.)
- **Acceptance gate:** the `COVERAGE_AUDIT.md` shopware anchor — a 8.6k-file repo must plan
  to completion within budget with per-service coverage reported, and `validate_plan_contract`
  must pass with service-namespaced slugs. This is bench-generated locally on a synthetic large
  multi-service fixture (no need to run real shopware), plus an end-to-end on a mid-size
  monorepo fixture.

---

## 5. Files touched (grounded)

| Component | File | What |
|---|---|---|
| Partitioner | `deepdoc/planner/partitioning.py` (new) | unit detection, greedy budget-fit, `make_sub_scan` |
| Sub-scan | `deepdoc/planner/partitioning.py` | read-only `RepoScan`-shaped projection |
| Merger | `deepdoc/planner/merge.py` (new) | namespacing, global buckets, nav assembly, plan merge |
| Orchestration | `deepdoc/planner/engine.py` | `plan_docs` → partition/loop/merge; `_plan_one_unit` |
| Reuse points | `deepdoc/planner/heuristics.py`, `token_budget.py`, `topology.py`, `nav_shaping.py`, `plan_contract.py` | called unchanged at unit + global scope |
| Service signal | `deepdoc/v2_models.py`, `persistence_v2.py` | make `file_services` load-bearing (already computed/persisted) |
| Reports | `deepdoc/pipeline_v2.py` | per-unit + global coverage panel |
| Config | `deepdoc/config.py` | `planner.partition.*` (unit_budget_fraction, min_unit_files, max_units, namespacing) |
| Docs | `AGENTS.md`, `README.md`, `CONCEPTS.md` | planner architecture update |

---

## 6. Risks & mitigations

- **Cross-unit proposal coherence.** Independent per-unit proposals can disagree on framing of
  shared concepts. Mitigation: global classify profile is shared as context to every unit;
  global-only buckets own shared framing; consistency pass repairs link gaps.
- **Slug namespacing changes URLs.** Existing docs' slugs change on regenerated monorepos.
  Mitigation: namespacing only activates when >1 unit exists (small repos keep today's slugs);
  stable `{unit}/{slug}` scheme documented; consider an update/redirect path for already-published
  monorepo docs (open gate).
- **Merge cost.** Merging hundreds of buckets + running global nav/decompose could itself strain
  the budget. Mitigation: merge is truncation-friendly and mostly deterministic; global refine
  steps operate on bucket metadata, not raw file inventory, so they stay small.
- **Budget estimate drift.** Line×token estimates are approximate. Mitigation: `fit_prompt_sections`
  remaining as runtime backstop, plus coarse-policy degrade (3.4) — never hard-fail.

---

## 7. Open decision gates (sign these before the code brief)

- **G1 — Namespacing format:** `service-slug/{slug}` vs `{top-dir}/{slug}` vs flat-with-six-char-hash
  suffix. (Recommend `{unit-slug}/{slug}`, readable; hash-suffix only on collision.)
- **G2 — Unit-budget fraction & concurrency:** one unit at a time (serial, simplest, safest on
  rate limits) vs N units in parallel (faster, more tokens in-flight). Phase 1 already has a
  concurrency limiter; recommend **serial-first**, parallel as a later kwin.
- **G3 — Global vs `core`-unit ownership of cross-service buckets:** separate global planning
  pass, or fold into the `core` unit? (Recommend a dedicated global pass for intro/glossary/
  API-ref; service units never own global buckets.)
- **G4 — Nav structure:** strict per-service silos vs merged-by-shared-section. (Recommend
  per-service top-level sections with a shared "Start Here.")
- **G5 — Migration:** acceptable to change monorepo doc slugs (no redirect first cut), or must
  we add a redirect map before shipping? (Recommend: accept slug change in this phase; note for
  hosted users.)
- **G6 — Scope of this phase's proof:** just the planner merge on synthetic multi-service
  fixtures, or also the shopware-scale end-to-end? (Recommend: synthetic multi-service fixture
  + one real mid-size monorepo; shopware itself is optional and heavier.)

---

## 8. Suggested sequencing

1. Partitioning + `make_sub_scan` on a fixture; assert sub-scan subgraph correctness.
2. `_plan_one_unit` (extract existing body); prove one-unit output == today's output
   (regression test).
3. Merger + namespacing; two-service synthetic fixture end-to-end.
4. Coarse policy + coverage-per-unit panel; no-hard-fail property test (giant dir).
5. Config surface + docs; shopware-scale/optional acceptance run.

Each step lands a green, reviewable commit on a feature branch; nothing merges to main until
Pranav visually approves a planned output.