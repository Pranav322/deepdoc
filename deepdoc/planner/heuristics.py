from contextlib import nullcontext

from .common import *
from .bucket_refinement import (
    _proposal_bucket_tokens, _is_low_value_utility_bucket, _is_incidental_http_bucket,
    _best_proposal_merge_target, _remove_slug_from_nav, _refine_proposal,
    _file_semantic_tokens, _bucket_semantic_tokens, _attach_file_to_best_bucket,
    _summary_file_score, _refine_bucket_ownership, _attach_orphans_semantically,
    _apply_page_contracts, _build_file_summaries_for_bucket, _should_decompose,
    _decompose_buckets, _consolidate_similar_buckets,
)
from .bucket_injection import (
    _inject_start_here_and_debug_buckets, _inject_research_context_buckets,
    _assign_publication_tiers, _canonical_section_for_bucket,
)
from .nav_shaping import (
    _shape_plan_nav, _merge_duplicate_setup_bucket, _normalize_nav_section,
    _build_endpoint_reference_nav, _append_nav_slug, _section_top,
    _default_section_for_primary,
)
from .endpoint_refs import _auto_generate_endpoint_refs, _stable_specialized_slug


def _normalize_tokens(*values: str) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        for token in TOKEN_RE.findall(value or ""):
            normalized = token.lower().strip("_-+")
            if len(normalized) < 3 or normalized in STOPWORD_TOKENS:
                continue
            tokens.add(normalized)
    return tokens



def _normalize_repo_profile(
    classification: dict[str, Any], scan: RepoScan
) -> dict[str, Any]:
    """Normalize repo profile: synonym aliases + framework trait annotation only."""
    profile = dict(classification.get("repo_profile", {}) or {})
    primary = profile.get("primary_type", "other")
    frameworks = set(scan.frameworks_detected)
    secondary_traits = set(profile.get("secondary_traits", []))

    # Annotate secondary traits from detected frameworks (informational, no classification override)
    framework_traits = {
        "falcon": "uses_falcon",
        "django": "uses_django",
        "express": "uses_express",
        "fastify": "uses_fastify",
        "laravel": "uses_laravel",
        "vue": "uses_vue",
        "react": "uses_react",
        "flask": "uses_flask",
        "fastapi": "uses_fastapi",
    }
    for framework, trait in framework_traits.items():
        if framework in frameworks:
            secondary_traits.add(trait)

    # Alias normalization only — collapse synonym spellings, don't override LLM classification
    _aliases: dict[str, str] = {
        "backend_api": "backend_service",
        "monorepo_product": "platform_monorepo",
    }
    normalized_primary = _aliases.get(primary, primary)

    profile["primary_type"] = normalized_primary
    profile["secondary_traits"] = sorted(secondary_traits)
    if not profile.get("confidence"):
        profile["confidence"] = "medium"
    classification["repo_profile"] = profile
    return classification


def _llm_step(llm: LLMClient, system: str, prompt: str, step_name: str) -> dict | None:
    """Execute a single LLM planning step with error handling."""
    response = None
    try:
        telemetry = getattr(llm, "telemetry", None)
        operation = (
            telemetry.operation(f"planner.{step_name}")
            if telemetry is not None
            else nullcontext()
        )
        with operation:
            response = llm.complete(system, prompt)
    except Exception as e:
        console.print(f"[red]✗ LLM call failed for {step_name}: {e}[/red]")
        return None

    if not response:
        return None

    try:
        return _parse_json_response(response)
    except Exception as e:
        console.print(f"[red]✗ Could not parse {step_name} response: {e}[/red]")
        # Try to salvage — sometimes the LLM wraps JSON in markdown
        try:
            # Strip markdown fences and retry
            cleaned = response.strip()
            if cleaned.startswith("```"):
                lines = cleaned.splitlines()
                lines = [l for l in lines if not l.strip().startswith("```")]
                cleaned = "\n".join(lines).lstrip("﻿").strip()
            return json.loads(cleaned)
        except Exception:
            return None


def _merge_plan(
    proposal: dict,
    assignment: dict,
    classification: dict,
    scan: RepoScan,
) -> DocPlan:
    """Combine the proposal (bucket definitions) with the assignment (file mapping)."""
    # Index proposed buckets by slug
    proposed_by_slug: dict[str, dict] = {}
    for b in proposal.get("buckets", []):
        proposed_by_slug[b["slug"]] = b

    # Index assignments by slug
    assigned_by_slug: dict[str, dict] = {}
    for a in assignment.get("buckets", []):
        assigned_by_slug[a["slug"]] = a

    buckets: list[DocBucket] = []
    for slug, prop in proposed_by_slug.items():
        assign = assigned_by_slug.get(slug, {})

        bucket = DocBucket(
            bucket_type=prop.get("bucket_type", "general"),
            title=prop.get("title", slug),
            slug=slug,
            section=prop.get("section", ""),
            description=prop.get("description", ""),
            depends_on=prop.get("depends_on", []),
            owned_files=assign.get("owned_files", prop.get("candidate_files", [])),
            owned_symbols=assign.get("owned_symbols", []),
            artifact_refs=assign.get("artifact_refs", []),
            required_sections=prop.get(
                "required_sections",
                ["overview", "details", "diagrams"],
            ),
            required_diagrams=prop.get("required_diagrams", []),
            coverage_targets=prop.get("coverage_targets", []),
            generation_hints=prop.get("generation_hints", {}),
            priority=assign.get("priority", 0),
            publication_tier=prop.get("publication_tier", "core"),
            source_kind_summary=prop.get("source_kind_summary", {}),
        )
        buckets.append(bucket)

    # Sort by priority
    buckets.sort(key=lambda b: b.priority)

    nav_structure = proposal.get("nav_structure", {})
    skipped_files = assignment.get("skipped_files", [])

    return DocPlan(
        buckets=buckets,
        nav_structure=nav_structure,
        skipped_files=skipped_files,
        classification=classification,
        integration_candidates=classification.get("integration_signals", []),
    )


