"""LiteLLM-based LLM client. Works with Claude, OpenAI, Ollama, and anything LiteLLM supports."""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from ..config import resolve_api_key
from ..telemetry import RunTelemetry
from .litellm_compat import prepare_litellm


class LLMClient:
    """Thin wrapper around LiteLLM completion for deepdoc."""

    def __init__(
        self,
        cfg: dict[str, Any],
        telemetry: RunTelemetry | None = None,
    ) -> None:
        self.cfg = cfg
        self.telemetry = telemetry
        llm_cfg = cfg.get("llm", {})
        self.model = llm_cfg.get("model", "")
        # max_tokens=None means don't cap — let the model use its full output capacity
        self.max_tokens = llm_cfg.get("max_tokens", None)
        self.temperature = llm_cfg.get("temperature", 0.2)
        self.base_url = str(llm_cfg.get("base_url") or "") or None
        # YAML parses bare dates like 2024-12-01 as datetime.date — coerce to str
        _api_version = llm_cfg.get("api_version")
        self.api_version = str(_api_version).strip() if _api_version is not None else None
        self.usage: dict[str, int] = {
            "calls": 0,
            "prompt_chars": 0,
            "estimated_prompt_tokens": 0,
        }
        self._usage_lock = threading.Lock()

        provider = (llm_cfg.get("provider") or "").strip()
        model = (self.model or "").strip()
        api_key_env = (llm_cfg.get("api_key_env") or "").strip()

        if not provider or not model:
            raise ValueError(
                "\n\n"
                "╔══════════════════════════════════════════════════════════════════════╗\n"
                "║         LLM NOT CONFIGURED — ACTION REQUIRED                        ║\n"
                "╠══════════════════════════════════════════════════════════════════════╣\n"
                "║                                                                      ║\n"
                "║  llm.provider and llm.model are not set in your .deepdoc.yaml.       ║\n"
                "║  DeepDoc cannot generate documentation without an LLM configured.    ║\n"
                "║                                                                      ║\n"
                "║  QUICKEST FIX — run the interactive setup:                           ║\n"
                "║    deepdoc init                                                       ║\n"
                "║                                                                      ║\n"
                "║  OR add the following to your .deepdoc.yaml manually:                ║\n"
                "║                                                                      ║\n"
                "║    llm:                                                               ║\n"
                "║      provider: <your-provider>    # see examples below               ║\n"
                "║      model: <your-model>          # matching model name              ║\n"
                "║      api_key_env: <YOUR_KEY_ENV>  # name of env var holding key      ║\n"
                "║                                                                      ║\n"
                "║  Provider / model examples:                                          ║\n"
                "║    openai    → gpt-4o, gpt-4o-mini                                   ║\n"
                "║    anthropic → claude-3-5-sonnet-20241022, claude-haiku-4-5-20251001 ║\n"
                "║    azure     → azure/gpt-4o  (also set base_url, api_version)        ║\n"
                "║    ollama    → ollama/llama3.2  (local, no API key needed)            ║\n"
                "║    groq      → groq/llama-3.1-8b-instant                             ║\n"
                "║                                                                      ║\n"
                "║  Any provider supported by LiteLLM works:                            ║\n"
                "║    https://docs.litellm.ai/docs/providers                            ║\n"
                "╚══════════════════════════════════════════════════════════════════════╝\n"
            )

        is_azure = provider.lower() == "azure" or model.lower().startswith("azure/")
        if is_azure:
            base_url = str(llm_cfg.get("base_url") or "").strip()
            # YAML parses bare dates like 2025-07-01 as datetime.date — coerce to str
            api_version = str(llm_cfg.get("api_version") or "").strip()
            missing = []
            if not base_url:
                missing.append("llm.base_url  (your Azure OpenAI endpoint URL)")
            if not api_version:
                missing.append("llm.api_version  (e.g. 2024-02-01)")
            if missing:
                items = "\n".join(f"║    • {item:<64}║" for item in missing)
                raise ValueError(
                    "\n\n"
                    "╔══════════════════════════════════════════════════════════════════════╗\n"
                    "║         AZURE OPENAI NOT FULLY CONFIGURED — ACTION REQUIRED         ║\n"
                    "╠══════════════════════════════════════════════════════════════════════╣\n"
                    "║                                                                      ║\n"
                    "║  Azure OpenAI requires additional settings that are missing:         ║\n"
                    "║                                                                      ║\n"
                    f"{items}\n"
                    "║                                                                      ║\n"
                    "║  Add them to your .deepdoc.yaml:                                     ║\n"
                    "║                                                                      ║\n"
                    "║    llm:                                                               ║\n"
                    "║      provider: azure                                                  ║\n"
                    "║      model: azure/gpt-4o          # your deployment name             ║\n"
                    "║      base_url: https://<resource>.openai.azure.com  # endpoint URL   ║\n"
                    "║      api_version: 2024-02-01      # Azure API version                ║\n"
                    "║      api_key_env: AZURE_API_KEY   # env var holding your key         ║\n"
                    "║                                                                      ║\n"
                    "║  Or re-run:  deepdoc init --provider azure                           ║\n"
                    "╚══════════════════════════════════════════════════════════════════════╝\n"
                )

        if api_key_env and not os.environ.get(api_key_env):
            pad = max(0, 34 - len(api_key_env))
            export_pad = max(0, 33 - len(api_key_env))
            raise ValueError(
                "\n\n"
                "╔══════════════════════════════════════════════════════════════════════╗\n"
                "║         API KEY NOT SET — ACTION REQUIRED                           ║\n"
                "╠══════════════════════════════════════════════════════════════════════╣\n"
                "║                                                                      ║\n"
                f"║  Environment variable '{api_key_env}' is not set.{' ' * pad}║\n"
                "║  DeepDoc needs this to authenticate with your LLM provider.          ║\n"
                "║                                                                      ║\n"
                "║  Set it in your shell before running deepdoc:                        ║\n"
                f"║    export {api_key_env}=<your-api-key>{' ' * export_pad}║\n"
                "║                                                                      ║\n"
                "║  Get your API key from your provider's dashboard or console.         ║\n"
                "╚══════════════════════════════════════════════════════════════════════╝\n"
            )

        # Resolve and store key so it can be passed directly to litellm.completion()
        # (litellm may pick up a stale AZURE_OPENAI_API_KEY from the environment
        # instead of AZURE_API_KEY — passing api_key explicitly avoids this)
        self.api_key = resolve_api_key(cfg) or None
        if self.api_key and api_key_env:
            os.environ[api_key_env] = self.api_key

    def complete(self, system: str, user: str) -> str:
        """Send a chat completion request and return the response text."""
        start = time.perf_counter()
        response = None
        error_type = ""
        try:
            self._record_usage(system, user)
            litellm = prepare_litellm()

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
            if self.api_version:
                kwargs["api_version"] = self.api_version
            if self.api_key:
                kwargs["api_key"] = self.api_key

            response = litellm.completion(**kwargs)
            return response.choices[0].message.content or ""

        except ImportError:
            error_type = "ImportError"
            raise RuntimeError(
                "litellm not installed. Run: pip install litellm"
            )
        except Exception as e:
            error_type = type(e).__name__
            raise RuntimeError(f"LLM request failed: {e}") from e
        finally:
            self._record_telemetry(
                system,
                user,
                response,
                elapsed=time.perf_counter() - start,
                error_type=error_type,
            )

    def complete_stream(self, system: str, user: str):
        """Stream a completion response, yielding text chunks."""
        start = time.perf_counter()
        response_chars = 0
        final_chunk = None
        error_type = ""
        try:
            self._record_usage(system, user)
            litellm = prepare_litellm()

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
            if self.api_version:
                kwargs["api_version"] = self.api_version
            if self.api_key:
                kwargs["api_key"] = self.api_key

            for chunk in litellm.completion(**kwargs):
                final_chunk = chunk
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    response_chars += len(delta.content)
                    yield delta.content

        except ImportError:
            error_type = "ImportError"
            raise RuntimeError("litellm not installed. Run: pip install litellm")
        except Exception as exc:
            error_type = type(exc).__name__
            raise
        finally:
            self._record_telemetry(
                system,
                user,
                final_chunk,
                elapsed=time.perf_counter() - start,
                error_type=error_type,
                response_chars=response_chars,
                streamed=True,
            )

    def _record_usage(self, system: str, user: str) -> None:
        prompt_chars = len(system or "") + len(user or "")
        with self._usage_lock:
            self.usage["calls"] += 1
            self.usage["prompt_chars"] += prompt_chars
            self.usage["estimated_prompt_tokens"] += max(1, prompt_chars // 4)

    @staticmethod
    def _usage_value(usage: Any, key: str) -> int | None:
        if usage is None:
            return None
        value = usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _record_telemetry(
        self,
        system: str,
        user: str,
        response: Any,
        *,
        elapsed: float,
        error_type: str,
        response_chars: int | None = None,
        streamed: bool = False,
    ) -> None:
        if self.telemetry is None:
            return
        prompt_chars = len(system or "") + len(user or "")
        if response_chars is None:
            try:
                response_chars = len(response.choices[0].message.content or "")
            except (AttributeError, IndexError, TypeError):
                response_chars = 0
        usage = getattr(response, "usage", None)
        prompt_tokens = self._usage_value(usage, "prompt_tokens")
        completion_tokens = self._usage_value(usage, "completion_tokens")
        total_tokens = self._usage_value(usage, "total_tokens")
        estimated = prompt_tokens is None
        if prompt_tokens is None:
            prompt_tokens = max(1, prompt_chars // 4)
        if completion_tokens is None:
            completion_tokens = max(0, response_chars // 4)
        if total_tokens is None:
            total_tokens = prompt_tokens + completion_tokens
        finish_reason = ""
        try:
            finish_reason = str(response.choices[0].finish_reason or "")
        except (AttributeError, IndexError, TypeError):
            pass
        operation = self.telemetry.current_operation()
        self.telemetry.record_llm_call(
            {
                **operation,
                "model": self.model,
                "duration_seconds": round(elapsed, 6),
                "prompt_chars": prompt_chars,
                "response_chars": response_chars,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "tokens_estimated": estimated,
                "finish_reason": finish_reason,
                "streamed": streamed,
                "status": "failed" if error_type else "success",
                "error_type": error_type,
            }
        )
