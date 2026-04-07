"""Config management — reads/writes .deepdoc.yaml in the repo root."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG: dict[str, Any] = {
    "project_name": "",
    "description": "",
    "output_dir": "docs",
    "site_dir": "site",
    "max_pages": 0,  # 0 = no cap, let LLM decide; set a number to limit
    # ── Generation mode ──────────────────────────────────────────────────
    "generation_mode": "feature_buckets",  # "feature_buckets" (v2) | "file_centric" (v1 legacy)
    # ── Giant file thresholds ────────────────────────────────────────────
    "large_file_lines": 500,  # files above this get tiered summarization
    "giant_file_lines": 2000,  # files above this get LLM-based feature clustering
    "source_context_budget": 200000,  # raw-source char budget before compressed evidence cards kick in
    "decompose_threshold": 7,  # buckets with 7+ files trigger decomposition consideration
    "consolidation_similarity_threshold": 0.55,  # Jaccard threshold for merging near-duplicate buckets
    "database_doc_mode": "overview_plus_groups",
    "database_group_model_cap": 12,
    "database_group_file_cap": 8,
    "runtime_doc_mode": "dedicated_pages",
    # ── Concurrency ─────────────────────────────────────────────────────
    "max_parallel_workers": 6,  # concurrent LLM calls for generation, clustering, and decompose
    "rate_limit_pause": 0.5,  # seconds to pause between generation batches (0 = no pause)
    # ── Integration detection ────────────────────────────────────────────
    "integration_detection": "auto",  # "auto" | "off"
    # ── Page type toggles ────────────────────────────────────────────────
    "include_feature_pages": True,
    "include_endpoint_pages": True,
    "include_integration_pages": True,
    # ── LLM ──────────────────────────────────────────────────────────────
    "llm": {
        "provider": "anthropic",  # anthropic | openai | ollama | any litellm alias
        "model": "claude-3-5-sonnet-20241022",
        "api_key_env": "ANTHROPIC_API_KEY",  # env var that holds the key
        "base_url": None,  # for Ollama / custom endpoints
        "max_tokens": None,  # None = let the model decide (recommended); set a number to cap output
        "temperature": 0.2,
    },
    "languages": ["python", "javascript", "typescript", "go", "php", "vue"],
    "include": [],  # glob patterns — empty = everything
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
        # ── Project-specific ───────────────────────────────────────────────
        "backend-tss-api_v2/backend-tss-api_v2-docs/",
    ],
    "github_pages": {
        "enabled": False,
        "branch": "gh-pages",
        "remote": "origin",
    },
    "site": {
        "repo_url": "",  # shown in top-bar of documentation site
        "favicon": "",
        "logo": "",
        "colors": {
            "primary": "",
            "light": "",
            "dark": "",
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
            "provider": "azure",
            "model": "azure/gpt-4o-mini",
            "api_key_env": "DEEPDOC_CHAT_API_KEY",
            "base_url": "",
            "api_version": "",
            "temperature": 0.1,
            "max_tokens": 24000,
            "continuation_retries": 2,
            "continuation_context_chars": 12000,
        },
        "embeddings": {
            "backend": "litellm",
            "fastembed_model": "nomic-ai/nomic-embed-text-v1.5",
            "fastembed_batch_size": 4,
            "provider": "azure",
            "model": "azure/text-embedding-3-large",
            "api_key_env": "DEEPDOC_EMBED_API_KEY",
            "base_url": "",
            "api_version": "",
            "batch_size": 24,
        },
        "vector_store": {
            "kind": "faiss",
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
            "deep_mode_max_prompt_chars": 140000,
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
            "deep_research_chunk_chars": 3200,
            "deep_research_top_k": 10,
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
