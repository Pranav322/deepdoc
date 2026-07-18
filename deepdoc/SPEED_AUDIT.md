# DeepDoc End-to-End Speed Audit

Merged and re-verified against the current `deepdoc/` source tree on 2026-07-19.
This document supersedes the earlier speed audit. It combines that audit with a
fresh multi-agent review of scanning, route resolution, call graphs, planning,
generation, smart updates, persistence, chatbot indexing/querying, and site
generation.

This is a static code-path audit. Rankings describe likely wall-clock impact
from code structure, I/O volume, algorithmic complexity, and network round
trips. Production traces are still required before attaching numeric speedup
claims.

## Executive Summary

The highest-value work is concentrated in six areas:

1. Reuse the semantic-classification scan during `deepdoc update` instead of
   scanning the complete repository again during execution.
2. Enforce one token-based evidence budget for generation prompts and cache
   parsed/evidence data shared by multiple buckets.
3. Replace generation batch barriers with a persistent rolling worker pool and
   provider-aware rate limiter.
4. Stop rereading and rehashing source files for page checkpoints, the
   manifest, and the generation ledger.
5. Make chatbot corpus and source-archive updates genuinely incremental rather
   than rewriting complete stores.
6. Reduce, cache, and bound planner LLM calls and prompts.

The Next.js scaffold writer is not a primary bottleneck. Scanning, LLM prefill
and response time, repeated hashing/serialization, and chatbot index rewriting
are much stronger candidates.

## Status of Findings from the Previous Audit

### Completed or retired

- **Completed: duplicate parser disk read.** `parse_file()` now accepts an
  optional `content` argument (`parser/registry.py:33-42`), and the main scan
  passes its cached content (`planner/engine.py:474-500`). This is no longer an
  active performance issue.
- **Completed: primary evidence reads use the scan cache.** The original four
  targets now read from `scan.file_contents` before falling back to disk:
  source context, helper rendering, configuration context, and generated-page
  evidence records (`generator/evidence.py:254,639,813`;
  `generator/generation.py:1126`). A narrower residual issue remains for
  specialized database/schema contexts, documented under P2.6.
- **Completed: route indexes are conditional.** Repo endpoint resolution now
  derives the required framework set and builds JS, Python, and Go indexes only
  when those framework families are present
  (`parser/routes/repo_resolver.py:73-103`).
- **Completed: retry attempts and backoff are capped.** `MAX_RETRIES` is now 3
  in both generation paths and exponential waits are capped at 20 seconds
  (`generator/generation.py:261,791-828`;
  `pipeline_v2.py:78,1498-1528`). Worker-slot sleeping and repeated generation
  stages remain separate active issues below.
- **Retired from the default V2 runtime path: duplicate sitemap builders in
  `pipeline_v2.py`.** The default `feature_buckets` path uses
  `BucketGenerationEngine`, so these helpers do not add wall-clock work there.
  They remain reachable compatibility code through `UpdaterV2` when a legacy
  generation mode is selected (`updater_v2.py:188-197`), so they are not
  universally dead and should be retained or removed only through a deliberate
  compatibility decision.
- **Retired: claims based on an uncommitted planner diff or missing functions.**
  This audit describes only the current working tree.

### Corrections to prior “non-issues”

- Chatbot incremental merge embeds only fresh records, but still loads and
  rewrites complete corpora and their indexes. It is therefore an active
  bottleneck.
- The consistency pass is one LLM call rather than one call per page, but it is
  still an uncached serial tail and should not be treated as free.
- Embedding APIs already receive batches. The remaining issue is corpus-level
  sequencing, repeated store rewrites, and backend-aware concurrency.
- Giant-file clustering and bucket decomposition already use thread pools.
  Their remaining costs are prompt size and the number of LLM calls.

## Priority 0 — Measurement Gaps

### P0.1 — Completed: end-to-end pipeline telemetry

**Locations:** `pipeline_v2.py:376-382,386-406,435-454,470-516,588-597`

