# DeepDoc

[![PyPI version](https://img.shields.io/pypi/v/deepdoc)](https://pypi.org/project/deepdoc/)
[![Python versions](https://img.shields.io/pypi/pyversions/deepdoc)](https://pypi.org/project/deepdoc/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

Auto-generate deep engineering documentation from real codebases using AI.

DeepDoc scans your repo, builds a bucket-based documentation plan, generates rich MDX pages with Mermaid diagrams, and builds a local-first Fumadocs site with Orama search.

---

## Features

- **Bucket-Based Documentation Architecture** — Docs are planned as system, feature, endpoint, endpoint reference, integration, and database buckets instead of noisy one-file-per-page output.
- **Five-Phase Pipeline** — Scan, plan, generate, playground, build. Planning and generation are separated so large repos and large files are handled more cleanly.
- **Multi-Step AI Planner** — The planner classifies the repo, proposes buckets, then assigns files, symbols, artifacts, and dependencies into the final doc structure.
- **Giant-File Handling** — Large files are decomposed into feature-aligned clusters so giant controllers or service files can feed multiple doc pages.
- **Endpoint-Family + Per-Endpoint Docs** — High-level endpoint family pages are AI-planned, and individual `endpoint_ref` pages are derived from scan data and generated separately.
- **Integration Discovery** — Third-party systems like payment gateways, delivery providers, warehouse systems, and webhook integrations can be grouped into integration docs.
- **Incremental Updates** — `deepdoc update` uses persisted plan and ledger data to regenerate only stale or structurally affected docs.
- **Full Refresh and Clean Rebuild Modes** — `generate --force` fully refreshes DeepDoc-managed docs and removes stale generated pages; `generate --clean --yes` wipes output and rebuilds from scratch.
- **Safe Existing-Docs Behavior** — Plain `generate` refuses to run over an existing DeepDoc-managed docs set and will not silently mix into a non-DeepDoc `docs/` folder.
- **Multi-Language Support** — JavaScript/TypeScript, Python, Go, PHP/Laravel with tree-sitter AST parsing and regex fallback.
- **Configurable LLM** — Works with Anthropic, OpenAI, Azure OpenAI, Ollama, and other LiteLLM-compatible providers.
- **Mermaid Diagrams** — Generated pages can include architecture, flow, and request-sequence diagrams.
- **OpenAPI-Aware API Docs** — Auto-detects OpenAPI/Swagger specs and stages canonical interactive `/api/*` pages in the generated site.
- **Local-First Fumadocs Site** — Generates a `site/` Next.js app with Fumadocs UI, Mermaid rendering, and built-in Orama search.
- **Static Export** — `deepdoc deploy` exports a static site to `site/out/` for any static host.

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

### Verify installation

```bash
deepdoc --version
deepdoc --help
python -m deepdoc --help
```

If you installed the chatbot extra, you can verify those dependencies with:

```bash
pip show faiss-cpu fastapi uvicorn
```

---

## Quick Start

```bash
# 1. Go to your project
cd /path/to/your-project

# 2. Initialize DeepDoc
deepdoc init

# 3. Set your API key
export ANTHROPIC_API_KEY=sk-ant-...

# 4. Generate docs
deepdoc generate

# 5. Preview locally
deepdoc serve
# → Open http://localhost:3000
```

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
3. **Phase 3: Generate** — Generate bucket pages in batches with parallel workers. High-level buckets are AI-planned; per-endpoint reference pages are derived from scan data and generated individually.
4. **Phase 4: API Ref** — Stage OpenAPI assets for the generated Fumadocs `/api/*` pages when a spec exists.
5. **Phase 5: Build** — Write the generated `site/` Fumadocs scaffold, page tree, search route, and static assets from the generated plan.

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
deepdoc update --deploy           # Update + deploy
```

**How it works:**

1. Loads the saved sync baseline, plan, and generation ledger from `.deepdoc/`.
2. Diffs committed changes from the last synced commit to the current `HEAD`.
3. Chooses a strategy automatically:
   - incremental update
   - targeted replan
   - full replan
4. Compares the saved scan cache with the current scan so semantic endpoint changes can refresh impacted docs even when ownership files do not line up directly.
5. Regenerates only the affected bucket pages when safe.
6. Incrementally refreshes the chatbot corpora from the same update run.
7. Rebuilds site config and nav afterward.

If git is unavailable, it falls back to hash-based staleness detection for recovery.

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--since` | last synced commit | Git ref to diff against |
| `--replan` | off | Force a full replan even if the change set looks incremental |
| `--deploy` | off | Deploy after updating |

### `deepdoc status`

Show how much documentation has been generated and whether any buckets are stale.

```bash
deepdoc status
```

This is useful after `generate` or `update` when you want a quick health check without opening the site.

### `deepdoc serve`

Preview the generated docs locally with live reload using the generated Fumadocs app in `site/`.

```bash
deepdoc serve
deepdoc serve --port 8001
```

Requires Node.js >= 18 to be installed. Site dependencies are auto-installed into `site/node_modules/` on first run.

### `deepdoc deploy`

Build and export the generated Fumadocs site.

```bash
deepdoc deploy
```

This runs `next build` inside `site/` and writes the static export to `site/out/`. You can deploy that directory to Vercel, Netlify, GitHub Pages, Cloudflare Pages, or any static host.

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

DeepDoc uses [LiteLLM](https://github.com/BerriAI/litellm) under the hood, which means it supports 100+ LLM providers. Here are the most common setups:

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

DeepDoc passes the model string directly to LiteLLM, so you can use any provider LiteLLM supports by using the correct prefix:

```bash
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
| `site.repo_url` | `""` | Repo URL shown in the generated Fumadocs navigation |
| `site.favicon` | `""` | Path to favicon |
| `site.logo` | `""` | Path to logo |

---

## Chatbot

DeepDoc can generate an AI-powered chatbot that answers questions about your codebase using RAG (Retrieval-Augmented Generation). The chatbot indexes your source code, config artifacts, generated docs, and selected repo-authored docs into a FAISS vector store, then serves a FastAPI backend that your Fumadocs site talks to.

### Quick Start

```bash
# 1. Initialize with chatbot enabled
deepdoc init --with-chatbot

# 2. Set chatbot-specific API keys
export DEEPDOC_CHAT_API_KEY=your-answer-model-key
export DEEPDOC_EMBED_API_KEY=your-embedding-model-key

# 3. Generate docs + chatbot indexes
deepdoc generate

# 4. Serve docs + chatbot backend locally
deepdoc serve
```

`deepdoc serve` auto-starts the chatbot backend alongside the Fumadocs site. The backend port is deterministically assigned from your repo path (range 8100–8799) unless you set an explicit `base_url`.
### use this ready to go config 
```
deepdoc config set llm.provider azure                                            
deepdoc config set llm.model azure/gpt-4.1
deepdoc config set llm.api_key_env AZURE_OPENAI_API_KEY
deepdoc config set llm.base_url https://aiservices-orizn.openai.azure.com/

deepdoc config set chatbot.enabled true

deepdoc config set chatbot.answer.api_key_env AZURE_OPENAI_API_KEY
deepdoc config set chatbot.answer.base_url https://aiservices-orizn.openai.azure.com/
deepdoc config set chatbot.answer.api_version 2024-02-15-preview
deepdoc config set chatbot.answer.model azure/gpt-4.1

deepdoc config set chatbot.embeddings.api_key_env AZURE_EMBEDDING_API_KEY
deepdoc config set chatbot.embeddings.base_url https://prod-chatbot-1.cognitiveservices.azure.com/
deepdoc config set chatbot.embeddings.api_version 2024-12-01-preview
deepdoc config set chatbot.embeddings.model azure/text-embedding-3-small
```

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

  embeddings:                                 # LLM used for embedding code/docs
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
    max_prompt_chars: 200000
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

| Key | Default | Description |
|-----|---------|-------------|
| **General** | | |
| `chatbot.enabled` | `false` | Enable chatbot indexing and backend |
| `chatbot.index_dir` | `.deepdoc/chatbot` | Directory for vector indexes and chunk data |
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
| **Embeddings LLM** | | |
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
| `chatbot.retrieval.max_prompt_chars` | `200000` | Total character budget for the assembled prompt |
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

### Chatbot Provider Examples

The chatbot's `answer` and `embeddings` sections are configured independently from the main `llm` section, so you can use different providers for doc generation vs. chatbot.

**Azure (default):**

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
| **Doc summary chunks** | Generated documentation pages | First sections extracted from each generated MDX page |
| **Doc full chunks** | Generated documentation pages | Section-level chunks from the full generated MDX pages |
| **Repo doc chunks** | Repo-authored docs such as `README.md`, `docs/`, design notes, and notebooks | Raw repo documentation kept separate from generated pages |
| **Relationship chunks** | Imports, symbols, call graph, and graph-neighbor summaries | Lightweight graph-style retrieval context |

`deepdoc update` incrementally syncs the chatbot indexes from the same commit-based update run — only changed files, repo-doc candidates, and regenerated doc pages are re-indexed.

### Chatbot Query Pipeline

When a user asks a question, the backend runs a multi-step retrieval pipeline:

1. **Query expansion** — The LLM generates up to 3 alternative search queries to improve recall.
2. **Embedding** — All queries are embedded using the configured embedding model.
3. **Hybrid retrieval** — FAISS similarity search and exact-match lexical search both gather candidates from each corpus.
4. **Follow-up retrieval** — The backend can derive focused second-pass searches and pull linked files/docs via graph-neighbor expansion.
5. **Chunk stitching** — Exact-match code hits can pull adjacent code windows from the same file so larger implementations survive chunk boundaries.
6. **Reranking** — The LLM scores and reranks the retrieved chunks for relevance.
7. **Prompt assembly** — Query-type-aware budgets reserve space for the most important evidence types within the character budget.
8. **Answer generation** — The answer LLM produces a grounded response with code, artifact, doc, repo-doc, relationship, and live-fallback citations when used.

`POST /deep-research` uses the same indexed corpora first, but it can also inspect a small bounded set of live repo files when exact-match evidence is missing from the index. This fallback respects the repo's exclude rules, skips oversized/binary files, and is only used in deep research mode.

### Chatbot API Endpoints

The generated `chatbot_backend/` exposes two endpoints:

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

### Deploying the Chatbot

For local development, `deepdoc serve` handles everything automatically. For production:

1. Deploy the Fumadocs static site (`site/out/`) to any static host.
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
| `endpoint_ref` | One generated page per concrete API endpoint |
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
    - Create nested endpoint reference pages under endpoint families
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
    └── out/                    # Static export after `deepdoc deploy`
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
          deepdoc update --deploy

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

---

## Releasing

DeepDoc now supports automated releases through GitHub Actions.

### What happens automatically

When you push to `main`, the release workflow checks the version in `pyproject.toml`.
If that version does not already have a matching Git tag like `v0.1.1`, GitHub Actions will:

- build the package
- publish it to PyPI
- create the Git tag
- create a GitHub Release and attach the built files
- use the matching section from `CHANGELOG.md` as the release notes when present

### Your release flow

1. Update `version = "..."` in `pyproject.toml`
2. Update `__version__ = "..."` in `deepdoc/__init__.py`
3. Add a matching section to `CHANGELOG.md`
4. Commit your changes
5. Push to `main`

That is it. You do not need to manually create tags or GitHub Releases anymore.

### Changelog format

The release workflow looks for a section in `CHANGELOG.md` that matches the version in `pyproject.toml`.
These heading styles all work:

- `## 0.1.2`
- `## [0.1.2]`
- `## v0.1.2`
- `## [0.1.2] - 2026-04-03`

Example:

```md
## [0.1.2] - 2026-04-03

- Added automated GitHub releases
- Improved PyPI metadata
- Documented `deepdoc[chatbot]` installation
```

If the matching version section is missing, GitHub falls back to auto-generated release notes.

### One-time setup

1. On PyPI, open the `deepdoc` project
2. Go to `Publishing`
3. Add a Trusted Publisher for GitHub Actions with:
   - owner: `tss-pranavkumar`
   - repository: `deepdoc`
   - workflow filename: `release.yml`
   - environment name: `pypi`
4. In GitHub, open Settings → Actions → General
5. Set Workflow permissions to `Read and write permissions`

After that, every new version pushed to `main` can publish without a PyPI token.

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
- Git (for `deepdoc update` and `deepdoc deploy`)
- An LLM API key (or Ollama running locally)

---

## License

MIT
