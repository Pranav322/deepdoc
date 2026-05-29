# AGENTS.md
Guidance for coding agents working in this repository.

## Scope
- Applies to the repository root.
- If you change core CLI behavior, persistence/state formats, routing semantics, or generated-site behavior, update this file in the same task. Also keep `README.md` in sync with actual codebase behavior.

## Repo Summary
- Project name: `deepdoc` (v2.3.6)
- Language/runtime: Python `>=3.10`
- Packaging: setuptools via `pyproject.toml`
- CLI entrypoint: `deepdoc = deepdoc.cli:main`
- Test runner: `pytest`
- Main implementation path is the v2 bucket-based pipeline.
- Generated docs live in `docs/` (configurable); the generated Fumadocs site lives in `site/`.
- Repo also contains a VS Code extension at `vscode-extension/` (Node/TypeScript, independent release track) and a Remotion marketing video project at `deepdoc/video/` (not part of the Python pipeline).

## Important Paths

### Core pipeline
- `deepdoc/cli.py` — Click commands: `init`, `generate`, `update`, `clean`, `status`, `benchmark`, `serve`, `deploy`, `config show/set`
- `deepdoc/config.py` — `.deepdoc.yaml` defaults, loading, and `_set_nested` type inference
- `deepdoc/pipeline_v2.py` — end-to-end orchestration; `PipelineV2` class; `_spec_base_path()` and `_write_spec()` for OpenAPI rewriting; `_build_site()` must be called *after* `_record_changelog()`
- `deepdoc/v2_models.py` — `DocBucket`, `DocPlan`, `RepoScan` (now carries `call_graph`, `topology_map`, `flow_candidates` fields), `_BucketAsPage`
- `deepdoc/smart_update_v2.py` — `SmartUpdater`, `ChangeSet`, `UpdateRunResult`, `UpdateSyncPlan`, `SemanticImpact`; `_handle_deleted_files` pre-step; `_append_changelog` must be called before `_rebuild_nav()`
- `deepdoc/persistence_v2.py` — `.deepdoc/` state, plan, ledger, sync baseline, changelog, engine fingerprint

### Planner
- `deepdoc/planner/engine.py` — repo-scan entrypoint and bucket-planning orchestration
- `deepdoc/planner/heuristics.py` — public planning API: `_merge_plan`, `_build_heuristic_assignment`, `_llm_step` (tests mock at this path); no longer contains `_shape_plan_nav` or `_decompose_buckets` — both removed as duplicates
- `deepdoc/planner/topology.py` — `build_topology_map()` derives `TopologyMap` from the call graph without LLM involvement; BFS + Jaccard-based clustering (threshold 0.40); feeds the classify step instead of a compressed file tree
- `deepdoc/planner/flow_candidates.py` — `FlowCandidate`, `EntryPoint`; `build_flow_candidates()` traces endpoint families, runtime tasks, and schedulers through the call graph
- `deepdoc/planner/specializations.py` — `_ensure_database_runtime_and_interface_buckets`, `_attach_flow_hints_to_cluster_buckets` (replaces the removed `_ensure_flow_buckets`), `_build_database_buckets`, `_build_runtime_buckets`, `_build_graphql_buckets`
- `deepdoc/planner/nav_shaping.py` — `_shape_plan_nav()` (canonical; uses topology depth via `_section_sort_key()`), `_normalize_nav_section` (canonical; heuristics.py duplicate removed)
- `deepdoc/planner/bucket_refinement.py` — bucket ownership, decomposition, consolidation; contains the single canonical `_decompose_buckets`; tracks `merge_target_slugs` to prevent double-absorption
- `deepdoc/planner/bucket_injection.py` — start-here/glossary/debug bucket injection; publication tier assignment; `_looks_like_path_slug_section()`, `_is_backend_placeholder_section()`
- `deepdoc/planner/endpoint_refs.py` — per-endpoint reference page auto-generation
- `deepdoc/planner/common.py`, `deepdoc/planner/utils.py` — shared helpers (`_format_topology_clusters()`, `_build_named_clusters_str()`)

