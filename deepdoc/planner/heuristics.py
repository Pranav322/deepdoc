from .common import *

def _normalize_tokens(*values: str) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        for token in TOKEN_RE.findall(value or ""):
            normalized = token.lower().strip("_-+")
            if len(normalized) < 3 or normalized in STOPWORD_TOKENS:
                continue
            tokens.add(normalized)
    return tokens


def _derive_topic_candidates(
    scan: RepoScan, classification: dict[str, Any]
) -> list[dict[str, Any]]:
    """Derive ranked concept candidates from code, artifacts, and markdown context."""
    repo_profile = classification.get("repo_profile", {})
    primary = repo_profile.get("primary_type", "other")
    templates = PROFILE_TOPIC_TEMPLATES.get(
        primary, PROFILE_TOPIC_TEMPLATES["backend_service"]
    )

    candidate_map: dict[str, dict[str, Any]] = {}
    file_token_cache = scan.topic_file_token_cache
    context_token_cache = scan.topic_context_token_cache

    def _ensure_candidate(title: str, category: str) -> dict[str, Any]:
        key = f"{category}:{title}"
        if key not in candidate_map:
            candidate_map[key] = {
                "title": title,
                "category": category,
                "score": 0,
                "evidence_files": set(),
                "evidence_docs": set(),
                "signals": set(),
            }
        return candidate_map[key]

    if not file_token_cache:
        for file_path, parsed in scan.parsed_files.items():
            file_token_cache[file_path] = _normalize_tokens(
                file_path,
                " ".join(symbol.name for symbol in parsed.symbols[:20]),
                " ".join(parsed.imports[:12]),
            )

    if not context_token_cache:
        for context in scan.research_contexts:
            context_key = (
                context.get("file_path") or context.get("title") or str(id(context))
            )
            context_token_cache[context_key] = _normalize_tokens(
                context.get("title", ""),
                context.get("summary", ""),
                " ".join(context.get("headings", [])),
            )

    for title, keywords, category in templates:
        _ensure_candidate(title, category)
        for file_path, file_tokens in file_token_cache.items():
            matched = sorted(
                {kw for kw in keywords if any(kw in token for token in file_tokens)}
            )
            if not matched:
                continue
            candidate = _ensure_candidate(title, category)
            candidate["score"] += len(matched) * 3
            candidate["evidence_files"].add(file_path)
            candidate["signals"].update(matched)

        for context in scan.research_contexts:
            context_key = (
                context.get("file_path") or context.get("title") or str(id(context))
            )
            context_tokens = context_token_cache.get(context_key, set())
            matched = sorted(
                {kw for kw in keywords if any(kw in token for token in context_tokens)}
            )
            if not matched:
                continue
            candidate = _ensure_candidate(title, category)
            candidate["score"] += len(matched) * 4
            candidate["evidence_docs"].add(context.get("file_path", ""))
            candidate["signals"].update(matched)

    # Force-add explicit research context categories when docs exist.
    for context in scan.research_contexts:
        kind = context.get("kind", "")
        if kind == "experiment_log":
            title = "Experiment Log and Findings"
        elif kind == "design_history":
            title = "Design History and Architecture Notes"
        elif kind == "development_notes":
            title = "Development Notes"
        elif kind == "glossary":
            title = "Glossary"
        else:
            continue
        candidate = _ensure_candidate(title, "research_context")
        candidate["score"] += 8
        candidate["evidence_docs"].add(context.get("file_path", ""))
        candidate["signals"].add(kind)

    ranked: list[dict[str, Any]] = []
    for candidate in candidate_map.values():
        if candidate["score"] <= 0:
            continue
        ranked.append(
            {
                "title": candidate["title"],
                "category": candidate["category"],
                "score": candidate["score"],
                "evidence_files": sorted(f for f in candidate["evidence_files"] if f)[
                    :8
                ],
                "evidence_docs": sorted(f for f in candidate["evidence_docs"] if f)[:6],
                "signals": sorted(candidate["signals"])[:10],
            }
        )
    ranked.sort(key=lambda item: (-item["score"], item["title"]))
    scan.topic_candidates = ranked
    return ranked[:20]


