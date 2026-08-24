from __future__ import annotations

from deepdoc.plan_contract import validate_plan_contract
from deepdoc.planner.merge import merge_unit_plans, missing_files
from deepdoc.v2_models import DocBucket, DocPlan


def _intro(slug: str = "start-here") -> DocBucket:
    return DocBucket(
        bucket_type="start_here_index",
        title="Start Here",
        slug=slug,
        section="Start Here",
        description="orientation",
        owned_files=["a.py"],
        generation_hints={"is_introduction_page": True},
    )


def _feature(slug: str, owned_files: list[str], depends_on: list[str] | None = None) -> DocBucket:
    return DocBucket(
        bucket_type="feature",
        title=slug,
        slug=slug,
        section="Features",
        description="d",
        owned_files=owned_files,
        depends_on=depends_on or [],
    )


def _plan(buckets: list[DocBucket], nav: dict[str, list[str]], skipped=None, orphaned=None) -> DocPlan:
    return DocPlan(
        buckets=buckets,
        nav_structure=nav,
        skipped_files=skipped or [],
        orphaned_files=orphaned or [],
    )


def test_single_unit_plan_is_returned_unchanged() -> None:
    plan = _plan([_intro(), _feature("feature", ["a.py"])], {"Start Here": ["start-here"], "Features": ["feature"]})

    merged = merge_unit_plans([("core", plan)])

    assert merged is plan


def test_two_units_with_same_local_slug_get_namespaced() -> None:
    plan_a = _plan([_intro(), _feature("feature", ["a.py"])], {"Start Here": ["start-here"], "Features": ["feature"]})
    plan_b = _plan([_intro(), _feature("feature", ["b.py"])], {"Start Here": ["start-here"], "Features": ["feature"]})

    merged = merge_unit_plans([("orders", plan_a), ("payments", plan_b)])
    slugs = sorted(b.slug for b in merged.buckets)

    assert slugs == ["orders/feature", "payments/feature", "payments/start-here", "start-here"]
    validate_plan_contract(merged)


def test_depends_on_and_parent_slug_are_rewritten() -> None:
    child = _feature("worker", ["a.py"], depends_on=["feature"])
    child.parent_slug = "feature"
    plan_a = _plan(
        [_intro(), _feature("feature", ["a.py"]), child],
        {"Start Here": ["start-here"], "Features": ["feature", "worker"]},
    )

    merged = merge_unit_plans([("orders", plan_a), ("payments", _plan([_intro()], {"Start Here": ["start-here"]}))])
    worker = next(b for b in merged.buckets if b.title == "worker")

    assert worker.depends_on == ["orders/feature"]
    assert worker.parent_slug == "orders/feature"


def test_multiple_introductions_merge_to_exactly_one() -> None:
    plan_a = _plan([_intro(), _feature("feature", ["a.py"])], {"Start Here": ["start-here"], "Features": ["feature"]})
    plan_b = _plan([_intro(), _feature("feature", ["b.py"])], {"Start Here": ["start-here"], "Features": ["feature"]})

    merged = merge_unit_plans([("orders", plan_a), ("payments", plan_b)])

    introductions = [b for b in merged.buckets if (b.generation_hints or {}).get("is_introduction_page")]
    assert len(introductions) == 1
    assert introductions[0].slug == "start-here"
    # The second unit's intro survives as a namespaced, non-introduction bucket.
    demoted = [b for b in merged.buckets if b.title == "Start Here" and b.slug != "start-here"]
    assert len(demoted) == 1
    assert demoted[0].slug == "payments/start-here"
    assert not (demoted[0].generation_hints or {}).get("is_introduction_page")
    validate_plan_contract(merged)


def test_skipped_and_orphaned_files_union_deterministically() -> None:
    plan_a = _plan([_intro()], {"Start Here": ["start-here"]}, skipped=["z.py", "a.py"], orphaned=["shared.py"])
    plan_b = _plan([_intro()], {"Start Here": ["start-here"]}, skipped=["a.py"], orphaned=["shared.py"])

    merged = merge_unit_plans([("orders", plan_a), ("payments", plan_b)])

    assert merged.skipped_files == ["a.py", "z.py"]
    assert merged.orphaned_files == ["shared.py"]


def test_missing_files_reports_undisposed_files() -> None:
    from deepdoc.v2_models import RepoScan

    scan = RepoScan(
        file_tree={},
        file_summaries={"a.py": "s", "b.py": "s", "c.py": "s"},
        api_endpoints=[],
        languages={},
        has_openapi=False,
        openapi_paths=[],
        total_files=3,
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
    )
    plan = _plan([_feature("feature", ["a.py"])], {"Features": ["feature"]}, skipped=["b.py"])

    assert missing_files(scan, plan) == ["c.py"]