### Generator
- `deepdoc/generator/generation.py` — `BucketGenerationEngine`; `_call_with_retry()` accepts `failure_prefix`; manifest loaded once per run (not per bucket); non-transient LLM errors (auth/quota/invalid model) raise immediately without retry
- `deepdoc/generator/evidence.py` — evidence pack assembly; `flow_context` included for buckets with `flow_id` generation hint; `generation_hints` null-guarded; Tier 0.5 (`_extract_owned_symbol_bodies`): when `owned_symbols` is set and >50% of a Tier 1 file's symbols are unowned, sends only owned symbol bodies + file header instead of full source; uses `Symbol.end_line` when `has_known_range()`, falls back to next-symbol boundary
- `deepdoc/generator/consistency.py` — `CrossBucketConsistencyPass`; single post-generation LLM call that detects cross-link gaps between independently generated pages and appends `:::note[See also]` callouts; runs after `engine.generate_all()` in `pipeline_v2.py`; controlled by `consistency_pass` config key (default `true`); skips gracefully on LLM failure or already-linked pages
- `deepdoc/generator/validation.py` — `PageValidator`; checks sections, files, routes, runtime/config/integration grounding, hallucinated paths/symbols, flow grounding, file coverage
- `deepdoc/generator/post_processors.py` — MDX repair pipeline; `repair_mdx_component_blocks` calls `_repair_accordion_nesting` first; brace escaping skips lines containing `={`; `normalize_mdx_steps`, `escape_mdx_text_hazards`, `inject_source_files_disclosure`; **MDX hazard fixers** (all run in `generation.py` at all three post-processing call sites): `normalize_fumadocs_directives` (maps `:::warn`/`:::error`/`:::success` → valid fumadocs callout names), `fix_frontmatter_description` (strips trailing `::` artefacts from YAML `description:` field), `fix_bare_mermaid_fences` (inserts missing ` ```mermaid ` opening fence when LLM writes bare `mermaid` text), `fix_bare_language_markers` (fixes both `:typescript` suffix and standalone `typescript`-on-its-own-line patterns), `fix_leaf_card_directives` (converts `::card{...}\nCONTENT\n::` to `:::card{...}\nCONTENT\n:::` container directives)

### Chatbot
- `deepdoc/chatbot/service.py` — `ChatbotQueryService`; `query`, `deep_research`, `code_deep`; re-exports `create_fastapi_app`; tests mock here
- `deepdoc/chatbot/retrieval_mixin.py` — hybrid retrieval: FAISS + SQLite FTS + symbol chunks + relationship chunks; adjacent window stitching
- `deepdoc/chatbot/answer_mixin.py` — LLM answer generation, continuation; citation dedup key is `(path, start_line, end_line)`; leading `./` stripped from citation paths
- `deepdoc/chatbot/deep_research.py` — `DeepResearcher` multi-step research loop with `synthesis_token_callback`
- `deepdoc/chatbot/live_fallback_mixin.py` — live filesystem fallback retrieval for deep-research mode
- `deepdoc/chatbot/routes.py` — FastAPI app factory; all SSE streaming endpoints use `tokens.get(timeout=30)` with `ping` keepalive events to prevent indefinite hangs
- `deepdoc/chatbot/providers.py` — `LiteLLMChatClient` (including `complete_stream()`), embedding clients; Azure `api_version` propagated from `llm.*` config
- `deepdoc/chatbot/indexer.py` — `ChatbotIndexer`; FAISS invalid-embedding filter (score ≤ -0.5)
- `deepdoc/chatbot/source_archive.py` — `build_source_archive`, `update_source_archive`; archived source is the proof for evidence hydration
- `deepdoc/chatbot/persistence.py` — FAISS index save/load; invalid-embedding filter on load
- `deepdoc/chatbot/settings.py` — chatbot config schema
- `deepdoc/chatbot/scaffold.py` — chatbot `chatbot_backend/` scaffolding generator

### Site builder
- `deepdoc/site/builder/scaffold_files.py` — non-chatbot scaffold generators; `_docs_page_tsx` wires `findNeighbour` (prev/next arrows) and "Read first:" callout from `deepdoc_prereqs` frontmatter; provenance badge renders `deepdoc_generated_at` + `deepdoc_generated_commit`
- `deepdoc/site/builder/chatbot_components.py` — chatbot TSX/TS generators (`_chatbot_panel_tsx`, `_chatbot_config_ts`, `_chatbot_toggle_tsx`)
- `deepdoc/site/builder/templates.py` — re-export facade; import scaffold functions from here

### Other modules
- `deepdoc/call_graph.py` — `CallGraph`; function-level call extraction; `CALL_KIND_LOCAL`, `CALL_KIND_CELERY`, `CALL_KIND_SIGNAL`, `CALL_KIND_EVENT`; supports Python (Django/Falcon/DRF) and JS/TS (Express/Node)
- `deepdoc/manifest.py` — `Manifest` class; tracks file → content-hash → doc-path; stored at `{output_dir}/.deepdoc_manifest.json`
- `deepdoc/openapi.py` — `find_openapi_specs()`, OpenAPI/Swagger spec parser and importer
- `deepdoc/source_metadata.py` — `SOURCE_KIND_CORE`, `SOURCE_KIND_SUPPORTING`, `LOW_TRUST_SOURCE_KINDS`, `FRAMEWORK_PRIORITIES`
- `deepdoc/benchmark_v2.py` — `BenchmarkResult`; planner quality scorecard harness
- `deepdoc/changelog_writer.py` — `record_and_write` appends to `.deepdoc/changelog.json` and regenerates `docs/whats-changed.mdx`; generates commit metadata tables, bulleted page lists, and strategy explanation blocks; `_ensure_in_nav` injects `whats-changed` into `Start Here`
- `deepdoc/updater_v2.py` — `UpdaterV2`; legacy V1-era file-map updater (kept for compatibility)
- `deepdoc/_legacy_types.py` — compatibility type shims
- `deepdoc/prompts_v2.py` — re-export facade; import all prompt constants from here
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
- `ChangeSet.strategy` never returns `full_replan` for normal changes — all code/file/endpoint changes route to `incremental` or `targeted_replan`. Full replan only via `force_replan=True` or engine fingerprint mismatch.
- `_handle_deleted_files` in `SmartUpdater` is the single place that cleans orphaned buckets (removes from plan, deletes MDX, prunes ledger, cleans `nav_structure`). After it runs, orphaned slugs are filtered from `change_set.stale_bucket_slugs` to prevent redundant regeneration.
- `_append_changelog()` must be called before `_rebuild_nav()` in `smart_update_v2.py` so the `whats-changed` page appears in nav on first run.
- `pipeline_v2._build_site()` must be called after `_record_changelog()` for the same reason.
- `CrossBucketConsistencyPass.run()` must be called after `engine.update_manifest(gen_results)` and before `summarize_generation_results()` in `pipeline_v2.py` so injected callouts are counted in the final summary and written to disk before any downstream site build step.
- After every non-noop `update` run and every `generate` run, a changelog entry is appended to `.deepdoc/changelog.json` and `docs/whats-changed.mdx` is regenerated. Do not skip these calls when adding new execution paths.
- Targeted replans merge by stable bucket identity (`semantic_id`) and preserve existing slugs when the same concept is rediscovered.
- Bucket slug collision guard: fallback slug generation appends `-2`, `-3`, … suffixes; a bucket that has already absorbed another cannot be absorbed again in the same consolidation pass (`merge_target_slugs` set).
- `_decompose_buckets` is canonical in `bucket_refinement.py` only — the duplicate was removed from `heuristics.py`.
- `_normalize_nav_section` is canonical in `nav_shaping.py` only — the duplicate was removed from `heuristics.py`.
- `_llm_step` no longer wraps LLM calls in `Rich.Live()` — that caused terminal corruption with concurrent `ThreadPoolExecutor` workers.
- Non-transient LLM errors (auth failures, invalid model names, quota errors) raise immediately in `_call_with_retry()`; only rate-limit and transient errors trigger backoff.
- MDX brace escaping (`{…}` → `&#123;…&#125;`) skips lines containing `={` to avoid mangling JSX prop assignments.
- Smart-update `merged_plan` now propagates `orphaned_files`, `integration_candidates`, and `classification` from the full plan.

### Chatbot architecture
Three independent model surfaces: `llm.*` (doc generation), `chatbot.answer.*` (answer LLM), `chatbot.embeddings.*` (vector embeddings).

Retrieval is hybrid: FAISS vector search (invalid-embedding filter: score ≤ -0.5) + SQLite FTS + symbol chunks + relationship chunks → candidate set → optional rerank → prompt assembly. Evidence-first responses: `evidence[]` is canonical source proof (file path + line range); `references[]` is for generated/repo docs only. Legacy fields (`code_citations`, `doc_links`, `file_inventory`) are derived from those canonical fields.

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
`bucket_injection.py` caps glossary evidence at 10 model files. The domain-glossary prompt enforces a 40-term hard cap, skips generic fields (`id`, `created_at`, `email`, etc.), uses `<Accordions>` grouped output, one Mermaid diagram max, and 300-line page length limit.

### Framework targets
Supported scan targets: Python (Django, Falcon, DRF), Go, PHP (Laravel), JS/TS (Express, Fastify, NestJS). Next.js, Nuxt, FastAPI, and Flask are **not** supported scan targets; they are used internally by the generated site and chatbot stacks. Extend scanner coverage in `deepdoc/scanner/` before adding generator-only heuristics.

### Other rules
- Prefer extending `_v2` modules over creating new parallel flows.
- Keep `deepdoc/parser/api_detector.py` as a compatibility facade.
- Put repo-aware route fixes in `deepdoc/parser/routes/repo_resolver.py`, not planner code.
- Fix generated output by changing generators/builders, not by hand-editing `docs/`, `site/`, or `.deepdoc/` state.
- If a change touches persisted state or freshness semantics, audit plan, ledger, sync state, manifest, and stale detection together.
- If route behavior changes materially, update the engine fingerprint in `deepdoc/persistence_v2.py`.
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
- `deepdoc benchmark` — runs the planner quality scorecard against a gold manifest catalog.
- `deepdoc deploy` — runs the Next.js/Fumadocs build and exports `site/out/`; blocked by the quality gate if failed/invalid/stub pages exist.
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
- Chatbot/site work: run chatbot config/scaffold/relationship tests and `tests/test_fumadocs_builder.py` if scaffold output changed.
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
- If a change touches chatbot behavior, audit: `deepdoc/chatbot/settings.py`, `deepdoc/chatbot/indexer.py`, `deepdoc/chatbot/service.py`, `deepdoc/chatbot/scaffold.py`, and `deepdoc/site/builder/chatbot_components.py`.
- The Start Here onboarding setup page uses the slug `local-development-setup`; the generic configuration page stays at `setup`.
- This repo may be in a dirty worktree; inspect carefully and never revert unrelated user changes.

## Verification Defaults
- `python3 -m compileall deepdoc`, `python3 -m deepdoc.cli --help`, and targeted `python3 -m pytest ...` runs.
- Prefer the smallest command that exercises the edited area first.

## Web / Marketing Site (`web/`)
A pnpm workspace containing the DeepDoc marketing/changelog site deployed to Vercel.

### Structure
```
web/
  artifacts/deepdoc-site/   ← Vite + React site (deploy target)
  artifacts/api-server/     ← local API server (not deployed to Vercel)
  artifacts/mockup-sandbox/ ← design sandbox (not deployed to Vercel)
  lib/                      ← shared workspace libraries
  scripts/                  ← build/codegen scripts
  package.json              ← workspace root
  pnpm-workspace.yaml       ← pnpm catalog + security settings
```

### Changelog automation
`web/artifacts/deepdoc-site/src/pages/Changelog.tsx` has no hardcoded release data. It imports from `virtual:changelog-data`, a Vite virtual module in `vite.config.ts` (`changelogPlugin`) that reads `CHANGELOG.md` from the repo root at build time (`path.resolve(import.meta.dirname, "../../../CHANGELOG.md")`).

**Rule**: never hardcode release entries in `Changelog.tsx`. Only edit `CHANGELOG.md`.

### Vercel deployment settings
| Setting | Value |
|---|---|
| Root Directory | `web` |
| Install Command | `pnpm install` |
| Build Command | `pnpm --filter @workspace/deepdoc-site run build` |
| Output Directory | `artifacts/deepdoc-site/dist/public` |

CHANGELOG path is 3 levels up from `web/artifacts/deepdoc-site/`. If the path breaks, count from there.

## Notes from the creator
- Internal tool for a team working in: Python, Go, PHP, JS/TS — frameworks include Fastify, Express, Laravel, Django, Falcon, Go.
- Goal: one-step solution to create and update docs with an embedded chatbot that can answer anything from the codebase, comparable in depth to Devin's DeepWiki.
- Do not assume anything; stop and ask questions until the direction is clear.
