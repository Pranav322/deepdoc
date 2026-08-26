# GitNexus Feasibility Audit for DeepDoc

**Audit date:** 2026-08-23  
**GitNexus source revision:** `aac7515d2a8c50a1f8f923c6fb77218b333560d6`  
**Question:** Can GitNexus's code graph provide the semantic foundation for a DeepWiki-class DeepDoc?

## Executive verdict

**Technically: yes, substantially. Legally: not under the public license for a commercial product without separate permission. Architecturally: use the graph engine, not its wiki generator.**

GitNexus already implements much of the universal semantic-index layer DeepDoc lacks:

- Tree-sitter-backed providers for 15 mainstream languages plus standalone COBOL support;
- a normalized symbol/reference model;
- language-aware import and call resolution;
- type and return-type propagation, inheritance/MRO, method dispatch, callable-value flow, DI, routes, tools, ORM, and optional CFG/PDG/taint layers;
- deterministic Leiden community detection;
- bounded execution-flow extraction;
- content-addressed parse caches and incremental graph updates;
- persistent LadybugDB storage plus CLI, MCP, and HTTP query surfaces.

A real local run against the GitNexus repository indexed **2,201 files into 27,169 nodes and 69,085 edges in 58.7 seconds**, producing 1,334 communities and 300 persisted flows. This proves useful nontrivial scale, but not arbitrary scale or complete flow coverage.

The best DeepDoc architecture is:

> **GitNexus-quality semantic index → DeepDoc-owned graph-to-document planner → DeepDoc evidence, validation, site, and chatbot stack.**

Do **not** replace DeepDoc's generator with GitNexus's current wiki implementation. GitNexus's graph is much stronger than its wiki planner: its outline is still based primarily on an LLM seeing file paths, exported symbols, and a directory tree; large prompts are batched by top-level directory; oversized module source is truncated by prefix; and graph evidence is capped to 30 call edges and a handful of processes per page. DeepDoc already has stronger evidence packs, page contracts, validation, route/OpenAPI handling, Fumadocs output, quality gates, and source-grounded chatbot indexing.

## 1. License is a hard decision gate

The cloned repository root `LICENSE` and `gitnexus/package.json` declare **PolyForm Noncommercial 1.0.0**. The license permits noncommercial purposes; it does not grant general commercial-product use. The repository README says commercial use is available with proper licensing and directs inquiries to Akon Labs / `founders@akonlabs.com`.

This is not legal advice, but the practical engineering rules are:

- Do not copy GitNexus source into MIT-licensed DeepDoc.
- Do not bundle `gitnexus` as a DeepDoc production dependency under the public license.
- Do not assume invoking the CLI as a subprocess makes commercial use permissible.
- Do not assume user-installed or optional integration removes the license issue.
- Safe options are:
  1. obtain a written commercial license/partnership;
  2. build a clean-room DeepDoc implementation from public concepts and independent specifications;
  3. provide an experimental noncommercial adapter only after legal review and with explicit licensing boundaries.

## 2. What GitNexus actually implements

### 2.1 Pipeline

`gitnexus/src/core/ingestion/pipeline.ts` defines a typed phase DAG:

```text
scan → structure → [springConfig, markdown, cobol] → parse → [routes, tools, orm]
  → crossFile → scopeResolution → [springAutoConfiguration, springAop]
  → pruneLocalSymbols → mro → springAopInheritance → di → communities → processes
```

The graph is the primary output. Phases declare dependencies and are topologically ordered. This is a cleaner extensibility model than DeepDoc's current scanner/parser/planner coupling.

### 2.2 Language support

`gitnexus-shared/src/languages.ts` and `gitnexus/src/core/ingestion/languages/index.ts` register:

1. JavaScript
2. TypeScript
3. Python
4. Java
5. Kotlin
6. Go
7. Rust
8. C#
9. C
10. C++
11. PHP
12. Ruby
13. Swift
14. Dart
15. Vue
16. COBOL (standalone regex processor, not Tree-sitter)

