# Semantic Graph + Hierarchical Documentation Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task. This document is planning only. Before implementation, re-open every referenced file and verify names/signatures against the live branch. Do not copy GitNexus source. Do not enable, distribute, invoke, or ship a GitNexus integration until written commercial permission covers the intended use.

**Goal:** Introduce a provider-neutral repository semantic graph, prove its quality, and make it the substrate for graph-derived hierarchical documentation planning while preserving DeepDoc's existing evidence, validation, update, site, and chatbot systems.

**Architecture:** DeepDoc owns a stable `RepositorySemanticGraph` contract and all downstream planning/generation logic. Existing DeepDoc analysis is adapted into that contract first, so development and tests can proceed without GitNexus. After licensing approval, a separately gated GitNexus adapter may populate the same contract through a versioned read-only boundary. Planning derives services and subsystems from workspace evidence, weighted graph communities, and entry-point reachability; it plans serially per unit, merges deterministically, then runs the existing global plan contract.

**Tech Stack:** Python 3.10+, dataclasses, existing Tree-sitter parsers, existing DeepDoc planner/generator, JSON persistence, pytest. Optional licensed sidecar: GitNexus 1.6.x, Node.js, HTTP/NDJSON or CLI JSON. No new graph database is required for the first implementation.

---

## 1. Fixed decisions

These defaults remove ambiguity for implementation:

1. **DeepDoc owns the semantic schema.** No downstream module accepts GitNexus-specific IDs, LadybugDB rows, or relationship names directly.
2. **Existing behavior remains the default until parity is proved.** `semantic_graph.provider: native` and `planner.mode: topology` initially preserve the current pipeline. The graph planner ships only after acceptance tests pass.
3. **GitNexus is a provider, not the product architecture.** It may supply graph records after licensing; DeepDoc still owns partitioning, planning, evidence, validation, persistence, updates, site generation, and chat.
4. **No GitNexus source copying.** The adapter consumes documented runtime output only. The public PolyForm-Noncommercial repository remains research evidence, not an implementation source.
5. **Serial-first planning.** Planning units execute one at a time in the first release. Parallel unit planning is a later optimization after correctness and rate-limit behavior are measured.
6. **Readable slug namespaces.** Multi-unit pages use `{unit-slug}/{local-slug}`. Single-unit repositories retain existing slugs. Hashes are collision fallbacks only.
7. **Dedicated global planning pass.** Introduction, repository architecture, glossary, cross-service/API overview, shared infrastructure, and deployment topology belong to a global pass rather than an arbitrary `core` service.
8. **Service-siloed navigation.** `Start Here` is global; each service gets a top-level section; shared/global material follows; testing/supporting material remains at the tail.
9. **No silent degradation.** Every graph/provider/trace/partition truncation is persisted and surfaced as coverage metadata.
10. **Graph absence is not proof of no dependency.** Unresolved edges and omitted/truncated traces remain explicit records.

---

## 2. Release and license gates

### Allowed before commercial-license approval

- Define provider-neutral graph models and protocols.
- Adapt DeepDoc's existing `CallGraph`, parsed files, routes, runtime scans, and service signals into the new graph.
- Build graph queries, native entry-point discovery, process tracing, community/unit derivation, planner projection/merge, tests, and benchmarks.
- Write a mock/fixture external-provider adapter contract.
- Run non-shipping local research benchmarks only if they comply with the current license and are not incorporated into a commercial service.

### Blocked until written approval

- Bundling or installing GitNexus from DeepDoc.
- Invoking GitNexus during a commercial DeepDoc run.
- Shipping a `gitnexus` provider option.
- Reading GitNexus's internal LadybugDB schema as a production dependency.
- Advertising GitNexus-backed language coverage.
- Copying or porting GitNexus implementation code.

### Required written terms before enabling the adapter

- Commercial runtime use, modification, deployment, and redistribution rights.
- Whether subprocess/sidecar/SaaS use is permitted.
- Coverage of `gitnexus-shared`, CLI/HTTP output, schemas, and bundled grammars.
- Stable supported API/export contract and versioning policy.
- Attribution requirements.
- Third-party dependency obligations.
- Security fixes/support, termination, and continued-use rights for pinned versions.

---

## 3. Target data flow

