from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from deepdoc.benchmark_v2 import (
    BenchmarkResult,
    build_artifact_scorecard,
    build_quality_scorecard,
    discover_generated_repo_roots,
    load_chatbot_eval_rows,
    save_quality_scorecard,
)
from deepdoc.cli import main


def _planner_results() -> list[BenchmarkResult]:
    return [
        BenchmarkResult(
            name="case-a",
            family="backend",
            repo_path="/tmp/a",
            holdout=False,
            score=96.0,
            details={
                "profile_match": 1.0,
                "section_coverage": 1.0,
                "title_coverage": 0.9,
                "noise_suppression": 0.95,
                "orphan_score": 1.0,
                "overview_focus": 0.9,
            },
            notes=[],
        ),
        BenchmarkResult(
            name="case-b",
            family="backend",
            repo_path="/tmp/b",
            holdout=True,
            score=94.0,
            details={
                "profile_match": 1.0,
                "section_coverage": 0.9,
                "title_coverage": 0.9,
                "noise_suppression": 0.95,
                "orphan_score": 0.9,
                "overview_focus": 0.8,
            },
            notes=["minor drift"],
        ),
    ]


def _chatbot_rows_good() -> list[dict[str, object]]:
    return [
        {
            "question": "q1",
            "grounded_correct": True,
            "citation_precision": 0.98,
            "evidence_recall": 0.96,
            "abstain_expected": False,
        },
        {
            "question": "q2",
            "grounded_correct": True,
            "citation_precision": 0.97,
            "evidence_recall": 0.95,
            "abstain_expected": True,
            "abstain_correct": True,
        },
    ]


def _chatbot_rows_bad() -> list[dict[str, object]]:
    return [
        {
            "question": "q1",
            "grounded_correct": False,
            "citation_precision": 0.55,
            "evidence_recall": 0.50,
            "abstain_expected": True,
            "abstain_correct": False,
        }
    ]


def test_build_quality_scorecard_includes_docs_chatbot_and_gate_status() -> None:
    scorecard = build_quality_scorecard(
        planner_results=_planner_results(),
        chatbot_results=_chatbot_rows_good(),
        label="week-1-baseline",
    )

    assert scorecard["schema_version"] == "scorecard_v1"
    assert scorecard["label"] == "week-1-baseline"
    assert scorecard["docs"]["cases_total"] == 2
    assert scorecard["chatbot"]["cases_total"] == 2
    assert scorecard["docs"]["completeness_score"] == 95.0
    assert scorecard["chatbot"]["completeness_score"] >= 95.0
    assert scorecard["overall"]["all_gates_pass"] is True


def test_build_quality_scorecard_flags_failing_gates() -> None:
    scorecard = build_quality_scorecard(
        planner_results=_planner_results(),
        chatbot_results=_chatbot_rows_bad(),
        label="regression",
    )

    assert scorecard["overall"]["all_gates_pass"] is False
    assert scorecard["overall"]["gates"]["grounded_accuracy"] is False
    assert scorecard["chatbot"]["completeness_score"] < 95.0


def test_load_chatbot_eval_rows_supports_array_and_wrapped_shapes(
    tmp_path: Path,
) -> None:
    array_path = tmp_path / "array.json"
    wrapped_path = tmp_path / "wrapped.json"
    results_path = tmp_path / "results.json"

    array_path.write_text(json.dumps(_chatbot_rows_good()), encoding="utf-8")
    wrapped_path.write_text(
        json.dumps({"cases": _chatbot_rows_good()}), encoding="utf-8"
    )
    results_path.write_text(
        json.dumps({"results": _chatbot_rows_good()}), encoding="utf-8"
    )

    assert len(load_chatbot_eval_rows(array_path)) == 2
    assert len(load_chatbot_eval_rows(wrapped_path)) == 2
    assert len(load_chatbot_eval_rows(results_path)) == 2


