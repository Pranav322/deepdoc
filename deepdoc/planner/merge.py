"""Deterministic merge of independently planned units into one global DocPlan."""

from __future__ import annotations

import copy
import dataclasses

from ..v2_models import DocBucket, DocPlan, RepoScan
from .heuristics import _deduplicate_bucket_slugs


def _namespaced(unit_slug: str, local_slug: str) -> str:
    return f"{unit_slug}/{local_slug}"


def merge_unit_plans(unit_plans: list[tuple[str, DocPlan]]) -> DocPlan:
    """Merge `(unit_slug, DocPlan)` pairs produced per planning unit.

    Every non-introduction bucket is namespaced under its unit slug so two
    units can never collide on slug or output path. Introduction pages are
    special-cased (a defensive safety net: real LLM propose output can
    legitimately volunteer its own introduction bucket per unit, even though
    the deterministic Start Here injector itself is deferred to the global
    stage that runs once after this merge): the first unit's introduction
    becomes the single global introduction; every other unit's introduction
    is demoted to a regular (namespaced) overview bucket so its content
    survives instead of being dropped.

    Operates on clones of the input buckets — the caller's source `DocPlan`s
    (and their buckets) are never mutated, so a unit's local plan can still
    be inspected/reused after merging.

    Callers must run the global bucket-injection/nav-shaping stage and
    `validate_plan_contract` on the result themselves — this function only
    merges; a single-unit caller should skip it entirely and use that unit's
    plan directly (merging a single plan with itself would only add
    unnecessary slug prefixing).
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
        for original in plan.buckets:
            bucket = dataclasses.replace(
                original,
                depends_on=list(original.depends_on),
                owned_files=list(original.owned_files),
                owned_symbols=list(original.owned_symbols),
                artifact_refs=list(original.artifact_refs),
                required_sections=list(original.required_sections),
                required_diagrams=list(original.required_diagrams),
                coverage_targets=list(original.coverage_targets),
                generation_hints=dict(original.generation_hints),
                source_kind_summary=dict(original.source_kind_summary),
                evidence_anchors=list(original.evidence_anchors),
            )
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
        merged_integration.extend(copy.deepcopy(plan.integration_candidates))
        if not merged_classification:
            merged_classification = copy.deepcopy(plan.classification)

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
    return _deduplicate_bucket_slugs(merged_plan)


def missing_files(scan: RepoScan, plan: DocPlan) -> list[str]:
    """Files in `scan.file_summaries` disposed of by neither a bucket nor skip/orphan lists."""
    owned: set[str] = set()
    for bucket in plan.buckets:
        owned.update(bucket.owned_files)
    disposed = owned | set(plan.skipped_files) | set(plan.orphaned_files)
    return sorted(set(scan.file_summaries) - disposed)


__all__ = ["merge_unit_plans", "missing_files"]
