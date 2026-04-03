"""Tests for planner consolidation and dedup logic (Changes 3, 4, 5)."""

from __future__ import annotations

from pathlib import Path

from deepdoc.planner_v2 import (
    DocBucket,
    DocPlan,
    RepoScan,
    _consolidate_similar_buckets,
    _should_decompose,
)
from deepdoc.parser.base import ParsedFile, Symbol


def _make_scan(
    *,
    file_summaries: dict[str, str] | None = None,
    file_line_counts: dict[str, int] | None = None,
    parsed_files: dict[str, ParsedFile] | None = None,
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
        file_contents={},
        giant_file_clusters=giant_file_clusters or {},
    )


def _make_bucket(
    slug: str,
    title: str,
    section: str = "Integrations",
    description: str = "",
    owned_files: list[str] | None = None,
    owned_symbols: list[str] | None = None,
    parent_slug: str | None = None,
    generation_hints: dict | None = None,
    bucket_type: str = "integration",
    required_sections: list[str] | None = None,
    required_diagrams: list[str] | None = None,
    coverage_targets: list[str] | None = None,
) -> DocBucket:
    return DocBucket(
        bucket_type=bucket_type,
        title=title,
        slug=slug,
        section=section,
        description=description or f"Documentation for {title}",
        owned_files=owned_files or [],
        owned_symbols=owned_symbols or [],
        parent_slug=parent_slug,
        generation_hints=generation_hints or {},
        required_sections=required_sections or ["overview"],
        required_diagrams=required_diagrams or [],
        coverage_targets=coverage_targets or [],
    )


# ═════════════════════════════════════════════════════════════════════════════
# Tests for _should_decompose (Change 3: raised thresholds)
# ═════════════════════════════════════════════════════════════════════════════


def test_should_decompose_below_new_threshold():
    """Buckets with 5-6 files should NOT decompose with new threshold of 7."""
    scan = _make_scan(
        file_summaries={f"file{i}.py": f"File {i}" for i in range(6)},
        parsed_files={
            f"file{i}.py": ParsedFile(
                path=Path(f"file{i}.py"),
                language="python",
                imports=[],
                symbols=[Symbol(name=f"func{i}", kind="function", signature=f"def func{i}()", start_line=1, end_line=10)],
            )
            for i in range(6)
        },
    )
    bucket = _make_bucket(
        slug="test-bucket",
        title="Test Bucket",
        owned_files=[f"file{i}.py" for i in range(6)],
    )
    # With threshold=7 (new default), 6 files should NOT trigger decompose
    assert _should_decompose(bucket, scan, threshold=7) is False


def test_should_decompose_at_new_threshold():
    """Buckets with 7+ files SHOULD decompose."""
    scan = _make_scan(
        file_summaries={f"file{i}.py": f"File {i}" for i in range(7)},
        parsed_files={},
    )
    bucket = _make_bucket(
        slug="test-bucket",
        title="Test Bucket",
        owned_files=[f"file{i}.py" for i in range(7)],
    )
    assert _should_decompose(bucket, scan, threshold=7) is True


def test_should_decompose_symbol_threshold_raised():
    """Symbol-based decompose requires 40+ symbols AND 5+ files now."""
    symbols = [
        Symbol(name=f"func{i}", kind="function", signature=f"def func{i}()", start_line=i * 10, end_line=i * 10 + 9)
        for i in range(30)  # 30 symbols — above old threshold of 25 but below new 40
    ]
    scan = _make_scan(
        file_summaries={f"file{i}.py": f"File {i}" for i in range(4)},
        parsed_files={
            "file0.py": ParsedFile(
                path=Path("file0.py"), language="python", imports=[], symbols=symbols
            ),
            **{
                f"file{i}.py": ParsedFile(
                    path=Path(f"file{i}.py"), language="python", imports=[], symbols=[]
                )
                for i in range(1, 4)
            },
        },
    )
    bucket = _make_bucket(
        slug="test-bucket",
        title="Test Bucket",
        owned_files=[f"file{i}.py" for i in range(4)],
    )
    # 30 symbols, 4 files — doesn't meet new threshold (40 symbols, 5 files)
    assert _should_decompose(bucket, scan, threshold=7) is False


def test_should_decompose_giant_file_still_triggers():
    """Giant file should still trigger decompose regardless of file count."""

    class FakeCluster:
        clusters = [type("C", (), {"cluster_name": "cluster1"})()]

    scan = _make_scan(
        file_summaries={"giant.py": "Giant file"},
        giant_file_clusters={"giant.py": FakeCluster()},
    )
    bucket = _make_bucket(
        slug="test-bucket",
        title="Test Bucket",
        owned_files=["giant.py"],
    )
    assert _should_decompose(bucket, scan, threshold=7) is True


