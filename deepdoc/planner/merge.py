"""Deterministic merge of independently planned units into one global DocPlan."""

from __future__ import annotations

import copy
import dataclasses

from ..v2_models import DocBucket, DocPlan, RepoScan, build_bucket_semantic_id
from .heuristics import _deduplicate_bucket_slugs

# Global-only bucket types (injected once, post-merge, by
# _apply_global_plan_stage) that legitimately re-reference files also owned
# by a normal feature bucket — e.g. Start Here links the 5 key files, the
# glossary cites model files. A later normal feature bucket does NOT get
# this leeway: two feature buckets both claiming `owned_files` on the same
# file is a real duplicate-ownership bug, not intentional overview evidence.
_OVERVIEW_BUCKET_TYPES = frozenset(
    {"start_here_index", "start_here_setup", "domain_glossary", "debug_runbook", "coarse_oversized"}
)


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

    The complete slug map — including the retained global introduction's
    corrected (unprefixed) entry — is built in one pass over every unit's
    buckets *before* any bucket reference is rewritten in a second pass.
    Building and rewriting in a single interleaved pass (the original
    implementation) meant a bucket processed before its own unit's
    introduction bucket would resolve `depends_on`/`parent_slug` against the
    not-yet-corrected namespaced slug. Every cloned bucket's `semantic_id`
    is recomputed from its final slug/parent/depends_on via the canonical
    `build_bucket_semantic_id`, so it never goes stale after the rewrite.

    Operates on clones of the input buckets — the caller's source `DocPlan`s
    (and their buckets) are never mutated, so a unit's local plan can still
    be inspected/reused after merging.

    Callers must run the global bucket-injection/nav-shaping stage,
    `normalize_plan_disposition`, and `validate_plan_contract` on the result
    themselves — this function only merges; a single-unit caller should
    skip it entirely and use that unit's plan directly (merging a single
    plan with itself would only add unnecessary slug prefixing).
    """
    if len(unit_plans) == 1:
        return unit_plans[0][1]

    # Pass 1 — decide every bucket's final slug, including which
    # introduction (if any) is retained unprefixed as the global one, before
    # any bucket reference is rewritten.
    slug_map: dict[tuple[str, str], str] = {}
    has_global_intro = False
    for unit_slug, plan in unit_plans:
        for bucket in plan.buckets:
            is_intro = bool((bucket.generation_hints or {}).get("is_introduction_page"))
            if is_intro and not has_global_intro:
                slug_map[(unit_slug, bucket.slug)] = bucket.slug
                has_global_intro = True
            else:
                slug_map[(unit_slug, bucket.slug)] = _namespaced(unit_slug, bucket.slug)

    # Pass 2 — clone every bucket and rewrite slug/depends_on/parent_slug
    # (and demote a non-retained introduction) using the now-final map.
    merged_buckets: list[DocBucket] = []
    merged_nav: dict[str, list[str]] = {}
    merged_skipped: list[str] = []
    merged_orphaned: list[str] = []
    merged_classification: dict = {}
    merged_integration: list[dict] = []

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
            is_intro = bool((original.generation_hints or {}).get("is_introduction_page"))
            new_slug = slug_map[(unit_slug, original.slug)]
            bucket.depends_on = [
                slug_map.get((unit_slug, dep), dep) for dep in bucket.depends_on
            ]
            bucket.parent_slug = (
                slug_map.get((unit_slug, bucket.parent_slug), bucket.parent_slug)
                if bucket.parent_slug
                else bucket.parent_slug
            )
            bucket.slug = new_slug
            if is_intro and new_slug != original.slug:
                # This unit's introduction wasn't the one retained — demote
                # it to a regular namespaced overview page; its content is
                # kept, just no longer claiming to be *the* introduction.
                hints = dict(bucket.generation_hints)
                hints.pop("is_introduction_page", None)
                bucket.generation_hints = hints
            bucket.semantic_id = build_bucket_semantic_id(bucket)
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


def normalize_plan_disposition(
    plan: DocPlan, unit_files: dict[str, set[str]] | None = None
) -> DocPlan:
    """Enforce file-disposition invariants on a merged plan, before
    `validate_plan_contract`:

    - a file owned by any bucket is removed from `skipped_files`/
      `orphaned_files` (ownership wins over either exclusion list);
    - `skipped_files` and `orphaned_files` never overlap (a file in both is
      a contradiction — `skipped_files`, an explicit exclusion, wins);
    - the same file owned by more than one *normal* feature bucket keeps
      only its first (bucket list order) owner — a later claim is dropped,
      not silently duplicated;
    - a global overview bucket (`_OVERVIEW_BUCKET_TYPES` — Start Here,
      glossary, setup, debug runbook, coarse coverage) that lists an
      already-owned file is demoted from `owned_files` to `artifact_refs`
      for that file: it keeps the evidence without a second claim of page
      ownership;
    - if `unit_files` (unit slug -> that unit's own files) is given, a
      bucket whose slug is namespaced `{unit}/...` can only *own* that
      unit's own files; anything else it lists is demoted to
      `artifact_refs` instead of silently kept as ownership it was never
      scoped to have.
    """
    # Establish normal feature ownership before processing overview buckets,
    # regardless of plan ordering. Global Start Here/glossary buckets are often
    # inserted before feature pages; they must cite files, not steal ownership.
    normal_owner: dict[str, str] = {}
    for bucket in plan.buckets:
        if bucket.bucket_type in _OVERVIEW_BUCKET_TYPES:
            continue
        for file_path in bucket.owned_files:
            normal_owner.setdefault(file_path, bucket.slug)

    owned_seen: set[str] = set()
    unit_slugs = sorted(unit_files or {}, key=len, reverse=True)
    for bucket in plan.buckets:
        unit_slug = next(
            (
                slug
                for slug in unit_slugs
                if bucket.slug == slug or bucket.slug.startswith(slug + "/")
            ),
            None,
        )
        allowed_files = unit_files.get(unit_slug) if unit_files and unit_slug else None

        kept: list[str] = []
        artifact_additions: list[str] = []
        for file_path in bucket.owned_files:
            out_of_scope = allowed_files is not None and file_path not in allowed_files
            overview_reference = (
                bucket.bucket_type in _OVERVIEW_BUCKET_TYPES
                and file_path in normal_owner
            )
            duplicate_normal_owner = (
                bucket.bucket_type not in _OVERVIEW_BUCKET_TYPES
                and normal_owner.get(file_path) != bucket.slug
            )
            if out_of_scope or overview_reference or duplicate_normal_owner:
                if file_path not in bucket.artifact_refs and file_path not in artifact_additions:
                    artifact_additions.append(file_path)
                continue
            if file_path in owned_seen:
                continue
            kept.append(file_path)
            owned_seen.add(file_path)
        bucket.owned_files = kept
        if artifact_additions:
            bucket.artifact_refs = [*bucket.artifact_refs, *artifact_additions]
        # Ownership participates in semantic identity. Normalization can
        # remove duplicate/foreign owners, so refresh the canonical identity
        # after the final ownership set is known.
        bucket.semantic_id = build_bucket_semantic_id(bucket)

    plan.skipped_files = sorted(set(plan.skipped_files) - owned_seen)
    plan.orphaned_files = sorted(set(plan.orphaned_files) - owned_seen - set(plan.skipped_files))
    return plan


def missing_files(scan: RepoScan, plan: DocPlan) -> list[str]:
    """Files in `scan.file_summaries` disposed of by neither a bucket nor skip/orphan lists."""
    owned: set[str] = set()
    for bucket in plan.buckets:
        owned.update(bucket.owned_files)
    disposed = owned | set(plan.skipped_files) | set(plan.orphaned_files)
    return sorted(set(scan.file_summaries) - disposed)


__all__ = ["merge_unit_plans", "normalize_plan_disposition", "missing_files"]
