from .common import *


def _proposal_bucket_tokens(bucket: dict[str, Any]) -> set[str]:
    cache = PROPOSAL_BUCKET_TOKEN_CACHE.get(id(bucket))
    if cache is not None:
        return cache
    cache = _normalize_tokens(
        bucket.get("title", ""),
        bucket.get("slug", ""),
        bucket.get("section", ""),
        bucket.get("description", ""),
        " ".join(bucket.get("coverage_targets", [])),
        bucket.get("bucket_type", ""),
    )
    PROPOSAL_BUCKET_TOKEN_CACHE[id(bucket)] = cache
    return cache


def _is_low_value_utility_bucket(bucket: dict[str, Any]) -> bool:
    tokens = _proposal_bucket_tokens(bucket)
    return (
        "utility" in bucket.get("bucket_type", "")
        or "utilities" in bucket.get("title", "").lower()
        or any(
            token in tokens
            for token in {"random", "string", "date", "config", "helper"}
        )
    )


def _is_incidental_http_bucket(bucket: dict[str, Any]) -> bool:
    tokens = _proposal_bucket_tokens(bucket)
    return "integration" in bucket.get("bucket_type", "") and any(
        token in tokens for token in {"http", "client", "download", "fetch"}
    )


def _best_proposal_merge_target(
    bucket: dict[str, Any],
    candidates: list[dict[str, Any]],
    preferred_tokens: set[str],
) -> dict[str, Any] | None:
    bucket_tokens = _proposal_bucket_tokens(bucket)
    best_target = None
    best_score = 0
    for candidate in candidates:
        if candidate is bucket:
            continue
        candidate_tokens = _proposal_bucket_tokens(candidate)
        overlap = len(bucket_tokens & candidate_tokens)
        overlap += len(preferred_tokens & candidate_tokens) * 2
        if overlap > best_score:
            best_score = overlap
            best_target = candidate
    return best_target if best_score >= 2 else None


def _remove_slug_from_nav(nav_structure: dict[str, list[str]], slug: str) -> None:
    for section_name, slugs in list(nav_structure.items()):
        if slug in slugs:
            nav_structure[section_name] = [s for s in slugs if s != slug]
            if not nav_structure[section_name]:
                del nav_structure[section_name]


