# CodeWiki

Auto-generate deep engineering documentation from real codebases using AI.

CodeWiki scans your repo, builds a bucket-based documentation plan, generates rich MDX pages with Mermaid diagrams, and builds a local-first Fumadocs site with Orama search.

---

## Features

- **Bucket-Based Documentation Architecture** — Docs are planned as system, feature, endpoint, endpoint reference, integration, and database buckets instead of noisy one-file-per-page output.
- **Five-Phase Pipeline** — Scan, plan, generate, playground, build. Planning and generation are separated so large repos and large files are handled more cleanly.
- **Multi-Step AI Planner** — The planner classifies the repo, proposes buckets, then assigns files, symbols, artifacts, and dependencies into the final doc structure.
- **Giant-File Handling** — Large files are decomposed into feature-aligned clusters so giant controllers or service files can feed multiple doc pages.
- **Endpoint-Family + Per-Endpoint Docs** — High-level endpoint family pages are AI-planned, and individual `endpoint_ref` pages are derived from scan data and generated separately.
- **Integration Discovery** — Third-party systems like payment gateways, delivery providers, warehouse systems, and webhook integrations can be grouped into integration docs.
- **Incremental Updates** — `codewiki update` uses persisted plan and ledger data to regenerate only stale or structurally affected docs.
- **Full Refresh and Clean Rebuild Modes** — `generate --force` fully refreshes CodeWiki-managed docs and removes stale generated pages; `generate --clean --yes` wipes output and rebuilds from scratch.
- **Safe Existing-Docs Behavior** — Plain `generate` refuses to run over an existing CodeWiki-managed docs set and will not silently mix into a non-CodeWiki `docs/` folder.
- **Multi-Language Support** — JavaScript/TypeScript, Python, Go, PHP/Laravel with tree-sitter AST parsing and regex fallback.
- **Configurable LLM** — Works with Anthropic, OpenAI, Azure OpenAI, Ollama, and other LiteLLM-compatible providers.
- **Mermaid Diagrams** — Generated pages can include architecture, flow, and request-sequence diagrams.
- **OpenAPI-Aware API Docs** — Auto-detects OpenAPI/Swagger specs and stages canonical interactive `/api/*` pages in the generated site.
- **Local-First Fumadocs Site** — Generates a `site/` Next.js app with Fumadocs UI, Mermaid rendering, and built-in Orama search.
- **Static Export** — `codewiki deploy` exports a static site to `site/out/` for any static host.

---

## Installation

### From source (recommended during development)

```bash
git clone <your-repo-url>
cd codewiki
pip install -e .
```

If the full install is slow due to tree-sitter compilation, install core deps first:

```bash
pip install click litellm gitpython rich pyyaml jinja2
pip install -e . --no-deps
```

### Verify installation

```bash
codewiki --version
codewiki --help
python -m codewiki --help
```

---

## Quick Start

```bash
# 1. Go to your project
cd /path/to/your-project

# 2. Initialize CodeWiki
codewiki init

# 3. Set your API key
export ANTHROPIC_API_KEY=sk-ant-...

# 4. Generate docs
codewiki generate

# 5. Preview locally
codewiki serve
# → Open http://localhost:3000
```

---

## Commands

Every command supports `--help`, including nested config commands:

```bash
codewiki --help
codewiki generate --help
codewiki config --help
codewiki config set --help
```

### `codewiki init`

Initializes CodeWiki in the current directory by creating a `.codewiki.yaml` config file.

