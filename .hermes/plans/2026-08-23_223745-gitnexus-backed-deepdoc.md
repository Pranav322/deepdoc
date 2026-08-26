# GitNexus-Backed DeepDoc Implementation Plan

> **For Hermes:** Use subagent-driven-development to execute this plan task-by-task only after Pranav approves implementation. Before every task, re-open the referenced files and verify symbols/signatures against the live branch. This plan assumes GitNexus commercial licensing will be approved. Licensing is a release gate, not an alternative architecture. Do not copy GitNexus source into DeepDoc; integrate through a licensed, versioned runtime contract.

**Goal:** Make GitNexus the semantic indexing and code-graph backend for DeepDoc, then build a DeepDoc-owned graph-derived hierarchical planner and evidence pipeline capable of producing coherent, source-grounded documentation for million-line, polyglot repositories.

**Architecture:** GitNexus performs repository discovery, Tree-sitter parsing, symbol/reference resolution, semantic edge creation, community detection, and initial process extraction. DeepDoc imports that output through a strict adapter into a stable internal `RepositorySemanticGraph`, improves service/subsystem hierarchy and documentation-oriented process selection, plans serially per graph-derived unit, merges unit plans with a global architecture pass, then uses the existing DeepDoc evidence, generation, validation, Fumadocs, update, and chatbot systems.

**Tech Stack:** Python 3.10+ DeepDoc; licensed GitNexus 1.6.x sidecar/runtime; Node.js; HTTP/NDJSON preferred for graph export, CLI JSON for development spike; dataclasses; JSON persistence; pytest; existing LiteLLM and Fumadocs systems.

---

## 1. Fixed architecture decisions

1. **GitNexus is the only semantic graph backend.** Do not build a competing native semantic resolver, community detector, or universal language-provider framework in DeepDoc.
2. **DeepDoc keeps its existing parser/scanner stack only for DeepDoc-specific enrichments** until each enrichment is mapped onto GitNexus output: route/OpenAPI presentation, runtime/database/integration artifacts, config/debug signals, source archives, and validation evidence.
3. **DeepDoc owns an internal graph contract.** GitNexus rows, node IDs, LadybugDB schema, and version-specific fields are translated once at the adapter boundary.
4. **Sidecar integration, not source vendoring.** Prefer a licensed, supported HTTP/NDJSON graph export. Use CLI/Cypher JSON only for the first integration spike. Avoid direct LadybugDB reads unless Akon Labs provides a stable schema commitment.
5. **Do not use GitNexus's wiki generator.** Its graph is the substrate; DeepDoc owns all documentation planning and generation.
6. **Serial-first unit planning.** One planning unit at a time until quality, rate limits, and merge semantics are stable.
7. **Graph-first hierarchy.** Explicit workspaces/deployable services first, weighted communities and entry-point reachability second, directories only as supporting evidence.
8. **Readable namespaces.** Multi-unit pages use `{unit-slug}/{local-slug}`. Single-unit repositories retain flat slugs. Hash suffixes resolve residual collisions only.
9. **Dedicated global pass.** Introduction, repository architecture, service map, cross-service flows, shared infrastructure, deployment, glossary, and API overview are globally owned.
10. **No silent incompleteness.** GitNexus truncation, unresolved relationships, skipped files, process caps, and DeepDoc evidence trims are persisted and surfaced.
11. **License controls release, not implementation direction.** We proceed on this architecture; production shipping remains blocked until commercial rights are documented.

---

## 2. Target production pipeline

```text
Repository / monorepo
        │
        ▼
Licensed GitNexus sidecar
  - scan/workspace discovery
  - 16-language parsing
  - symbol/import/call/type resolution
  - routes/tools/ORM/DI/inheritance
  - communities
  - candidate processes
  - incremental graph + persistence
        │
        ▼  versioned HTTP/NDJSON graph export
DeepDoc GitNexusGraphAdapter
  - validate handshake/schema/provider version
  - normalize paths and identities
  - translate nodes/edges/confidence/evidence
  - import communities/processes/truncation
        │
        ▼
DeepDoc RepositorySemanticGraph
        │
        ├─ graph quality/coverage report
        ├─ documentation-oriented process expansion/ranking
        ├─ service → subsystem → component hierarchy
        └─ cross-unit dependency model
        │
        ▼
Graph-derived planning units
        │
        ▼
Serial per-unit DeepDoc planner
        │
        ▼
Deterministic PlanMerger + global architecture pass
        │
        ▼
validate_plan_contract
        │
        ▼
Existing DeepDoc evidence → generation → validation → consistency
        │
        ▼
Fumadocs site + source-grounded chatbot + incremental updater
```

