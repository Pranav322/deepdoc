"""Chatbot configuration helpers."""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_CHATBOT_CONFIG: dict[str, Any] = {
    "enabled": False,
    "index_dir": ".codewiki/chatbot",
    "backend": {
        "base_url": "http://127.0.0.1:8001",
        "allowed_origins": [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
    },
    "answer": {
        "provider": "azure",
        "model": "azure/gpt-4o-mini",
        "api_key_env": "CODEWIKI_CHAT_API_KEY",
        "base_url": "",
        "api_version": "",
        "temperature": 0.1,
        "max_tokens": 1200,
    },
    "embeddings": {
        "provider": "azure",
        "model": "azure/text-embedding-3-large",
        "api_key_env": "CODEWIKI_EMBED_API_KEY",
        "base_url": "",
        "api_version": "",
        "batch_size": 24,
    },
    "vector_store": {
        "kind": "faiss",
    },
    "retrieval": {
        "top_k_code": 8,
        "top_k_artifact": 4,
        "top_k_docs": 3,
        "max_prompt_code_chunks": 6,
        "max_prompt_artifact_chunks": 3,
        "max_prompt_doc_chunks": 2,
        "max_prompt_chars": 200000,
        "query_expansion": True,
        "expansion_max_queries": 3,
        "rerank": True,
        "rerank_candidate_limit": 20,
    },
    "chunking": {
        "code_chunk_lines": 120,
        "code_chunk_overlap": 20,
        "artifact_chunk_lines": 140,
        "artifact_chunk_overlap": 20,
        "max_doc_summary_chunks_per_page": 2,
        "max_doc_summary_chars": 1800,
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def get_chatbot_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    return _deep_merge(DEFAULT_CHATBOT_CONFIG, cfg.get("chatbot", {}))


def chatbot_enabled(cfg: dict[str, Any]) -> bool:
    return bool(get_chatbot_cfg(cfg).get("enabled"))


def chatbot_index_dir(repo_root: Path, cfg: dict[str, Any]) -> Path:
    chatbot_cfg = get_chatbot_cfg(cfg)
    return repo_root / chatbot_cfg.get("index_dir", DEFAULT_CHATBOT_CONFIG["index_dir"])


def chatbot_backend_base_url(cfg: dict[str, Any]) -> str:
    chatbot_cfg = get_chatbot_cfg(cfg)
    return chatbot_cfg.get("backend", {}).get("base_url", "http://127.0.0.1:8001")


def chatbot_backend_port(cfg: dict[str, Any]) -> int:
    parsed = urlparse(chatbot_backend_base_url(cfg))
    return parsed.port or 8001


def chatbot_allowed_origins(cfg: dict[str, Any]) -> list[str]:
    chatbot_cfg = get_chatbot_cfg(cfg)
    backend_cfg = chatbot_cfg.get("backend", {})
    origins = backend_cfg.get("allowed_origins", [])
    return origins if isinstance(origins, list) else []


def resolve_service_api_key(service_cfg: dict[str, Any]) -> str | None:
    env_var = service_cfg.get("api_key_env", "")
    return os.environ.get(env_var) if env_var else None


def service_model_identity(service_cfg: dict[str, Any]) -> str:
    return "|".join(
        [
            service_cfg.get("provider", ""),
            service_cfg.get("model", ""),
            service_cfg.get("base_url", ""),
            service_cfg.get("api_version", ""),
        ]
    )
