# Changelog

All notable changes to this project will be documented in this file.

The automated release workflow reads the section that matches the version in
`pyproject.toml` and uses it as the GitHub Release notes.

## Unreleased

- Ongoing development.

## [1.9.0] - 2026-05-04

DeepDoc 1.9.0 replaces the LLM-discovers-structure planning model with topology-driven nav planning: call graph analysis pre-computes cohesive domain clusters before any LLM call, the LLM names and describes them, and flows are embedded inside their owning domain pages instead of a separate "Core Workflows" section.

### Added

- Added `deepdoc/planner/topology.py` — `build_topology_map()` derives a `TopologyMap` from the call graph without any LLM involvement. It computes per-file indegree and BFS call-depth from entry points, groups files into `TopologyCluster` objects via BFS + Jaccard-based merging (threshold 0.40), and identifies a foundational cluster for shared infrastructure files (indegree ≥ 8% of repo size).
- Added `topology_map: TopologyMap | None` field to `RepoScan`; populated during Phase 2 scans immediately after call graph construction.
- Added `_format_topology_clusters()` to `utils.py` — formats topology clusters with entry files, key symbols, owned file counts, side effects, and external calls for the classify prompt.
- Added `_build_named_clusters_str()` to `utils.py` — merges LLM-assigned cluster names/sections/descriptions from the classify step with topology cluster file lists and call-graph signals into a rich context string for the propose step.
- Added `_attach_flow_hints_to_cluster_buckets()` in `specializations.py` — instead of creating a separate "Core Workflows" bucket, attaches `flow_entrypoints`, `flow_id`, `flow_entry_kind`, and `sequence_diagram` hints directly to the domain bucket that owns the flow's entry files.
- Added `_build_section_depth_map()` and `_section_sort_key()` in `nav_shaping.py` — order nav sections by topology cluster depth (entry-point-facing clusters appear first, foundational last) rather than by hardcoded section name lists.

### Changed

- **Classify step** now sends pre-computed topology clusters to the LLM instead of a compressed file tree. The LLM names each cluster and assigns it a domain section, returning a `cluster_names` dict rather than per-file classification.
- **Propose step** now receives `named_clusters` (topology clusters enriched with LLM-assigned names/sections) instead of `classification_summary` + `flow_candidates`. Buckets are created from named clusters, not discovered from a compressed file-tree blob.
- `_shape_plan_nav()` now accepts an optional `scan` argument and uses topology depth to order domain sections; the old hardcoded `_section_rank()` is replaced by `_section_sort_key()` which only pins `Start Here`/`Overview` at the front and `Testing`/`CI/CD`/`Supporting Material` at the tail.
- `_default_section_for_primary()` no longer returns `"Core Workflows"` for `backend_service` repos — domain section names come from the LLM's cluster naming step instead.
- Duplicate `_shape_plan_nav` definition removed from `heuristics.py`; the authoritative version in `nav_shaping.py` is now used throughout.
- `_ensure_flow_buckets` and `_expand_flow_bucket_ownership` removed from the public planner API and replaced by `_attach_flow_hints_to_cluster_buckets`.

### Fixed

- Fixed `heuristics.py` importing `_section_rank` from `nav_shaping` after the function was replaced by `_section_sort_key`.

## [1.8.0] - 2026-05-04

### Added

- Added call flow pipeline: `FlowCandidate` and `EntryPoint` models in `deepdoc/planner/flow_candidates.py` trace endpoint families and runtime tasks/schedulers through the call graph to collect entrypoints, call chains, side effects (Celery/signal/event dispatches), and external touchpoints.
- Added `_ensure_flow_buckets` and `_expand_flow_bucket_ownership` in the planner to automatically create "Core Workflows" documentation buckets for the top-scored flow candidates and enrich their file/symbol ownership from call chain evidence.
- Added `flow_context` to `AssembledEvidence`; the evidence assembler renders a structured call flow section (entrypoints, call chain, side effects, external touchpoints) for any bucket with a `flow_id` generation hint.
- Added `_check_flow_grounding` validator that marks pages invalid when a flow bucket omits required "Call Flow" or "Side Effects" sections despite flow context being present.
- Added `{flow_context}` placeholder to all prompt templates in `bucket_types.py` and `page_types.py`.

### Changed