```text
Repository
  │
  ├─ native DeepDoc scanner/parser/call graph ─┐
  │                                            │
  └─ licensed external graph provider (later) ─┤
                                               ▼
                              RepositorySemanticGraph v1
                              nodes + edges + confidence
                              entry points + processes
                              communities + truncations
                                               │
                         ┌─────────────────────┴─────────────────────┐
                         ▼                                           ▼
                Graph quality report                      Workspace/service discovery
                                                                      │
                                                                      ▼
                                                        Hierarchical planning units
                                                                      │
                                                                      ▼
                                                    serial local plans + global pass
                                                                      │
                                                                      ▼
                                                        deterministic PlanMerger
                                                                      │
                                                                      ▼
                                                        validate_plan_contract
                                                                      │
                                                                      ▼
                                      existing DeepDoc evidence/generation/validation
```

---

## 4. Provider-neutral schema

Create a compact schema sufficient for planning and evidence without reproducing every possible program-analysis detail.

### `SemanticNode`

Required fields:

- `id`: provider-neutral stable ID generated by DeepDoc
- `kind`: project/package/service/file/symbol/route/task/tool/datastore/external/config
- `name`, `qualified_name`
- `file_path`, `start_line`, `end_line`
- `language`, `symbol_kind`, `visibility`
- `service_id`, `package_id`
- `metadata`: bounded provider-neutral facts

### `SemanticEdge`

Required fields:

- `source_id`, `target_id`
- `kind`: contains/defines/imports/calls/accesses/uses/extends/implements/instantiates/registers/injects/handles/publishes/subscribes/reads/writes/invokes_external/configures/deploys
- `confidence`: `[0.0, 1.0]`
- `resolution`: exact/probable/ambiguous/unresolved/external
- `reason`
- `evidence`: source file + line/range where available
- `provider`

### `SemanticEntryPoint`

- `kind`: http/cli/main/public_api/event_consumer/scheduler/task/plugin/serverless/test/build/ui
- `node_id`, label, framework, trigger
- confidence/evidence

### `SemanticProcess`

- stable ID/title/entry-point IDs
- ordered steps and edge IDs
- tails/effects
- confidence/score
- truncation flags: depth, branching, candidate cap, trace budget

### `SemanticCommunity`

- ID/label/member node IDs
- hierarchy level and optional parent
- cohesion/modularity
- derivation signals

### `GraphCoverage`

- discovered/parsed/indexed files
- symbols by language/type
- edges by kind/resolution
- unresolved in-program references
- external references
- omitted/truncated entry points/processes
- unsupported/skipped files
- provider/version/schema identity

---

## 5. Detailed implementation sequence

### Task 0: Establish an isolated feature branch and baseline

**Objective:** Preserve the current clean baseline and keep the two research documents separate from implementation commits.

**Files:** No code changes.

**Steps:**

1. Verify current branch/HEAD and working tree.
2. Preserve the existing untracked research files:
   - `deepdoc/GITNEXUS_FEASIBILITY_AUDIT.md`
   - `deepdoc/HIERARCHICAL_PLANNER_BRIEF.md`
3. Create a feature branch such as `feature/semantic-graph-planner` only when implementation begins.
4. Run the baseline suite with the repository virtualenv:

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m compileall deepdoc
```

**Expected:** Current baseline remains 529 passed / 3 skipped unless main has legitimately advanced; record the actual result rather than forcing this historical count.

**Commit:** None for baseline inspection.

---

### Task 1: Define `RepositorySemanticGraph` v1

**Objective:** Add a provider-neutral, serializable semantic graph with stable IDs, adjacency queries, confidence, evidence, and coverage metadata.

**Files:**

- Create: `deepdoc/semantic_graph/__init__.py`
- Create: `deepdoc/semantic_graph/models.py`
- Create: `deepdoc/semantic_graph/graph.py`
- Create: `deepdoc/semantic_graph/serialization.py`
- Test: `tests/test_semantic_graph_models.py`
- Test: `tests/test_semantic_graph_serialization.py`

**TDD steps:**

1. Write failing tests for deterministic node IDs, edge deduplication, outgoing/incoming lookup, file/symbol lookup, confidence bounds, and v1 JSON round-trip.
2. Run focused tests and confirm missing-module/model failures.
3. Implement immutable record dataclasses plus a mutable indexed graph container.
4. Reject malformed IDs, dangling edges, non-normalized paths, invalid confidence, and unknown schema versions.
5. Add deterministic ordering to serialization.
6. Re-run focused tests.

**Required design constraints:**

- Do not replace `CallGraph` yet.
- Do not import GitNexus packages or types.
- Metadata must remain JSON-safe and bounded.
- IDs must survive provider changes where the same file/range/qualified symbol is rediscovered.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_semantic_graph_models.py tests/test_semantic_graph_serialization.py -q
```

