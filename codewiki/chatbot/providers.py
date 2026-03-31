"""Provider wrappers for chatbot retrieval and answering."""

from __future__ import annotations

from typing import Any

from .settings import get_chatbot_cfg, resolve_service_api_key


class LiteLLMChatClient:
    """Thin wrapper for chat completions."""

    def __init__(self, service_cfg: dict[str, Any]) -> None:
        self.service_cfg = service_cfg

    def complete(self, system: str, user: str) -> str:
        try:
            import litellm

            litellm.suppress_debug_info = True

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
            raise RuntimeError("litellm not installed. Install codewiki[chatbot].") from exc
        except Exception as exc:
            model = self.service_cfg.get("model", "unknown")
            key_env = self.service_cfg.get("api_key_env", "")
            hint = f" Check env var {key_env}." if key_env else ""
            raise RuntimeError(f"Chat completion failed (model={model}).{hint} {exc}") from exc


class LiteLLMEmbeddingClient:
    """Thin wrapper for embedding calls."""

    def __init__(self, service_cfg: dict[str, Any]) -> None:
        self.service_cfg = service_cfg
        self.batch_size = service_cfg.get("batch_size", 24)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        try:
            import litellm

            litellm.suppress_debug_info = True
            vectors: list[list[float]] = []
            for i in range(0, len(texts), self.batch_size):
                batch = texts[i : i + self.batch_size]
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

                response = litellm.embedding(**kwargs)
                vectors.extend(item["embedding"] for item in response.data)
            return vectors
        except ImportError as exc:
            raise RuntimeError("litellm not installed. Install codewiki[chatbot].") from exc
        except Exception as exc:
            model = self.service_cfg.get("model", "unknown")
            key_env = self.service_cfg.get("api_key_env", "")
            hint = f" Check env var {key_env}." if key_env else ""
            raise RuntimeError(f"Embedding request failed (model={model}).{hint} {exc}") from exc


def build_chat_client(cfg: dict[str, Any]) -> LiteLLMChatClient:
    return LiteLLMChatClient(get_chatbot_cfg(cfg).get("answer", {}))


def build_embedding_client(cfg: dict[str, Any]) -> LiteLLMEmbeddingClient:
    return LiteLLMEmbeddingClient(get_chatbot_cfg(cfg).get("embeddings", {}))
