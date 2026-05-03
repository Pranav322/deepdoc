# AGENTS.md
Guidance for coding agents working in this repository.
This file might be stale and if that is the case please update it first 

## Scope
- Applies to the repository root.

- If you change core CLI behavior, persistence/state formats, routing semantics, or generated-site behavior, update this file in the same task. ANd also make sure that README.md is in sync with actual codebase.

## Repo Summary
- Project name: `deepdoc`
- Language/runtime: Python `>=3.10`
- Packaging: setuptools via `pyproject.toml`
- CLI entrypoint: `deepdoc = deepdoc.cli:main`
- Test runner: `pytest`
- Main implementation path is the v2 bucket-based pipeline.
- Generated docs usually live in `docs/`; the generated site lives in `site/`.
- Repo also contains a VS Code extension module at `vscode-extension/` with its own Node/TypeScript toolchain and Marketplace release flow.

## Important Paths
- `pyproject.toml`: packaging, dependencies, pytest discovery
- `README.md`: user-facing behavior and documented workflows
- `.github/workflows/release.yml`: Python package release automation (PyPI + GitHub release)
- `.github/workflows/release-vscode-extension.yml`: VS Code extension release automation
- `vscode-extension/package.json`: extension manifest, version, commands, settings
- `vscode-extension/CHANGELOG.md`: extension release notes source
- `deepdoc/cli.py`: Click commands, Rich output, serve/deploy flow
- `deepdoc/config.py`: defaults and `.deepdoc.yaml` helpers
- `deepdoc/pipeline_v2.py`: end-to-end orchestration
- `deepdoc/planner/engine.py`: repo scan entrypoint and bucket planning orchestration
- `deepdoc/planner/heuristics.py`: public planning API — `_merge_plan`, `_build_heuristic_assignment`, `_llm_step` (keep here; tests mock it at this path)
- `deepdoc/planner/nav_shaping.py`: nav structure, section ordering, endpoint reference nav
- `deepdoc/planner/bucket_refinement.py`: bucket ownership, file attachment, decomposition, consolidation
- `deepdoc/planner/bucket_injection.py`: start-here/debug/research-context bucket injection, publication tier assignment
- `deepdoc/planner/endpoint_refs.py`: auto-generation of per-endpoint reference pages
- `deepdoc/generator/generation.py`: page generation orchestration
- `deepdoc/generator/evidence.py`: page evidence assembly
- `deepdoc/generator/validation.py`: generated-page validation
- `deepdoc/persistence_v2.py`: `.deepdoc/` state, plan, ledger, sync baseline
- `deepdoc/smart_update_v2.py`: incremental update and replan logic
- `deepdoc/parser/routes/`: route detection and repo-aware resolution
- `deepdoc/scanner/`: runtime, integration, artifact, and data extraction helpers
- `deepdoc/chatbot/service.py`: `ChatbotQueryService` public API — `query`, `deep_research`, `code_deep`; re-exports `create_fastapi_app` and provider names (keep imports here; tests mock against this module)
- `deepdoc/chatbot/retrieval_mixin.py`: all retrieval, search, rerank, expansion, and hit-selection methods
- `deepdoc/chatbot/answer_mixin.py`: LLM answer generation, continuation, prompt building
- `deepdoc/chatbot/live_fallback_mixin.py`: live filesystem fallback retrieval
- `deepdoc/chatbot/routes.py`: FastAPI app factory (`create_fastapi_app`) and all HTTP route handlers
- `deepdoc/chatbot/providers.py`: `LiteLLMChatClient` (including `complete_stream`), embedding clients
- `deepdoc/chatbot/deep_research.py`: `DeepResearcher` multi-step research loop
- `deepdoc/site/builder/scaffold_files.py`: non-chatbot scaffold file generators (package.json, tsconfig, CSS, layout TSX, etc.)
- `deepdoc/site/builder/chatbot_components.py`: chatbot-specific TSX/TS generators (`_chatbot_panel_tsx`, `_chatbot_config_ts`, `_chatbot_toggle_tsx`)
- `deepdoc/site/builder/templates.py`: re-export facade + any remaining orchestration; import from here for all scaffold functions
- `deepdoc/prompts_v2.py`: re-export facade — all prompt constants and selectors live in `deepdoc/prompts/`
- `deepdoc/prompts/system.py`: `SYSTEM_V2`, `CROSS_LINK_SECTION`
- `deepdoc/prompts/page_types.py`: page-type prompt strings (overview, architecture, guide, module, api_reference, setup, deployment, integration)
- `deepdoc/prompts/bucket_types.py`: bucket-type prompt strings (feature, endpoint, integration, database, runtime, graphql, start-here, glossary, runbook, etc.)
- `deepdoc/prompts/update.py`: `UPDATE_PAGE_V2` incremental update prompt
- `deepdoc/prompts/selectors.py`: `PROMPT_STYLE_TEMPLATES`, `get_prompt_for_bucket`, `get_prompt_for_page_type`
- `tests/`: pytest suite and fixtures