**Commit:** `feat: add provider-neutral semantic graph schema`

---

### Task 2: Add the provider protocol and native DeepDoc adapter

**Objective:** Populate `RepositorySemanticGraph` from existing DeepDoc scan artifacts without changing planner output.

**Files:**

- Create: `deepdoc/semantic_graph/provider.py`
- Create: `deepdoc/semantic_graph/native_provider.py`
- Modify: `deepdoc/v2_models.py`
- Modify: `deepdoc/planner/engine.py` near `scan_repo()` construction
- Test: `tests/test_native_semantic_graph_provider.py`
- Update later in same task if behavior is persisted: `deepdoc/AGENTS.md` or root `AGENTS.md` after verifying canonical documentation ownership

**Source seams to verify:**

- `deepdoc/call_graph.py::CallGraph`, `CallEdge`, `GraphRelation`
- `deepdoc/v2_models.py::RepoScan`
- `deepdoc/planner/engine.py::scan_repo`
- Route/runtime/database/integration records already attached to `RepoScan`

**TDD steps:**

1. Build a fixture scan with parsed symbols, imports, calls, a route, runtime task, and external integration.
2. Assert normalized file/symbol/route/task nodes and typed edges.
3. Assert every imported relation carries `provider="native"`, confidence, reason, and evidence when available.
4. Assert unresolved/external calls are retained rather than dropped.
5. Implement `SemanticGraphProvider` and `NativeSemanticGraphProvider`.
6. Attach the resulting graph to `RepoScan.semantic_graph` while retaining `RepoScan.call_graph` for compatibility.
7. Confirm existing planner tests are byte/structurally unchanged where appropriate.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_native_semantic_graph_provider.py tests/test_call_graph.py -q
```

**Commit:** `feat: adapt native scan output to semantic graph`

---

### Task 3: Add graph persistence and identity

**Objective:** Persist lightweight semantic graph state safely and invalidate it when schema/provider identity changes.

**Files:**

- Modify: `deepdoc/persistence_v2.py`
- Modify: `deepdoc/v2_models.py`
- Create: `tests/test_semantic_graph_persistence.py`
- Modify: `tests/test_state.py` if canonical persistence tests live there

**Plan:**

- Store graph data in `.deepdoc/semantic_graph.json` or compressed equivalent; do not inflate `scan_cache.json` with the whole graph.
- Store schema version, provider, provider version, graph fingerprint, commit SHA, file hashes, and coverage/truncation metadata.
- Use `atomic_write_json`/`atomic_write_text`.
- A schema/provider mismatch must reject the graph and trigger rebuild, not partially load it.
- Do not persist timing observations as correctness state.
- Update `ENGINE_FINGERPRINT` only when the new graph becomes planning-load-bearing, not merely when an unused file is introduced.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_semantic_graph_persistence.py tests/test_state.py -q
```

**Commit:** `feat: persist versioned semantic graph state`

---

### Task 4: Build provider-independent graph query services

**Objective:** Stop planner/generator code from reaching into graph internals such as `CallGraph._callees`.

**Files:**

- Create: `deepdoc/semantic_graph/queries.py`
- Test: `tests/test_semantic_graph_queries.py`
- Later consumers: `deepdoc/planner/topology.py`, `deepdoc/planner/flow_candidates.py`, `deepdoc/generator/evidence.py`

**Required queries:**

- nodes/edges by file, symbol, kind, service, package
- callers/callees with minimum confidence and allowed resolutions
- file-level weighted adjacency
- entry-point neighborhood
- reachable subgraph with explicit depth/branch/edge budgets
- cross-community/service edges
- effect/tail nodes
- unresolved-reference summary

**TDD steps:**

