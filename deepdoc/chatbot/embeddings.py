"""Cloud-first embedding provider for the DeepDoc chatbot.

Supports two backends:
  - "litellm":  Cloud provider embeddings via litellm (OpenAI, Azure, etc.).
                Default. Recommended for code documentation due to large token context.
                Uses text-embedding-3-small (8,192 token limit).
  - "fastembed": Downloads model once, runs 100% in RAM, zero API calls.
                 Local alternative. Requires model with >= 2048 token context.
                 Recommended: nomic-ai/nomic-embed-text-v1.5 (8192 tokens, 768-dim).
                 Do NOT use bge-small/base/large (512 token limit for code docs).

The litellm backend is strongly preferred for code documentation because:
  - Large token context (text-embedding-3-small has 8,192 tokens)
  - Handles long code chunks without truncation
  - Production-grade quality for semantic search
  - Available on major cloud providers (OpenAI, Azure, etc.)

Use fastembed only if you need local-only embeddings. Ensure the model has >= 2048 token context.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

try:
    import numpy as np
except ImportError:  # pragma: no cover - exercised in lean test envs
    np = None

logger = logging.getLogger(__name__)

_fastembed_model_cache: dict[str, Any] = {}
_FASTEMBED_CHAR_LIMITS: dict[str, int | None] = {
    "nomic-ai/nomic-embed-text-v1.5": None,
    "nomic-ai/nomic-embed-text-v1": None,
    "BAAI/bge-m3": None,
    "BAAI/bge-large-en-v1.5": 4000,
    "BAAI/bge-base-en-v1.5": 4000,
    "BAAI/bge-small-en-v1.5": 3000,
    "sentence-transformers/all-MiniLM-L6-v2": 3000,
}
_FASTEMBED_CONSERVATIVE_BATCH_MODELS = {
    "nomic-ai/nomic-embed-text-v1.5",
    "nomic-ai/nomic-embed-text-v1",
}


def get_embeddings(
    texts: list[str],
    backend: str = "litellm",
    model: str = "nomic-ai/nomic-embed-text-v1.5",
    batch_size: int = 32,
    # litellm kwargs (only used when backend="litellm")
    litellm_model: str = "text-embedding-3-small",
    litellm_kwargs: dict | None = None,
) -> np.ndarray:
    """Embed a list of texts and return a float32 numpy array of shape (N, D).

    Vectors are L2-normalised so cosine similarity == inner product.
    """
    if not texts:
        if np is None:
            return []
        return np.empty(
            (0, embedding_dim(backend=backend, model=model)), dtype=np.float32
        )

    if backend == "fastembed":
        return _fastembed_embed(texts, model=model, batch_size=batch_size)
    elif backend == "litellm":
        return _litellm_embed(
            texts, model=litellm_model, extra_kwargs=litellm_kwargs or {}
        )
    else:
        raise ValueError(
            f"Unknown embedding backend: {backend!r}. Use 'fastembed' or 'litellm'."
        )


def embedding_dim(
    backend: str = "litellm", model: str = "nomic-ai/nomic-embed-text-v1.5"
) -> int:
    """Return the embedding dimension for the given backend/model."""
    if backend == "fastembed":
        # Known dimensions for common fastembed models
        _DIMS = {
            "nomic-ai/nomic-embed-text-v1.5": 768,  # 8192 token context, Matryoshka support — RECOMMENDED
            "nomic-ai/nomic-embed-text-v1": 768,  # 8192 token context — v1.5 preferred
            "BAAI/bge-m3": 1024,  # 8192 token context, multilingual
            "BAAI/bge-large-en-v1.5": 1024,  # 512 token limit — NOT recommended for code
            "BAAI/bge-base-en-v1.5": 768,  # 512 token limit — NOT recommended for code
            "BAAI/bge-small-en-v1.5": 384,  # 512 token limit — NOT recommended for code
            "sentence-transformers/all-MiniLM-L6-v2": 384,  # 512 token limit — NOT recommended for code
        }
        return _DIMS.get(model, 768)  # default 768 (nomic)
    elif backend == "litellm":
        return 1536  # text-embedding-3-small default
    return 768


# ── fastembed backend ──────────────────────────────────────────────────────────


def _fastembed_embed(
    texts: list[str],
    model: str = "nomic-ai/nomic-embed-text-v1.5",
    batch_size: int = 32,
) -> Any:
    """Embed using fastembed (local model, runs in RAM, zero API calls).

    IMPORTANT: Only use models with >= 2048 token context for code documentation.
    Recommended: "nomic-ai/nomic-embed-text-v1.5" (8192 tokens, 768 dims)
    Do NOT use bge-small/base/large (512 token limit) — they will truncate code chunks.
    """
    try:
        from fastembed import TextEmbedding
    except ImportError:
        raise ImportError(
            "fastembed is not installed. Run: pip install fastembed\n"
            "It downloads a ~130MB model the first time, then runs fully locally."
        )

    if model not in _fastembed_model_cache:
        logger.info(f"[embeddings] Loading fastembed model '{model}' into RAM...")
        cache_dir = _fastembed_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        _fastembed_model_cache[model] = TextEmbedding(
            model_name=model,
            cache_dir=str(cache_dir),
        )
        logger.info(f"[embeddings] Model '{model}' loaded.")

    embed_model = _fastembed_model_cache[model]
    effective_batch_size = _effective_fastembed_batch_size(texts, model, batch_size)
    if effective_batch_size != batch_size:
        logger.warning(
            "[embeddings] Reducing fastembed batch size for '%s' from %s to %s "
            "because long code chunks run significantly slower in large local batches.",
            model,
            batch_size,
            effective_batch_size,
        )

    # fastembed returns a generator; collect in batches
    all_vecs: list[np.ndarray] = []
    for i in range(0, len(texts), effective_batch_size):
        batch = texts[i : i + effective_batch_size]
        batch = [_trim_fastembed_text(t, model) for t in batch]
        vecs = list(embed_model.embed(batch))
        all_vecs.extend(vecs)

    return _normalize_embedding_rows(all_vecs)


def _effective_fastembed_batch_size(
    texts: list[str],
    model: str,
    requested_batch_size: int,
) -> int:
    """Clamp pathological local fastembed batch sizes for long code chunks.

    In practice, nomic fastembed on long code/context chunks can become much
    slower with large local batches than with small ones. Keep user-specified
    settings for short texts, but cap long-context local embedding runs to a
    conservative batch size that completes reliably.
    """
    batch_size = max(int(requested_batch_size or 1), 1)
    if batch_size <= 4 or not texts:
        return batch_size
    if model not in _FASTEMBED_CONSERVATIVE_BATCH_MODELS:
        return batch_size

    max_chars = max(len(text) for text in texts)
    avg_chars = sum(len(text) for text in texts) / max(len(texts), 1)
    if max_chars >= 3000 or avg_chars >= 1200:
        return 4
    return batch_size


def _fastembed_cache_dir() -> Path:
    """Return a stable on-disk cache path for fastembed models."""
    explicit = os.environ.get("FASTEMBED_CACHE_PATH")
    if explicit:
        return Path(explicit).expanduser()

    xdg_cache_home = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache_home:
        return Path(xdg_cache_home).expanduser() / "fastembed"

    return Path.home() / ".cache" / "fastembed"


def _trim_fastembed_text(text: str, model: str) -> str:
    """Trim only when a model is known to be short-context."""
    char_limit = _FASTEMBED_CHAR_LIMITS.get(model)
    if char_limit is None or len(text) <= char_limit:
        return text
    trimmed = text[:char_limit].rstrip()
    return trimmed + "\n... [truncated for embedding]"


# ── litellm backend ────────────────────────────────────────────────────────────


def _litellm_embed(
    texts: list[str],
    model: str = "text-embedding-3-small",
    extra_kwargs: dict | None = None,
) -> Any:
    """Embed using litellm (cloud provider — requires API key configured)."""
    try:
        import litellm
    except ImportError:
        raise ImportError("litellm is not installed.")

    kwargs = extra_kwargs or {}
    batch_size = 512
    all_vecs: list[list[float]] = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = litellm.embedding(model=model, input=batch, **kwargs)
        all_vecs.extend(item["embedding"] for item in response.data)

    return _normalize_embedding_rows(all_vecs)


def _normalize_embedding_rows(rows: list[Any]) -> Any:
    if np is not None:
        arr = np.array(rows, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        return arr / norms

    normalized: list[list[float]] = []
    for row in rows:
        values = [float(value) for value in row]
        norm = sum(value * value for value in values) ** 0.5 or 1.0
        normalized.append([value / norm for value in values])
    return normalized
