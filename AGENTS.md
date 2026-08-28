# AGENTS.md
Guidance for coding agents working in this repository.

## Scope
- Applies to the repository root.
- If you change core CLI behavior, persistence/state formats, routing semantics, or generated-site behavior, update this file in the same task. Also keep `README.md` in sync with actual codebase behavior.
- **IMPORTANT**: Whenever you need more knowledge about the exact execution flows, functions, classes, invariants, and cross-file relationships, take reference from [`deepdoc/CONCEPTS.md`](deepdoc/CONCEPTS.md). It is the exhaustive semantic and architectural map of the codebase.

## Repo Summary
- Project name: `deepdoc` (v0.5.0)
- Language/runtime: Python `>=3.10`
- Packaging: setuptools via `pyproject.toml`
- CLI entrypoint: `deepdoc = deepdoc.cli:main`
- Test runner: `pytest`
- Main implementation path is the v2 bucket-based pipeline.
- Generated docs live in `docs/` (configurable); the generated site scaffold (Next.js + Fumadocs) lives in `site/`, and `next build` in `site/` outputs static HTML to `site/out/`.
- Repo also contains a VS Code extension at `vscode-extension/` (Node/TypeScript, independent release track) and a Remotion marketing video project at `deepdoc/video/` (not part of the Python pipeline).

## Important Paths

### Core pipeline
- `deepdoc/cli.py` — Click commands: `init`, `generate`, `update`, `clean`, `status`, `benchmark`, `serve`, `deploy`, `config show/set`
- `deepdoc/config.py` — `.deepdoc.yaml` defaults, loading, and `_set_nested` type inference
- `deepdoc/pipeline_v2.py` — end-to-end orchestration; `PipelineV2` class; `_spec_base_path()` and `_write_spec()` for OpenAPI rewriting; `_build_site()` must be called *after* `_record_changelog()`; `_print_scan()` prints the scan summary and a warning for known-but-unsupported source languages found (`scan.unsupported_extensions`); `_print_coverage()` prints a documented/orphaned/coverage-% panel right after planning, from `plan.buckets`/`plan.orphaned_files`/`plan.skipped_files` vs. `scan.file_contents` — no new scanning, just surfacing existing plan/scan data
- `deepdoc/v2_models.py` — `DocBucket`, `DocPlan`, `RepoScan` (now carries `call_graph`, `topology_map`, `flow_candidates`, `unsupported_extensions`, `skipped_source_files` fields), `_BucketAsPage`
- `deepdoc/smart_update_v2.py` — `SmartUpdater`, `ChangeSet`, `UpdateRunResult`, `UpdateSyncPlan`, `SemanticImpact`; `_handle_deleted_files` pre-step; `_append_changelog` must be called before `_rebuild_nav()`
- `deepdoc/persistence_v2.py` — `.deepdoc/` state, plan, ledger, sync baseline, changelog, engine fingerprint

### Planner
- `deepdoc/planner/engine.py` — repository-scan entrypoint and planner orchestration. `plan_docs()` runs Phase 2 scans once globally, builds service planning units, and uses `unit_likely_fits_budget()` only as a conservative preflight. The real acceptance mechanism is each `fit_prompt_sections()` call inside `_plan_local()`: an overflowing required CLASSIFY/PROPOSE/ASSIGN prompt raises `UnitNeedsSplit`, so only that unit is split and retried. A finite repository `max_pages` budget is allocated across units; local units omit global buckets. After deterministic merge, `_apply_global_plan_stage()` runs once against the full scan to create the repository-wide Start Here/setup/glossary/debug/database/runtime/interface pages and perform final shaping and validation.
- `deepdoc/planner/partitioning.py` — `PlanningUnit` (carries `coarse: bool`, `boundary_stubs: tuple[Any, ...]` — see `unit_boundaries.py` — and `unclaimed: bool`, the authoritative marker for the unit holding files no `file_services` entry claimed; never infer that from the slug, since a repo whose every file is claimed *and* which has a service literally named `core` would otherwise hand `CORE_SLUG` to that real service), `build_planning_units()` (groups files by `scan.file_services`; unclaimed files form `core`; zero/one named service remains one compatibility unit), `make_sub_scan()` (isolates all file-scoped evidence — including nested file-bearing fields such as `EndpointBundle.evidence` and `RuntimeTask.producer_files`, which are trimmed to the unit without dropping the retained handler/task — trims topology, drops the global call graph, and recomputes languages), `split_planning_unit()`/`next_split()` (deterministic splitting), `unit_likely_fits_budget()` (conservative preflight estimate), and `bound_planning_unit()` (pre-splits obviously oversized units; runtime prompt fitting remains authoritative). Config `planning_unit_max_files_seed` only shapes the first split guess.
- `deepdoc/planner/unit_boundaries.py` — Slice B deterministic semantic refinement, using only existing call-graph/topology/endpoint-bundle/runtime/flow evidence, no LLM calls, no GitNexus. `refine_unit_ownership()` runs only when `build_planning_units()` produced 2+ named units; it conservatively moves an unclaimed `core` file into exactly one named unit when the file's combined affinity score clears a fixed minimum and beats the runner-up by a fixed margin ratio. Affinity comes from five signals with fixed documented weights: raw local call edges, topology-cluster co-membership (deliberately weighted *below* the minimum score, so it can only corroborate other evidence and never moves a file on its own — `topology.py` assigns a leftover file to its best-guess cluster and finally to `max(proto, key=len)`, the biggest cluster, an arbitrary bucket), flow co-occurrence, `EndpointBundle.evidence` file paths (only when the bundle's `handler_file` anchors to exactly one named unit and no evidence file belongs to another named unit), and `RuntimeTask.producer_files` (same single-anchor rule). One endpoint/runtime vote is sufficient on its own, but the margin rule still keeps a helper claimed by two services in `core`. Flow candidates are built in `plan_docs` immediately before refinement (multi-unit path only) precisely so the flow signal is live: the other builder runs inside `_apply_global_plan_stage`, i.e. after every unit is already planned, which left `scan.flow_candidates` empty for both `refine_unit_ownership()` and `compute_boundary_stubs()`. The lazy guard in `_attach_flow_hints_to_cluster_buckets` then finds the field populated and becomes a no-op, so there is no double build. Note `CallGraph.__len__` makes an empty graph falsy, so both guards skip a repo with no edges. Schedulers, realtime consumers, and `scan.entry_points` deliberately contribute nothing: none carries a bounded dependent *file* list. `TopologyCluster.shared_dep_files` are foundational by construction, so they are already excluded — otherwise (including ties, weak signal, or a topology-foundational file) the file stays in `core`. A `file_services`-assigned file is never a candidate; that ownership is a hard anchor, enforced structurally via `PlanningUnit.unclaimed` rather than by comparing slugs. When refinement finds an owner for *every* unclaimed file the emptied unit is dropped rather than planned, since a zero-file unit still reserves a page in `_allocate_page_budgets` and burns three LLM calls on an empty sub-scan. `compute_boundary_stubs()` aggregates a bounded, serializable `BoundaryStub` (remote unit slug, direction, aggregate score/call count, evidence kinds — never remote file paths, symbols, raw edges, or any flow label/ID/title). No flow-derived string reaches a prompt at all: `FlowCandidate.flow_id` is frequently a slug of upstream text, so a remote path can arrive already stripped of `/` and `.` (`services-payments-private-handler-py-flow`) and no character-level sanitizer can distinguish it from a legitimate identifier. Flow co-occurrence survives only as the aggregate `flow` evidence kind and its score contribution; a user-facing flow summary is out of scope until a non-sensitive product-owned label design exists. Stubs are computed for a unit's *current* file membership against every other baseline unit; it is recomputed fresh on every call in `engine.py::_plan_unit_with_retry` (including every retry-split), so a split child never inherits a stale parent aggregate. `format_boundary_stubs()` renders the compact optional `cross_unit_context` section that `_plan_local`'s CLASSIFY prompt includes through the normal `fit_prompt_sections` optional-section path (can be omitted under a tight budget, never required). It is ordered *first* in `optional_sections`: that fill is greedy in list order and each section consumes the remaining budget, so a trailing tiny section is the first thing an unbounded inventory starves; every other optional section there is unbounded in principle, and this one is capped at `_MAX_STUBS_PER_UNIT` lines. `local_call_edges()` is public and injectable — `serialize()` materializes a dict per edge plus every graph relation, so `plan_docs` derives the pair list once and threads it through `refine_unit_ownership()`/`compute_boundary_stubs()` instead of rebuilding it per unit and per retry-split.
- `deepdoc/planner/merge.py` — `merge_unit_plans()` clones and namespaces all unit buckets, rewrites `depends_on`/`parent_slug`/nav references, merges classifications, and demotes every unit-local introduction to a namespaced service overview. The merged intermediate plan intentionally has no introduction; the full-scan global stage creates the sole repository-wide introduction. `normalize_plan_disposition()` enforces ownership invariants, and `missing_files()` reports undisposed scan files.
- `deepdoc/planner/heuristics.py` — public planning API: `_merge_plan`, `_build_heuristic_assignment`, `_partition_topology_assignment`, `_merge_partial_assignment`, `_llm_step` (tests mock at this path); no longer contains `_shape_plan_nav` or `_decompose_buckets` — both removed as duplicates
- `deepdoc/planner/topology.py` — `build_topology_map()` derives `TopologyMap` from the call graph without LLM involvement; BFS + Jaccard-based clustering (threshold 0.40); feeds the classify step instead of a compressed file tree
- `deepdoc/planner/flow_candidates.py` — `FlowCandidate`, `EntryPoint`; `build_flow_candidates()` traces endpoint families, runtime tasks, and schedulers through the call graph
- `deepdoc/planner/specializations.py` — `_ensure_database_runtime_and_interface_buckets`, `_attach_flow_hints_to_cluster_buckets` (replaces the removed `_ensure_flow_buckets`), `_build_database_buckets`, `_build_runtime_buckets`, `_build_graphql_buckets`
- `deepdoc/planner/nav_shaping.py` — `_shape_plan_nav()` (canonical; orders sections by topology depth via `_section_sort_key()` — no `_compute_section_tier`, tier computed purely from `section_depth`), `_normalize_nav_section` (canonical; heuristics.py duplicate removed)
- `deepdoc/planner/bucket_refinement.py` — bucket ownership, decomposition, consolidation; contains the single canonical `_decompose_buckets`; tracks `merge_target_slugs` to prevent double-absorption
- `deepdoc/planner/bucket_injection.py` — start-here/glossary/debug bucket injection; publication tier assignment; `_looks_like_path_slug_section()`, `_is_backend_placeholder_section()`
- `deepdoc/planner/endpoint_refs.py` — per-endpoint reference page auto-generation
- `deepdoc/planner/common.py`, `deepdoc/planner/utils.py` — shared helpers (`_format_topology_clusters()`, `_build_named_clusters_str()`)