def _refine_proposal(
    proposal: dict[str, Any],
    scan: RepoScan,
    classification: dict[str, Any],
) -> dict[str, Any]:
    """Clean proposal noise before assignment."""
    repo_profile = classification.get("repo_profile", {})
    primary = repo_profile.get("primary_type", "other")
    buckets = list(proposal.get("buckets", []))
    nav_structure = dict(proposal.get("nav_structure", {}))
    first_party_tokens: set[str] = set()
    for identity in scan.integration_identities or []:
        if getattr(identity, "party", "third_party") != "first_party":
            continue
        first_party_tokens.update(
            _normalize_tokens(identity.name, identity.display_name)
        )

    utility_buckets = [
        b
        for b in buckets
        if _is_low_value_utility_bucket(b) and len(b.get("candidate_files", [])) <= 2
    ]
    if len(utility_buckets) >= 2:
        merged_files: list[str] = []
        merged_targets: list[str] = []
        merged_diagrams: list[str] = []
        merged_sections: list[str] = []
        for bucket in utility_buckets:
            merged_files.extend(bucket.get("candidate_files", []))
            merged_targets.extend(bucket.get("coverage_targets", []))
            merged_diagrams.extend(bucket.get("required_diagrams", []))
            merged_sections.extend(bucket.get("required_sections", []))
            _remove_slug_from_nav(nav_structure, bucket.get("slug", ""))
        buckets = [b for b in buckets if b not in utility_buckets]
        utilities_slug = "common-utilities-configuration"
        merged_bucket = {
            "bucket_type": "utility-group",
            "title": "Common Utilities & Configuration",
            "slug": utilities_slug,
            "section": "Operations",
            "description": "Shared helpers and configuration utilities used across the repository",
            "rationale": "Merge low-value single-file utility pages into one stronger page.",
            "candidate_files": sorted(set(merged_files)),
            "candidate_domains": ["shared"],
            "depends_on": ["system-overview"] if primary == "research_training" else [],
            "required_sections": [
                "overview",
                "shared_helpers",
                "configuration",
                "usage_patterns",
            ],
            "required_diagrams": sorted(set(merged_diagrams))[:2]
            or ["architecture_flow"],
            "coverage_targets": sorted(set(merged_targets))[:10],
            "generation_hints": {
                "include_endpoint_detail": False,
                "is_endpoint_ref": False,
                "is_endpoint_family": False,
                "include_openapi": False,
                "include_database_context": False,
                "include_integration_detail": False,
                "is_introduction_page": False,
                "prompt_style": "general",
                "icon": "cube",
            },
        }
        buckets.append(merged_bucket)
        nav_structure.setdefault("Operations", []).append(utilities_slug)

    if primary not in {"backend_service", "falcon_backend"}:
        for bucket in list(buckets):
            if not _is_incidental_http_bucket(bucket):
                continue
            target = _best_proposal_merge_target(
                bucket,
                buckets,
                {
                    "data",
                    "dataset",
                    "pipeline",
                    "evaluation",
                    "infer",
                    "runtime",
                    "train",
                },
            )
            if not target:
                continue
            target.setdefault("candidate_files", []).extend(
                bucket.get("candidate_files", [])
            )
            target.setdefault("coverage_targets", []).extend(
                bucket.get("coverage_targets", [])
            )
            target.setdefault("required_sections", []).extend(
                bucket.get("required_sections", [])
            )
            _remove_slug_from_nav(nav_structure, bucket.get("slug", ""))
            buckets.remove(bucket)

    if first_party_tokens:
        for bucket in buckets:
            if "integration" not in bucket.get("bucket_type", ""):
                continue
            bucket_tokens = _proposal_bucket_tokens(bucket)
            if not (bucket_tokens & first_party_tokens):
                continue
            bucket["bucket_type"] = "subsystem"
            bucket["section"] = (
                "Runtime & Frameworks"
                if primary in {"backend_service", "falcon_backend"}
                else "Architecture"
            )
            bucket.setdefault("generation_hints", {})["include_integration_detail"] = (
                False
            )
            bucket["generation_hints"]["prompt_style"] = "system"

    proposal["buckets"] = buckets
    proposal["nav_structure"] = nav_structure
    return proposal


def _file_semantic_tokens(file_path: str, scan: RepoScan) -> set[str]:
    cached = scan.semantic_file_token_cache.get(file_path)
    if cached is not None:
        return cached
    parsed = scan.parsed_files.get(file_path)
    imports = parsed.imports[:12] if parsed else []
    symbols = [symbol.name for symbol in parsed.symbols[:12]] if parsed else []
    tokens = _normalize_tokens(file_path, " ".join(imports), " ".join(symbols))
    scan.semantic_file_token_cache[file_path] = tokens
    return tokens


def _bucket_semantic_tokens(bucket: DocBucket) -> set[str]:
    cached = getattr(bucket, "_semantic_tokens", None)
    if cached is not None:
        return cached
    tokens = _normalize_tokens(
        bucket.title,
        bucket.slug,
        bucket.section,
        bucket.description,
        " ".join(bucket.coverage_targets),
        bucket.bucket_type,
        " ".join(
            bucket.generation_hints.get("page_contract", {}).get(
                "must_cover_concepts", []
            )
        )
        if bucket.generation_hints
        else "",
    )
    bucket._semantic_tokens = tokens
    return tokens


def _attach_file_to_best_bucket(
    file_path: str,
    plan: DocPlan,
    scan: RepoScan,
    *,
    include_overview: bool = False,
) -> bool:
    file_tokens = _file_semantic_tokens(file_path, scan)
    best_bucket = None
    best_score = 0
    curated_bucket_types = {
        "start_here_index",
        "start_here_setup",
        "domain_glossary",
        "debug_runbook",
    }
    for bucket in plan.buckets:
        hints = bucket.generation_hints or {}
        if not include_overview and hints.get("is_introduction_page"):
            continue
        if bucket.bucket_type in curated_bucket_types and file_path not in bucket.owned_files:
            continue
        bucket_tokens = _bucket_semantic_tokens(bucket)
        score = len(file_tokens & bucket_tokens)
        if file_path in bucket.owned_files:
            score += 2
        if score > best_score:
            best_score = score
            best_bucket = bucket
    if best_bucket and best_score >= 2:
        if file_path not in best_bucket.owned_files:
            best_bucket.owned_files.append(file_path)
        return True
    return False


