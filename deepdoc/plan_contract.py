"""Structural contract for planned documentation output."""

from __future__ import annotations

from collections import defaultdict

from .v2_models import DocBucket, DocPlan


class PlanContractError(ValueError):
    """Raised when a documentation plan cannot be emitted safely."""


def bucket_output_path(bucket: DocBucket) -> str:
    """Return the Markdown path owned by a bucket."""
    if (bucket.generation_hints or {}).get("is_introduction_page"):
        return "index.md"
    return f"{bucket.slug}.md"


def bucket_site_path(bucket: DocBucket) -> str:
    """Return the public site path owned by a bucket."""
    if (bucket.generation_hints or {}).get("is_introduction_page"):
        return "/"
    return f"/{bucket.slug}"


def validate_plan_contract(plan: DocPlan) -> None:
    """Raise one deterministic error containing every structural violation."""
    violations: list[str] = []
    introductions = sorted(
        bucket.slug
        for bucket in plan.buckets
        if (bucket.generation_hints or {}).get("is_introduction_page")
    )
    if len(introductions) != 1:
        found = ", ".join(introductions) if introductions else "none"
        violations.append(
            f"expected exactly one introduction bucket; found {len(introductions)}: {found}"
        )

    slug_owners: dict[str, list[str]] = defaultdict(list)
    output_owners: dict[str, list[str]] = defaultdict(list)
    for bucket in plan.buckets:
        slug_owners[bucket.slug].append(bucket.title)
        output_owners[bucket_output_path(bucket)].append(bucket.slug)

    for slug, owners in sorted(slug_owners.items()):
        if len(owners) > 1:
            violations.append(
                f"duplicate bucket slug: {slug} <- {', '.join(sorted(owners))}"
            )
    for output_path, owners in sorted(output_owners.items()):
        if len(owners) > 1:
            violations.append(
                f"duplicate output writer: {output_path} <- {', '.join(sorted(owners))}"
            )

    known_slugs = set(slug_owners)
    system_nav_slugs = {"whats-changed"}
    nav_locations: dict[str, list[str]] = defaultdict(list)
    for section, slugs in sorted(plan.nav_structure.items()):
        for slug in slugs:
            nav_locations[slug].append(section)
            if slug not in known_slugs and slug not in system_nav_slugs:
                violations.append(f"unresolved nav slug: {section} -> {slug}")

    for slug, sections in sorted(nav_locations.items()):
        if len(sections) > 1:
            violations.append(
                f"duplicate nav reference: {slug} <- {', '.join(sorted(sections))}"
            )

    if violations:
        details = "\n".join(f"- {item}" for item in sorted(violations))
        raise PlanContractError(f"Invalid documentation plan:\n{details}")