def _build_heuristic_assignment(proposal: dict[str, Any], scan: RepoScan) -> dict[str, Any]:
    """Build deterministic file assignments when the LLM assign JSON is invalid."""
    buckets = list(proposal.get("buckets", []))
    if not buckets:
        return {"buckets": [], "skipped_files": [], "file_to_buckets": {}}

    source_files = set(scan.file_summaries)
    assigned_files: set[str] = set()
    assignment_by_slug: dict[str, dict[str, Any]] = {}
    bucket_tokens: dict[str, set[str]] = {}

    for idx, bucket in enumerate(buckets):
        slug = bucket.get("slug", f"bucket-{idx}")
        candidate_files = [
            file_path
            for file_path in bucket.get("candidate_files", [])
            if file_path in source_files
        ]
        artifact_refs = [
            file_path
            for file_path in bucket.get("candidate_files", [])
            if file_path in set(scan.config_files)
        ]
        assignment_by_slug[slug] = {
            "slug": slug,
            "owned_files": list(dict.fromkeys(candidate_files)),
            "owned_symbols": [],
            "artifact_refs": list(dict.fromkeys(artifact_refs)),
            "priority": idx,
        }
        assigned_files.update(candidate_files)
        bucket_tokens[slug] = _proposal_bucket_tokens(bucket)

    def _file_tokens(file_path: str) -> set[str]:
        parsed = scan.parsed_files.get(file_path)
        imports = parsed.imports[:12] if parsed else []
        symbols = [symbol.name for symbol in parsed.symbols[:20]] if parsed else []
        return _normalize_tokens(
            file_path,
            scan.file_summaries.get(file_path, ""),
            " ".join(imports),
            " ".join(symbols),
            scan.source_kind_by_file.get(file_path, ""),
        )

    skipped_files: list[str] = []
    for file_path in sorted(source_files - assigned_files):
        lower_parts = set(file_path.lower().split("/"))
        if lower_parts & {"tests", "test", "__tests__", "spec"}:
            skipped_files.append(file_path)
            continue

        tokens = _file_tokens(file_path)
        best_slug = ""
        best_score = 0
        for slug, tokens_for_bucket in bucket_tokens.items():
            score = len(tokens & tokens_for_bucket)
            if scan.source_kind_by_file.get(file_path) in tokens_for_bucket:
                score += 1
            if score > best_score:
                best_score = score
                best_slug = slug

        if best_slug and best_score > 0:
            assignment_by_slug[best_slug]["owned_files"].append(file_path)
        else:
            skipped_files.append(file_path)

    file_to_buckets: dict[str, list[str]] = {}
    for assignment in assignment_by_slug.values():
        assignment["owned_files"] = list(dict.fromkeys(assignment["owned_files"]))
        for file_path in assignment["owned_files"]:
            file_to_buckets.setdefault(file_path, []).append(assignment["slug"])

    return {
        "buckets": list(assignment_by_slug.values()),
        "skipped_files": sorted(set(skipped_files)),
        "file_to_buckets": file_to_buckets,
    }




def _partition_topology_assignment(
    proposal: dict[str, Any], scan: RepoScan
) -> tuple[dict[str, Any], list[str]]:
    """Preassign files only when proposal and topology ownership uniquely agree."""
    source_files = set(scan.file_summaries)
    topology = scan.topology_map
    if not topology or not topology.file_cluster_id:
        return {"buckets": [], "skipped_files": [], "file_to_buckets": {}}, sorted(
            source_files
        )

    candidates_by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for bucket in proposal.get("buckets", []):
        for file_path in dict.fromkeys(bucket.get("candidate_files", [])):
            if file_path in source_files:
                candidates_by_file[file_path].append(bucket)

    endpoint_files = {
        file_path
        for endpoint in scan.api_endpoints
        for file_path in endpoint_owned_files(endpoint)
    }
    excluded_files = (
        set(topology.foundational_files)
        | set(scan.giant_file_clusters)
        | set(scan.config_files)
        | endpoint_files
    )
    deterministic_by_slug: dict[str, list[str]] = defaultdict(list)
    unresolved: list[str] = []
    for file_path in sorted(source_files):
        candidates = candidates_by_file.get(file_path, [])
        source_kind = scan.source_kind_by_file.get(
            file_path, classify_source_kind(file_path)
        )
        if (
            file_path in excluded_files
            or source_kind != "product"
            or len(candidates) != 1
        ):
            unresolved.append(file_path)
            continue
        bucket = candidates[0]
        cluster_id = str(bucket.get("cluster_id") or "")
        if not cluster_id or topology.file_cluster_id.get(file_path) != cluster_id:
            unresolved.append(file_path)
            continue
        deterministic_by_slug[str(bucket.get("slug") or "")].append(file_path)

    buckets = [
        {
            "slug": slug,
            "owned_files": files,
            "owned_symbols": [],
            "artifact_refs": [],
            "priority": 0,
        }
        for slug, files in deterministic_by_slug.items()
        if slug
    ]
    return (
        {
            "buckets": buckets,
            "skipped_files": [],
            "file_to_buckets": {
                file_path: [slug]
                for slug, files in deterministic_by_slug.items()
                for file_path in files
                if slug
            },
        },
        unresolved,
    )