def test_save_quality_scorecard_writes_json_file(tmp_path: Path) -> None:
    out_path = tmp_path / "scorecards" / "quality.json"
    scorecard = build_quality_scorecard(
        planner_results=_planner_results(),
        chatbot_results=_chatbot_rows_good(),
        label="persist",
    )

    save_quality_scorecard(out_path, scorecard)

    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded["label"] == "persist"
    assert (
        loaded["overall"]["completeness_score"]
        == scorecard["overall"]["completeness_score"]
    )


def test_cli_benchmark_strict_scorecard_fails_on_bad_chatbot_metrics(
    monkeypatch,
    tmp_path: Path,
) -> None:
    catalog_path = tmp_path / "catalog.json"
    chatbot_path = tmp_path / "chatbot_eval.json"
    scorecard_path = tmp_path / "quality_scorecard.json"
    repo_path = tmp_path / "fixture-repo"
    repo_path.mkdir()

    catalog_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "name": "fixture",
                        "family": "ad_hoc",
                        "repo_path": str(repo_path),
                        "holdout": False,
                        "gold": {},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    chatbot_path.write_text(json.dumps(_chatbot_rows_bad()), encoding="utf-8")

    monkeypatch.setattr(
        "deepdoc.cli._load_or_exit",
        lambda: {
            "llm": {"provider": "anthropic", "model": "test"},
            "output_dir": "docs",
        },
    )
    monkeypatch.setattr("deepdoc.cli._find_repo_root", lambda: tmp_path)

    def _fake_run_case(
        case: dict[str, object], cfg: dict[str, object]
    ) -> BenchmarkResult:
        return BenchmarkResult(
            name=str(case["name"]),
            family=str(case.get("family", "other")),
            repo_path=str(case["repo_path"]),
            holdout=bool(case.get("holdout", False)),
            score=99.0,
            details={
                "profile_match": 1.0,
                "section_coverage": 1.0,
                "title_coverage": 1.0,
                "noise_suppression": 1.0,
                "orphan_score": 1.0,
                "overview_focus": 1.0,
            },
            notes=[],
        )

    monkeypatch.setattr("deepdoc.benchmark_v2.run_case", _fake_run_case)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "benchmark",
            "--catalog",
            str(catalog_path),
            "--chatbot-eval",
            str(chatbot_path),
            "--scorecard-out",
            str(scorecard_path),
            "--strict-scorecard",
        ],
    )

    assert result.exit_code != 0
    assert "gates failed" in result.output.lower()
    payload = json.loads(scorecard_path.read_text(encoding="utf-8"))
    assert payload["overall"]["all_gates_pass"] is False