## Architecture Notes
- Prefer extending `_v2` modules instead of creating new parallel flows.
- Keep `deepdoc/parser/api_detector.py` as a compatibility facade.
- Put repo-aware route fixes in `deepdoc/parser/routes/repo_resolver.py`, not planner code.
- Target-repo framework support is intentionally scoped. Next.js, Nuxt, FastAPI, and Flask are not supported scan targets; preserve the generated site and chatbot stacks, which still use Next.js and FastAPI internally.
- Runtime/background-job, GraphQL, and data-layer extraction should flow through `deepdoc/scanner/` into `RepoScan` metadata, then be consumed by `deepdoc/planner/` and `deepdoc/generator/`; avoid one-off generator-only heuristics when scan metadata can be made explicit.
- Runtime extraction currently includes Celery, `node-cron`, JS queue/agenda workers, Go workers/schedulers, Django management commands/signals/Channels, Laravel jobs/events/listeners/scheduler registrations, Socket.IO/websocket consumers, and lightweight crontab-style declarations. Extend those families in `deepdoc/scanner/runtime.py` before inventing generator-only runtime prose.
- Large database estates should stay in the overview-plus-groups model: keep `database-schema` as the overview page and use child buckets with `parent_slug="database-schema"` for deterministic subgroup coverage.
- Planner nav shaping is reader-first and repo-agnostic: preserve deterministic specialized sections where needed, but normalize backend docs toward a natural flow (`Start Here` → `Core Workflows` → `API Reference` → `Data Model` → runtime/integrations/ops) instead of raw bucket order.
- Database grouping should avoid one-file micro-pages when model estates are large; coalesce sparse singleton model groups into stable aggregate groups (for example `core-models`) so coverage remains complete without nav noise.
- Fix generated output by changing generators/builders, not by hand-editing `docs/`, `site/`, or `.deepdoc/` state.
- Preserve `source_kind` and `publication_tier` semantics consistently across planner, persistence, generation, smart update, and chatbot indexing.
- Chatbot responses are evidence-first: `evidence[]` is canonical for source/config proof and the generated right-pane code viewer; `references[]` is for generated docs and repo-authored docs only. Legacy fields (`code_citations`, `doc_links`, `code_workspace_citations`, `file_inventory`) should be derived from those canonical fields.
- Chatbot indexing now has explicit source/archive artifacts plus separate corpora for code chunks, symbol chunks, config artifacts, generated docs, repo docs, and relationships. Keep generated/internal outputs (`.deepdoc*`, `docs/`, `site/`, `chatbot_backend/`) out of source evidence.
- Chatbot retrieval is hybrid: SQLite FTS lexical search, symbol chunks, relationship chunks, and embedding search feed the candidate set, and exact-match code hits can stitch adjacent windows from the same file. These indexes are candidate retrieval only; hydrated source archive/catalog snippets are the proof.
- Query modes are intentional: `/query` runs Fast mode (single-pass, index-first, lower prompt budget, LLM retrieval steps disabled by default), `/deep-research` runs richer synthesis with bounded archived-source fallback and doc references, and `/code-deep` runs strict source-first retrieval with trace output and no generated-doc code proof. Each mode has a paired SSE streaming endpoint (`/query/stream`, `/deep-research/stream`, `/code-deep/stream`) that yields `token` events during answer generation followed by a final `result` event; the generated chatbot UI uses these by default and falls back to the non-streaming endpoints when streaming is unavailable.
- The chatbot backend also exposes `/query-context` for retrieval-only diagnostics (selected candidates, hydrated `evidence[]`, `references[]`, and diagnostics without answer generation); keep this endpoint aligned with fast-mode selection logic.
- The backend validates answer grounding: no invented file paths, no unknown evidence IDs, no docs as implementation proof, and no `line unknown`. If a retry still fails, fail closed with diagnostics instead of fabricating right-pane evidence.
- For realtime UX, `/code-deep/stream` emits SSE trace events during research followed by the final result payload.
- Chatbot is an opt-in concern. When `chatbot.enabled` is false, keep the generated site docs-only: do not scaffold `/ask`, chatbot frontend components, or `chatbot_backend/` artifacts.
- CLI commands that load repo config emit a configurable compatibility warning when existing generated docs were produced by a deprecated DeepDoc version. Keep `compatibility.deprecated_version_warning.*` behavior and README/CHANGELOG documentation in sync when changing this warning.
- The generated docs pages still use Fumadocs MDX rendering, but the custom chatbot answer pane and right-pane code modal share their own lazy Prism highlighter via `react-syntax-highlighter`; keep those custom surfaces visually aligned without replacing the Fumadocs docs-page path.
- Published API docs should come from validated runtime endpoints via `RepoScan.published_api_endpoints`, but scanned endpoints should enrich grouped endpoint-family pages instead of creating one generated MDX page per route. Keep per-route pages limited to canonical OpenAPI assets or legacy plans.
- Generated Fumadocs output must stay MDX-safe and GitHub-Pages-safe: preserve explicit site base-path support in the scaffold and escape raw destructured brace args in markdown tables before writing docs.
- Generated-page validation now checks not just sections/files/routes, but also runtime/config/integration grounding when that evidence was assembled. Keep those checks aligned with `deepdoc/generator/evidence.py`.
- Generated-page validation also guards against hallucinated file paths, hallucinated symbol references, and low file coverage on core pages. Keep validator failures actionable for the retry prompt.
- Generated pages carry DeepDoc provenance frontmatter (`deepdoc_generated_*`, `deepdoc_status`, `deepdoc_evidence_files`) and the generated Fumadocs site surfaces the commit badge when available.
- If freshness/state semantics change, audit `deepdoc/planner/`, `deepdoc/generator/`, `persistence_v2.py`, and `smart_update_v2.py` together.
- If route behavior changes materially, update the engine fingerprint in `deepdoc/persistence_v2.py`.