---

## 3. Responsibility boundary

### GitNexus owns

- File/language discovery for graph indexing
- Tree-sitter parsing and normalized captures
- Symbol definitions and references
- Import/export and cross-file resolution
- Receiver-bound calls, type/return propagation, MRO/dispatch
- DI, registration, route/tool/ORM semantic relationships where supported
- Graph persistence and incremental graph updates
- Base Leiden communities
- Base candidate process traces
- Graph search/query/export

### DeepDoc owns

- Adapter validation and stable internal schema
- Documentation-specific service/subsystem hierarchy
- Documentation-oriented entry/tail selection and process ranking
- Planning units and prompt budgets
- Per-unit planner and global plan merge
- Page taxonomy and navigation
- Evidence selection and source hydration
- Page generation and validation
- OpenAPI presentation and existing specialist pages
- Cross-page consistency and links
- Fumadocs output
- Documentation update semantics
- Chatbot source archive, retrieval, citations, and generated-doc linking
- Coverage and operator reporting

---

## 4. Internal semantic graph contract

The adapter must translate GitNexus into a stable DeepDoc representation. Do not expose raw GitNexus records outside `deepdoc/semantic_graph/providers/gitnexus.py`.

### `SemanticNode`

- `id`: DeepDoc stable ID
- `provider_id`: original GitNexus ID, adapter-private/debug only
- `kind`: project/package/service/file/symbol/route/task/tool/datastore/external/config
- `name`, `qualified_name`
- `file_path`, `start_line`, `end_line`
- `language`, `symbol_kind`, `visibility`
- `package_id`, `service_id`
- bounded JSON-safe `metadata`

### `SemanticEdge`

- `id`, `source_id`, `target_id`
- normalized kind:
  - contains/defines/imports/calls/accesses/uses
  - extends/implements/overrides/instantiates
  - registers/injects/handles
  - fetches/queries/reads/writes
  - publishes/subscribes
  - configures/deploys
- confidence `[0,1]`
- resolution: exact/probable/ambiguous/unresolved/external
- reason
- source evidence range
- provider/version

### `SemanticEntryPoint`

- kind: http/cli/main/public_api/event_consumer/scheduler/task/plugin/serverless/test/build/ui/tool
- root node
- label/framework/trigger
- confidence/evidence

### `SemanticProcess`

- stable ID/title
- entry-point IDs
- ordered node/edge steps
- tails/effects
- score/confidence
- truncation metadata

### `SemanticCommunity`

- source GitNexus community ID/label
- member nodes
- cohesion/modularity
- hierarchy parent assigned by DeepDoc
- service/package association
- derivation evidence

### `GraphCoverage`

- GitNexus/provider/schema version
- discovered/indexed files
- symbol counts by language/type
- edge counts by kind/resolution
- unresolved in-program references
- skipped/unsupported files
- entry candidates and persisted processes
- depth/branch/candidate/trace truncations
- community filtering/fallback metadata

---

## 5. Implementation phases

## Phase 0 — Licensing and contract negotiation in parallel

This phase does not change the architecture. Engineering proceeds against a fixture/mock contract while commercial terms are finalized.

Request from Akon Labs:

- Commercial SaaS, local CLI, subprocess, sidecar, modification, and redistribution rights
- Coverage of GitNexus CLI/server, `gitnexus-shared`, graph output, schemas, and bundled grammars
- Stable export/API contract and deprecation window
- Permission to cache and transform graph output into DeepDoc state
- Version pinning and continued-use rights
- Security fixes/support/SLA
- Attribution requirements
- Third-party dependency obligations

**Production gate:** no release can invoke or package GitNexus until written approval is recorded.

---

### Task 1: Freeze and document the GitNexus export contract

**Objective:** Select one supported, versioned read-only interface with Akon Labs and document every field DeepDoc requires.

**Preferred order:**

1. HTTP/NDJSON graph export
2. Supported CLI JSON graph export
3. Supported MCP bulk resource
4. Direct LadybugDB only with explicit schema guarantee

**Files:**

- Create: `deepdoc/semantic_graph/GITNEXUS_CONTRACT.md`
- Create: `deepdoc/semantic_graph/schemas/gitnexus_export_v1.schema.json`
- Create fixture: `tests/fixtures/semantic_graph/gitnexus_export_v1.ndjson`

