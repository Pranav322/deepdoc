from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from deepdoc.generator import BucketGenerationEngine
from deepdoc.plan_contract import (
    PlanContractError,
    bucket_output_path,
    bucket_site_path,
    validate_plan_contract,
)
from deepdoc.planner import DocBucket, DocPlan, RepoScan


def _bucket(
    slug: str,
    title: str | None = None,
    *,
    introduction: bool = False,
    prompt_style: str = "feature",
) -> DocBucket:
    return DocBucket(
        bucket_type="feature",
        title=title or slug.replace("-", " ").title(),
        slug=slug,
        section="Guide",
        description=f"Documentation for {slug}",
        owned_files=[f"src/{slug}.py"],
        generation_hints={
            "is_introduction_page": introduction,
            "prompt_style": prompt_style,
        },
    )


def _plan(buckets: list[DocBucket], nav: dict[str, list[str]]) -> DocPlan:
    return DocPlan(buckets=buckets, nav_structure=nav, skipped_files=[])


def _scan() -> RepoScan:
    return RepoScan(
        file_tree={},
        file_summaries={},
        api_endpoints=[],
        languages={},
        has_openapi=False,
        openapi_paths=[],
        total_files=0,
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
    )


def test_validate_plan_contract_accepts_one_intro_and_resolved_nav() -> None:
    intro = _bucket("start-here", introduction=True)
    feature = _bucket("orders")
    plan = _plan([intro, feature], {"Start Here": ["start-here"], "Guide": ["orders"]})

    validate_plan_contract(plan)

    assert bucket_output_path(intro) == "index.md"
    assert bucket_site_path(intro) == "/"
    assert bucket_output_path(feature) == "orders.md"
    assert bucket_site_path(feature) == "/orders"


def test_validate_plan_contract_rejects_missing_introduction() -> None:
    plan = _plan([_bucket("orders")], {"Guide": ["orders"]})

    with pytest.raises(PlanContractError, match="found 0: none"):
        validate_plan_contract(plan)


def test_validate_plan_contract_rejects_multiple_introductions_and_writers() -> None:
    plan = _plan(
        [_bucket("intro-z", introduction=True), _bucket("intro-a", introduction=True)],
        {"Start Here": ["intro-z", "intro-a"]},
    )

    with pytest.raises(PlanContractError) as exc_info:
        validate_plan_contract(plan)

    message = str(exc_info.value)
    assert "expected exactly one introduction bucket; found 2: intro-a, intro-z" in message
    assert "duplicate output writer: index.md <- intro-a, intro-z" in message


def test_validate_plan_contract_rejects_duplicate_slug_and_output() -> None:
    plan = _plan(
        [_bucket("start-here", introduction=True), _bucket("orders", "Orders A"), _bucket("orders", "Orders B")],
        {"Start Here": ["start-here"], "Guide": ["orders"]},
    )

    with pytest.raises(PlanContractError) as exc_info:
        validate_plan_contract(plan)

    message = str(exc_info.value)
    assert "duplicate bucket slug: orders <- Orders A, Orders B" in message
    assert "duplicate output writer: orders.md <- orders, orders" in message


def test_validate_plan_contract_rejects_unresolved_nav_slug() -> None:
    plan = _plan(
        [_bucket("start-here", introduction=True)],
        {"Guide": ["missing-page"], "Start Here": ["start-here"]},
    )

    with pytest.raises(PlanContractError, match="unresolved nav slug: Guide -> missing-page"):
        validate_plan_contract(plan)


def test_validate_plan_contract_allows_system_whats_changed_nav() -> None:
    plan = _plan(
        [_bucket("start-here", introduction=True)],
        {"Start Here": ["start-here", "whats-changed"]},
    )

    validate_plan_contract(plan)


def test_validate_plan_contract_rejects_duplicate_nav_reference() -> None:
    plan = _plan(
        [_bucket("start-here", introduction=True), _bucket("orders")],
        {"Features": ["orders"], "Guide": ["orders"], "Start Here": ["start-here"]},
    )

    with pytest.raises(PlanContractError, match="duplicate nav reference: orders <- Features, Guide"):
        validate_plan_contract(plan)


def test_plan_contract_errors_are_deterministic() -> None:
    intro_a = _bucket("intro-a", introduction=True)
    intro_z = _bucket("intro-z", introduction=True)
    plan_a = _plan([intro_z, intro_a], {"Z": ["missing-z"], "A": ["missing-a"]})
    plan_b = _plan([intro_a, intro_z], {"A": ["missing-a"], "Z": ["missing-z"]})

    with pytest.raises(PlanContractError) as first:
        validate_plan_contract(plan_a)
    with pytest.raises(PlanContractError) as second:
        validate_plan_contract(plan_b)

    assert str(first.value) == str(second.value)


def test_overview_prompt_style_does_not_claim_index_without_intro_hint() -> None:
    bucket = _bucket("architecture", prompt_style="overview")

    assert bucket_output_path(bucket) == "architecture.md"
    assert bucket_site_path(bucket) == "/architecture"


def test_generate_all_rejects_duplicate_writers_before_worker_starts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan(
        [_bucket("intro-a", introduction=True), _bucket("intro-b", introduction=True)],
        {"Start Here": ["intro-a", "intro-b"]},
    )
    engine = BucketGenerationEngine(
        repo_root=tmp_path,
        cfg={},
        llm=MagicMock(),
        scan=_scan(),
        plan=plan,
        output_dir=tmp_path / "docs",
    )
    generate_one = MagicMock()
    monkeypatch.setattr(engine, "_generate_one", generate_one)

    with pytest.raises(PlanContractError):
        engine.generate_all(force=True)

    generate_one.assert_not_called()
    assert not (tmp_path / "docs" / "index.md").exists()


def test_incremental_engine_validates_full_plan_not_stale_subset(tmp_path: Path) -> None:
    intro = _bucket("start-here", introduction=True)
    feature = _bucket("orders")
    full_plan = _plan(
        [intro, feature],
        {"Start Here": ["start-here"], "Guide": ["orders"]},
    )
    engine = BucketGenerationEngine(
        repo_root=tmp_path,
        cfg={},
        llm=MagicMock(),
        scan=_scan(),
        plan=full_plan,
        output_dir=tmp_path / "docs",
    )
    engine.plan = _plan([feature], full_plan.nav_structure)

    validate_plan_contract(engine.contract_plan)
    with pytest.raises(PlanContractError, match="found 0"):
        validate_plan_contract(engine.plan)
