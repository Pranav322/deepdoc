"""Provider wrappers for chatbot retrieval and answering."""

from __future__ import annotations

from typing import Any, Iterator

from ..llm import (
    ModelCapabilityError,
    build_prompt_budget,
    count_message_tokens,
    fit_prompt_sections,
    resolve_completion_capabilities,
)
from ..llm.litellm_compat import prepare_litellm
from .embedding_capabilities import (
    EmbeddingCapabilityError,
    fit_embedding_text,
    resolve_embedding_capabilities,
)
from .settings import get_chatbot_cfg, resolve_service_api_key


class LiteLLMChatClient:
    """Thin wrapper for chat completions."""

    def __init__(self, service_cfg: dict[str, Any]) -> None:
        self.service_cfg = service_cfg
        self.model = str(service_cfg.get("model") or "")
        self.capabilities = resolve_completion_capabilities(
            self.model,
            service_cfg,
            config_prefix="chatbot.answer",
        )
        self.prompt_budget = build_prompt_budget(
            self.capabilities,
            output_reserve_tokens=service_cfg.get("output_reserve_tokens"),
        )
        self.context_window_tokens = self.capabilities.context_window_tokens
        self.output_reserve_tokens = self.prompt_budget.output_reserve_tokens
        configured_max_tokens = service_cfg.get("max_tokens")
        self.max_tokens = (
            min(
                max(1, int(configured_max_tokens)),
                self.output_reserve_tokens,
                self.capabilities.max_output_tokens or self.output_reserve_tokens,
            )
            if configured_max_tokens is not None
            else None
        )

    def fit_prompt_sections(self, **kwargs):
        """Fit a chatbot prompt through the answer model's resolved envelope."""
        return fit_prompt_sections(
            self.capabilities,
            output_reserve_tokens=self.output_reserve_tokens,
            **kwargs,
        )

    def fit_continuation_prompt(
        self,
        system: str,
        instruction: str,
        previous_answer: str,
        legacy_char_limit: int,
    ) -> str:
        """Return the largest line-aligned answer suffix that fits the model."""
        candidate = previous_answer[-max(400, legacy_char_limit) :]
        lines = candidate.splitlines(keepends=True) or [candidate]

        def _fit(tail: str):
            return self.fit_prompt_sections(
                system=system,
                render_prompt=lambda sections: (
                    instruction
                    + "\n\nPrevious answer tail:\n"
                    + sections.get("tail", "")
                ),
                required_sections={},
                optional_sections=[("tail", [tail])],
                step_name="chatbot continuation",
            )

        low, high = 0, len(lines) - 1
        best = None
        while low <= high:
            middle = (low + high) // 2
            fitted = _fit("".join(lines[middle:]))
            if fitted.omitted_records.get("tail"):
                low = middle + 1
            else:
                best = fitted
                high = middle - 1
        if best is None:
            raise ModelCapabilityError(
                "Chatbot continuation instruction and answer tail cannot fit the "
                "resolved answer-model context window."
            )
        return best.prompt

    def _validate_prompt_size(self, system: str, user: str) -> None:
        input_tokens, _ = count_message_tokens(system, user, self.capabilities)
        maximum_input = (
            self.context_window_tokens
            - self.output_reserve_tokens
            - self.prompt_budget.safety_tokens
        )
        if input_tokens > maximum_input:
            raise ModelCapabilityError(
                "Chatbot prompt exceeds the resolved answer-model context window "
                f"({input_tokens:,} input tokens > {maximum_input:,} available)."
            )

    def complete(self, system: str, user: str) -> str:
        try:
            self._validate_prompt_size(system, user)
            litellm = prepare_litellm()

            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": self.service_cfg.get("temperature", 0.1),
            }
            if self.max_tokens is not None:
                kwargs["max_tokens"] = self.max_tokens
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
        except ModelCapabilityError:
            raise
        except Exception as exc:
            model = self.service_cfg.get("model", "unknown")
            key_env = self.service_cfg.get("api_key_env", "")
            hint = f" Check env var {key_env}." if key_env else ""
            raise RuntimeError(
                f"Chat completion failed (model={model}).{hint} {exc}"
            ) from exc

    def complete_stream(self, system: str, user: str) -> Iterator[str]:
        try:
            self._validate_prompt_size(system, user)
            litellm = prepare_litellm()

            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": self.service_cfg.get("temperature", 0.1),
                "stream": True,
            }
            if self.max_tokens is not None:
                kwargs["max_tokens"] = self.max_tokens
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
        except ModelCapabilityError:
            raise
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
        self.capabilities = resolve_embedding_capabilities(
            {**service_cfg, "backend": "litellm"}
        )
        provider = (service_cfg.get("provider") or "").lower()
        model = (service_cfg.get("model") or "").lower()
        default_batch_size = (
            1 if provider == "azure" or model.startswith("azure/") else 24
        )
        self.batch_size = service_cfg.get("batch_size", default_batch_size)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        texts = [fit_embedding_text(text, self.capabilities) for text in texts]

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
        except EmbeddingCapabilityError:
            raise
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
                raise EmbeddingCapabilityError(
                    "A token-fitted embedding input was rejected by the provider. "
                    "Verify chatbot.embeddings.base_model or max_input_tokens."
                ) from exc
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
                "api_version": llm_cfg.get("api_version") or answer_cfg.get("api_version", ""),
                "base_model": answer_cfg.get("base_model") or llm_cfg.get("base_model"),
                "context_window_tokens": answer_cfg.get("context_window_tokens") or llm_cfg.get("context_window_tokens"),
                "output_reserve_tokens": answer_cfg.get("output_reserve_tokens") or llm_cfg.get("output_reserve_tokens"),
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
    is_azure = provider.lower() == "azure" or model.lower().startswith("azure/")
    if is_azure:
        base_url = (answer_cfg.get("base_url") or "").strip()
        api_version = (answer_cfg.get("api_version") or "").strip()
        missing = []
        if not base_url or base_url.startswith("https://<"):
            missing.append("base_url  (your Azure OpenAI endpoint URL)")
        if not api_version:
            missing.append("api_version  (e.g. 2024-02-01)")
        if missing:
            items = "\n".join(f"║    • {item:<64}║" for item in missing)
            raise ValueError(
                "\n\n"
                "╔══════════════════════════════════════════════════════════════════════╗\n"
                "║         AZURE CHATBOT NOT FULLY CONFIGURED — ACTION REQUIRED        ║\n"
                "╠══════════════════════════════════════════════════════════════════════╣\n"
                "║                                                                      ║\n"
                "║  Azure OpenAI requires additional settings that are missing:         ║\n"
                "║                                                                      ║\n"
                f"{items}\n"
                "║                                                                      ║\n"
                "║  Add them to .deepdoc.yaml under llm: or chatbot.answer:             ║\n"
                "║                                                                      ║\n"
                "║    llm:                                                               ║\n"
                "║      base_url: https://<resource>.openai.azure.com                   ║\n"
                "║      api_version: 2024-02-01                                         ║\n"
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
        self.capabilities = resolve_embedding_capabilities(
            {**service_cfg, "backend": "fastembed"}
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using fastembed. Returns shape (N, embedding_dim)."""
        if not texts:
            return []
        try:
            from .embeddings import get_embeddings

            texts = [fit_embedding_text(text, self.capabilities) for text in texts]
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
