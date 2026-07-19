"""Provider-neutral request, token, concurrency, and cooldown limiting."""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
import threading
import time
from typing import Iterator

from ..telemetry import RunTelemetry


class ProviderRateLimiter:
    """Bound concurrent calls and rolling request/token usage for one service."""

    def __init__(
        self,
        *,
        max_concurrency: int,
        requests_per_minute: int,
        tokens_per_minute: int,
        telemetry: RunTelemetry | None = None,
        window_seconds: float = 60.0,
    ) -> None:
        self.max_concurrency = max(1, int(max_concurrency))
        self.requests_per_minute = max(1, int(requests_per_minute))
        self.tokens_per_minute = max(1, int(tokens_per_minute))
        self.window_seconds = max(0.01, float(window_seconds))
        self.telemetry = telemetry
        self._semaphore = threading.BoundedSemaphore(self.max_concurrency)
        self._lock = threading.Lock()
        self._events: deque[tuple[float, int]] = deque()
        self._cooldown_until = 0.0

    @contextmanager
    def slot(self, estimated_tokens: int) -> Iterator[None]:
        wait_started = time.perf_counter()
        self._semaphore.acquire()
        try:
            self._reserve(max(1, int(estimated_tokens)))
            wait = time.perf_counter() - wait_started
            if self.telemetry is not None and wait > 0.001:
                self.telemetry.counter("llm.rate_limit_wait_seconds", wait)
            yield
        finally:
            self._semaphore.release()

    def penalize(self, seconds: float) -> None:
        cooldown = max(0.0, float(seconds))
        if cooldown <= 0:
            return
        with self._lock:
            self._cooldown_until = max(
                self._cooldown_until,
                time.monotonic() + cooldown,
            )
        if self.telemetry is not None:
            self.telemetry.counter("llm.provider_cooldown_seconds", cooldown)

    def _reserve(self, estimated_tokens: int) -> None:
        while True:
            wait = 0.0
            now = time.monotonic()
            with self._lock:
                self._discard_expired(now)
                cooldown_wait = max(0.0, self._cooldown_until - now)
                token_total = sum(tokens for _, tokens in self._events)
                request_ok = len(self._events) < self.requests_per_minute
                token_ok = token_total + estimated_tokens <= self.tokens_per_minute
                # A single prompt larger than TPM must still be allowed when alone.
                if not self._events and estimated_tokens > self.tokens_per_minute:
                    token_ok = True
                if cooldown_wait <= 0 and request_ok and token_ok:
                    self._events.append((now, estimated_tokens))
                    return
                waits = [cooldown_wait] if cooldown_wait > 0 else []
                if self._events and (not request_ok or not token_ok):
                    waits.append(
                        max(0.001, self._events[0][0] + self.window_seconds - now)
                    )
                wait = max(waits) if waits else 0.001
            time.sleep(wait)

    def _discard_expired(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._events and self._events[0][0] <= cutoff:
            self._events.popleft()
