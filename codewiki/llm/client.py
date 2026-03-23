"""LiteLLM-based LLM client. Works with Claude, OpenAI, Ollama, and anything LiteLLM supports."""

from __future__ import annotations

import os
from typing import Any

from ..config import resolve_api_key


class LLMClient:
    """Thin wrapper around LiteLLM completion for codewiki."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        llm_cfg = cfg.get("llm", {})
        self.model = llm_cfg.get("model", "claude-3-5-sonnet-20241022")
        # max_tokens=None means don't cap — let the model use its full output capacity
        self.max_tokens = llm_cfg.get("max_tokens", None)
        self.temperature = llm_cfg.get("temperature", 0.2)
        self.base_url = llm_cfg.get("base_url")

        # Set API key in environment so LiteLLM picks it up automatically
        api_key = resolve_api_key(cfg)
        if api_key:
            env_var = llm_cfg.get("api_key_env", "ANTHROPIC_API_KEY")
            os.environ[env_var] = api_key

    def complete(self, system: str, user: str) -> str:
        """Send a chat completion request and return the response text."""
        try:
            import litellm

            # Silence LiteLLM's verbose logging
            litellm.suppress_debug_info = True

            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": self.temperature,
            }
            # Only pass max_tokens if explicitly set — otherwise let the model decide
            if self.max_tokens:
                kwargs["max_tokens"] = self.max_tokens
            if self.base_url:
                kwargs["base_url"] = self.base_url

            response = litellm.completion(**kwargs)
            return response.choices[0].message.content or ""

        except ImportError:
            raise RuntimeError(
                "litellm not installed. Run: pip install litellm"
            )
        except Exception as e:
            raise RuntimeError(f"LLM request failed: {e}") from e

    def complete_stream(self, system: str, user: str):
        """Stream a completion response, yielding text chunks."""
        try:
            import litellm

            litellm.suppress_debug_info = True

            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": self.temperature,
                "stream": True,
            }
            if self.max_tokens:
                kwargs["max_tokens"] = self.max_tokens
            if self.base_url:
                kwargs["base_url"] = self.base_url

            for chunk in litellm.completion(**kwargs):
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content

        except ImportError:
            raise RuntimeError("litellm not installed. Run: pip install litellm")
