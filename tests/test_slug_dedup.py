from __future__ import annotations

from deepdoc.plan_contract import validate_plan_contract
from deepdoc.planner import DocBucket, DocPlan
from deepdoc.planner.heuristics import _deduplicate_bucket_slugs
from deepdoc.v2_models import build_bucket_semantic_id


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
    # Force semantic IDs to depend on the slug rather than identical owned-file
    # hashes, so renaming auth_b to auth-2 must refresh its identity.
    for bucket in (auth_a, auth_b):
        bucket.owned_files = []
        bucket.semantic_id = build_bucket_semantic_id(bucket)
    original_auth_b_id = auth_b.semantic_id
    plan = DocPlan(buckets=[intro, auth_a, auth_b], nav_structure={}, skipped_files=[])

    plan = _deduplicate_bucket_slugs(plan)

    assert [b.slug for b in plan.buckets] == ["start-here", "auth", "auth-2"]
    assert auth_b.semantic_id != original_auth_b_id
    assert all(bucket.semantic_id == build_bucket_semantic_id(bucket) for bucket in plan.buckets)

    plan.nav_structure = {
        "Start Here": ["start-here"],
        "Guide": [b.slug for b in plan.buckets if b.slug != "start-here"],
    }
    validate_plan_contract(plan)  # must not raise