def _summary_file_score(file_path: str, scan: RepoScan) -> int:
    score = 0
    if file_path in scan.entry_points:
        score += 5
    if file_path in scan.config_files:
        score += 4
    lower = file_path.lower()
    if any(
        token in lower
        for token in ("app", "main", "server", "config", "settings", "routes")
    ):
        score += 3
    if file_path in scan.giant_file_clusters:
        score += 2
    return score


def _refine_bucket_ownership(
    plan: DocPlan,
    scan: RepoScan,
    classification: dict[str, Any],
) -> DocPlan:
    """Trim umbrella ownership and attach semantically related files before fallback."""
    assigned = {f for bucket in plan.buckets for f in bucket.owned_files}
    for file_path in sorted(set(scan.file_summaries) - assigned):
        _attach_file_to_best_bucket(file_path, plan, scan, include_overview=False)

    for bucket in plan.buckets:
        hints = bucket.generation_hints or {}
        if not hints.get("is_introduction_page"):
            continue
        ranked = sorted(
            set(bucket.owned_files),
            key=lambda path: (-_summary_file_score(path, scan), path),
        )
        keep_count = (
            8
            if classification.get("repo_profile", {}).get("primary_type")
            == "research_training"
            else 10
        )
        bucket.owned_files = ranked[:keep_count]
    return plan


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