1. Write graph fixtures with cycles, ambiguous edges, external tails, and mixed confidence.
2. Verify deterministic traversal and explicit truncation reports.
3. Ensure cycles terminate and no private graph storage is exposed.
4. Implement queries.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_semantic_graph_queries.py -q
```

**Commit:** `feat: add semantic graph query layer`

---

### Task 5: Broaden native entry-point and tail taxonomy

**Objective:** Generalize DeepDoc's current endpoint/task/scheduler flow seeds without depending on GitNexus.

**Files:**

- Create: `deepdoc/semantic_graph/entrypoints.py`
- Create: `deepdoc/semantic_graph/effects.py`
- Modify: `deepdoc/planner/flow_candidates.py`
- Test: `tests/test_semantic_entrypoints.py`
- Extend: `tests/test_flow_candidates.py`

**Entry kinds:** HTTP, CLI, `main`/bootstrap, public library API, task, scheduler, event consumer, plugin activation, serverless handler, UI handler, test/build target.

**Tail/effect kinds:** response/output, DB read/write, external HTTP/RPC, event publish, filesystem mutation, process spawn, UI-state mutation, artifact emission.

**Behavior:**

- Existing endpoint/runtime detection remains authoritative where available.
- Generic graph patterns add candidates with lower confidence.
- Every candidate records detection reason and evidence.
- Unknown sinks remain unknown; never relabel a leaf as a business effect without evidence.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_semantic_entrypoints.py tests/test_flow_candidates.py -q
```

**Commit:** `feat: generalize semantic entry points and effects`

---

### Task 6: Replace global top-N flows with bounded, on-demand process tracing

**Objective:** Produce honest process candidates globally and allow deeper expansion for a chosen service/subsystem.

**Files:**

- Create: `deepdoc/semantic_graph/processes.py`
- Modify: `deepdoc/planner/flow_candidates.py` as compatibility facade
- Test: `tests/test_semantic_process_tracing.py`

**Requirements:**

- Configurable depth, branching, trace budget, confidence threshold, and candidate cap.
- Truncation counters in every result and aggregate coverage.
- Cycle/SCC-aware traversal.
- Documentation-oriented ranking: explicit entry and meaningful tail outrank depth alone.
- Terminal diversity so one helper family cannot monopolize all traces.
- On-demand tracing scoped to a service/community for planning and evidence.
- Keep the existing `FlowCandidate` interface operational until consumers migrate.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_semantic_process_tracing.py tests/test_flow_candidates.py -q
```

**Commit:** `feat: add bounded semantic process tracing`

---

### Task 7: Introduce weighted graph communities and hierarchy

**Objective:** Discover subsystem candidates using multiple structural signals while treating directories as evidence, not truth.

**Files:**

- Create: `deepdoc/semantic_graph/communities.py`
- Create: `deepdoc/semantic_graph/workspaces.py`
- Modify: `deepdoc/planner/topology.py` through an adapter path, not a destructive rewrite
- Test: `tests/test_semantic_communities.py`
- Test: `tests/test_workspace_boundaries.py`
- Extend/create: `tests/test_topology.py` if no canonical topology test currently exists

**Signals and default weights:**

- Explicit workspace/package/deploy boundary: strongest
- Calls: strong
- Imports: medium
- Implements/extends/DI/registers: medium-strong
- Entry-point reachability overlap: strong
- Same directory/name tokens: weak
- Semantic similarity: optional and never sole evidence

**Hierarchy:**

1. Explicit service/workspace/package roots
2. Subsystem communities within each root
3. Foundational/shared component cluster
4. Cross-service dependency overlay

**Rules:**

- Deterministic output under stable input.
- Isolated nodes must remain accounted for.
- Community labels are hints; LLM naming occurs later.
- Store membership evidence and cohesion.
- Do not require Neo4j/LadybugDB.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_semantic_communities.py tests/test_workspace_boundaries.py -q
```

**Commit:** `feat: derive hierarchical semantic communities`

---

### Task 8: Build the graph-quality evaluation harness

**Objective:** Make provider selection empirical rather than feature-list-driven.

**Files:**

- Create: `deepdoc/semantic_graph/evaluation.py`
- Create: `deepdoc/semantic_graph/cli_report.py` or integrate with `deepdoc/benchmark_v2.py` after verifying the cleanest seam
- Create: `tests/fixtures/semantic_graph/`
- Create: `tests/test_semantic_graph_evaluation.py`
- Modify: `deepdoc/benchmark_v2.py`

**Metrics:**

- discovered vs parsed vs indexed files
- symbol extraction precision/recall on curated fixtures
- call/import resolution precision/recall
- unresolved in-program rate
- entry-point precision/recall
- process usefulness and tail accuracy
- cluster cohesion/stability and boundary accuracy
- wall time and peak RSS
- incremental/full equivalence
- truncation/omission counts

**Fixture matrix:**