def test_should_decompose_skips_endpoint_ref():
    """Endpoint ref buckets should never decompose."""
    scan = _make_scan(
        file_summaries={f"file{i}.py": f"File {i}" for i in range(10)},
    )
    bucket = _make_bucket(
        slug="get-orders",
        title="GET /api/orders",
        owned_files=[f"file{i}.py" for i in range(10)],
        generation_hints={"is_endpoint_ref": True},
    )
    assert _should_decompose(bucket, scan, threshold=7) is False


# ═════════════════════════════════════════════════════════════════════════════
# Tests for _consolidate_similar_buckets (Change 4)
# ═════════════════════════════════════════════════════════════════════════════


def test_consolidate_merges_highly_similar_buckets():
    """Two buckets in the same section with overlapping titles/descriptions merge."""
    plan = DocPlan(
        buckets=[
            _make_bucket(
                slug="vinculum-overview",
                title="Vinculum Warehouse Integration Overview",
                section="Integrations",
                description="Overview of Vinculum warehouse order return integration",
                owned_files=["vinculum_client.py", "vinculum_config.py"],
            ),
            _make_bucket(
                slug="vinculum-workflow",
                title="Vinculum Order Return and Exchange Workflow",
                section="Integrations",
                description="Vinculum warehouse order return exchange workflow processing",
                owned_files=["vinculum_tasks.py", "vinculum_sync.py"],
            ),
        ],
        nav_structure={"Integrations": ["vinculum-overview", "vinculum-workflow"]},
        skipped_files=[],
    )
    cfg = {"consolidation_similarity_threshold": 0.40}
    result = _consolidate_similar_buckets(plan, cfg)

    assert len(result.buckets) == 1
    merged = result.buckets[0]
    # All files preserved
    assert set(merged.owned_files) == {
        "vinculum_client.py",
        "vinculum_config.py",
        "vinculum_tasks.py",
        "vinculum_sync.py",
    }


def test_consolidate_preserves_different_sections():
    """Buckets in different sections with similar names should NOT merge."""
    plan = DocPlan(
        buckets=[
            _make_bucket(
                slug="auth-overview",
                title="Authentication Overview",
                section="Architecture",
                description="Auth middleware overview",
                owned_files=["auth.py"],
            ),
            _make_bucket(
                slug="auth-integration",
                title="Authentication Integration",
                section="Integrations",
                description="Auth provider integration details",
                owned_files=["auth_provider.py"],
            ),
        ],
        nav_structure={
            "Architecture": ["auth-overview"],
            "Integrations": ["auth-integration"],
        },
        skipped_files=[],
    )
    cfg = {"consolidation_similarity_threshold": 0.55}
    result = _consolidate_similar_buckets(plan, cfg)

    # Different sections — should NOT merge
    assert len(result.buckets) == 2


def test_consolidate_does_not_merge_dissimilar():
    """Buckets with low overlap should NOT merge even in same section."""
    plan = DocPlan(
        buckets=[
            _make_bucket(
                slug="order-flow",
                title="Order Processing Flow",
                section="Core Features",
                description="Complete order lifecycle from creation to fulfillment",
                owned_files=["orders.py"],
            ),
            _make_bucket(
                slug="payment-gateway",
                title="Payment Gateway Integration",
                section="Core Features",
                description="Juspay and Razorpay payment processing",
                owned_files=["payments.py"],
            ),
        ],
        nav_structure={"Core Features": ["order-flow", "payment-gateway"]},
        skipped_files=[],
    )
    cfg = {"consolidation_similarity_threshold": 0.55}
    result = _consolidate_similar_buckets(plan, cfg)

    assert len(result.buckets) == 2


def test_consolidate_skips_introduction_pages():
    """Introduction/overview pages should never be merge targets or victims."""
    plan = DocPlan(
        buckets=[
            _make_bucket(
                slug="architecture-overview",
                title="System Architecture Overview",
                section="Architecture",
                description="Architecture overview of the system",
                generation_hints={"is_introduction_page": True},
                owned_files=["app.py"],
            ),
            _make_bucket(
                slug="architecture-details",
                title="System Architecture Details",
                section="Architecture",
                description="Architecture details and design decisions",
                owned_files=["design.py"],
            ),
        ],
        nav_structure={"Architecture": ["architecture-overview", "architecture-details"]},
        skipped_files=[],
    )
    cfg = {"consolidation_similarity_threshold": 0.3}  # Very low threshold
    result = _consolidate_similar_buckets(plan, cfg)

    # Introduction page should be preserved even with low threshold
    assert len(result.buckets) == 2