**Contract records:**

- `provider_metadata`
- `node`
- `edge`
- `community`
- `process`
- `coverage`
- `end`

**Acceptance:** Every required DeepDoc field maps to either a GitNexus output field or a deterministic adapter derivation. Missing information is explicitly listed; nothing is guessed.

**Commit:** `docs: define gitnexus graph export contract`

---

### Task 2: Add provider-neutral semantic graph models

**Objective:** Define DeepDoc's stable internal schema, indexes, queries, and deterministic serialization.

**Files:**

- Create: `deepdoc/semantic_graph/__init__.py`
- Create: `deepdoc/semantic_graph/models.py`
- Create: `deepdoc/semantic_graph/graph.py`
- Create: `deepdoc/semantic_graph/serialization.py`
- Test: `tests/test_semantic_graph_models.py`
- Test: `tests/test_semantic_graph_serialization.py`

**TDD:**

1. Failing tests for stable IDs, normalized paths, edge deduplication, confidence validation, dangling-edge rejection, adjacency queries, and v1 round-trip.
2. Implement minimal models/indexes.
3. Ensure deterministic serialization independent of ingestion order.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_semantic_graph_models.py tests/test_semantic_graph_serialization.py -q
```

**Commit:** `feat: add deepdoc semantic graph contract`

---

### Task 3: Implement the streaming GitNexus adapter

**Objective:** Translate licensed GitNexus output into `RepositorySemanticGraph` without retaining the complete raw export in memory.

**Files:**

- Create: `deepdoc/semantic_graph/providers/__init__.py`
- Create: `deepdoc/semantic_graph/providers/gitnexus.py`
- Create: `deepdoc/semantic_graph/providers/gitnexus_client.py`
- Test: `tests/test_gitnexus_adapter.py`
- Test: `tests/test_gitnexus_client.py`

**Requirements:**

- Provider/version/schema handshake before ingesting records
- Stream NDJSON records with maximum line/record/total-size limits
- Normalize repo-relative POSIX paths; reject escapes and foreign roots
- Translate all supported node/edge types with confidence/reason/evidence
- Preserve unknown types in namespaced bounded metadata while ignoring them safely downstream
- Reject partial streams lacking final integrity metadata
- Compare declared and imported counts/checksum
- No source contents, API keys, or repository secrets in logs

**Client requirements:**

- Explicit configured URL or binary path
- Subprocess argv only; no shell command strings
- Time, memory, and output limits
- Clear timeout/version/schema errors
- No silent fallback to DeepDoc's old graph

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_gitnexus_adapter.py tests/test_gitnexus_client.py -q
```

**Commit:** `feat: import gitnexus semantic graphs`

---

### Task 4: Add GitNexus configuration and health checks

**Objective:** Make GitNexus a required, explicit pipeline dependency with actionable failure messages.

**Files:**

- Modify: `deepdoc/config.py`
- Modify: `deepdoc/cli.py`
- Create: `deepdoc/semantic_graph/health.py`
- Test: config/CLI/health tests
- Update: `README.md`, `AGENTS.md`, `deepdoc/CONCEPTS.md`

**Configuration:**

```yaml
semantic_graph:
  provider: gitnexus
  gitnexus:
    transport: http
    base_url: http://127.0.0.1:4747
    binary: gitnexus
    required_version: ">=1.6,<2"
    analyze_timeout_seconds: 3600
    export_timeout_seconds: 600
    max_export_bytes: 2000000000
    min_edge_confidence: 0.5
```

**Health checks:** binary/server reachable, supported version, licensed capability if exposed, repository can be indexed, schema/export supported, graph not stale.

**Behavior:** `generate` and graph-dependent `update` fail clearly if GitNexus is unavailable or incompatible. Do not silently use the old `CallGraph`.

**Verification:**

```bash
.venv/bin/python -m pytest -k "gitnexus and (config or health or cli)" -q
.venv/bin/python -m deepdoc.cli --help
```

**Commit:** `feat: require configured gitnexus backend`

---

### Task 5: Add a GitNexus-to-DeepDoc coverage bridge

**Objective:** Ensure GitNexus's broader language coverage and skipped-file behavior are preserved instead of being accidentally reduced to DeepDoc's current six-language/1 MB scanner envelope.

**Verified current constraints:**

