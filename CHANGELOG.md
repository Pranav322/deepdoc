# Changelog

All notable changes to this project will be documented in this file.

The automated release workflow reads the section that matches the version in
`pyproject.toml` and uses it as the GitHub Release notes.

## Unreleased

### Added

- **LiteLLM-first model capability resolution.** DeepDoc now has one local,
  provider-neutral capability and token-budget layer. Explicit model limits win;
  known models resolve from LiteLLM metadata; custom aliases require a known
  `base_model` or explicit context instead of receiving a guessed limit.
- **Planner token fitting.** Classify, propose, assign, and decomposition prompts
  now preserve complete required inventories and fit optional records into the
  resolved model token envelope, replacing raw planner character slices and the
  previous 50-endpoint formatter cap.
- **Complete page prompt fitting.** Active V2 page generation now token-fits the
  final request, including templates, required evidence, OpenAPI, sitemap links,
  and retry instructions. Omitted supplemental contexts are exposed in page
  provenance instead of causing a late approximate context failure.
- **Chatbot answer prompt fitting.** Answer, continuation, reranker, and
  correction requests now use the selected answer model's local LiteLLM
  capability envelope. Retrieval fan-out remains bounded separately, and local
  capacity failures are reported clearly before a provider request.
- **Local pipeline performance telemetry.** `deepdoc generate` and
  `deepdoc update` now record sanitized phase timings, LLM latency/token usage,
  retry backoff, evidence size, page-write bytes, and chatbot indexing stages in
  a rotating `.deepdoc/performance/runs.jsonl` history. The new
  `deepdoc performance` command renders the latest phase and model breakdown.
- **Scan subphase visibility.** Performance records now distinguish file
  walking, source/document reads, parsing, framework and endpoint detection,
  route resolution, scanner families, call graph, topology, and flow work, with
  source-file and byte counters.
- **Single-scan smart updates.** Semantic endpoint classification now carries
  its current repository scan into incremental generation or targeted planning,
  avoiding a second complete scan in the common endpoint-aware update path.
- **Dependency-scoped update scans.** Safe modifications to existing source
  files now restrict collection, reads, parsing, and endpoint detection to
  affected bucket and route dependencies. Unaffected cached endpoints and scan
  metadata are retained, while structural, configuration, artifact, Django, or
  otherwise uncertain changes visibly fall back to one complete scan.
- **Incremental chatbot corpus writes.** Update runs now load each corpus once
  and skip healthy corpora without effective mutations. Touched corpora retain
  complete JSONL/vector/FAISS/FTS replacement, while stronger FAISS and FTS
  health checks preserve interrupted-write recovery.
- **Content-addressed source archive.** Chatbot source evidence now uses one
  transactional SQLite store with independently compressed SHA-256 blobs, so a
  one-file update no longer decompresses and recompresses every source. Existing
  gzip archives migrate automatically on the first update.
- **Topology-safe planner assignment.** Files with one proposal candidate and
  an exact topology-cluster match are assigned deterministically before the
  serial ASSIGN request. Ambiguous and special files remain model-owned, and the
  existing full deterministic fallback remains unchanged.
- **Deterministic parallel source scanning.** Source reads, hashing, framework
  detection, parsing, and endpoint detection now use bounded workers with stable
  path-order merges. Repository-level route resolution remains serial after the
  complete content map is available.
- **Shared generation evidence indexes.** Module resolution, helper symbols,
  source lines, and symbol boundaries are indexed once per generation engine
  instead of being rebuilt and rescanned for every documentation bucket.
- **Shared scan hashes and bounded manifest checkpoints.** Generation now reuses
  hashes computed during scanning for staleness, manifest, and ledger updates;
  manifests track every owning doc page, write atomically, and checkpoint every
  10 pages or 15 seconds instead of rereading sources and rewriting per page.
- **Rolling page generation.** A single bounded executor now serves the entire
  page plan, allowing free workers to take the next page without waiting for a
  fixed batch's slowest request; result order remains deterministic.
- **Provider-neutral request limiting.** Documentation LLM calls now share
  configurable concurrency, rolling RPM and estimated TPM limits plus adaptive
  `429`/`Retry-After` cooldown. Interactive `deepdoc init` displays defaults;
  non-interactive setup uses safe defaults or explicit flags without blocking.

### Fixed

- **Scoped chatbot recovery preserves complete corpora.** A scoped smart update
  now performs one complete scan before replacing an unhealthy source-backed
  corpus, preventing unaffected indexed records from being dropped.
- **LLM output truncation is explicit.** `llm.max_tokens: null` now omits the
  provider cap instead of imposing the 16K context reserve, and provider
  `finish_reason="length"` responses raise a clear configuration error rather
  than silently falling back to a degraded planner result.
- **Generated Next.js sites compile with current Mermaid types.** The Mermaid
  runner now selects `HTMLElement` nodes explicitly before passing them to
  `mermaid.run()`, and table-of-contents extraction no longer requires an
  ES2018-only regular-expression flag. The Fumadocs root page tree also omits
  the obsolete `$ref` property rejected by current types.
- **Never-grounded artifact hints no longer cause permanent stale loops.** A
  missing tracked path now invalidates a page only when the generation ledger
  proves that path existed previously.
- **Interrupted generation with shared source files now resumes safely.** A new
  source hash resets manifest ownership to pages actually completed at that
  hash; staleness checks require the current page ownership and output file, so
  unfinished pages cannot be skipped after a checkpointed sibling finishes.
- **Context-window configuration now controls generation.** All evidence
  categories share one context-derived budget, raw source is bounded within it,
  output space is reserved, final draft/retry prompts receive a local preflight,
  and generated frontmatter identifies trimmed categories instead of silently
  overflowing a smaller provider context.

## [0.4.2] - 2026-06-23

### Fixed

- **Falcon class-based routes now detect inherited HTTP methods.** `find_falcon_responders` recurses into same-file base classes, so `class UserResource(BaseResource)` correctly picks up `on_get`/`on_delete` methods defined only in the base class. An `_visited` frozenset prevents infinite loops in diamond-inheritance edge cases.

### Improved

