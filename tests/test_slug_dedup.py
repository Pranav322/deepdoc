from __future__ import annotations

from deepdoc.plan_contract import validate_plan_contract
from deepdoc.planner import DocBucket, DocPlan
from deepdoc.planner.heuristics import _deduplicate_bucket_slugs


def _bucket(slug: str, title: str, *, introduction: bool = False) -> DocBucket:
    return DocBucket(
        bucket_type="feature",
        title=title,
        slug=slug,
        section="Guide",
        description=f"Documentation for {title}",
        owned_files=[f"src/{slug}.py"],
        generation_hints={"is_introduction_page": introduction},
    )


def test_deduplicate_bucket_slugs_uniquifies_top_level_collisions() -> None:
    intro = _bucket("start-here", "Start Here", introduction=True)
    auth_a = _bucket("auth", "Service A Auth")
    auth_b = _bucket("auth", "Service B Auth")
    plan = DocPlan(buckets=[intro, auth_a, auth_b], nav_structure={}, skipped_files=[])

    plan = _deduplicate_bucket_slugs(plan)

    assert [b.slug for b in plan.buckets] == ["start-here", "auth", "auth-2"]

    plan.nav_structure = {
        "Start Here": ["start-here"],
        "Guide": [b.slug for b in plan.buckets if b.slug != "start-here"],
    }
    validate_plan_contract(plan)  # must not raise