- GitNexus supports JavaScript, TypeScript, Python, Java, Kotlin, Go, Rust, C#, C, C++, PHP, Ruby, Swift, Dart, Vue, and COBOL.
- GitNexus's filesystem walker defaults to `512 KB` (`DEFAULT_MAX_FILE_SIZE_BYTES`) and may be raised through `--max-file-size` / `GITNEXUS_MAX_FILE_SIZE` to a hard `32 MB` Tree-sitter ceiling.
- GitNexus currently removes oversized paths before parsing and reports them mainly through warnings; its returned `ScannedFile[]` contains only admitted files.
- DeepDoc currently recognizes six source families and skips files above `scan.max_source_bytes=1_000_000` before reading/parsing.

**Files:**

- Create: `deepdoc/semantic_graph/coverage.py`
- Create: `deepdoc/semantic_graph/source_inventory.py`
- Modify: `deepdoc/v2_models.py`
- Modify: `deepdoc/config.py`
- Modify: `deepdoc/planner/engine.py::scan_repo` or replace this ownership in the orchestrator
- Test: `tests/test_gitnexus_coverage_bridge.py`
- Test: `tests/test_source_inventory.py`

**Required behavior:**

1. Build a canonical repository inventory independently of graph output (prefer Git tracked files plus configured include/exclude rules).
2. Compare inventory against GitNexus indexed File nodes. Every missing path gets a reason: ignored, unsupported language, oversized, binary, unreadable, parse failure, worker quarantine, unknown, or absent from export.
3. Configure GitNexus's threshold explicitly rather than inheriting its 512 KB default. Recommended initial production setting: `8192 KB`; allow up to the verified 32768 KB ceiling after memory benchmarks.
4. Do not apply DeepDoc's six-language parser registry as an admission gate to GitNexus-supported files. Java/Rust/C#/C/C++/Kotlin/Ruby/Swift/Dart/COBOL files must remain first-class source/evidence files when represented by the GitNexus graph.
5. Split source hydration from semantic parsing:
   - GitNexus owns semantic parsing.
   - DeepDoc reads bounded source ranges for evidence using GitNexus node ranges, regardless of whether `deepdoc.parser` supports the language.
   - DeepDoc's existing parsers run only for optional DeepDoc-specific enrichments in their supported languages.
6. Add a language-neutral source reader with byte/range guards. It may hydrate exact symbol ranges or bounded windows without constructing an AST.
7. Persist per-file coverage, not only aggregate counts.
8. Fail the run or visibly degrade when important first-party source is missing from the graph; never treat a skipped file as analyzed.

**Files between GitNexus's configured threshold and 32 MB:**

- Ask GitNexus to parse them by setting `--max-file-size` explicitly.
- Reduce worker sub-batch size to at least the individual-file size and tune worker timeout/heap as measured.
- Preserve any quarantine/parse-failure signal.

**Files above 32 MB:**

GitNexus cannot Tree-sitter-parse them through its current implementation because `TREE_SITTER_MAX_BUFFER` is a hard 32 MB cap. DeepDoc must distinguish:

- generated/minified/vendor artifacts: explicitly skip with reason;
- data/schema artifacts: document through artifact-specific bounded readers where useful;
- legitimate first-party source: create an `opaque_file` coverage node, hydrate bounded raw ranges for evidence, mark semantic relationships unavailable, and emit a prominent incomplete-analysis warning.

An `opaque_file` is not permission to invent graph edges. It remains visible in coverage and can receive a conservative file-level documentation page, but no call/type/process claims are made from it. Complete semantic support for a legitimate >32 MB source file requires a supported GitNexus enhancement (for example segmented parsing with stable offset reconciliation) agreed with Akon Labs; simple byte-splitting is not safe for nested syntax and must not be implemented as a fake parser.

**TDD:**