The reported `generate` duration stops before the consistency pass. Glossary
linking, changelog generation, chatbot indexing, source archive creation,
backend scaffolding, and final sync-state persistence are not separately timed.
This can make the timing summary point at the wrong phase.

**Resolution:** Generate/update runs now persist sanitized, thread-safe phase,
LLM, retry, evidence, page-write, and chatbot-index telemetry to a rotating
`.deepdoc/performance/runs.jsonl` history. `deepdoc performance` renders the
latest breakdown and previous-run duration comparison. Prompt/response text,
source content, endpoint URLs, and secrets are never recorded. Scanner-family,
file-read, and route/topology granularity remains tracked separately under P0.2.

### P0.2 — Completed: scan subphase visibility

**Locations:** `planner/engine.py:328-579,645-818`

**Resolution:** `RepoScan.scan_timings` and run telemetry now report service
boundary detection, file walking, documentation and source reads, framework
detection, parsing, endpoint detection, route resolution, giant-file clustering,
endpoint bundles, integrations, artifact/runtime/config scans, call graph,
topology, debug discovery, and flow-candidate work independently. Source file
and byte counters are available through `deepdoc performance`, including a
complete zero-valued shape for empty repositories.

## Priority 1 — Highest-Impact Active Findings

### P1.1 — Completed: reuse semantic-classification scan

**Locations:** `smart_update_v2.py:751,895-914,456-487,597-618`

Semantic impact detection builds a full `RepoScan`. Incremental execution or a
targeted replan then performs another full scan. The first scan occurs when git
changes exist and saved endpoint metadata is available, but that is a common
update path.

**Resolution:** Semantic impact detection now attaches its current `RepoScan`
to the run-scoped `ChangeSet`. Incremental and targeted execution consume that
exact object and record an `update.scan_reused` counter. If semantic detection
did not scan or failed, execution performs one normal fallback scan. No scan is
persisted or shared across update runs.

### P1.2 — Targeted replans still begin with a full-repository scan

**Location:** `smart_update_v2.py:456-493`

The include-scoped configuration is prepared after the full scan. A targeted
replan therefore does not receive a targeted scan.

**Action:** Apply include roots during collection, or incrementally patch the
saved scan, route index, and call graph for changed files.

### P1.3 — Generation evidence has no shared token ceiling

**Locations:** `generator/evidence.py:114-119,365-416,1385-1406,1565-1642`;
`generator/generation.py:124-249`

Source context may consume about 200k characters, compressed cards another
60k, helper context another 60k, and artifact context another 40k. Database,
runtime, configuration, graph, repository-doc, and flow contexts are appended
outside one global budget. Large prompts increase request upload, model prefill,
cost, timeout risk, and retry cost.

**Action:** Allocate one token-based budget across all evidence categories.
Rank evidence by bucket ownership and relevance, reserve output/context-window
headroom, deduplicate source repeated by specialized contexts, and log actual
prompt tokens.

### P1.4 — Generation uses batch barriers instead of rolling concurrency

**Location:** `generator/generation.py:465-543`

Every batch creates a new executor, waits for its slowest request, destroys the
executor, and optionally sleeps before the next batch. Fast workers cannot pull
pages from the next batch.

**Action:** Use one persistent bounded executor with a rolling submission
window. Apply a provider-aware token/request limiter at submission time and
pause only when quotas or throttling require it.

### P1.5 — Completed: shared hashes and bounded manifest checkpoints

**Locations:** `generator/generation.py:527-529,1471-1504`;
`manifest.py:32-34`

**Resolution:** `scan_repo` computes `RepoScan.file_content_hashes` while source
content is already in memory. Generation staleness checks, manifest updates, and
ledger persistence reuse those hashes with disk fallback only for files absent
from the scan. The manifest tracks sorted `doc_paths` for every source (while
reading legacy `doc_path` entries), checkpoints atomically every 10 completed
pages or 15 seconds, and saves once at completion. Redundant post-generation
manifest passes were removed from all pipeline/update callers.