def _normalize_repo_profile(
    classification: dict[str, Any], scan: RepoScan
) -> dict[str, Any]:
    """Normalize repo profile using scan-time heuristics and stack signals."""
    profile = dict(classification.get("repo_profile", {}) or {})
    primary = profile.get("primary_type", "other")
    frameworks = set(scan.frameworks_detected)
    published_endpoint_count = len(scan.published_api_endpoints)
    secondary_traits = set(profile.get("secondary_traits", []))

    framework_traits = {
        "falcon": "uses_falcon",
        "django": "uses_django",
        "express": "uses_express",
        "fastify": "uses_fastify",
        "laravel": "uses_laravel",
        "vue": "uses_vue",
    }
    for framework, trait in framework_traits.items():
        if framework in frameworks:
            secondary_traits.add(trait)

    if "falcon" in frameworks:
        normalized_primary = "falcon_backend"
    elif primary in {"backend_api", "backend_service"}:
        normalized_primary = "backend_service"
    elif primary in {"monorepo_product", "platform_monorepo"}:
        normalized_primary = "platform_monorepo"
    elif primary == "research_training":
        normalized_primary = "research_training"
    elif "vue" in frameworks and published_endpoint_count == 0:
        normalized_primary = "frontend_admin"
    elif published_endpoint_count > 0:
        normalized_primary = "backend_service"
    elif any(path.endswith(("cli.py", "__main__.py")) for path in scan.file_summaries):
        normalized_primary = "cli_tooling"
    elif frameworks:
        normalized_primary = "framework_library"
    else:
        normalized_primary = "other"

    if (
        {"vue"} & frameworks
        and published_endpoint_count > 0
        and normalized_primary not in {"research_training"}
    ):
        normalized_primary = "hybrid"

    if "falcon" in frameworks:
        profile["evidence"] = (
            profile.get("evidence") or "Falcon routes and middleware detected"
        )

    profile["primary_type"] = normalized_primary
    profile["secondary_traits"] = sorted(secondary_traits)
    if not profile.get("confidence"):
        profile["confidence"] = "medium"
    classification["repo_profile"] = profile
    return classification


def _llm_step(llm: LLMClient, system: str, prompt: str, step_name: str) -> dict | None:
    """Execute a single LLM planning step with error handling."""
    from rich.live import Live
    from rich.text import Text

    response = None
    with Live(
        Text(
            f"⠋ Running planner step: {step_name}... (may take 15-30s)",
            style="bold cyan",
        ),
        console=console,
        refresh_per_second=10,
        transient=True,
    ):
        try:
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
                cleaned = "\n".join(lines)
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
    for bucket in plan.buckets:
        hints = bucket.generation_hints or {}
        if not include_overview and hints.get("is_introduction_page"):
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