Each Tree-sitter-backed language implements a `LanguageProvider`; every supported language also appears in the `SCOPE_RESOLVERS` registry. Providers include AST queries, import semantics, type extraction, export detection, entry-point patterns, framework patterns, import resolution, and language-specific scope/MRO hooks.

Tree-sitter captures are normalized across languages using common tags such as `@definition.class`, `@definition.function`, `@call.name`, `@import.source`, and `@reference.inherits`. This is the right foundation for a language-independent semantic IR.

### 2.3 Semantic resolution

The source contains a real, multi-pass resolver—not merely regex calls:

- authoritative `SemanticModel` indexed by node ID, simple name, qualified name, and file;
- per-file `ParsedFile` artifacts with definitions, imports, scopes, references, callable-flow facts, and optional CFG side channels;
- 3-tier lookup: same-file, import-scoped, global fallback;
- receiver-bound call resolution;
- overload narrowing;
- compound receiver-chain folding;
- cross-file return-type propagation in SCC order;
- inheritance, interface implementations, MRO, virtual/interface dispatch;
- callable-value flow for callbacks/function pointers;
- confidence and reason metadata on graph edges;
- unresolved-receiver census distinguishing in-program, external, and unknown gaps.

This is significantly more capable and better normalized than DeepDoc's current hand-built `CallGraph`.

### 2.4 Graph schema

The graph defines rich node classes (File, Folder, Function, Method, Class, Interface, Struct, Trait, Impl, Enum, Macro, TypeAlias, Variable, Property, Route, Tool, Community, Process, BasicBlock, etc.) and relationships including:

- CONTAINS / DEFINES
- IMPORTS / CALLS / ACCESSES / USES
- EXTENDS / IMPLEMENTS / METHOD_OVERRIDES / METHOD_IMPLEMENTS
- INJECTS / DECORATES / ADVISED_BY / CONDITIONAL_ON
- HANDLES_ROUTE / FETCHES / QUERIES
- HANDLES_TOOL
- MEMBER_OF / STEP_IN_PROCESS / ENTRY_POINT_OF
- optional CFG / CDG / REACHING_DEF / TAINTED / SANITIZES / TAINT_PATH

Every relationship has confidence and reason fields; some resolution edges include evidence signals. This is close to the semantic graph DeepDoc should consume.

### 2.5 Communities

`community-processor.ts` uses deterministic Leiden clustering over a projection of Function, Method, Class, and Interface nodes. The clustering graph includes CALLS, EXTENDS, and IMPLEMENTS. For graphs above 10,000 symbols it drops low-confidence edges and degree-1 nodes to control runtime; a 60-second timeout falls back to one community.

This is useful but not a complete service detector:

- IMPORTS, DI, routes, events, packages, deployment boundaries, and semantic similarity are not direct clustering edges.
- Large-repo filtering omits peripheral symbols.
- Heuristic labels can be generic/duplicated (the real run produced many communities named `Visitors` and `Scripts`).
- Communities are flat, not a service → subsystem → component hierarchy.

DeepDoc should consume communities as one signal, not equate a community with a documentation page or service.

### 2.6 Processes / entry-to-tail traces

`process-processor.ts`:

- builds forward/reverse adjacency from CALLS edges with confidence ≥0.5;
- ranks non-test Function/Method entry candidates by outgoing/incoming ratio, export status, universal and language-specific name patterns, and framework/path hints;
- retains at most 200 entry-point candidates;
- runs bounded depth-first traversal;
- records traces at leaves, cycles, max depth, and detected outward-effect sinks;
- sink detection currently uses extracted fetch and ORM sites;
- deduplicates subset traces and entry/terminal duplicates;
- favors sink-terminated and deeper traces, then round-robins terminals;
- persists Process nodes and ordered STEP_IN_PROCESS edges;
- links Route and Tool nodes to process roots.

This is genuine execution-flow approximation, but not exhaustive program tracing:

- default max depth 10;
- max branching 4;
- per-entry trace budget 12;
- top 200 entry candidates;
- only CALLS edges ≥0.5 are traversed;
- sink coverage is mostly fetch/ORM, not all meaningful effects;
- ranking is heuristic and output is capped;
- labels are only entry → terminal (real outputs included `BuildModuleTree → IsVerbose`).

GitNexus correctly records truncation counters. DeepDoc should preserve and expose this epistemic metadata and treat processes as candidates/evidence, not complete truth.

## 3. Real execution evidence

Executed:

```bash
npx -y gitnexus@1.6.9 analyze /tmp/gitnexus-audit --force
```

Result:

```text
Repository indexed successfully (58.7s)
27,169 nodes | 69,085 edges | 1334 clusters | 300 flows
2,201 indexed files
```

Graph distribution included:

- 10,426 Functions
- 7,517 Consts
- 2,023 Methods
- 1,217 Interfaces
- 1,124 persisted Community nodes
- 300 Processes
- 24,158 CALLS edges
- 19,789 DEFINES edges
- 5,840 IMPORTS edges
- 5,538 ACCESSES edges
- 1,270 STEP_IN_PROCESS edges

This demonstrates useful throughput and a substantial graph on a nontrivial repository. It does not prove an arbitrary million-line repository will fit every mode. GitNexus contains explicit Linux-kernel-scale engineering comments and memory controls, but its strongest memory-saving `streamGraphEmit` mode disables communities and processes—the very graph products DeepDoc needs for planning. A production integration must benchmark the full semantic mode, not only indexing completion.

## 4. Scaling mechanisms and limits

### Strong mechanisms

- Parse work is byte-budget chunked and worker-thread parallel.
- Worker-serialized `ParsedFile` artifacts avoid main-thread reparsing.
- Parse outputs are content-addressed and sharded on disk.
- Warm cache hits replay serialized parse output.
- Incremental writeback extracts the changed subgraph and includes affected importers.
- Dirty-write markers force full rebuild after interrupted updates.
- Graph persistence uses CSV streaming + LadybugDB bulk COPY.
- Adaptive heap/buffer sizing accounts for machine/cgroup memory.
- Process/community caps and truncation are explicitly recorded.
- Embeddings are cached and are optional.

### Important limits

- Full graph analysis still has O(repo) resident state in normal mode.
- Source comments cite Linux-kernel measurements around millions of nodes and very high memory requirements; this needs independent benchmark replication before product claims.
- `streamGraphEmit` reduces heap substantially but disables communities/processes/taint summaries because those phases read the whole graph.
- Embeddings auto-skip above 50,000 nodes unless overridden; large-repo semantic search therefore needs separate design/capacity planning.
- Process traces are sampled/bounded, not complete.
- Community detection is flat and filtered at scale.
- The public parse-throughput benchmark document still contains TBD measurement cells; not every scale claim has published measurement data.

## 5. GitNexus's wiki generator: useful reference, not the target

`core/wiki/generator.ts` implements:

1. Gather all files + exported symbols from the graph.
2. Ask an LLM to group files into roughly 5–15 modules using file/export list + directory tree.
3. If the grouping prompt exceeds 100k estimated tokens, batch by top-level directory and merge independent groupings by slug.
4. If a module exceeds 30k source tokens, split once by subdirectory; otherwise truncate source by character prefix.
5. Generate leaf pages in parallel from source + up to 30 intra/inter-module CALLS edges + up to 5 processes.
6. Generate parent pages from excerpts of child docs.
7. Generate an overview from parent summaries, module-edge counts, and top processes.
8. Incrementally regenerate modules touched by git-diff file membership; >5 new files triggers full regrouping.

### Strengths

- It does perform bottom-up leaf → parent → overview generation.
- It batches outline grouping rather than hard-failing at 100k tokens.
- Graph call/process evidence is included in page prompts.
- It supports reviewable/editable module trees and resumable module pages.

### Weaknesses compared with DeepDoc