### P1.6 — Completed: shared immutable evidence indexes

**Locations:** `generator/evidence.py:247-259,367-416,544-656`

**Resolution:** `EvidenceAssembler` now builds module, symbol, file-line, and
symbol-end indexes once during initialization and shares them across all bucket
workers. Import resolution uses direct suffix keys rather than scanning the
whole module index; helper rendering reuses pre-split lines and precomputed
symbol boundaries. Disk remains a fallback only for files absent from the scan
cache. The indexes are eager and immutable, avoiding concurrent lazy-cache
mutation and unbounded cache growth.

### P1.7 — Chatbot incremental merges rewrite complete corpora

**Locations:** `chatbot/indexer.py:292-355,424-459,480`

`_corpus_needs_rebuild` loads each corpus, and `_merge_records` loads it again.
The incremental path calls merges for all non-rebuilt corpora, including
untouched corpora, then rewrites chunk JSONL, vectors, FAISS, and FTS state.
Only fresh records avoid re-embedding.

**Action:** Skip untouched corpora. Pass already loaded records/vectors into
updates. Longer term, use keyed shards or mutable stores so one changed file
does not rewrite a complete corpus.

### P1.8 — Incremental source archive updates are whole-archive rewrites

**Location:** `chatbot/source_archive.py:100-133`

An update loads/decompresses the complete archive, validates and rereads
unchanged sources, applies changed/deleted paths, recomputes the complete
catalog, and recompresses everything.

**Action:** Store sources as individually compressed content-addressed blobs or
entries plus a small manifest. Preserve catalog metadata for unchanged files.

### P1.9 — Planner latency contains a serial LLM dependency chain

**Locations:** `planner/engine.py:51-66,192-217,235-254`;
`planner/heuristics.py:74-79`

Classify, propose, and assign block on each other. Propose includes the named
cluster set and assign includes the repository file set, so prompt latency grows
with repository size.

**Action:** Cache each step by scan/topology fingerprint. Use deterministic
topology ownership for straightforward file assignment, bound or partition
cluster context, and invoke an LLM only for ambiguous decisions.

### P1.10 — Scanner parsing is fully sequential

**Location:** `planner/engine.py:406-517`

File reads, framework detection, parsing, and endpoint detection execute one
file at a time even though files are independent.

**Action:** Extract a deterministic `_scan_one_file` operation and run it in a
bounded pool. Benchmark processes versus threads because parser behavior and
the GIL determine which is faster. Merge results in stable path order.

## Priority 2 — Strong Secondary Findings

### P2.1 — Include filters are applied after repository walking and inspection

**Locations:** `planner/engine.py:383-425,453-460`

The walker still traverses the full non-excluded tree, performs path checks and
progress work, and only later rejects supported files outside `include`.

**Action:** Compile matchers once, prune traversal by include roots when
possible, and reject unsupported/non-documentation paths earlier.

### P2.2 — Scanner families repeatedly sweep the same corpus

**Locations:** `scanner/runtime.py:124,196,237,301,416,491,561`;
`scanner/database.py:103,224,288`; `scanner/integrations.py:79-203`;
`scanner/artifacts.py:249-297`

Runtime types, database frameworks, integrations, artifacts, logging, and debug
signals are found through many independent full-file loops.

**Action:** Build a shared language-gated per-file signal record containing
lowercased markers, imports, decorators, symbols, and configuration indicators.
Merge compatible regex passes and run independent scanner families concurrently.

### P2.3 — Phase-two enrichment is mostly sequential

**Location:** `planner/engine.py:645-818`

Endpoint bundles, integrations, artifact/database scans, runtime/config scans,
call graph/topology, and debug discovery execute sequentially. Some mutate the
same `RepoScan`, and topology depends on the call graph, but several expensive
branches are otherwise independent.