- **Topology: import-indegree foundational detection.** Heavily-imported files like `models.py`, `constants.py`, and `exceptions.py` are now correctly flagged as foundational even when they have few call-graph edges. The new `_build_import_maps` helper resolves raw import strings to repo file paths and augments the call indegree used for foundational detection.
- **Topology: import edges in orphan cluster assignment.** Unassigned files that only import from a cluster (without direct call edges) now score against that cluster at 0.5 weight, reducing coin-flip placements into the largest cluster.
- **Topology: cross-edge density as a cluster merge signal.** Two clusters with heavy inter-cluster call traffic now merge even when their file Jaccard is below the 0.60 threshold. The new `_CROSS_EDGE_DENSITY = 0.35` constant controls the cutoff, preventing tightly coupled micro-clusters from producing separate doc pages.

## [0.4.1] - 2026-06-15

### Fixed

- **Mermaid diagrams now render in the generated site.** Replaced the unreliable CDN `type="module"` script (which never re-fires on Next.js client-side navigation) with a `MermaidRunner` React client component that re-runs `mermaid.run()` on every route change via `usePathname`. `mermaid` is now an explicit npm dependency (`^11.4.1`) in the site template.
- **Mermaid syntax errors caused by backticks in node labels.** Mermaid 11+ treats backtick-delimited text inside node labels as its own markdown string syntax, breaking diagrams with LLM-generated file citations like `` ["foo() (`bar.py:10`)"] ``. The post-processor now strips backticks from all double-quoted string tokens inside mermaid blocks before saving.
- **`/ask` page: `file_inventory` crash.** `file_inventory` items from the backend are dicts with a `file_path` key, not raw strings. The frontend was calling `.split('/')` on an object, causing a runtime TypeError.
- **`/ask` page: deep research progress bar now fills forward.** The animated bar no longer dances left-right; it fills progressively based on research milestones (`start` → 8%, `decompose` → 18%, each `step_done` → up to 82%, `synthesise_start` → 88%, `done` → 100%) with a smooth CSS transition.

### Changed

- **`/ask` page: full trace data surfaced in right pane.** `tool_call` trace events now show the actual action and file path (e.g. `read deepdoc/chatbot/service.py`); `decompose` events expand into the sub-question list; `step_done` events list files found per step. Previously all trace fields beyond `phase` and `message` were discarded.
- **`/ask` page: right pane uses compact clickable file rows instead of inline code cards.** Each evidence item is a single row (file name, directory, line number). Clicking opens a full dark code modal with the complete snippet — no truncation. `file_inventory` (all files researched) appears as an "Also researched" list below evidence.
- **`/ask` page: redesigned to match DeepWiki aesthetic.** Question renders as an `<h1>` heading. Warm-gray OKLCH palette throughout. Shimmer skeleton loading. Dark charcoal send button. Trace moved to right pane during deep research, replaced by file rows when done.

---

## [0.4.0] - 2026-06-15

### Changed

- **Site builder migrated from MkDocs to Next.js + Fumadocs.** Generated docs now run on a Next.js 15 + Fumadocs shell that reads plain `.md` files at runtime via remark/rehype — no MDX compile step, so LLM-generated content with `{`, `<`, or unbalanced fences can never crash a build. `deepdoc serve` runs `next dev`; `deepdoc deploy` runs `next build` and exports to `site/out/`. Requires Node ≥ 18.
- **Chatbot `/ask` workspace redesigned.** Two-pane layout: left pane streams the answer with deep-research trace inline (trace disappears when done); right pane shows sources and references for both fast and deep mode. Ask bar is a centred card matching the docs content width.
- **Bottom-fixed ask bar.** Replaces the FAB popup with a floating input bar that sits precisely over the docs content area using Fumadocs CSS layout variables, collapsing correctly on mobile.
- **Sidebar footer.** Commit SHA and generation date appear at the bottom of the docs sidebar.
- **Chatbot response length now matches question intent.** Greetings and small-talk get a 1–3 sentence reply; technical questions remain thorough with full code and evidence citations.

---

## Pre-release history

> Versions below were internal iterations before public release. Kept for reference.

## [3.3.1] - 2026-06-11

### Fixed

- **Removed suggestion pills from quick-ask popup dock.** Deleted the `SUGGESTED` array of example questions and all associated rendering, click handler, and CSS. Textarea placeholder changed to neutral text.
- **Research steps panel now auto-collapses when deep research is done** (on SSE `done` phase, not at `finish`). Previously the expanded trace stayed open until the full answer finished streaming, hiding the answer below it. Now the panel collapses as soon as research signals completion, giving the answer full viewport space.

## [3.3.0] - 2026-06-11

### Fixed

- **`_LAST` nav pins now work without a topology map.** Bumped Testing/CI-CD/Supporting Material values from 57-59 to 997-999 so they always sort last even when no call graph data exists. Previously they sorted before unclassified fallback sections, putting Testing right after Start Here in repos without topology data.

### Changed

- **Nav ordering driven purely by topology depth.** Removed `_compute_section_tier()` (hardcoded bucket-type overrides) and `_SECTION_PRIORITY` from site builder (re-sorted after planner). Site builder now preserves planner's topology-driven `_order`. LLM-proposed sections land at their correct depth position instead of hash order.
- **Dead code cleanup.** Removed unused `_section_rank()` from `heuristics.py` and `mkdocs_builder.py`.

### Tests

- **Added `test_section_sort_key_orders_by_topology_depth`** — end-to-end topology-depth ordering with clusters at depths 0, 2, 5.

## [3.2.0] - 2026-06-10

### Features

- **Client-side conversation thread on `/ask`.** Each question appends a `.dda-turn` section (question header + optional research trace + answer body) to the panel — nothing is replaced on follow-up, so the entire Q/A history stays scrollable. Turns (capped at 20) and the latest sidebar sources persist to `sessionStorage` (per-tab, namespaced by `window.location.pathname`, never sent to the server) and are restored automatically on page reload. The "New" button clears both in-memory state and storage. Auto-scroll sticks to the bottom while streaming and detaches when the user scrolls more than 140 px above the fold. The last ~10 turns are threaded to the backend as `history` context on follow-up questions.

### Changed

