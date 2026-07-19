"""Local, fail-open performance telemetry for DeepDoc runs."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Iterator
from uuid import uuid4


TELEMETRY_SCHEMA_VERSION = 1
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
_CURRENT_OPERATION: ContextVar[dict[str, Any]] = ContextVar(
    "deepdoc_telemetry_operation", default={}
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunTelemetry:
    """Collect one run's metrics and persist one sanitized JSONL record."""

    def __init__(
        self,
        repo_root: Path,
        command: str,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> None:
        self.repo_root = repo_root
        self.command = command
        self.max_bytes = max_bytes
        self.run_id = uuid4().hex
        self.started_at = _utc_now()
        self._started = time.perf_counter()
        self._lock = threading.RLock()
        self._spans: dict[str, dict[str, float | int]] = {}
        self._counters: dict[str, float] = {}
        self._llm_calls: list[dict[str, Any]] = []
        self._finished = False
        self._disabled = False

    @property
    def path(self) -> Path:
        return self.repo_root / ".deepdoc" / "performance" / "runs.jsonl"

    @contextmanager
    def span(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        status = "success"
        try:
            yield
        except BaseException:
            status = "failed"
            raise
        finally:
            elapsed = time.perf_counter() - start
            self.record_duration(name, elapsed, failed=status == "failed")

    def record_duration(self, name: str, seconds: float, *, failed: bool = False) -> None:
        with self._lock:
            record = self._spans.setdefault(
                name,
                {"duration_seconds": 0.0, "count": 0, "failed": 0},
            )
            record["duration_seconds"] = float(record["duration_seconds"]) + seconds
            record["count"] = int(record["count"]) + 1
            if failed:
                record["failed"] = int(record["failed"]) + 1

    @contextmanager
    def operation(self, name: str, **attributes: Any) -> Iterator[None]:
        token = _CURRENT_OPERATION.set({"name": name, **attributes})
        try:
            yield
        finally:
            _CURRENT_OPERATION.reset(token)

    def current_operation(self) -> dict[str, Any]:
        return dict(_CURRENT_OPERATION.get())

    def counter(self, name: str, value: float = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0.0) + value

    def record_llm_call(self, payload: dict[str, Any]) -> None:
        safe_payload = {
            key: value
            for key, value in payload.items()
            if key
            not in {
                "prompt",
                "response",
                "system",
                "user",
                "api_key",
                "base_url",
            }
        }
        with self._lock:
            self._llm_calls.append(safe_payload)

    def snapshot(self, status: str, **summary: Any) -> dict[str, Any]:
        with self._lock:
            return {
                "schema_version": TELEMETRY_SCHEMA_VERSION,
                "run_id": self.run_id,
                "command": self.command,
                "started_at": self.started_at,
                "finished_at": _utc_now(),
                "status": status,
                "total_seconds": round(time.perf_counter() - self._started, 6),
                "spans": json.loads(json.dumps(self._spans)),
                "counters": dict(self._counters),
                "llm_calls": list(self._llm_calls),
                "summary": summary,
            }

    def finish(self, status: str, **summary: Any) -> dict[str, Any]:
        with self._lock:
            if self._finished:
                return self.snapshot(status, **summary)
            self._finished = True
        payload = self.snapshot(status, **summary)
        self._append(payload)
        return payload

    def _append(self, payload: dict[str, Any]) -> None:
        if self._disabled:
            return
        data = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
        try:
            with self._lock:
                path = self.path
                path.parent.mkdir(parents=True, exist_ok=True)
                current_size = path.stat().st_size if path.exists() else 0
                if current_size and current_size + len(data) > self.max_bytes:
                    rotated = path.with_suffix(path.suffix + ".1")
                    if rotated.exists():
                        rotated.unlink()
                    os.replace(path, rotated)
                with path.open("ab") as handle:
                    handle.write(data)
        except OSError:
            self._disabled = True


def load_performance_runs(repo_root: Path) -> list[dict[str, Any]]:
    """Load valid run records from rotated and active JSONL files."""
    path = repo_root / ".deepdoc" / "performance" / "runs.jsonl"
    records: list[dict[str, Any]] = []
    for candidate in (path.with_suffix(path.suffix + ".1"), path):
        if not candidate.exists():
            continue
        try:
            lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                payload = json.loads(line)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and payload.get("finished_at"):
                records.append(payload)
    return records


def load_latest_performance_run(repo_root: Path) -> dict[str, Any] | None:
    records = load_performance_runs(repo_root)
    return records[-1] if records else None