def test_consolidate_skips_endpoint_refs():
    """Endpoint ref pages should never be merged."""
    plan = DocPlan(
        buckets=[
            _make_bucket(
                slug="get-orders",
                title="GET /api/orders",
                section="API Reference",
                description="Get orders endpoint",
                generation_hints={"is_endpoint_ref": True},
                owned_files=["views.py"],
            ),
            _make_bucket(
                slug="list-orders",
                title="GET /api/orders/list",
                section="API Reference",
                description="List orders endpoint",
                generation_hints={"is_endpoint_ref": True},
                owned_files=["views.py"],
            ),
        ],
        nav_structure={"API Reference": ["get-orders", "list-orders"]},
        skipped_files=[],
    )
    cfg = {"consolidation_similarity_threshold": 0.3}
    result = _consolidate_similar_buckets(plan, cfg)

    assert len(result.buckets) == 2


def test_consolidate_merges_same_parent_children():
    """Sub-topics with the same parent and high overlap should merge."""
    plan = DocPlan(
        buckets=[
            _make_bucket(
                slug="refund-modes-convozen",
                title="Refund Modes and Constants for Convozen Integration",
                section="Integrations > Convozen",
                description="Refund modes constants used in Convozen integration",
                parent_slug="convozen-api",
                owned_files=["constants.py"],
            ),
            _make_bucket(
                slug="refund-modes-webhook",
                title="Refund Modes and Constants for Webhook Integrations",
                section="Integrations > Convozen",
                description="Refund modes constants used in webhook integrations",
                parent_slug="convozen-api",
                owned_files=["constants.py", "webhook_constants.py"],
            ),
        ],
        nav_structure={
            "Integrations > Convozen": ["refund-modes-convozen", "refund-modes-webhook"]
        },
        skipped_files=[],
    )
    cfg = {"consolidation_similarity_threshold": 0.45}
    result = _consolidate_similar_buckets(plan, cfg)

    assert len(result.buckets) == 1
    merged = result.buckets[0]
    assert "constants.py" in merged.owned_files
    assert "webhook_constants.py" in merged.owned_files


def test_consolidate_nav_structure_cleaned():
    """Nav structure should be cleaned after merging — no dangling slugs."""
    plan = DocPlan(
        buckets=[
            _make_bucket(
                slug="vinculum-overview",
                title="Vinculum Warehouse Integration Overview",
                section="Integrations",
                description="Overview of Vinculum warehouse integration",
                owned_files=["vinculum.py"],
            ),
            _make_bucket(
                slug="vinculum-status",
                title="Vinculum Order Return Status Synchronization",
                section="Integrations",
                description="Vinculum order return status sync integration",
                owned_files=["vinculum_sync.py"],
            ),
            _make_bucket(
                slug="juspay-integration",
                title="Juspay Payment Gateway",
                section="Integrations",
                description="Juspay payment gateway integration",
                owned_files=["juspay.py"],
            ),
        ],
        nav_structure={
            "Integrations": ["vinculum-overview", "vinculum-status", "juspay-integration"]
        },
        skipped_files=[],
    )
    cfg = {"consolidation_similarity_threshold": 0.40}
    result = _consolidate_similar_buckets(plan, cfg)

    # Vinculum buckets should merge, Juspay stays
    remaining_slugs = {b.slug for b in result.buckets}
    for section, slugs in result.nav_structure.items():
        for slug in slugs:
            assert slug in remaining_slugs, f"Dangling slug '{slug}' in nav_structure"