**Action:** Return immutable sub-results from independent jobs and merge them on
the main thread. Keep call graph then topology sequential. Do not parallelize
shared LLM/client work without provider-safe limits.

### P2.4 — Planner performs additional LLM calls beyond classify/propose/assign

**Locations:** `scanner/integrations.py:206-253`;
`planner/engine.py:663-700`;
`planner/bucket_refinement.py:500-637`

Integration normalization, each giant-file cluster, and decomposition of broad
buckets add model calls. Decomposition can perform a second pass and includes
large file-summary payloads.

**Action:** Prefer deterministic topology/symbol splitting first, cache calls by
content hash, reduce summary payloads, and use LLM normalization only when
heuristics are ambiguous.

### P2.5 — Invalid pages can multiply large model calls

**Locations:** `generator/generation.py:610-716,791-828`

Initial generation, quality repair, and clean rewrite can each make up to three
transient attempts. The current worst case is nine large calls per page. Backoff
sleeps inside worker threads, so widespread throttling can occupy every worker.

**Action:** Apply local repairs for deterministic path/frontmatter/placeholder
failures, allow at most one full rewrite where possible, centrally reschedule
delayed work, and honor provider `Retry-After` values.

### P2.6 — Specialized evidence paths still reread source data

**Locations:** `generator/evidence.py:247-259,634-656,1565-1642`;
`generator/generation.py:1120-1135`

The original evidence-cache fix is complete for source context, helper
rendering, configuration context, and page evidence records. Remaining
specialized database/schema paths still read files directly or repeatedly scan
the same cached content, and overlapping buckets can repeat fallback parsing
and tier extraction.

**Action:** Make the scan content/hash/parse cache the normal source for all
evidence builders and only fall back to disk for files absent from the scan.

### P2.7 — Validation and post-processing make repeated full-document passes

**Locations:** `generator/validation.py:101-149,341-423,568-728`;
`generator/generation.py:614-713`; `generator/post_processors.py:54-227`

Each draft is scanned independently for headings, paths, symbols, routes,
inline code, word count, fences, Mermaid repairs, HTML normalization, and links.
The processing chain is repeated for repair and rewrite drafts.

**Action:** Parse a reusable `ValidationFacts` structure once per draft. Run
hard-fail checks on intermediate drafts and full warning checks only on final
content. Combine compatible fence-aware processors.

### P2.8 — Sitemap/dependency precomputation rebuilds indexes per bucket

**Location:** `generator/generation.py:1310-1423`

`slug_to_bucket` and `file_to_buckets` are reconstructed for each planned page.

**Action:** Build both once in `BucketGenerationEngine.__init__` and reuse them.

### P2.9 — Ledger persistence rehashes tracked source files

**Location:** `persistence_v2.py:681-778`

Saving the generation ledger rereads and hashes every tracked file after scan
and manifest code already performed equivalent work.

**Action:** Pass the scan's content-hash map to persistence and reuse it for the
ledger, manifest, and staleness checks.

### P2.10 — Chatbot discovery repeats full work per changed file

**Location:** `chatbot/indexer.py:153-169`

Artifact and repository-document discovery functions are invoked inside
changed-file comprehensions.

**Action:** Discover each candidate set once, then filter changed paths through
set membership.

### P2.11 — Relationship refresh rebuilds more than the affected subgraph

**Location:** `chatbot/indexer.py:266-289`

Any changed relationship target can trigger complete call-graph chunk
generation; only graph-relation chunks receive a file filter.

**Action:** Determine the changed files' incoming/outgoing neighborhood and
rebuild only those relationship chunks.

### P2.12 — Chatbot full sync builds and writes corpora sequentially

**Location:** `chatbot/indexer.py:54-111`

Seven corpora are constructed and then embedded/saved in sequence. Chunk
construction is partly independent, but embedding concurrency may contend for
local CPU/RAM or cloud quotas and SQLite writers may contend.