1. Fixture containing GitNexus-supported but DeepDoc-unsupported `.java`, `.rs`, and `.cs` files; assert they remain indexed and source-hydratable.
2. Files at 511 KB, 513 KB, 1.1 MB, 8 MB, and >32 MB; assert explicit policy outcomes.
3. Missing graph file with no reported reason; assert `unknown_missing` and degraded/incomplete status.
4. Generated oversized file; assert explicit skip, not incomplete first-party coverage.
5. Legitimate >32 MB first-party file; assert opaque visibility and no fabricated semantic edges.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_gitnexus_coverage_bridge.py tests/test_source_inventory.py -q
```

**Commit:** `feat: preserve gitnexus language and large-file coverage`

---

### Task 6: Orchestrate GitNexus indexing and graph import

**Objective:** Replace `scan_repo` as the semantic source while retaining DeepDoc-specific scans and language-neutral raw-source availability.

**Files:**

- Modify: `deepdoc/pipeline_v2.py`
- Modify: `deepdoc/planner/engine.py::scan_repo`
- Modify: `deepdoc/v2_models.py::RepoScan`
- Create: `deepdoc/semantic_graph/orchestrator.py`
- Test: `tests/test_gitnexus_orchestration.py`
- Extend: scan regressions

**Sequence:**

1. Discover repository identity/HEAD and build the canonical independent inventory.
2. Ask GitNexus for status/staleness.
3. Analyze incrementally or force as requested with DeepDoc's explicit max-file policy.
4. Export/import graph and coverage.
5. Reconcile the graph File nodes with the independent inventory; block or flag unexplained gaps.
6. Hydrate graph-addressed source ranges through the language-neutral source reader. Do not gate hydration on `deepdoc.parser.supported_extensions()`.
7. Run DeepDoc-specific artifact/OpenAPI/config/debug enrichment where applicable.
8. Map GitNexus routes/processes/symbols into `RepoScan` compatibility fields during migration.
9. Persist graph/provider identity and per-file coverage.

**Migration rule:** `RepoScan.semantic_graph` becomes authoritative. `RepoScan.call_graph`, `topology_map`, and `flow_candidates` remain temporary compatibility projections until consumers migrate. The old `PipelineV2._guard_supported_source_files()` must be replaced with a semantic-graph coverage guard; otherwise a Java/Rust/C# repository would still be rejected despite successful GitNexus indexing.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_gitnexus_orchestration.py tests/test_gitnexus_coverage_bridge.py -q
```

**Commit:** `feat: make gitnexus the scan graph backend`

---

### Task 7: Persist graph state and provider identity

**Objective:** Save imported graph state atomically and invalidate it correctly.

**Files:**

- Modify: `deepdoc/persistence_v2.py`
- Modify: `deepdoc/v2_models.py`
- Test: `tests/test_semantic_graph_persistence.py`
- Extend: `tests/test_state.py`

**State:**

- `.deepdoc/semantic_graph.json.zst` or agreed bounded representation
- schema/provider/version/export fingerprint
- repository commit and GitNexus index identity
- file/content fingerprints when available
- coverage and truncation metadata

**Rules:**

- Provider/schema mismatch forces graph reimport/replan.
- Partial scans never overwrite a complete graph.
- Atomic writes only.
- Keep graph state separate from lightweight `scan_cache.json`.
- Update `ENGINE_FINGERPRINT` when GitNexus graph becomes load-bearing.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_semantic_graph_persistence.py tests/test_state.py -q
```

**Commit:** `feat: persist gitnexus graph identity and state`

---

### Task 8: Replace private `CallGraph` access with semantic graph queries

**Objective:** Make topology, flow, evidence, and chatbot consumers use one provider-neutral query layer.

**Files:**

- Create: `deepdoc/semantic_graph/queries.py`
- Modify: `deepdoc/planner/topology.py`
- Modify: `deepdoc/planner/flow_candidates.py`
- Modify: `deepdoc/generator/evidence.py`
- Modify: chatbot relationship chunk creation after verifying canonical seam
- Test: `tests/test_semantic_graph_queries.py`
- Extend: `tests/test_call_graph.py`, `tests/test_flow_candidates.py`

**Queries:** callers/callees, file adjacency, symbol neighborhood, reachable subgraph, entry/process lookup, service/community membership, cross-unit edges, unresolved summary, source evidence.

**Rule:** No downstream code may access `CallGraph._callees` or GitNexus storage directly.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_semantic_graph_queries.py tests/test_call_graph.py tests/test_flow_candidates.py -q
```

**Commit:** `refactor: consume semantic graph through query layer`

---

### Task 9: Normalize GitNexus entry points, processes, and effects

**Objective:** Convert GitNexus's candidate processes into documentation-grade flow candidates.

**Files:**

- Create: `deepdoc/semantic_graph/processes.py`
- Create: `deepdoc/semantic_graph/entrypoints.py`
- Create: `deepdoc/semantic_graph/effects.py`
- Modify: `deepdoc/planner/flow_candidates.py` as compatibility facade
- Test: `tests/test_gitnexus_process_normalization.py`
- Test: `tests/test_documentation_process_ranking.py`

**Improvements over raw GitNexus processes:**