## Generated And Derived Files
Treat these as generated or persisted outputs unless the task is specifically about their format:
- `.deepdoc/` contents and legacy files like `.deepdoc_plan.json` and `.deepdoc_file_map.json`
- `.deepdoc/scan_cache.json`, including runtime summaries, database groups, GraphQL interface summaries, and Knex artifact summaries
- `.deepdoc/generation_quality.json`
- `.deepdoc/consistency_warnings.json`
- `docs/`, `site/`, `site/public/`, and `site/out/`
- `build/`, `dist/`, `deepdoc.egg-info/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`
- `vscode-extension/out/`, `vscode-extension/*.vsix`, `vscode-extension/node_modules/`
- Test fixture apps under `tests/fixtures/` unless the scenario explicitly requires fixture changes

## Multi-Release Rules
- This repository has two independent release tracks:
  - Python package release uses root `CHANGELOG.md` + `pyproject.toml` + `.github/workflows/release.yml`.
  - VS Code extension release uses `vscode-extension/CHANGELOG.md` + `vscode-extension/package.json` + `.github/workflows/release-vscode-extension.yml`.
- Do not mix versions or changelog entries between these tracks.
- If extension behavior changes, update `vscode-extension/README.md` and `vscode-extension/CHANGELOG.md`.
- If CLI/package behavior changes, update root `README.md` and root `CHANGELOG.md`.

## Install And Build Commands
Prefer `python3` over `python` in this repo.

```bash
python3 -m pip install --upgrade pip
python3 -m pip install -e .
python3 -m pip install -e . pytest
python3 -m pip install -e ".[chatbot]"
python3 -m pip install build
python3 -m build
python3 -m deepdoc --help
python3 -m deepdoc.cli --help
deepdoc --help
```

If tree-sitter compilation is slow, the lighter fallback documented in `README.md` is:

```bash
python3 -m pip install click litellm gitpython rich pyyaml jinja2
python3 -m pip install -e . --no-deps
python3 -m pip install pytest
```

