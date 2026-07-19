from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import time
from pathlib import Path

import yaml
from click.testing import CliRunner

from deepdoc.cli import main
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

    with limiter.slot(1000):
        pass


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

    assert result.exit_code == 0
    cfg = yaml.safe_load((tmp_path / ".deepdoc.yaml").read_text(encoding="utf-8"))
    assert cfg["llm"]["context_window_tokens"] == 128000
    assert cfg["llm"]["rate_limits"]["max_concurrency"] == 6
    assert cfg["llm"]["rate_limits"]["requests_per_minute"] == 60
    assert cfg["llm"]["rate_limits"]["tokens_per_minute"] == 250000
