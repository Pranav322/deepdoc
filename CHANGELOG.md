# Changelog

All notable changes to this project will be documented in this file.

The automated release workflow reads the section that matches the version in
`pyproject.toml` and uses it as the GitHub Release notes.

## Unreleased

- Ongoing development.

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