def _merge_partial_assignment(
    proposal: dict[str, Any],
    deterministic: dict[str, Any],
    llm_assignment: dict[str, Any] | None,
    unresolved_files: list[str],
) -> dict[str, Any]:
    """Merge an ambiguous-file LLM delta with deterministic ownership."""
    unresolved = set(unresolved_files)
    deterministic_by_slug = {
        item.get("slug", ""): item for item in deterministic.get("buckets", [])
    }
    llm_by_slug = {
        item.get("slug", ""): item
        for item in (llm_assignment or {}).get("buckets", [])
    }
    buckets: list[dict[str, Any]] = []
    file_to_buckets: dict[str, list[str]] = defaultdict(list)

    for proposal_bucket in proposal.get("buckets", []):
        slug = str(proposal_bucket.get("slug") or "")
        deterministic_item = deterministic_by_slug.get(slug, {})
        llm_item = llm_by_slug.get(slug, {})
        owned_files = list(
            dict.fromkeys(
                list(deterministic_item.get("owned_files", []))
                + [
                    path
                    for path in llm_item.get("owned_files", [])
                    if path in unresolved
                ]
            )
        )
        for file_path in owned_files:
            file_to_buckets[file_path].append(slug)
        buckets.append(
            {
                "slug": slug,
                "owned_files": owned_files,
                "owned_symbols": list(
                    dict.fromkeys(llm_item.get("owned_symbols", []))
                ),
                "artifact_refs": list(
                    dict.fromkeys(llm_item.get("artifact_refs", []))
                ),
                "priority": int(llm_item.get("priority", 0) or 0),
            }
        )

    skipped_files = [
        path
        for path in (llm_assignment or {}).get("skipped_files", [])
        if path in unresolved
    ]
    return {
        "buckets": buckets,
        "skipped_files": list(dict.fromkeys(skipped_files)),
        "file_to_buckets": dict(file_to_buckets),
    }


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



def _attach_orphans_semantically(
    plan: DocPlan,
    scan: RepoScan,
    classification: dict[str, Any],
) -> DocPlan:
    assigned = {f for bucket in plan.buckets for f in bucket.owned_files}
    for file_path in sorted(set(scan.file_summaries) - assigned):
        attached = _attach_file_to_best_bucket(
            file_path, plan, scan, include_overview=False
        )
        if not attached:
            _attach_file_to_best_bucket(file_path, plan, scan, include_overview=True)
    return plan


def _apply_page_contracts(
    plan: DocPlan,
    scan: RepoScan,
    classification: dict[str, Any],
) -> DocPlan:
    primary = classification.get("repo_profile", {}).get("primary_type", "other")
    for bucket in plan.buckets:
        section = bucket.section
        sibling_slugs = [
            b.slug
            for b in plan.buckets
            if b.section == section and b.slug != bucket.slug
        ][:5]
        must_cover: list[str] = []
        title_tokens = _bucket_semantic_tokens(bucket)
        if primary == "research_training":
            if section == "Model Architecture":
                must_cover = [
                    "interfaces",
                    "internal mechanics",
                    "configuration",
                    "performance",
                ]
            elif section == "Training":
                must_cover = ["training loop", "state transitions", "checkpointing"]
            elif section == "Optimization":
                must_cover = ["optimizer behavior", "schedules", "parameter groups"]
            elif section == "Evaluation":
                must_cover = ["metrics", "evaluation flow", "outputs"]
            elif section == "Inference & Runtime":
                must_cover = ["runtime behavior", "request flow", "sampling or caching"]
            elif section == "Research Context":
                must_cover = ["source context", "timeline or findings", "references"]
        elif section == "Operations":
            must_cover = ["configuration", "operational concerns"]
        bucket.generation_hints = bucket.generation_hints or {}
        bucket.generation_hints["page_contract"] = {
            "intent": bucket.description or bucket.title,
            "must_cover_concepts": must_cover,
            "required_sibling_links": sibling_slugs,
            "forbidden_filler": ["miscellaneous", "various helpers", "other stuff"],
            "title_tokens": sorted(title_tokens)[:12],
        }
    return plan


def _build_file_summaries_for_bucket(bucket: DocBucket, scan: RepoScan) -> str:
    """Build condensed file summaries for decomposition context."""
    lines = []
    for fpath in bucket.owned_files:
        pf = scan.parsed_files.get(fpath)
        line_count = scan.file_line_counts.get(fpath, 0)
        if not pf:
            lines.append(f"### {fpath} ({line_count} lines)\n(no parse data)\n")
            continue
        symbol_names = [f"{s.kind}:{s.name}" for s in pf.symbols[:12]]
        lines.append(f"### {fpath} ({line_count} lines)")
        if symbol_names:
            lines.append(f"Symbols: {', '.join(symbol_names)}")
        if pf.imports:
            lines.append(f"Key imports: {', '.join(pf.imports[:8])}")
        lines.append("")
    return "\n".join(lines)


def _should_decompose(bucket: DocBucket, scan: RepoScan, threshold: int) -> bool:
    """Decide whether a bucket is broad enough to warrant decomposition.

    Uses multiple signals, not just file count.
    """
    hints = bucket.generation_hints or {}
    if hints.get("is_endpoint_ref") or hints.get("is_endpoint_family"):
        return False
    if hints.get("is_introduction_page"):
        return False

    file_count = len(bucket.owned_files)
    if file_count >= threshold:
        return True

    total_symbols = 0
    for fpath in bucket.owned_files:
        pf = scan.parsed_files.get(fpath)
        if pf:
            total_symbols += len(pf.symbols)
    if total_symbols >= 40 and file_count >= 5:
        return True

    giant_count = sum(1 for f in bucket.owned_files if f in scan.giant_file_clusters)
    return giant_count >= 1


