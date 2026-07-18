from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

from click.testing import CliRunner

from deepdoc.cli import main
from deepdoc.llm import LLMClient
from deepdoc.telemetry import (
    RunTelemetry,
    load_latest_performance_run,
    load_performance_runs,
)


def test_telemetry_records_spans_counters_and_sanitized_llm_calls(tmp_path: Path) -> None:
    telemetry = RunTelemetry(tmp_path, "generate")

    with telemetry.span("pipeline.scan"):
        telemetry.counter("files.read", 3)
    telemetry.record_llm_call(
        {
            "name": "planner.classify",
            "prompt_tokens": 12,
            "api_key": "secret",
            "prompt": "source text",
        }
    )
    telemetry.finish("success", pages=2)

    latest = load_latest_performance_run(tmp_path)
    assert latest is not None
    assert latest["status"] == "success"
    assert latest["spans"]["pipeline.scan"]["count"] == 1
    assert latest["counters"]["files.read"] == 3
    assert latest["llm_calls"][0]["name"] == "planner.classify"
    assert "api_key" not in latest["llm_calls"][0]
    assert "prompt" not in latest["llm_calls"][0]


def test_telemetry_records_failed_span_and_fail_open_write(tmp_path: Path) -> None:
    telemetry = RunTelemetry(tmp_path, "generate")
    try:
        with telemetry.span("pipeline.plan"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    telemetry._disabled = True
    payload = telemetry.finish("failed", error_type="RuntimeError")

    assert payload["spans"]["pipeline.plan"]["failed"] == 1
    assert not telemetry.path.exists()


def test_telemetry_rotates_at_size_limit(tmp_path: Path) -> None:
    first = RunTelemetry(tmp_path, "generate", max_bytes=400)
    first.counter("payload", 1)
    first.finish("success", marker="x" * 300)
    second = RunTelemetry(tmp_path, "update", max_bytes=400)
    second.finish("success", marker="y" * 300)

    assert second.path.exists()
    assert second.path.with_suffix(".jsonl.1").exists()
    runs = load_performance_runs(tmp_path)
    assert [run["command"] for run in runs] == ["generate", "update"]


def test_telemetry_concurrent_updates_are_not_lost(tmp_path: Path) -> None:
    telemetry = RunTelemetry(tmp_path, "generate")

    def record(_: int) -> None:
        telemetry.counter("workers.completed")
        telemetry.record_llm_call({"name": "worker", "prompt_tokens": 1})

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(record, range(100)))
    payload = telemetry.finish("success")

    assert payload["counters"]["workers.completed"] == 100
    assert len(payload["llm_calls"]) == 100


def test_load_runs_ignores_malformed_lines(tmp_path: Path) -> None:
    telemetry = RunTelemetry(tmp_path, "generate")
    telemetry.path.parent.mkdir(parents=True)
    telemetry.path.write_text(
        '{"finished_at":"2026-01-01","command":"generate"}\n{bad json\n',
        encoding="utf-8",
    )

    runs = load_performance_runs(tmp_path)
    assert len(runs) == 1
    assert runs[0]["command"] == "generate"


def test_llm_client_records_provider_tokens(monkeypatch, tmp_path: Path) -> None:
    telemetry = RunTelemetry(tmp_path, "generate")
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="answer"),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=17,
            completion_tokens=5,
            total_tokens=22,
        ),
    )
    fake_litellm = SimpleNamespace(completion=lambda **kwargs: response)
    monkeypatch.setattr("deepdoc.llm.client.prepare_litellm", lambda: fake_litellm)
    client = LLMClient(
        {"llm": {"provider": "ollama", "model": "ollama/test"}},
        telemetry=telemetry,
    )

    with telemetry.operation("planner.classify", stage="classify"):
        assert client.complete("system", "user") == "answer"
    payload = telemetry.finish("success")

    call = payload["llm_calls"][0]
    assert call["name"] == "planner.classify"
    assert call["prompt_tokens"] == 17
    assert call["completion_tokens"] == 5
    assert call["total_tokens"] == 22
    assert call["tokens_estimated"] is False


def test_llm_usage_updates_are_thread_safe(tmp_path: Path) -> None:
    client = LLMClient({"llm": {"provider": "ollama", "model": "ollama/test"}})

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _: client._record_usage("a", "b"), range(200)))

    assert client.usage["calls"] == 200
    assert client.usage["prompt_chars"] == 400


def test_performance_cli_handles_missing_history(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ["performance"])

    assert result.exit_code == 0
    assert "No performance history found" in result.output


def test_performance_cli_renders_latest_run(tmp_path: Path, monkeypatch) -> None:
    first = RunTelemetry(tmp_path, "generate")
    first.finish("success")
    second = RunTelemetry(tmp_path, "update")
    with second.span("update.incremental"):
        pass
    second.record_llm_call(
        {
            "name": "generation.orders",
            "duration_seconds": 1.5,
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "status": "success",
        }
    )
    second.finish("success")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(main, ["performance"])

    assert result.exit_code == 0
    assert "DeepDoc Performance" in result.output
    assert "update" in result.output
    assert "update.incremental" in result.output
    assert "Prompt tokens" in result.output


def test_jsonl_contains_one_record_per_finished_run(tmp_path: Path) -> None:
    for command in ("generate", "update"):
        RunTelemetry(tmp_path, command).finish("success")

    lines = RunTelemetry(tmp_path, "unused").path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert all(json.loads(line)["status"] == "success" for line in lines)