```bash
codewiki init
codewiki init --provider openai --model gpt-4o
codewiki init --provider ollama --model ollama/llama3.2
codewiki init --provider azure --model azure/gpt-4o
codewiki init --output-dir documentation
```

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--name` | directory name | Project name |
| `--description` | empty | Short project description |
| `--provider` | `anthropic` | LLM provider: `anthropic`, `openai`, `ollama`, `azure` |
| `--model` | provider default | Model name |
| `--output-dir` | `docs` | Where generated docs are written |

### `codewiki generate`

Full documentation generation. This is the first-run or explicit full-refresh command.

```bash
codewiki generate
codewiki generate --force           # Full refresh of CodeWiki-managed docs
codewiki generate --clean --yes     # Wipe output + state and rebuild from scratch
codewiki generate --deploy          # Generate + export the static site
codewiki generate --batch-size 3    # Smaller batches for rate-limited APIs
codewiki generate --include "src/**" --include "lib/**"
codewiki generate --exclude "tests/**"
```

**Current behavior:**

- `codewiki generate`
  - intended for the first run
  - refuses to run if CodeWiki docs/state already exist
  - refuses to write into a non-CodeWiki `docs/` folder unless you explicitly clean it
- `codewiki generate --force`
  - re-runs the full pipeline
  - regenerates all CodeWiki-managed pages even if they are not stale
  - removes stale generated pages that no longer belong in the new plan
  - preserves non-CodeWiki files
- `codewiki generate --clean --yes`
  - deletes the output dir and CodeWiki state
  - rebuilds everything from scratch

**What happens under the hood (5-phase pipeline):**

1. **Phase 1: Scan** — Walk the repo, parse supported languages, detect endpoints, config/setup artifacts, integration signals, and OpenAPI specs.
2. **Phase 2: Plan** — Run the multi-step bucket planner. It classifies the repo, proposes bucket candidates, and assigns files/symbols/artifacts to the final doc structure.
3. **Phase 3: Generate** — Generate bucket pages in batches with parallel workers. High-level buckets are AI-planned; per-endpoint reference pages are derived from scan data and generated individually.
4. **Phase 4: API Ref** — Stage OpenAPI assets for the generated Fumadocs `/api/*` pages when a spec exists.
5. **Phase 5: Build** — Write the generated `site/` Fumadocs scaffold, page tree, search route, and static assets from the generated plan.

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--force` | off | Full refresh of CodeWiki-managed docs and cleanup of stale generated pages |
| `--clean` | off | Delete output dir and CodeWiki state, then regenerate from scratch |
| `--yes` | off | Skip destructive confirmation for `--clean` |
| `--include` | all files | Glob patterns to include (can be repeated) |
| `--exclude` | see config | Additional glob patterns to exclude |
| `--deploy` | off | Build and export the static site after generation |
| `--batch-size` | 10 | Pages per batch before pausing (helps with rate limits) |

### `codewiki update`

Incrementally update docs when source files change. This is the normal command after the first successful `generate`.

```bash
codewiki update                    # Normal ongoing refresh
codewiki update --since HEAD~3     # Changes in last 3 commits
codewiki update --since main       # All changes since branching from main
codewiki update --replan           # Force a full replan
codewiki update --deploy           # Update + deploy
```

**How it works:**

1. Loads the saved plan and generation ledger from `.codewiki/`.
2. Detects changed, new, and deleted files.
3. Chooses a strategy automatically:
   - incremental update
   - targeted replan
   - full replan
4. Regenerates only the affected bucket pages when safe.
5. Rebuilds site config and nav afterward.

If git is unavailable, it falls back to hash-based staleness detection.

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--since` | `HEAD~1` | Git ref to diff against |
| `--replan` | off | Force a full replan even if the change set looks incremental |
| `--deploy` | off | Deploy after updating |

### `codewiki status`

Show how much documentation has been generated and whether any buckets are stale.

```bash
codewiki status
```

This is useful after `generate` or `update` when you want a quick health check without opening the site.

### `codewiki serve`

Preview the generated docs locally with live reload using the generated Fumadocs app in `site/`.

```bash
codewiki serve
codewiki serve --port 3000
```

Requires Node.js >= 18 to be installed. Site dependencies are auto-installed into `site/node_modules/` on first run.

### `codewiki deploy`

Build and export the generated Fumadocs site.

```bash
codewiki deploy
```

This runs `next build` inside `site/` and writes the static export to `site/out/`. You can deploy that directory to Vercel, Netlify, GitHub Pages, Cloudflare Pages, or any static host.

### `codewiki config`

View or update config values without editing YAML manually.

```bash
codewiki config show                                    # Print all config
codewiki config set llm.provider openai                 # Switch provider
codewiki config set llm.model gpt-4o                    # Switch model
codewiki config set llm.temperature 0.3                 # Adjust creativity
codewiki config set output_dir documentation            # Change output dir
codewiki config set llm.api_key_env AZURE_API_KEY       # Change API key env var
```

---

## LLM Provider Setup

CodeWiki uses [LiteLLM](https://github.com/BerriAI/litellm) under the hood, which means it supports 100+ LLM providers. Here are the most common setups:

### Anthropic (Claude) — Default

```bash
codewiki init --provider anthropic
export ANTHROPIC_API_KEY=sk-ant-api03-...
codewiki generate
```

Models: `claude-3-5-sonnet-20241022`, `claude-3-opus-20240229`, `claude-3-haiku-20240307`

### OpenAI (GPT)

```bash
codewiki init --provider openai --model gpt-4o
export OPENAI_API_KEY=sk-...
codewiki generate
```

Models: `gpt-4.1`, `gpt-4.1-mini`, `gpt-4o`, `gpt-4o-mini`, `gpt-4-turbo`

### Azure OpenAI

Azure requires a few more environment variables because deployments have custom names and endpoints.

```bash
# 1. Initialize with Azure
codewiki init --provider azure --model azure/<your-deployment-name>

# 2. Set required environment variables
export AZURE_API_KEY=your-azure-api-key
export AZURE_API_BASE=https://<your-resource-name>.openai.azure.com
export AZURE_API_VERSION=2024-02-01

# 3. Update config to point to your deployment
codewiki config set llm.model azure/<your-deployment-name>
codewiki config set llm.base_url https://<your-resource-name>.openai.azure.com

# 4. Generate
codewiki generate
```

**Where to find these values in Azure Portal:**

1. Go to [Azure Portal](https://portal.azure.com) → Azure OpenAI resource.
2. Click **Keys and Endpoint** in the sidebar → copy **Key 1** (that's your `AZURE_API_KEY`) and the **Endpoint** (that's your `AZURE_API_BASE`).
3. Go to **Model deployments** → **Manage Deployments** → note your deployment name (e.g., `gpt-4o-deployment`). Use this as `azure/gpt-4o-deployment` in the model field.
4. API version: Use `2024-02-01` or the latest GA version shown in Azure docs.

**Example `.codewiki.yaml` for Azure:**

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
codewiki init --provider ollama --model ollama/llama3.2

# 3. Generate (no API key needed)
codewiki generate
```

Other Ollama models: `ollama/codellama`, `ollama/mistral`, `ollama/mixtral`

### Any LiteLLM Provider

CodeWiki passes the model string directly to LiteLLM, so you can use any provider LiteLLM supports by using the correct prefix:

```bash
# Groq
codewiki config set llm.model groq/llama3-70b-8192
export GROQ_API_KEY=...

# Together AI
codewiki config set llm.model together_ai/meta-llama/Llama-3-70b-chat-hf
export TOGETHER_API_KEY=...

# AWS Bedrock
codewiki config set llm.model bedrock/anthropic.claude-3-sonnet-20240229-v1:0
# (uses AWS credentials from environment)
```

See [LiteLLM providers](https://docs.litellm.ai/docs/providers) for the full list.

---

## Configuration

The `.codewiki.yaml` file in your repo root controls everything:

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
| `site_dir` | `site` | Where MkDocs builds the static site |
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
| `site.repo_url` | `""` | Repo URL shown in the generated Fumadocs navigation |
| `site.favicon` | `""` | Path to favicon |
| `site.logo` | `""` | Path to logo |

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
| FastAPI | Python | `@app.get()`, `@router.post()`, docstrings, `response_model` |
| Flask | Python | `@app.route()` with method expansion |
| Laravel | PHP | `Route::get()`, grouped prefixes, middleware, resource expansion |
| Django / DRF | Python | `path()`, `re_path()`, `@api_view`, `as_view()`, DRF routers, `@action` |
| Express | JS/TS | Mounted routers via `app.use()`, nested prefixes, chained `route()` calls |
| Fastify | JS/TS | Plugin `register(..., { prefix })`, shorthand methods, `route({ ... })`, schema hints |
| Vue | Vue SFC | Component detection, `defineProps`, `defineEmits`, `defineModel`, `defineSlots`, router/store signals |

**Supported but not headline-high-confidence yet:**

| Framework | Language | Current coverage |
|-----------|----------|------------------|
| NestJS | TS | `@Controller` + `@Get/@Post` decorators |
| Falcon | Python | `app.add_route()` + `on_get/on_post` responders |
| Gin / Echo / Fiber | Go | Common route helpers (`GET`, `POST`, `HandleFunc`) |
| Next.js / Nuxt | JS/TS | Repo-level framework detection and planning hints |

---

## Architecture

The current system is bucket-based.

**Planner bucket types:**

| Type | Purpose |
|------|---------|
| `system` | Architecture, setup, testing, deployment/ops, auth, shared middleware, observability |
| `feature` | Business workflows like checkout, refunds, order status, onboarding |
| `endpoint` | Endpoint-family or resource-level API docs |
| `endpoint_ref` | One generated page per concrete API endpoint |
| `integration` | Third-party systems like payment, warehouse, delivery, webhook providers |
| `database` | Cross-cutting database/schema/data-layer documentation |

**Five implemented phases:**

1. **Repository scan/indexing**
   - Parse supported source files
   - Detect endpoints, config files, setup artifacts, OpenAPI specs
   - Record file sizes, symbols, imports, and raw scan summaries
2. **Multi-step planning**
   - Classify repo artifacts
   - Propose system/feature/endpoint/integration/database buckets
   - Assign files, symbols, and artifacts into the final plan
3. **Generation engine**
   - Build evidence packs for buckets
   - Generate pages in batches with parallel workers
   - Create nested endpoint reference pages under endpoint families
   - Validate output and degrade gracefully on failures
4. **Persistence**
   - Persist plan, file map, scan cache, and generation ledger in `.codewiki/`
   - Keep enough state for updates, staleness detection, and cleanup
5. **Smart update**
   - Choose incremental update vs targeted replan vs full replan
   - Refresh only stale docs when safe
   - Rebuild affected docs after structural repo changes

---

## Generated Files

After running `codewiki generate`, you'll find:

```
your-repo/
├── .codewiki.yaml              # Config
├── .codewiki/                  # Canonical persisted state
│   ├── plan.json               # Bucket plan
│   ├── scan_cache.json         # Lightweight scan snapshot
│   ├── ledger.json             # Generated-page ledger
│   ├── file_map.json           # file → bucket/page mapping
│   └── state.json              # last synced commit + update status
├── .codewiki_manifest.json     # Legacy source hash manifest
├── .codewiki_plan.json         # Legacy compatibility plan file
├── .codewiki_file_map.json     # Legacy compatibility file map
├── docs/                       # Generated MDX pages
│   ├── index.mdx
│   ├── architecture.mdx
│   ├── setup-and-configuration.mdx
│   ├── orders-api.mdx
│   ├── get-api-v1-orders.mdx
│   └── ...
└── site/                       # Generated Fumadocs app
    ├── app/
    ├── components/
    ├── lib/
    ├── openapi/                # Staged OpenAPI assets (when a spec exists)
    ├── public/
    └── out/                    # Static export after `codewiki deploy`
```

---

## GitHub Actions CI/CD

Automate doc updates on every push to main:

```yaml
# .github/workflows/docs.yml
name: Update Documentation

on:
  push:
    branches: [main]

jobs:
  update-docs:
    runs-on: ubuntu-latest
    permissions:
      contents: write       # Needed for gh-pages push

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
          pip install ./codewiki   # or from PyPI if published

      - name: Update and deploy docs
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          codewiki update --deploy
```

Add your API key to repo Settings → Secrets → Actions → `ANTHROPIC_API_KEY`.

---

## Typical Workflow

**First time:**
```bash
cd your-repo
codewiki init --provider anthropic
export ANTHROPIC_API_KEY=sk-ant-...
codewiki generate
codewiki serve                      # Preview at localhost:3000
codewiki deploy                     # Export a static site to site/out/
```

**Every time you update code:**
```bash
git add . && git commit -m "feat: new feature"
codewiki update                     # Only regenerates affected pages
codewiki deploy                     # Or use --deploy flag with update
```

**Full refresh after planner / prompt / generator changes:**
```bash
codewiki generate --force
```

**Wipe docs and rebuild from zero:**
```bash
codewiki generate --clean --yes
```

**Switch LLM mid-project:**
```bash
codewiki config set llm.provider openai
codewiki config set llm.model gpt-4o
export OPENAI_API_KEY=sk-...
codewiki generate --force           # Full regen with new model
```

---

## Requirements

- Python 3.10+
- Git (for `codewiki update` and `codewiki deploy`)
- An LLM API key (or Ollama running locally)

---

## License

MIT