- **Answer rendering rebuilt on vendored markdown-it + highlight.js.** Answers are now proper Markdown — links, ordered/unordered lists, tables, blockquotes, and fenced code blocks with syntax highlighting — using offline-bundled libs (`deepdoc/site/builder/vendor/`). No CDN or network access at render time. The `fence` rule emits `.dda-code-wrap` cards with a language label and a one-click copy button; `html: false` ensures raw HTML in answers is escaped (XSS-safe). Streaming renders are throttled to ~80 ms so the parser never runs per-token; the final syntax-highlighted pass runs once at stream end.
- **SPA-aware FAB lifecycle.** The quick-ask FAB now subscribes to Material's `document$` observable and calls `sync()` on every navigation — `build()` re-injects the FAB on docs pages (idempotent), `teardown()` removes it on `/ask`. Previously the FAB disappeared after navigating `/ask → back` via `navigation.instant` (which does not re-run `extra_javascript`) and required a hard refresh to recover.
- **Centered quick-ask popup.** `#dd-popup` is now centered horizontally at the bottom of the viewport (`left: 50%` / `translateX(-50%)`, `transform-origin: center bottom`) instead of anchored to the bottom-right corner.
- **Compact dock with proper radiogroup ARIA.** The floating dock was tightened to a single header row; the Fast / Deep Research mode selector is now a `role="radiogroup"` of `role="radio"` / `aria-checked` pills instead of the old tablist/aria-selected markup.
- **WCAG AA muted color.** Muted text now uses Material's `--md-default-fg-color--light` (opaque `#6e6e73` fallback) instead of `rgba(0,0,0,.5)`, which failed contrast in light mode.

## [3.1.0] - 2026-06-08

### Features

- **MkDocs-native chatbot widget + `/ask` answer workspace.** Delivers the in-site chat experience promised as a follow-up in 2.4.0 — a self-contained vanilla-JS floating "dock" injected on every page plus a full-page `/ask` workspace, generated directly into the MkDocs Material site (no Node/Next.js). Submitting a question opens `/ask/?q=…&mode=fast|deep`; answers stream over SSE with inline **Source evidence** cards (click to open a dark code modal with the snippet, line range, language, and symbol tags) and a **Read next** doc list. In **Deep Research** mode the page also shows a collapsible **Research steps** panel that traces the agent's decompose → retrieve → tool-call → synthesise timeline, and a collapsible **Files explored** list from the run's file inventory. Scaffolded only when `chatbot.enabled` is true.
- **`search` tool in the deep-research agent loop.** `DeepResearcher` now runs semantic FAISS `search` alongside `read_file` and `grep` inside its ReAct loop.
- **`[site]` install extra.** `pip install "deepdoc[site]"` pulls MkDocs Material + pymdown-extensions + the Swagger UI plugin, so previewing/deploying the generated site no longer needs a separate manual install.

### Changed

- **Chatbot query surface collapsed from three modes to two — `fast` and `deep`.** `POST /query` is a single-pass FAISS answer; `POST /deep` is the agentic ReAct researcher. Routes, service, config, and scaffold were simplified accordingly (`routes.py` shed ~100 lines).
- **`/ask` workspace hardened against MkDocs `navigation.instant`.** The page's chrome-hiding `dd-ask-page` body class is now toggled per-navigation via Material's `document$` instead of a one-shot add, so clicking a source no longer lands on an unstyled docs page until a manual refresh.
- **Tighter, correct answer rendering.** The in-answer Markdown renderer is now block-aware (consecutive bullets share one `<ul>`, paragraphs wrap in `<p>`, no stray `<br>` around block elements), fixing runaway vertical whitespace; the fast/deep toggle now syncs `?mode=` into the URL; and the `/ask` visual scale (title, radii, shadows, padding) was tightened.
- **Answer sidebar surfaces more of the retrieval payload** — folds in `relationship`/`live-fallback` code citations and `repo-doc`/`doc` references that were previously computed but dropped. `confidence` and internal `diagnostics` are intentionally not shown.

### Removed

- **Dropped the MDX-only post-processors** left over from the Fumadocs era (`post_processors.py` shed ~96 lines) — CommonMark output needs no JSX/brace escaping. Completes the MkDocs migration cleanup begun in 2.4.0.

## [3.0.0] - 2026-05-30

### 🎉 First Stable Release

After 2 major pre-release iterations and months of production testing, DeepDoc v3.0.0 is the **first stable release**.

#### Changed

- **Version bump from 2.4.0 → 3.0.0** — signals API stability and production readiness. No breaking config or pipeline changes from v2.4.0.
- **All web marketing pages updated** — hero badges, pipeline descriptions, and feature copy now reference v3.0 with stable-release messaging.
- **README.md cleansed of Node.js references** — `node --version` verification replaced with `pip show mkdocs-material`; `actions/setup-node` steps removed from CI workflow examples.

## [2.4.0] - 2026-05-29

### Changed

- **Site generator migrated from Fumadocs (Next.js/MDX) to MkDocs Material (pure Python).** Generated pages are now plain CommonMark `.md` rendered server-side — there is no JSX/MDX compile step, so a page can never fail to build. This removes the entire class of MDX brace/JSX escaping failures and eliminates the Node.js/npm dependency for previewing and deploying docs.
  - `deepdoc serve` now runs `mkdocs serve`; `deepdoc deploy` runs `mkdocs build` and exports static HTML to `site/out/`. Both require `pip install mkdocs-material` (and `mkdocs-swagger-ui-tag` when an OpenAPI spec is present) instead of Node.js.
  - The LLM now emits MkDocs Material **pymdownx Blocks** syntax (`/// note`, `/// tab | …`, `/// details | …`) and grid-cards HTML, taught uniformly across `system.py`, `page_types.py`, and `bucket_types.py`. The previously split-brained prompts (some teaching `:::` remark-directives, others raw `<Steps>`/`<Cards>`/`<Callout>` JSX) are unified.
  - New canonical builder `deepdoc/site/builder/mkdocs_builder.py` (`build_mkdocs_from_plan`) writes `site/mkdocs.yml` (Material theme + Mermaid superfence), a brand stylesheet, the landing page (grid cards), and consolidates OpenAPI into a single `docs/api.md` Swagger UI page. `site_dir: out` avoids colliding with deepdoc's `site/` directory.
  - Internal `/slug` links are rewritten to MkDocs-relative form (`/` → `index.md`, `/auth` → `auth.md`) by `repair_internal_doc_links` (single owner); the changelog page, consistency "See also" callouts, and short/stub-page notices all emit MkDocs syntax.