Useful runtime commands:

```bash
deepdoc init
deepdoc generate
deepdoc update
deepdoc serve --port 8001
deepdoc deploy
```

Notes:
- `deepdoc deploy` runs the generated Next/Fumadocs build and exports `site/out/`.
- `deepdoc serve` and `deepdoc deploy` assume generated site files already exist under `site/`.
- Avoid destructive generation modes like `deepdoc generate --clean --yes` unless the task explicitly requires a clean rebuild.
- `deepdoc update` is commit-based: it diffs the last synced commit in `.deepdoc/state.json` against the current `HEAD`, compares the saved scan cache with the current scan for semantic endpoint changes, then refreshes docs and chatbot state from one update run.

## Lint, Type Check, And Test Commands
- No formatter, linter, or type checker is configured in `pyproject.toml`.
- No checked-in config was found for `ruff`, `black`, `isort`, `flake8`, `mypy`, `pyright`, `tox`, or `nox`.
- Do not invent repo-standard lint or type-check commands unless the user explicitly asks for them.
- Practical verification here is `compileall`, CLI/import smoke checks, and pytest.

```bash
python3 -m compileall deepdoc
python3 -m pytest -q
python3 -m pytest tests/test_state.py -q
python3 -m pytest tests/test_state.py::test_save_and_load_sync_state_roundtrip -q
python3 -m pytest tests/test_smart_update.py -q
python3 -m pytest -k "route or stale or chatbot" -q
```

Single-test guidance:
- Run one file: `python3 -m pytest tests/test_state.py -q`
- Run one test: `python3 -m pytest tests/test_state.py::test_save_and_load_sync_state_roundtrip -q`
- Run by expression: `python3 -m pytest -k "baseline and not partial" -q`
- Use `-q` by default for focused runs.

## Testing Expectations
- For route work, run route-detector coverage plus at least one `scan_repo(...)` regression.
- For runtime/database/interface extraction work, add fixture-backed scan coverage plus planner/generator regressions so the new metadata changes page planning and page evidence, not just raw scan output.
- For runtime extraction work, cover both scanner output and the downstream runtime bucket/evidence/validation behavior.
- For freshness or update work, run stale and smart-update tests, not just tiny helper tests.
- For chatbot or generated-site work, run chatbot config/scaffold/relationship tests and `tests/test_fumadocs_builder.py` if scaffold output changed.
- For non-trivial changes, prefer a focused test first, then `python3 -m pytest -q` if feasible.
- If you could not run verification, say so clearly and name the next command to run.

## Code Style

### Imports And Module Layout
- Start package modules with a short module docstring.
- Use `from __future__ import annotations` in package modules; that is the prevailing pattern.
- Group imports as standard library, third-party, then local package imports.
- Prefer relative imports inside the package when neighboring modules already do.
- Match existing section-divider comments and overall module structure where they already exist.

### Formatting And Structure
- Follow existing PEP 8 style with 4-space indentation.
- Match surrounding formatting; there is no enforced autoformatter.
- Prefer targeted changes over broad rewrites.
- Keep comments sparse and practical; explain non-obvious intent, not line-by-line mechanics.

### Types And Data Modeling
- Add type hints to new public functions and important helpers.
- Prefer built-in generics like `dict[str, Any]` and `list[str]`.
- Use dataclasses for structured records, matching `planner_v2.py`, `generator_v2.py`, and related scan models.
- Preserve compatibility fields and return shapes used across v1/v2 boundaries.

### Naming Conventions
- Use `snake_case` for functions, variables, and test names.
- Use `PascalCase` for classes and dataclasses.
- Use `UPPER_SNAKE_CASE` for module-level constants.
- Keep CLI option names and user-facing terms consistent with existing vocabulary: generate, update, serve, deploy, bucket, plan, ledger, sync state.

### Error Handling And UX
- CLI-facing failures should usually raise `click.ClickException` or print a clear Rich message.
- Rich console output via `Console`, `Panel`, and `Table` is the dominant CLI UX pattern.
- Broad `except Exception` blocks already exist around parsing, git, LLM, and persistence boundaries; if you catch broadly, return a safe fallback or preserve the last good state.
- Avoid silently swallowing actionable errors in core flows.

