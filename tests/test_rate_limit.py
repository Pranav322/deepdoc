from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml
from click.testing import CliRunner

from deepdoc.cli import main
from deepdoc.llm import LLMClient, LLMOutputTruncatedError
from deepdoc.llm.rate_limit import ProviderRateLimiter


def test_rate_limiter_bounds_concurrency() -> None:
    limiter = ProviderRateLimiter(
        max_concurrency=1,
        requests_per_minute=100,
        tokens_per_minute=100000,
        window_seconds=1,
    )
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def first() -> None:
        with limiter.slot(10):
            first_entered.set()
            release_first.wait(timeout=1)

    def second() -> None:
        first_entered.wait(timeout=1)
        with limiter.slot(10):
            second_entered.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(first)
        second_future = executor.submit(second)
        assert first_entered.wait(timeout=1)
        assert not second_entered.wait(timeout=0.03)
        release_first.set()
        first_future.result(timeout=1)
        second_future.result(timeout=1)

    assert second_entered.is_set()


def test_rate_limiter_enforces_request_window() -> None:
    limiter = ProviderRateLimiter(
        max_concurrency=2,
        requests_per_minute=1,
        tokens_per_minute=100000,
        window_seconds=0.05,
    )
    with limiter.slot(10):
        pass
    started = time.perf_counter()
    with limiter.slot(10):
        pass

    assert time.perf_counter() - started >= 0.04


def test_rate_limiter_enforces_shared_cooldown() -> None:
    limiter = ProviderRateLimiter(
        max_concurrency=2,
        requests_per_minute=100,
        tokens_per_minute=100000,
        window_seconds=1,
    )
    limiter.penalize(0.05)
    started = time.perf_counter()
    with limiter.slot(10):
        pass

    assert time.perf_counter() - started >= 0.04


def test_large_single_prompt_does_not_deadlock_tpm_limit() -> None:
    limiter = ProviderRateLimiter(
        max_concurrency=1,
        requests_per_minute=10,
        tokens_per_minute=100,
        window_seconds=1,
    )

    def acquire() -> None:
        with limiter.slot(1000):
            pass

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(acquire).result(timeout=2)


def test_init_persists_explicit_provider_limits(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        main,
        [
            "init",
            "--provider",
            "ollama",
            "--llm-max-concurrency",
            "3",
            "--llm-rpm",
            "40",
            "--llm-tpm",
            "175000",
            "--context-window-tokens",
            "64000",
        ],
    )

    assert result.exit_code == 0
    cfg = yaml.safe_load((tmp_path / ".deepdoc.yaml").read_text(encoding="utf-8"))
    assert cfg["llm"]["context_window_tokens"] == 64000
    assert cfg["llm"]["rate_limits"] == {
        "max_concurrency": 3,
        "requests_per_minute": 40,
        "tokens_per_minute": 175000,
        "adaptive_backoff": True,
    }


def test_init_noninteractive_uses_safe_limit_defaults(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ["init", "--provider", "ollama"])

    assert result.exit_code != 0
    assert "--context-window-tokens" in result.output


def test_llm_output_cap_is_clamped_to_context_reserve() -> None:
    client = LLMClient(
        {
            "llm": {
                "provider": "ollama",
                "model": "ollama/test",
                "context_window_tokens": 32000,
                "output_reserve_tokens": 8000,
                "max_tokens": 500000,
            }
        }
    )

    assert client.max_tokens == 8000


def test_unconfigured_llm_preserves_friendly_setup_error() -> None:
    with pytest.raises(ValueError, match="LLM NOT CONFIGURED"):
        LLMClient({"llm": {}})


def test_llm_null_output_cap_uses_provider_default(monkeypatch) -> None:
    completion = MagicMock()
    completion.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="ok"), finish_reason="stop"
            )
        ]
    )
    monkeypatch.setattr(
        "deepdoc.llm.client.prepare_litellm",
        lambda: SimpleNamespace(completion=completion),
    )
    client = LLMClient(
        {
            "llm": {
                "provider": "ollama",
                "model": "ollama/test",
                "max_tokens": None,
                "context_window_tokens": 128000,
                "output_reserve_tokens": 16000,
            }
        }
    )

    assert client.max_tokens is None
    assert client.complete("system", "user") == "ok"
    assert "max_tokens" not in completion.call_args.kwargs


def test_llm_length_finish_reason_raises_actionable_error(monkeypatch) -> None:
    completion = MagicMock()
    completion.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="partial"), finish_reason="length"
            )
        ]
    )
    monkeypatch.setattr(
        "deepdoc.llm.client.prepare_litellm",
        lambda: SimpleNamespace(completion=completion),
    )
    client = LLMClient(
        {
            "llm": {
                "provider": "ollama",
                "model": "ollama/test",
                "max_tokens": 2048,
                "context_window_tokens": 128000,
                "output_reserve_tokens": 16000,
            }
        }
    )

    with pytest.raises(LLMOutputTruncatedError, match="output was truncated"):
        client.complete("system", "user")


def test_llm_client_rejects_oversized_prompt_before_provider(monkeypatch) -> None:
    completion = MagicMock()
    monkeypatch.setattr(
        "deepdoc.llm.client.prepare_litellm",
        lambda: SimpleNamespace(completion=completion),
    )
    client = LLMClient(
        {
            "llm": {
                "provider": "ollama",
                "model": "ollama/test",
                "context_window_tokens": 4096,
                "output_reserve_tokens": 1024,
            }
        }
    )

    with pytest.raises(RuntimeError, match="exceeds configured context window"):
        client.complete("system", "x" * 40000)

    completion.assert_not_called()