### Removed

- Deleted the Fumadocs/Next.js scaffold: `scaffold_files.py`, `chatbot_components.py`, `templates.py`, and the `engine.py` builder. The chatbot UI is no longer part of the generated site scaffold (the chatbot backend still runs via `deepdoc serve`); a MkDocs-native chatbot widget is planned as a follow-up.
- Removed MDX-only post-processors (`escape_mdx_angle_hazards`, `normalize_fumadocs_directives`, `fix_leaf_card_directives`) — CommonMark needs no JSX escaping — and vestigial MDX compile-gate ledger fields.

## [2.3.6] - 2026-05-29

### Features

- **Symbol-level evidence packs** — `EvidenceAssembler._build_source_context` now applies a focused "Tier 0.5" extraction for Tier 1 files (≤500 lines) when a bucket's `owned_symbols` is set and more than half the file's symbols are unowned. Only the owned symbol bodies + the file header (imports, module preamble) are sent to the LLM instead of the full file. Uses `Symbol.end_line` when available, falls back to next-symbol boundary inference. Consistent with the existing Tier 3 (`_extract_key_sections`) narrowing behaviour.

- **Cross-bucket consistency pass** — A single post-generation LLM call now runs after all pages are generated. It receives compact per-page summaries (slug, title, type, H2 headings) and returns cross-linking gaps — pages that discuss concepts documented elsewhere but have no link to them. For each gap, a `:::note[See also]` callout is appended to the source page if the target slug is not already linked. Skips gracefully on LLM failure and on already-linked pages. Controlled by `consistency_pass: true/false` in config (default on).

## [2.3.5] - 2026-05-29

### Bug Fixes

- **Bare language marker repair** — `fix_bare_language_markers` in `post_processors.py` detects when the LLM appends `:typescript` / `:json` / etc. directly to a sentence instead of opening a proper ` ```typescript ` fence, and inserts the correct fence. Without this, code content following the marker sits in free MDX body and causes acorn parse errors.

## [2.3.4] - 2026-05-29

### Bug Fixes

- **Bare mermaid fence repair** — `fix_bare_mermaid_fences` in `post_processors.py` detects when the LLM writes `mermaid` as a bare paragraph instead of opening a ` ```mermaid ` fence, and inserts the correct fence. Without this, `{node}` labels inside diagrams leak into free MDX body and cause acorn parse errors.
- **Leaf card directive fix** — `fix_leaf_card_directives` converts LLM-generated `::card{...}\nCONTENT\n::` blocks to `:::card{...}\nCONTENT\n:::` container directives that the fumadocs remark plugin actually understands. Previously the standalone `::` close markers rendered as visible text on the page.

## [2.3.3] - 2026-05-29

### Bug Fixes

- **Fumadocs directive normalization** — `normalize_fumadocs_directives` in `post_processors.py` maps LLM shorthand callout names (`:::warn`, `:::error`, `:::success`, etc.) to the valid fumadocs set (`:::warning`, `:::danger`, `:::tip`). Previously these rendered as raw text instead of styled callout boxes.
- **Frontmatter description cleanup** — `fix_frontmatter_description` strips trailing `::` / `:::` artefacts from the YAML `description:` field that the remark-directive plugin partially parses, corrupting the nav sidebar descriptions.
- **Mermaid error boundary silent fallback** — `MermaidErrorBoundary` in scaffold now returns `null` for broken diagrams instead of a visible error `<pre>` block, keeping pages noise-free. Source-level mermaid fixes (`_fix_mermaid_diagram`) remain in place as the primary guard.

## [2.3.2] - 2026-05-28

### Bug Fixes

- **Mermaid error boundary** — `components/mdx/mermaid.tsx` scaffold now wraps the diagram renderer in a React error boundary. Invalid Mermaid syntax generated by the LLM (e.g. malformed edge labels) shows a `[diagram parse error]` message instead of crashing the entire page.

## [2.3.1] - 2026-05-28

### Bug Fixes

- **Shiki language whitelist** — `normalize_code_fence_languages` in `post_processors.py` now falls back to `plaintext` for any code fence language not included in Shiki's default bundle (e.g. `promql`, `hql`, `cel`). Previously these caused `ShikiError` build failures during `next build`.
- **`DocsPage` prev/next props removed** — scaffold template no longer passes `prev`/`next` props that were removed in recent fumadocs releases, fixing TypeScript compile errors on fresh site builds.

## [2.3.0] - 2026-05-27

DeepDoc 2.3.0 is an internal quality and architecture release: the Node.js MDX compile gate subprocess is replaced by inline Python validation, validator checks are demoted to warnings so generation never stalls on stylistic issues, and the marketing site ships a full design-system refresh.

### Changed

#### Generator
- **MDX compile gate removed** — the external Node.js subprocess (`mdx_validator/validate.mjs`) that validated generated MDX is replaced by inline Python-side validation. Generation no longer requires a Node.js process at validation time, eliminating subprocess startup overhead and environment-dependency issues on Node-less machines.
- **Validator check demotions** — most validation checks are now **warning-only** and no longer trigger Step 6 / Step 6.5 retries. Hard-fails remain only for: truncated output (`word_count < 100`), leaked placeholders (`placeholder_sections`), and hallucinated file paths (`_check_hallucinated_paths`). All other checks — missing sections, low file coverage, out-of-evidence refs, hallucinated symbols, unmatched routes, flow grounding, contract concepts, runtime entities, config keys, integration grounding — log warnings and are recorded in `generation_quality.json` but do not block the page. See `docs/validator_demotions.md` for per-check rationale.

#### Chatbot
- **Shared constants centralised** — `chatbot/constants.py` introduced as the single source of truth for shared string literals (chunk types, corpus names, field keys) used across `indexer.py`, `retrieval_mixin.py`, `answer_mixin.py`, and `service.py`.
- **Retrieval and answer cleanup** — `retrieval_mixin.py` and `answer_mixin.py` updated for the new constants module; dead code and redundant type checks removed across `linking.py`, `live_fallback_mixin.py`, `docs_summary.py`, and `settings.py`.