### Testing Style
- Tests use pytest with `test_*.py` discovery under `tests/`.
- Shared fixtures live in `tests/conftest.py`.
- Prefer focused regression tests near the changed behavior instead of adding large new fixture trees.

## Safe Workflow For Agents
- Read the relevant v2 modules before changing behavior; the same concept often spans planner, generator, persistence, and smart update.
- If a change touches persisted data or freshness semantics, audit plan save/load, ledger save/load, sync state save/load, manifest updates, and stale detection.
- If a change touches routing, audit the per-framework detector, route registry, repo resolver, `scan_repo(...)`, and endpoint bucket ownership.
- If a change touches chatbot behavior, audit `deepdoc/chatbot/settings.py`, `deepdoc/chatbot/indexer.py`, `deepdoc/chatbot/service.py`, `deepdoc/chatbot/scaffold.py`, and `deepdoc/site/fumadocs_builder_v2.py`.
- The generated chatbot now supports three shared-context answer modes over one visible thread:
  - `POST /query` for fast retrieval answers
  - `POST /deep-research` for heavier synthesis using the same `question` + `history` request contract
  - `POST /code-deep` for code-aware deep answers with `trace`, canonical `evidence[]`, `references[]`, and compatibility `file_inventory`
- For live progress updates, use `POST /code-deep/stream` (SSE) with the same `question` + `history` request contract.
- The Start Here onboarding setup page uses the slug `local-development-setup`; keep the generic configuration page at `setup`.
- If you change documented CLI behavior, update `README.md` in the same task.
- This repo may be in a dirty worktree; inspect carefully and never revert unrelated user changes.

## Verification Defaults
- Good default checks are `python3 -m compileall deepdoc`, `python3 -m deepdoc.cli --help`, and targeted `python3 -m pytest ...` runs.
- Prefer the smallest command that exercises the edited area first.


## Web / Marketing Site (`web/`)

The `web/` folder is a pnpm workspace containing the DeepDoc marketing/changelog site,
deployed to Vercel. Key facts for agents working here:

### Structure
```
web/
  artifacts/deepdoc-site/   ← the Vite + React site (deploy target)
  artifacts/api-server/     ← local API server (not deployed to Vercel)
  artifacts/mockup-sandbox/ ← design sandbox (not deployed to Vercel)
  lib/                      ← shared workspace libraries
  scripts/                  ← build/codegen scripts
  package.json              ← workspace root
  pnpm-workspace.yaml       ← pnpm catalog + security settings
```

### History / Why it looks like this
- Originally lived at `web/deep-doc-design/` (a Replit project with its own `.git`).
- Migrated on 2026-05-03: the inner `.git` was removed and the contents were flattened
  directly into `web/` so the parent repo (`codewiki`) tracks them.

### Changelog automation
`web/artifacts/deepdoc-site/src/pages/Changelog.tsx` **has no hardcoded release data**.
It imports from `virtual:changelog-data`, a Vite virtual module defined in
`web/artifacts/deepdoc-site/vite.config.ts` (`changelogPlugin`).

The plugin reads `CHANGELOG.md` from the repo root at build time (path:
`path.resolve(import.meta.dirname, "../../../CHANGELOG.md")`), parses every
`## [x.y.z] - date` section, and bakes the result into the JS bundle.

**Rule**: never hardcode release entries in `Changelog.tsx`. Only edit `CHANGELOG.md`.

### Vercel deployment settings
| Setting | Value |
|---|---|
| Root Directory | `web` |
| Install Command | `pnpm install` |
| Build Command | `pnpm --filter @workspace/deepdoc-site run build` |
| Output Directory | `artifacts/deepdoc-site/dist/public` |

If the CHANGELOG path in `vite.config.ts` ever breaks, count directory levels from
`web/artifacts/deepdoc-site/` up to the repo root — currently **3 levels** (`../../../`).

## Notes from the creator 

- i am creating it for my internal team , we mostly work with the mentioned languages (python , go ,php ,  js/ts - frameworks including fastify , express , laravel , django , falcon , go )
- i am creating one step solution to create and update docs which contains cahtbot 
- i want the chatbot to be able to answer anything literally form the codebase 
- the docs shoudl be complete enough and comparable to deepwiki by devin 
- you are not supposed to assume anything , at any step stop and ask me question until you are sure about in whcih direction to take the projects  
