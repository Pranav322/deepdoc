"""Config management — reads/writes .deepdoc.yaml in the repo root."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG: dict[str, Any] = {
    "project_name": "",
    "description": "",
    "output_dir": "deepdoc-docs",
    "site_dir": "deepdoc-site",
    "max_pages": 0,  # 0 = no cap, let LLM decide; set a number to limit
    # ── Generation mode ──────────────────────────────────────────────────
    "generation_mode": "feature_buckets",  # "feature_buckets" (v2) | "file_centric" (v1 legacy)
    # ── Giant file thresholds ────────────────────────────────────────────
    "large_file_lines": 500,  # files above this get tiered summarization
    "giant_file_lines": 2000,  # files above this get LLM-based feature clustering
    "source_context_budget": 200000,  # raw-source char budget before compressed evidence cards kick in
    "decompose_threshold": 7,  # buckets with 7+ files trigger decomposition consideration
    "planning_unit_max_files_seed": 0,  # 0 = no cap; else an advisory ceiling on the first split-seed size for an over-budget planning unit (bound_planning_unit's exact-token gate is what actually proves each part fits, this only shapes the initial guess)
    "consolidation_similarity_threshold": 0.55,  # Jaccard threshold for merging near-duplicate buckets
    "max_files_per_bucket": 25,  # buckets above this are split by the decomposition pass
    "max_flow_files": 45,  # cap on files pulled into a single flow's context
    "max_flow_symbols": 80,  # cap on symbols pulled into a single flow's context
    "database_doc_mode": "overview_plus_groups",
    "database_group_model_cap": 12,
    "database_group_file_cap": 8,
    "runtime_doc_mode": "dedicated_pages",
    "quality": {
        "strict": False,
    },
    "scan": {
        "max_workers": 8,
        "max_source_bytes": 1_000_000,
        "max_repo_files": 0,       # 0 = unlimited; warn when exceeded
        "timeout_seconds": 0,      # 0 = unlimited; abort scan with partial results when exceeded
        "build_repo_model": True,
        "persistent_index": True,
    },
    # ── Concurrency ─────────────────────────────────────────────────────
    "batch_size": 10,  # pages submitted per generation batch
    "max_parallel_workers": 6,  # concurrent LLM calls for generation, clustering, and decompose
    "rate_limit_pause": 0.5,  # seconds to pause between generation batches (0 = no pause)
    "manifest_checkpoint_pages": 10,
    "manifest_checkpoint_seconds": 15.0,
    # ── Integration detection ────────────────────────────────────────────
    "integration_detection": "auto",  # "auto" | "off"
    # ── Page type toggles ────────────────────────────────────────────────
    "consistency_pass": True,  # post-generation LLM pass adding cross-page "See also" links
    "include_endpoint_pages": True,
    "include_integration_pages": True,
    # ── LLM ──────────────────────────────────────────────────────────────
    "llm": {
        "provider": "",  # must be set in .deepdoc.yaml — run: deepdoc init
        "model": "",
        "api_key_env": "",
        "api_version": "",  # Azure deployments; written by `deepdoc init --provider azure`
        "base_url": None,
        "max_tokens": None,
        "temperature": 0.2,
        "base_model": None,
        "context_window_tokens": None,
        "output_reserve_tokens": None,
        "rate_limits": {
            "max_concurrency": 6,
            "requests_per_minute": 60,
            "tokens_per_minute": 250000,
            "adaptive_backoff": True,
        },
    },
    # Descriptive only — fills the "languages" sentence in generation prompts.
    # Does NOT gate or broaden scanning; the scanner's supported-extension set
    # (python/javascript/typescript/go/php/vue) is fixed and independent of
    # this list. Adding a language here does not make DeepDoc parse it.
    "languages": ["python", "javascript", "typescript", "go", "php", "vue"],
    # Descriptive only, like `languages` above — names the frameworks in the
    # generation prompt. Does not gate or broaden detection.
    "frameworks": [],
    "include": [],  # glob patterns — empty = everything
    "services": [],  # optional monorepo service roots, e.g. ["services/auth", "apps/api"]
    # ── Endpoint grouping ────────────────────────────────────────────────
    # Override or extend endpoint domain grouping used when classifying unmatched
    # endpoints into fallback pages. Keys are bucket names, values are path-segment
    # keywords to match. Merged on top of the built-in keyword list.
    # Example:
    #   tss-money: [tssmoney, wallet, cashback]
    #   catalog: [product, item, sku, category]
    "endpoint_groups": {},
    "exclude": [
        # ── Git / VCS ──────────────────────────────────────────────────────
        ".git",
        ".svn",
        ".hg",
        # ── IDE / Editor ───────────────────────────────────────────────────
        ".idea",
        ".vscode",
        "*.swp",
        "*.swo",
        ".DS_Store",
        "Thumbs.db",
        # ── Python ─────────────────────────────────────────────────────────
        "__pycache__",
        "*.pyc",
        "*.pyo",
        "*.pyd",
        ".venv",
        "venv",
        "*venv*",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "*.egg-info",
        ".eggs",
        "htmlcov",
        # ── JavaScript / TypeScript ────────────────────────────────────────
        "node_modules",
        "*.min.js",
        "*.bundle.js",
        "*.map",
        ".nyc_output",
        ".eslintcache",
        ".cache",
        ".parcel-cache",
        ".turbo",
        "storybook-static",
        # ── Vue / Nuxt ─────────────────────────────────────────────────────
        ".nuxt",
        ".output",
        # ── React / Next.js ────────────────────────────────────────────────
        ".next",
        # ── Go ─────────────────────────────────────────────────────────────
        "*.sum",
        "*.exe",
        "*.test",
        "*.out",
        # ── PHP / Laravel ──────────────────────────────────────────────────
        "vendor",
        ".phpunit.cache",
        ".php-cs-fixer.cache",
        "storage/framework",
        "bootstrap/cache",
        # ── Django ─────────────────────────────────────────────────────────
        "static",
        "staticfiles",
        "media",
        # ── General build / output ─────────────────────────────────────────
        "dist",
        "build",
        "bin",
        "out",
        "target",
        "coverage",
        "tmp",
        # ── Environment / secrets ──────────────────────────────────────────
        ".env",
        ".env.*",
        "*.local",
        # ── Logs / data ────────────────────────────────────────────────────
        "logs",
        "*.log",
        "*.sql",
        "*.lock",
        # ── Infra / containers ─────────────────────────────────────────────
        ".docker",
        ".terraform",
        # ── DeepDoc generated outputs (never scan our own scaffold/state) ───
        ".deepdoc",
        # Static build output from repository documentation systems is derived
        # content, not authored documentation input.
        "site",
        "chatbot_backend",
        # ── Project-specific ───────────────────────────────────────────────
        # Add project-specific excludes here in .deepdoc.yaml under the "exclude:" key.
    ],
    # ── Generated site appearance ──────────────────────────────────────────
    # Everything here is applied by `deepdoc serve` / `deepdoc deploy` without
    # regenerating any documentation — no LLM calls, no repository scan. Every
    # key is optional; an empty value means "use the built-in default", so an
    # existing .deepdoc.yaml renders exactly as before.
    "site": {
        "repo_url": "",  # e.g. https://github.com/acme/widgets — adds a repo link
        "edit_branch": "main",  # branch used by the "edit this page" link
        "edit_path_prefix": "",  # path inside the repo the docs live under
        "favicon": "",  # repo-relative image, copied into <site_dir>/public/
        "logo": "",
        "logo_dark": "",  # optional separate logo for dark mode
        "colors": {
            "primary": "",
            "light": "",  # lighter shade — used as the dark-mode accent
            "dark": "",  # darker shade — used for link hover
        },
        "theme": {
            # One of the built-in palettes, or "" for DeepDoc's own.
            # neutral | black | vitepress | ocean | catppuccin | dusk | purple
            "preset": "",
            # Raw Fumadocs design-token overrides — the final word, and the
            # escape hatch for anything the named keys above don't cover.
            # Keys are given without the `--color-fd-` prefix, e.g.
            #   light: {background: "#ffffff", border: "#e5e5e5"}
            "tokens": {
                "light": {},
                "dark": {},
            },
            # Google Font family names. Empty means no webfont is loaded and no
            # external request is made — the site uses system stacks.
            "fonts": {
                "sans": "",
                "mono": "",
            },
            # Any Shiki theme name.
            "code_theme": {
                "light": "github-light",
                "dark": "github-dark",
            },
        },
        "chrome": {
            "sidebar": True,
            "sidebar_default_open_level": 1,
            "sidebar_collapsible": True,
            "toc": True,
            "toc_style": "clerk",  # clerk | normal
            "toc_depth": [2, 3],  # heading levels shown in the table of contents
            "breadcrumb": True,
            "page_footer": True,  # previous / next page links
            "edit_link": False,  # requires repo_url
            "last_update": True,
            "theme_switch": True,
            "search": True,
            "generated_meta": True,  # commit-sha + date strip in the sidebar footer
            "links": [],  # extra navbar links: [{text, url}]
        },
        "nav": {
            "sections": [],  # explicit order of top-level sections, by title
            "pin": [],  # page slugs hoisted above all sections
            "hide": [],  # page slugs removed from the sidebar (still reachable by URL)
            "rename": {},  # {slug: "New Title"} — also matches section titles
            "extra": [],  # hand-written pages / external links:
            #   - {slug: runbook, title: "Runbook", section: "Guides"}
            #   - {url: "https://...", title: "Releases"}
        },
        # Overrides for built-in UI strings (Fumadocs `Translations` keys plus
        # DeepDoc's callout names), e.g. {toc: "On this page", note: "Heads up"}.
        "labels": {},
    },
    "compatibility": {
        "deprecated_version_warning": {
            "enabled": True,
        },
    },
    "chatbot": {
        "enabled": False,
        "index_dir": ".deepdoc/chatbot",
        "backend": {
            "base_url": "",
            "allowed_origins": [
                "http://localhost:3000",
                "http://127.0.0.1:3000",
            ],
        },
        "answer": {
            "provider": "",
            "model": "",
            "api_key_env": "DEEPDOC_CHAT_API_KEY",
            "base_url": "",
            "api_version": "",
            "temperature": 0.1,
            "max_tokens": 24000,
            "base_model": None,
            "context_window_tokens": None,
            "output_reserve_tokens": None,
            "continuation_retries": 2,
            "continuation_context_chars": 12000,
        },
        "embeddings": {
            "backend": "fastembed",
            # Local model — runs offline, no API key. This is an explicit choice; swap to any model from:
            # https://qdrant.github.io/fastembed/examples/Supported_Models/
            "fastembed_model": "nomic-ai/nomic-embed-text-v1.5",
            "fastembed_batch_size": 4,
            "base_model": None,
            "max_input_tokens": None,
            "provider": "",
            "model": "",
            "api_key_env": "DEEPDOC_EMBED_API_KEY",
            "base_url": "",
            "api_version": "",
            "batch_size": 24,
        },
        "indexing": {
            "include_repo_docs": True,
            "include_tests": False,
            "repo_doc_globs": [],
            "exclude_globs": [],
            "max_file_bytes": 250000,
            "max_repo_doc_chars": 12000,
        },
        "retrieval": {
            "top_k_code": 15,
            "top_k_artifact": 8,
            "top_k_docs": 6,
            "top_k_relationship": 8,
            "candidate_top_k_code": 30,
            "candidate_top_k_artifact": 16,
            "candidate_top_k_docs": 12,
            "candidate_top_k_relationship": 12,
            "max_prompt_code_chunks": 12,
            "max_prompt_artifact_chunks": 6,
            "max_prompt_doc_chunks": 6,
            "max_prompt_relationship_chunks": 6,
            "max_prompt_chars": 120000,
            "fast_mode_use_llm_retrieval_steps": False,
            "fast_mode_iterative_retrieval": False,
            "fast_mode_max_prompt_chars": 90000,
            "deep_mode_max_prompt_chars": 180000,
            "deep_top_k_code": 16,
            "deep_top_k_relationship": 12,
            "deep_top_k_docs": 4,
            "deep_file_inventory_limit": 18,
            "lexical_retrieval": True,
            "lexical_candidate_limit": 24,
            "query_expansion": True,
            "expansion_max_queries": 3,
            "iterative_retrieval": True,
            "iterative_max_followup_queries": 2,
            "graph_neighbor_expansion": True,
            "graph_neighbor_max_files": 6,
            "graph_neighbor_code_chunks_per_file": 2,
            "graph_neighbor_artifact_chunks_per_file": 1,
            "graph_neighbor_relationship_chunks_per_file": 2,
            "graph_neighbor_max_docs": 4,
            "rerank": True,
            "rerank_candidate_limit": 32,
            "rerank_candidate_limit_per_kind": 8,
            "rerank_preview_chars": 450,
            "stitch_adjacent_code_chunks": True,
            "stitch_max_adjacent_chunks": 2,
            "deep_research_live_fallback": True,
            "live_fallback_max_files": 6,
            "live_fallback_max_per_file": 2,
            "live_fallback_context_lines": 12,
        },
        "chunking": {
            "code_chunk_lines": 120,
            "code_chunk_overlap": 20,
            "artifact_chunk_lines": 140,
            "artifact_chunk_overlap": 20,
            "max_doc_summary_chunks_per_page": 4,
            "max_doc_summary_chars": 4000,
        },
    },
}

CONFIG_FILE = ".deepdoc.yaml"


def find_config(start: Path | None = None) -> Path | None:
    """Walk up directory tree to find .deepdoc.yaml."""
    cwd = start or Path.cwd()
    for directory in [cwd, *cwd.parents]:
        candidate = directory / CONFIG_FILE
        if candidate.exists():
            return candidate
    return None


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load config, merging with defaults."""
    cfg_path = path or find_config()
    if cfg_path is None:
        return dict(DEFAULT_CONFIG)

    with open(cfg_path) as f:
        user_cfg = yaml.safe_load(f) or {}

    return _deep_merge(dict(DEFAULT_CONFIG), user_cfg)


def save_config(cfg: dict[str, Any], path: Path) -> None:
    with open(path, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def resolve_api_key(cfg: dict[str, Any]) -> str | None:
    env_var = cfg["llm"].get("api_key_env", "")
    return os.environ.get(env_var) if env_var else None