- Python service
- TypeScript app/monorepo
- Go service
- PHP/Laravel service
- Vue front end
- Rust crate
- Java/Spring service
- C/C++ project
- Mixed multi-service monorepo
- Generated 10k-file structural fixture without committing 10k source files

**Provider comparison:** Native provider now; licensed GitNexus provider later. Report `unknown/not measured` rather than fabricated values.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_semantic_graph_evaluation.py -q
.venv/bin/python -m deepdoc.cli benchmark --help
```

**Commit:** `feat: add semantic graph quality benchmark`

---

### Task 9: Define the external graph adapter contract without GitNexus code

**Objective:** Prepare a stable ingestion boundary while licensing is pending.

**Files:**

- Create: `deepdoc/semantic_graph/external_contract.py`
- Create: `deepdoc/semantic_graph/providers/json_provider.py`
- Test: `tests/test_external_graph_contract.py`
- Create fixture: `tests/fixtures/semantic_graph/external_graph_v1.json`

**Contract:**

- NDJSON or JSON records for provider metadata, nodes, edges, entry points, communities, processes, and coverage.
- Strict schema/version validation.
- Path normalization and repository-root escape rejection.
- Size/count limits and streaming ingestion.
- Unknown provider node/edge kinds preserved in namespaced metadata but ignored safely by planners.
- No executable command construction in this task.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_external_graph_contract.py -q
```

**Commit:** `feat: define external semantic graph contract`

---

### License Gate A: Implement the GitNexus adapter only after approval

**Objective:** Import licensed GitNexus output through the external contract.

**Files likely after approval:**

- Create: `deepdoc/semantic_graph/providers/gitnexus.py`
- Create: `tests/test_gitnexus_adapter.py`
- Create: `tests/integration/test_gitnexus_adapter_live.py` marked optional
- Modify: `deepdoc/config.py`
- Modify: `deepdoc/cli.py`
- Modify: `README.md`, `AGENTS.md`, `CHANGELOG.md`

**Recommended interface:** Prefer a negotiated stable HTTP/NDJSON graph export. Use CLI JSON for the spike only. Avoid direct LadybugDB coupling unless Akon Labs guarantees schema/version compatibility.

**Security requirements:**

- Execute an explicit configured binary path with `subprocess` argv, never a shell string.
- Time, memory, output-size, and repository-path bounds.
- No API keys or source contents in logs.
- Verify provider version and schema before import.
- Fail closed on partial/malformed output.

**Feature gate:**

```yaml
semantic_graph:
  provider: native       # gitnexus unavailable until licensed build
  external:
    enabled: false
```

**Shipping gate:** Packaging/CI must fail if the unlicensed adapter dependency is included in a release artifact before the license receipt/config gate exists.

---

### Task 10: Derive budget-aware planning units from the semantic graph

**Objective:** Replace directory-first partitioning with graph-informed planning units.

**Files:**

- Create: `deepdoc/planner/partitioning.py`
- Modify: `deepdoc/v2_models.py` if `PlanningUnit` belongs there; prefer a planner-local model first
- Test: `tests/test_planner_partitioning.py`

**Precedence:**

1. Explicit workspace/deployable/service boundaries
2. Graph communities within those boundaries
3. Entry-point/process ownership
4. Shared/foundational cluster
5. Budget subdivision
6. Directory fallback only when graph evidence is absent

**`PlanningUnit` fields:**

- ID/name/slug/root/service/package
- owned files/symbols/communities/processes/entry points
- shared dependencies
- cross-unit edges
- estimated prompt sizes
- confidence and derivation evidence
- coarse/truncated flags

**Budget behavior:**

- Use actual planner prompt components and token counter where possible, not line-count × guessed tokens alone.
- Split oversized units recursively by child communities, then package/subtree.
- A single oversized leaf uses symbol/process slices and explicit coarse metadata; it does not silently invent a complete plan.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_planner_partitioning.py -q
```

**Commit:** `feat: derive graph-aware planning units`

---

### Task 11: Implement complete sub-scan projection

**Objective:** Reuse the current planner at unit scope without leaking out-of-unit records or mutating the original scan.

**Files:**

- Modify: `deepdoc/planner/partitioning.py`
- Test: `tests/test_planner_subscan.py`

**Every `RepoScan` field must be classified:**

- Filter by unit files: summaries, lines, parsed files, contents, hashes, source kinds, frameworks, endpoints, bundles, integrations, runtime, database, GraphQL, Knex, debug, config impacts, graph, topology, flows.
- Recompute: languages, frameworks, total files, file tree, entry points, config files, unsupported/skip coverage where unit-specific.
- Preserve global read-only facts only when the planner needs them and label their scope.
- Never claim the sub-scan is a complete repository scan.

**Key acceptance:** Mutation of any projected collection must not mutate the parent `RepoScan`.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_planner_subscan.py -q
```

