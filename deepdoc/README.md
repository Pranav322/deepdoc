# deepdoc — Python Package

The core DeepDoc product. A five-phase AI pipeline that scans a codebase, plans a documentation structure, generates rich MDX pages, and builds a local Fumadocs site with optional AI chatbot.

## Install

```bash
pip install deepdoc

# With chatbot support (adds faiss-cpu, fastapi, uvicorn, fastembed)
pip install "deepdoc[chatbot]"
```

Development install from this repo:

```bash
python3 -m pip install -e .
python3 -m pip install -e ".[chatbot]"
```

## Quick usage

```bash
cd your-repo
deepdoc init          # creates .deepdoc.yaml
deepdoc generate      # scan → plan → generate → build site
deepdoc serve         # preview at http://localhost:3000
deepdoc update        # incremental re-gen for changed files
```

## Package structure

```
deepdoc/
├── cli.py                  # Click commands (generate, update, serve, deploy, chatbot, …)
├── config.py               # .deepdoc.yaml defaults and loader
├── pipeline_v2.py          # End-to-end orchestration (5 phases)
├── smart_update_v2.py      # Incremental update / targeted replan logic
├── persistence_v2.py       # .deepdoc/ state — plan, ledger, scan cache, sync baseline
├── v2_models.py            # DocBucket, DocPlan, RepoScan data models
│
├── planner/                # Phase 2 — LLM bucket planning
│   ├── engine.py           # scan_repo() + plan_docs() orchestration
│   ├── heuristics.py       # Public planning API (_merge_plan, _llm_step)
│   ├── common.py           # Shared prompts, endpoint keyword map
│   ├── bucket_refinement.py  # Ownership, decomposition, consolidation
│   ├── nav_shaping.py      # Nav structure and section ordering
│   ├── endpoint_refs.py    # API-reference bucket generation
│   └── topology.py         # Cluster topology for section ordering
│
├── scanner/                # Phase 1 — static analysis (no LLM)
│   ├── endpoints.py        # Route/endpoint detection
│   ├── runtime.py          # Runtime surface extraction
│   ├── integrations.py     # Third-party integration signals
│   ├── database.py         # Schema / data-layer extraction
│   └── artifacts.py        # Config artifact detection
│
├── generator/              # Phase 3 — MDX page generation
│   ├── generation.py       # Per-bucket generation, batching, retry
│   ├── evidence.py         # Evidence pack assembly per bucket
│   ├── validation.py       # Output validation (sections, routes, grounding)
│   └── post_processors.py  # MDX cleanup, brace escaping, frontmatter
│
├── parser/                 # Route parsing per framework
│   └── routes/             # Django, Flask, FastAPI, Express, NestJS, …
│
├── chatbot/                # Optional AI chatbot
│   ├── service.py          # Query modes: /query, /deep-research, /code-deep
│   ├── retrieval_mixin.py  # FAISS + SQLite FTS hybrid search
│   ├── answer_mixin.py     # LLM answer generation and prompt building
│   ├── routes.py           # FastAPI app factory and HTTP handlers
│   └── indexer.py          # Embedding index build and update
│
├── site/builder/           # Phase 5 — Fumadocs Next.js scaffold
│   ├── engine.py           # Site build orchestration
│   ├── scaffold_files.py   # Page tree, nav, search route, MDX pages
│   └── chatbot_components.py  # Chatbot-specific TSX/TS generators
│
├── llm/
│   └── client.py           # LiteLLM wrapper with usage tracking
│
└── prompts/                # All prompt strings
    └── selectors.py        # Prompt lookup entrypoint
```

## Five-phase pipeline

| Phase | What happens | LLM calls |
|---|---|---|
| **1 Scan** | Parse source files, detect routes, config, integrations, OpenAPI specs | None |
| **2 Plan** | Classify repo → propose buckets → assign files/symbols/artifacts | Yes |
| **3 Generate** | Build evidence packs per bucket, call LLM in parallel batches, validate output | Yes |
| **4 API Ref** | Stage OpenAPI assets for Fumadocs `/api/*` pages | None |
| **5 Build** | Write Fumadocs Next.js scaffold, page tree, nav, search route | None |

## Key configuration (`deepdoc.yaml`)

```yaml
llm:
  provider: openai          # openai | anthropic | azure | ollama | …
  model: gpt-4o
  api_key_env: OPENAI_API_KEY

output_dir: docs            # where generated MDX pages land
include_endpoint_pages: true

# Optional: explicit monorepo services
services:
  - name: api
    root: services/api
  - name: web
    root: services/web

# Optional: extend endpoint grouping keywords
endpoint_groups:
  payments: [stripe, refund, invoice]

quality:
  strict: false             # set true (or use --strict-quality) to fail CI on degraded pages
```

Full config reference: see `deepdoc config show` or the root `README.md`.

## Running tests

```bash
python3 -m pytest -q                             # full suite
python3 -m pytest tests/test_state.py -q         # single file
python3 -m pytest -k "stale or smart_update" -q  # by keyword
```

## Release track

Version lives in `pyproject.toml`. Changelog in the root `CHANGELOG.md`. Push a version bump to `main` to trigger the PyPI publish workflow (`.github/workflows/release.yml`).