- Nav sections proposed by the LLM are now preserved as-is rather than being replaced with hardcoded generic labels. `_canonical_section_for_bucket` only overrides empty or placeholder sections; supporting-tier buckets (tests, CI/CD) still get properly re-sectioned.
- `_section_rank` replaced with an anchor-only ordering model: Start Here and Overview are pinned first; Design & Notes, Testing, CI/CD and Release, and Supporting Material are pinned last; all other sections (LLM-named domain sections like "Order Management" or "Authentication & User Management") are ordered by first-appearance in the LLM's proposal.
- `_normalize_nav_section` no longer aggressively remaps domain section names (Architecture → Core Workflows, Subsystems → Core Workflows, etc.); only safe universal aliases remain.
- `PROPOSE_PROMPT` now instructs the LLM to name nav sections after business domains rather than generic technical layers.

## [1.7.1] - 2026-05-02

### Added

- Added a `deepdoc deploy` quality gate that refuses to export docs when generation quality reports failed/invalid pages or generated MDX is still marked invalid/stub.
- Added a configurable compatibility warning for repositories whose generated docs were produced by deprecated DeepDoc versions, including an upgrade command.

### Fixed

- Fixed Azure embedding retries so `maximum input length is 8192 tokens` errors split or trim oversized symbol corpus records instead of failing chatbot sync.

## [1.7.0] - 2026-05-02

DeepDoc 1.7.0 adds real token-by-token streaming to the chatbot's Fast and Deep Research modes, delivering the same live-answer experience already available in Code-aware mode.

### Added

- Added `POST /query/stream` SSE endpoint that streams the Fast mode answer token-by-token before emitting a final `result` event.
- Added `POST /deep-research/stream` SSE endpoint that streams the Deep Research synthesis answer token-by-token before emitting a final `result` event.
- Added `complete_stream()` method to `LiteLLMChatClient` using `litellm.completion(stream=True)`, yielding token strings as they arrive.
- Added `token_callback` parameter to `_complete_with_continuation()`, `query()`, `deep_research()`, and `_run_research_mode()` so the final answer generation can push tokens to any caller.
- Added `synthesis_token_callback` to `DeepResearcher` so only the synthesis step streams tokens (sub-question expansions remain non-streaming).

### Changed

- Updated the generated chatbot UI so Fast and Deep modes fetch from the new `/stream` endpoints and progressively render the answer with `ReactMarkdown` as tokens arrive, falling back to the non-streaming endpoints if the stream is unavailable.

## [1.6.0] - 2026-05-01

DeepDoc 1.6.0 makes the chatbot more trustworthy for code questions by grounding answers in archived source evidence instead of raw retrieved chunks.

### Added

- Added a dedicated symbol corpus plus SQLite FTS lexical retrieval so chatbot search can blend exact identifier matches with semantic search.
- Added source catalog and index manifest artifacts for deterministic evidence hydration and index inspection.
- Added canonical chatbot `evidence[]`, `references[]`, and diagnostics payloads, plus `/query-context` alignment with the same evidence contract.

### Changed

- Updated chatbot answer assembly to hydrate proof from the source archive/catalog, exclude generated/internal paths from source evidence, and treat docs as references instead of implementation proof.
- Updated generated chatbot UI to surface evidence IDs, reference links, diagnostics, and inline evidence navigation in the answer workspace.
- Updated README and AGENTS guidance to match the evidence-first retrieval model, symbol indexing, lexical search, and validation behavior.

### Fixed

- Fixed answer-grounding gaps by validating cited evidence IDs and source paths, retrying invalid answers, and failing closed with conservative diagnostics when validation still fails.
- Fixed MDX hazard escaping for additional raw brace and less-than sequences emitted by generated docs.

## [1.5.2] - 2026-04-27

- Added trust hardening for generated docs: provenance frontmatter, generated-site commit badges, coverage reporting, local setup verification, and warning-only cross-page consistency artifacts.
- Tightened generated-page validation for hallucinated paths, hallucinated symbols, and low file coverage on core pages.
- Improved chatbot trust behavior with explicit no-fabrication prompting, score-based out-of-scope abstention, stricter citation filtering, and similarity-based confidence.

## [1.5.1] - 2026-04-25

- Changed the generated Fumadocs scaffold to omit chatbot routes, frontend components, and `chatbot_backend/` artifacts when `chatbot.enabled` is false, keeping docs-only builds clean.

## [1.5.0] - 2026-04-25

- Changed scanned runtime endpoint planning to enrich grouped endpoint-family pages instead of generating one MDX page per route, while preserving OpenAPI-backed per-route API pages when a spec exists.
- Added a deterministic planner assignment fallback so malformed LLM JSON in the assign step no longer discards the proposed bucket plan.

## [1.4.0] - 2026-04-17