def _consolidate_similar_buckets(plan: DocPlan, cfg: dict[str, Any]) -> DocPlan:
    """Merge near-duplicate buckets based on semantic token overlap (Jaccard similarity).

    Runs after decompose to catch cases where decomposition or the proposal step
    created overlapping pages (e.g. "Vinculum Overview" + "Vinculum Workflow").
    """
    threshold = cfg.get("consolidation_similarity_threshold", 0.70)
    buckets = list(plan.buckets)
    merged_slugs: set[str] = set()

    # Pre-compute token sets for all buckets
    token_cache: dict[str, set[str]] = {}
    for bucket in buckets:
        token_cache[bucket.slug] = _bucket_semantic_tokens(bucket)

    # Find merge candidates — iterate over all pairs
    merge_map: dict[str, str] = {}  # victim_slug → target_slug
    for i, a in enumerate(buckets):
        if a.slug in merged_slugs:
            continue
        hints_a = a.generation_hints or {}
        # Don't merge intro pages or endpoint refs
        if hints_a.get("is_introduction_page") or hints_a.get("is_endpoint_ref"):
            continue

        for j, b in enumerate(buckets):
            if j <= i or b.slug in merged_slugs:
                continue
            hints_b = b.generation_hints or {}
            if hints_b.get("is_introduction_page") or hints_b.get("is_endpoint_ref"):
                continue

            # Only consider merging buckets in the same section or with same parent
            same_section = a.section == b.section
            same_parent = a.parent_slug is not None and a.parent_slug == b.parent_slug
            if not same_section and not same_parent:
                continue

            tokens_a = token_cache[a.slug]
            tokens_b = token_cache[b.slug]
            if not tokens_a or not tokens_b:
                continue

            intersection = len(tokens_a & tokens_b)
            union = len(tokens_a | tokens_b)
            jaccard = intersection / union if union > 0 else 0.0

            if jaccard >= threshold:
                # Merge smaller into larger (by file count)
                if len(a.owned_files) >= len(b.owned_files):
                    target, victim = a, b
                else:
                    target, victim = b, a
                merge_map[victim.slug] = target.slug
                merged_slugs.add(victim.slug)
                console.print(
                    f"[cyan]  ↳ Merged '{victim.title}' into '{target.title}' "
                    f"(similarity: {jaccard:.2f})[/cyan]"
                )

    if not merge_map:
        return plan

    # Execute merges
    slug_to_bucket = {b.slug: b for b in buckets}
    for victim_slug, target_slug in merge_map.items():
        # Follow chains: if target was also merged, find the final target
        final_target = target_slug
        visited: set[str] = set()
        while final_target in merge_map:
            if final_target in visited:
                break
            visited.add(final_target)
            final_target = merge_map[final_target]

        target = slug_to_bucket[final_target]
        victim = slug_to_bucket[victim_slug]

        # Merge owned_files (deduplicated, preserving order)
        existing_files = set(target.owned_files)
        for f in victim.owned_files:
            if f not in existing_files:
                target.owned_files.append(f)
                existing_files.add(f)

        # Merge owned_symbols
        existing_symbols = set(target.owned_symbols)
        for s in victim.owned_symbols:
            if s not in existing_symbols:
                target.owned_symbols.append(s)
                existing_symbols.add(s)

        # Merge artifact_refs
        existing_artifacts = set(target.artifact_refs)
        for a in victim.artifact_refs:
            if a not in existing_artifacts:
                target.artifact_refs.append(a)
                existing_artifacts.add(a)

        # Merge required_sections and required_diagrams
        target.required_sections = list(
            dict.fromkeys(target.required_sections + victim.required_sections)
        )
        target.required_diagrams = list(
            dict.fromkeys(target.required_diagrams + victim.required_diagrams)
        )

        # Merge coverage_targets
        target.coverage_targets = list(
            dict.fromkeys(target.coverage_targets + victim.coverage_targets)
        )

        # Clear cached semantic tokens so they get recomputed
        if hasattr(target, "_semantic_tokens"):
            delattr(target, "_semantic_tokens")

    # Remove merged buckets
    new_buckets = [b for b in buckets if b.slug not in merged_slugs]

    # Clean up nav_structure
    new_nav = {}
    remaining_slugs = {b.slug for b in new_buckets}
    for section_name, slugs in plan.nav_structure.items():
        cleaned = [s for s in slugs if s in remaining_slugs]
        if cleaned:
            new_nav[section_name] = cleaned

    plan.buckets = new_buckets
    plan.nav_structure = new_nav

    if merged_slugs:
        console.print(
            f"[green]  Consolidated {len(merged_slugs)} duplicate bucket(s) "
            f"→ {len(new_buckets)} buckets remaining[/green]"
        )

    return plan


