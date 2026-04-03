"""Tests for parallelized pipeline operations and concurrency config."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

from deepdoc.planner_v2 import (
    DocBucket,
    DocPlan,
    RepoScan,
    _decompose_buckets,
    run_phase2_scans,
)
from deepdoc.parser.base import ParsedFile, Symbol
from deepdoc.config import DEFAULT_CONFIG


def _make_scan(
    *,
    file_summaries: dict[str, str] | None = None,
    file_line_counts: dict[str, int] | None = None,
    parsed_files: dict[str, ParsedFile] | None = None,
    file_contents: dict[str, str] | None = None,
    giant_file_clusters: dict[str, object] | None = None,
) -> RepoScan:
    summaries = file_summaries or {}
    return RepoScan(
        file_tree={},
        file_summaries=summaries,
        api_endpoints=[],
        languages={"python": max(len(summaries), 1)},
        has_openapi=False,
        openapi_paths=[],
        total_files=len(summaries),
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
        file_line_counts=file_line_counts or {},
        parsed_files=parsed_files or {},
        file_contents=file_contents or {},
        giant_file_clusters=giant_file_clusters or {},
    )


def _make_bucket(
    slug: str,
    title: str,
    owned_files: list[str],
    section: str = "Features",
    description: str = "",
) -> DocBucket:
    return DocBucket(
        bucket_type="feature",
        title=title,
        slug=slug,
        section=section,
        description=description or f"Docs for {title}",
        owned_files=owned_files,
    )


# ═════════════════════════════════════════════════════════════════════════════
# Config defaults
# ═════════════════════════════════════════════════════════════════════════════


def test_default_config_includes_concurrency_settings():
    """DEFAULT_CONFIG should include max_parallel_workers and rate_limit_pause."""
    assert "max_parallel_workers" in DEFAULT_CONFIG
    assert DEFAULT_CONFIG["max_parallel_workers"] == 6
    assert "rate_limit_pause" in DEFAULT_CONFIG
    assert DEFAULT_CONFIG["rate_limit_pause"] == 0.5


def test_default_config_decompose_threshold_is_seven():
    """decompose_threshold should default to 7 (raised from 5)."""
    assert DEFAULT_CONFIG["decompose_threshold"] == 7


# ═════════════════════════════════════════════════════════════════════════════
# Giant-file clustering parallelization
# ═════════════════════════════════════════════════════════════════════════════


def test_giant_file_clustering_uses_thread_pool():
    """Giant-file clustering should use ThreadPoolExecutor for parallel LLM calls."""
    # Create scan with 3 giant files
    paths = [f"giant{i}.py" for i in range(3)]
    scan = _make_scan(
        file_summaries={p: f"Giant file {p}" for p in paths},
        file_line_counts={p: 3000 for p in paths},
        parsed_files={
            p: ParsedFile(
                path=Path(p),
                language="python",
                imports=[],
                symbols=[
                    Symbol(
                        name="BigClass",
                        kind="class",
                        signature="class BigClass:",
                        start_line=1,
                        end_line=3000,
                    )
                ],
            )
            for p in paths
        },
        file_contents={p: "# big file\n" * 3000 for p in paths},
    )

    class FakeAnalysis:
        clusters = [type("C", (), {"cluster_name": "cluster1"})()]

    call_count = 0
    call_times = []

    def fake_cluster(path, parsed, content, llm):
        nonlocal call_count
        call_count += 1
        call_times.append(time.monotonic())
        time.sleep(0.05)  # simulate LLM latency
        return FakeAnalysis()

    cfg = {"giant_file_lines": 2000, "max_parallel_workers": 3}

    with patch("deepdoc.scan_v2.cluster_giant_file", side_effect=fake_cluster) as mock_cluster:
        # We need to also mock the other scan imports
        with patch("deepdoc.scan_v2.build_endpoint_bundles"), \
             patch("deepdoc.scan_v2.discover_integrations"), \
             patch("deepdoc.scan_v2.discover_artifacts") as mock_artifacts:
            # Mock artifact scan return
            mock_artifact_result = MagicMock()
            mock_artifact_result.setup_artifacts = []
            mock_artifact_result.deploy_artifacts = []
            mock_artifact_result.ci_artifacts = []
            mock_artifact_result.test_artifacts = []
            mock_artifact_result.ops_artifacts = []
            mock_artifact_result.database_scan = None
            mock_artifacts.return_value = mock_artifact_result

            result_scan = run_phase2_scans(scan, cfg, MagicMock())

    # All 3 files should have been clustered
    assert call_count == 3
    assert len(result_scan.giant_file_clusters) == 3

    # Calls should have been roughly concurrent (not sequential)
    # With 3 workers and 0.05s each, total should be ~0.05s not ~0.15s
    if len(call_times) >= 2:
        # At least 2 calls should have started within 0.03s of each other
        time_diffs = [call_times[i + 1] - call_times[i] for i in range(len(call_times) - 1)]
        min_diff = min(time_diffs)
        assert min_diff < 0.04, f"Calls seem sequential, min gap: {min_diff:.3f}s"


# ═════════════════════════════════════════════════════════════════════════════
# Decompose parallelization
# ═════════════════════════════════════════════════════════════════════════════


def test_decompose_parallelizes_llm_calls():
    """Decompose should fire LLM calls in parallel for multiple eligible buckets."""
    # Create 3 buckets that need decomposing (8 files each, above threshold of 7)
    buckets = []
    scan_files = {}
    scan_line_counts = {}
    scan_parsed = {}

    for b_idx in range(3):
        files = [f"feature{b_idx}/file{i}.py" for i in range(8)]
        for f in files:
            scan_files[f] = f"File in feature {b_idx}"
            scan_line_counts[f] = 100
            scan_parsed[f] = ParsedFile(
                path=Path(f), language="python", imports=[], symbols=[]
            )
        buckets.append(
            _make_bucket(
                slug=f"feature-{b_idx}",
                title=f"Feature {b_idx}",
                owned_files=files,
            )
        )

    scan = _make_scan(
        file_summaries=scan_files,
        file_line_counts=scan_line_counts,
        parsed_files=scan_parsed,
    )

    plan = DocPlan(
        buckets=buckets,
        nav_structure={"Features": [b.slug for b in buckets]},
        skipped_files=[],
    )

    call_times = []

    def fake_llm_step(llm, system, prompt, step_name):
        call_times.append(time.monotonic())
        time.sleep(0.05)  # simulate LLM latency
        # Return a valid decompose result
        return {
            "sub_topics": [
                {
                    "title": f"Sub A of {step_name}",
                    "slug": f"sub-a-{step_name}",
                    "description": "Sub topic A",
                    "owned_files": [],
                    "owned_symbols": [],
                    "required_sections": ["overview"],
                    "required_diagrams": [],
                },
                {
                    "title": f"Sub B of {step_name}",
                    "slug": f"sub-b-{step_name}",
                    "description": "Sub topic B",
                    "owned_files": [],
                    "owned_symbols": [],
                    "required_sections": ["overview"],
                    "required_diagrams": [],
                },
            ],
            "nav_section": "Features > Decomposed",
            "keep_parent_overview": False,
        }

    cfg = {"decompose_threshold": 7, "max_parallel_workers": 3}

    with patch("deepdoc.planner_v2._llm_step", side_effect=fake_llm_step):
        result = _decompose_buckets(plan, scan, cfg, MagicMock(), {})

    # Should have called LLM 3 times (one per bucket)
    assert len(call_times) == 3

    # Calls should have been concurrent
    if len(call_times) >= 2:
        time_diffs = [call_times[i + 1] - call_times[i] for i in range(len(call_times) - 1)]
        min_diff = min(time_diffs)
        assert min_diff < 0.04, f"Decompose calls seem sequential, min gap: {min_diff:.3f}s"


def test_decompose_no_candidates_returns_plan_unchanged():
    """If no buckets need decomposing, plan should be returned as-is."""
    buckets = [
        _make_bucket(
            slug="small-bucket",
            title="Small Bucket",
            owned_files=["file1.py", "file2.py"],
        )
    ]
    scan = _make_scan(
        file_summaries={"file1.py": "f1", "file2.py": "f2"},
        parsed_files={},
    )
    plan = DocPlan(
        buckets=buckets,
        nav_structure={"Features": ["small-bucket"]},
        skipped_files=[],
    )
    cfg = {"decompose_threshold": 7}

    # Should not call LLM at all
    with patch("deepdoc.planner_v2._llm_step") as mock_llm:
        result = _decompose_buckets(plan, scan, cfg, MagicMock(), {})

    mock_llm.assert_not_called()
    assert len(result.buckets) == 1


# ═════════════════════════════════════════════════════════════════════════════
# Generator rate_limit_pause config
# ═════════════════════════════════════════════════════════════════════════════


def test_generator_reads_rate_limit_pause_from_config():
    """BucketGenerationEngine should read rate_limit_pause from config."""
    from deepdoc.generator_v2 import BucketGenerationEngine, RATE_LIMIT_PAUSE

    cfg = {
        "rate_limit_pause": 0.1,
        "max_parallel_workers": 2,
        "batch_size": 5,
        "source_context_budget": 200000,
        "llm": {"provider": "anthropic", "model": "test", "temperature": 0.2},
    }
    scan = _make_scan()
    plan = DocPlan(buckets=[], nav_structure={}, skipped_files=[])

    engine = BucketGenerationEngine(
        repo_root=Path("/tmp/test"),
        cfg=cfg,
        llm=MagicMock(),
        scan=scan,
        plan=plan,
        output_dir=Path("/tmp/test/docs"),
    )

    assert engine.rate_limit_pause == 0.1
    assert engine.max_workers == 2
    assert engine.batch_size == 5


def test_generator_uses_default_rate_limit_pause():
    """Without config override, should use the module-level default."""
    from deepdoc.generator_v2 import BucketGenerationEngine, RATE_LIMIT_PAUSE

    cfg = {
        "source_context_budget": 200000,
        "llm": {"provider": "anthropic", "model": "test", "temperature": 0.2},
    }
    scan = _make_scan()
    plan = DocPlan(buckets=[], nav_structure={}, skipped_files=[])

    engine = BucketGenerationEngine(
        repo_root=Path("/tmp/test"),
        cfg=cfg,
        llm=MagicMock(),
        scan=scan,
        plan=plan,
        output_dir=Path("/tmp/test/docs"),
    )

    assert engine.rate_limit_pause == RATE_LIMIT_PAUSE