#### Planner
- **Topology and refinement updates** — `topology.py` cluster-merging and `bucket_refinement.py` decomposition logic updated for consistency with the new validator contract; `nav_shaping.py` and `common.py` minor cleanups.
- **Public API tightened** — `planner/__init__.py` exports trimmed to the canonical public surface; internal helpers no longer exported.

#### Legacy module removal
- `deepdoc/_legacy_types.py` deleted — all callers use `v2_models.py` directly.
- `deepdoc/prompts_v2.py` re-export facade deleted — callers import from `deepdoc/prompts/` directly.
- `deepdoc/generator/mdx_validator/` Node.js shim deleted.

#### Site builder
- `scaffold_files.py`, `mdx_utils.py`, `engine.py`, and `templates.py` updated for the removed compile-gate and new generator API surface.

### Web

- **Complete marketing site redesign** — new design system: DM Serif Display + DM Sans + JetBrains Mono + Dancing Script cursive wordmark. Chartreuse `#C2FF4D` accent replacing old cyan. Aurora gradient hero background. Typewriter terminal animation. Upward-drifting code-fragment canvas on the CTA. Light/dark mode toggle with no-flash init. Video container fixed to 16:9. `web/src/` added to git tracking.
- **Docs page** — updated to new design system; all hardcoded old-cyan color references replaced with the new cohesive palette; SVG architecture diagram updated; `DM Serif Display` headings throughout.

### Tests
- `test_mdx_compile_gate.py` removed (module deleted).
- All other affected test files updated for the new generator, chatbot, and planner APIs.

## [2.2.1] - 2026-05-22

DeepDoc 2.2.1 is a bug-fix release addressing 22 scanner, planner, and generator correctness issues identified by audit, plus adversarial-review remediations.

### Bug Fixes

#### Scanner
- **Import lookup**: `__init__.py` parent-path indexing so `from pkg.sub import X` resolves to `pkg/sub/__init__.py`.
- **Endpoint ownership**: endpoint handler now uses `endpoint_owned_files()` covering `handler_file`, `route_file`, and `file` — not just `file`.
- **Database scanner**: hybrid segment + filename-prefix test-file skip catches `test_*.py` outside a `tests/` directory.
- **Artifacts scanner**: path-segment membership check restores CI artifact detection for `.github/workflows/` and other directory-style patterns.
- **Runtime scanner**: task-name pre-filter skips files that can't contain any task name before running expensive regex loops.
- **Clustering**: duplicate symbols are deduplicated by first occurrence rather than last.
- **Integrations**: webhook regex reverted to plain `r"webhook"` (word-boundary `\b` blocked compound identifiers like `webhook_handler`); comment-only lines are now skipped.

#### Planner
- **`repo_root` threading**: `plan_docs` and `run_phase2_scans` accept and propagate a `repo_root` parameter instead of silently defaulting to `Path(".")`.
- **Topology sort**: cluster sort key corrected to `(is_foundational, min_depth, -len(all_files))` so foundational clusters are processed first.
- **Topology ID collision**: duplicate cluster IDs are disambiguated with a counter suffix instead of silently overwriting.
- **Bucket file list cap**: `_decompose_buckets` caps `owned_files` at 50 with a trailing `"... and N more"` note.
- **`parent_slug` on split children**: decomposed child buckets now carry `parent_slug` pointing to the parent.
- **Keyword merge**: `_build_repo_endpoint_keywords` union-merges new keywords into existing groups rather than overwriting.

#### Generator
- **Proportional OpenAPI budget**: first spec receives up to 4 000 chars; additional specs share the remaining budget down to a 2 000-char floor (single-spec repos recover the previous 4 000-char context).
- **Ambiguous import cap**: import-based dependency links skip any hint that resolves to more than 5 files to avoid noise from generic module names.
- **Sitemap orphans**: buckets absent from `nav_structure` are now grouped by `bucket.section` with section headers instead of being appended as a flat list.
- **`_EP_TITLE_RE`**: endpoint-title regex promoted to a module-level constant instead of being compiled inside the per-bucket hot path.
- **Artifact env context**: `artifact_refs` are now included when scanning env/config keys in evidence assembly.
- **Flow validation**: bare `"sequence"` removed from `_flow_terms`; only `"sequence diagram"` is accepted to prevent false positives on unrelated uses of the word.

#### Pipeline
- **Ordering invariant restored**: `save_all` now runs before `_record_changelog`, which runs before `_build_site`. Changelog entries reference pages that are guaranteed to be persisted, and `whats-changed.mdx` exists when the site builder checks for it.

### Other
- Added `CONTRIBUTING.md` with local setup, testing, and release instructions.
- Added `.github/workflows/deepdoc-refresh.yml` example workflow for teams running DeepDoc as an internal docs pipeline.

## [2.2.0] - 2026-05-22

DeepDoc 2.2.0 is an infrastructure and planning reliability release focused on data safety, incremental update correctness, and multi-spec API support.

### New Features

#### Persistence & Safety
- **Atomic writes across all state files** — every `.deepdoc/` write now goes through `atomic_write_text` / `atomic_write_json` (mkstemp → fsync → os.replace), eliminating partial-write corruption on crash or SIGKILL.
- **Exclusive process lock** — `deepdoc_state_lock` uses an fcntl file lock so concurrent `generate` or `update` runs on the same repo are detected and rejected immediately with a clear error message instead of silently overwriting each other's state.