DeepDoc 1.4.0 adds a dedicated code-aware chatbot mode with live trace events
and improves planner output quality for generated docs in large repositories.

### Added

- Added a dedicated code-aware chatbot mode with `POST /code-deep` and live SSE tracing via `POST /code-deep/stream`.
- Added code-aware retrieval defaults, file inventory output, and generated site UI support for a third chatbot mode with live progress visibility.

### Changed

- Updated planner nav shaping to produce a reader-first, repo-agnostic flow that keeps backend docs in a natural order (`Start Here` → `Core Workflows` → `API Reference` → `Data Model` → runtime/integrations/ops) while preserving coverage.
- Updated endpoint-reference nav grouping to live under `API Reference` and dedupe legacy setup overlap with `local-development-setup`.
- Updated fallback orphan bucket naming/placement to reduce noisy `* and Related` module pages in generated navigation.
- Updated database grouping to coalesce large sets of sparse singleton model groups into stable aggregate groups (for example `core-models`) so database coverage stays complete without one-file nav spam.

## [1.3.0] - 2026-04-07

DeepDoc 1.3.0 improves deep-research coverage, rebalances retrieval quality,
and adds a scorecard workflow for release readiness checks.

### Added

- Added source-archive persistence for chatbot indexing (`source_archive.json.gz`)
  so deep-research workflows can inspect repository files from indexed state.
- Added an agent-style deep-research loop with bounded `read_file` and `grep`
  tool actions over archived sources for multi-step investigation.
- Added benchmark scorecard workflows in `deepdoc benchmark`, including
  catalog-based and artifact-proxy scoring, scorecard JSON output, and strict
  quality-gate enforcement.
- Added retrieval diagnostics and API enhancements for chatbot backends,
  including `POST /query-context` and `response_mode` in query responses.
- Added generated `chatbot_backend/` scaffolding (`app.py`, schemas, settings,
  requirements, and env example) for standalone chatbot deployment.

### Changed

- Updated deep-research retrieval to combine sub-question evidence with
  original-question retrieval context and deeper per-step evidence budgets.
- Rebalanced retrieval/rerank behavior across code, artifact, docs, and
  relationship corpora with per-kind candidate balancing and expanded
  query-intent heuristics.
- Updated chatbot retrieval defaults and prompt-budget behavior to improve
  runtime, flow, and architecture question coverage.
- Updated README guidance around benchmark scorecards, chatbot retrieval modes,
  and release flow details.

### Fixed

- Fixed deep-research answer continuity by routing long step and synthesis
  responses through continuation-aware completion handling.
- Fixed evidence-loss scenarios during reranking by preserving relationship
  chunks as first-class candidates in final retrieval ordering.

### Maintenance

- Removed checked-in generated DeepDoc state and static site export artifacts
  (`.deepdoc/*`, legacy plan/file-map snapshots, and `site/out/*`) to keep
  release commits focused on source changes.

### Docs And Tests

- Added/expanded regression coverage for benchmark scorecards, source-archive
  persistence, deep-research retrieval behavior, chatbot config/query/scaffold,
  generation evidence validation, Fumadocs builder behavior, and JSON parsing.

## [1.2.0] - 2026-04-06

DeepDoc 1.2.0 expands repo-grounded chatbot retrieval, broadens runtime extraction,
adds generation quality reporting, and hardens incremental update behavior.

### Added

- Added package-based v2 architecture modules for planner, scanner, generator, and
  site builder to replace large monolithic files.
- Added a dedicated repo-doc chatbot corpus with configurable indexing guardrails so
  selected repo-authored docs are indexed separately from generated docs.
- Added hybrid chatbot retrieval improvements: lexical exact-match paths, graph-aware
  relationship expansion, adjacent code-window stitching, and richer citation payloads.
- Added `/deep-research` live repo fallback with bounded evidence collection while
  keeping normal `/query` index-only.
- Added runtime extraction coverage for Django commands/signals/channels, Laravel
  jobs/events/listeners/scheduler, JS/TS worker and queue patterns, and Go workers.
- Added persisted generation quality reporting at `.deepdoc/generation_quality.json`.

### Changed

- Updated planner specializations and evidence assembly so runtime, config, and
  integration details propagate consistently into generated pages.
- Extended generated-page validation to enforce route/runtime/config/integration
  grounding when corresponding evidence exists.
- Updated README and AGENTS guidance to match the current architecture and retrieval
  behavior.

### Fixed

- Fixed incremental chatbot sync handling for deleted generated-doc files so stale
  chunks are removed correctly.

### Docs And Tests

