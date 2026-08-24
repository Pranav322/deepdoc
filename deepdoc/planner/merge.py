"""Deterministic merge of independently planned units into one global DocPlan."""

from __future__ import annotations

from ..plan_contract import validate_plan_contract
from ..v2_models import DocBucket, DocPlan, RepoScan
from .heuristics import _deduplicate_bucket_slugs


def _namespaced(unit_slug: str, local_slug: str) -> str:
    return f"{unit_slug}/{local_slug}"


def merge_unit_plans(unit_plans: list[tuple[str, DocPlan]]) -> DocPlan:
    """Merge `(unit_slug, DocPlan)` pairs produced per planning unit.

    Every non-introduction bucket is namespaced under its unit slug so two
    units can never collide on slug or output path. Introduction pages are
    special-cased: the first unit's introduction becomes the single global
    introduction; every other unit's introduction is demoted to a regular
    (namespaced) overview bucket so its content survives instead of being
    dropped. The merged plan is validated before it's returned.

    Callers with a single unit should skip this and return that unit's plan
    directly — merging a single plan with itself would only add unnecessary
    slug prefixing.
    """
    if len(unit_plans) == 1:
        return unit_plans[0][1]

    slug_map: dict[tuple[str, str], str] = {}
    for unit_slug, plan in unit_plans:
        for bucket in plan.buckets:
            slug_map[(unit_slug, bucket.slug)] = _namespaced(unit_slug, bucket.slug)

    merged_buckets: list[DocBucket] = []
    merged_nav: dict[str, list[str]] = {}
    merged_skipped: list[str] = []
    merged_orphaned: list[str] = []
    merged_classification: dict = {}
    merged_integration: list[dict] = []
    has_global_intro = False

    for unit_slug, plan in unit_plans:
        for bucket in plan.buckets:
            is_intro = bool((bucket.generation_hints or {}).get("is_introduction_page"))
            bucket.depends_on = [
                slug_map.get((unit_slug, dep), dep) for dep in bucket.depends_on
            ]
            bucket.parent_slug = (
                slug_map.get((unit_slug, bucket.parent_slug), bucket.parent_slug)
                if bucket.parent_slug
                else bucket.parent_slug
            )
            if is_intro:
                if not has_global_intro:
                    # First introduction found becomes the single global one;
                    # keep its slug unprefixed so it still owns index.md / "/".
                    # The pre-pass above namespaced every slug by default —
                    # correct this one entry back to the original so nav refs
                    # to it (still using the local slug) resolve correctly.
                    slug_map[(unit_slug, bucket.slug)] = bucket.slug
                    has_global_intro = True
                else:
                    # A later unit's introduction is demoted to a namespaced
                    # overview page — its content is kept, just no longer
                    # claiming to be *the* introduction.
                    hints = dict(bucket.generation_hints)
                    hints.pop("is_introduction_page", None)
                    bucket.generation_hints = hints
                    bucket.slug = slug_map[(unit_slug, bucket.slug)]
            else:
                bucket.slug = slug_map[(unit_slug, bucket.slug)]
            merged_buckets.append(bucket)

        for section, slugs in plan.nav_structure.items():
            mapped = [slug_map.get((unit_slug, s), s) for s in slugs]
            merged_nav.setdefault(section, []).extend(mapped)

        merged_skipped.extend(plan.skipped_files)
        merged_orphaned.extend(plan.orphaned_files)
        merged_integration.extend(plan.integration_candidates)
        if not merged_classification:
            merged_classification = plan.classification

    merged_plan = DocPlan(
        buckets=merged_buckets,
        nav_structure=merged_nav,
        skipped_files=sorted(set(merged_skipped)),
        orphaned_files=sorted(set(merged_orphaned)),
        classification=merged_classification,
        integration_candidates=merged_integration,
    )
    # Safety net, not the primary merge algorithm: namespacing above already
    # makes every slug unique, this only guards against an edge case slipping
    # through (e.g. a unit slug itself colliding with another unit's bucket).
    merged_plan = _deduplicate_bucket_slugs(merged_plan)
    validate_plan_contract(merged_plan)
    return merged_plan


def missing_files(scan: RepoScan, plan: DocPlan) -> list[str]:
    """Files in `scan.file_summaries` disposed of by neither a bucket nor skip/orphan lists."""
    owned: set[str] = set()
    for bucket in plan.buckets:
        owned.update(bucket.owned_files)
    disposed = owned | set(plan.skipped_files) | set(plan.orphaned_files)
    return sorted(set(scan.file_summaries) - disposed)


__all__ = ["merge_unit_plans", "missing_files"]
