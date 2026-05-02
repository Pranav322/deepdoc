from .common import *
from .bucket_refinement import _bucket_semantic_tokens
from .bucket_injection import _canonical_section_for_bucket


def _shape_plan_nav(plan: DocPlan, classification: dict[str, Any]) -> DocPlan:
    """Normalize sections and build a repo-agnostic, reader-first nav flow."""
    primary = classification.get("repo_profile", {}).get("primary_type", "other")
    merged_utilities: list[DocBucket] = []
    new_buckets: list[DocBucket] = []

    for bucket in plan.buckets:
        title_lower = bucket.title.lower()
        if (
            primary == "research_training"
            and len(bucket.owned_files) <= 2
            and any(token in title_lower for token in ("utilities", "utility"))
        ):
            merged_utilities.append(bucket)
            continue

        hints = bucket.generation_hints or {}
        if not hints.get("preserve_section"):
            bucket.section = _canonical_section_for_bucket(bucket, primary)

        bucket.section = _normalize_nav_section(bucket.section, primary)
        new_buckets.append(bucket)

    if merged_utilities:
        merged = DocBucket(
            bucket_type="utility-group",
            title="Common Utilities & Configuration",
            slug="common-utilities-configuration",
            section=_normalize_nav_section("Operations", primary),
            description="Shared low-level helpers and configuration utilities referenced across the repository",
            owned_files=sorted(
                {f for bucket in merged_utilities for f in bucket.owned_files}
            ),
            required_sections=[
                "overview",
                "shared_helpers",
                "configuration",
                "usage_patterns",
            ],
            generation_hints={"prompt_style": "general", "icon": "cube"},
            priority=min(bucket.priority for bucket in merged_utilities),
        )
        new_buckets.append(merged)

    plan.buckets = sorted(new_buckets, key=lambda bucket: bucket.priority)
    plan.buckets = _merge_duplicate_setup_bucket(plan.buckets)

    nav: dict[str, list[str]] = defaultdict(list)
    slug_to_bucket = {bucket.slug: bucket for bucket in plan.buckets}

    fixed_start_here = ["start-here", "local-development-setup", "domain-glossary"]
    for slug in fixed_start_here:
        if slug in slug_to_bucket:
            _append_nav_slug(nav, "Start Here", slug)

    endpoint_grouped: set[str] = set()

    for bucket in plan.buckets:
        if bucket.slug in fixed_start_here:
            continue
        hints = bucket.generation_hints or {}
        if hints.get("is_endpoint_family") or hints.get("is_endpoint_ref"):
            continue
        section = bucket.section or _default_section_for_primary(primary)
        _append_nav_slug(nav, section, bucket.slug)

    endpoint_nav = _build_endpoint_reference_nav(plan.buckets)
    for section_name, slugs in endpoint_nav.items():
        for slug in slugs:
            _append_nav_slug(nav, section_name, slug)
            endpoint_grouped.add(slug)

    for bucket in plan.buckets:
        hints = bucket.generation_hints or {}
        if not (hints.get("is_endpoint_family") or hints.get("is_endpoint_ref")):
            continue
        if bucket.slug in endpoint_grouped:
            continue
        _append_nav_slug(nav, "API Reference", bucket.slug)

    section_order = {section: idx for idx, section in enumerate(nav.keys())}
    ordered_sections = sorted(
        nav.keys(),
        key=lambda section: (
            _section_rank(_section_top(section), primary),
            _section_top(section),
            section_order[section],
            section,
        ),
    )

    plan.nav_structure = {
        section: nav[section] for section in ordered_sections if nav.get(section)
    }
    return plan


def _merge_duplicate_setup_bucket(buckets: list[DocBucket]) -> list[DocBucket]:
    by_slug = {bucket.slug: bucket for bucket in buckets}
    canonical = by_slug.get("local-development-setup")
    legacy = by_slug.get("setup")
    if not canonical or not legacy:
        return buckets

    canonical.owned_files = list(
        dict.fromkeys(canonical.owned_files + legacy.owned_files)
    )
    canonical.owned_symbols = list(
        dict.fromkeys(canonical.owned_symbols + legacy.owned_symbols)
    )
    canonical.artifact_refs = list(
        dict.fromkeys(canonical.artifact_refs + legacy.artifact_refs)
    )
    canonical.required_sections = list(
        dict.fromkeys(canonical.required_sections + legacy.required_sections)
    )
    canonical.required_diagrams = list(
        dict.fromkeys(canonical.required_diagrams + legacy.required_diagrams)
    )
    canonical.coverage_targets = list(
        dict.fromkeys(canonical.coverage_targets + legacy.coverage_targets)
    )
    if not canonical.description.strip() and legacy.description.strip():
        canonical.description = legacy.description

    return [bucket for bucket in buckets if bucket.slug != "setup"]