- Recognize HTTP, CLI, main/bootstrap, public API, event consumer, scheduler/task, plugin, serverless, build/test, UI, and tool entries.
- Recognize DB, external API/RPC, event publication, filesystem/process/UI/artifact tails.
- Prefer explicit entry + meaningful effect over generic deep paths.
- Diversify by service, entry kind, and terminal effect.
- Preserve GitNexus depth/branch/candidate/trace truncation.
- Allow scoped trace expansion/query for a selected community/service through the supported interface.
- Mark exact/probable/ambiguous claims in prompts and evidence.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_gitnexus_process_normalization.py tests/test_documentation_process_ranking.py tests/test_flow_candidates.py -q
```

**Commit:** `feat: rank gitnexus processes for documentation`

---

### Task 10: Build service → subsystem → component hierarchy

**Objective:** Turn GitNexus's flat communities plus workspace/service evidence into documentation hierarchy.

**Files:**

- Create: `deepdoc/semantic_graph/hierarchy.py`
- Create: `deepdoc/semantic_graph/workspaces.py`
- Modify: `deepdoc/planner/topology.py` as compatibility projection
- Test: `tests/test_semantic_hierarchy.py`
- Test: `tests/test_workspace_boundaries.py`

**Precedence:**

1. GitNexus workspace/package/service records and manifest/deploy evidence
2. Configured DeepDoc services
3. GitNexus communities within explicit roots
4. Entry-point/process reachability
5. Shared/foundational dependencies
6. Directory/name hints

**Do not:** equate every GitNexus community with a page or service.

**Output:** stable hierarchical units with confidence, derivation evidence, shared dependencies, and cross-unit edges.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_semantic_hierarchy.py tests/test_workspace_boundaries.py -q
```

**Commit:** `feat: derive documentation hierarchy from gitnexus`

---

### Task 11: Build the GitNexus quality and scale benchmark

**Objective:** Establish hard acceptance thresholds before graph output drives production documentation.

**Files:**

- Create: `deepdoc/semantic_graph/evaluation.py`
- Modify: `deepdoc/benchmark_v2.py`
- Create: `tests/fixtures/semantic_graph/`
- Test: `tests/test_gitnexus_graph_evaluation.py`

**Repository matrix:**

- `backend-tss-api_v2`
- TypeScript app/monorepo
- Rust crate
- Java/Spring service
- C/C++ project
- PHP/Laravel project
- Vue front end
- mixed multi-service monorepo
- generated 10k-file structural fixture
- optional shopware-scale run

**Metrics:**

- discovered/indexed files and languages
- symbol precision/recall on fixtures
- call/import precision/recall
- unresolved in-program rate
- entry-point recall
- flow usefulness/tail accuracy
- hierarchy boundary accuracy/stability
- wall time/peak RSS/export size/import time
- incremental/full equivalence
- truncation counts

**Real-run caveat:** the prior 58.7-second audit run lacked FTS and embeddings; future reports must state enabled capabilities.

**Commit:** `feat: benchmark gitnexus graph quality and scale`

---

### Task 12: Derive budget-aware planning units

**Objective:** Convert semantic hierarchy into units that fit planner model budgets.

**Files:**

- Create: `deepdoc/planner/partitioning.py`
- Test: `tests/test_planner_partitioning.py`

**Unit contents:** service/package, communities, files/symbols, entry points/processes, shared dependencies, cross-unit edges, graph confidence, prompt estimate, coarse/truncated flags.

**Splitting order:** service → subsystem community → component/process slice → package/subtree fallback.

**Budget:** calculate from rendered planner sections and the existing tokenizer, not only line estimates. Never put the full repository file inventory in a global required section.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_planner_partitioning.py -q
```

**Commit:** `feat: partition gitnexus graph into planning units`

---

### Task 13: Project complete per-unit `RepoScan` views

**Objective:** Run the mature DeepDoc planner at unit scope without leaking unrelated services.

**Files:**

- Modify: `deepdoc/planner/partitioning.py`
- Test: `tests/test_planner_subscan.py`

**Filter:** contents, summaries, parsed/source records, endpoints, runtime, database, integrations, config/debug, semantic graph, communities, processes, services, coverage.

**Recompute:** languages, frameworks, totals, file tree, entry/config lists.

**Acceptance:** Projection is immutable relative to the parent and carries explicit scope/completeness metadata.

**Commit:** `feat: project semantic planning subscans`

---

### Task 14: Extract `_plan_one_unit`

**Objective:** Refactor classify → propose → assign for serial reuse per unit.

**Files:**

- Modify: `deepdoc/planner/engine.py`
- Create: `tests/test_planner_single_unit_parity.py`
- Extend existing planner tests

**Boundary:** Local refinement happens per unit; global introduction/nav/orphan/contract handling occurs only after merge.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_planner_single_unit_parity.py tests/test_planner_assignment_partition.py tests/test_planner_granularity.py tests/test_planner_consolidation.py -q
```