def _auto_generate_endpoint_refs(
    plan: DocPlan,
    scan: RepoScan,
    include_endpoint_pages: bool = True,
    cfg: dict[str, Any] | None = None,
) -> DocPlan:
    """Attach scanned endpoint details to grouped API-reference buckets.

    Historically this created one generated page per concrete route. That made
    large backend repos produce hundreds of thin pages. Runtime-discovered
    endpoints now feed endpoint-family pages, with bounded grouped fallback pages
    for endpoints that do not match an existing family.
    """
    import re as _re

    NOISE_PATHS = {
        "/health",
        "/healthz",
        "/ready",
        "/readyz",
        "/alive",
        "/ping",
        "/status",
        "/metrics",
        "/version",
        "/info",
        "/favicon.ico",
        "/robots.txt",
        "/sitemap.xml",
    }
    NOISE_SUFFIXES = (".svg", ".png", ".jpg", ".ico", ".css", ".js", ".map")
    endpoint_domain_keywords = _build_repo_endpoint_keywords(scan, cfg or {})

    endpoints = scan.published_api_endpoints
    if not include_endpoint_pages or not endpoints:
        return plan

    repo_profile = plan.classification.get("repo_profile", {})
    primary_type = repo_profile.get("primary_type", "other")
    restrict_endpoints = primary_type not in ("backend_service", "falcon_backend")

    def _resource_from_path(path: str) -> str:
        clean = _re.sub(r"^/(?:api/)?(?:v\d+/)?", "", path)
        parts_list = [
            p
            for p in clean.split("/")
            if p and not p.startswith(":") and not p.startswith("{")
        ]
        return parts_list[0] if parts_list else "general"

    def _resource_aliases(resource: str) -> set[str]:
        normalized = resource.lower().replace("_", "-")
        aliases = {normalized, normalized.replace("-", "_")}
        if normalized.endswith("s") and len(normalized) > 3:
            singular = normalized[:-1]
            aliases.update({singular, singular.replace("-", "_")})
        else:
            aliases.add(f"{normalized}s")
        return aliases

    def _bucket_tokens(bucket: DocBucket) -> set[str]:
        return _normalize_tokens(
            bucket.slug,
            bucket.title,
            bucket.description,
            " ".join(bucket.owned_symbols[:20]),
            " ".join(bucket.owned_files[:20]),
        )

    def _endpoint_tokens(ep: dict) -> set[str]:
        owned_files = endpoint_owned_files(ep)
        path_parts = _re.split(r"[^A-Za-z0-9_+-]+", ep.get("path", ""))
        return _normalize_tokens(
            ep.get("path", ""),
            ep.get("handler", ""),
            ep.get("name", ""),
            ep.get("summary", ""),
            " ".join(path_parts),
            " ".join(owned_files),
        )

    def _domain_labels(tokens: set[str]) -> set[str]:
        labels: set[str] = set()
        for label, keywords in endpoint_domain_keywords.items():
            matched = False
            for token in tokens:
                for keyword in keywords:
                    if keyword == token:
                        matched = True
                    elif len(keyword) >= 4 and keyword in token:
                        matched = True
                    elif len(token) >= 4 and token in keyword:
                        matched = True
                    if matched:
                        break
                if matched:
                    break
            if matched:
                labels.add(label)
        return labels

    def _slugify(value: str) -> str:
        return _re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "api"

    def _unique_slug(base_slug: str, existing_slugs: set[str]) -> str:
        slug = base_slug
        suffix = 2
        while slug in existing_slugs:
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        existing_slugs.add(slug)
        return slug

    def _is_noise_endpoint(ep: dict) -> bool:
        method = ep.get("method", "GET").upper()
        path = ep.get("path", "/unknown")
        handler = ep.get("handler", "")
        path_lower = path.lower()
        if path_lower in NOISE_PATHS:
            return True
        if any(path_lower.endswith(s) for s in NOISE_SUFFIXES):
            return True
        return path == "/" and method == "GET" and handler in ("root", "index", "home")

    endpoints = [ep for ep in endpoints if not _is_noise_endpoint(ep)]
    if not endpoints:
        return plan

    # Match against planned API-reference buckets, not only path-shaped
    # endpoint-family slugs. LLM plans often use semantic pages such as
    # user_auth_profile for /login, /logout, and /register.
    family_buckets = []
    for bucket in plan.buckets:
        hints = bucket.generation_hints or {}
        if hints.get("is_endpoint_ref") or hints.get("is_introduction_page"):
            continue
        section = (bucket.section or "").lower()
        if (
            hints.get("is_endpoint_family")
            or hints.get("include_endpoint_detail")
            or hints.get("prompt_style") == "endpoint"
            or section.startswith("api reference")
        ):
            family_buckets.append(bucket)

    bucket_profiles: dict[str, tuple[set[str], set[str]]] = {
        bucket.slug: (_bucket_tokens(bucket), _domain_labels(_bucket_tokens(bucket)))
        for bucket in family_buckets
    }

    def _best_endpoint_family(ep: dict) -> DocBucket | None:
        resource = _resource_from_path(ep.get("path", "/unknown"))
        resource_aliases = _resource_aliases(resource)
        ep_files = set(endpoint_owned_files(ep))
        ep_tokens = _endpoint_tokens(ep)
        ep_labels = _domain_labels(ep_tokens)

        best_bucket: DocBucket | None = None
        best_score = 0
        for bucket in family_buckets:
            bucket_tokens, bucket_labels = bucket_profiles[bucket.slug]
            score = 0
            score += len(ep_tokens & bucket_tokens) * 3
            score += len(ep_labels & bucket_labels) * 6
            if resource_aliases & bucket_tokens:
                score += 6
            if ep_files and ep_files & set(bucket.owned_files):
                score += 4
            if (bucket.generation_hints or {}).get("is_endpoint_family"):
                score += 1
            if score > best_score:
                best_score = score
                best_bucket = bucket

        return best_bucket if best_score >= 6 else None

    unmatched: list[dict] = []
    for ep in endpoints:
        if restrict_endpoints and not family_buckets:
            continue
        parent = _best_endpoint_family(ep)
        ep_files = endpoint_owned_files(ep)

        if parent:
            parent.owned_files = sorted({*parent.owned_files, *ep_files})
            parent.generation_hints["is_endpoint_family"] = True
            parent.generation_hints["include_endpoint_detail"] = True
            parent.generation_hints.setdefault("include_openapi", True)
            parent.generation_hints.setdefault("prompt_style", "endpoint")
        else:
            unmatched.append(ep)

    if unmatched:
        existing_slugs = {b.slug for b in plan.buckets}
        grouped: dict[str, list[dict]] = defaultdict(list)
        sparse: list[dict] = []
        fallback_page_count = 0

        for ep in unmatched:
            ep_labels = sorted(_domain_labels(_endpoint_tokens(ep)))
            if ep_labels:
                grouped[ep_labels[0]].append(ep)
                continue
            grouped[_resource_from_path(ep.get("path", "/unknown"))].append(ep)

        for group_key, group_eps in list(grouped.items()):
            if len(group_eps) < 3 and group_key not in endpoint_domain_keywords:
                sparse.extend(group_eps)
                del grouped[group_key]

        if sparse:
            grouped["supporting"] = sparse

        for group_key, group_eps in sorted(grouped.items()):
            display = group_key.replace("_", " ").replace("-", " ").title()
            base_slug = (
                "additional-api-endpoints"
                if group_key == "supporting"
                else f"{_slugify(group_key)}-api-endpoints"
            )
            slug = _unique_slug(base_slug, existing_slugs)
            ep_files = sorted(
                {f for ep in group_eps for f in endpoint_owned_files(ep)}
            )
            handlers = sorted(
                {ep.get("handler", "") for ep in group_eps if ep.get("handler")}
            )
            plan.buckets.append(
                DocBucket(
                    bucket_type="endpoint-family",
                    title=(
                        "Additional API Endpoints"
                        if group_key == "supporting"
                        else f"{display} API Endpoints"
                    ),
                    slug=slug,
                    section="API Reference",
                    description=(
                        "Grouped API reference for scanned runtime endpoints that did "
                        "not match a planned endpoint family "
                        f"({len(group_eps)} endpoints)."
                    ),
                    owned_files=ep_files,
                    owned_symbols=handlers[:50],
                    required_sections=[
                        "route_overview",
                        "auth_validation",
                        "execution_flow",
                        "downstream_calls",
                        "state_changes",
                        "response_errors",
                        "diagrams",
                    ],
                    generation_hints={
                        "is_endpoint_family": True,
                        "include_endpoint_detail": True,
                        "include_openapi": True,
                        "prompt_style": "endpoint",
                        "icon": "globe-alt",
                    },
                    priority=24,
                )
            )
            fallback_page_count += 1
            plan.nav_structure.setdefault("API Reference", []).append(slug)
    else:
        fallback_page_count = 0

    attached = len(endpoints) - len(unmatched)
    if attached or unmatched:
        console.print(
            "[green]✓ Grouped "
            f"{attached} endpoint(s) into family pages"
            f"{f' and {len(unmatched)} into {fallback_page_count} grouped fallback page(s)' if unmatched else ''}"
            "[/green]"
        )

    return plan