def _inject_start_here_and_debug_buckets(
    plan: DocPlan,
    scan: RepoScan,
    cfg: dict[str, Any],
) -> DocPlan:
    """Inject Start Here (orientation) and Debug Runbook buckets into the plan.

    Start Here buckets are always generated (orientation, setup, domain glossary).
    Debug Runbook is only generated if debug_signals were detected.
    """
    # ── Start Here section (always generated) ──────────────────────────────
    # Generate 3 pages: index (orientation), setup (local dev), and domain glossary.
    # These are always present regardless of codebase type — they are the entry point
    # for every new team member.

    plan.nav_structure.setdefault("Start Here", [])

    all_files = list(scan.file_summaries.keys())
    db_model_files: list[str] = []

    # Collect database model files from artifact scan if available
    artifact_scan = getattr(scan, "artifact_scan", None)
    if artifact_scan and hasattr(artifact_scan, "database_scan"):
        db_scan = artifact_scan.database_scan
        if db_scan:
            for mf in getattr(db_scan, "model_files", []):
                if hasattr(mf, "file_path"):
                    db_model_files.append(mf.file_path)
            db_model_files.extend(getattr(db_scan, "schema_files", []))

    if not db_model_files:
        db_model_files = [
            f
            for f in all_files
            if any(kw in f.lower() for kw in ("model", "schema", "entity", "database"))
        ][:30]

    # Collect artifact files (config, setup files)
    artifact_files = []
    if artifact_scan:
        if hasattr(artifact_scan, "config_artifacts"):
            artifact_files.extend(
                [getattr(a, "file_path", a) for a in artifact_scan.config_artifacts][
                    :15
                ]
            )
        if hasattr(artifact_scan, "setup_artifacts"):
            artifact_files.extend(
                [getattr(a, "file_path", a) for a in artifact_scan.setup_artifacts][:10]
            )
    artifact_files = list(dict.fromkeys(artifact_files))[:20]

    # Start Here Index (orientation)
    plan.buckets.insert(
        0,
        DocBucket(
            bucket_type="start_here_index",
            title="Start Here",
            slug="start-here",
            section="Start Here",
            description="New-joiner orientation: what this service does, who uses it, how to navigate the docs, and the 5 files every developer must know.",
            owned_files=all_files[:30],  # broad evidence — representative sample
            artifact_refs=artifact_files[:10] if artifact_files else [],
            required_sections=[
                "what_this_does",
                "who_uses_it",
                "tech_at_a_glance",
                "getting_running",
                "reading_order",
                "architecture_diagram",
                "five_key_files",
                "day_one_questions",
            ],
            required_diagrams=["architecture_overview"],
            generation_hints={
                "prompt_style": "start_here_index",
                "icon": "rocket",
                "always_generate": True,
                "preserve_section": True,
            },
            priority=-20,  # highest priority — generate first
            parent_slug=None,
        ),
    )
    plan.nav_structure["Start Here"].insert(0, "start-here")

    # Local Development Setup
    setup_files = [
        f
        for f in all_files
        if any(
            kw in f.lower()
            for kw in (
                "config",
                "setting",
                "env",
                "docker",
                "requirement",
                "package.json",
                ".env",
            )
        )
    ][:20]

    plan.buckets.insert(
        1,
        DocBucket(
            bucket_type="start_here_setup",
            title="Local Development Setup",
            slug="local-development-setup",
            section="Start Here",
            description="Complete step-by-step guide to running this service locally, including all environment variables, dependencies, and verification steps.",
            owned_files=setup_files,
            artifact_refs=artifact_files[:15] if artifact_files else [],
            required_sections=[
                "prerequisites",
                "clone_and_install",
                "environment_variables",
                "database_setup",
                "external_dependencies",
                "starting_service",
                "verification",
                "troubleshooting",
            ],
            generation_hints={
                "prompt_style": "start_here_setup",
                "icon": "terminal",
                "always_generate": True,
                "preserve_section": True,
            },
            priority=-19,
            parent_slug=None,
        ),
    )
    plan.nav_structure["Start Here"].insert(1, "local-development-setup")

    # Domain Glossary
    plan.buckets.insert(
        2,
        DocBucket(
            bucket_type="domain_glossary",
            title="Domain Glossary",
            slug="domain-glossary",
            section="Start Here",
            description="Plain-English definitions of every domain-specific term, model name, status code, and internal system name used in this codebase.",
            owned_files=db_model_files[:30] if db_model_files else all_files[:20],
            artifact_refs=[],
            required_sections=[
                "how_to_use",
                "domain_terms",
                "status_codes_and_state_machines",
                "integration_name_map",
                "abbreviations",
            ],
            required_diagrams=["state_machine_for_primary_entity"],
            generation_hints={
                "prompt_style": "domain_glossary",
                "icon": "book-open",
                "always_generate": True,
                "preserve_section": True,
            },
            priority=-18,
            parent_slug=None,
        ),
    )
    plan.nav_structure["Start Here"].insert(2, "domain-glossary")

    # ── Debug & Observability runbook (conditional) ───────────────────────
    # Only generate if debug_signals were detected in the scan phase.
    debug_signals = getattr(scan, "debug_signals", []) if scan else []
    if len(debug_signals) >= 2:
        debug_owned_files = []
        for sig in debug_signals:
            if hasattr(sig, "file_path") and sig.file_path:
                debug_owned_files.append(sig.file_path)
            if hasattr(sig, "files"):
                debug_owned_files.extend(sig.files[:3])
        debug_owned_files = list(dict.fromkeys(debug_owned_files))[:20]

        # Also include middleware, config, and monitoring files
        debug_owned_files += [
            f
            for f in all_files
            if any(
                kw in f.lower()
                for kw in (
                    "monitor",
                    "metric",
                    "health",
                    "log",
                    "sentry",
                    "newrelic",
                    "prometheus",
                )
            )
        ][:10]
        debug_owned_files = list(dict.fromkeys(debug_owned_files))[:25]

        plan.buckets.append(
            DocBucket(
                bucket_type="debug_runbook",
                title="Debugging & Observability",
                slug="debugging-observability",
                section="Operations",
                description="Production debugging runbook: health checks, log patterns, queue inspection, Redis key reference, common failure modes, and exception handling map.",
                owned_files=debug_owned_files,
                artifact_refs=artifact_files[:8] if artifact_files else [],
                required_sections=[
                    "quick_checklist",
                    "health_endpoints",
                    "log_locations",
                    "background_task_debugging",
                    "cache_redis_key_reference",
                    "common_failure_modes",
                    "exception_handling_map",
                    "monitoring_metrics",
                ],
                required_diagrams=["debug_flow_sequence"],
                coverage_targets=[
                    sig.name if hasattr(sig, "name") else str(sig)
                    for sig in debug_signals
                ],
                generation_hints={
                    "prompt_style": "debug_runbook",
                    "icon": "bug",
                    "always_generate": True,
                    "preserve_section": True,
                    "debug_signals": [
                        {
                            "signal_type": getattr(sig, "signal_type", "unknown"),
                            "name": getattr(sig, "name", "unknown"),
                            "description": getattr(sig, "description", ""),
                            "patterns": getattr(sig, "patterns", [])[:6],
                            "files": getattr(sig, "files", [])[:5],
                        }
                        for sig in debug_signals
                    ],
                },
                priority=8,
            )
        )
        plan.nav_structure.setdefault("Operations", []).append(
            "debugging-observability"
        )

    return plan


