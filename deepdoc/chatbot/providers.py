"""Provider wrappers for chatbot retrieval and answering."""

from __future__ import annotations

from typing import Any

from ..llm.litellm_compat import prepare_litellm
from .chunker import MAX_CHUNK_CHARS
from .settings import get_chatbot_cfg, resolve_service_api_key


class LiteLLMChatClient:
    """Thin wrapper for chat completions."""

    def __init__(self, service_cfg: dict[str, Any]) -> None:
        self.service_cfg = service_cfg

    def complete(self, system: str, user: str) -> str:
        try:
            litellm = prepare_litellm()

            kwargs: dict[str, Any] = {
                "model": self.service_cfg.get("model"),
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": self.service_cfg.get("temperature", 0.1),
            }
            if self.service_cfg.get("max_tokens"):
                kwargs["max_tokens"] = self.service_cfg["max_tokens"]
            if self.service_cfg.get("base_url"):
                kwargs["base_url"] = self.service_cfg["base_url"]
            if self.service_cfg.get("api_version"):
                kwargs["api_version"] = self.service_cfg["api_version"]
            api_key = resolve_service_api_key(self.service_cfg)
            if api_key:
                kwargs["api_key"] = api_key

            response = litellm.completion(**kwargs)
            return response.choices[0].message.content or ""
        except ImportError as exc:
            raise RuntimeError("litellm not installed. Install deepdoc[chatbot].") from exc
        except Exception as exc:
            model = self.service_cfg.get("model", "unknown")
            key_env = self.service_cfg.get("api_key_env", "")
            hint = f" Check env var {key_env}." if key_env else ""
            raise RuntimeError(f"Chat completion failed (model={model}).{hint} {exc}") from exc


class LiteLLMEmbeddingClient:
    """Thin wrapper for embedding calls."""

    def __init__(self, service_cfg: dict[str, Any]) -> None:
        self.service_cfg = service_cfg
        provider = (service_cfg.get("provider") or "").lower()
        default_batch_size = 1 if provider == "azure" else 24
        self.batch_size = service_cfg.get("batch_size", default_batch_size)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        try:
            litellm = prepare_litellm()
            vectors: list[list[float]] = []
            for i in range(0, len(texts), self.batch_size):
                batch = texts[i : i + self.batch_size]
                vectors.extend(self._embed_batch(litellm, batch))
            return vectors
        except ImportError as exc:
            raise RuntimeError("litellm not installed. Install deepdoc[chatbot].") from exc
        except Exception as exc:
            model = self.service_cfg.get("model", "unknown")
            key_env = self.service_cfg.get("api_key_env", "")
            hint = f" Check env var {key_env}." if key_env else ""
            raise RuntimeError(f"Embedding request failed (model={model}).{hint} {exc}") from exc

    def _embed_batch(self, litellm: Any, batch: list[str]) -> list[list[float]]:
        try:
            response = litellm.embedding(**self._embedding_kwargs(batch))
            return [item["embedding"] for item in response.data]
        except Exception as exc:
            if self._is_context_window_error(exc):
                if len(batch) > 1:
                    mid = max(len(batch) // 2, 1)
                    return self._embed_batch(litellm, batch[:mid]) + self._embed_batch(litellm, batch[mid:])
                trimmed = self._trim_text_for_retry(batch[0])
                if trimmed != batch[0]:
                    return self._embed_batch(litellm, [trimmed])
            raise

    def _embedding_kwargs(self, batch: list[str]) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.service_cfg.get("model"),
            "input": batch,
        }
        if self.service_cfg.get("base_url"):
            kwargs["api_base"] = self.service_cfg["base_url"]
        if self.service_cfg.get("api_version"):
            kwargs["api_version"] = self.service_cfg["api_version"]
        if self.service_cfg.get("provider") == "azure":
            kwargs["api_type"] = "azure"
        api_key = resolve_service_api_key(self.service_cfg)
        if api_key:
            kwargs["api_key"] = api_key
        return kwargs

    def _is_context_window_error(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return (
            "contextwindow" in message
            or "maximum context length" in message
            or "requested" in message and "tokens" in message
        )

    def _trim_text_for_retry(self, text: str) -> str:
        if len(text) <= 1200:
            return text
        provider = (self.service_cfg.get("provider") or "").lower()
        if provider == "azure":
            safe_cap = 2800
            budget = min(safe_cap, max(int(len(text) * 0.5), 1200))
        else:
            budget = min(MAX_CHUNK_CHARS, max(int(len(text) * 0.75), 1200))
        if budget >= len(text):
            return text
        trimmed = text[:budget].rstrip()
        return trimmed + "\n... [truncated for embedding]"


def build_chat_client(cfg: dict[str, Any]) -> LiteLLMChatClient:
    return LiteLLMChatClient(get_chatbot_cfg(cfg).get("answer", {}))


def build_embedding_client(cfg: dict[str, Any]) -> LiteLLMEmbeddingClient:
    return LiteLLMEmbeddingClient(get_chatbot_cfg(cfg).get("embeddings", {}))