def _normalize_nav_section(section: str, primary: str) -> str:
    value = (section or "").strip() or _default_section_for_primary(primary)
    top, sep, rest = value.partition(" > ")

    if top == "API Endpoints":
        top = "API Reference"

    backend_like = {
        "backend_service",
        "falcon_backend",
        "hybrid",
    }
    if primary in backend_like:
        top = {
            "Data Layer": "Data Model",
            "Database": "Data Model",
            "Architecture": "Core Workflows",
            "Subsystems": "Core Workflows",
            "Modules": "Core Workflows",
            "API": "API Reference",
            "Getting Started": "Start Here",
            "Research Context": "Design & Notes",
        }.get(top, top)

    if top == "Database":
        top = "Data Model"

    if sep:
        return f"{top} > {rest}"
    return top


def _build_endpoint_reference_nav(buckets: list[DocBucket]) -> dict[str, list[str]]:
    families = [
        bucket
        for bucket in buckets
        if (bucket.generation_hints or {}).get("is_endpoint_family")
    ]
    refs = [
        bucket
        for bucket in buckets
        if (bucket.generation_hints or {}).get("is_endpoint_ref")
    ]
    if not families and not refs:
        return {}

    families_by_slug = {bucket.slug: bucket for bucket in families}
    family_refs: dict[str, list[DocBucket]] = defaultdict(list)
    orphan_refs: list[DocBucket] = []

    for bucket in refs:
        parent_slug = bucket.parent_slug or (
            bucket.depends_on[0] if bucket.depends_on else ""
        )
        if parent_slug and parent_slug in families_by_slug:
            family_refs[parent_slug].append(bucket)
        else:
            orphan_refs.append(bucket)

    nav: dict[str, list[str]] = {}
    for family in sorted(
        families, key=lambda item: (item.priority, item.title, item.slug)
    ):
        refs_for_family = sorted(
            family_refs.get(family.slug, []),
            key=lambda item: (item.priority, item.title, item.slug),
        )
        if not refs_for_family:
            continue
        section_name = f"API Reference > {family.title}"
        nav[section_name] = [family.slug] + [bucket.slug for bucket in refs_for_family]

    if orphan_refs:
        nav["API Reference > Other"] = [
            bucket.slug
            for bucket in sorted(
                orphan_refs,
                key=lambda item: (item.priority, item.title, item.slug),
            )
        ]

    return nav


def _append_nav_slug(nav: dict[str, list[str]], section: str, slug: str) -> None:
    section_list = nav.setdefault(section, [])
    if slug not in section_list:
        section_list.append(slug)


def _section_top(section: str) -> str:
    return section.split(" > ", 1)[0].strip()


def _default_section_for_primary(primary: str) -> str:
    if primary in {"backend_service", "falcon_backend", "hybrid"}:
        return "Core Workflows"
    if primary == "research_training":
        return "Operations"
    return "Architecture"


def _section_rank(section: str, primary: str) -> int:
    backend_like = {
        "backend_service",
        "falcon_backend",
        "hybrid",
    }
    if primary in backend_like:
        order = [
            "Start Here",
            "Overview",
            "Core Workflows",
            "API Reference",
            "Data Model",
            "Background Jobs",
            "Integrations",
            "Runtime & Frameworks",
            "Interfaces",
            "Operations",
            "Design & Notes",
            "Testing",
            "CI/CD and Release",
            "Supporting Material",
        ]
        if section in order:
            return order.index(section)
        return len(order) + 10

    if primary == "research_training":
        order = [
            "Start Here",
            "Overview",
            "Model Architecture",
            "Training",
            "Optimization",
            "Data Pipeline",
            "Evaluation",
            "Inference & Runtime",
            "Interfaces",
            "Operations",
            "Research Context",
            "Design & Notes",
            "Testing",
            "CI/CD and Release",
            "Supporting Material",
        ]
        if section in order:
            return order.index(section)
        return len(order) + 10

    order = [
        "Start Here",
        "Overview",
        "Architecture",
        "Core API",
        "API Reference",
        "Integrations",
        "Operations",
        "Testing",
        "Design & Notes",
        "Supporting Material",
    ]
    if section in order:
        return order.index(section)
    return len(order) + 10