def _inject_research_context_buckets(
    plan: DocPlan,
    scan: RepoScan,
    classification: dict[str, Any],
) -> DocPlan:
    """Add research-context pages when markdown/docs contain strong signals."""
    if not scan.research_contexts:
        return plan
    existing_titles = {bucket.title.lower() for bucket in plan.buckets}
    for context in scan.research_contexts:
        kind = context.get("kind", "")
        if kind == "experiment_log":
            title = "Experiment Log and Findings"
            slug = "experiment-log-findings"
        elif kind == "design_history":
            title = "Design History and Architecture Notes"
            slug = "design-history-architecture-notes"
        elif kind == "development_notes":
            title = "Development Notes"
            slug = "development-notes"
        elif kind == "glossary":
            title = "Glossary"
            slug = "glossary"
        else:
            continue
        if title.lower() in existing_titles:
            continue
        bucket = DocBucket(
            bucket_type="research-context",
            title=title,
            slug=slug,
            section="Research Context",
            description=context.get("summary", title),
            artifact_refs=[context.get("file_path", "")],
            required_sections=["overview", "key_findings", "references"],
            required_diagrams=[],
            generation_hints={"prompt_style": "research_context", "icon": "book-open"},
            priority=40,
        )
        plan.buckets.append(bucket)
        plan.nav_structure.setdefault("Research Context", []).append(slug)
        existing_titles.add(title.lower())
    return plan


def _assign_publication_tiers(
    plan: DocPlan,
    scan: RepoScan,
    classification: dict[str, Any],
) -> DocPlan:
    """Label buckets as core or supporting based on their evidence makeup."""
    for bucket in plan.buckets:
        hints = bucket.generation_hints or {}
        tracked = tracked_bucket_files(bucket)
        kind_counts = source_kind_counts(tracked, scan.source_kind_by_file)
        bucket.source_kind_summary = kind_counts
        bucket.publication_tier = infer_publication_tier(
            tracked,
            scan.source_kind_by_file,
            is_introduction_page=hints.get("is_introduction_page", False),
            is_endpoint_family=hints.get("is_endpoint_family", False),
            is_endpoint_ref=hints.get("is_endpoint_ref", False),
        )
        title_lower = bucket.title.lower()
        if bucket.bucket_type == "research-context" or any(
            token in title_lower
            for token in (
                "testing",
                "test ",
                "example",
                "fixture",
                "generated",
                "release",
                "ci/cd",
                "ci",
                "build process",
            )
        ):
            bucket.publication_tier = "supporting"
    return plan