**Commit:** `refactor: isolate serial planning unit pipeline`

---

### Task 15: Implement deterministic `PlanMerger`

**Objective:** Merge local unit plans into one collision-free global plan.

**Files:**

- Create: `deepdoc/planner/merge.py`
- Create: `tests/test_plan_merge.py`
- Extend: `tests/test_plan_contract.py`

**Rules:** namespace local slugs for multi-unit repos; rewrite parent/dependency/nav references; preserve semantic IDs; exactly one global introduction; union coverage; retain cross-unit graph; final `_deduplicate_bucket_slugs`; final `validate_plan_contract`.

**Commit:** `feat: merge gitnexus-derived unit plans`

---

### Task 16: Add global architecture planning

**Objective:** Create repository-wide docs from compressed unit/process/cross-edge summaries.

**Files:**

- Create: `deepdoc/planner/global_planning.py`
- Modify: `deepdoc/planner/engine.py`
- Modify canonical prompts after verification
- Test: `tests/test_global_planning.py`

**Pages:** introduction, architecture, service map, cross-service flows, shared infrastructure, deployment/configuration, global API overview, glossary when evidenced.

**Constraint:** Global planning receives summaries and cross-unit graph records, never all raw source or full file inventory.

**Commit:** `feat: plan global architecture from gitnexus graph`

---

### Task 17: Integrate symbol/process graph evidence

**Objective:** Make each generated page evidence-driven by GitNexus symbol ranges and graph neighborhoods.

**Files:**

- Modify: `deepdoc/generator/evidence.py`
- Modify: `deepdoc/generator/validation.py`
- Create: `tests/test_evidence_graph_context.py`

**Rules:** relevant symbols/processes first; exact source ranges; confidence/truncation disclosure; ambiguous edges phrased conditionally; retain current source tiers/compressed cards as bounded fallback; no GitNexus textual claim without source evidence or explicit graph reason.

**Commit:** `feat: assemble gitnexus-backed page evidence`

---

### Task 18: Integrate graph relationships into chatbot indexing

**Objective:** Make code Q&A use GitNexus-backed symbol and relationship chunks while retaining DeepDoc source citations.

**Files:**

- Modify: `deepdoc/chatbot/indexer.py`
- Modify: relationship chunk builder after verifying location
- Modify: `deepdoc/chatbot/retrieval_mixin.py`
- Modify: `deepdoc/chatbot/source_archive.py` only if graph provenance requires it
- Test: chatbot relationship/retrieval tests

**Requirements:** graph relations improve candidate expansion; source archive remains canonical proof; citations use source file/range; graph-only unresolved/inferred facts are labeled; changed graph neighborhoods trigger affected relationship reindexing.

**Commit:** `feat: index gitnexus relationships for chatbot retrieval`

---

### Task 19: Implement GitNexus-aware incremental updates

**Objective:** Reuse GitNexus incremental indexing and regenerate only graph-affected documentation.

**Files:**

- Modify: `deepdoc/smart_update_v2.py`
- Modify: `deepdoc/persistence_v2.py`
- Modify: `deepdoc/manifest.py`
- Test: `tests/test_gitnexus_incremental.py`
- Extend: `tests/test_smart_update.py`, `tests/test_state.py`

**Flow:** git diff → GitNexus incremental analyze → export changed graph/identity → affected node/community/process/unit set → stale bucket set → targeted replan/regeneration.

**Acceptance:** Incremental graph + docs state equals clean full output on fixture semantics; partial state never replaces healthy complete state; stable semantic IDs preserve URLs.

**Commit:** `feat: support gitnexus-aware incremental docs`

---

### Task 20: Coverage, telemetry, and operator status

**Objective:** Expose whether the graph and resulting documentation are complete enough to trust.

**Files:**

- Modify: `deepdoc/pipeline_v2.py::_print_scan`, `_print_coverage`
- Modify: `deepdoc/telemetry.py`
- Modify: `deepdoc/cli.py` status/performance
- Extend: `tests/test_coverage_report.py`
- Create: `tests/test_gitnexus_reporting.py`