- Expanded tests across chatbot indexing/query behavior, runtime extraction,
  planner granularity, generation evidence/validation, and framework fixtures.
- Added Falcon and Go fixture coverage for framework/runtime scan and retrieval paths.

## [1.1.0] - 2026-04-04

DeepDoc 1.1.0 improves generation grounding, chatbot retrieval depth, and generated
site/OpenAPI behavior so docs stay closer to real code and staged API assets.

### Added

- Added helper-function evidence assembly for imported repo-local utilities so feature
  and endpoint pages can describe called helpers from actual source instead of guesses.
- Added secondary internal-doc context and extracted environment/config evidence for
  overview and system-style pages.
- Added a chatbot `relationship` corpus with import-graph and symbol-index chunks,
  plus chain retrieval that pulls related code from imported files.
- Added validation checks for unmatched route claims and references to files outside
  the assembled evidence set.

### Changed

- Made evidence extraction thresholds follow config and expanded large-file excerpts so
  generated pages keep more real branch logic, symbol bodies, and owned code paths.
- Tightened generation prompts to require grounded business logic, helper behavior,
  config knobs, constants, file coverage tables, and clearer uncertainty handling.
- Reworked Fumadocs OpenAPI support to build API pages from the staged manifest,
  surface OpenAPI operations in navigation when endpoint pages are absent, and strip
  server origins from manifest paths.
- Improved generated site scaffolding by preserving handwritten landing-page content
  while still injecting frontmatter, and refined chatbot code-block styling in the UI.
- Increased default chatbot retrieval and answer budgets so responses can include more
  code, artifacts, docs, and relationship context in a single answer.
- Hardened Mermaid cleanup by sanitizing problematic flowchart edge labels.

### Docs And Tests

- Expanded regression coverage for configurable evidence thresholds, helper following,
  internal-doc context, evidence-backed validation, relationship indexing and chain
  retrieval, OpenAPI manifest routing, origin stripping, and Mermaid cleanup.

## [1.0.0] - 2026-04-03

DeepDoc 1.0.0 is the first stable release and significantly improves documentation planning,
retrieval quality, generation throughput, and release automation.

### Added

- Added source classification and publication-tier metadata across scanning, planning,
  persistence, generation, and chatbot indexing.
- Added publishability filtering for runtime API endpoints so generated API structure
  only includes validated product routes.
- Added first-party versus third-party integration classification so internal systems
  are documented as subsystems instead of external integrations when appropriate.
- Added repo-profile normalization for more accurate documentation structures across
  backend services, Falcon apps, monorepos, CLI tooling, framework libraries, and
  hybrid codebases.
- Added FAISS index loading support in chatbot retrieval paths and new retrieval
  metadata such as framework, source kind, publication tier, and trust score.
- Added concurrency controls for generation with `--max-parallel-workers` and
  `--rate-limit-pause`.
- Added site dependency sync stamping so `serve` and `deploy` can detect stale
  `node_modules` more reliably.

### Changed

- Reworked planner behavior to prefer fewer, deeper pages instead of over-splitting
  concepts into many shallow buckets.
- Raised decomposition thresholds, parallelized giant-file clustering and bucket
  decomposition, and added post-planning bucket consolidation for near-duplicate pages.
- Improved landing-page generation with a repository-wide map, richer overview prompts,
  stronger framework awareness, and better routing into deeper docs pages.
- Updated chatbot retrieval ranking to prefer core runtime/docs evidence by default
  while still allowing tests, fixtures, examples, and generated artifacts to surface
  when explicitly requested.
- Improved generated Fumadocs scaffolding, including preserved handwritten `index.mdx`
  pages, updated OpenAPI loading, and more polished chatbot answer and citation UI.
- Hardened MDX and Mermaid normalization, including safer `<Step>` heading handling,
  indented code-fence normalization, and ER diagram cleanup.
- Split GitHub release creation into changelog-driven notes when a matching version
  section exists, with auto-generated notes as the fallback.

### Docs And Tests

- Documented the changelog-based release flow in `README.md`.
- Expanded regression coverage for planner consolidation, publication metadata,
  parallel pipeline behavior, chatbot retrieval, persistence, Fumadocs generation,
  Mermaid cleanup, and CLI site dependency syncing.

## [0.1.1] - 2026-04-01

- Published DeepDoc to PyPI.
- Improved package metadata for the PyPI project page.
- Added installation instructions for `pip install deepdoc`.
- Documented `deepdoc[chatbot]` for chatbot features.
- Added automated release workflow scaffolding for future releases.