def _canonical_section_for_bucket(bucket: DocBucket, primary_type: str) -> str:
    title_tokens = _bucket_semantic_tokens(bucket)
    if bucket.publication_tier == "supporting":
        supporting_section = supporting_section_for_kinds(bucket.source_kind_summary)
        if supporting_section:
            return supporting_section
        if bucket.bucket_type == "research-context" or any(
            token in title_tokens for token in {"history", "note", "notes", "glossary"}
        ):
            return "Design & Notes"
        if any(
            token in title_tokens for token in {"test", "cypress", "playwright", "spec"}
        ):
            return "Testing"
        if any(
            token in title_tokens
            for token in {"release", "deploy", "build", "workflow", "ci"}
        ):
            return "CI/CD and Release"
        return "Supporting Material"
    if primary_type == "research_training":
        if bucket.generation_hints.get("is_introduction_page"):
            return "Overview"
        if (
            bucket.bucket_type == "research-context"
            or "glossary" in title_tokens
            or "experiment" in title_tokens
            or "history" in title_tokens
        ):
            return "Research Context"
        if any(
            token in title_tokens
            for token in {"model", "attention", "transformer", "fp8", "quant"}
        ):
            return "Model Architecture"
        if any(
            token in title_tokens
            for token in {"optim", "optimizer", "schedule", "scheduler", "muon", "lr"}
        ):
            return "Optimization"
        if any(token in title_tokens for token in {"train", "checkpoint", "loss"}):
            return "Training"
        if any(
            token in title_tokens
            for token in {"data", "dataset", "tokenizer", "parquet", "pipeline"}
        ):
            return "Data Pipeline"
        if any(
            token in title_tokens
            for token in {"eval", "metric", "score", "benchmark", "report"}
        ):
            return "Evaluation"
        if any(
            token in title_tokens
            for token in {"infer", "runtime", "sampling", "cache", "stats"}
        ):
            return "Inference & Runtime"
        if (
            bucket.generation_hints.get("is_endpoint_family")
            or bucket.generation_hints.get("is_endpoint_ref")
            or any(
                token in title_tokens for token in {"api", "cli", "interface", "chat"}
            )
        ):
            return "Interfaces"
        return "Operations"
    if primary_type in {"monorepo_product", "platform_monorepo"}:
        if any(token in title_tokens for token in {"package", "workspace", "shared"}):
            return "Monorepo Structure"
        if any(
            token in title_tokens for token in {"release", "ci", "workflow", "build"}
        ):
            return "Release"
        if any(
            token in title_tokens for token in {"ui", "frontend", "canvas", "component"}
        ):
            return "Frontend"
        if any(token in title_tokens for token in {"runtime", "worker", "execution"}):
            return "Runtime"
        if any(token in title_tokens for token in {"api", "service", "server"}):
            return "API & Services"
        return "Configuration"
    if primary_type == "framework_library":
        if bucket.generation_hints.get("is_introduction_page"):
            return "Overview"
        if any(
            token in title_tokens
            for token in {"diagram", "plugin", "syntax", "render", "layout"}
        ):
            return "Framework Surfaces"
        if any(
            token in title_tokens for token in {"api", "config", "detect", "engine"}
        ):
            return "Core API"
        if any(token in title_tokens for token in {"test", "build", "ci", "quality"}):
            return "Development"
        return "Ecosystem"
    if primary_type == "cli_tooling":
        if bucket.generation_hints.get("is_introduction_page"):
            return "Overview"
        if any(
            token in title_tokens for token in {"cli", "command", "dispatch", "flag"}
        ):
            return "CLI"
        if any(
            token in title_tokens
            for token in {"scan", "plan", "generate", "update", "pipeline"}
        ):
            return "Pipeline"
        if any(
            token in title_tokens
            for token in {"provider", "client", "llm", "integration"}
        ):
            return "Integrations"
        return "Operations"
    if primary_type == "falcon_backend":
        if bucket.generation_hints.get("is_introduction_page"):
            return "Overview"
        if bucket.generation_hints.get(
            "is_endpoint_family"
        ) or bucket.generation_hints.get("is_endpoint_ref"):
            return "API Reference"
        if any(
            token in title_tokens
            for token in {
                "falcon",
                "middleware",
                "translator",
                "auth",
                "route",
                "resource",
            }
        ):
            return "Runtime & Frameworks"
        if any(
            token in title_tokens
            for token in {"model", "schema", "migration", "database"}
        ):
            return "Data Layer"
        if any(
            token in title_tokens
            for token in {"queue", "task", "sync", "worker", "celery"}
        ):
            return "Background Jobs"
        if any(
            token in title_tokens for token in {"provider", "gateway", "integration"}
        ):
            return "Integrations"
        return "Subsystems"
    if primary_type == "backend_service":
        if bucket.generation_hints.get("is_introduction_page"):
            return "Overview"
        if bucket.generation_hints.get(
            "is_endpoint_family"
        ) or bucket.generation_hints.get("is_endpoint_ref"):
            return "API Reference"
        if any(
            token in title_tokens
            for token in {"middleware", "auth", "route", "controller", "handler"}
        ):
            return "Runtime & Frameworks"
        if any(
            token in title_tokens
            for token in {"model", "schema", "migration", "database"}
        ):
            return "Data Layer"
        if any(
            token in title_tokens for token in {"provider", "gateway", "integration"}
        ):
            return "Integrations"
        if any(token in title_tokens for token in {"queue", "task", "worker", "sync"}):
            return "Background Jobs"
        return "Subsystems"
    if bucket.generation_hints.get("is_introduction_page"):
        return "Overview"
    if bucket.generation_hints.get("is_endpoint_family") or bucket.generation_hints.get(
        "is_endpoint_ref"
    ):
        return "API"
    if any(token in title_tokens for token in {"integration", "provider", "gateway"}):
        return "Integrations"
    if any(
        token in title_tokens for token in {"model", "schema", "migration", "database"}
    ):
        return "Data Layer"
    if any(
        token in title_tokens
        for token in {"logging", "deploy", "metric", "health", "config"}
    ):
        return "Operations"
    return "Architecture"