def test_consolidate_merges_required_sections_and_diagrams():
    """Merged bucket should have combined required_sections and required_diagrams."""
    plan = DocPlan(
        buckets=[
            _make_bucket(
                slug="vinculum-overview",
                title="Vinculum Warehouse Integration Overview",
                section="Integrations",
                description="Vinculum warehouse integration overview and setup",
                owned_files=["vinculum.py"],
                required_sections=["overview", "setup"],
                required_diagrams=["architecture_flow"],
            ),
            _make_bucket(
                slug="vinculum-workflow",
                title="Vinculum Warehouse Integration Workflow",
                section="Integrations",
                description="Vinculum warehouse integration workflow and processing",
                owned_files=["vinculum_tasks.py"],
                required_sections=["overview", "workflow", "error_handling"],
                required_diagrams=["sequence_diagram"],
            ),
        ],
        nav_structure={"Integrations": ["vinculum-overview", "vinculum-workflow"]},
        skipped_files=[],
    )
    cfg = {"consolidation_similarity_threshold": 0.35}
    result = _consolidate_similar_buckets(plan, cfg)

    assert len(result.buckets) == 1
    merged = result.buckets[0]
    # Should have union of required_sections (deduplicated)
    assert "overview" in merged.required_sections
    assert "setup" in merged.required_sections
    assert "workflow" in merged.required_sections
    assert "error_handling" in merged.required_sections
    # Should have union of required_diagrams
    assert "architecture_flow" in merged.required_diagrams
    assert "sequence_diagram" in merged.required_diagrams


def test_consolidate_chain_merges():
    """If A merges into B and B merges into C, A's files should end up in C."""
    plan = DocPlan(
        buckets=[
            _make_bucket(
                slug="vinculum-main",
                title="Vinculum Warehouse Integration",
                section="Integrations",
                description="Vinculum warehouse integration main",
                owned_files=["vinculum.py", "vinculum_client.py", "vinculum_config.py"],
            ),
            _make_bucket(
                slug="vinculum-sync",
                title="Vinculum Warehouse Status Synchronization",
                section="Integrations",
                description="Vinculum warehouse status sync integration",
                owned_files=["vinculum_sync.py"],
            ),
            _make_bucket(
                slug="vinculum-return",
                title="Vinculum Warehouse Order Return Processing",
                section="Integrations",
                description="Vinculum warehouse order return processing integration",
                owned_files=["vinculum_return.py"],
            ),
        ],
        nav_structure={
            "Integrations": ["vinculum-main", "vinculum-sync", "vinculum-return"]
        },
        skipped_files=[],
    )
    cfg = {"consolidation_similarity_threshold": 0.40}
    result = _consolidate_similar_buckets(plan, cfg)

    # All three should collapse into one
    assert len(result.buckets) == 1
    merged = result.buckets[0]
    assert len(merged.owned_files) == 5


def test_consolidate_respects_threshold_config():
    """Higher threshold should prevent merges that happen at lower threshold."""
    buckets = [
        _make_bucket(
            slug="vinculum-overview",
            title="Vinculum Warehouse Integration Overview",
            section="Integrations",
            description="Vinculum warehouse integration overview",
            owned_files=["vinculum.py"],
        ),
        _make_bucket(
            slug="vinculum-workflow",
            title="Vinculum Order Return Workflow Integration",
            section="Integrations",
            description="Vinculum order return workflow integration",
            owned_files=["vinculum_tasks.py"],
        ),
    ]

    # Low threshold — should merge
    plan_low = DocPlan(
        buckets=[DocBucket(**{k: list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v for k, v in b.__dict__.items() if not k.startswith("_")}) for b in buckets],
        nav_structure={"Integrations": ["vinculum-overview", "vinculum-workflow"]},
        skipped_files=[],
    )
    result_low = _consolidate_similar_buckets(plan_low, {"consolidation_similarity_threshold": 0.30})

    # Very high threshold — should NOT merge
    plan_high = DocPlan(
        buckets=[DocBucket(**{k: list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v for k, v in b.__dict__.items() if not k.startswith("_")}) for b in buckets],
        nav_structure={"Integrations": ["vinculum-overview", "vinculum-workflow"]},
        skipped_files=[],
    )
    result_high = _consolidate_similar_buckets(plan_high, {"consolidation_similarity_threshold": 0.95})

    assert len(result_low.buckets) == 1
    assert len(result_high.buckets) == 2


def test_consolidate_no_merges_returns_plan_unchanged():
    """When nothing merges, the plan should come back identical."""
    plan = DocPlan(
        buckets=[
            _make_bucket(
                slug="orders",
                title="Order Processing",
                section="Core",
                description="Order lifecycle management",
                owned_files=["orders.py"],
            ),
            _make_bucket(
                slug="payments",
                title="Payment Gateway",
                section="Integrations",
                description="Juspay payment processing",
                owned_files=["payments.py"],
            ),
        ],
        nav_structure={"Core": ["orders"], "Integrations": ["payments"]},
        skipped_files=[],
    )
    cfg = {"consolidation_similarity_threshold": 0.55}
    result = _consolidate_similar_buckets(plan, cfg)

    assert len(result.buckets) == 2
    assert result.nav_structure == {"Core": ["orders"], "Integrations": ["payments"]}