- Module grouping does not directly consume Leiden communities; it primarily uses file paths, exports, and directory structure.
- Batched grouping lacks a global reconciliation model beyond same-slug merging.
- Hierarchy is effectively two levels.
- Oversized source is prefix-truncated, potentially excluding the most relevant symbols.
- Only 30 call edges and ~5 processes are included per module.
- No DeepDoc-equivalent evidence tiers, page contracts, hallucinated-path/symbol validation, grounding thresholds, OpenAPI specialization, consistent Fumadocs site build, or strict quality gate.
- Page failures are collected rather than retried/repaired with DeepDoc's richer validation pipeline.

Therefore: do not adopt GitNexus's wiki generator as DeepDoc's generator. Use its graph/index concepts or licensed graph output to strengthen DeepDoc's planner and evidence assembler.

## 6. Integration options

### Option A — Commercial license + GitNexus sidecar/indexer (recommended fastest path)

Obtain a commercial license from Akon Labs. Pin a GitNexus version and run indexing as a controlled child process/service. Consume a **versioned, read-only graph contract** over one of:

- HTTP `/api/graph` NDJSON + `/api/query` (direct graph access);
- CLI `cypher`, `query`, `context`, `trace` JSON outputs;
- MCP read-only tools/resources;
- direct LadybugDB only if a stable schema/version contract is negotiated.

DeepDoc converts the external graph into its own internal `RepositorySemanticGraph` so its planner/generator do not depend on GitNexus-specific node IDs or schema details.

Pros: shortest path to mature 16-language semantics, workers, caching, communities, processes, and cross-repo contracts.  
Cons: license cost, Node/native dependency, schema/version coupling, operational sidecar, vendor dependency.

### Option B — Commercial license + library embedding

Use the exported TypeScript APIs (`runPipelineFromRepo`, `WikiGenerator`) through a Node worker/service. This is tighter/faster than shelling out but GitNexus does not present a narrow, stable public library API; internal paths and schema can change. Only choose this with an explicit support/versioning agreement.

### Option C — Optional user-installed integration

DeepDoc detects an existing `.gitnexus` index or `gitnexus` executable and imports graph output when available, falling back to its own analyzer otherwise. Technically feasible, but it is not automatically license-safe for commercial use; obtain written clarification before shipping.

### Option D — Clean-room DeepDoc semantic engine

Implement the public architectural concepts independently:

- provider registry + normalized Tree-sitter capture vocabulary;
- semantic IR / symbol indexes;
- three-tier resolution;
- confidence/evidence on edges;
- workspace/build-manifest resolution;
- community detection;
- bounded, honest process tracing;
- sharded parse cache and worker parsing.

Pros: full control, MIT-compatible, Python-native integration.  
Cons: very large engineering effort; GitNexus source demonstrates years' worth of edge cases and correctness work.

## 7. Recommended DeepDoc architecture

### If a commercial license is obtainable

Use GitNexus as a **semantic-index sidecar**, not as the docs engine:

```text
Repository
  → GitNexus index (Tree-sitter + resolution + graph + communities/processes)
  → DeepDoc GitNexusGraphAdapter
  → DeepDoc RepositorySemanticGraph (stable internal schema)
  → graph-aware hierarchical planner
  → DeepDoc evidence assembler / generator / validator / Fumadocs / chatbot
```

The adapter should import:

- File/symbol nodes with source ranges and descriptions;
- CALLS/IMPORTS/EXTENDS/IMPLEMENTS/INJECTS/ACCESSES/etc. edges with confidence/reason;
- communities + cohesion;
- processes + ordered steps + truncation metadata;
- route/tool nodes and entry-point links;
- unresolved-resolution metadata where exposed.

Do not bind DeepDoc directly to GitNexus IDs, raw LadybugDB layout, or wiki module format.

### If licensing is unavailable or uneconomic

Do a clean-room implementation using GitNexus only as prior-art inspiration. Start with a **narrow high-value semantic matrix** (not hundreds of grammars):

- TS/JS/Python/Go/PHP/Vue (existing DeepDoc);
- Rust/Java/C#/C++/Ruby/Kotlin next;
- normalized symbols/imports/calls/types;
- confidence-aware resolution;
- workspace manifests;
- entry-point registry;
- weighted community graph.

