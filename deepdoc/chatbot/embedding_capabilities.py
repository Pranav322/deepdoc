"""Embedding input capabilities and deterministic local fitting."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
from typing import Any

from ..llm.litellm_compat import prepare_litellm
from .types import ChunkRecord


class EmbeddingCapabilityError(ValueError):
    """Embedding input capacity is unknown or cannot fit essential content."""


@dataclass(frozen=True)
class EmbeddingCapabilities:
    backend: str
    model: str
    capability_model: str
    max_input_tokens: int
    source: str


_FASTEMBED_MAX_INPUT_TOKENS = {
    "nomic-ai/nomic-embed-text-v1.5": 8192,
    "nomic-ai/nomic-embed-text-v1": 8192,
    "BAAI/bge-m3": 8192,
    "BAAI/bge-large-en-v1.5": 512,
    "BAAI/bge-base-en-v1.5": 512,
    "BAAI/bge-small-en-v1.5": 512,
    "sentence-transformers/all-MiniLM-L6-v2": 256,
}


def _configured_limit(value: Any) -> int | None:
    if value is None or (
        isinstance(value, str) and value.strip().lower() in {"", "auto", "null", "none"}
    ):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise EmbeddingCapabilityError(
            "chatbot.embeddings.max_input_tokens must be a positive integer or 'auto'."
        ) from exc
    if result <= 0:
        raise EmbeddingCapabilityError(
            "chatbot.embeddings.max_input_tokens must be a positive integer or 'auto'."
        )
    return result


def resolve_embedding_capabilities(cfg: dict[str, Any]) -> EmbeddingCapabilities:
    """Resolve local or hosted embedding input capacity without provider I/O."""
    backend = str(cfg.get("backend") or "fastembed").strip().lower()
    model = str(
        cfg.get("fastembed_model") if backend == "fastembed" else cfg.get("model") or ""
    ).strip()
    base_model = str(cfg.get("base_model") or "").strip()
    explicit_limit = _configured_limit(cfg.get("max_input_tokens"))
    if explicit_limit is not None:
        return EmbeddingCapabilities(
            backend=backend,
            model=model,
            capability_model=base_model or model,
            max_input_tokens=explicit_limit,
            source="configured",
        )
    if backend == "fastembed":
        limit = _FASTEMBED_MAX_INPUT_TOKENS.get(model)
        if limit is None:
            raise EmbeddingCapabilityError(
                f"Could not resolve embedding input capacity for local model {model!r}. "
                "Set chatbot.embeddings.max_input_tokens explicitly."
            )
        return EmbeddingCapabilities(
            backend=backend,
            model=model,
            capability_model=model,
            max_input_tokens=limit,
            source="fastembed_registry",
        )

    capability_model = base_model or model
    try:
        info = prepare_litellm().get_model_info(capability_model)
        limit = int(info.get("max_input_tokens") or info.get("max_tokens"))
    except Exception as exc:
        raise EmbeddingCapabilityError(
            f"Could not resolve embedding input capacity for {model!r}. Set "
            "chatbot.embeddings.base_model to a LiteLLM-known model or set "
            "chatbot.embeddings.max_input_tokens explicitly."
        ) from exc
    return EmbeddingCapabilities(
        backend=backend,
        model=model,
        capability_model=capability_model,
        max_input_tokens=limit,
        source="litellm_base_model" if base_model else "litellm",
    )


def embedding_policy_fingerprint(capabilities: EmbeddingCapabilities) -> str:
    payload = {
        "version": 1,
        "backend": capabilities.backend,
        "model": capabilities.model,
        "capability_model": capabilities.capability_model,
        "max_input_tokens": capabilities.max_input_tokens,
        "source": capabilities.source,
        "fit_algorithm": "line-prefix-v1",
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _count_tokens(text: str, capabilities: EmbeddingCapabilities) -> int:
    try:
        return max(
            1,
            int(
                prepare_litellm().token_counter(
                    model=capabilities.capability_model,
                    text=text,
                )
            ),
        )
    except Exception:
        # Conservative fallback when no model tokenizer is available.
        return max(1, math.ceil(len(text) / 3))


def fit_embedding_text(text: str, capabilities: EmbeddingCapabilities) -> str:
    """Fit one embedding input at line boundaries without hidden char caps."""
    if _count_tokens(text, capabilities) <= capabilities.max_input_tokens:
        return text
    marker = "\n... [truncated for embedding]"
    lines = text.splitlines(keepends=True)
    if not lines:
        raise EmbeddingCapabilityError("Embedding input cannot be represented safely.")
    low, high, best = 0, len(lines) - 1, ""
    while low <= high:
        middle = (low + high) // 2
        candidate = "".join(lines[: middle + 1]).rstrip() + marker
        if _count_tokens(candidate, capabilities) <= capabilities.max_input_tokens:
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    if not best:
        char_budget = max(1, capabilities.max_input_tokens * 3 - len(marker))
        return text[:char_budget].rstrip() + marker
    return best


def fit_embedding_records(
    records: list[ChunkRecord], capabilities: EmbeddingCapabilities
) -> list[ChunkRecord]:
    """Persist exactly the text represented by embeddings."""
    fitted: list[ChunkRecord] = []
    for record in records:
        text = fit_embedding_text(record.text, capabilities)
        if text == record.text:
            fitted.append(record)
            continue
        chunk_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        fitted.append(
            replace(
                record,
                text=text,
                chunk_hash=chunk_hash,
                chunk_id=record.chunk_id.replace(
                    record.chunk_hash[:8], chunk_hash[:8]
                ),
            )
        )
    return fitted