def _shape_plan_nav(plan: DocPlan, classification: dict[str, Any]) -> DocPlan:
    """Normalize sections and merge low-value standalone helper pages."""
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
        if not (hints.get("preserve_section") or " > " in (bucket.section or "")):
            bucket.section = _canonical_section_for_bucket(bucket, primary)
        if bucket.section in {
            "Training",
            "Data Pipeline",
            "Evaluation",
            "Optimization",
            "Model Architecture",
        } and bucket.title.lower().endswith(" overview"):
            bucket.section = bucket.section
        new_buckets.append(bucket)

    if merged_utilities:
        merged = DocBucket(
            bucket_type="utility-group",
            title="Common Utilities & Configuration",
            slug="common-utilities-configuration",
            section="Operations",
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
    nav: dict[str, list[str]] = defaultdict(list)
    for bucket in plan.buckets:
        nav[bucket.section].append(bucket.slug)
    plan.nav_structure = dict(nav)
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


def _auto_generate_endpoint_refs(
    plan: DocPlan,
    scan: RepoScan,
    include_endpoint_pages: bool = True,
) -> DocPlan:
    """Auto-generate individual endpoint_ref buckets from scan API endpoints.

    This creates one page per API endpoint (e.g. GET /api/v1/orders) and nests
    each under its parent endpoint-family bucket. The LLM planner only creates
    family buckets (endpoint type) — this fills in the per-endpoint detail pages.
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

    endpoints = scan.published_api_endpoints
    if not include_endpoint_pages or not endpoints:
        return plan

    repo_profile = plan.classification.get("repo_profile", {})
    primary_type = repo_profile.get("primary_type", "other")
    restrict_endpoints = primary_type not in ("backend_service", "falcon_backend")

    # Map endpoints to their family bucket by matching resource group
    family_buckets = [
        b for b in plan.buckets if b.generation_hints.get("is_endpoint_family")
    ]

    # Build resource → family bucket slug mapping
    def _resource_from_path(path: str) -> str:
        clean = _re.sub(r"^/(?:api/)?(?:v\d+/)?", "", path)
        parts_list = [
            p
            for p in clean.split("/")
            if p and not p.startswith(":") and not p.startswith("{")
        ]
        return parts_list[0] if parts_list else "general"

    resource_to_family: dict[str, str] = {}
    for fb in family_buckets:
        # Derive resource from slug (e.g. "orders-api" → "orders")
        resource = fb.slug.replace("-api", "").replace("-", "_")
        resource_to_family[resource] = fb.slug
        # Also map without underscores
        resource_to_family[resource.replace("_", "-")] = fb.slug

    ref_buckets: list[DocBucket] = []
    existing_slugs = {b.slug for b in plan.buckets}

    for ep in endpoints:
        method = ep.get("method", "GET").upper()
        path = ep.get("path", "/unknown")
        handler = ep.get("handler", "")
        ep_files = endpoint_owned_files(ep)
        path_lower = path.lower()

        if path_lower in NOISE_PATHS:
            continue
        if any(path_lower.endswith(s) for s in NOISE_SUFFIXES):
            continue
        if path == "/" and method == "GET" and handler in ("root", "index", "home"):
            continue
        if restrict_endpoints and not family_buckets:
            continue

        # Build slug
        path_slug = _re.sub(r"[/:{}<>]+", "-", path).strip("-").lower()
        ref_slug = f"{method.lower()}-{path_slug}"

        # Avoid duplicates
        if ref_slug in existing_slugs:
            continue
        existing_slugs.add(ref_slug)

        # Find parent family bucket
        resource = _resource_from_path(path)
        parent_slug = resource_to_family.get(
            resource, resource_to_family.get(resource.replace("_", "-"), "")
        )

        ref_buckets.append(
            DocBucket(
                bucket_type="endpoint-ref",
                title=f"{method} {path}",
                slug=ref_slug,
                section="API Endpoints",
                description=f"API reference for {method} {path} — handler: {handler}",
                owned_files=ep_files,
                owned_symbols=[handler] if handler else [],
                required_sections=[
                    "endpoint_summary",
                    "handler",
                    "parameters",
                    "request_body",
                    "response_format",
                    "error_responses",
                    "auth",
                    "sequence_diagram",
                ],
                generation_hints={
                    "is_endpoint_ref": True,
                    "include_endpoint_detail": True,
                    "include_openapi": True,
                    "prompt_style": "endpoint_ref",
                    "icon": "globe-alt",
                },
                priority=25,
                depends_on=[parent_slug] if parent_slug else [],
            )
        )

    if ref_buckets:
        plan.buckets.extend(ref_buckets)

        # Group endpoint_refs by family in nav — nested under parent family title
        family_slug_to_title: dict[str, str] = {
            b.slug: b.title
            for b in plan.buckets
            if b.generation_hints.get("is_endpoint_family")
        }
        family_refs: dict[str, list[str]] = defaultdict(list)
        ungrouped: list[str] = []
        for b in ref_buckets:
            parent = b.depends_on[0] if b.depends_on else ""
            if parent and parent in family_slug_to_title:
                family_refs[parent].append(b.slug)
            else:
                ungrouped.append(b.slug)

        # Build nested nav sections: "API Endpoints > Orders API" etc.
        for family_slug, ref_slugs in sorted(family_refs.items()):
            family_title = family_slug_to_title.get(family_slug, family_slug)
            section_key = f"API Endpoints > {family_title}"
            # Include the family overview page first, then individual endpoints
            plan.nav_structure[section_key] = [family_slug] + ref_slugs
            # Remove family slug from its original section so it's not duplicated
            for section_name, slugs in list(plan.nav_structure.items()):
                if section_name != section_key and family_slug in slugs:
                    slugs.remove(family_slug)

        if ungrouped:
            plan.nav_structure["API Endpoints > Other"] = ungrouped

        console.print(
            f"[green]✓ Auto-generated {len(ref_buckets)} individual endpoint reference pages[/green]"
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

                    slug = f"{group_name.lower().replace(' ', '-').replace('_', '-')}-module"
                    plan.buckets.append(
                        DocBucket(
                            bucket_type="module",
                            title=title,
                            slug=slug,
                            section="Modules",
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
                    if "Modules" not in plan.nav_structure:
                        plan.nav_structure["Modules"] = []
                    plan.nav_structure["Modules"].append(slug)

        plan.orphaned_files = sorted(orphaned)

    return plan


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

            # Individual endpoint reference pages
            for ep in eps:
                method = ep.get("method", "GET").upper()
                path = ep.get("path", "/unknown")
                handler = ep.get("handler", "")
                ep_files = endpoint_owned_files(ep)
                path_slug = re.sub(r"[/:{}<>]+", "-", path).strip("-").lower()
                ref_slug = f"{method.lower()}-{path_slug}"
                ref_title = f"{method} {path}"
                buckets.append(
                    DocBucket(
                        bucket_type="endpoint-ref",
                        title=ref_title,
                        slug=ref_slug,
                        section="API Endpoints",
                        description=f"API reference for {method} {path} — handler: {handler}",
                        owned_files=ep_files,
                        owned_symbols=[handler] if handler else [],
                        required_sections=[
                            "endpoint_summary",
                            "handler",
                            "parameters",
                            "request_body",
                            "response_format",
                            "error_responses",
                            "auth",
                            "sequence_diagram",
                        ],
                        generation_hints={
                            "is_endpoint_ref": True,
                            "include_endpoint_detail": True,
                            "include_openapi": True,
                            "prompt_style": "endpoint_ref",
                            "icon": "globe-alt",
                        },
                        priority=25,
                        depends_on=[slug],
                    )
                )
                nav["API Endpoints"].append(ref_slug)

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