Use permissively licensed Tree-sitter grammars directly; verify each grammar's license independently.

## 8. How DeepDoc should improve beyond GitNexus

1. **Graph-aware planning:** use workspace boundaries + weighted communities + entry-point reachability. GitNexus wiki grouping currently uses file/export lists and directories, not communities as the primary plan.
2. **Hierarchical communities:** service → subsystem → component, not flat Leiden clusters.
3. **Documentation-oriented flow ranking:** rank by product-facing entry points and meaningful tails; GitNexus's generic process labels often surface mechanical terminal helpers.
4. **On-demand flow expansion:** precomputed top-N processes are hints; planner can request deeper traces for a selected subsystem rather than relying on a global capped sample.
5. **Evidence completeness:** assemble source by relevant symbols/graph neighborhoods; never prefix-truncate a large module.
6. **Validation:** retain DeepDoc's grounded file/symbol/route checks and quality gates.
7. **Coverage accounting:** graph/node/symbol/flow coverage by unit, with explicit truncation and unresolved-edge counts.
8. **Large-graph two-pass strategy:** a compact structural graph for all files, then deeper semantic resolution only for selected communities/processes if full-resolution memory is too high.
9. **Stable adapter contract:** DeepDoc owns a versioned semantic schema independent of GitNexus implementation details.

## 9. Revised implementation order

1. **Commercial-license decision / proof-of-concept adapter spike.** Contact Akon Labs; in parallel, build a throwaway adapter against CLI/HTTP JSON only and compare graph quality on representative repos. Do not ship it.
2. **Define DeepDoc `RepositorySemanticGraph` contract.** Versioned nodes/edges/confidence/evidence/truncation; provider-neutral.
3. **Graph quality bake-off.** Compare existing DeepDoc graph vs GitNexus graph on at least: Python service, TS app, Rust crate, Java/Spring service, mixed monorepo, large synthetic repo. Metrics: parsed-file %, resolved-call precision/recall on curated fixtures, entry-point recall, flow usefulness, cluster cohesion/stability, peak memory/time.
4. **Choose provider:** licensed GitNexus adapter vs clean-room DeepDoc analyzer.
5. **Graph-derived hierarchical planner.** Workspace boundaries first; communities and entry reachability second; token budget third. Per-unit plan + global merge.
6. **DeepDoc generation integration.** Graph-neighborhood evidence, flow pages, parent summaries, global architecture.
7. **Incremental graph + docs updates.** Changed subgraph → affected units/pages; preserve stable semantic page IDs.
8. **Hosted scale/cost.** Queue, memory classes, graph storage, cheap/strong model tiers, budget caps.

## 10. Go/no-go experiments before implementation

Run the same pinned GitNexus build on:

- `backend-tss-api_v2` (Python/Falcon; known DeepDoc baseline);
- a real Rust crate;
- a Java/Spring service;
- a C/C++ repository;
- a JS/TS monorepo;
- a synthetic 10k-file monorepo;
- optionally shopware.

For each, measure:

- files discovered vs parsed;
- symbols and edges by type;
- unresolved in-program receiver/call counts;
- entry-point candidate/truncation counts;
- process coverage and usefulness (human-rated);
- communities, cohesion/modularity, stability across reruns;
- wall time and peak RSS;
- incremental-update equivalence;
- mapping into DeepDoc page buckets and source evidence.

Do not select an architecture from feature lists alone. Require these measurements and a written commercial-license answer.

## Final recommendation

**Do not build the directory-first hierarchical planner yet.** First decide the semantic substrate.

The preferred route is to approach Akon Labs for commercial licensing and build a short, disposable GraphAdapter spike. If the license and contract are acceptable, GitNexus can save DeepDoc a major amount of semantic-index engineering. If not, use the audited architecture as a reference and implement a clean-room provider-neutral graph, starting with the 10–15 languages that cover the target repos.

In either case, DeepDoc should retain ownership of planning, evidence assembly, validation, generated site, update semantics, and chatbot. That combination can be stronger than either project alone.