#### Planning
- **DocBucket semantic identity** — `DocBucket` gains `semantic_id`, `origin`, `confidence`, `evidence_anchors`, and `planner_schema_version` fields. `build_bucket_semantic_id()` derives a deterministic, slug-stable key from endpoint family, parent slug, or owned-file fingerprint. Serialized to and from the `.deepdoc/plan.json` ledger.
- **Targeted incremental plan merge** — `SmartUpdater` replaces its naive slug-append strategy with `_merge_targeted_plan()`, which matches replanned buckets against existing ones by slug then semantic ID. Matched buckets are mutated in-place (files, hints, confidence merged) and queued for regeneration only when their ownership actually changed, avoiding unnecessary regeneration of unchanged pages.
- **Monorepo service boundary detection** — `scan_repo` now runs `_detect_service_boundaries()`, which reads an explicit `services:` list from config or auto-discovers service roots by looking for `pyproject.toml`, `package.json`, `go.mod`, `Dockerfile`, etc. one level under `services/`, `apps/`, and `packages/`. Every scanned file is tagged with its owning service in `RepoScan.file_services`.
- **Endpoint keyword map is now config-extensible** — `ENDPOINT_DOMAIN_KEYWORDS` moved to `planner/common.py` and `_build_repo_endpoint_keywords()` applies a three-layer merge: user `endpoint_groups` config wins, then families observed by the scanner, then the hardcoded fallback. Honoured in both `heuristics.py` and `endpoint_refs.py`.

#### Pipeline & CLI
- **`--strict-quality` flag** — `deepdoc generate` and `deepdoc update` now accept `--strict-quality`, which reads `pages_failed`, `pages_invalid`, `pages_degraded`, and `mdx_fallback_slugs` from the run stats and raises a `ClickException` listing all blockers. Designed for CI pipelines that should fail-fast on degraded output.
- **Multi-spec OpenAPI staging** — `stage_openapi_assets` now stages all detected specs instead of stopping at the first. Each spec gets a collision-safe `deepdoc-openapi-{n}-{stem}-{sha1}` filename and a single combined `manifest.json` is written.
- **LLM token usage in quality report** — token usage from the LLM client is captured into stats and persisted to `generation_quality.json` after every run.
- **Quality-driven staleness** — `_doc_quality_requires_regeneration` marks any page whose ledger record shows `is_valid: false`, `mdx_fallback_applied`, or whose content contains `stub: true` / `deepdoc_status: invalid` as stale so it is regenerated automatically on the next incremental run without a `--force`.
- **Duplicate changelog guard** — `append_changelog_entry` skips writing when the incoming commit matches the most recent entry's commit, preventing duplicate entries from rapid pipeline retries on the same SHA.

## [2.1.0] - 2026-05-20

DeepDoc 2.1.0 is a quality and reliability release — no new pipeline stages, but a broad set of correctness fixes across the scanner, planner, generator, chatbot, and CLI that address real-world failures observed after the 2.0.0 launch.

### Fixed

#### Scanner
- **Deepdoc-generated dirs excluded from scan** — `site/`, `.deepdoc/`, `chatbot_backend/`, and the configured `output_dir` were being scanned as source files, causing giant-file warnings on scaffold files like `chatbot-panel.tsx`. These dirs are now excluded both in `config.py` defaults and as a hardcoded implicit guard in `scan_repo()`.
- **Redis false-positive reduced** — bare `r` was included in the Redis connection-variable pattern in `scanner/common.py`, causing almost any single-letter variable to match. Removed; pattern now requires `cache`, `redis`, or `client`.
- **Artifact scan is now deterministic** — `artifacts.py` iterates `file_contents` in sorted order so artifact detection results are stable across runs.
- **Path stripping handles stacked prefixes** — `scanner/utils.py` now strips all leading `./` segments (e.g. `../../foo`) rather than only the first one.
- **NestJS multi-controller support** — `detect_nestjs` previously used `.search()` so only the first `@Controller` in a file was found. Now uses `.finditer()` with a sorted controller-span list; each `@Get`/`@Post`/etc. is assigned the base path of the nearest preceding `@Controller`.
- **Fastify mount attribute fix** — `repo_resolver.py` referenced the non-existent `parent_info.local_fastify_mounts`; corrected to `parent_info.local_mounts`.

#### Planner
- **Bucket slug collision guard** — fallback slug generation now checks for existing slugs and appends a counter suffix (`-2`, `-3`, …) to avoid silent collisions where two buckets resolve to the same slug and one overwrites the other in the plan.
- **Consolidation cycle guard** — added a `visited` set to the bucket-consolidation while-loop; a bucket that has already been considered as a merge target cannot be merged again, preventing infinite loops when the merge-candidate graph has a cycle.
- **Unified nav section normalizer** — `_normalize_nav_section` was defined in both `heuristics.py` and `nav_shaping.py` with diverging logic (the `heuristics.py` copy had backend-specific remaps the `nav_shaping.py` copy lacked). The duplicate is removed; the canonical version in `nav_shaping.py` now includes all remaps for universal and backend-specific cases.
- **Duplicate `_decompose_buckets` removed** — `heuristics.py` both imported `_decompose_buckets` from `bucket_refinement` and redefined it locally (~158 lines). The local shadow is deleted; all callers resolve to the single canonical version in `bucket_refinement.py`.
- **Terminal corruption during parallel decompose fixed** — `_llm_step` wrapped every LLM call in a `Rich.Live()` context on the shared module-level `console`. With up to 6 concurrent `ThreadPoolExecutor` workers each opening a `Live` context simultaneously, terminal output was corrupted (garbled progress bars, interleaved escape sequences). The `Live` context manager has been removed entirely.
- **Incidental HTTP bucket double-merge prevented** — `bucket_refinement.py` now tracks absorbed slugs in a `merge_target_slugs` set; a bucket that has already absorbed another cannot itself be absorbed again in the same pass.
- **Smart-update `merged_plan` was incomplete** — the `DocPlan` constructor call in `smart_update_v2.py` omitted `orphaned_files`, `integration_candidates`, and `classification`. These are now propagated so incremental replans retain full plan context.
- **Orphaned slugs removed from stale set** — after `_handle_deleted_files` runs, slugs for fully-orphaned buckets are now filtered out of `change_set.stale_bucket_slugs` to prevent a redundant regeneration attempt on pages that have already been deleted.
- **Copy-renamed files trigger regeneration** — the incremental update stale check used `status_code == "R"` (rename only); now checks `status_code in ("R", "C")` to also catch copy operations.
- **Update success requires zero failures** — `pages_failed <= 0` (always true since the count is non-negative) replaced with the correct `pages_failed == 0`.