def _stable_specialized_slug(base_slug: str, existing: set[str]) -> str:
    slug = base_slug
    suffix = 2
    while slug in existing:
        slug = f"{base_slug}-{suffix}"
        suffix += 1
    return slug


def _validate_coverage(plan: DocPlan, scan: RepoScan) -> DocPlan:
    """Ensure all important source files are assigned to at least one bucket."""
    all_assigned: set[str] = set()
    for bucket in plan.buckets:
        all_assigned.update(bucket.owned_files)
    skipped = set(plan.skipped_files)

    all_source = set(scan.file_summaries.keys())
    orphaned = all_source - all_assigned - skipped

    if orphaned:
        orphan_groups: dict[str, list[str]] = defaultdict(list)
        for f in orphaned:
            parts = f.split("/")
            group = parts[0] if len(parts) > 1 else "root"
            orphan_groups[group].append(f)

        for group_name, files in orphan_groups.items():
            # Try to find an existing bucket that covers this directory
            matched = False
            for bucket in plan.buckets:
                if any(f.startswith(group_name + "/") for f in bucket.owned_files):
                    bucket.owned_files.extend(files)
                    matched = True
                    break

            if not matched:
                best_bucket = None
                best_overlap = 0
                orphan_imports: set[str] = set()
                for f in files:
                    pf = scan.parsed_files.get(f)
                    if pf:
                        orphan_imports.update(pf.imports)

                if orphan_imports:
                    for bucket in plan.buckets:
                        bucket_imports: set[str] = set()
                        for bf in bucket.owned_files[:10]:
                            bpf = scan.parsed_files.get(bf)
                            if bpf:
                                bucket_imports.update(bpf.imports)
                        overlap = len(orphan_imports & bucket_imports)
                        if overlap > best_overlap:
                            best_overlap = overlap
                            best_bucket = bucket

                if best_bucket and best_overlap >= 2:
                    best_bucket.owned_files.extend(files)
                    matched = True
                else:
                    representative_symbols: list[str] = []
                    for f in files[:3]:
                        pf = scan.parsed_files.get(f)
                        if pf:
                            representative_symbols.extend(
                                s.name
                                for s in pf.symbols[:3]
                                if s.kind in ("class", "function")
                            )
                    if representative_symbols:
                        title = f"{', '.join(representative_symbols[:3])} and Related"
                    else:
                        title = f"{group_name.replace('_', ' ').replace('-', ' ').title()} Module"

                    title = _clean_fallback_bucket_title(title, group_name)
                    base_slug = f"{group_name.lower().replace(' ', '-').replace('_', '-')}-module"
                    existing_slugs = {b.slug for b in plan.buckets}
                    slug = base_slug
                    _counter = 2
                    while slug in existing_slugs:
                        slug = f"{base_slug}-{_counter}"
                        _counter += 1
                    section = _fallback_module_section(plan)
                    plan.buckets.append(
                        DocBucket(
                            bucket_type="module",
                            title=title,
                            slug=slug,
                            section=section,
                            description=f"Documentation covering {title.lower()}",
                            owned_files=files,
                            required_sections=["overview", "details", "diagrams"],
                            generation_hints={
                                "prompt_style": "general",
                                "icon": "cube",
                            },
                            priority=50,
                        )
                    )
                    if section not in plan.nav_structure:
                        plan.nav_structure[section] = []
                    plan.nav_structure[section].append(slug)

        plan.orphaned_files = sorted(orphaned)

    return plan