**Commit:** `feat: project complete planner sub-scans`

---

### Task 12: Extract `_plan_one_unit` without behavior changes

**Objective:** Refactor the current classify → propose → assign path into a reusable function while proving one-unit parity.

**Files:**

- Modify: `deepdoc/planner/engine.py`
- Extend: `tests/test_planner_assignment_partition.py`
- Create: `tests/test_planner_single_unit_parity.py`

**Requirements:**

- `plan_docs()` still performs Phase 2 scan upgrades once globally.
- `_plan_one_unit()` receives an already-enriched projected scan.
- Unit planning includes classify, propose, assign, local refinement, and local coverage only.
- Global-only injections, global nav shaping, final orphans, and final contract validation remain outside unit planning.
- With one unit and graph planner disabled, call sequence and plan output match current behavior.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_planner_single_unit_parity.py tests/test_planner_assignment_partition.py tests/test_planner_granularity.py tests/test_planner_consolidation.py -q
```

**Commit:** `refactor: isolate single-unit planner pipeline`

---

### Task 13: Implement deterministic `PlanMerger`

**Objective:** Merge independently planned units into one coherent, valid global plan.

**Files:**

- Create: `deepdoc/planner/merge.py`
- Test: `tests/test_plan_merge.py`
- Extend: `tests/test_plan_contract.py`

**Merge rules:**

- Namespace local slugs only when more than one unit exists.
- Rewrite `parent_slug`, `depends_on`, nav references, and generation cross-links consistently.
- Preserve stable semantic IDs and existing slugs during targeted replans when identity matches.
- Exactly one global introduction.
- Union skipped/orphaned/coverage metadata without duplication.
- Retain cross-unit dependency edges for global planning and evidence.
- Global-only buckets are created after local merge.
- Run `_deduplicate_bucket_slugs` only as a final safety net.
- Run `validate_plan_contract()` on the merged full plan.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_plan_merge.py tests/test_plan_contract.py -q
```

**Commit:** `feat: merge namespaced unit documentation plans`

---

### Task 14: Add the global architecture planning pass

**Objective:** Generate repository-level pages from compressed unit summaries and cross-unit graph relationships—not raw whole-repository source.

**Files:**

- Create: `deepdoc/planner/global_planning.py`
- Modify: `deepdoc/planner/engine.py`
- Modify: prompt files under `deepdoc/prompts/` after verifying canonical ownership
- Test: `tests/test_global_planning.py`

**Inputs:**

- unit profile/title/description
- principal entry points and processes
- public interfaces
- datastores/external integrations
- shared/foundational dependencies
- cross-unit edges
- unit coverage/confidence/truncation

**Outputs:**

- one introduction
- repository architecture
- service map
- cross-service interactions
- deployment/configuration overview when evidenced
- shared infrastructure
- glossary/API overview when warranted
- service top-level nav sections

**Constraint:** No required prompt section may contain the full raw file inventory. Metadata must itself be hierarchically summarized if it exceeds the model budget.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_global_planning.py tests/test_plan_merge.py -q
```

**Commit:** `feat: add graph-grounded global planning pass`

---

### Task 15: Integrate graph-neighborhood evidence

**Objective:** Use the semantic graph to select relevant evidence per page without weakening DeepDoc's existing source and validation guarantees.

**Files:**

- Modify: `deepdoc/generator/evidence.py`
- Modify: `deepdoc/generator/validation.py`
- Extend/create: `tests/test_evidence_graph_context.py`
- Extend: graph-related generator tests after locating canonical files

**Behavior:**

- Prioritize owned symbols, process steps, exact neighbors, interfaces, effects, and cross-unit boundaries.
- Include edge confidence/reason and truncation notices in evidence.
- Resolve source by symbol ranges, not prefix truncation.
- Preserve existing raw-source tiers and compressed file cards as fallback.
- Page claims may cite graph evidence only if backed by source ranges or explicit external/config facts.
- Low-confidence/ambiguous edges must be described as possible, never definitive.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_evidence_graph_context.py -q
```

