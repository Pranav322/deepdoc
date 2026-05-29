# DeepDoc

[![PyPI version](https://img.shields.io/pypi/v/deepdoc)](https://pypi.org/project/deepdoc/)
[![Python versions](https://img.shields.io/pypi/pyversions/deepdoc)](https://pypi.org/project/deepdoc/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

## Repository Layout

| Directory | What it is | Where to start |
|---|---|---|
| [`deepdoc/`](./deepdoc/) | The Python package — CLI, pipeline, planner, generator, chatbot, and site builder. This is the core product. | [`deepdoc/README.md`](./deepdoc/README.md) |
| [`web/`](./web/) | Marketing and changelog site built with Astro 5 + Tailwind. Deployed to the public DeepDoc website. | [`web/README.md`](./web/README.md) |
| [`vscode-extension/`](./vscode-extension/) | VS Code extension — explains selected code snippets in Fast or Deep mode and inserts AI-generated comments inline. | [`vscode-extension/README.md`](./vscode-extension/README.md) |
| [`tests/`](./tests/) | pytest test suite for the Python package. | Run `python3 -m pytest -q` from repo root. |
| [`scripts/`](./scripts/) | One-off release and maintenance scripts. | — |

---

Auto-generate deep engineering documentation from real codebases using AI.

DeepDoc scans your repo, builds a bucket-based documentation plan, generates rich Markdown pages with Mermaid diagrams, and builds a local-first MkDocs Material site with built-in search.

## Contents

- [Quick Start](#quick-start)
- [Chatbot in 5 Minutes](#chatbot-in-5-minutes)
- [Installation](#installation)
- [Commands](#commands)
- [LLM Provider Setup](#llm-provider-setup)
- [Configuration](#configuration)
- [Chatbot](#chatbot)
- [Supported Languages & Frameworks](#supported-languages--frameworks)
- [Architecture](#architecture)
- [Generated Files](#generated-files)
- [GitHub Actions CI/CD](#github-actions-cicd)
- [Requirements](#requirements)
- [Contributing & Release Flow](./CONTRIBUTING.md)

---

## Features

- **Bucket-based documentation architecture** — system, feature, endpoint, integration, and database buckets instead of one-file-per-page noise.
- **Multi-step AI planner** — classifies the repo, proposes buckets, then assigns files, symbols, artifacts, and dependencies into a final reader-first plan.
- **Giant-file handling** — large files are decomposed into feature-aligned clusters so a single controller can feed multiple doc pages.
- **Stable plain-Markdown generation** — generated pages are plain CommonMark (no MDX/JSX compile step, so a page can never fail to build); they are repaired and validated in Python before being written, and deploy-time quality gates block failed, invalid, or stub pages before the build.
- **Evidence-first chatbot answers** — final code proof is hydrated from archived source snippets with exact file paths and line ranges, not just retrieval guesses.
- **Incremental updates** — `deepdoc update` regenerates only stale or structurally affected docs against the last synced commit.
- **OpenAPI-aware API docs** — auto-detects OpenAPI/Swagger specs and renders an interactive Swagger UI page (`mkdocs-swagger-ui-tag`) in the generated site.
- **Local-first MkDocs Material site** — generates a `site/mkdocs.yml` (Material theme, Mermaid, built-in search); `deepdoc deploy` runs `mkdocs build` and exports a static site to any host. Pure Python — no Node.js required.

Works with Anthropic, OpenAI, Azure OpenAI, Google Gemini, Ollama, and any other LiteLLM-compatible provider. Parses Python, JavaScript/TypeScript, Go, PHP, and Vue.

---

## Installation

### From PyPI (recommended)

```bash
pip install deepdoc
```

If you want DeepDoc's chatbot features, install the `chatbot` extra:

```bash
pip install "deepdoc[chatbot]"
```

The base install does not include chatbot dependencies.

### From source (recommended during development)

```bash
git clone https://github.com/tss-pranavkumar/deepdoc.git
cd deepdoc
pip install -e .
```

If you want chatbot features during development:

```bash
pip install -e ".[chatbot]"
```

If the full install is slow due to tree-sitter compilation, install core deps first:

```bash
pip install click litellm gitpython rich pyyaml jinja2
pip install -e . --no-deps
```

To preview or deploy the generated site you also need **MkDocs Material** (pure Python — no Node.js):

```bash
pip install mkdocs-material
pip install mkdocs-swagger-ui-tag   # only when your repo has an OpenAPI/Swagger spec
```

`deepdoc serve` / `deepdoc deploy` will tell you the exact `pip install` command if MkDocs is missing.

### Verify installation

```bash
deepdoc --version
deepdoc --help
python -m deepdoc --help
node --version    # must report 18 or higher
```

If you installed the chatbot extra, you can verify those dependencies with:

```bash
pip show faiss-cpu fastapi uvicorn
```

---

## Quick Start

### Docs only

```bash
cd /path/to/your-project
deepdoc init --provider anthropic
export ANTHROPIC_API_KEY=sk-ant-...
deepdoc generate
deepdoc serve   # → http://localhost:3000
```

### Docs + chatbot — one env var

```bash
cd /path/to/your-project
pip install "deepdoc[chatbot]"
deepdoc init --with-chatbot --provider anthropic
export ANTHROPIC_API_KEY=sk-ant-...
deepdoc generate
deepdoc serve   # → http://localhost:3000  •  chatbot at /ask
```

The chatbot reuses your doc-gen LLM and runs embeddings locally via `fastembed`. **No extra keys, no extra config.** Swap `--provider anthropic` for `openai`, `gemini`, `azure`, or `ollama` to use a different LLM.

When `chatbot.enabled` is `false`, DeepDoc generates a docs-only site: no chatbot route, no chatbot UI components, and no `chatbot_backend/` scaffold.

---

## Chatbot in 5 Minutes

> **Defaults work out of the box.** The chatbot inherits your `llm.*` config and runs embeddings locally via `fastembed`. The recipes below only add config when you actually need to override the defaults (Azure endpoints, custom Ollama base URL, or mixing providers).

### Single provider — one key for everything

This is the path 95% of users want. Anthropic shown; swap `--provider` for `openai`, `gemini`, etc.

```bash
pip install "deepdoc[chatbot]"
cd /path/to/your-project

deepdoc init --with-chatbot --provider anthropic
export ANTHROPIC_API_KEY=sk-ant-...

deepdoc generate
deepdoc serve
# → Docs at http://localhost:3000  •  Chatbot at http://localhost:3000/ask
```

### Mix providers — different LLM for chat than for docs

Use Claude for docs (great long-form), GPT-4o-mini for chat answers (fast + cheap), local embeddings.

```bash
pip install "deepdoc[chatbot]"
cd /path/to/your-project

deepdoc init --with-chatbot --provider anthropic
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...

deepdoc config set chatbot.answer.provider openai
deepdoc config set chatbot.answer.model gpt-4o-mini
deepdoc config set chatbot.answer.api_key_env OPENAI_API_KEY

deepdoc generate
deepdoc serve
```

Want cloud embeddings instead of local? Add:

```bash
deepdoc config set chatbot.embeddings.backend litellm
deepdoc config set chatbot.embeddings.provider openai
deepdoc config set chatbot.embeddings.model text-embedding-3-large
deepdoc config set chatbot.embeddings.api_key_env OPENAI_API_KEY
```

### Azure OpenAI

Azure deployments need explicit endpoint + API-version values. Replace `YOUR-RESOURCE` and deployment names with your actual values.

```bash
pip install "deepdoc[chatbot]"
cd /path/to/your-project

export AZURE_API_KEY=...
export AZURE_API_BASE=https://YOUR-RESOURCE.openai.azure.com

deepdoc init --with-chatbot --provider azure --model azure/gpt-4o
deepdoc config set llm.base_url $AZURE_API_BASE

# Only embeddings need separate Azure config (different deployment)
deepdoc config set chatbot.embeddings.backend litellm
deepdoc config set chatbot.embeddings.provider azure
deepdoc config set chatbot.embeddings.model azure/text-embedding-3-large
deepdoc config set chatbot.embeddings.api_key_env AZURE_API_KEY
deepdoc config set chatbot.embeddings.base_url $AZURE_API_BASE
deepdoc config set chatbot.embeddings.api_version 2024-02-01

deepdoc generate
deepdoc serve
```

The answer LLM inherits `llm.*` (Azure deployment + base URL + key) automatically.

### Ollama — Fully local, no API keys

Free and private. Runs everything on your machine.

```bash
pip install "deepdoc[chatbot]"
cd /path/to/your-project

# Start Ollama first: https://ollama.com
ollama pull llama3.2

deepdoc init --with-chatbot --provider ollama --model ollama/llama3.2
deepdoc config set llm.base_url http://localhost:11434

deepdoc generate
deepdoc serve
# → Docs at http://localhost:3000  •  Chatbot at http://localhost:3000/ask
```

> Fastembed downloads the local embedding model (~300 MB) on first run. No API key needed for any step.

---

## Commands

Every command supports `--help`, including nested config commands:

```bash
deepdoc --help
deepdoc generate --help
deepdoc config --help
deepdoc config set --help
```

### `deepdoc init`

Initializes DeepDoc in the current directory by creating a `.deepdoc.yaml` config file.

```bash
deepdoc init
deepdoc init --provider openai --model gpt-4o
deepdoc init --provider ollama --model ollama/llama3.2
deepdoc init --provider azure --model azure/gpt-4o
deepdoc init --output-dir documentation
deepdoc init --with-chatbot
deepdoc init --provider openai --with-chatbot
```

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--name` | directory name | Project name |
| `--description` | empty | Short project description |
| `--provider` | `anthropic` | LLM provider: `anthropic`, `openai`, `ollama`, `azure` |
| `--model` | provider default | Model name |
| `--output-dir` | `docs` | Where generated docs are written |
| `--with-chatbot` | off | Enable chatbot scaffolding and indexing (see [Chatbot](#chatbot) section) |

### `deepdoc generate`

Full documentation generation. This is the first-run or explicit full-refresh command.

```bash
deepdoc generate
deepdoc generate --force           # Full refresh of DeepDoc-managed docs
deepdoc generate --clean --yes     # Wipe output + state and rebuild from scratch
deepdoc generate --deploy          # Generate + export the static site
deepdoc generate --batch-size 3    # Smaller batches for rate-limited APIs
deepdoc generate --include "src/**" --include "lib/**"
deepdoc generate --exclude "tests/**"
```

**Current behavior:**

- `deepdoc generate`
  - intended for the first run
  - refuses to run if DeepDoc docs/state already exist
  - refuses to write into a non-DeepDoc `docs/` folder unless you explicitly clean it
- `deepdoc generate --force`
  - re-runs the full pipeline
  - regenerates all DeepDoc-managed pages even if they are not stale
  - removes stale generated pages that no longer belong in the new plan
  - preserves non-DeepDoc files
- `deepdoc generate --clean --yes`
  - deletes the output dir and DeepDoc state
  - rebuilds everything from scratch

**What happens under the hood (5-phase pipeline):**

1. **Phase 1: Scan** — Walk the repo, parse supported languages, detect endpoints, config/setup artifacts, runtime surfaces, integration signals, and OpenAPI specs.
2. **Phase 2: Plan** — Run the multi-step bucket planner. It classifies the repo, proposes bucket candidates, and assigns files/symbols/artifacts to the final doc structure.
3. **Phase 3: Generate** — Generate bucket pages in batches with parallel workers. High-level buckets are AI-planned; scanned endpoints enrich grouped API-reference pages instead of creating one page per route. Each page passes through Python-side Markdown repair, grounding validation, and bounded quality retries before being written to disk.
4. **Phase 4: API Ref** — Stage OpenAPI specs and render them on a single interactive Swagger UI page (`mkdocs-swagger-ui-tag`) when a spec exists.
5. **Phase 5: Build** — Write the generated `site/mkdocs.yml` scaffold (Material theme), nav, and brand stylesheet from the generated plan.

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--force` | off | Full refresh of DeepDoc-managed docs and cleanup of stale generated pages |
| `--clean` | off | Delete output dir and DeepDoc state, then regenerate from scratch |
| `--yes` | off | Skip destructive confirmation for `--clean` |
| `--include` | all files | Glob patterns to include (can be repeated) |
| `--exclude` | see config | Additional glob patterns to exclude |
| `--deploy` | off | Build and export the static site after generation |
| `--batch-size` | 10 | Pages per batch before pausing (helps with rate limits) |

### `deepdoc update`

Incrementally update docs when source files change. This is the normal command after the first successful `generate`.

```bash
deepdoc update                    # Normal ongoing refresh
deepdoc update --since HEAD~3     # Changes in last 3 commits
deepdoc update --since main       # All changes since branching from main
deepdoc update --replan           # Force a full replan
deepdoc update --strict-quality   # Fail if generated docs are invalid/degraded
deepdoc update --deploy           # Update + deploy
```

**How it works:**

1. Loads the saved sync baseline, plan, and generation ledger from `.deepdoc/`.
2. Diffs committed changes from the last synced commit to the current `HEAD`.
3. Chooses a strategy automatically:
   - **incremental** — regenerate only the stale bucket pages
   - **targeted replan** — new/deleted files or endpoint structure changes; re-plans affected buckets then regenerates them. Full replan is never triggered automatically for normal code changes.
4. Compares the saved scan cache with the current scan so semantic endpoint changes can refresh impacted docs even when ownership files do not line up directly.
5. Regenerates only the affected bucket pages. Deleted files are cleaned up in-place: orphaned buckets and their Markdown pages are removed, partially-emptied buckets are marked stale and regenerated.
6. Appends an entry to `.deepdoc/changelog.json` and regenerates `docs/whats-changed.md` so the docs site always shows a current commit-by-commit change log.
7. Incrementally refreshes the chatbot corpora from the same update run.
8. Rebuilds site config and nav afterward.

If git is unavailable, it falls back to hash-based staleness detection for recovery.
When `--deploy` is used, DeepDoc deploys only after a fully successful update; failed page generation or chatbot sync blocks deployment.

Generation writes quality artifacts under `.deepdoc/`:

- `.deepdoc/generation_quality.json` records invalid/degraded pages, coverage metrics, local setup warnings, and consistency summary data.
- `.deepdoc/consistency_warnings.json` records warning-only cross-page identifier consistency findings.

Generated Markdown pages include provenance frontmatter such as `deepdoc_generated_commit`, `deepdoc_generated_at`, `deepdoc_generated_version`, `deepdoc_status`, `deepdoc_evidence_files`, and `deepdoc_prereqs` (prerequisite page slugs). The MkDocs Material theme renders these pages with built-in navigation, search, and table of contents.

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--since` | last synced commit | Git ref to diff against |
| `--replan` | off | Force a full replan even if the change set looks incremental |
| `--deploy` | off | Deploy after a fully successful update |

### `deepdoc status`

Show how much documentation has been generated and whether any buckets are stale.

```bash
deepdoc status
```

This is useful after `generate` or `update` when you want a quick health check without opening the site.

### `deepdoc serve`

Preview the generated docs locally with live reload using the generated MkDocs Material site in `site/`.

```bash
deepdoc serve
deepdoc serve --port 8001
```

Runs `mkdocs serve` against `site/mkdocs.yml`. Requires `pip install mkdocs-material` (pure Python — no Node.js).

### `deepdoc deploy`

Build and export the generated MkDocs Material site.

```bash
deepdoc deploy
```

This runs `mkdocs build` against `site/mkdocs.yml` and writes the static HTML to `site/out/`. You can deploy that directory to Vercel, Netlify, GitHub Pages, Cloudflare Pages, or any static host.

Before building, `deepdoc deploy` checks `.deepdoc/generation_quality.json` and generated page frontmatter. It refuses to deploy when the last generation has failed/invalid pages or when `docs/` still contains pages marked `deepdoc_status: "invalid"` or `stub: true`; rerun `deepdoc generate` after fixing those issues.

If you want GitHub Pages specifically, this repo includes a workflow at `.github/workflows/github-pages.yml` that publishes the checked-in `site/out/` export through the official Pages Actions flow. That means you do not need to move the export into a branch `docs/` folder.

### `deepdoc config`

View or update config values without editing YAML manually.

```bash
deepdoc config show                                    # Print all config
deepdoc config set llm.provider openai                 # Switch provider
deepdoc config set llm.model gpt-4o                    # Switch model
deepdoc config set llm.temperature 0.3                 # Adjust creativity
deepdoc config set output_dir documentation            # Change output dir
deepdoc config set llm.api_key_env AZURE_API_KEY       # Change API key env var
deepdoc config set compatibility.deprecated_version_warning.enabled false
```

### `deepdoc benchmark`

Run planner benchmark cases and optionally generate a combined docs+chatbot quality scorecard.

```bash
deepdoc benchmark --catalog benchmarks/catalog.json
deepdoc benchmark --repo /path/to/repo --gold benchmarks/gold.json
deepdoc benchmark --catalog benchmarks/catalog.json --chatbot-eval benchmarks/chatbot_eval.json
deepdoc benchmark --catalog benchmarks/catalog.json --chatbot-eval benchmarks/chatbot_eval.json --scorecard-out .deepdoc/quality_scorecard.json --strict-scorecard
deepdoc benchmark --generated-root /Users/apple/autodoc/docs --scorecard-out /Users/apple/autodoc/docs/_scorecards/latest.json
```

Use `--strict-scorecard` to fail the command when completeness gates are not met.

When you do not have a hand-written benchmark catalog or chatbot eval file yet, use artifact mode (`--generated-root` or `--artifact-repo`) to compute a provisional scorecard directly from persisted `.deepdoc/` outputs.

---

## LLM Provider Setup

DeepDoc uses [LiteLLM](https://github.com/BerriAI/litellm) under the hood, which means it supports 100+ providers.

For new users, start with one of these common doc-generation setups:

### Anthropic (Claude) — Default

```bash
deepdoc init --provider anthropic
export ANTHROPIC_API_KEY=sk-ant-api03-...
deepdoc generate
```

Models: `claude-3-5-sonnet-20241022`, `claude-3-opus-20240229`, `claude-3-haiku-20240307`

### OpenAI (GPT)

```bash
deepdoc init --provider openai --model gpt-4o
export OPENAI_API_KEY=sk-...
deepdoc generate
```

Models: `gpt-4.1`, `gpt-4.1-mini`, `gpt-4o`, `gpt-4o-mini`, `gpt-4-turbo`

### Google Gemini

If you use a simple Google AI Studio API key, use the `gemini/` prefix. Without that prefix, LiteLLM defaults to Vertex AI semantics.

```bash
deepdoc init
deepdoc config set llm.provider gemini
deepdoc config set llm.model gemini/gemini-2.0-flash
deepdoc config set llm.api_key_env GEMINI_API_KEY
export GEMINI_API_KEY=...
deepdoc generate
```

Common choices: `gemini/gemini-2.0-flash`, `gemini/gemini-2.5-flash`, `gemini/gemini-2.5-pro`

### Azure OpenAI

Azure requires a few more environment variables because deployments have custom names and endpoints.

```bash
# 1. Initialize with Azure
deepdoc init --provider azure --model azure/<your-deployment-name>

# 2. Set required environment variables
export AZURE_API_KEY=your-azure-api-key
export AZURE_API_BASE=https://<your-resource-name>.openai.azure.com
export AZURE_API_VERSION=2024-02-01

# 3. Update config to point to your deployment
deepdoc config set llm.model azure/<your-deployment-name>
deepdoc config set llm.base_url https://<your-resource-name>.openai.azure.com

# 4. Generate
deepdoc generate
```

**Where to find these values in Azure Portal:**

1. Go to [Azure Portal](https://portal.azure.com) → Azure OpenAI resource.
2. Click **Keys and Endpoint** in the sidebar → copy **Key 1** (that's your `AZURE_API_KEY`) and the **Endpoint** (that's your `AZURE_API_BASE`).
3. Go to **Model deployments** → **Manage Deployments** → note your deployment name (e.g., `gpt-4o-deployment`). Use this as `azure/gpt-4o-deployment` in the model field.
4. API version: Use `2024-02-01` or the latest GA version shown in Azure docs.

**Example `.deepdoc.yaml` for Azure:**

```yaml
project_name: my-project
output_dir: docs
llm:
  provider: azure
  model: azure/gpt-4o-deploy      # "azure/" prefix + your deployment name
  api_key_env: AZURE_API_KEY
  base_url: https://mycompany.openai.azure.com
  max_tokens: 4096
  temperature: 0.2
```

**Azure AD / Managed Identity (token-based auth):**

If you use Azure AD instead of API keys, set these instead:

```bash
export AZURE_AD_TOKEN=your-ad-token
export AZURE_API_BASE=https://<your-resource-name>.openai.azure.com
export AZURE_API_VERSION=2024-02-01
```

LiteLLM picks up `AZURE_AD_TOKEN` automatically when `AZURE_API_KEY` is not set.

### Ollama (Local / Free)

No API key needed. Just make sure Ollama is running locally.

```bash
# 1. Install and start Ollama (https://ollama.com)
ollama pull llama3.2

# 2. Initialize
deepdoc init --provider ollama --model ollama/llama3.2

# 3. Generate (no API key needed)
deepdoc generate
```

Other Ollama models: `ollama/codellama`, `ollama/mistral`, `ollama/mixtral`

### Any LiteLLM Provider

DeepDoc passes the model string directly to LiteLLM, so you can use any provider LiteLLM supports by using the correct prefix. `deepdoc init` only has shortcuts for the common providers above, so for everything else initialize once and then use `deepdoc config set ...`:

```bash
# Gemini
deepdoc config set llm.provider gemini
deepdoc config set llm.model gemini/gemini-2.0-flash
export GEMINI_API_KEY=...

# Groq
deepdoc config set llm.model groq/llama3-70b-8192
export GROQ_API_KEY=...

# Together AI
deepdoc config set llm.model together_ai/meta-llama/Llama-3-70b-chat-hf
export TOGETHER_API_KEY=...

# AWS Bedrock
deepdoc config set llm.model bedrock/anthropic.claude-3-sonnet-20240229-v1:0
# (uses AWS credentials from environment)
```

See [LiteLLM providers](https://docs.litellm.ai/docs/providers) for the full list.

---

## Configuration

The `.deepdoc.yaml` file in your repo root controls everything:

```yaml
project_name: my-app
description: "A web application for managing tasks"
output_dir: docs
site_dir: site

llm:
  provider: anthropic
  model: claude-3-5-sonnet-20241022
  api_key_env: ANTHROPIC_API_KEY
  base_url: null                    # Set for Ollama/custom endpoints
  max_tokens: null                  # null = no cap (recommended); set a number to limit output
  temperature: 0.2

languages:
  - python
  - javascript
  - typescript
  - go
  - php

include: []                         # Empty = include everything
exclude:
  - node_modules
  - .git
  - __pycache__
  - "*.pyc"
  - vendor
  - dist
  - build
  - .env
  - "*.lock"
  - "*.sum"

generation_mode: feature_buckets

# Generation tuning
max_pages: 0                        # 0 = no cap; set a number to limit total pages
giant_file_lines: 2000              # Files above this get LLM-based feature clustering
source_context_budget: 200000       # Raw-source char budget before DeepDoc switches overflow files to compressed evidence cards
integration_detection: auto         # "auto" | "off"

# Page type toggles
include_endpoint_pages: true        # Generate endpoint documentation
include_integration_pages: true     # Generate integration documentation

# Parallelism — tune for your LLM provider's rate limits
max_parallel_workers: 6             # Concurrent LLM calls (increase for Azure PTU)
batch_size: 10                      # Pages per batch before rate-limit pause

github_pages:
  enabled: false
  branch: gh-pages
  remote: origin

site:
  repo_url: ""                      # e.g., https://github.com/you/your-repo
  favicon: ""
  logo: ""
```

### Configuration Reference

| Key | Default | Description |
|-----|---------|-------------|
| `project_name` | directory name | Project name used in site title |
| `description` | `""` | Short project description |
| `output_dir` | `docs` | Where generated markdown pages are written |
| `site_dir` | `site` | Where the generated MkDocs site config (`mkdocs.yml`) lives |
| **LLM** | | |
| `llm.provider` | `anthropic` | `anthropic`, `openai`, `azure`, `ollama`, or any LiteLLM alias |
| `llm.model` | `claude-3-5-sonnet-20241022` | Model name (use provider prefix for non-Anthropic, e.g. `azure/gpt-4.1`) |
| `llm.api_key_env` | `ANTHROPIC_API_KEY` | Environment variable that holds the API key |
| `llm.base_url` | `null` | Custom endpoint URL (required for Ollama, optional for Azure) |
| `llm.max_tokens` | `null` | Max output tokens per LLM call. `null` = no cap (recommended). Set explicitly if your provider requires it (e.g. some Azure deployments). Typical values: `4096` for shorter pages, `8192`–`16384` for detailed docs |
| `llm.temperature` | `0.2` | LLM sampling temperature |
| **Generation** | | |
| `generation_mode` | `feature_buckets` | Documentation generation mode |
| `max_pages` | `0` | Max pages to generate. `0` = no cap |
| `giant_file_lines` | `2000` | Files above this line count get LLM-based feature clustering |
| `source_context_budget` | `200000` | Raw-source char budget per page before overflow files are represented as compressed evidence cards |
| `integration_detection` | `auto` | Detect third-party integrations: `auto` or `off` |
| `include_endpoint_pages` | `true` | Generate endpoint documentation pages |
| `include_integration_pages` | `true` | Generate integration documentation pages |
| **Parallelism** | | |
| `max_parallel_workers` | `6` | Concurrent LLM calls. Increase for Azure PTU or high-TPM deployments |
| `batch_size` | `10` | Pages per batch before rate-limit pause |
| **File filters** | | |
| `languages` | `[python, javascript, typescript, go, php, vue]` | Languages to parse |
| `include` | `[]` | Glob patterns to include (empty = everything) |
| `exclude` | *(see config)* | Glob patterns to exclude (node_modules, .git, dist, etc.) |
| **GitHub Pages** | | |
| `github_pages.branch` | `gh-pages` | Branch for GitHub Pages deploy |
| `github_pages.remote` | `origin` | Git remote for deploy |
| **Site** | | |
| `site.repo_url` | `""` | Repo URL shown in the generated MkDocs Material navigation |
| `site.favicon` | `""` | Path to favicon |
| `site.logo` | `""` | Path to logo |
| **Compatibility** | | |
| `compatibility.deprecated_version_warning.enabled` | `true` | Warn when existing generated docs were produced by a different major version of DeepDoc (e.g. docs from v1.x with CLI v2.x). Suppressed for minor/patch version gaps. |

---

## Chatbot

DeepDoc can generate an AI-powered chatbot that answers questions about your codebase using evidence-first RAG. Retrieval indexes find candidate files, but final code proof always comes from archived source/config snippets with exact file paths and line ranges. Generated docs and repo-authored docs can help explain concepts, but they are returned as references, not right-pane code evidence.

> **Defaults you should know.** The chatbot **inherits** `provider`, `model`, and `api_key_env` from your `llm.*` config when `chatbot.answer.*` is empty (the scaffolded default). Embeddings default to `fastembed` — fully local, no API key. You only need extra config if (a) you want a different LLM for chat than for docs, or (b) you want cloud embeddings.

If chatbot is disabled, DeepDoc keeps the generated site docs-only: it does not generate the `/ask` route, chatbot frontend components, or `chatbot_backend/` scaffold.

> **Already running?** If you followed the [Chatbot in 5 Minutes](#chatbot-in-5-minutes) guide above, your chatbot is already configured and working. Everything below is for advanced configuration, tuning, and production deployment.

### How the Model Surfaces Work

The chatbot has three independent model surfaces that you can mix across providers:

| Surface | Controls | Example |
|---------|----------|----------|
| `llm.*` | Doc planning and page generation | Claude, GPT-4o, Gemini |
| `chatbot.answer.*` | Chatbot answer generation | GPT-4o-mini, Claude, Gemini Flash |
| `chatbot.embeddings.*` | Vector embeddings for retrieval | text-embedding-3-large, Gemini text-embedding-004 |

`deepdoc serve` auto-starts the chatbot backend alongside the MkDocs site. The backend port is deterministically assigned from your repo path (range 8100–8799) unless you set an explicit `base_url`.

### Evidence-First Responses

All chatbot endpoints now share one response contract:

- `evidence[]` is the canonical source of right-pane code/config snippets. Each item has an ID like `E1`, `file_path`, `start_line`, `end_line`, and `snippet`.
- `references[]` contains generated docs or repo-authored docs. These are read-next links, not implementation proof.
- Legacy fields such as `code_citations`, `doc_links`, `code_workspace_citations`, and `file_inventory` are derived for compatibility.
- SQLite FTS, FAISS vectors, symbol chunks, and relationship chunks are candidate retrieval artifacts only. A candidate becomes evidence only after it is hydrated from the source archive/catalog.
- Generated/internal paths such as `.deepdoc*`, `docs/`, `site/`, and `chatbot_backend/` are excluded from source evidence.
- The answer validator rejects invented source paths, `line unknown`, unknown evidence IDs, and docs used as implementation proof. If a retry still fails, the backend returns a conservative answer with diagnostics.

Public endpoints remain stable:

| Endpoint | Mode | Behavior |
|----------|------|----------|
| `POST /query` | Fast | Single-pass, index-first answer. Uses source/config evidence and optional doc references. |
| `POST /deep-research` | Deep | Multi-step synthesis. May use docs for orientation, but implementation claims must be grounded in source/config evidence. |
| `POST /code-deep` | Code Deep | Strict source-first answer with trace and file inventory compatibility fields. Missing exact evidence is reported as a gap. |
| `POST /query-context` | Diagnostics | Returns selected candidates, hydrated `evidence[]`, `references[]`, and diagnostics without generating an answer. |
| `POST /code-deep/stream` | Code Deep stream | Emits SSE trace events followed by the final evidence-first payload. |

### Provider Recipes

These are advanced recipes that override the inheritance defaults — e.g. mixing providers or using cloud embeddings. For the simple "one key for everything" path, see [Chatbot in 5 Minutes](#chatbot-in-5-minutes) above.

#### Claude for docs, OpenAI for embeddings

Claude doesn't offer embedding models, so cloud embeddings need a separate provider. (Or just keep the default `fastembed` and skip this entirely.)

```bash
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...

deepdoc config set llm.provider anthropic
deepdoc config set llm.model claude-3-5-sonnet-20241022
deepdoc config set llm.api_key_env ANTHROPIC_API_KEY

deepdoc config set chatbot.enabled true
deepdoc config set chatbot.embeddings.backend litellm
deepdoc config set chatbot.embeddings.provider openai
deepdoc config set chatbot.embeddings.model text-embedding-3-large
deepdoc config set chatbot.embeddings.api_key_env OPENAI_API_KEY
```

The chatbot answer LLM inherits `llm.*` (Claude) automatically.

#### Different model for chat than for docs

Claude for docs, GPT-4o-mini for cheaper/faster chat answers. Embeddings stay local.

```bash
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...

deepdoc config set llm.provider anthropic
deepdoc config set llm.model claude-3-5-sonnet-20241022
deepdoc config set llm.api_key_env ANTHROPIC_API_KEY

deepdoc config set chatbot.enabled true
deepdoc config set chatbot.answer.provider openai
deepdoc config set chatbot.answer.model gpt-4o-mini
deepdoc config set chatbot.answer.api_key_env OPENAI_API_KEY
```

#### Azure with separate embedding deployment

Azure deployments need explicit `base_url` + `api_version`, and embeddings typically live on a different deployment.

```bash
export AZURE_API_KEY=...

deepdoc config set llm.provider azure
deepdoc config set llm.model azure/gpt-4.1
deepdoc config set llm.api_key_env AZURE_API_KEY
deepdoc config set llm.base_url https://YOUR-RESOURCE.openai.azure.com/

deepdoc config set chatbot.enabled true
deepdoc config set chatbot.embeddings.backend litellm
deepdoc config set chatbot.embeddings.provider azure
deepdoc config set chatbot.embeddings.model azure/text-embedding-3-small
deepdoc config set chatbot.embeddings.api_key_env AZURE_API_KEY
deepdoc config set chatbot.embeddings.base_url https://YOUR-RESOURCE.openai.azure.com/
deepdoc config set chatbot.embeddings.api_version 2024-02-15-preview
```

The answer LLM inherits `llm.*` (Azure deployment, base URL, version, key) automatically — no `chatbot.answer.*` config needed for Azure.

### Installation

The chatbot requires extra dependencies not included in the base install:

```bash
# From PyPI
pip install "deepdoc[chatbot]"

# From source (development)
pip install -e ".[chatbot]"
```

Extra dependencies: `numpy`, `faiss-cpu`, `fastapi`, `uvicorn`, `httpx`.

Verify the chatbot extras are installed:

```bash
pip show faiss-cpu fastapi uvicorn
```

### Chatbot Configuration

All chatbot settings live under the `chatbot` key in `.deepdoc.yaml`. Running `deepdoc init --with-chatbot` populates these defaults:

These are scaffolding defaults, not a recommendation that you must use Azure. Most teams change the provider, model, and API-key env vars right after `init`.

```yaml
chatbot:
  enabled: true
  index_dir: ".deepdoc/chatbot"

  backend:
    base_url: ""                              # Leave empty for auto-assigned local port
    allowed_origins:
      - "http://localhost:3000"
      - "http://127.0.0.1:3000"

  answer:                                     # LLM used for answering user questions
    provider: "azure"
    model: "azure/gpt-4o-mini"
    api_key_env: "DEEPDOC_CHAT_API_KEY"
    base_url: ""
    api_version: ""
    temperature: 0.1
    max_tokens: 24000
    continuation_retries: 2                   # Auto-continue if answer ends abruptly
    continuation_context_chars: 12000         # Tail chars included in continuation prompt

  embeddings:                                 # LLM used for embedding code/docs
    backend: "litellm"                       # "litellm" for cloud embeddings or "fastembed" for fully local embeddings
    fastembed_model: "nomic-ai/nomic-embed-text-v1.5"
    fastembed_batch_size: 4
    provider: "azure"
    model: "azure/text-embedding-3-large"
    api_key_env: "DEEPDOC_EMBED_API_KEY"
    base_url: ""
    api_version: ""
    batch_size: 24

  vector_store:
    kind: "faiss"

  indexing:
    include_repo_docs: true
    include_tests: false
    repo_doc_globs: []
    exclude_globs: []
    max_file_bytes: 250000
    max_repo_doc_chars: 12000

  retrieval:
    top_k_code: 15
    top_k_artifact: 8
    top_k_docs: 6
    top_k_relationship: 8
    candidate_top_k_code: 30
    candidate_top_k_artifact: 16
    candidate_top_k_docs: 12
    candidate_top_k_relationship: 12
    max_prompt_code_chunks: 12
    max_prompt_artifact_chunks: 6
    max_prompt_doc_chunks: 6
    max_prompt_relationship_chunks: 6
    max_prompt_chars: 120000
    fast_mode_use_llm_retrieval_steps: false  # Fast mode skips expansion/rerank by default
    fast_mode_iterative_retrieval: false      # Fast mode skips second-pass follow-up retrieval
    fast_mode_max_prompt_chars: 90000         # Smaller prompt budget for faster /query answers
    deep_mode_max_prompt_chars: 140000        # Larger budget for /deep-research synthesis
    code_deep_mode_max_prompt_chars: 180000   # Largest prompt budget for /code-deep
    code_deep_top_k: 16                       # Code chunks retrieved for code-aware mode
    code_deep_top_k_relationship: 12          # Relationship chunks retrieved for code-aware mode
    code_deep_top_k_docs: 4                   # Cap docs chunks in code-aware mode
    code_deep_file_inventory_limit: 18        # Max files listed in code-aware inventory
    lexical_retrieval: true
    lexical_candidate_limit: 24
    query_expansion: true
    expansion_max_queries: 3
    iterative_retrieval: true
    iterative_max_followup_queries: 2
    graph_neighbor_expansion: true
    graph_neighbor_max_files: 6
    graph_neighbor_code_chunks_per_file: 2
    graph_neighbor_artifact_chunks_per_file: 1
    graph_neighbor_relationship_chunks_per_file: 2
    graph_neighbor_max_docs: 4
    rerank: true
    rerank_candidate_limit: 32
    rerank_candidate_limit_per_kind: 8
    rerank_preview_chars: 450
    stitch_adjacent_code_chunks: true
    stitch_max_adjacent_chunks: 2
    deep_research_live_fallback: true
    live_fallback_max_files: 6
    live_fallback_max_per_file: 2
    live_fallback_context_lines: 12
    deep_research_chunk_chars: 3200
    deep_research_top_k: 10

  chunking:
    code_chunk_lines: 120
    code_chunk_overlap: 20
    artifact_chunk_lines: 140
    artifact_chunk_overlap: 20
    max_doc_summary_chunks_per_page: 4
    max_doc_summary_chars: 4000
```

### Chatbot Configuration Reference

The defaults work for almost every project. Expand below only when you need to tune a specific knob.

<details>
<summary><strong>Full chatbot configuration reference (60+ keys)</strong></summary>

| Key | Default | Description |
|-----|---------|-------------|
| **General** | | |
| `chatbot.enabled` | `false` | Enable chatbot indexing and backend (set automatically by `deepdoc init --with-chatbot`) |
| `chatbot.index_dir` | `.deepdoc/chatbot` | Directory for source archive/catalog, SQLite lexical index, vector indexes, relationship artifacts, and chunk data |
| **Indexing** | | |
| `chatbot.indexing.include_repo_docs` | `true` | Index selected repo-authored docs such as README/design notes in a separate corpus |
| `chatbot.indexing.include_tests` | `false` | Allow test/example/fixture docs into the repo-doc corpus |
| `chatbot.indexing.repo_doc_globs` | `[]` | Extra glob patterns for repo docs to index |
| `chatbot.indexing.exclude_globs` | `[]` | Additional glob patterns to exclude from repo-doc indexing |
| `chatbot.indexing.max_file_bytes` | `250000` | Skip oversized repo-doc files during indexing |
| `chatbot.indexing.max_repo_doc_chars` | `12000` | Max chars per repo-doc section chunk |
| **Backend** | | |
| `chatbot.backend.base_url` | `""` | External backend URL. Leave empty for auto-assigned local port |
| `chatbot.backend.allowed_origins` | `[localhost:3000, 127.0.0.1:3000]` | CORS origins the backend accepts |
| **Answer LLM** | | |
| `chatbot.answer.provider` | `azure` | Provider for the answer model |
| `chatbot.answer.model` | `azure/gpt-4o-mini` | Model used to generate answers |
| `chatbot.answer.api_key_env` | `DEEPDOC_CHAT_API_KEY` | Env var holding the answer model API key |
| `chatbot.answer.base_url` | `""` | Custom endpoint (for Azure, Ollama, etc.) |
| `chatbot.answer.api_version` | `""` | Azure API version string |
| `chatbot.answer.temperature` | `0.1` | Sampling temperature (lower = more deterministic) |
| `chatbot.answer.max_tokens` | `24000` | Max tokens per answer |
| `chatbot.answer.continuation_retries` | `2` | Extra completion attempts when an answer appears truncated |
| `chatbot.answer.continuation_context_chars` | `12000` | Number of trailing chars passed when asking the model to continue |
| **Embeddings LLM** | | |
| `chatbot.embeddings.backend` | `litellm` | Embedding backend: `litellm` for cloud providers or `fastembed` for fully local embeddings |
| `chatbot.embeddings.fastembed_model` | `nomic-ai/nomic-embed-text-v1.5` | Local embedding model used when `chatbot.embeddings.backend=fastembed` |
| `chatbot.embeddings.fastembed_batch_size` | `4` | Local fastembed batch size |
| `chatbot.embeddings.provider` | `azure` | Provider for the embedding model |
| `chatbot.embeddings.model` | `azure/text-embedding-3-large` | Embedding model |
| `chatbot.embeddings.api_key_env` | `DEEPDOC_EMBED_API_KEY` | Env var holding the embedding API key |
| `chatbot.embeddings.base_url` | `""` | Custom endpoint |
| `chatbot.embeddings.api_version` | `""` | Azure API version string |
| `chatbot.embeddings.batch_size` | `24` | Texts per embedding API call |
| **Retrieval** | | |
| `chatbot.retrieval.top_k_code` | `15` | Top code chunks retrieved per query |
| `chatbot.retrieval.top_k_artifact` | `8` | Top artifact chunks retrieved per query |
| `chatbot.retrieval.top_k_docs` | `6` | Top generated-doc and repo-doc chunks retrieved per query |
| `chatbot.retrieval.top_k_relationship` | `8` | Top relationship chunks retrieved per query |
| `chatbot.retrieval.candidate_top_k_code` | `30` | Candidate code chunks gathered before reranking |
| `chatbot.retrieval.candidate_top_k_artifact` | `16` | Candidate artifact chunks gathered before reranking |
| `chatbot.retrieval.candidate_top_k_docs` | `12` | Candidate doc chunks gathered before reranking |
| `chatbot.retrieval.candidate_top_k_relationship` | `12` | Candidate relationship chunks gathered before reranking |
| `chatbot.retrieval.max_prompt_code_chunks` | `12` | Max code chunks included in the final prompt |
| `chatbot.retrieval.max_prompt_artifact_chunks` | `6` | Max artifact chunks in the final prompt |
| `chatbot.retrieval.max_prompt_doc_chunks` | `6` | Max doc chunks in the final prompt |
| `chatbot.retrieval.max_prompt_relationship_chunks` | `6` | Max relationship chunks included in the final prompt |
| `chatbot.retrieval.max_prompt_chars` | `120000` | Default character budget for assembled prompts |
| `chatbot.retrieval.fast_mode_use_llm_retrieval_steps` | `false` | In `/query` fast mode, disable LLM query expansion and reranking |
| `chatbot.retrieval.fast_mode_iterative_retrieval` | `false` | In `/query` fast mode, disable iterative follow-up retrieval |
| `chatbot.retrieval.fast_mode_max_prompt_chars` | `90000` | Prompt budget used by `/query` fast mode |
| `chatbot.retrieval.deep_mode_max_prompt_chars` | `140000` | Prompt budget used by `/deep-research` |
| `chatbot.retrieval.code_deep_mode_max_prompt_chars` | `180000` | Prompt budget used by `/code-deep` |
| `chatbot.retrieval.code_deep_top_k` | `16` | Code chunks retrieved in code-aware mode |
| `chatbot.retrieval.code_deep_top_k_relationship` | `12` | Relationship chunks retrieved in code-aware mode |
| `chatbot.retrieval.code_deep_top_k_docs` | `4` | Docs chunk cap in code-aware mode |
| `chatbot.retrieval.code_deep_file_inventory_limit` | `18` | Max files listed in code-aware inventory |
| `chatbot.retrieval.lexical_retrieval` | `true` | Blend exact-match retrieval with embedding retrieval |
| `chatbot.retrieval.lexical_candidate_limit` | `24` | Max lexical candidates gathered before merge/rerank |
| `chatbot.retrieval.query_expansion` | `true` | Use LLM to generate alternative search queries |
| `chatbot.retrieval.expansion_max_queries` | `3` | Number of alternative queries to generate |
| `chatbot.retrieval.iterative_retrieval` | `true` | Derive focused follow-up searches from early hits |
| `chatbot.retrieval.iterative_max_followup_queries` | `2` | Max follow-up queries used during iterative retrieval |
| `chatbot.retrieval.graph_neighbor_expansion` | `true` | Pull linked files and doc neighbors into the candidate set |
| `chatbot.retrieval.graph_neighbor_max_files` | `6` | Max linked files considered for graph-neighbor expansion |
| `chatbot.retrieval.graph_neighbor_code_chunks_per_file` | `2` | Code chunks per linked file during graph expansion |
| `chatbot.retrieval.graph_neighbor_artifact_chunks_per_file` | `1` | Artifact chunks per linked file during graph expansion |
| `chatbot.retrieval.graph_neighbor_relationship_chunks_per_file` | `2` | Relationship chunks per linked file during graph expansion |
| `chatbot.retrieval.graph_neighbor_max_docs` | `4` | Max linked docs pulled in during graph expansion |
| `chatbot.retrieval.rerank` | `true` | Use LLM to rerank retrieved chunks |
| `chatbot.retrieval.rerank_candidate_limit` | `32` | Max candidates sent to the reranker |
| `chatbot.retrieval.rerank_candidate_limit_per_kind` | `8` | Per-kind candidate cap before filling the global rerank pool |
| `chatbot.retrieval.rerank_preview_chars` | `450` | Characters of each chunk shown to the reranker |
| `chatbot.retrieval.stitch_adjacent_code_chunks` | `true` | Expand exact-match code hits with adjacent windows from the same file |
| `chatbot.retrieval.stitch_max_adjacent_chunks` | `2` | Max adjacent code windows stitched onto a top hit |
| `chatbot.retrieval.deep_research_live_fallback` | `true` | Allow `/deep-research` to inspect bounded live repo files when indexed retrieval is weak |
| `chatbot.retrieval.live_fallback_max_files` | `6` | Max repo files inspected during a deep-research live fallback |
| `chatbot.retrieval.live_fallback_max_per_file` | `2` | Max fallback snippets returned per inspected file |
| `chatbot.retrieval.live_fallback_context_lines` | `12` | Lines per fallback snippet around each exact match |
| `chatbot.retrieval.deep_research_chunk_chars` | `3200` | Max chars per evidence chunk passed into deep-research step answers |
| `chatbot.retrieval.deep_research_top_k` | `10` | Retrieved chunks per deep-research sub-question |
| **Chunking** | | |
| `chatbot.chunking.code_chunk_lines` | `120` | Lines per code chunk |
| `chatbot.chunking.code_chunk_overlap` | `20` | Overlap lines between code chunks |
| `chatbot.chunking.artifact_chunk_lines` | `140` | Lines per artifact chunk |
| `chatbot.chunking.artifact_chunk_overlap` | `20` | Overlap lines between artifact chunks |
| `chatbot.chunking.max_doc_summary_chunks_per_page` | `4` | Doc summary chunks extracted per page |
| `chatbot.chunking.max_doc_summary_chars` | `4000` | Max chars per doc summary chunk |

</details>

### Chatbot Provider Examples

The chatbot's `answer` and `embeddings` sections are configured independently from the main `llm` section, so you can use different providers for doc generation vs. chatbot.

**Azure:**

```yaml
chatbot:
  answer:
    provider: "azure"
    model: "azure/gpt-4o-mini"
    base_url: "https://YOUR-RESOURCE.openai.azure.com/"
    api_version: "2024-08-01-preview"
    api_key_env: "DEEPDOC_CHAT_API_KEY"
  embeddings:
    provider: "azure"
    model: "azure/text-embedding-3-large"
    base_url: "https://YOUR-RESOURCE.openai.azure.com/"
    api_version: "2024-08-01-preview"
    api_key_env: "DEEPDOC_EMBED_API_KEY"
```

**OpenAI:**

```yaml
chatbot:
  answer:
    provider: "openai"
    model: "gpt-4o-mini"
    api_key_env: "DEEPDOC_CHAT_API_KEY"
  embeddings:
    provider: "openai"
    model: "text-embedding-3-large"
    api_key_env: "DEEPDOC_EMBED_API_KEY"
    batch_size: 24                            # OpenAI supports larger batches
```

**Google Gemini:**

```yaml
chatbot:
  answer:
    provider: "gemini"
    model: "gemini/gemini-2.0-flash"
    api_key_env: "DEEPDOC_CHAT_API_KEY"
  embeddings:
    backend: "litellm"
    provider: "gemini"
    model: "gemini/text-embedding-004"
    api_key_env: "DEEPDOC_EMBED_API_KEY"
```

**Fully local embeddings with fastembed:**

```yaml
chatbot:
  embeddings:
    backend: "fastembed"
    fastembed_model: "nomic-ai/nomic-embed-text-v1.5"
    fastembed_batch_size: 4
```

**Anthropic:**

```yaml
chatbot:
  answer:
    provider: "anthropic"
    model: "claude-3-5-sonnet-20241022"
    api_key_env: "DEEPDOC_CHAT_API_KEY"
  embeddings:
    provider: "openai"                        # Anthropic doesn't offer embedding models
    model: "text-embedding-3-large"
    api_key_env: "DEEPDOC_EMBED_API_KEY"
```

### How Chatbot Indexing Works

During `deepdoc generate`, six corpora are built and stored in `.deepdoc/chatbot/`:

| Corpus | Source | Description |
|--------|--------|-------------|
| **Code chunks** | All parsed source files | Code split by line count with overlap, tagged with symbols and file paths |
| **Artifact chunks** | Config files (Dockerfile, package.json, OpenAPI specs, etc.) | Non-code project files split similarly |
| **Doc summary chunks** | Generated documentation pages | First sections extracted from each generated Markdown page |
| **Doc full chunks** | Generated documentation pages | Section-level chunks from the full generated Markdown pages |
| **Repo doc chunks** | Repo-authored docs such as `README.md`, `docs/`, design notes, and notebooks | Raw repo documentation kept separate from generated pages |
| **Relationship chunks** | Imports, symbols, call graph, and graph-neighbor summaries | Lightweight graph-style retrieval context |

`deepdoc update` incrementally syncs the chatbot indexes from the same commit-based update run — only changed files, repo-doc candidates, and regenerated doc pages are re-indexed.

### Chatbot Query Pipeline

When a user asks a question, the backend runs a mode-aware retrieval pipeline:

1. **Query expansion** — In default/deep/code-aware mode, the LLM can generate alternative search queries to improve recall. Fast mode disables this by default.
2. **Embedding** — All queries are embedded using the configured embedding model.
3. **Hybrid retrieval** — FAISS similarity search and exact-match lexical search both gather candidates from each corpus.
4. **Follow-up retrieval** — The backend can derive focused second-pass searches and pull linked files/docs via graph-neighbor expansion. Fast mode can skip follow-up queries for lower latency.
5. **Chunk stitching** — Exact-match code hits can pull adjacent code windows from the same file so larger implementations survive chunk boundaries.
6. **Reranking** — In default/deep/code-aware mode, the LLM can rerank candidates for relevance. Fast mode disables this by default.
7. **Prompt assembly** — Query-type-aware budgets reserve space for the most important evidence types within the character budget.
8. **Answer generation + continuity guard** — The answer LLM produces a grounded response, and if the output appears truncated (for example ending on a dangling heading), DeepDoc retries with a continuation prompt so the response finishes cleanly.

`POST /deep-research` uses the same indexed corpora first, but it can also inspect a small bounded set of live repo files when exact-match evidence is missing from the index. This fallback respects the repo's exclude rules, skips oversized/binary files, and is only used in deep research mode.

`POST /code-deep` uses a code-heavy retrieval profile and returns an explicit file inventory plus step trace so users can see where evidence came from while answering file-oriented questions such as “where is auth defined?”.

`POST /query`, `POST /deep-research`, and `POST /code-deep` return `response_mode` in the payload (`fast`, `deep`, `code_deep`, or `default`) so clients can confirm which retrieval profile generated the result.

### Chatbot API Endpoints

The generated `chatbot_backend/` exposes five endpoints:

**Health check:**
```
GET /health → { "status": "ok" }
```

**Query:**
```
POST /query
{
  "question": "How does authentication work?",
  "history": [
    { "role": "user", "content": "What endpoints exist?" },
    { "role": "assistant", "content": "..." }
  ]
}
```

The response includes the answer text, code citations (file path + line range), artifact citations, and links to relevant generated doc pages.

`/query` is optimized for speed: it runs retrieval in fast mode (no LLM query expansion/rerank by default) and returns an answer plus citations.

**Code-aware deep query:**
```
POST /code-deep
{
  "question": "Where is authentication defined?",
  "history": [],
  "max_rounds": 4
}
```

`/code-deep` returns a code-aware answer plus `trace` and `file_inventory` fields so clients can show reasoning progress and files considered.

**Code-aware live stream (SSE):**
```
POST /code-deep/stream
{
  "question": "Where is authentication defined?",
  "history": [],
  "max_rounds": 4
}
```

`/code-deep/stream` emits `trace` events while researching, then a final `result` event and `done`.

**Retrieve context only (no answer generation):**
```
POST /query-context
{
  "question": "Where is reshipping implemented?",
  "history": []
}
```

`/query-context` returns selected citations/chunks only. Use this endpoint to inspect retrieval quality independently from answer generation.

### Deploying the Chatbot

For local development, `deepdoc serve` handles everything automatically. For production:

1. Deploy the MkDocs static site (`site/out/`) to any static host.
2. Deploy `chatbot_backend/` separately to a Python-capable host.
3. Set `chatbot.backend.base_url` in `.deepdoc.yaml` to point at the deployed backend URL.
4. Rebuild the site so the frontend picks up the new backend URL: `deepdoc deploy`.

### Cleaning Up Chatbot Files

```bash
deepdoc clean          # Removes chatbot_backend/, .deepdoc/chatbot/, and other generated state
deepdoc clean --yes    # Skip confirmation prompt
```

---

## Supported Languages & Frameworks

**Parsing (tree-sitter AST + regex fallback):**

| Language | Extensions | Extracts |
|----------|-----------|----------|
| Python | `.py` | Functions, classes, decorators, imports |
| JavaScript | `.js`, `.jsx`, `.mjs`, `.cjs` | Functions, classes, arrow functions, imports |
| TypeScript | `.ts`, `.tsx` | Same as JS + interfaces, type aliases |
| Go | `.go` | Functions, methods, structs, interfaces |
| PHP | `.php` | Functions, classes, methods, namespaces |
| Vue | `.vue` | SFC script symbols, props/emits/slots, router/store usage |

**High-confidence framework support (fixture-backed):**

| Framework | Language | Proven patterns |
|-----------|----------|-----------------|
| Laravel | PHP | `Route::get()`, grouped prefixes, middleware, resource expansion |
| Django / DRF | Python | `path()`, `re_path()`, `@api_view`, `as_view()`, DRF routers, `@action` |
| Express | JS/TS | Mounted routers via `app.use()`, nested prefixes, chained `route()` calls |
| Fastify | JS/TS | Plugin `register(..., { prefix })`, shorthand methods, `route({ ... })`, schema hints |
| Falcon | Python | `app.add_route()`, responder classes, imported resources, app middleware |
| Vue | Vue SFC | Component detection, `defineProps`, `defineEmits`, `defineModel`, `defineSlots`, router/store signals |

**Supported but not headline-high-confidence yet:**

| Framework | Language | Current coverage |
|-----------|----------|------------------|
| Gin / Echo / Fiber | Go | Common route helpers (`GET`, `POST`, `HandleFunc`) |

**Runtime/background surface extraction:**

| Surface | Current coverage |
|---------|------------------|
| Celery | Tasks, retry/queue hints, beat schedules, producers |
| Django | Management commands, signal receivers, Channels websocket consumers |
| Laravel | Queued jobs, listeners, events, scheduler registrations |
| JS/TS | `node-cron`, queue workers, agenda jobs, Socket.IO / websocket consumers |
| Go | Goroutine workers, `AddFunc` cron registrations, scheduler `.Every(...).Do(...)` patterns |
| Generic cron | Python `crontab(...)` style schedule declarations |

---

## Architecture

The current system is bucket-based.

**Planner bucket types:**

| Type | Purpose |
|------|---------|
| `system` | Architecture, setup, testing, deployment/ops, auth, shared middleware, observability |
| `feature` | Business workflows like checkout, refunds, order status, onboarding |
| `endpoint` | Endpoint-family or resource-level API docs |
| `endpoint_ref` | Legacy or OpenAPI-backed single-endpoint page; scanned runtime endpoints are grouped into endpoint-family docs by default |
| `integration` | Third-party systems like payment, warehouse, delivery, webhook providers |
| `database` | Cross-cutting database/schema/data-layer documentation |

**Five implemented phases:**

1. **Repository scan/indexing**
   - Parse supported source files
   - Detect endpoints, config files, setup artifacts, runtime surfaces, integrations, and OpenAPI specs
   - Record file sizes, symbols, imports, config impacts, and raw scan summaries
2. **Multi-step planning**
   - Classify repo artifacts
   - Propose system/feature/endpoint/integration/database buckets
   - Assign files, symbols, and artifacts into the final plan
3. **Generation engine**
    - Build evidence packs for buckets
    - Generate pages in batches with parallel workers
    - Enrich grouped endpoint-family pages with scanned endpoint details and stage OpenAPI-backed API pages when a spec exists
    - Validate output for file, route, runtime, config, and integration grounding
    - Degrade gracefully on failures
    - Persist quality status so invalid/degraded pages are visible after a run
4. **Persistence**
   - Persist plan, file map, scan cache, and generation ledger in `.deepdoc/`
   - Keep enough state for updates, staleness detection, and cleanup
5. **Smart update**
   - Choose incremental update vs targeted replan vs full replan
   - Refresh only stale docs when safe
   - Rebuild affected docs after structural repo changes

---

## Generated Files

After running `deepdoc generate`, you'll find:

```
your-repo/
├── .deepdoc.yaml              # Config
├── .deepdoc/                  # Canonical persisted state
│   ├── plan.json               # Bucket plan
│   ├── scan_cache.json         # Lightweight scan snapshot
│   ├── ledger.json             # Generated-page ledger
│   ├── file_map.json           # file → bucket/page mapping
│   ├── state.json              # last synced commit + update status
│   └── sync_receipt.json       # latest update/generate sync receipt
├── .deepdoc_manifest.json     # Legacy source hash manifest
├── .deepdoc_plan.json         # Legacy compatibility plan file
├── .deepdoc_file_map.json     # Legacy compatibility file map
├── docs/                       # Generated Markdown pages
│   ├── index.md
│   ├── architecture.md
│   ├── setup-and-configuration.md
│   ├── api.md                  # Swagger UI page (when an OpenAPI spec exists)
│   ├── openapi/                # Staged OpenAPI specs
│   └── ...
└── site/                       # Generated MkDocs Material site
    ├── mkdocs.yml
    ├── docs/stylesheets/extra.css
    └── out/                    # Static HTML after `deepdoc deploy`
```

---

## GitHub Actions CI/CD

Use GitHub Pages Actions when you want to publish the already-generated static export from `site/out/`:

```yaml
# .github/workflows/github-pages.yml
name: Deploy GitHub Pages

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/configure-pages@v5
      - run: |
          test -d site/out
          test -f site/out/index.html
      - uses: actions/upload-pages-artifact@v3
        with:
          path: site/out

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```

This workflow publishes the committed `site/out/` directory directly, so GitHub Pages does not need a `docs/` folder.

If you want to regenerate docs on every push before deploying them, use a separate workflow like this:

```yaml
# .github/workflows/docs.yml
name: Update And Deploy Documentation

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  update-docs:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pages: write
      id-token: write

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0    # Full history needed for git diff

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - uses: actions/setup-node@v4
        with:
          node-version: "20"

      - name: Install dependencies
        run: |
          pip install deepdoc   # or: pip install "deepdoc[chatbot]" if you use chatbot features

      - name: Update and deploy docs
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          deepdoc update --strict-quality --deploy

      - name: Upload Pages artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: site/out

  deploy:
    needs: update-docs
    runs-on: ubuntu-latest
    environment:
      name: github-pages
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```

Add your API key to repo Settings → Secrets → Actions → `ANTHROPIC_API_KEY`.

If you self-host and just want docs kept fresh without deploying to GitHub Pages, use this minimal variant instead — it commits the refreshed `docs/` and `.deepdoc/` state back to the branch:

```yaml
# .github/workflows/deepdoc-refresh.yml
name: Refresh Docs

on:
  push:
    branches: [main]

jobs:
  refresh:
    runs-on: ubuntu-latest
    permissions:
      contents: write

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0    # Full history needed for git diff

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - uses: actions/setup-node@v4
        with:
          node-version: "20"

      - name: Install deepdoc
        run: pip install deepdoc

      - name: Refresh docs
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: deepdoc update --strict-quality

      - name: Commit updated docs
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add docs/ .deepdoc/
          git diff --cached --quiet || git commit -m "chore: refresh docs [skip ci]"
          git push
```

The `[skip ci]` tag on the commit message prevents the workflow from triggering itself again.

---

## Contributing & Releases

Release flow for the Python package and the VS Code extension, plus repo layout and test-running notes, lives in [CONTRIBUTING.md](./CONTRIBUTING.md). Both tracks publish automatically when you push a version bump to `main`.

---

## Typical Workflow

**First time:**
```bash
cd your-repo
deepdoc init --provider anthropic
export ANTHROPIC_API_KEY=sk-ant-...
deepdoc generate
deepdoc serve                      # Preview at localhost:3000
deepdoc deploy                     # Export a static site to site/out/
```

**Every time you update code:**
```bash
git add . && git commit -m "feat: new feature"
deepdoc update                     # Only regenerates affected pages
deepdoc deploy                     # Or use --deploy flag with update
```

**Full refresh after planner / prompt / generator changes:**
```bash
deepdoc generate --force
```

**Wipe docs and rebuild from zero:**
```bash
deepdoc generate --clean --yes
```

**Switch LLM mid-project:**
```bash
deepdoc config set llm.provider openai
deepdoc config set llm.model gpt-4o
export OPENAI_API_KEY=sk-...
deepdoc generate --force           # Full regen with new model
```

---

## Requirements

- Python 3.10+
- **MkDocs Material** (`pip install mkdocs-material`) — used by `deepdoc serve` and `deepdoc deploy` for the generated site. Pure Python, no Node.js. Add `mkdocs-swagger-ui-tag` when your repo has an OpenAPI/Swagger spec.
- Git (for `deepdoc update` and `deepdoc deploy`)
- An LLM API key (or Ollama running locally)

---

## License

MIT
