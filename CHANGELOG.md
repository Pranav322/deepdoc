# Changelog

All notable changes to this project will be documented in this file.

The automated release workflow reads the section that matches the version in
`pyproject.toml` and uses it as the GitHub Release notes.

## Unreleased

- Ongoing development.

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
