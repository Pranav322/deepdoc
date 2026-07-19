"""Tests for parallelized pipeline operations and concurrency config."""

from __future__ import annotations

from pathlib import Path
import threading
import time
from unittest.mock import MagicMock, patch

from deepdoc.config import DEFAULT_CONFIG
from deepdoc.generator import BucketGenerationEngine, GenerationResult
from deepdoc.llm import ModelCapabilities
from deepdoc.parser.base import ParsedFile, Symbol
from deepdoc.planner import DocBucket, DocPlan, RepoScan, run_phase2_scans
from deepdoc.planner.bucket_refinement import _decompose_buckets


def _planner_llm() -> MagicMock:
    llm = MagicMock()
    llm.capabilities = ModelCapabilities(
        model="test",
        capability_model="test",
        context_window_tokens=128000,
        max_output_tokens=16000,
        source="test",
    )
    llm.output_reserve_tokens = 16000
    return llm


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


def _generation_engine(tmp_path: Path, buckets: list[DocBucket]) -> BucketGenerationEngine:
    plan = DocPlan(
        buckets=buckets,
        nav_structure={"Guide": [bucket.slug for bucket in buckets]},
        skipped_files=[],
    )
    scan = _make_scan(
        file_summaries={bucket.owned_files[0]: "summary" for bucket in buckets},
    )
    scan.file_content_hashes = {
        bucket.owned_files[0]: f"hash-{idx}" for idx, bucket in enumerate(buckets)
    }
    return BucketGenerationEngine(
        repo_root=tmp_path,
        cfg={
            "batch_size": 2,
            "max_parallel_workers": 2,
            "rate_limit_pause": 0,
        },
        llm=MagicMock(),
        scan=scan,
        plan=plan,
        output_dir=tmp_path / "docs",
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

    with patch("deepdoc.scanner.cluster_giant_file", side_effect=fake_cluster):
        # We need to also mock the other scan imports
        with patch("deepdoc.scanner.build_endpoint_bundles"), \
             patch("deepdoc.scanner.discover_integrations"), \
             patch("deepdoc.scanner.discover_artifacts") as mock_artifacts:
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

    with patch("deepdoc.planner.heuristics._llm_step", side_effect=fake_llm_step):
        _decompose_buckets(plan, scan, cfg, _planner_llm(), {})

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
    with patch("deepdoc.planner.heuristics._llm_step") as mock_llm:
        result = _decompose_buckets(plan, scan, cfg, _planner_llm(), {})

    mock_llm.assert_not_called()
    assert len(result.buckets) == 1


def test_decompose_second_pass_fires_for_oversized_sub_buckets():
    """Second-pass decompose should run for sub-buckets that come back oversized."""
    # First pass creates two sub-topics; one has 27 files (above max_files_per_bucket=25)
    oversized_files = [f"cart/file{i}.py" for i in range(27)]
    small_files = [f"order/file{i}.py" for i in range(5)]
    all_files = oversized_files + small_files

    scan_files = {f: "summary" for f in all_files}
    scan = _make_scan(
        file_summaries=scan_files,
        file_line_counts={f: 100 for f in all_files},
        parsed_files={
            f: ParsedFile(path=Path(f), language="python", imports=[], symbols=[])
            for f in all_files
        },
    )
    parent_bucket = _make_bucket(
        slug="shop-core",
        title="Shop Core",
        owned_files=all_files,
    )
    plan = DocPlan(
        buckets=[parent_bucket],
        nav_structure={"Features": ["shop-core"]},
        skipped_files=[],
    )

    call_count = {"n": 0}

    def fake_llm_step(llm, system, prompt, step_name):
        call_count["n"] += 1
        n = call_count["n"]
        if n == 1:
            # First pass: splits into one oversized + one normal sub-topic
            return {
                "sub_topics": [
                    {
                        "title": "Cart Ops",
                        "slug": "cart-ops",
                        "description": "Cart operations",
                        "owned_files": oversized_files,
                        "owned_symbols": [],
                        "required_sections": ["overview"],
                        "required_diagrams": [],
                    },
                    {
                        "title": "Order Ops",
                        "slug": "order-ops",
                        "description": "Order operations",
                        "owned_files": small_files,
                        "owned_symbols": [],
                        "required_sections": ["overview"],
                        "required_diagrams": [],
                    },
                ],
                "nav_section": "Features",
                "keep_parent_overview": False,
            }
        # Second pass splits the oversized cart-ops bucket into two halves
        half = len(oversized_files) // 2
        return {
            "sub_topics": [
                {
                    "title": "Cart Ops A",
                    "slug": "cart-ops-a",
                    "description": "Cart ops part A",
                    "owned_files": oversized_files[:half],
                    "owned_symbols": [],
                    "required_sections": ["overview"],
                    "required_diagrams": [],
                },
                {
                    "title": "Cart Ops B",
                    "slug": "cart-ops-b",
                    "description": "Cart ops part B",
                    "owned_files": oversized_files[half:],
                    "owned_symbols": [],
                    "required_sections": ["overview"],
                    "required_diagrams": [],
                },
            ],
            "nav_section": "Features",
            "keep_parent_overview": False,
        }

    cfg = {"decompose_threshold": 7, "max_files_per_bucket": 25, "max_parallel_workers": 2}

    with patch("deepdoc.planner.heuristics._llm_step", side_effect=fake_llm_step):
        result = _decompose_buckets(plan, scan, cfg, _planner_llm(), {})

    # LLM called twice: once for first pass, once for second pass on oversized bucket
    assert call_count["n"] == 2

    # No final bucket should have more than 25 files
    oversized_final = [b for b in result.buckets if len(b.owned_files) > 25]
    assert oversized_final == [], f"Still oversized: {[(b.slug, len(b.owned_files)) for b in oversized_final]}"


def test_decompose_second_pass_accepts_oversized_if_llm_returns_none():
    """When second-pass LLM returns None, the oversized bucket should be kept as-is."""
    oversized_files = [f"big/file{i}.py" for i in range(30)]
    scan = _make_scan(
        file_summaries={f: "s" for f in oversized_files},
        file_line_counts={f: 100 for f in oversized_files},
        parsed_files={
            f: ParsedFile(path=Path(f), language="python", imports=[], symbols=[])
            for f in oversized_files
        },
    )
    parent = _make_bucket(slug="big-feature", title="Big Feature", owned_files=oversized_files)
    plan = DocPlan(
        buckets=[parent],
        nav_structure={"Features": ["big-feature"]},
        skipped_files=[],
    )

    call_count = {"n": 0}

    def fake_llm_step(llm, system, prompt, step_name):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First pass: produces one oversized sub-topic
            return {
                "sub_topics": [
                    {
                        "title": "Big A",
                        "slug": "big-a",
                        "description": "All the big files",
                        "owned_files": oversized_files,
                        "owned_symbols": [],
                        "required_sections": ["overview"],
                        "required_diagrams": [],
                    },
                    {
                        "title": "Big B",
                        "slug": "big-b",
                        "description": "Placeholder",
                        "owned_files": [],
                        "owned_symbols": [],
                        "required_sections": ["overview"],
                        "required_diagrams": [],
                    },
                ],
                "nav_section": "Features",
                "keep_parent_overview": False,
            }
        # Second pass fails
        return None

    cfg = {"decompose_threshold": 7, "max_files_per_bucket": 25}

    with patch("deepdoc.planner.heuristics._llm_step", side_effect=fake_llm_step):
        result = _decompose_buckets(plan, scan, cfg, _planner_llm(), {})

    # Should not crash; the oversized bucket is accepted with a warning
    assert result is not None
    oversized_slugs = [b.slug for b in result.buckets if len(b.owned_files) > 25]
    assert "big-a" in oversized_slugs


# ═════════════════════════════════════════════════════════════════════════════
# Generator rate_limit_pause config
# ═════════════════════════════════════════════════════════════════════════════


def test_generator_reads_rate_limit_pause_from_config():
    """BucketGenerationEngine should read rate_limit_pause from config."""
    from deepdoc.generator import BucketGenerationEngine

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
    from deepdoc.generator.generation import RATE_LIMIT_PAUSE, BucketGenerationEngine

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


def test_generation_rolling_pool_starts_next_page_before_straggler_finishes(
    tmp_path: Path,
) -> None:
    buckets = [
        _make_bucket(f"page-{idx}", f"Page {idx}", [f"src/page-{idx}.py"])
        for idx in range(4)
    ]
    buckets[0].generation_hints = {"is_introduction_page": True}
    engine = _generation_engine(tmp_path, buckets)
    third_started = threading.Event()
    straggler_saw_third = []

    def generate(bucket, _):
        if bucket.slug == "page-0":
            straggler_saw_third.append(third_started.wait(timeout=1.0))
        elif bucket.slug == "page-2":
            third_started.set()
        else:
            time.sleep(0.01)
        return GenerationResult(bucket=bucket, content=f"# {bucket.title}\n")

    engine._generate_one = generate
    results = engine.generate_all(force=True)

    assert straggler_saw_third == [True]
    assert [result.bucket.slug for result in results] == [
        "page-0",
        "page-1",
        "page-2",
        "page-3",
    ]


def test_generation_results_stay_in_plan_order_when_completion_order_varies(
    tmp_path: Path,
) -> None:
    buckets = [
        _make_bucket(
            f"ordered-{idx}",
            f"Ordered {idx}",
            [f"src/ordered-{idx}.py"],
        )
        for idx in range(5)
    ]
    buckets[0].generation_hints = {"is_introduction_page": True}
    engine = _generation_engine(tmp_path, buckets)

    def generate(bucket, _):
        index = int(bucket.slug.rsplit("-", 1)[1])
        time.sleep((5 - index) * 0.005)
        return GenerationResult(bucket=bucket, content=f"# {bucket.title}\n")

    engine._generate_one = generate
    results = engine.generate_all(force=True)

    assert [result.bucket.slug for result in results] == [
        bucket.slug for bucket in buckets
    ]
