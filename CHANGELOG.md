# Changelog

All notable changes to this project will be documented in this file.

The automated release workflow reads the section that matches the version in
`pyproject.toml` and uses it as the GitHub Release notes.

## Unreleased

- Ongoing development.

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