**Commit:** `feat: assemble semantic graph page evidence`

---

### Task 16: Persist unit/graph provenance and update semantics

**Objective:** Make graph/planning changes compatible with incremental documentation updates.

**Files:**

- Modify: `deepdoc/v2_models.py`
- Modify: `deepdoc/persistence_v2.py`
- Modify: `deepdoc/smart_update_v2.py`
- Modify: `deepdoc/manifest.py`
- Test: `tests/test_semantic_graph_incremental.py`
- Extend: `tests/test_smart_update.py`, `tests/test_state.py`

**Requirements:**

- Persist graph/provider identity and planning-unit identity.
- Detect changed nodes/edges/communities/process ownership.
- Map graph changes to affected buckets.
- Preserve stable slugs by semantic ID.
- Provider/schema changes force a full graph rebuild and targeted/full replan according to measured impact.
- A partial scan cannot overwrite a healthy complete graph snapshot.
- Keep manifest, ledger, scan cache, graph state, and sync baseline mutually consistent.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_semantic_graph_incremental.py tests/test_smart_update.py tests/test_state.py -q
```

**Commit:** `feat: support graph-aware incremental documentation`

---

### Task 17: Add coverage, telemetry, and operator diagnostics

**Objective:** Make graph quality and planning degradation visible to users and benchmarks.

**Files:**

- Modify: `deepdoc/pipeline_v2.py::_print_scan`, `_print_coverage`
- Modify: `deepdoc/telemetry.py`
- Modify: `deepdoc/cli.py` status/performance surfaces as appropriate
- Test: `tests/test_coverage_report.py`
- Create: `tests/test_semantic_graph_reporting.py`

**Report:**

- provider and schema version
- discovered/parsed/indexed files
- supported/unsupported/skipped languages
- exact/probable/ambiguous/unresolved edge totals
- entry points and processes, including truncation
- planning units and coarse units
- documented/orphaned/skipped files per unit and globally
- graph/planner duration and model usage

**Rules:** No source text, API keys, prompt contents, or secret configuration in telemetry.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_coverage_report.py tests/test_semantic_graph_reporting.py -q
```

**Commit:** `feat: report semantic graph and unit coverage`

---

### Task 18: Configuration, migration, and guarded rollout

**Objective:** Add explicit configuration without changing existing users unexpectedly.

**Files:**

- Modify: `deepdoc/config.py`
- Modify: `deepdoc/cli.py`
- Modify: `deepdoc/persistence_v2.py::ENGINE_FINGERPRINT` only when activating graph planning
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `deepdoc/CONCEPTS.md`
- Modify: root `CHANGELOG.md`
- Test: config/CLI tests after locating canonical modules

**Proposed configuration:**

```yaml
semantic_graph:
  provider: native
  min_edge_confidence: 0.5
  persist: true
  processes:
    max_depth: 10
    max_branching: 4
    traces_per_entry: 12
    max_entry_candidates: 200

planner:
  mode: topology              # graph_hierarchical only after acceptance
  graph_hierarchical:
    enabled: false
    serial: true
    unit_budget_fraction: 0.70
    namespace_slugs: true
    global_pass: true
```

**Rollout:**

1. Native semantic graph generated but not planning-load-bearing.
2. Shadow mode compares old and graph-derived units/plans without publishing the shadow output.
3. Opt-in graph planner for benchmark users.
4. Default only after acceptance thresholds pass.
5. GitNexus provider appears only in licensed builds/configurations.

**Verification:**

```bash
.venv/bin/python -m pytest -k "config or cli or semantic_graph or planner" -q
.venv/bin/python -m deepdoc.cli --help
```

**Commit:** `feat: add guarded semantic graph planner rollout`

---

### Task 19: End-to-end acceptance and release gate

**Objective:** Prove correctness, scale, and non-regression before enabling graph planning by default.

**Test layers:**

1. Unit tests from Tasks 1–18.
2. Synthetic multi-service end-to-end fixture.
3. Native provider comparison on existing supported-language fixtures.
4. Real mid-size monorepo run.
5. Generated 10k-file planning fixture.
6. After license: GitNexus-provider bake-off on the agreed matrix.
7. Full regression suite.
8. Generated-site build from a graph-planned output.

**Acceptance criteria:**