**Report:** GitNexus version/capabilities; files/languages/symbols/edges; unresolved and ambiguous edges; communities/hierarchy; process counts and truncation; unit/page coverage; wall time, RSS where obtainable, export/import/LLM usage.

**Commit:** `feat: report gitnexus graph and documentation coverage`

---

### Task 21: Full acceptance, generated-site review, and release gate

**Objective:** Prove that the GitNexus-backed pipeline produces better, scalable docs before merging or shipping.

**Verification:**

```bash
.venv/bin/python -m compileall deepdoc
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m deepdoc.cli --help
```

Run full generation on the repository matrix. Build at least one generated site:

```bash
npm install
npm run build
```

inside generated `site/`.

**Acceptance criteria:**

- GitNexus successfully indexes every selected language fixture.
- Graph export/import count and checksum match.
- No planner prompt contains a required full-repository inventory.
- Multi-service repository plans to completion within budget.
- Exactly one introduction; valid nav; no duplicate writers.
- Every source file is documented, explicitly skipped, or explicitly orphaned.
- Process/graph claims are source-backed and confidence-aware.
- Truncations and unresolved relationships are visible.
- Incremental/full equivalence passes.
- Full pytest suite passes.
- Generated Fumadocs site builds.
- Commercial license approval is recorded and packaging complies with its terms.
- Pranav visually reviews the generated wiki and approves it before PR/merge.

**Final commit:** `feat: enable gitnexus-backed hierarchical documentation`

---

## 6. Delivery milestones

### Milestone A — Licensed graph bridge

Tasks 1–7. DeepDoc can require GitNexus, preserve its language/file coverage, index a repository, import a validated graph, and persist provider identity.

### Milestone B — Documentation intelligence

Tasks 8–11. DeepDoc converts GitNexus's raw communities/processes into documentation-oriented hierarchy, flows, and measured quality reports.

### Milestone C — Million-line planner

Tasks 12–16. Planning is per semantic unit with deterministic merge and a global architecture layer.

### Milestone D — Product integration

Tasks 17–20. Graph evidence powers pages, chatbot, incremental updates, and visible coverage.

### Milestone E — Production approval

Task 21. Full verification, generated-site build, license gate, visual review, then PR/merge.

---

## 7. Risks within the chosen GitNexus path

### Contract instability

Mitigation: negotiated versioned export; one adapter boundary; pinned supported versions; fixture contract tests.

### Sidecar unavailable or stale

Mitigation: required health check and clear failure. No silent fallback to weaker graph semantics.

### Flat/noisy GitNexus communities

Mitigation: DeepDoc hierarchy combines explicit workspaces, processes, shared dependencies, and communities; communities never map one-to-one to pages.

### Bounded GitNexus processes omit important flows

Mitigation: retain truncation metadata and issue scoped trace expansion for selected units through the supported interface.

### Full semantic mode memory pressure

Mitigation: benchmark actual full mode; classify repositories into memory tiers; request/implement a licensed supported export/index mode that retains communities/processes; do not claim arbitrary scale from streaming mode if it disables them.

### DeepDoc-specific route/runtime data disagrees with GitNexus

Mitigation: source-evidence arbitration with explicit precedence and conflict reporting; never union contradictory routes blindly.

### Graph claims outrun source proof

Mitigation: source archive and line ranges remain canonical proof; validation distinguishes exact/probable/ambiguous relationships.

### URL churn in multi-service repos

Mitigation: stable unit identities, readable namespaces, semantic-ID preservation, and redirect mapping before changing existing published slugs.

---

## 8. Definition of done

The GitNexus-backed architecture is complete only when:

- GitNexus is the sole semantic graph backend used by new full-generation runs.
- DeepDoc imports it through a stable validated contract, not internal schema assumptions.
- Services/subsystems are derived from graph and workspace evidence.
- Entry-to-tail flows inform planning and evidence.
- Million-line/multi-service planning is hierarchical and model-budget bounded.
- Generated pages remain DeepDoc-validated and source-grounded.
- Incremental graph changes regenerate only affected docs without losing correctness.
- Coverage/truncation/unresolved state is visible.
- Chatbot retrieval benefits from graph relationships but cites source proof.
- All tests and a real site build pass.
- Commercial licensing permits the deployed integration.
- Pranav approves the visual and documentation quality before merge or release.