#### Generator
- **Null guard on `generation_hints`** — `evidence.py` accessed `bucket.generation_hints.get(...)` directly; if the field was `None` this raised `AttributeError`. Now guarded with `(bucket.generation_hints or {}).get(...)`.
- **Manifest loaded once per run** — `generation.py` was loading the on-disk manifest once per bucket inside the stale check. The manifest is now loaded once in `generate_all` and passed into `_bucket_is_stale`, eliminating redundant I/O in large repos.
- **Non-transient LLM errors no longer retry** — the generation retry loop was sleeping and retrying on all exceptions. Auth failures, invalid model names, and quota errors now raise immediately; only rate-limit and transient errors trigger the backoff retry.
- **MDX brace escaping skips JSX prop lines** — the broad `{…}` → `&#123;…&#125;` escape in `post_processors.py` was mangling JSX prop assignments like `component={MyComp}`. Lines containing `={` are now excluded from broad brace escaping.
- **Dead unreachable `return` removed** — an unreachable `return content` statement at the end of a branch in `post_processors.py` was silently masking the actual return path. Deleted.
- **Empty list YAML frontmatter** — `_merge_frontmatter_fields` was writing empty lists as `key:\n  []` (block-style), which gray-matter/Fumadocs rejected. Empty lists are now written as `key: []` (flow-style).

#### Chatbot
- **FAISS invalid-embedding filter** — `chatbot/persistence.py` now filters out results with `score <= -0.5`, preventing corrupted or zero-magnitude embeddings from appearing as top search hits.
- **SSE streams no longer hang** — all three SSE endpoints (`/stream`, `/deep-research/stream`, `/code-deep/stream`) used a blocking `tokens.get()` with no timeout; a silently-dead generator thread would stall the HTTP response forever. Each endpoint now uses `tokens.get(timeout=30)` and emits a `ping` keepalive event on timeout.
- **Citation dedup by range, not just path** — `answer_mixin.py` was deduplicating citations by file path only, collapsing distinct line ranges in the same file to a single entry. The dedup key is now `(path, start_line, end_line)`.
- **Leading `./` stripped from citation paths** — regex-matched file paths in `answer_mixin.py` now have any leading `./` stripped before lookup, matching how paths are stored in the index.
- **Azure `api_version` propagated to chatbot** — when the chatbot inherits its LLM config from `llm.*`, `api_version` is now included in the inherited config alongside `base_url` and `api_key_env`.

#### CLI / Config
- **`deepdoc config set` type inference uses defaults** — `_set_nested` used the *existing* config value to infer the target type; if the value was `None` (key not yet set), it fell through to a plain string assignment. It now walks `DEFAULT_CONFIG` as a type oracle when the existing value is absent.
- **Azure provider validated before generation starts** — selecting `--provider azure` previously wrote a config that caused generation to start and then fail silently mid-run because LiteLLM couldn't reach the endpoint. `LLMClient.__init__` now validates that `base_url` and `api_version` are both present and non-empty before any LLM call is made, raising a loud box error that names exactly what is missing and shows the correct YAML snippet to fix it. The same check runs in `build_chat_client` for chatbot Azure configs. `deepdoc init --provider azure` now writes placeholder values for both fields into `.deepdoc.yaml` and shows Azure-specific next steps so users know what to fill in before running `generate`.

#### Nav / Site
- **`whats-changed` page appears in nav on first run** — two ordering bugs prevented the changelog page from appearing in the sidebar on the very first `generate`: (1) `pipeline_v2.py` was calling `_build_site()` before `_record_changelog()`, so the nav was built without the slug; (2) `smart_update_v2.py` was calling `_append_changelog()` after `_rebuild_nav()`, so the updated plan nav was never written to the site. Both fixed by reordering the calls.
- **`whats-changed` synthetic page registered before nav loop** — `engine.py` now injects a synthetic `DocPage` for `whats-changed` into `slug_to_page` before the nav-structure loop, so it isn't silently skipped (it isn't a `DocBucket` so `plan.pages` never contains it).

#### Glossary
- **Glossary evidence cap** — `bucket_injection.py` was feeding up to 30 model files as evidence for the domain-glossary bucket; capped at 10.
- **Glossary length limits enforced** — the domain-glossary prompt now enforces a 40-term hard cap, an explicit skip-list for generic fields (`id`, `created_at`, `email`, etc.), grouped output via `<Accordions>`, a single Mermaid diagram maximum, and a 300-line page length limit. Previously the LLM wrote individual entries for every model field, producing pages that exceeded 5 000 lines.

#### Changelog page
- **Richer changelog entries** — `changelog_writer.py` now generates commit metadata tables, bulleted page lists with links, source file lists, and strategy explanation blocks per entry, replacing the previous one-liner accordion entries.

## [2.0.0] - 2026-05-09

DeepDoc 2.0.0 introduces precise incremental updates (no more full replans on large commits), a commit changelog page, and MDX quality improvements.

### Added

- **Incremental-only updates** — `deepdoc update` no longer triggers a full replan regardless of how many files changed. Deleted files are handled in-place: orphaned buckets are cleaned up, partially-emptied buckets are marked stale and regenerated. Full replan is only triggered by an explicit `--force` flag or an engine fingerprint mismatch.
- **Commit changelog** — every `generate` and `update` run appends an entry to `.deepdoc/changelog.json` (newest-first, capped at 50). A `docs/whats-changed.mdx` page is regenerated automatically after each run, showing date, commit message, pages updated, and files changed per run. The `whats-changed` slug is auto-injected into the `Start Here` nav section.
- **Directional navigation** — generated pages include prev/next arrows (wired to `findNeighbour` from `fumadocs-core`) and a "Read first:" callout for pages that have prerequisites (`depends_on` on the bucket).
- **`deepdoc_prereqs` frontmatter** — prerequisite slugs are written into MDX frontmatter so the site scaffold can render them as callout links.

### Fixed

- **MDX `<Accordion>` nesting** — `repair_mdx_component_blocks` now inserts missing `</Accordion>` tags immediately before `</Accordions>` rather than appending them at document tail (which produced valid tag counts but invalid nesting). Also strips orphaned `</Accordion>` that the LLM sometimes emits after `</Accordions>`. `<Accordions type="single">` and other attribute variants are now matched correctly.
- **Stale page cleanup on deletion** — deleting source files now immediately removes orphaned `.mdx` pages and prunes the ledger rather than waiting for a full reconcile run.
- **Version warning** — the "upgrade recommended" panel now fires only when the docs' major version differs from the installed CLI's major version, and the message correctly says "run `deepdoc generate`" rather than "upgrade the CLI" (the CLI is already current; the docs need regenerating).

