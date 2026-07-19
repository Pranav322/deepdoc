"""Regression tests for Phase 1 performance fixes.

Covers:
  Fix #1 — parse_file(content=...) skips disk re-read
  Fix #8 — evidence reads from scan.file_contents cache
  Fix #9 — resolve_repo_endpoints only builds indexes for present frameworks
  Fix #10 — retry backoff constants are capped
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deepdoc.parser.base import ParsedFile, Symbol
from deepdoc.parser.registry import parse_file


# ─────────────────────────────────────────────────────────────────────────────
# Fix #1: parse_file accepts optional content, skips disk re-read
# ─────────────────────────────────────────────────────────────────────────────


def test_parse_file_uses_provided_content_and_skips_disk_read(tmp_path: Path) -> None:
    """Providing content= should skip path.read_text entirely."""
    src = tmp_path / "lib.py"
    src.write_text("def hello():\n    return 'world'\n", encoding="utf-8")

    # Delete the file first so any disk read would fail
    src.unlink()
    parsed = parse_file(src, content="def hello():\n    return 'world'\n")

    assert parsed is not None
    assert parsed.language == "python"
    assert len(parsed.symbols) == 1
    assert parsed.symbols[0].name == "hello"


def test_parse_file_backward_compat_without_content(tmp_path: Path) -> None:
    """Calling without content= still reads from disk (backward-compat)."""
    src = tmp_path / "mod.py"
    src.write_text("CONFIG = 42\n", encoding="utf-8")

    parsed = parse_file(src)

    assert parsed is not None
    assert parsed.language == "python"
    assert len(parsed.symbols) == 1
    assert parsed.symbols[0].name == "CONFIG"


def test_parse_file_content_param_none_default() -> None:
    """content parameter defaults to None — existing callers unaffected."""
    import inspect

    sig = inspect.signature(parse_file)
    assert "content" in sig.parameters
    assert sig.parameters["content"].default is None


def test_parse_file_returns_none_for_unsupported_extension(tmp_path: Path) -> None:
    """Unsupported extension still returns None with or without content."""
    src = tmp_path / "data.txt"
    src.write_text("hello\n", encoding="utf-8")

    assert parse_file(src) is None
    assert parse_file(src, content="hello\n") is None


# ─────────────────────────────────────────────────────────────────────────────
# Fix #8: Evidence reads from scan.file_contents cache
# ─────────────────────────────────────────────────────────────────────────────


def test_evidence_reads_from_file_contents_cache(tmp_path: Path) -> None:
    """EvidenceAssembler._build_source_context prefers scan.file_contents over disk.

    The cached content deliberately differs from what's on disk — this is the
    only way to prove the cache was actually used rather than a disk fallback
    that happens to produce the same text.
    """
    from deepdoc.generator.evidence import EvidenceAssembler
    from deepdoc.planner import DocBucket, DocPlan, RepoScan

    repo_root = tmp_path
    src = repo_root / "app.py"
    src.write_text("def run():\n    return 'DISK_VERSION'\n", encoding="utf-8")

    scan = RepoScan(
        file_tree={},
        file_summaries={"app.py": "symbols=[function:run] | lines=2"},
        api_endpoints=[],
        languages={"python": 1},
        has_openapi=False,
        openapi_paths=[],
        total_files=1,
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
        file_line_counts={"app.py": 2},
        parsed_files={
            "app.py": ParsedFile(
                path=Path("app.py"),
                language="python",
                symbols=[Symbol(name="run", kind="function", signature="def run():", start_line=1, end_line=2)],
                imports=[],
            )
        },
        file_contents={"app.py": "def run():\n    return 'CACHE_VERSION'\n"},
    )

    bucket = DocBucket(
        bucket_type="system",
        title="App",
        slug="app",
        section="core",
        description="App module",
        owned_files=["app.py"],
    )
    plan = DocPlan(buckets=[bucket], nav_structure={}, skipped_files=[])
    cfg = {"source_context_budget": 60_000}

    assembler = EvidenceAssembler(repo_root, scan, plan, cfg)

    evidence = assembler.assemble(bucket)
    assert evidence is not None
    assert "CACHE_VERSION" in evidence.source_context
    assert "DISK_VERSION" not in evidence.source_context


def test_evidence_falls_back_to_disk_when_cache_miss(tmp_path: Path) -> None:
    """When scan.file_contents is missing a file, evidence falls back to disk."""
    from deepdoc.generator.evidence import EvidenceAssembler
    from deepdoc.planner import DocBucket, DocPlan, RepoScan

    repo_root = tmp_path
    src = repo_root / "fallback.py"
    src.write_text("FALLBACK = True\n", encoding="utf-8")

    scan = RepoScan(
        file_tree={},
        file_summaries={"fallback.py": "symbols=[constant:FALLBACK] | lines=1"},
        api_endpoints=[],
        languages={"python": 1},
        has_openapi=False,
        openapi_paths=[],
        total_files=1,
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
        file_line_counts={"fallback.py": 1},
        parsed_files={},
        file_contents={},  # empty cache — forces disk fallback
    )

    bucket = DocBucket(
        bucket_type="system",
        title="Fallback",
        slug="fallback",
        section="core",
        description="Fallback test",
        owned_files=["fallback.py"],
    )
    plan = DocPlan(buckets=[bucket], nav_structure={}, skipped_files=[])
    cfg = {"source_context_budget": 60_000}

    assembler = EvidenceAssembler(repo_root, scan, plan, cfg)

    evidence = assembler.assemble(bucket)
    assert evidence is not None
    assert "FALLBACK" in evidence.source_context


# ─────────────────────────────────────────────────────────────────────────────
# Fix #9: resolve_repo_endpoints only builds indexes for present frameworks
# ─────────────────────────────────────────────────────────────────────────────


def test_resolve_repo_endpoints_skips_js_index_when_no_js_framework() -> None:
    """JS/Go indexes are NOT built when endpoints have no express/fastify/go entries.

    Spies on the builder functions directly — a black-box check on the output
    alone can't tell "index was skipped" from "index was built but unused".
    """
    from unittest.mock import patch

    from deepdoc.parser.api_detector import APIEndpoint
    from deepdoc.parser.routes import repo_resolver
    from deepdoc.parser.routes.repo_resolver import resolve_repo_endpoints

    # Only Python endpoint — no JS/Go frameworks present
    endpoint = APIEndpoint(
        method="GET",
        path="/users/",
        handler="user_list",
        file="views.py",
        line=42,
        framework="falcon",
    )

    # file_contents includes .ts/.go files but no JS/Go framework is present,
    # so those indexes must not be built even though matching files exist.
    with patch.object(
        repo_resolver, "_build_js_index", wraps=repo_resolver._build_js_index
    ) as js_spy, patch.object(
        repo_resolver, "_build_go_index", wraps=repo_resolver._build_go_index
    ) as go_spy, patch.object(
        repo_resolver, "_build_python_index", wraps=repo_resolver._build_python_index
    ) as py_spy:
        result = resolve_repo_endpoints(
            Path("."),
            [endpoint],
            {
                "views.py": "def user_list():\n    pass\n",
                "unrelated.ts": "import * as x from './other'",
                "unrelated.go": 'package main\nimport "net/http"\n',
            },
        )

    js_spy.assert_not_called()
    go_spy.assert_not_called()
    py_spy.assert_called_once()
    assert len(result) >= 1
    assert any(e.method == "GET" for e in result)


def test_resolve_repo_endpoints_only_builds_js_index_for_express_fastify() -> None:
    """JS index IS built (and only JS) when express endpoints are present."""
    from unittest.mock import patch

    from deepdoc.parser.api_detector import APIEndpoint
    from deepdoc.parser.routes import repo_resolver
    from deepdoc.parser.routes.repo_resolver import resolve_repo_endpoints

    endpoint = APIEndpoint(
        method="POST",
        path="/api/orders",
        handler="createOrder",
        file="routes/orders.js",
        line=10,
        framework="express",
    )

    with patch.object(
        repo_resolver, "_build_js_index", wraps=repo_resolver._build_js_index
    ) as js_spy, patch.object(
        repo_resolver, "_build_go_index"
    ) as go_spy, patch.object(
        repo_resolver, "_build_python_index"
    ) as py_spy:
        result = resolve_repo_endpoints(
            Path("."),
            [endpoint],
            {
                "routes/orders.js": (
                    "const express = require('express');\n"
                    "const router = express.Router();\n"
                    "router.post('/api/orders', createOrder);\n"
                ),
            },
        )

    js_spy.assert_called_once()
    go_spy.assert_not_called()
    py_spy.assert_not_called()
    assert len(result) >= 1
    assert any(e.method == "POST" for e in result)


def test_resolve_repo_endpoints_handles_none_index_gracefully() -> None:
    """When an index is None (not built), the endpoint is still normalized."""
    from deepdoc.parser.api_detector import APIEndpoint
    from deepdoc.parser.routes.repo_resolver import resolve_repo_endpoints

    # Fastify endpoint but no matching JS files in file_contents
    endpoint = APIEndpoint(
        method="GET",
        path="/health",
        handler="healthCheck",
        file="health.js",
        line=5,
        framework="fastify",
    )

    result = resolve_repo_endpoints(
        Path("."),
        [endpoint],
        {},  # empty file_contents → no JS index built → js_index is None
    )

    # Should still produce a normalized endpoint without crashing
    assert len(result) >= 1
    assert any(e.method == "GET" for e in result)


def test_resolve_repo_endpoints_skips_all_when_no_matching_frameworks() -> None:
    """When no recognized framework present, no indexes are built."""
    from deepdoc.parser.api_detector import APIEndpoint
    from deepdoc.parser.routes.repo_resolver import resolve_repo_endpoints

    # Unknown framework — no index should be built
    endpoint = APIEndpoint(
        method="GET",
        path="/ping",
        handler="ping",
        file="ping.py",
        line=1,
        framework="unknown_framework",
    )

    result = resolve_repo_endpoints(
        Path("."),
        [endpoint],
        {
            "ping.py": "def ping():\n    return 'pong'\n",
            "server.ts": "import express from 'express';\n",
            "main.go": 'package main\nimport "net/http"\n',
        },
    )

    assert len(result) == 1
    assert result[0].method == "GET"


# ─────────────────────────────────────────────────────────────────────────────
# Fix #10: Retry backoff constants are capped
# ─────────────────────────────────────────────────────────────────────────────


def test_generation_max_retries_is_three() -> None:
    from deepdoc.generator.generation import MAX_RETRIES

    assert MAX_RETRIES == 3


def test_pipeline_max_retries_is_three() -> None:
    from deepdoc.pipeline_v2 import MAX_RETRIES

    assert MAX_RETRIES == 3


def test_generation_backoff_is_capped() -> None:
    """_call_with_retry's *actual* sleep durations are clamped at 20.0s + jitter.

    Drives the real retry loop (not a re-derived formula) against an
    always-failing generator, with MAX_RETRIES bumped high enough that the
    unclamped exponential would blow past 20s if the min() clamp were ever
    removed from the source.
    """
    from unittest.mock import MagicMock, patch

    from deepdoc.generator import generation as generation_mod
    from deepdoc.generator.generation import BucketGenerationEngine

    engine = object.__new__(BucketGenerationEngine)
    engine.generator = MagicMock()
    engine.generator.generate.side_effect = RuntimeError("simulated 500 internal server error")

    fake_bucket = MagicMock()
    fake_bucket.title = "Fake Bucket"
    fake_evidence = MagicMock()
    fake_evidence.bucket = fake_bucket

    sleeps: list[float] = []
    with patch.object(generation_mod, "MAX_RETRIES", 8), patch(
        "time.sleep", side_effect=sleeps.append
    ):
        with pytest.raises(RuntimeError):
            engine._call_with_retry(fake_evidence, "", "", "")

    assert sleeps, "retry loop never slept — test isn't exercising the backoff path"
    assert max(sleeps) <= 20.0 + 1.5  # jitter adds up to 1.5s
    assert engine.generator.generate.call_count == 8


def test_pipeline_backoff_is_capped() -> None:
    """_call_llm_with_retry's *actual* sleep durations are clamped at 20.0s + jitter."""
    from unittest.mock import MagicMock, patch

    from deepdoc import pipeline_v2 as pipeline_mod
    from deepdoc.pipeline_v2 import PipelineV2

    pipeline = object.__new__(PipelineV2)
    pipeline.llm = MagicMock()
    pipeline.llm.complete.side_effect = RuntimeError("simulated 500 internal server error")

    sleeps: list[float] = []
    with patch.object(pipeline_mod, "MAX_RETRIES", 8), patch(
        "time.sleep", side_effect=sleeps.append
    ):
        with pytest.raises(RuntimeError):
            pipeline._call_llm_with_retry("some prompt")

    assert sleeps, "retry loop never slept — test isn't exercising the backoff path"
    assert max(sleeps) <= 20.0 + 1.5  # jitter adds up to 1.5s
    assert pipeline.llm.complete.call_count == 8