def _decompose_buckets(
    plan: DocPlan,
    scan: RepoScan,
    cfg: dict,
    llm: LLMClient,
    repo_profile: dict,
) -> DocPlan:
    """Decompose broad buckets into focused sub-topics (parallelized LLM calls)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from .heuristics import _llm_step

    threshold = cfg.get("decompose_threshold", 7)
    new_buckets: list[DocBucket] = []
    new_nav = dict(plan.nav_structure)
    repo_profile_str = json.dumps(repo_profile, indent=2) if repo_profile else "unknown"
    existing_slugs = {b.slug for b in plan.buckets}

    # Build existing bucket context for overlap avoidance
    all_bucket_titles = [
        f"- {b.title} ({b.slug}) — {b.description[:80]}" for b in plan.buckets
    ]

    # Separate buckets into those needing decompose and those that don't
    candidates: list[DocBucket] = []
    for bucket in plan.buckets:
        if not _should_decompose(bucket, scan, threshold):
            new_buckets.append(bucket)
        else:
            candidates.append(bucket)

    if not candidates:
        return plan

    # Build all prompts upfront
    prompts: dict[str, tuple[DocBucket, str]] = {}
    for bucket in candidates:
        other_buckets_str = "\n".join(
            line for line in all_bucket_titles if f"({bucket.slug})" not in line
        )
        file_summaries = _build_file_summaries_for_bucket(bucket, scan)
        prompt = DECOMPOSE_PROMPT.format(
            title=bucket.title,
            section=bucket.section,
            bucket_type=bucket.bucket_type,
            description=bucket.description,
            file_count=len(bucket.owned_files),
            file_list="\n".join(
                f"  - {f} ({scan.file_line_counts.get(f, 0)} lines)"
                for f in bucket.owned_files
            ),
            file_summaries=file_summaries[:15000],
            existing_buckets=other_buckets_str or "(none)",
            repo_profile=repo_profile_str,
        )
        prompts[bucket.slug] = (bucket, prompt)

    # Fire all decompose LLM calls in parallel
    max_workers = min(cfg.get("max_parallel_workers", 6), len(candidates))
    console.print(
        f"  [dim]Decomposing {len(candidates)} bucket(s) with {max_workers} workers...[/dim]"
    )
    decompose_results: dict[str, dict | None] = {}

    def _decompose_one(slug: str, prompt: str) -> tuple[str, dict | None]:
        return slug, _llm_step(llm, DECOMPOSE_SYSTEM, prompt, f"decompose-{slug}")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_decompose_one, slug, prompt): slug
            for slug, (_, prompt) in prompts.items()
        }
        for future in as_completed(futures):
            slug, result = future.result()
            decompose_results[slug] = result

    # Process results sequentially (modifies shared state: existing_slugs, new_nav)
    for bucket in candidates:
        result = decompose_results.get(bucket.slug)

        if not result or not result.get("sub_topics") or len(result["sub_topics"]) < 2:
            new_buckets.append(bucket)
            continue

        nav_section = result.get("nav_section", f"{bucket.section} > {bucket.title}")
        keep_parent = result.get("keep_parent_overview", False)
        sub_slugs: list[str] = []
        hints = bucket.generation_hints or {}

        if keep_parent:
            overview_bucket = DocBucket(
                bucket_type=bucket.bucket_type,
                title=f"{bucket.title} Overview",
                slug=bucket.slug,
                section=nav_section,
                description=f"Overview of {bucket.title} — how the sub-components fit together",
                depends_on=bucket.depends_on,
                owned_files=bucket.owned_files[:3],
                owned_symbols=[],
                artifact_refs=bucket.artifact_refs,
                required_sections=["overview", "architecture", "component_summary"],
                required_diagrams=bucket.required_diagrams or ["architecture_flow"],
                coverage_targets=[],
                generation_hints={
                    **{k: v for k, v in hints.items() if k != "is_introduction_page"},
                    "prompt_style": "system",
                },
                priority=bucket.priority,
            )
            new_buckets.append(overview_bucket)
            sub_slugs.append(bucket.slug)

        for i, sub in enumerate(result["sub_topics"]):
            sub_slug = sub["slug"]
            if sub_slug in existing_slugs:
                sub_slug = f"{sub_slug}-{bucket.slug[:8]}"
            if sub_slug in existing_slugs:
                sub_slug = f"{sub_slug}-{i}"
            existing_slugs.add(sub_slug)

            sub_bucket = DocBucket(
                bucket_type=bucket.bucket_type,
                title=sub["title"],
                slug=sub_slug,
                section=nav_section,
                description=sub.get("description", ""),
                depends_on=bucket.depends_on,
                owned_files=sub.get("owned_files", []),
                owned_symbols=sub.get("owned_symbols", []),
                artifact_refs=[],
                required_sections=sub.get("required_sections", ["overview", "details"]),
                required_diagrams=sub.get("required_diagrams", []),
                coverage_targets=[],
                generation_hints={
                    **{k: v for k, v in hints.items() if k != "is_introduction_page"},
                    "prompt_style": sub.get(
                        "prompt_style", hints.get("prompt_style", "general")
                    ),
                },
                priority=bucket.priority + i + 1,
                parent_slug=bucket.slug,
            )
            new_buckets.append(sub_bucket)
            sub_slugs.append(sub_slug)

        for section_name, slugs in list(new_nav.items()):
            if bucket.slug in slugs:
                slugs.remove(bucket.slug)
                if not slugs:
                    del new_nav[section_name]
        new_nav.setdefault(nav_section, []).extend(sub_slugs)

        console.print(
            f"[cyan]  ↳ Decomposed '{bucket.title}' into {len(result['sub_topics'])} sub-topics"
            f"{' + overview' if keep_parent else ''}[/cyan]"
        )

    plan.buckets = new_buckets
    plan.nav_structure = new_nav
    return plan


def _consolidate_similar_buckets(plan: DocPlan, cfg: dict[str, Any]) -> DocPlan:
    """Merge near-duplicate buckets based on semantic token overlap (Jaccard similarity).

    Runs after decompose to catch cases where decomposition or the proposal step
    created overlapping pages (e.g. "Vinculum Overview" + "Vinculum Workflow").
    """
    threshold = cfg.get("consolidation_similarity_threshold", 0.55)
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
        while final_target in merge_map:
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