**Action:** Parallelize safe chunk construction. Schedule embedding through a
backend-aware bounded queue; benchmark rather than assuming all seven stores
can be embedded or written concurrently.

### P2.13 — Chatbot-only recovery still performs pipeline-wide work

**Locations:** `smart_update_v2.py:375-376,597-643`

Recovery with no stale documentation buckets still performs a full scan and
`save_all`, then may run expensive corpus merges.

**Action:** Load the saved scan for corpus recovery and persist only chatbot
artifacts that require repair.

### P2.14 — Deep research subquestions and agent iterations are serial

**Locations:** `chatbot/deep_research.py:194-223,496-575`

Subquestions execute one after another. Each may run up to five ReAct turns and
then an additional forced synthesis call.

**Action:** Run independent subquestions with bounded concurrency, add early
stopping, cache tool results, and use a smaller iteration cap for simple/high-
confidence questions.

### P2.15 — Retrieval can repeat complete hybrid search and add an LLM rerank

**Locations:** `chatbot/retrieval_mixin.py:34-101,849-930`

Derived follow-up queries repeat semantic and lexical retrieval. Optional LLM
reranking adds another network round trip.

**Action:** Only run follow-up retrieval when initial confidence or coverage is
low. Keep LLM reranking disabled in fast mode or use a local reranker.

## Priority 3 — Scale and Tail-Latency Findings

### P3.1 — JS/Fastify route caches are recreated per endpoint

**Locations:** `parser/routes/repo_resolver.py:235-295,316-441`

Route-prefix and hook ancestry can be recomputed for endpoints sharing the same
router/module.

**Action:** Share memoization across `resolve_repo_endpoints` and key hooks by
file/router identity.

### P3.2 — Django route modules and handlers can be reparsed repeatedly

**Locations:** `parser/routes/repo_resolver.py:1058-1087,1235-1243`

Recursive URL expansion reparses shared modules and re-extracts handler method
metadata.

**Action:** Cache URL-module analysis by content hash and handler metadata by
handler file/class.

### P3.3 — Call-graph lookups and edge deduplication contain linear searches

**Locations:** `call_graph.py:120-124,486-510`

High-degree relation lists use linear membership checks, and import candidates
are checked against `module_index.values()`.

**Action:** Maintain a relation-key set and normalized known-path/reverse module
indexes.

### P3.4 — Topology cluster merging is pairwise

**Location:** `planner/topology.py:328-372`

Every cluster pair performs set and cross-edge work, approaching quadratic
behavior with many small entry-point clusters.

**Action:** Use union-find and generate candidate pairs from inverted file and
cross-edge indexes.

### P3.5 — Flow construction repeats graph and symbol searches

**Locations:** `planner/flow_candidates.py:77-145,184-318,369-407,516-533,581-600`

Endpoint families, tasks, and schedulers retrace execution chains; scheduler
symbol lookup scans all files; candidate merging is pairwise.

**Action:** Memoize chains by entry/depth, build a symbol-to-file index, and
block merge candidates through endpoint/file inverted indexes.

### P3.6 — Orphan attachment and bucket consolidation use all-pairs scoring

**Locations:** `planner/bucket_refinement.py:230-323,665-700`

Unassigned files are scored against every bucket more than once, while bucket
consolidation compares bucket pairs.

**Action:** Defer orphan attachment until the final bucket set, use token-to-
bucket indexes, and block consolidation candidates by section/parent/tokens.

### P3.7 — Lexical fallback and chain retrieval contain corpus-wide loops

**Locations:** `chatbot/retrieval_mixin.py:155-204,816-845`

Lexical search rebuilds `chunk_id` maps and may scan all records when FTS has no
hits. Chain retrieval compares relationship imports against every code file.

**Action:** Prebuild record and module/stem/file indexes at service load. Avoid
full lexical fallback for normal indexed queries.

### P3.8 — Deep-research grep repeatedly scans and splits the whole archive

**Location:** `chatbot/deep_research.py:596-624`