### Changed

- `ChangeSet.strategy` no longer returns `full_replan` for any number of changed/new/deleted files or endpoint structure changes — all such cases route to `incremental` or `targeted_replan`.
- `_handle_deleted_files` is now a first-class pre-step inside `_targeted_replan`, handling both partial deletions (file removed from bucket's owned list) and full orphan removal (bucket + MDX + ledger entry deleted).

## [1.9.3] - 2026-05-07

DeepDoc 1.9.3 fixes backend navigation quality for real-world repos: path-slug sections produced by the classify LLM (e.g. `new-src-api-services-order-index-ts`) are now detected and replaced with proper domain sections, database and runtime buckets use flat canonical section names, and OpenAPI specs are rewritten so Fumadocs can resolve paths directly.

### Added

- Added `_looks_like_path_slug_section()` in `bucket_injection.py` and `nav_shaping.py` — detects all-lowercase-hyphenated section values that look like file path cluster IDs (e.g. `new-src-api-services-sync-index-ts`) so they are always recategorized rather than preserved.
- Added `_is_backend_placeholder_section()` in `bucket_injection.py` — rejects generic placeholder section names (`Architecture`, `Core`, `Features`, `Services`, `Subsystems`, `Runtime & Frameworks`) for backend repos so they are replaced with a specific domain section.
- Added `_BACKEND_INTEGRATION_TOKENS`, `_BACKEND_OPERATION_TOKENS`, and `_BACKEND_RUNTIME_TOKENS` token sets in `bucket_injection.py` for finer-grained backend section routing (Integrations, Operations, Background Jobs).
- Added a dedicated `_BACKEND_ORDER` section ranking list in `nav_shaping.py` — backend repos now get a fixed reader-first ordering: `Start Here` → `Overview` → `Core Workflows` → `API Reference` → `Data Model` → `Background Jobs` → `Integrations` → `Operations` → `Supporting Infrastructure` → tail sections.
- Added `_spec_base_path()` and `_write_spec()` helpers in `pipeline_v2.py` — `_spec_base_path` extracts the server base path from OpenAPI 3 `servers[]` or Swagger 2 `basePath`; `_write_spec` writes the rewritten spec as YAML or JSON depending on file suffix.
- Added "Last indexed" provenance badge to the generated Fumadocs docs page (`scaffold_files.py`) — reads `deepdoc_generated_at` and `deepdoc_generated_commit` from page frontmatter and renders a muted timestamp + short commit ID above the page body.

### Changed

- `_canonical_section_for_bucket()` now rejects path-slug sections and backend placeholder sections before preserving the existing section, so classify-step noise no longer leaks into final nav.
- Backend bucket section routing reordered: `Data Layer` check moved before runtime/integration checks; `Subsystems` fallback replaced with `Core Workflows`; added explicit `Operations` bucket for config/logging/monitoring tokens; `Supporting Infrastructure` replaces the old `Runtime & Frameworks` catch-all for middleware/auth/route/controller buckets.
- Normalized all database bucket sections from `Database > Database & Schema` to flat `Data Model` (`specializations.py`).
- Normalized all runtime bucket sections from `Background Jobs > Background Jobs & Runtime` to flat `Background Jobs` (`specializations.py`).
- OpenAPI staging in `pipeline_v2.py` now rewrites the spec before saving: bakes the server base path into every path key and resets `servers` to `[{"url": "/"}]` so Fumadocs can do a direct dict lookup without prepending the server origin.
- OpenAPI nav entries are now placed under a top-level `API Playground` folder instead of being nested inside the existing `API Reference` folder (`engine.py`).

### Tests

- Added `test_shape_plan_nav_recategorizes_path_slug_backend_sections` — verifies that `new-src-*` path-slug sections are all replaced and buckets land in `Core Workflows`, `Integrations`, `Operations`, and `Supporting Infrastructure` as appropriate.
- Updated `test_shape_plan_nav_backend_uses_reader_flow_and_dedupes_setup` section assertion from `Architecture` to `Core Workflows` to match new routing.
- Updated `test_specialized_bucket_injection_splits_large_database_docs_and_adds_runtime_pages` assertion from `Database > Database & Schema` to `Data Model`.
- Updated `test_build_fumadocs_from_plan_creates_site_scaffold` to assert provenance badge fields (`deepdoc_generated_at`, `deepdoc_generated_commit`, `Last indexed:`, `Intl.DateTimeFormat`) are present in the generated docs page.

## [1.9.2] - 2026-05-04

### Added

- Added **Step 6.5** in the generation retry loop: when Step 6 (patch retry with appended quality feedback) still fails validation, Step 6.5 performs a complete clean regeneration with a structured failure report prepended at the very top of the prompt. The report lists each specific failure category (missing sections, hallucinated paths, missing file refs, unmatched routes, etc.) with concrete items, so the LLM cannot miss or deprioritise the constraints.
- Added `BucketGenerationEngine._build_failure_prefix(validation)` — builds the top-of-prompt failure report with per-category breakdown and explicit "what you MUST do differently" instructions.
- Added `failure_prefix` parameter to `PageGenerator.generate()` and `BucketGenerationEngine._call_with_retry()` — the prefix is injected before all evidence context so it is the first thing the model reads.

## [1.9.1] - 2026-05-04

### Fixed

- Fixed classify LLM echoing cluster IDs as section names (e.g. `new-src-api-services-order-index-ts`) instead of domain names. Added `_fix_slug_cluster_sections()` post-processing guard that detects all-lowercase-hyphenated section values and replaces them with the cluster's human name from the same LLM response.
- Strengthened `CLASSIFY_PROMPT` section-naming rules with an explicit example table, a hard constraint against using cluster IDs as section values, and a target of 4–8 shared domain sections across all clusters.
- Updated `_print_classification_summary()` to display named cluster count and unique sections instead of the stale "classified N source files" message (which was always 0 with the topology-based classify format).

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