def _clean_fallback_bucket_title(title: str, group_name: str) -> str:
    if title.endswith(" and Related"):
        return (
            f"{group_name.replace('_', ' ').replace('-', ' ').title()} Module Internals"
        )
    return title


def _fallback_module_section(plan: DocPlan) -> str:
    # Last-resort fallback only — use a neutral section name for any repo type
    return "Other"


def _fallback_plan(scan: RepoScan, cfg: dict[str, Any]) -> DocPlan:
    """Generate a reasonable bucket-based plan without LLM, using repo structure."""
    import re

    buckets: list[DocBucket] = []
    nav: dict[str, list[str]] = defaultdict(list)
    assigned_files: set[str] = set()

    # ── Architecture/Overview ────────────────────────────────────────────
    overview_files = scan.entry_points[:5] + scan.config_files[:3]
    buckets.append(
        DocBucket(
            bucket_type="architecture",
            title="Architecture & Overview",
            slug="architecture",
            section="Overview",
            description="Project overview, architecture, and high-level design",
            owned_files=overview_files,
            required_sections=[
                "overview",
                "architecture",
                "key_components",
                "configuration",
                "diagrams",
            ],
            generation_hints={
                "is_introduction_page": True,
                "prompt_style": "system",
                "icon": "server",
            },
            priority=0,
        )
    )
    nav["Overview"].append("architecture")
    assigned_files.update(overview_files)

    # ── Setup ────────────────────────────────────────────────────────────
    if scan.config_files:
        buckets.append(
            DocBucket(
                bucket_type="setup",
                title="Setup & Configuration",
                slug="setup",
                section="Getting Started",
                description="Installation, environment variables, and configuration",
                owned_files=[],
                artifact_refs=scan.config_files[:10],
                required_sections=[
                    "overview",
                    "prerequisites",
                    "installation",
                    "configuration",
                    "environment_variables",
                    "verification",
                ],
                generation_hints={"prompt_style": "system", "icon": "cog"},
                priority=1,
            )
        )
        nav["Getting Started"].append("setup")

    # ── Categorize files ─────────────────────────────────────────────────
    ROLE_DIRS = {
        "middleware": ["middleware", "middlewares"],
        "models": ["model", "models", "schemas", "entities"],
        "routes": ["route", "routes", "router", "routers"],
        "controllers": ["controller", "controllers", "handlers"],
        "services": ["service", "services"],
        "utils": ["util", "utils", "helpers", "lib", "common"],
        "config": ["config", "configs", "settings"],
    }

    dir_to_role: dict[str, str] = {}
    for role, dir_names in ROLE_DIRS.items():
        for d in dir_names:
            dir_to_role[d] = role

    role_buckets_map: dict[str, list[str]] = defaultdict(list)
    domain_buckets_map: dict[str, list[str]] = defaultdict(list)

    for rel_path in scan.file_summaries:
        if scan.source_kind_by_file.get(rel_path, classify_source_kind(rel_path)) in {
            "fixture",
            "generated",
        }:
            continue
        parts = rel_path.split("/")
        if (
            scan.source_kind_by_file.get(rel_path, classify_source_kind(rel_path))
            == "test"
        ):
            continue

        matched_role = None
        for part in parts:
            if part.lower() in dir_to_role:
                matched_role = dir_to_role[part.lower()]
                break

        if matched_role:
            role_buckets_map[matched_role].append(rel_path)
        else:
            if len(parts) >= 3 and parts[0] in ("src", "api", "app", "pkg", "internal"):
                group = parts[1]
            elif len(parts) >= 2:
                group = parts[0]
            else:
                group = "root"
            domain_buckets_map[group].append(rel_path)

    # ── Database: Schema & Models ────────────────────────────────────────
    model_files = role_buckets_map.get("models", [])
    db_model_files: list[str] = list(model_files)
    if (
        scan.artifact_scan
        and hasattr(scan.artifact_scan, "database_scan")
        and scan.artifact_scan.database_scan
    ):
        db_scan = scan.artifact_scan.database_scan
        for mf in db_scan.model_files:
            if mf.file_path not in db_model_files:
                db_model_files.append(mf.file_path)
        db_model_files.extend(
            f for f in db_scan.schema_files if f not in db_model_files
        )
    if db_model_files:
        buckets.append(
            DocBucket(
                bucket_type="database",
                title="Database & Schema",
                slug="database-schema",
                section="Database",
                description="Database schemas, models, ER diagrams, relationships, and migrations",
                owned_files=db_model_files,
                required_sections=[
                    "overview",
                    "er_diagram",
                    "table_definitions",
                    "relationships",
                    "migrations",
                    "query_patterns",
                    "configuration",
                ],
                required_diagrams=["er_diagram"],
                generation_hints={
                    "include_database_context": True,
                    "prompt_style": "database",
                    "icon": "database",
                },
                priority=3,
            )
        )
        nav["Database"].append("database-schema")
        assigned_files.update(db_model_files)

    # ── Middleware & Auth ─────────────────────────────────────────────────
    mw_files = role_buckets_map.get("middleware", [])
    if mw_files:
        buckets.append(
            DocBucket(
                bucket_type="middleware",
                title="Middleware & Authentication",
                slug="middleware-auth",
                section="Architecture",
                description="Authentication, authorization, rate limiting, and middleware pipeline",
                owned_files=mw_files,
                required_sections=[
                    "overview",
                    "architecture",
                    "key_components",
                    "configuration",
                    "diagrams",
                ],
                generation_hints={"prompt_style": "system", "icon": "shield-check"},
                priority=4,
            )
        )
        nav["Architecture"].append("middleware-auth")
        assigned_files.update(mw_files)

    # ── Feature buckets from domain dirs ─────────────────────────────────
    for group_name, files in sorted(domain_buckets_map.items()):
        if group_name in (".", "root") and len(files) <= 2:
            buckets[0].owned_files.extend(files)
            assigned_files.update(files)
            continue

        slug = f"{group_name.lower().replace(' ', '-').replace('_', '-')}"
        buckets.append(
            DocBucket(
                bucket_type="feature",
                title=f"{group_name.replace('_', ' ').replace('-', ' ').title()}",
                slug=slug,
                section="Features",
                description=f"Documentation for {group_name} feature area",
                owned_files=files,
                required_sections=[
                    "overview",
                    "main_workflows",
                    "core_helpers",
                    "state_transitions",
                    "edge_cases",
                    "diagrams",
                ],
                generation_hints={"prompt_style": "feature", "icon": "bolt"},
                priority=10,
            )
        )
        nav["Features"].append(slug)
        assigned_files.update(files)

    # ── Remaining role-based files ───────────────────────────────────────
    for role in ["controllers", "services", "utils", "routes", "config"]:
        files = [f for f in role_buckets_map.get(role, []) if f not in assigned_files]
        if not files:
            continue
        merged = False
        for bucket in buckets:
            if bucket.generation_hints.get("prompt_style") == "feature":
                overlap = set(f.split("/")[0] for f in files) & set(
                    f.split("/")[0] for f in bucket.owned_files
                )
                if overlap:
                    bucket.owned_files.extend(files)
                    assigned_files.update(files)
                    merged = True
                    break
        if not merged:
            buckets.append(
                DocBucket(
                    bucket_type="module",
                    title=f"{role.replace('_', ' ').title()}",
                    slug=f"{role}",
                    section="Modules",
                    description=f"{role.title()} layer documentation",
                    owned_files=files,
                    required_sections=["overview", "details", "diagrams"],
                    generation_hints={"prompt_style": "general", "icon": "cube"},
                    priority=15,
                )
            )
            nav["Modules"].append(role)
            assigned_files.update(files)

    # ── Endpoint families ────────────────────────────────────────────────
    if scan.published_api_endpoints:
        resource_groups: dict[str, list[dict]] = defaultdict(list)
        for ep in scan.published_api_endpoints:
            path = ep.get("path", "")
            clean = re.sub(r"^/(?:api/)?(?:v\d+/)?", "", path)
            parts_list = [
                p
                for p in clean.split("/")
                if p and not p.startswith(":") and not p.startswith("{")
            ]
            resource = parts_list[0] if parts_list else "general"
            resource_groups[resource].append(ep)

        for resource, eps in sorted(resource_groups.items()):
            ep_files = sorted({f for ep in eps for f in endpoint_owned_files(ep)})
            slug = f"{resource}-api"
            buckets.append(
                DocBucket(
                    bucket_type="endpoint-family",
                    title=f"{resource.replace('_', ' ').replace('-', ' ').title()} API",
                    slug=slug,
                    section="API Reference",
                    description=f"API reference for {resource} endpoints ({len(eps)} endpoints)",
                    owned_files=ep_files,
                    required_sections=[
                        "route_overview",
                        "auth_validation",
                        "execution_flow",
                        "downstream_calls",
                        "state_changes",
                        "response_errors",
                        "diagrams",
                    ],
                    generation_hints={
                        "is_endpoint_family": True,
                        "include_endpoint_detail": True,
                        "include_openapi": True,
                        "prompt_style": "endpoint",
                        "icon": "globe-alt",
                    },
                    priority=20,
                )
            )
            nav["API Reference"].append(slug)
            assigned_files.update(ep_files)

    # ── Skipped files ────────────────────────────────────────────────────
    all_source = set(scan.file_summaries.keys())
    test_files = sorted(
        f
        for f in all_source
        if any(p in f.split("/") for p in ("tests", "test", "__tests__", "spec"))
    )

    plan = DocPlan(
        buckets=buckets,
        nav_structure=dict(nav),
        skipped_files=test_files,
    )
    return _ensure_database_runtime_and_interface_buckets(plan, scan, cfg)


from .utils import _parse_json_response
from .specializations import _ensure_database_runtime_and_interface_buckets