### Generator
- `deepdoc/generator/generation.py` — `BucketGenerationEngine`; `_call_with_retry()` accepts `failure_prefix`; manifest loaded once per run (not per bucket); non-transient LLM errors (auth/quota/invalid model) raise immediately without retry
- `deepdoc/generator/evidence.py` — evidence pack assembly; `flow_context` included for buckets with `flow_id` generation hint; `generation_hints` null-guarded; Tier 0.5 (`_extract_owned_symbol_bodies`): when `owned_symbols` is set and >50% of a Tier 1 file's symbols are unowned, sends only owned symbol bodies + file header instead of full source; uses `Symbol.end_line` when `has_known_range()`, falls back to next-symbol boundary
- `deepdoc/generator/consistency.py` — `CrossBucketConsistencyPass`; single post-generation LLM call that detects cross-link gaps between independently generated pages and appends `:::note[See also]` callouts; runs after `engine.generate_all()` in `pipeline_v2.py`; controlled by `consistency_pass` config key (default `true`); skips gracefully on LLM failure or already-linked pages
- `deepdoc/generator/validation.py` — `PageValidator`; checks sections, files, routes, runtime/config/integration grounding, hallucinated paths/symbols, flow grounding, file coverage
- `deepdoc/generator/post_processors.py` — framework-neutral Markdown repair pipeline (all run in `generation.py` at all three post-processing call sites): `fix_mermaid_diagrams`, fence repair (`repair_unbalanced_code_fences`, `repair_dangling_plain_fences`), `normalize_html_code_blocks`, `normalize_explanatory_lines_outside_fences`, `fix_frontmatter_description` (strips trailing `::` artefacts from YAML `description:`), `fix_bare_mermaid_fences`, `fix_bare_language_markers`, and `repair_internal_doc_links`. **Link rewriting:** `repair_internal_doc_links` is the single owner that validates `/slug` links against the page tree; `_to_mkdocs_relative` is an identity no-op (Next.js uses root-absolute `/slug` paths natively); the glossary linker emits `domain-glossary#slug` directly. No MDX/JSX escaping or Shiki-language normalization exists — the remark/rehype pipeline handles plain CommonMark safely, so `escape_mdx_*`, `normalize_fumadocs_directives`, `fix_leaf_card_directives`, `normalize_code_fence_languages`, and `repair_split_object_code_fences` were all removed.

### Chatbot
- `deepdoc/chatbot/service.py` — `ChatbotQueryService`; two public modes: `query(mode="fast")` (single-pass FAISS) and `deep()` (agentic, code-heavy); re-exports `create_fastapi_app`; tests mock here
- `deepdoc/chatbot/retrieval_mixin.py` — hybrid retrieval: FAISS + SQLite FTS + symbol chunks + relationship chunks; adjacent window stitching; `_evidence_priority`: code/product chunks score above docs (docs get +0.2 vs code +2.5)
- `deepdoc/chatbot/answer_mixin.py` — LLM answer generation, continuation; citation dedup key is `(path, start_line, end_line)`; leading `./` stripped from citation paths
- `deepdoc/chatbot/deep_research.py` — `DeepResearcher` multi-step ReAct loop; agent tools: `search` (semantic FAISS), `read_file` (source archive), `grep` (regex); max 5 iterations per sub-question; `synthesis_token_callback`
- `deepdoc/chatbot/live_fallback_mixin.py` — live filesystem fallback retrieval (keyword-based, archive zip) for deep mode
- `deepdoc/chatbot/routes.py` — FastAPI app factory; two endpoints: `POST /query` (fast), `POST /deep` (agentic); SSE variants `/query/stream` and `/deep/stream`; all SSE endpoints use `timeout=30` + `ping` keepalive
- `deepdoc/chatbot/providers.py` — `LiteLLMChatClient` (including `complete_stream()`), embedding clients; Azure `api_version` propagated from `llm.*` config
- `deepdoc/chatbot/indexer.py` — `ChatbotIndexer`; FAISS invalid-embedding filter (score ≤ -0.5)
- `deepdoc/chatbot/source_archive.py` — `build_source_archive`, `update_source_archive`; archived source is the proof for evidence hydration; updates read only changed paths under a stable archive policy
- `deepdoc/chatbot/persistence.py` — FAISS index save/load plus the canonical `source_archive.sqlite3` content-addressed store; legacy gzip archives migrate on first write
- `deepdoc/chatbot/settings.py` — chatbot config schema
- `deepdoc/chatbot/scaffold.py` — chatbot `chatbot_backend/` scaffolding generator

### Site builder (Next.js + Fumadocs)
- `deepdoc/site/builder/next_builder.py` — **canonical site builder**: `build_next_from_plan()` copies the Next.js + Fumadocs shell template from `next_template/` into `site/`, writes `site/deepdoc.config.json` (nav tree, brand colors, chatbot URL, project name) and `site/app/globals.css` (brand CSS vars). `mkdocs_builder.py` is kept for compatibility but no longer called by the pipeline.
- `deepdoc/site/builder/next_template/` — shipped as package-data; contains the full Next.js + Fumadocs shell (`package.json`, `app/layout.tsx`, `app/[[...slug]]/page.tsx`, `lib/docs.ts`, `lib/nav.ts`, `components/chatbot.tsx`, etc.). Content (`docs/*.md`) is read at build time by `lib/docs.ts` via a **remark/rehype pipeline only** — no MDX JSX compiler ever runs on LLM-generated content, so `{`, `<Tag>` etc. in code blocks cannot crash a build.
- `MermaidRunner` must select `HTMLElement` nodes (`querySelectorAll<HTMLElement>`) because current Mermaid types reject a generic `NodeListOf<Element>`.
- `deepdoc/site/builder/mdx_utils.py` — frontmatter helpers (operate on generated `*.md`)
- Generated pages are plain CommonMark `.md`. The LLM emits GitHub Alert callouts (`> [!NOTE]`, `> [!WARNING]`) and native HTML `<details>` for accordions — no MkDocs pymdownx blocks, no JSX.
- **Chatbot UX** — React `ChatbotWidget` component (`components/chatbot.tsx`): FAB + dock popup using `usePathname()` for SPA-aware navigation (replaces vanilla JS `window.document$` dependency). The `/ask` page (`app/ask/page.tsx`) is a React client component. Brand colors flow via `--brand` / `--brand-light` / `--brand-dark` CSS vars set from `deepdoc.config.json` at generate time. Chatbot backend URL is read client-side from `window.__DD_CONFIG__` (injected by the layout from `deepdoc.config.json`).

### Other modules
- `deepdoc/llm/retry.py` — `is_retryable_llm_error()`; single source of truth for transient-vs-fatal LLM error classification (used by both retry loops)
- `deepdoc/llm/rate_limit.py` — provider-neutral shared concurrency/RPM/TPM limiter with adaptive cooldown; one limiter belongs to each model service/client
- `deepdoc/telemetry.py` — thread-safe, fail-open run telemetry; writes sanitized rotating JSONL under `.deepdoc/performance/` and exposes latest-run loaders for `deepdoc performance`
- `deepdoc/plan_contract.py` — structural generation gate and canonical bucket output/site paths; rejects missing/multiple introductions, duplicate slugs/output writers, unresolved nav slugs, and duplicate nav references before workers start
- `deepdoc/call_graph.py` — `CallGraph`; function-level call extraction; `CALL_KIND_LOCAL`, `CALL_KIND_CELERY`, `CALL_KIND_SIGNAL`, `CALL_KIND_EVENT`; supports Python (Django/Falcon/DRF/FastAPI), JS/TS (Express/Fastify/NestJS), Go, and PHP (Laravel). Import-evidence-gated call-site resolution (never guesses): same-file → imported (alias-aware, multi-hop re-export, cycle-guarded) → unambiguous repo-wide → import-evidence-gated → external. Member calls resolve only with explicit evidence; Python self.method() walks enclosing class's base chain cross-file (transitive, cycle-guarded). NestJS `@UseGuards`/`@UseInterceptors` tracked as graph edges.
- `deepdoc/manifest.py` — `Manifest` class; tracks file → content hash → sorted owning doc paths (legacy single `doc_path` remains readable); stored atomically at `{output_dir}/.deepdoc_manifest.json`
- `deepdoc/openapi.py` — `find_openapi_specs()`, OpenAPI/Swagger spec parser and importer
- `deepdoc/source_metadata.py` — `SOURCE_KIND_CORE`, `SOURCE_KIND_SUPPORTING`, `LOW_TRUST_SOURCE_KINDS`, `FRAMEWORK_PRIORITIES`, `KNOWN_UNSUPPORTED_LANGUAGE_EXTENSIONS` (descriptive-only map used by the CLI coverage warning, e.g. `.java`/`.rs`/`.cs` — never wired into scan gating)
- `deepdoc/benchmark_v2.py` — `BenchmarkResult`; planner quality scorecard harness
- `deepdoc/changelog_writer.py` — `record_and_write` appends to `.deepdoc/changelog.json` and regenerates `docs/whats-changed.md`; generates commit metadata tables, bulleted page lists, and strategy explanation blocks; `_ensure_in_nav` injects `whats-changed` into `Start Here`
- `deepdoc/updater_v2.py` — `UpdaterV2`; legacy V1-era file-map updater (kept for compatibility)
- `deepdoc/_legacy_types.py` — compatibility type shims
- `deepdoc/prompts/__init__.py` — re-export facade; import all prompt constants from here (there is no `prompts_v2.py`)
- `deepdoc/prompts/system.py` — `SYSTEM_V2`, `CROSS_LINK_SECTION`
- `deepdoc/prompts/page_types.py` — page-type prompts; all templates include `{flow_context}` placeholder
- `deepdoc/prompts/bucket_types.py` — bucket-type prompts; all templates include `{flow_context}` placeholder
- `deepdoc/prompts/update.py` — `UPDATE_PAGE_V2`
- `deepdoc/prompts/selectors.py` — `get_prompt_for_bucket`, `get_prompt_for_page_type`
- `deepdoc/parser/routes/` — per-framework route detection and repo-aware resolution (`repo_resolver.py`)
- `deepdoc/scanner/` — runtime, integration, artifact, database extraction
- `tests/` — pytest suite; shared fixtures in `tests/conftest.py`