Each grep tool call splits every source file again, repeatable across ReAct
iterations.

**Action:** Cache source lines and add FTS/trigram lookup for larger archives.

### P3.9 — Changelog generation grows without a rendering bound

**Locations:** `changelog_writer.py:49-105`;
`persistence_v2.py:212-224`

Every generation/update appends history, reloads all entries, and rewrites the
complete `whats-changed.md` page.

**Action:** Retain append-only state but render a bounded recent window with an
archive/page mechanism.

### P3.10 — Persistence serializes and fsyncs several complete state files

**Locations:** `persistence_v2.py:88-112,302-306,466-480,969-981`

Plan and file map are written to both current and legacy locations, and each
atomic write independently flushes and fsyncs. This is correct for durability
but adds tail latency and duplicate serialization.

**Action:** Skip byte-identical writes, group state commits where safe, and
retire legacy duplicate locations only through a deliberate compatibility
migration.

### P3.11 — Glossary linking scans every generated page

**Location:** `pipeline_v2.py:1549-1588`

Every run reads each Markdown page and attempts term replacement.

**Action:** Compile a combined matcher and process only new/changed pages unless
the glossary itself changed.

### P3.12 — Site scaffold rewrites managed files even when unchanged

**Location:** `site/builder/next_builder.py:57-77,187,203-215`

The template copier is already incremental for most files, but managed config
and CSS are rewritten on every run, changing timestamps and potentially
invalidating downstream caches.

**Action:** Compare generated bytes before writing. Preserve `.next/cache` in
CI/deploy environments. A complete `next build` is expected behavior and should
be profiled before being classified as a defect.

### P3.13 — The global state lock covers long network and indexing phases

**Location:** `pipeline_v2.py:307-309`

The lock remains held during scanning, all model requests, generation, site
work, chatbot indexing, and archive creation. This prevents corruption but
serializes separate invocations for the full run duration.

**Action:** Treat this primarily as a throughput/operability issue. If concurrent
read-only operations are required, separate run ownership from short state
commit locks without weakening single-writer guarantees.

## Recommended Implementation Sequence

| Order | Work | Why first |
|---|---|---|
| 1 | Complete timing/token/I/O instrumentation | Establishes the actual critical path and validates every later change |
| 2 | Reuse the update classification scan | Removes a complete repository scan with contained design impact |
| 3 | Shared scan content/hash/parse/evidence indexes | Eliminates repeated work across generation and persistence |
| 4 | One token-based generation evidence budget | Reduces the most expensive model requests and retry amplification |
| 5 | Persistent rolling generation executor | Removes straggler barriers while preserving bounded concurrency |
| 6 | Batch manifest checkpoints and reuse hashes in ledger | Cuts repeated source reads and state serialization |
| 7 | Skip untouched chatbot corpora; shard corpus/archive persistence | Makes incremental updates scale with changed content |
| 8 | Bound/cache planner LLM steps | Reduces fixed planning latency and large-repository prompt growth |
| 9 | Parallelize deterministic scan/enrichment work | Improves CPU phases after measurements identify safe boundaries |
| 10 | Optimize route/topology/flow/retrieval indexes | Addresses large-repository scaling after higher-impact work |

## Verification Plan for Performance Changes

For each optimization, record a before/after benchmark using at least:

- a small repository;
- a medium polyglot repository;
- a large monorepo with excluded/vendor directories;
- a no-op update;
- a one-file code update;
- an endpoint-signature update requiring targeted planning;
- generation with and without chatbot indexing;
- a cold and warm chatbot query;
- a deep-research query that invokes archive tools.

Track wall time by subphase, CPU time, peak RSS, files/bytes read and written,
prompt/input/output tokens, LLM request count, retries, embedding count, corpus
records rewritten, archive bytes recompressed, and cache-hit ratios. Preserve
documentation quality, route coverage, update correctness, and state recovery
tests alongside every speed measurement.