- All scanned source files are documented, explicitly skipped, or explicitly orphaned.
- No required planner prompt exceeds the model envelope.
- Exactly one introduction; all nav slugs valid; no output collisions.
- Single-unit native plan has no unexplained regressions from baseline.
- Graph-planned multi-service output has stable namespaced slugs.
- Every process and graph claim is backed by source evidence or marked inferred/ambiguous.
- Truncation and unresolved counts are visible.
- Incremental graph update equals a clean full rebuild on fixture semantics.
- No GitNexus dependency, binary, or source exists in unlicensed release artifacts.
- Full suite passes using `.venv/bin/python`.

**Commands:**

```bash
.venv/bin/python -m compileall deepdoc
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m deepdoc.cli --help
```

For a generated site:

```bash
npm install
npm run build
```

Run inside the generated `site/` directory.

**Final commit:** `feat: enable graph-derived hierarchical documentation`

Do not merge or ship until Pranav reviews the generated wiki visually and explicitly approves it.

---

## 6. Provider bake-off decision matrix

Score each provider from measured results, not marketing claims:

| Dimension | Weight | Required evidence |
|---|---:|---|
| Call/import resolution precision | 20% | Curated fixture ground truth |
| Entry-point recall | 10% | Framework + generic entry fixtures |
| Flow usefulness/tail accuracy | 15% | Human rating + known expected paths |
| Language/file visibility | 10% | Parsed/indexed inventory |
| Cluster/service quality | 15% | Gold boundaries + stability |
| Large-repo wall time/RSS | 10% | Same hardware, pinned versions |
| Incremental equivalence | 10% | Incremental vs clean graph diff |
| Operational/licensing fit | 10% | Contract, deployment, support |

**Go threshold:** No provider becomes default if call precision, entry-point recall, or incremental equivalence is materially worse than the existing native path on currently supported languages, even if it supports more languages overall.

---

## 7. Principal risks and mitigations

### License delay or denial

The provider-neutral/native work remains useful. Only the external provider implementation and enablement are blocked.

### Schema coupling

DeepDoc translates provider records at one adapter boundary and persists only its own versioned schema.

### Graph confidence mistaken for truth

Every edge/process carries confidence, reason, evidence, and resolution state. Prompts and validators distinguish exact from inferred.

### Flat or noisy communities

Workspace/service boundaries dominate; communities are subordinate signals. Global reconciliation and minimum-cohesion rules prevent each flat cluster becoming a page.

### Process cap hides important flows

Use global top-N only for discovery; expand on demand per selected service/community. Persist omission/truncation counts.

### Planner refactor regresses small repos

One-unit parity is an explicit test and graph planning remains opt-in until proven.

### Planner metadata itself exceeds context

Summarize unit metadata hierarchically; never send a full raw file list globally. Use token accounting on rendered prompts.

### External sidecar operational failures

Version handshake, timeout, output limits, health checks, cached last-known-good graph, clear failure mode, and native-provider fallback only when configured—not silent provider switching.

### Existing research documents conflict

Treat `HIERARCHICAL_PLANNER_BRIEF.md` as superseded where it says directory/service-first. Before coding, update it or add a supersession banner pointing to this plan and `GITNEXUS_FEASIBILITY_AUDIT.md`.

---

## 8. Milestones

### Milestone A — Safe foundation, no license needed

Tasks 1–9. Outcome: provider-neutral semantic graph, native adapter, honest process/community model, quality harness, external JSON contract.

### Milestone B — Graph-derived planner, no license needed

Tasks 10–18 using native graph fixtures. Outcome: hierarchical units, sub-scan planner, merger, global pass, evidence integration, incremental state, shadow rollout.

### Milestone C — Licensed GitNexus integration

License Gate A plus provider bake-off. Outcome: GitNexus can populate the DeepDoc graph behind a stable adapter if it wins quality/operational evaluation.

### Milestone D — Production activation

Task 19, visual review, release gates, docs, and explicit approval before merge/default enablement.

---

## 9. Definition of done

This project is done only when:

- DeepDoc can plan a large multi-service repository without sending the whole repository inventory in one required prompt.
- Planning units are justified by manifests, graph structure, and flows rather than folders alone.
- Generated pages cite source-backed symbol/process evidence.
- Provider/truncation/unresolved coverage is visible.
- Small repositories retain current behavior or have reviewed improvements.
- Incremental updates preserve stable page identities.
- A real generated site builds successfully.
- The full test suite passes.
- GitNexus is not present in any shipped artifact until commercial rights are documented.
- Pranav visually approves the generated documentation before PR/merge.