### Release and infrastructure
- `pyproject.toml` — packaging, dependencies, pytest discovery
- `README.md` — user-facing behavior and documented workflows
- `CONTRIBUTING.md` — contributor guide: local setup, code style, testing expectations, PR process, release flows
- `.github/workflows/release.yml` — Python package release automation (PyPI + GitHub)
- `.github/workflows/release-vscode-extension.yml` — VS Code extension release automation
- `examples/deepdoc-refresh.yml` — example GitHub Actions workflow for teams using DeepDoc to auto-refresh their own docs on push; **not** an active workflow in this repo (was moved out of `.github/workflows/` to prevent spurious CI runs)
- `vscode-extension/package.json` — extension manifest, version, commands, settings
- `vscode-extension/CHANGELOG.md` — extension release notes source

## Architecture Notes

### Planning pipeline (topology-driven, as of 1.9.0)
The planner no longer sends a compressed file tree to the LLM. Instead:
1. `build_topology_map()` uses the pre-built call graph to compute `TopologyCluster` objects via BFS + Jaccard-based merging — no LLM involved.
2. The **classify step** sends topology clusters to the LLM; the LLM names each cluster and assigns a domain section (returns `cluster_names` dict, not per-file classification).
3. The **propose step** receives `named_clusters` (topology clusters enriched with LLM-assigned names/sections) and builds `DocBucket` objects from them.
4. Flow hints (`flow_entrypoints`, `flow_id`, `sequence_diagram`) are attached directly to the domain bucket owning the flow's entry files by `_attach_flow_hints_to_cluster_buckets()` in `specializations.py` — no separate "Core Workflows" bucket is created.
5. `_shape_plan_nav()` (canonical version in `nav_shaping.py`) orders sections by topology cluster depth; `Start Here`/`Overview` pinned front, `Testing`/`CI/CD`/`Supporting Material` pinned tail.