def test_build_artifact_scorecard_uses_generation_artifacts(tmp_path: Path) -> None:
    repo_dir = tmp_path / "backend-a"
    state = repo_dir / ".deepdoc"
    chatbot = state / "chatbot"
    chatbot.mkdir(parents=True)

    (state / "generation_quality.json").write_text(
        json.dumps(
            {
                "status": "partial",
                "pages_generated": 10,
                "pages_failed": 0,
                "pages_invalid": 2,
                "pages_degraded": 2,
            }
        ),
        encoding="utf-8",
    )
    (state / "scan_cache.json").write_text(
        json.dumps(
            {
                "api_endpoints": [
                    {"method": "GET", "path": "/api/health", "publication_ready": True}
                ]
            }
        ),
        encoding="utf-8",
    )

    required = {
        "code_chunks.jsonl": '{"text":"GET /api/health", "file_path":"src/routes.py"}\n',
        "artifact_chunks.jsonl": '{"text":"config", "file_path":"settings.py"}\n',
        "relationship_chunks.jsonl": '{"text":"graph", "file_path":"src/routes.py"}\n',
        "doc_chunks.jsonl": '{"text":"docs", "doc_path":"docs/index.mdx"}\n',
        "doc_full_chunks.jsonl": '{"text":"full docs", "doc_path":"docs/index.mdx"}\n',
        "repo_doc_chunks.jsonl": '{"text":"repo docs", "doc_path":"README.md"}\n',
    }
    for name, content in required.items():
        (chatbot / name).write_text(content, encoding="utf-8")

    for name in (
        "code_meta.json",
        "artifact_meta.json",
        "relationship_meta.json",
        "doc_summary_meta.json",
        "doc_full_meta.json",
        "repo_doc_meta.json",
    ):
        (chatbot / name).write_text("{}\n", encoding="utf-8")

    for name in (
        "code.faiss",
        "artifacts.faiss",
        "relationship.faiss",
        "docs.faiss",
        "docs_full.faiss",
        "repo_docs.faiss",
    ):
        (chatbot / name).write_bytes(b"faiss")

    scorecard = build_artifact_scorecard([repo_dir], label="artifact-test")

    assert scorecard["mode"] == "artifact_proxy"
    assert scorecard["repo_count"] == 1
    assert scorecard["repos"][0]["docs"]["completeness_score"] == 80.0
    assert scorecard["repos"][0]["chatbot"]["bootstrap_eval_cases"] >= 2
    assert scorecard["chatbot"]["cases_total"] >= 2


def test_discover_generated_repo_roots_filters_by_deepdoc_state(tmp_path: Path) -> None:
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    (good / ".deepdoc").mkdir(parents=True)
    bad.mkdir()

    found = discover_generated_repo_roots(tmp_path)
    assert found == [good]


def test_cli_benchmark_artifact_mode_generates_scorecard(
    monkeypatch,
    tmp_path: Path,
) -> None:
    generated_root = tmp_path / "generated"
    repo_dir = generated_root / "backend-a"
    state = repo_dir / ".deepdoc"
    chatbot = state / "chatbot"
    chatbot.mkdir(parents=True)

    (state / "generation_quality.json").write_text(
        json.dumps(
            {
                "status": "success",
                "pages_generated": 6,
                "pages_failed": 0,
                "pages_invalid": 0,
                "pages_degraded": 0,
            }
        ),
        encoding="utf-8",
    )
    (state / "scan_cache.json").write_text(
        json.dumps(
            {
                "api_endpoints": [
                    {
                        "method": "POST",
                        "path": "/v1/orders",
                        "publication_ready": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    for name in (
        "code_chunks.jsonl",
        "artifact_chunks.jsonl",
        "relationship_chunks.jsonl",
        "doc_chunks.jsonl",
        "doc_full_chunks.jsonl",
        "repo_doc_chunks.jsonl",
    ):
        (chatbot / name).write_text(
            '{"text":"POST /v1/orders", "file_path":"src/orders.py"}\n',
            encoding="utf-8",
        )

    for name in (
        "code_meta.json",
        "artifact_meta.json",
        "relationship_meta.json",
        "doc_summary_meta.json",
        "doc_full_meta.json",
        "repo_doc_meta.json",
    ):
        (chatbot / name).write_text("{}\n", encoding="utf-8")

    for name in (
        "code.faiss",
        "artifacts.faiss",
        "relationship.faiss",
        "docs.faiss",
        "docs_full.faiss",
        "repo_docs.faiss",
    ):
        (chatbot / name).write_bytes(b"faiss")

    monkeypatch.setattr(
        "deepdoc.cli._load_or_exit",
        lambda: {
            "llm": {"provider": "anthropic", "model": "test"},
            "output_dir": "docs",
        },
    )
    monkeypatch.setattr("deepdoc.cli._find_repo_root", lambda: tmp_path)

    out_path = tmp_path / "artifact_scorecard.json"
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "benchmark",
            "--generated-root",
            str(generated_root),
            "--scorecard-out",
            str(out_path),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["mode"] == "artifact_proxy"
    assert payload["repo_count"] == 1
