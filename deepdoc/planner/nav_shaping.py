from .common import *
from .bucket_refinement import _bucket_semantic_tokens
from .bucket_injection import _canonical_section_for_bucket

_PATH_SECTION_PREFIXES = (
    "new-src-",
    "src-",
    "app-",
    "lib-",
    "packages-",
    "services-",
    "controllers-",
    "middlewares-",
    "utils-",
)


def _shape_plan_nav(
    plan: DocPlan,
    classification: dict[str, Any],
    scan: Any = None,
) -> DocPlan:
    """Normalize sections and build a topology-driven, reader-first nav flow."""
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
        if not hints.get("preserve_section") or _is_path_slug_section(bucket.section):
            bucket.section = _canonical_section_for_bucket(bucket, primary)

        bucket.section = _normalize_nav_section(bucket.section, primary)
        new_buckets.append(bucket)

    if merged_utilities:
        merged = DocBucket(
            bucket_type="utility-group",
            title="Common Utilities & Configuration",
            slug="common-utilities-configuration",
            section=_normalize_nav_section(
                "Operations" if primary == "research_training" else "Supporting Infrastructure",
                primary,
            ),
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

    # Build section → min topology depth map for ordering
    section_depth: dict[str, int] = _build_section_depth_map(plan.buckets, scan, classification)

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
        # Overview/intro page is placed at the root level by the site builder —
        # adding it to a section too creates a duplicate entry in the sidebar.
        if hints.get("is_introduction_page"):
            continue
        section = bucket.section or "Architecture"
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

    # Build section → tier map for three-tier nav ordering
    slug_to_bucket_map = {bucket.slug: bucket for bucket in plan.buckets}
    section_buckets_by_top: dict[str, list[DocBucket]] = defaultdict(list)
    for section, slugs in nav.items():
        top_section = _section_top(section)
        for slug in slugs:
            if slug in slug_to_bucket_map:
                section_buckets_by_top[top_section].append(slug_to_bucket_map[slug])
    section_tier_map = {
        top: _compute_section_tier(buckets_list)
        for top, buckets_list in section_buckets_by_top.items()
    }

    section_order = {section: idx for idx, section in enumerate(nav.keys())}
    ordered_sections = sorted(
        nav.keys(),
        key=lambda section: _section_sort_key(section, primary, section_depth, section_order, section_tier_map),
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

    # Universal synonym aliases — collapse variant spellings, don't impose structure
    top = {
        "Getting Started": "Start Here",
        "API Endpoints": "API Reference",
        "API": "API Reference",
        "Database": "Data Model",
        "Data Layer": "Data Model",
        "Background Processing": "Background Jobs",
        "Async Tasks": "Background Jobs",
        "Jobs": "Background Jobs",
    }.get(top, top)

    if sep:
        if rest.strip() == top:
            return top
        return f"{top} > {rest}"
    return top


def _is_path_slug_section(section: str) -> bool:
    """Return True when the section looks like a file path cluster id."""
    value = (section or "").strip()
    if not value:
        return False
    if " > " in value or "/" in value or "\\" in value:
        return False
    lower = value.lower()
    if lower != value or "-" not in lower:
        return False
    if lower.endswith(("-ts", "-js", "-tsx", "-jsx", "-py", "-php", "-go")):
        return True
    return lower.startswith(_PATH_SECTION_PREFIXES) and lower.count("-") >= 2


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
    if primary == "research_training":
        return "Operations"
    return "Architecture"


def _build_section_depth_map(
    buckets: list[DocBucket],
    scan: Any,
    classification: dict[str, Any],
) -> dict[str, int]:
    """Map each nav section to the minimum topology depth among its buckets.

    This lets _section_sort_key order sections by call-graph proximity to
    entry points: shallow clusters (entry-point-facing) come first, deep /
    foundational clusters come last.
    """
    tmap = getattr(scan, "topology_map", None) if scan else None
    cluster_names: dict[str, dict] = classification.get("cluster_names", {}) if classification else {}

    # Build section → cluster_id from classify output
    section_to_cluster: dict[str, str] = {}
    for cid, info in cluster_names.items():
        if isinstance(info, dict) and info.get("section"):
            section_to_cluster.setdefault(info["section"], cid)

    if not tmap or not tmap.clusters:
        return {}

    cluster_depth: dict[str, int] = {c.cluster_id: c.min_depth for c in tmap.clusters}

    # Build section → min_depth using the classify cluster→section mapping
    section_depth: dict[str, int] = {}
    for section, cid in section_to_cluster.items():
        depth = cluster_depth.get(cid, 999)
        top = _section_top(section)
        if top not in section_depth or depth < section_depth[top]:
            section_depth[top] = depth

    return section_depth


def _compute_section_tier(buckets_in_section: list[DocBucket]) -> int:
    """Return 1=user-facing, 2=domain/feature, 3=infrastructure.

    Tier 1: sections containing intro, endpoint family, or endpoint-detail buckets.
    Tier 2: sections containing feature/integration/database/endpoint bucket types.
    Tier 3: everything else (foundational, infrastructure, utility).
    """
    for b in buckets_in_section:
        hints = b.generation_hints or {}
        if (
            hints.get("is_introduction_page")
            or hints.get("is_endpoint_family")
            or hints.get("include_endpoint_detail")
        ):
            return 1
    for b in buckets_in_section:
        if b.bucket_type in ("feature", "integration", "database", "endpoint", "endpoint_ref"):
            return 2
    return 3


def _section_sort_key(
    section: str,
    primary: str,
    section_depth: dict[str, int],
    section_order: dict[str, int],
    section_tier_map: dict[str, int] | None = None,
) -> tuple:
    """Sort key for nav sections.

    Pins Start Here / Overview first and tail sections (Testing, CI/CD, Supporting
    Material) last. Everything in between is ordered by three tiers that preserve
    a newcomer reading journey (user-facing → domain/feature → infrastructure),
    with topology depth as a tiebreaker within each tier.
    """
    top = _section_top(section)

    _FIRST = {"Start Here": 0, "Overview": 1}
    _LAST = {
        "Testing": 57,
        "CI/CD and Release": 58,
        "CI/CD & Release": 58,
        "Supporting Material": 59,
    }

    if top in _FIRST:
        return (_FIRST[top], section_order.get(section, 999), section)
    if top in _LAST:
        return (_LAST[top], section_order.get(section, 999), section)

    # Three-tier middle: user-facing (10+) → domain/feature (20+) → infrastructure (30+)
    # Within each tier, topology depth orders entry-point-facing sections first.
    tier = (section_tier_map or {}).get(top, 3)
    tier_base = 10 * tier
    depth = section_depth.get(top, 50)
    child_rank = 0 if section == top else 1
    return (tier_base + depth, child_rank, section_order.get(section, 999), section)
