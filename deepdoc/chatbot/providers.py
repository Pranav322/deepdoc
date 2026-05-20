"""Provider wrappers for chatbot retrieval and answering."""

from __future__ import annotations

from typing import Any, Iterator

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
            raise RuntimeError(
                "litellm not installed. Install deepdoc[chatbot]."
            ) from exc
        except Exception as exc:
            model = self.service_cfg.get("model", "unknown")
            key_env = self.service_cfg.get("api_key_env", "")
            hint = f" Check env var {key_env}." if key_env else ""
            raise RuntimeError(
                f"Chat completion failed (model={model}).{hint} {exc}"
            ) from exc

    def complete_stream(self, system: str, user: str) -> Iterator[str]:
        try:
            litellm = prepare_litellm()

            kwargs: dict[str, Any] = {
                "model": self.service_cfg.get("model"),
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": self.service_cfg.get("temperature", 0.1),
                "stream": True,
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

            for chunk in litellm.completion(**kwargs):
                delta = chunk.choices[0].delta
                text = getattr(delta, "content", None) or ""
                if text:
                    yield text
        except ImportError as exc:
            raise RuntimeError(
                "litellm not installed. Install deepdoc[chatbot]."
            ) from exc
        except Exception as exc:
            model = self.service_cfg.get("model", "unknown")
            key_env = self.service_cfg.get("api_key_env", "")
            hint = f" Check env var {key_env}." if key_env else ""
            raise RuntimeError(
                f"Chat completion (stream) failed (model={model}).{hint} {exc}"
            ) from exc


class LiteLLMEmbeddingClient:
    """Thin wrapper for embedding calls."""

    def __init__(self, service_cfg: dict[str, Any]) -> None:
        self.service_cfg = service_cfg
        provider = (service_cfg.get("provider") or "").lower()
        model = (service_cfg.get("model") or "").lower()
        default_batch_size = (
            1 if provider == "azure" or model.startswith("azure/") else 24
        )
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
            raise RuntimeError(
                "litellm not installed. Install deepdoc[chatbot]."
            ) from exc
        except Exception as exc:
            model = self.service_cfg.get("model", "unknown")
            key_env = self.service_cfg.get("api_key_env", "")
            hint = f" Check env var {key_env}." if key_env else ""
            raise RuntimeError(
                f"Embedding request failed (model={model}).{hint} {exc}"
            ) from exc

    def _embed_batch(self, litellm: Any, batch: list[str]) -> list[list[float]]:
        try:
            response = litellm.embedding(**self._embedding_kwargs(batch))
            return [item["embedding"] for item in response.data]
        except Exception as exc:
            if self._is_context_window_error(exc):
                if len(batch) > 1:
                    mid = max(len(batch) // 2, 1)
                    return self._embed_batch(litellm, batch[:mid]) + self._embed_batch(
                        litellm, batch[mid:]
                    )
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
            or "maximum input length" in message
            or ("input length" in message and "tokens" in message)
            or ("requested" in message and "tokens" in message)
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
    answer_cfg = get_chatbot_cfg(cfg).get("answer", {})
    provider = (answer_cfg.get("provider") or "").strip()
    model = (answer_cfg.get("model") or "").strip()

    # If chatbot.answer is not explicitly configured, inherit from the doc-gen llm.* config.
    # This means a single deepdoc init --provider X covers both doc generation and chatbot.
    if not provider or not model:
        llm_cfg = cfg.get("llm", {})
        llm_provider = (llm_cfg.get("provider") or "").strip()
        llm_model = (llm_cfg.get("model") or "").strip()
        if llm_provider and llm_model:
            answer_cfg = {
                **answer_cfg,
                "provider": llm_provider,
                "model": llm_model,
                "api_key_env": llm_cfg.get("api_key_env") or answer_cfg.get("api_key_env", ""),
                "base_url": llm_cfg.get("base_url") or answer_cfg.get("base_url", ""),
            }
            provider, model = llm_provider, llm_model

    if not provider or not model:
        raise ValueError(
            "\n\n"
            "╔══════════════════════════════════════════════════════════════════════╗\n"
            "║         CHATBOT NOT CONFIGURED — ACTION REQUIRED                    ║\n"
            "╠══════════════════════════════════════════════════════════════════════╣\n"
            "║                                                                      ║\n"
            "║  No LLM is configured for the chatbot.                               ║\n"
            "║                                                                      ║\n"
            "║  OPTION 1 — reuse your doc-gen LLM (zero extra config):              ║\n"
            "║    Just make sure llm.provider and llm.model are set.                ║\n"
            "║    The chatbot will automatically use the same provider and key.      ║\n"
            "║                                                                      ║\n"
            "║  OPTION 2 — use a separate (e.g. cheaper) model for chat:            ║\n"
            "║                                                                      ║\n"
            "║    chatbot:                                                           ║\n"
            "║      answer:                                                          ║\n"
            "║        provider: <your-provider>    # openai, anthropic, azure, etc. ║\n"
            "║        model: <your-model>          # matching model name            ║\n"
            "║        api_key_env: <YOUR_KEY_ENV>  # env var holding your key       ║\n"
            "║                                                                      ║\n"
            "║  Any LiteLLM-compatible provider works:                              ║\n"
            "║    https://docs.litellm.ai/docs/providers                            ║\n"
            "╚══════════════════════════════════════════════════════════════════════╝\n"
        )
    return LiteLLMChatClient(answer_cfg)


def build_embedding_client(
    cfg: dict[str, Any],
) -> LiteLLMEmbeddingClient | FastembedEmbeddingClient:
    """Build embedding client: fastembed (local) or litellm (cloud)."""
    chatbot_cfg = get_chatbot_cfg(cfg)
    embeddings_cfg = chatbot_cfg.get("embeddings", {})
    backend = embeddings_cfg.get("backend", "fastembed")

    if backend == "fastembed":
        return FastembedEmbeddingClient(embeddings_cfg)

    provider = (embeddings_cfg.get("provider") or "").strip()
    model = (embeddings_cfg.get("model") or "").strip()
    if not provider or not model:
        raise ValueError(
            "\n\n"
            "╔══════════════════════════════════════════════════════════════════════╗\n"
            "║         EMBEDDINGS NOT CONFIGURED — ACTION REQUIRED                 ║\n"
            "╠══════════════════════════════════════════════════════════════════════╣\n"
            "║                                                                      ║\n"
            "║  chatbot.embeddings.backend is set to 'litellm' but               ║\n"
            "║  chatbot.embeddings.provider and .model are not set.                ║\n"
            "║                                                                      ║\n"
            "║  Either switch to the local (no-API-key) backend:                   ║\n"
            "║                                                                      ║\n"
            "║    chatbot:                                                           ║\n"
            "║      embeddings:                                                      ║\n"
            "║        backend: fastembed    # runs locally, no key needed           ║\n"
            "║                                                                      ║\n"
            "║  Or configure a cloud embedding provider:                            ║\n"
            "║                                                                      ║\n"
            "║    chatbot:                                                           ║\n"
            "║      embeddings:                                                      ║\n"
            "║        backend: litellm                                               ║\n"
            "║        provider: <your-provider>   # e.g. openai, azure              ║\n"
            "║        model: <your-model>         # e.g. text-embedding-3-large     ║\n"
            "║        api_key_env: <YOUR_KEY_ENV> # env var holding your key        ║\n"
            "╚══════════════════════════════════════════════════════════════════════╝\n"
        )
    return LiteLLMEmbeddingClient(embeddings_cfg)


class FastembedEmbeddingClient:
    """Local embedding client using fastembed (no API keys, zero cloud calls)."""

    def __init__(self, service_cfg: dict[str, Any]) -> None:
        self.service_cfg = service_cfg
        # Fallback model if not set in config — explicit choice, not a vendor endorsement.
        # Full model list: https://qdrant.github.io/fastembed/examples/Supported_Models/
        self.model = service_cfg.get(
            "fastembed_model", "nomic-ai/nomic-embed-text-v1.5"
        )
        self.batch_size = service_cfg.get("fastembed_batch_size", 4)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using fastembed. Returns shape (N, embedding_dim)."""
        if not texts:
            return []
        try:
            from .embeddings import get_embeddings

            vecs = get_embeddings(
                texts,
                backend="fastembed",
                model=self.model,
                batch_size=self.batch_size,
            )
            if hasattr(vecs, "tolist"):
                return vecs.tolist()
            return list(vecs)
        except ImportError as exc:
            raise RuntimeError(
                "fastembed not installed. Run: pip install fastembed\n"
                "Or set embeddings.backend='litellm' to use cloud embeddings."
            ) from exc
        except Exception as exc:
            raise RuntimeError(f"fastembed embedding failed: {exc}") from exc
