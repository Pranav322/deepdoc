"""Resource monitoring utilities for scale tests and production guards."""

from __future__ import annotations

import os
import platform
import threading
import time


def measure_rss_bytes() -> int:
    """Return current process RSS in bytes (best-effort, platform-dependent)."""
    if platform.system() == "Darwin":
        try:
            # macOS: task_info via ps
            import subprocess
            result = subprocess.run(
                ["ps", "-o", "rss=", "-p", str(os.getpid())],
                capture_output=True, text=True, timeout=5,
            )
            return int(result.stdout.strip()) * 1024  # ps returns KB
        except (ValueError, subprocess.SubprocessError, FileNotFoundError):
            pass
    try:
        import resource
        if hasattr(resource, "RUSAGE_SELF"):
            usage = resource.getrusage(resource.RUSAGE_SELF)
            return usage.ru_maxrss * 1024  # macOS returns KB
    except (ImportError, AttributeError):
        pass
    return 0


def measure_rss_mb() -> float:
    """Return current process RSS in megabytes."""
    return measure_rss_bytes() / (1024 * 1024)


class TimeoutGuard:
    """Context manager that sets a flag when elapsed time exceeds a limit.

    Does NOT interrupt the running code — callers must periodically check
    ``expired`` and bail out gracefully.
    """

    def __init__(self, timeout_seconds: float):
        self.timeout_seconds = timeout_seconds
        self.start_time: float = 0.0
        self.expired: bool = False

    def __enter__(self) -> "TimeoutGuard":
        if self.timeout_seconds > 0:
            self.start_time = time.perf_counter()
        return self

    def __exit__(self, *args) -> None:
        pass

    def check(self) -> bool:
        """Return True if timeout has expired. Call this in loops."""
        if self.expired:
            return True
        if self.timeout_seconds <= 0:
            return False
        elapsed = time.perf_counter() - self.start_time
        if elapsed >= self.timeout_seconds:
            self.expired = True
        return self.expired


__all__ = ["measure_rss_bytes", "measure_rss_mb", "TimeoutGuard"]