### Key invariants
- Every full `DocPlan` must pass `validate_plan_contract()` before generation: exactly one `is_introduction_page` bucket, one owner per slug/output path, and every non-system nav slug resolved exactly once. The introduction owns `index.md` and `/`. Incremental engines validate the preserved full constructor plan, not their stale-bucket mini-plan.
- `ChangeSet.strategy` never returns `full_replan` for normal changes — all code/file/endpoint changes route to `incremental` or `targeted_replan`. Full replan only via `force_replan=True` or engine fingerprint mismatch.
- `_handle_deleted_files` in `SmartUpdater` is the single place that cleans orphaned buckets (removes from plan, deletes MDX, prunes ledger, cleans `nav_structure`). After it runs, orphaned slugs are filtered from `change_set.stale_bucket_slugs` to prevent redundant regeneration.
- `_append_changelog()` must be called before `_rebuild_nav()` in `smart_update_v2.py` so the `whats-changed` page appears in nav on first run.
- `pipeline_v2._build_site()` must be called after `_record_changelog()` for the same reason.
- `CrossBucketConsistencyPass.run()` must be called after `engine.generate_all()` and before `summarize_generation_results()` so injected callouts are counted before downstream site build. `generate_all()` now owns in-memory manifest updates and final checkpoint persistence; do not restore a redundant `update_manifest()` caller pass.
- After every non-noop `update` run and every `generate` run, a changelog entry is appended to `.deepdoc/changelog.json` and `docs/whats-changed.md` is regenerated. Do not skip these calls when adding new execution paths.
- Targeted replans merge by stable bucket identity (`semantic_id`) and preserve existing slugs when the same concept is rediscovered.
- Bucket slug collision guard: fallback slug generation appends `-2`, `-3`, … suffixes; a bucket that has already absorbed another cannot be absorbed again in the same consolidation pass (`merge_target_slugs` set).
- `_decompose_buckets` is canonical in `bucket_refinement.py` only — the duplicate was removed from `heuristics.py`.
- `_normalize_nav_section` is canonical in `nav_shaping.py` only — the duplicate was removed from `heuristics.py`.
- `_llm_step` labels planner calls through the shared telemetry operation context; `LLMClient` records model wait, character counts, actual provider tokens when available, labelled estimates otherwise, finish reason, and failure type without storing prompt/response text. A prior `Rich.Live()` wrapper was removed because concurrent planner workers corrupted terminal output.
- `deepdoc/llm/token_budget.py` is the single owner of completion-model capabilities and local token counting. Resolution order is explicit config, LiteLLM metadata for `base_model` or model, then a **loud** conservative fallback (`DEFAULT_FALLBACK_CONTEXT_TOKENS`=128000 / `DEFAULT_FALLBACK_OUTPUT_RESERVE_TOKENS`=16000) so an unknown alias never hard-blocks generation. The fallback emits a `RuntimeWarning` and sets `capabilities.source="fallback_default"`; explicit `context_window_tokens`/`output_reserve_tokens`/`base_model` always win and silence it. Capability lookup and token counting must not call a provider. The default must stay *loud* (warn, never silent); `deepdoc init` bakes the resolved fallback into `.deepdoc.yaml` explicitly for unknown models. (This replaced the prior hard `ModelCapabilityError`; the planner's separate `required inventory exceeds ...` error at prompt-fit time is unrelated and still fatal.)
- `deepdoc init` writes automatic completion capability defaults. Existing integer `context_window_tokens`/`output_reserve_tokens` values remain authoritative; custom aliases must supply `base_model` or explicit capability values before generation. The CLI must deep-copy default configuration before writing it.
- Planner dynamic context is token-fitted through `fit_prompt_sections()`: required topology/named-cluster, assignment bucket, and unresolved-file inventories are never sliced; optional records are included whole in deterministic order until the rendered request reaches the resolved model envelope. A required inventory that cannot fit must fail before the LLM call, never fall back to a partial plan.
- A repo with more than one meaningful service (`scan.file_services`) is bounded, not sent through one repo-wide required inventory: `plan_docs()` partitions into `PlanningUnit`s (`partitioning.py`) and plans each independently before merging (`merge.py`). This is what keeps the required ASSIGN/PROPOSE inventories under the token budget on large multi-service repos; see the Planner section above for the module split.
- Active V2 page generation uses the same complete request envelope: raw source, contract, must-cite paths, flow, endpoints, OpenAPI, sitemap/dependencies, and retry material are required; supplemental evidence contexts are admitted whole by priority and recorded in generated provenance when omitted. Keep `LLMClient` preflight as the final assertion.
- ASSIGN preassigns a file only when it is a normal product source with exactly one proposal candidate and a matching topology cluster. Foundational, giant, endpoint-owned, config, supporting-kind, overlapping, and topology-mismatched files remain in the LLM inventory. LLM ownership is filtered to that unresolved inventory before merging; on failure the existing full heuristic assignment remains authoritative.
- Phase 1 performance fixes on `main`: `parse_file()` accepts cached content from `scan_repo`; primary generation evidence reads prefer `scan.file_contents`; route resolution builds only framework-required JS/Python/Go indexes; both generation retry loops use at most 3 attempts with exponential waits capped at 20 seconds. Preserve disk fallbacks for files absent from the scan cache.
- `RepoScan.scan_timings` carries run-scoped base-scan and enrichment timings; when telemetry is active, the same phases plus file/byte counters are available through `deepdoc performance`. Do not persist timing observations in `scan_cache.json`.
- Base scanning collects canonical sorted paths, then uses invocation-local workers for source reads, framework detection, parsing, and endpoint detection. `scan.max_workers` is clamped to 1–32; shared-state merges and progress updates occur only on the coordinator in path order, and repository-wide route resolution remains serial after all contents are available. Never share a tree-sitter `Parser` instance across workers.
- Before a source file is read/parsed, `planner/engine.py::_skip_reason_for_source_file()` skips minified (`*.min.*`), generated/vendored (`/dist/`, `/build/`, `/vendor/`, `/node_modules/`, `/.min/` path segments), oversized (`scan.max_source_bytes`, default 1MB), and binary (NUL byte in first 8KB) files — they never enter `source_work`/`file_contents` or the ASSIGN-prompt inventory. Counts land in `RepoScan.skipped_source_files` and print as a dedicated skip line in `PipelineV2._print_scan()`, separate from the `_print_coverage()` panel (which already excludes them since it's keyed off `scan.file_contents`).
- `parser/routes/common.py::dedupe_endpoints` first removes exact `method:path:line` duplicates, then arbitrates conflicting claims sharing `(method, line, route_file/file, handler)` by keeping only the highest-`FRAMEWORK_PRIORITIES` claim — `handler` is part of the group key so a single synthesized line (e.g. a DRF `router.register(...)` expanding into several actions) isn't mistaken for one conflicting route.
- `parser/routes/repo_resolver.py::_resolve_nestjs_endpoint` composes a repo-wide `app.setGlobalPrefix('...')` onto the per-file `@Controller`+handler path only when exactly one unambiguous `setGlobalPrefix` call exists repo-wide; multiple/conditional calls are left unresolved rather than guessed. `parser/routes/laravel.py` recognizes both `Route::group(['prefix' => ...], fn)` and the fluent `Route::prefix('...')->group(fn)` style.
- `parser/routes/fastapi.py::detect_fastapi` rejects any decorator match whose resolved path does not start with `/` (e.g. `@mock.patch("myapp.services.charge")` matches the same `@obj.patch(...)` shape as a real route decorator but isn't one).
- `PipelineV2._guard_supported_source_files()` runs right after Phase 1 scan, before planning: if `scan.file_contents` is empty it raises `click.ClickException` naming the supported languages (python/javascript/typescript/go/php/vue), distinguishing an empty repo (`scan.total_files == 0`) from a repo with only unsupported/binary/oversized files — instead of reaching `validate_plan_contract()` with an empty inventory and failing with an opaque `PlanContractError`.
- `RepoScan.published_api_endpoints` (filtered by `publication_ready`) is the authoritative endpoint list for every consequential consumer — `planner/heuristics.py::_partition_topology_assignment`'s `endpoint_files` exclusion set, `generator/evidence.py`'s endpoint indexing/fallback lookups, `chatbot/chunker.py::_endpoint_index`, and `pipeline_v2.py`'s OpenAPI-owner mapping. Raw `scan.api_endpoints` remains only for diagnostics/telemetry (scan summary counts, persisted state, smart-update merges) — do not add new consequential consumers of the raw list.
- `EvidenceAssembler` eagerly builds immutable module, symbol, file-line, and symbol-boundary indexes once per engine. Bucket workers must reuse those indexes; do not reintroduce per-bucket whole-repository index construction or mutable unbounded helper caches.
- Evidence uses one context-derived global budget. `llm.context_window_tokens` minus output reserve, safety margin, and template headroom bounds all categories; raw source may use at most 60%. Preserve deterministic category order, line-boundary trimming, final prompt preflight for every retry stage, and provenance fields describing trims.
- `RepoScan.file_content_hashes` is computed with source reads and reused by staleness, manifest, and ledger writes. Manifest ownership is multi-page and sorted. Generation checkpoints after 10 pages or 15 seconds plus final completion; preserve atomic writes and fallback hashing only for scan-missing files.
- Manifest `doc_paths` represent pages completed for the stored source hash. A hash change resets ownership; same-hash checkpoints accumulate it. Bucket freshness requires matching hash, exact output-path ownership, and an existing Markdown file. Preserve this page-aware resume contract for shared sources.
- Page generation uses one persistent bounded `ThreadPoolExecutor`; do not reintroduce per-batch executor creation or joins. Completion is processed as available, but returned results are normalized to plan order before persistence. Hosted requests are additionally bounded by per-service concurrency/RPM/TPM settings and shared adaptive cooldown.
- Transient/non-transient LLM error classification is centralized in `deepdoc/llm/retry.py::is_retryable_llm_error()` (exported from `deepdoc.llm`). Both retry loops — `generator/generation.py::_call_with_retry()` and `pipeline_v2.py::_call_llm_with_retry()` — call it with the exception object; do **not** reintroduce a local `_is_retryable`. It classifies by litellm/openai exception *class name* along the `__cause__`/`__context__` chain (`LLMClient.complete` wraps failures in `RuntimeError(...) from e`, so the original type survives), with a substring fallback for message-only inputs. HTTP **500** / "the server had an error" (the common Azure/OpenAI blip) is **retryable**; auth/invalid-model/bad-request stay fatal and raise immediately.
- MDX brace escaping (`{…}` → `&#123;…&#125;`) skips lines containing `={` to avoid mangling JSX prop assignments.
- Smart-update `merged_plan` now propagates `orphaned_files`, `integration_candidates`, and `classification` from the full plan.
- Semantic endpoint detection carries a transient `RepoScan` on `ChangeSet`; `_execution_scan()` must reuse it for incremental/targeted work and perform exactly one fallback scan only when semantic detection produced none. Never persist or globally memoize this run-scoped scan.
- Safe smart updates build an exact-path scan closure from modified files, their bucket siblings, cached route/handler ownership, entry points, and required config. Collection filters before reads and parsing. New/deleted/artifact/config/OpenAPI changes, Django URL trees, incomplete ownership, or scopes covering at least half the repo visibly fall back to one full scan. Scoped endpoint results replace only authoritative route slices; unaffected cached endpoints and repository metadata must survive persistence.
- A scoped update must perform one complete scan before rebuilding an unhealthy source-backed chatbot corpus (`code`, `symbol`, `artifact`, `repo_doc`, or `relationship`). Healthy corpus updates remain scoped. Never replace a source-backed corpus from a partial `RepoScan`.
- `llm.output_reserve_tokens` protects prompt context but is not an implicit provider output cap. `llm.max_tokens: null` omits the provider parameter; explicit caps are bounded by the reserve. Treat `finish_reason="length"` as an actionable truncation error, never a planner fallback.

### Chatbot architecture
Three independent model surfaces: `llm.*` (doc generation), `chatbot.answer.*` (answer LLM), `chatbot.embeddings.*` (vector embeddings).

Retrieval is hybrid: FAISS vector search (invalid-embedding filter: score ≤ -0.5) + SQLite FTS + symbol chunks + relationship chunks → candidate set → optional rerank → prompt assembly. Evidence-first responses: `evidence[]` is canonical source proof (file path + line range); `references[]` is for generated/repo docs only. Legacy fields (`code_citations`, `doc_links`, `file_inventory`) are derived from those canonical fields.

Incremental chatbot sync inspects each corpus once, skips healthy corpora without effective changed/deleted keys, and fully replaces JSONL/vector/FAISS/FTS state only for touched or unhealthy corpora. Corpus health includes embedding/schema identity, vector count, FAISS presence, and exact FTS row count. Intentionally oversized source files must not create a permanent rebuild loop.

The canonical source archive is `source_archive.sqlite3`: path rows reference independently gzip-compressed SHA-256 blobs and carry catalog metadata in the same transaction. A stable policy fingerprint covers archive limits/excludes; policy changes trigger an atomic full rebuild, while normal updates read and transact only changed/deleted paths. `source_archive.json.gz` remains read-compatible and migrates on first write.

Chatbot answer capability resolution is independent from document generation. An explicitly configured `chatbot.answer` model needs its own known LiteLLM model, `base_model`, or explicit context. Only an inherited answer model may inherit `llm.*` capability settings. Answer, continuation, reranker, and correction prompts must fit the answer-client envelope; retrieval candidate limits remain operational controls.

Deep research uses that same answer-client envelope. Initial evidence is optional whole-record context, but the original goal, current sub-question, completed tool transcript, and completed synthesis findings are required. Never turn a `ModelCapabilityError` into a plausible partial research result.

Embedding capacity is separate from completion capacity. Default FastEmbed Nomic resolves from the local token profile without importing or downloading FastEmbed; first actual embedding still triggers the normal lazy download. Hosted embedding aliases need a LiteLLM-known `base_model` or explicit `max_input_tokens`. Fitted embedding text, hash, and chunk ID must stay aligned, and capacity-policy fingerprint changes rebuild semantic corpora without rebuilding the source archive.

Query modes:
- `POST /query` — fast, single-pass, index-first
- `POST /deep-research` — richer synthesis with bounded archived-source fallback
- `POST /code-deep` — strict source-first, trace output, file inventory

Each has a paired SSE streaming endpoint (`/stream`, `/deep-research/stream`, `/code-deep/stream`). All SSE endpoints use `tokens.get(timeout=30)` and emit `ping` keepalive events on timeout to prevent indefinite hangs. `POST /query-context` provides retrieval-only diagnostics.

Chatbot is opt-in. When `chatbot.enabled` is false, no `/ask` route, chatbot components, or `chatbot_backend/` are scaffolded.

### Azure provider
`LLMClient.__init__` validates that `base_url` and `api_version` are both present before any LLM call. `build_chat_client` applies the same check for chatbot Azure configs. `deepdoc init --provider azure` writes placeholder values for both and shows Azure-specific next steps. Azure `api_version` is propagated when the chatbot inherits its LLM config from `llm.*`.

### Generated-page quality
- Generation retry has up to Step 6.5: Step 6 patches with quality feedback; Step 6.5 does a full clean regeneration with a structured failure report (`_build_failure_prefix`) prepended to the prompt.
- Validation checks: sections, files, routes, runtime/config/integration grounding, hallucinated paths/symbols, flow grounding, low file coverage.
- See `docs/known_issues.md` for a working list of bugs found but not fixed, each with verified cause and concrete next step.
- Bucket size is primarily controlled by three knobs in `planner/topology.py`: `_MAX_CLUSTER_DEPTH`, `_MERGE_JACCARD`, `_FOUNDATIONAL_FRACTION`. Loosening these creates mega-clusters (90+ owned files, heavy evidence compression, cascading validator warnings). See `docs/planner_tuning.md` for current values, rationale, and the verification checklist before changing them.
- Most validator checks are **warning-only**. Hard-fails remain only for: truncated output (`word_count < 100`), leaked placeholders (`placeholder_sections`), and hallucinated file paths (`_check_hallucinated_paths`). All other checks — missing sections, low file coverage, out-of-evidence refs, hallucinated symbols, unmatched routes, flow grounding, contract concepts, runtime entities, config keys, integration grounding — log warnings only and do not trigger Step 6 / Step 6.5 retries. See `docs/validator_demotions.md` for the per-check rationale and the future fix that would let each one return to hard-fail.
- Provenance frontmatter (`deepdoc_generated_*`, `deepdoc_status`, `deepdoc_evidence_files`) on all generated pages; commit badge in the scaffold.
- `deepdoc deploy` quality gate refuses to export when failed/invalid/stub pages exist.

### Glossary limits
`bucket_injection.py` caps glossary evidence at 10 model files. The domain-glossary prompt enforces a 40-term hard cap, skips generic fields (`id`, `created_at`, `email`, etc.), uses `/// details | Domain` grouped output, one Mermaid diagram max, and 300-line page length limit.

### Framework targets
- **Python:** Django, Django REST Framework, Falcon, FastAPI
- **JavaScript / TypeScript:** Express, Fastify, NestJS
- **PHP:** Laravel
- **Go:** conventional HTTP services and supported route helpers
- **Vue:** component and symbol extraction, not a standalone backend route target

DeepDoc can parse a number of source formats, but parsing is not the same as full framework support. Endpoint resolution, runtime discovery, call-graph enrichment, and generated API documentation are only guaranteed for the supported stacks above. **Do not adopt DeepDoc for Flask, Nuxt, or an unlisted framework unless you are prepared to extend scanner coverage first.**

### Other rules
- Prefer extending `_v2` modules over creating new parallel flows.
- Keep `deepdoc/parser/api_detector.py` as a compatibility facade.
- Put repo-aware route fixes in `deepdoc/parser/routes/repo_resolver.py`, not planner code.
- Fix generated output by changing generators/builders, not by hand-editing `docs/`, `site/`, or `.deepdoc/` state.
- If a change touches persisted state or freshness semantics, audit plan, ledger, sync state, manifest, and stale detection together.
- Freshness treats a missing tracked path as a deletion only when that path had a recorded generation hash. Never-existing LLM artifact hints are not allowed to make a freshly generated bucket immediately stale.
- If route behavior or runtime-evidence semantics change materially, update the engine fingerprint in `deepdoc/persistence_v2.py`.
- CLI-facing failures should raise `click.ClickException` or print a clear Rich message.
- If CLI behavior changes, update `README.md` and root `CHANGELOG.md` in the same task.
- The version compatibility warning compares major versions only (`generated_major < cli_major`); message says "run `deepdoc generate`", not "upgrade the CLI".
- `deepdoc_prereqs` frontmatter (prerequisite slugs from `bucket.depends_on`) drives the "Read first:" callout in the scaffold. Keep `_add_provenance_frontmatter` and the DocsPage template in sync.
- Large database estates: keep `database-schema` as overview with child buckets (`parent_slug="database-schema"`); coalesce sparse singleton model groups into stable aggregate groups.
- Database bucket sections normalize to flat `Data Model`; runtime bucket sections normalize to flat `Background Jobs`.
- OpenAPI staging rewrites specs: bakes server base path into every path key, resets `servers` to `[{"url": "/"}]`, places nav entries under `API Playground` (not inside `API Reference`).

## Generated And Derived Files
Treat as generated/persisted outputs — do not hand-edit:
- `.deepdoc/` — all state, plan, ledger, sync baseline
- `.deepdoc/changelog.json` — append-only run log written by `changelog_writer.py`
- `.deepdoc/scan_cache.json`, `.deepdoc/generation_quality.json`, `.deepdoc/consistency_warnings.json`
- `docs/`, `site/`, `site/public/`, `site/out/`
- `build/`, `dist/`, `deepdoc.egg-info/`, `codewiki.egg-info/`, `__pycache__/`, `.pytest_cache/`
- `vscode-extension/out/`, `vscode-extension/*.vsix`, `vscode-extension/node_modules/`
- `deepdoc/generator/mdx_validator/node_modules/`
- `deepdoc/video/node_modules/`
- Test fixture apps under `tests/fixtures/` unless the scenario explicitly requires fixture changes

## Multi-Release Rules
Two independent release tracks — do not mix:
- **Python package**: root `CHANGELOG.md` + `pyproject.toml` + `.github/workflows/release.yml`. Push to `main` with a bumped version to auto-publish to PyPI.
- **VS Code extension**: `vscode-extension/CHANGELOG.md` + `vscode-extension/package.json` + `.github/workflows/release-vscode-extension.yml`.

Release steps: bump version → add CHANGELOG section → commit → push to `main`.

## Install And Build Commands
Prefer `python3` over `python`.

```bash
python3 -m pip install -e .
python3 -m pip install -e ".[chatbot]"   # includes faiss-cpu, fastapi, uvicorn, httpx, fastembed
python3 -m pip install build && python3 -m build
```

If tree-sitter compilation is slow:
```bash
python3 -m pip install click litellm gitpython rich pyyaml jinja2
python3 -m pip install -e . --no-deps
```

Useful runtime commands:
```bash
deepdoc init
deepdoc generate
deepdoc update
deepdoc status
deepdoc performance
deepdoc clean
deepdoc config show
deepdoc config set llm.model gpt-4o
deepdoc serve --port 8001
deepdoc deploy
deepdoc benchmark
```

Notes:
- `deepdoc clean` — removes `.deepdoc.yaml`, generated docs, and saved state; prompts for confirmation unless `--yes`.
- `deepdoc status` — shows all generated pages, staleness, and quality status.
- `deepdoc performance` — shows the latest sanitized generate/update timing and LLM usage record from the 10 MB rotating local history.
- `deepdoc benchmark` — runs the planner quality scorecard against a gold manifest catalog.
- `deepdoc deploy` — runs `npm install` (if needed) + `next build` inside `site/` and exports static HTML to `site/out/`; blocked by the quality gate if failed/invalid/stub pages exist. Requires Node.js ≥18 (no Python site deps needed).
- `deepdoc serve` and `deepdoc deploy` assume generated site files already exist under `site/`.
- `deepdoc update` is commit-based: diffs `.deepdoc/state.json`'s last synced commit against `HEAD`, compares saved scan cache for semantic endpoint changes, then refreshes docs and chatbot state.
- Avoid `deepdoc generate --clean --yes` unless a clean rebuild is explicitly required.
- DeepDoc state writes under `.deepdoc/` use atomic persistence helpers in `persistence_v2.py`; generate/update runs acquire the state lock to prevent concurrent corruption.

## Lint, Type Check, And Test Commands
No formatter, linter, or type checker configured. Do not invent lint commands.

```bash
python3 -m compileall deepdoc
python3 -m pytest -q
python3 -m pytest tests/test_state.py -q
python3 -m pytest tests/test_state.py::test_save_and_load_sync_state_roundtrip -q
python3 -m pytest tests/test_smart_update.py -q
python3 -m pytest -k "route or stale or chatbot" -q
```

## Testing Expectations
- Route work: run route-detector coverage + at least one `scan_repo(...)` regression.
- Topology/planner work: cover topology clustering output and the downstream bucket/evidence/nav behavior together; do not just test `build_topology_map()` in isolation.
- Runtime/database/interface extraction: fixture-backed scan coverage + planner/generator regressions (new metadata must change page planning and evidence, not just raw scan output).
- Freshness/update work: run stale and smart-update tests.
- Chatbot/site work: run chatbot config/scaffold/relationship tests and `tests/test_next_builder.py` if scaffold output changed. When scaffold output changes, also run a real `npm install && next build` inside a generated `site/` to confirm the static site builds.
- For non-trivial changes, prefer a focused test first, then `python3 -m pytest -q` if feasible.
- If you could not run verification, say so clearly and name the next command to run.

## Code Style

### Imports and layout
- `from __future__ import annotations` at top of package modules.
- Import order: stdlib → third-party → local (relative imports inside the package).
- Match existing section-divider comments and module structure.

### Formatting
- PEP 8, 4-space indentation; no enforced autoformatter — match surrounding style.
- Comments only for non-obvious intent; no line-by-line mechanics.

### Types and data modeling
- Type hints on new public functions; built-in generics (`dict[str, Any]`, `list[str]`).
- Dataclasses for structured records.
- Preserve compatibility fields used across v1/v2 boundaries.

### Naming
- `snake_case` functions/variables/test names, `PascalCase` classes, `UPPER_SNAKE_CASE` constants.
- Keep CLI option names consistent: generate, update, serve, deploy, bucket, plan, ledger, sync state.

### Error handling
- CLI-facing failures: `click.ClickException` or a clear Rich `Panel`/`Table`.
- Broad `except Exception` is acceptable around parsing, git, LLM, and persistence boundaries; return a safe fallback or preserve last good state; do not silently swallow actionable errors.

## Safe Workflow For Agents
- Read the relevant v2 modules before changing behavior; the same concept often spans planner, generator, persistence, and smart update.
- If a change touches persisted data or freshness semantics, audit: plan save/load, ledger save/load, sync state save/load, manifest, stale detection, and `_append_changelog` call sites.
- If a change touches routing, audit: per-framework detector, route registry, repo resolver, `scan_repo(...)`, endpoint bucket ownership.
- If a change touches planning, audit: `topology.py`, `flow_candidates.py`, `specializations.py`, `heuristics.py`, `nav_shaping.py`, and `bucket_refinement.py` together.
- If a change touches chatbot behavior, audit: `deepdoc/chatbot/settings.py`, `deepdoc/chatbot/indexer.py`, `deepdoc/chatbot/service.py`, and `deepdoc/chatbot/scaffold.py` (the chatbot backend). The chatbot UI (`components/chatbot.tsx`, `app/ask/page.tsx`) lives in the Next.js site scaffold.
- The Start Here onboarding setup page uses the slug `local-development-setup`; the generic configuration page stays at `setup`.
- This repo may be in a dirty worktree; inspect carefully and never revert unrelated user changes.

## Verification Defaults
- `python3 -m compileall deepdoc`, `python3 -m deepdoc.cli --help`, and targeted `python3 -m pytest ...` runs.
- Prefer the smallest command that exercises the edited area first.

## Web / Marketing Site (`web/`)
An **Astro 5** static marketing/changelog/docs site (Tailwind v4 via `@tailwindcss/vite`) deployed to **Cloudflare Pages** (project `deepdoc`, direct-upload — no Git provider connected, confirmed 2026-07-24 via DNS/`wrangler pages project list`; earlier docs here saying Vercel were stale). Build with `bun run build`, dev with `bun run dev`, deploy with `npx wrangler pages deploy dist --project-name=deepdoc` from `web/`.

### Structure
```
web/
  astro.config.mjs          ← site URL, integrations (sitemap), Tailwind plugin
  src/
    layouts/Layout.astro     ← single shared layout; owns all <head> SEO/meta
    pages/                    ← index.astro, docs.astro, changelog.astro (file-based routing)
    components/               ← Header, Footer, Logo, PipelineOrbit, CodeToDocs (hero SVG animation)
    styles/global.css
  scripts/build-images.mjs  ← `npm run images`: sharp pre-optimizer for hero + OG assets
  src/assets/                ← image masters (proof-docs*.png), never served directly
  public/                    ← static assets: favicon.svg, robots.txt, og.jpg, generated proof-docs-*.webp
```

### Brand logo (`components/Logo.astro`)
Single source of truth for the mark + wordmark (used by Header and Footer). `variant="full"` renders a **merged lockup**: the accent D mark is the leading letter, followed by "eepDoc" — never render the mark next to the full word "DeepDoc" (reads as a repeated D). The mark is em-sized off `wordSize` to match the wordmark cap height. Its scoped `<style>` block owns all `dd-*` styling; do not style `dd-*` classes from `global.css`. Accessibility: the container carries `role="img" aria-label="DeepDoc"`; mark and partial word are `aria-hidden`.

### Landing hero (`index.astro`)
Centered, product-led: source-grounded badge → sans display headline → short sub → equal hosted/local paths → full-width product window (`.hero-stage`/`.hero-window` in `global.css`) with the chat-proof card overlaid bottom-right (stacks static below 640px). `AuroraHeroBackground.astro` provides the decorative original lime-and-teal aurora behind the hero. It uses SVG/CSS only, respects reduced motion, and is simplified on mobile. Keep the animation slow and low-contrast so the headline and product proof remain dominant. `CodeToDocs.astro` remains unused.

### Features bento (`index.astro` "What it does")
The three-card bento keeps proof close to each claim: source files map to doc areas, chatbot messages cite real files, and the update panel shows regenerated files. Cards enter on scroll, then their internal rows/messages/status indicators run quiet looping animations; respect `prefers-reduced-motion` and keep motion secondary to legibility.

### Landing page copy & section rhythm
Marketing copy is **outcome-led, not implementation-led** — say "your docs stay organized / answers cite real files / updates regenerate only what changed", never "bucket", "planner", or "evidence packs" on the landing page (the Pipeline orbit describes mechanics in plain language). Section order: hero → works-with strip → demo video → features bento → pipeline → getting started → CTA (the old "Product proof" section was removed as redundant with the hero window). `.section-raised` (in `global.css`) is applied to the video and getting-started sections to break up the dark stretches — keep roughly alternating dark/raised bands. Header is logo-only (no STABLE chip); nav links are 14px/500.

### SEO
- All meta lives in `Layout.astro`: title, description, canonical, OG (incl. `og:image`/`og:image:alt`), Twitter card, `SoftwareApplication` JSON-LD, `theme-color`. Pages override via the `title`/`description`/`image`/`noindex` props.
- `noindex={true}` on a `<Layout>` emits `<meta name="robots" content="noindex, nofollow">` — used for thin/placeholder pages (e.g. `changelog.astro`).
- Sitemap is generated by `@astrojs/sitemap` at build (`/sitemap-index.xml`). Its `filter` in `astro.config.mjs` excludes `/changelog` so noindex pages stay out of the sitemap — keep the filter in sync when a page is marked `noindex`.
- `public/robots.txt` allows all crawlers and points to the sitemap.
- OG image is `public/og.jpg` (1200×630, ~77 KB) with `og:image:width`/`height`/`type` declared. Regenerate via `npm run images`, never hand-crop — several scrapers (WhatsApp) drop cards over ~300 KB.
- `SoftwareApplication` JSON-LD carries `softwareVersion` — bump it in `Layout.astro` alongside `pyproject.toml`.
- Meta descriptions must stay ≤160 chars and titles ≤60, or they truncate in the SERP.
- Every page needs exactly one `<h1>`. `docs.astro` has a compact one at the top of its main column (it has no hero); don't remove it when reworking that page.

### Design tokens are shared with the marketing site

`page_html.ts` can't import `src/styles/global.css` — it's an HTML string built in a
Worker, not an Astro page — so its `:root` is a hand-copy of the marketing palette.
**`npm run test:tokens` fails if the two drift**, for both themes and for the
`MINI_PAGE_CSS` subset used by the standalone 403/stale pages. Run it after touching
either file. The hosted app keeps the short names (`--ink`, `--surface`) rather than
`--color-*`; renaming buys nothing until these become real `.astro` pages.

Two tokens are intentionally *not* mirrored: `--accent-ink` (text on an accent-filled
button — must be the light surface on light mode's `#4C8B00`) and `--danger` (needs
darkening for light). Marketing has neither.

**Theme crosses the subdomain via a `dd_theme` cookie on `.deepdoc.tech`.** localStorage
is per-hostname and can never reach `cloud.`. The hosted app reads the cookie
server-side, so its theme is correct in the first byte with no no-flash script.
`Header.astro` writes the cookie alongside localStorage; `Layout.astro`'s inline script
prefers cookie over localStorage (marketing pages are prerendered so they can't read it
server-side). **Omit the `domain=` attribute on localhost** or the browser silently drops
the cookie.

### The hosted app's design system (`lib/hosted/page_html.ts`)

Everything below the palette in that `<style>` block is the app's own vocabulary and is
load-bearing for how the signed-in screens read. Reworked 2026-08-03 (the "minimal and
expensive" pass); the rules that pass established:

- **Accent is a state colour, not a fill.** `#C2FF4D` marks selection, focus rings,
  live/ready status dots, and the brand mark. Nothing else. **Primary buttons are
  ink-filled** via `--solid`/`--solid-ink` (near-white on dark, near-black on light).
  A lime slab under every action was the single loudest thing on these screens; do not
  put it back.
- **Mono is for code only.** `--font-mono` is reserved for a pasted repo URL and inline
  `code`. Repo names, page titles, labels and status text all render in `--font-sans`.
  Mono-as-UI-text was what made the app read as a terminal toy rather than a product.
- **One page width, owned by the render functions.** `--w-page` is set from
  `document.body.dataset.view` (`'app'` → 736px, anything else → 1152px) and read by BOTH
  `.appbar-inner` and `.page`, so the brand mark sits directly above the page title.
  **`route()` deliberately does NOT set it** — `/projects` is a wide grid while
  `/generate` and the detail page are narrow columns, so each of `renderProjects`,
  `renderProjectDetail`, `renderGenerate`, `renderGenerating`, `renderPublicGallery`,
  `renderLoggedOut` and `renderPublicInProgress` sets it as its first statement. A new
  render path that forgets inherits the previous screen's width.
- **One card grid, two configurations** (`.card-grid`/`.card`, 2026-08-03, modelled on
  DeepWiki's layout). The public gallery's cards carry a real screenshot
  (`.card-shot` + `.gallery-shot`); **`/projects` cards deliberately carry none** — on
  your own list the name and build state are what you scan for, and a wall of thumbnails
  of sites you already know is noise. Both grids lead with a single `.card-new` (accent
  gradient, `+` glyph) which is the primary CTA; that replaced the header "Generate new"
  button, so don't re-add one. `grid-auto-rows: minmax(150px, auto)` is what stops a row
  of description-less cards coming out shorter than the row above it.
- **`.card[hidden]` and `.repo-item[hidden]` both need explicit `display: none`** — both
  carry an author-level `display` that outranks the UA's `[hidden]` rule, and both are
  filtered by toggling `hidden`. Drop either rule and the matching search box silently
  stops filtering.
- **The gallery's search field does two jobs**: substring-filters the example cards
  (against a `data-name` haystack of owner/repo + description + language) and recognises
  a pasted GitHub link, offering to generate it. Because generating needs auth, the URL
  is stashed in `localStorage.dd_pending_repo` and `renderGenerate()` consumes it exactly
  once via `consumePendingRepo()` — that handoff is what stops the visitor having to find
  and paste the link again after OAuth.
- **Removed 2026-08-03, on purpose:** the gallery cards' rotating conic-gradient "border
  beam" and the `attachTilt()` mousemove 3D tilt. The DeepWiki-style grid is calm and
  flat; both effects fought it. `fallbackHue()` went with them (dead since the live-iframe
  previews were replaced by screenshots).
- **One button shape.** `.btn` plus `secondary`/`ghost`, `small`/`large`, and text-only
  `.link-danger`/`.link-quiet` for destructive and tertiary actions. Do not add a sixth
  button shape.
- **Type ramp** is the fixed `.t-display`/`.t-title`/`.t-body`/`.t-sub`/`.t-meta` classes.
  Negative tracking above 18px is what stops large text reading as scaled-up body copy.
- **`--seg-track`/`--seg-thumb` exist because the neutral ramp only runs one direction.**
  The visibility segmented control's active thumb must read as *raised* in both themes,
  which means lighter than its track on dark and lighter than the page on light. Deriving
  it from `--surface-*` gives a thumb that looks recessed on dark. These two are the only
  hard-coded colours outside the mirrored palette.
- **`.repo-item` is a real `<button>`** (keyboard focus and Enter/Space for free), which
  means it carries an author-level `display: block` that outranks the UA's `[hidden]`
  rule — hence the explicit `.repo-item[hidden] { display: none }`. Delete that and
  `filterRepos()` silently stops filtering.
- **No backticks or `${` inside the CSS**, comments included. The whole stylesheet is
  inside a JS template literal; a backtick in a comment ends the string and the Astro
  build fails with a bare `Expected ";"`.

Verify a change here with all three: `npm run test:tokens`, `npm run build`, and
`npm run test:hosted` (the last one is the only thing that parses the client JS — it now
also covers the gallery filter, the pasted-link detection and its escaping, and the
`dd_pending_repo` handoff).

### Gallery thumbnails (`lib/hosted/thumb.ts`, `api/thumb/[owner]/[repo].ts`)

The public gallery serves real screenshots, captured once via the Cloudflare
Browser Rendering REST API and cached in R2 under
`thumbs/{owner}/{repo}/{createdAt}.jpg`. The timestamp in the key makes the served
URL immutable — a regenerate writes a new key and the old one is simply orphaned.

Only ever captures sites that are **public and `done`**, re-checked immediately before
the write; a private site would capture its own 403 page, and a mid-generation one
would pin a picture of the progress screen for a year.

Requires two Pages secrets: `CF_ACCOUNT_ID` and `CF_BROWSER_TOKEN` (an API token with
**Browser Run → Edit**; the dashboard renamed Browser Rendering to Browser Run, but the
REST path is still `/browser-rendering/screenshot`). Without them the endpoint serves a
designed SVG placeholder rather than failing.

**Two variants per site, light and dark.** Generated docs sites use `next-themes`, which
falls back to `prefers-color-scheme` and applies the result as a *class* on `<html>`. A
headless browser reports no preference, so every capture came out light — glaring inside a
dark gallery. Browser Rendering has no colour-scheme emulation, but `addScriptTag` can set
the class directly, and the site's dark styling is plain CSS keyed off it (verified: mean
luma 236 → 27). Light needs no forcing; it's the default render.

Theme is part of both the R2 key and the request URL (`?t=dark|light`) rather than read
from the cookie, so each variant keeps its own immutable, independently cacheable address —
a cookie-varying image URL would defeat the CDN and the `immutable` Cache-Control. The
gallery swaps `img.src` in place on toggle via `data-owner`/`-repo`/`-created`.

**Gotcha: Pages binds secrets at deploy time.** `wrangler pages secret put` alone does
*not* reach the running deployment — you must redeploy afterwards or the Worker keeps
seeing `undefined`. Symptom: the endpoint still returns `image/svg+xml` while the token
works fine against the API directly.

Capture is rate-limited by design (free tier allows 6 REST calls/min): a per-repo R2 lock
stops several viewers racing the same cold card, and `thumbs/_budget.json` caps real
captures at 4/min account-wide. Everything over the cap takes the placeholder, so a cold
gallery warms over a few minutes of traffic rather than stampeding.

### Hosted app client JS — no compiler covers it

The hosted app's ~720 lines of client JS live inside a template string in
`src/lib/hosted/page_html.ts`. Neither `tsc` nor the Astro build ever parses that string, so
a syntax error or a regressed failure path ships silently. Every backtick and `${` inside it
must be escaped (`` \` ``, `\${`).

`npm run test:hosted` pulls the **rendered** script off a running server and exercises
`poll()`'s failure paths against a stubbed DOM. Run it after touching that file:

```bash
npm run build && npx wrangler pages dev dist --port 8788 &
npm run test:hosted
```

Stability invariants it protects — do not regress these:
- `poll()` must treat HTTP 401 as "session expired, build still running", not as a stage.
  An unchecked `res.json()` there yields `status: undefined`, which is neither `done` nor
  `failed`, so the poll reschedules forever behind a ticking timer.
- Every `fetch` in that file needs a `catch` **and** a `res.ok` check. `/api/me` failing
  unguarded leaves the page permanently blank; unchecked mutations make a failed delete or
  visibility change look successful.
- Values from GitHub or the backend go through `escapeHtml()` before reaching `innerHTML`.
- `#appbar-slot` and `#content` carry `min-height` so the page doesn't jump on boot.

To exercise the real hostname locally without editing `/etc/hosts`, launch Chrome with
`--host-resolver-rules="MAP cloud.localhost 127.0.0.1"` and visit `http://cloud.localhost:8788/`.

### Image pipeline (`scripts/build-images.mjs`)
Hero screenshots and the OG card are pre-optimized **offline** by sharp into `public/`, from masters in `src/assets/`. Run `npm run images` after replacing a master.

Do **not** switch these to `astro:assets` `<Image>`: `index.astro` is server-rendered on purpose (it shares `/` with the hosted app shell via the `src/middleware.ts` hostname rewrite), and `@astrojs/cloudflare`'s `imageService: "compile"` can only optimize on *prerendered* pages — Cloudflare has no sharp at runtime. Static WebP plus a hand-written `srcset`/`sizes` is the working combination.

The hero renders at ≤1104 CSS px (`max-w-6xl` minus `px-6`), so two widths (1104/2208) cover standard and retina. Both the light and dark variants are always fetched — `display:none` does not cancel an `<img>` download, and the theme is a `data-theme` attribute set by the header toggle, so a `prefers-color-scheme` `<picture>` would desync from a manual switch. Keeping both small (~48/125 KB) is the accepted tradeoff.

### Changelog
`changelog.astro` is currently a placeholder (marked `noindex`). The canonical release history lives in root `CHANGELOG.md`.

### Cloudflare Pages deployment
| Setting | Value |
|---|---|
| Project name | `deepdoc` |
| Bound domains | `deepdoc.tech`, `deepdoc.pages.dev` |
| Root Directory | `web` |
| Install Command | `bun install` |
| Build Command | `bun run build` |
| Output Directory | `dist` |
| Deploy command | `npx wrangler pages deploy dist --project-name=deepdoc` (from `web/`, after `bun run build`) |

## Hosted-generation ("Try DeepDoc") — LIVE IN PRODUCTION at cloud.deepdoc.tech

A secondary, no-CLI hosted flow: sign in with GitHub, pick a repo (yours —
public or private — via a picker, or paste any public URL), and get a real
generated docs site at a vanity `/owner/repo/` URL. Deployed on Azure +
Cloudflare. **See `docs/PRODUCTION_INFRA.md` for the full resource inventory,
maintenance commands, and teardown steps** — this section covers the code/dev
side only.

- **`web/hosted/` is retired (2026-07-25) — merged into `web/`.** The hosted
  app is no longer a separate Cloudflare Worker; it's now part of the same
  Astro project that serves the marketing site, both on the same Cloudflare
  **Pages** project (`deepdoc`), with `cloud.deepdoc.tech` and `deepdoc.tech`
  as two custom domains on that one project. This was a deliberate
  unification (near-zero hosted-product traffic at the time made it the
  cheapest possible moment) — see `docs/PRODUCTION_INFRA.md` for the
  before/after and the exact cutover steps taken, and `docs/HOSTED_UI_SPEC.md`
  for the full page/route spec (IA/visual content unchanged by this move —
  only the framework and deploy target changed).
  - `web/astro.config.mjs` — `output: 'server'` + `@astrojs/cloudflare` adapter
    (**pinned to `12.6.13`** — the `13.x`/`14.x` lines require Astro 6/7, this
    project is on Astro 5.18.1; do not blindly `bun update` this package).
  - `web/wrangler.toml` — D1 (`DB` → `deepdoc-hosted-db`) + R2 (`SITES` →
    `deepdoc-hosted-sites`) bindings for the Pages project. Secrets
    (`GITHUB_CLIENT_ID`, `GITHUB_SECRET_ID`, `QUEUE_MESSAGES_URL`) are
    `wrangler pages secret put --project-name=deepdoc` in production, `.dev.vars`
    locally — same pattern as before, just `pages secret` instead of `secret`.
  - `web/src/middleware.ts` — **the entire routing trick.** Marketing pages
    (`index.astro`, `docs.astro`, `changelog.astro`) live unprefixed at the
    project root; the hosted app's pages/endpoints live under
    `src/pages/cloud/`. The middleware rewrites any request whose hostname is
    `cloud.deepdoc.tech` (or `cloud.localhost` for local dev — see below) by
    prefixing `/cloud` onto the path before Astro's router resolves it — so
    the *external* URL a browser or GitHub's OAuth callback sees stays
    unprefixed (`/`, `/generate`, `/api/auth/callback/github`, ...), byte-for-byte
    what it was on the old Worker. GitHub's registered OAuth callback URL did
    not need to change.
  - **`index.astro` is intentionally NOT prerendered**, unlike `docs.astro`/
    `changelog.astro`. `/` is the one path both domains use (marketing
    homepage vs. the hosted app's shell/sign-in-gate), and Cloudflare Pages
    serves a prerendered path as a static asset *before* the Function/
    middleware ever runs — so if `/` were static, it would always serve the
    marketing homepage regardless of hostname. This was a real bug caught
    during the migration verification, not a hypothetical. Do not
    re-prerender `index.astro` without re-deriving this.
  - Local dev: real hostname-based branching needs a real hostname, not just
    a path — visiting `/cloud/generate` directly does **not** work (the
    client JS's relative `fetch('/api/me')` would hit the marketing
    namespace, not `/cloud/api/me`). Either add `127.0.0.1 cloud.localhost`
    to `/etc/hosts` and browse `http://cloud.localhost:4321`, or for one-off
    curl testing use `curl --resolve cloud.localhost:PORT:127.0.0.1 ...`
    (no `/etc/hosts` edit needed). `bun run build && npx wrangler pages dev dist`
    gives real D1/R2 bindings locally (`astro dev` alone does not);
    `wrangler d1 execute deepdoc-hosted-db --local --file=hosted-schema-backup...`
    equivalent — the local D1 SQLite file is empty until you apply the schema
    once (see `web/hosted`'s old `schema.sql`, kept for reference during the
    transition — the table structure itself did not change).
  - Route structure under `src/pages/cloud/`: `index.ts`, `generate.ts`,
    `projects/index.ts`, `projects/[owner]/[repo].ts` (all four just serve
    the same app-shell HTML — the client-side script picks the view),
    `try.ts`/`account.ts`/`new.ts` (302 stale-bookmark redirects to `/`),
    `auth/github.ts` + `api/auth/callback/github.ts` (OAuth), `api/me.ts`,
    `api/repos.ts`, `api/generate.ts`, `api/status/[id].ts`,
    `api/projects/index.ts`, `api/projects/[owner]/[repo].ts` (DELETE),
    `api/projects/[owner]/[repo]/visibility.ts` (POST), and
    `[owner]/[repo]/[...path].ts` (the site-proxy catch-all). **Astro's own
    static-route-beats-dynamic-route priority replaces the old Worker's
    manual regex-ordering comments** ("must stay last", "must be matched
    before") — a literal file always wins over a `[...path]` catch-all at the
    same position, so there's no ordering to get wrong here.
  - Shared logic lives in `web/src/lib/hosted/`: `queue.ts` (`enqueueJob`/
    `fetchJobStatus` — the Azure Storage Queue dispatch contract, unchanged),
    `session.ts` (session/quota helpers — cookie handling now goes through
    Astro's `cookies.get/set/delete` instead of manual `Cookie`/`Set-Cookie`
    header parsing), `page_html.ts` (the actual page markup + the entire
    client-side vanilla-JS SPA — **ported verbatim** from the old
    `try_page.ts`, not rewritten, to avoid regressions in already-shipped,
    already-tested UI).
    - The "Continue with GitHub" button (`startGithubAuth`) and the
      "Generate"/"Regenerate" button (`startJob`) both disable + swap to a
      pulsing-dot loading label (`.btn-spinner`, reuses the existing `pulse`
      keyframe) immediately on click, since both trigger a real network
      round-trip (D1 write + OAuth redirect; DB reads/writes + queue enqueue)
      with no other feedback otherwise. `startJob` restores the button and
      shows an error box on any failure (non-2xx *or* a thrown `fetch`) so it
      never gets stuck disabled. The generation stage list's "cloning" glow
      is not separately delayed — it already lights up the instant the
      generating screen mounts; the perceived lateness was this same
      pre-fetch dead-click gap.
    - The stage-list accordion's sub-items (`STAGE_DETAIL`) are still static
      placeholder copy, not real per-page progress — making them real
      requires new plumbing (deepdoc's generation loop has no live progress
      artifact to tail; see `.claude/MEMORY.md` if a follow-up picks this up).
  - `web/src/env.d.ts` — `App.Locals` typed via `@astrojs/cloudflare`'s
    `Runtime<T>` so every endpoint gets `locals.runtime.env.DB` /
    `.SITES` / etc. with real types (needs `@cloudflare/workers-types` as a
    devDependency for the ambient `D1Database`/`R2Bucket` globals it
    references).
  - **A profile dropdown** (avatar chip, click to open, outside-click/Escape
    to close) is the only account surface — identity + a "Projects (N) ›"
    link + "Generate new" + Log out **only**; it deliberately does not list
    projects inline (that was tried and explicitly rejected — see
    `docs/HOSTED_UI_SPEC.md` rule 14). **The app bar reuses `deepdoc.tech`'s
    own `Header.astro`/`Logo.astro` recipe** (52px sticky bar, blurred
    background, the same "depth D" brand-mark SVG, still inlined as a JS
    string in `page_html.ts`'s `brandMarkHtml()` rather than a real shared
    Astro component — the hosted pages are plain `.ts` endpoints returning
    raw HTML strings, not `.astro` components, so they can't `import
    Logo.astro` directly. A true shared component is a reasonable future
    cleanup, not done in this pass).
  - **All state lives in Cloudflare D1** (`deepdoc-hosted-db`, schema:
    `sessions`, `oauth_states`, `projects`, `rate_limit_starts`,
    `owner_repo_jobs`) — unchanged by the migration. **Accounts & visibility**
    (`docs/PRODUCTION_INFRA.md` has the full detail): each site has a
    `visibility` (`private` default for new generations) on both `projects`
    and `owner_repo_jobs`; `owner_repo_jobs.owner_login` is the single owner
    (first generation wins, `handleGenerate` 409s a second user). Private-site
    access is enforced **server-side** in the `[owner]/[repo]/[...path].ts`
    catch-all — a private site requires `session.login == owner_login` before
    serving ANY byte incl. `/_next/*` assets (real boundary: the R2 bucket
    isn't public, this endpoint is the only read path).
- **Project card metadata is fetched server-side, not trusted from the
  client (since 2026-08-25).** `api/generate.ts` calls GitHub's
  `repos/{owner}/{repo}` with the session token before dispatch and stores the
  resulting description/language/stars/avatar on the `projects` row; the POST
  body's values are only a fallback for a transient GitHub failure. Before
  this, metadata was whatever the browser sent, so the paste-a-URL path (which
  sends none) left most rows null and the public gallery rendered bare cards.
  An explicit GitHub **404 is now a 400** from this endpoint — a nonexistent
  or invisible repo used to fail minutes later inside the container job. Any
  other GitHub failure must keep degrading to null metadata rather than
  blocking a build. `web/scripts/backfill-project-meta.mjs` (dry-run by
  default, `--apply` to write) repairs pre-existing rows.
- `api/examples.ts` dedupes by lowercased `owner/repo`: `owner_repo_jobs` is
  unique on `(owner, repo)` case-**sensitively**, so the same repo reached
  under a differently-cased owner produced two gallery cards for one site.
- **Dispatch = queue + event-driven Container Apps Job (autoscaling, since
  2026-07-24).** Generation compute is NO LONGER an always-on runner — the old
  `deepdoc-runner` Container App is retired. `src/pages/cloud/api/generate.ts`
  mints a `job_id` and enqueues `{job_id,owner,repo,github_token,visibility}`
  (base64-JSON, via `src/lib/hosted/queue.ts`'s `enqueueJob`) onto the Azure
  Storage Queue `deepdoc-jobs` via `QUEUE_MESSAGES_URL` (queue REST + add-only
  SAS). A KEDA `azure-queue` scaler on the Container Apps **Job**
  `deepdoc-gen-job` starts one isolated execution per message (min 0 / max 10,
  4 vCPU / 8 GiB each) → **scale-to-zero when idle (~$0)**. The token rides in
  the message (private queue, deleted after processing). Status/serving are R2:
  the job writes `jobs/{id}/status.json` and the site `{owner}/{repo}/…`, and
  the Pages Function reads both from R2 (`fetchJobStatus`) — it never talks to
  a container. The site proxy (`cloud/[owner]/[repo]/[...path].ts`) serves
  one of four terminal screens by status: served R2 bytes (`done`, files
  present), `tryPageHtml` SPA shell (non-terminal — queued/cloning/generating/
  building, incl. the null-status startup window), `failedPageHtml` (`failed` —
  honest error page showing `status.json.error`), and `stalePageHtml` (**only**
  `done` with files evicted from R2). Do not re-collapse `failed` into
  `stalePageHtml` — its "generated successfully" copy is a lie for a failed job. **KEDA can occasionally spawn a duplicate no-op execution
  (polling race); it's harmless — only one execution can lease a message, so
  no duplicate generation. Stop a lingering one with `az containerapp job
  stop`.**
- `hosted-runner/` — the container image (`deepdoc-runner:vN` in ACR, build
  context = **repo root**). Unaffected by the Astro unification — it talks to
  Cloudflare D1/R2 via bindings/S3-API, never to whatever is consuming the
  queue on the Cloudflare side. `pipeline.py` holds the shared clone → `deepdoc
  generate` → `deepdoc deploy` → R2-upload logic plus `write_status` (R2
  `jobs/{id}/status.json`). `job.py` is the Job entrypoint (`--command python
  --args job.py`): dequeues one message from `deepdoc-jobs` with a 1-hr
  visibility lease (so it isn't redelivered mid-run / double-counted), runs the
  pipeline, deletes the message on any terminal state, exits. `app.py` (the old
  FastAPI HTTP server) is legacy/vestigial post-cutover — kept but unused.
  `DEEPDOC_BIN` resolves to a local `.venv/bin/deepdoc` if present else `PATH`
  (do not re-hardcode the `.venv` path — that was a real bug). The message
  encoding is **base64(JSON)** on both sides: the Cloudflare side `btoa()`s it,
  `job.py` uses `TextBase64DecodePolicy` — keep them in sync.
- **Next.js `basePath` must be baked in at build time to match the serving
  URL, or CSS/JS 404s.** The generated static export assumes root-path
  hosting by default; since sites are served at `/{owner}/{repo}/`, not
  domain root, the runner sets `NEXT_PUBLIC_BASE_PATH=/{owner}/{repo}` as a
  build-time env var before running `deepdoc deploy` (the template already
  reads this var — see `deepdoc/site/builder/next_template/next.config.mjs`).
  This bit twice during development (once locally, once — differently — for
  the vanity-URL redesign) before landing on baking the real owner/repo path
  directly rather than a job-id path. Do not revert to job-id-based serving
  paths without re-deriving this.
- **Known-working Azure config for the custom `DeepSeek-V4-Flash` deployment**:
  LiteLLM has no metadata for this alias, so `llm.context_window_tokens: 128000`
  and `llm.output_reserve_tokens: 16000` must be set explicitly in
  `.deepdoc.yaml`, and `llm.api_key_env` must be `AZURE_API_KEY` (not
  `AZURE_OPENAI_API_KEY`). Omitting `context_window_tokens` fails fast with
  `ModelCapabilityError` before any LLM call — `deepdoc/llm/token_budget.py`'s
  intended fail-closed behavior, not a bug to work around. Foundry account
  `deepdoc-foundry` (pre-existing) lives in Azure resource group
  `deepdoc-main`/`eastus`, `base_url:
  https://deepdoc-foundry.services.ai.azure.com/`.
- Verified end-to-end live in real production (not just local), both before
  and after the Astro unification: private-repo clone with an authenticated
  token, a full generate→deploy run through the real deployed
  Cloudflare → Container App → Foundry pipeline, the resulting site served
  correctly at its real `cloud.deepdoc.tech/<owner>/<repo>/` URL with working
  CSS, and the project persisting in D1 across requests (proving real state
  persistence, not same-isolate luck).
- **Access control now enforced** (was previously absent) — sites default to
  private (owner-only, session-checked server-side including asset paths); a
  user opts into public via the dashboard toggle. See the accounts/visibility
  note above and `docs/PRODUCTION_INFRA.md`.
- Known limitations accepted for this first production pass (see
  `docs/PRODUCTION_INFRA.md` for the full list): runner job state is still
  in-process memory (fine at min=max=1 replica, lost on restart); no Key
  Vault (Container App secrets are sufficient at this scale); scale-to-zero
  Container Apps Jobs is a deferred cost optimization over the current
  always-on Container App.

## Notes from the creator
- Internal tool for a team working in: Python, Go, PHP, JS/TS — frameworks include Fastify, Express, Laravel, Django, Falcon, Go.
- Goal: one-step solution to create and update docs with an embedded chatbot that can answer anything from the codebase, comparable in depth to Devin's DeepWiki.
- Do not assume anything; stop and ask questions until the direction is clear.
