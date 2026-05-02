from .common import *

def plan_docs(scan: RepoScan, cfg: dict[str, Any], llm: LLMClient) -> DocPlan:
    """Run the multi-step planner.

    Phase 2 scans (giant-file clustering, endpoint bundles, integration discovery)
    run first to enrich the scan, then:
    Step 1: CLASSIFY — categorize every file/artifact
    Step 2: PROPOSE — create bucket candidates (no cap, LLM decides freely)
    Step 3: ASSIGN — map files to buckets, produce final plan
    Step 4: attach scanned endpoints to grouped API-reference buckets
    """

    phase_start = time.perf_counter()

    # ── Phase 2 Scans (enrich before planning) ───────────────────────────
    console.print(
        Panel("[bold]Running Phase 2 scan upgrades[/bold]", border_style="green")
    )
    step_start = time.perf_counter()
    scan = run_phase2_scans(scan, cfg, llm)
    scan.planner_timings["phase2_scans"] = time.perf_counter() - step_start

    max_pages = cfg.get("max_pages", 0)
    giant_file_threshold = cfg.get("giant_file_lines", 2000)

    # Build shared context strings
    file_tree_str = _format_file_tree_compressed(scan.file_tree, scan.file_summaries)
    file_summaries_str = _format_summaries_compressed(scan.file_summaries)
    published_endpoints = scan.published_api_endpoints
    endpoints_str = _format_endpoints(published_endpoints)
    lang_str = ", ".join(
        f"{lang} ({count})"
        for lang, count in sorted(scan.languages.items(), key=lambda x: -x[1])
    )
    fw_str = ", ".join(scan.frameworks_detected) or "none detected"

    # ── Step 1: Classify ─────────────────────────────────────────────────
    console.print(
        Panel(
            "[bold]Planner Step 1/3: Classifying repository artifacts[/bold]",
            border_style="cyan",
        )
    )

    classify_prompt = CLASSIFY_PROMPT.format(
        languages=lang_str,
        frameworks=fw_str,
        total_files=scan.total_files,
        endpoint_count=len(published_endpoints),
        entry_points=", ".join(scan.entry_points[:10]) or "none",
        config_files=", ".join(scan.config_files[:15]) or "none",
        file_tree=file_tree_str[:15000],
        file_summaries=file_summaries_str[:20000],
        endpoints=endpoints_str[:5000],
        giant_file_threshold=giant_file_threshold,
    )

    step_start = time.perf_counter()
    classification = _llm_step(llm, CLASSIFY_SYSTEM, classify_prompt, "classify")
    scan.planner_timings["classify"] = time.perf_counter() - step_start
    if not classification:
        console.print(
            "[yellow]⚠ Classification failed — falling back to auto-plan[/yellow]"
        )
        return _fallback_plan(scan, cfg)

    classification = _normalize_repo_profile(classification, scan)
    _print_classification_summary(classification)

    # ── Step 2: Propose Buckets ──────────────────────────────────────────
    console.print(
        Panel(
            "[bold]Planner Step 2/3: Proposing documentation buckets[/bold]",
            border_style="cyan",
        )
    )

    # Build classification summary for the proposal step
    classification_summary = _build_classification_summary(classification)
    repo_profile = classification.get("repo_profile", {})
    repo_profile_str = json.dumps(repo_profile, indent=2) if repo_profile else "unknown"
    step_start = time.perf_counter()
    topic_candidates = _derive_topic_candidates(scan, classification)
    scan.planner_timings["derive_topic_candidates"] = time.perf_counter() - step_start
    topic_candidates_str = _format_topic_candidates(topic_candidates)
    research_context_str = _format_research_context(scan)

    # Enrich with Phase 2 results if available
    if scan.integration_identities:
        integration_signals = "## Discovered Integration Identities (Phase 2)\n"
        for ident in scan.integration_identities:
            substantial_tag = (
                "[SUBSTANTIAL — create standalone page]"
                if ident.is_substantial
                else "[EMBEDDED — keep in feature pages]"
            )
            party_tag = (
                "[FIRST-PARTY — treat as subsystem]"
                if getattr(ident, "party", "third_party") == "first_party"
                else "[THIRD-PARTY]"
            )
            integration_signals += f"- **{ident.display_name}** ({ident.name}) {substantial_tag} {party_tag}\n"
            integration_signals += f"  Files: {', '.join(ident.files[:5])}\n"
            integration_signals += f"  Evidence: {', '.join(ident.evidence[:3])}\n"
    else:
        integration_signals = json.dumps(
            classification.get("integration_signals", []), indent=2
        )

    cross_cutting = json.dumps(classification.get("cross_cutting", []), indent=2)

    # Enrich giant files with cluster info from Phase 2
    giant_files_list = classification.get("giant_files", [])
    giant_parts = []
    for f in giant_files_list:
        lc = scan.file_line_counts.get(f, "?")
        cluster_info = ""
        if f in scan.giant_file_clusters:
            analysis = scan.giant_file_clusters[f]
            cluster_names = [c.cluster_name for c in analysis.clusters]
            cluster_info = f" → clusters: {', '.join(cluster_names)}"
        giant_parts.append(f"- {f} ({lc} lines){cluster_info}")
    giant_files_str = "\n".join(giant_parts) or "(none)"

    # Build database info from artifact_scan
    database_info = "(none detected)"
    if (
        scan.artifact_scan
        and hasattr(scan.artifact_scan, "database_scan")
        and scan.artifact_scan.database_scan
    ):
        db_scan = scan.artifact_scan.database_scan
        db_parts = [
            f"ORM: {db_scan.orm_framework or 'unknown'}",
            f"Total models: {db_scan.total_models}",
        ]
        for mf in db_scan.model_files[:20]:
            if not mf.is_migration:
                models_str = ", ".join(mf.model_names[:10]) if mf.model_names else "?"
                db_parts.append(f"  - {mf.file_path}: [{models_str}]")
        if db_scan.migration_files:
            db_parts.append(f"  Migrations: {len(db_scan.migration_files)} files")
        if db_scan.schema_files:
            db_parts.append(f"  Schema files: {', '.join(db_scan.schema_files)}")
        database_info = "\n".join(db_parts)

    # Build max_pages instruction: 0 = no cap
    if max_pages and max_pages > 0:
        max_pages_instruction = f"- Maximum total buckets: {max_pages}"
    else:
        max_pages_instruction = (
            "- No hard limit. Generate a dedicated page for each meaningfully distinct "
            "subsystem, feature domain, or integration. If a subsystem has a complex "
            "internal architecture (e.g., multiple layers, a unique algorithm, or its own "
            "config surface), give it its own page rather than merging it. "
            "Typical range: 25-45 pages for a medium-large repo. "
            "Never merge unrelated topics just to reduce page count."
        )

    propose_prompt = PROPOSE_PROMPT.format(
        classification_summary=classification_summary,
        endpoint_count=len(published_endpoints),
        endpoints=endpoints_str[:15000],
        integration_signals=integration_signals,
        cross_cutting=cross_cutting,
        giant_files=giant_files_str,
        database_info=database_info,
        topic_candidates=topic_candidates_str,
        research_context=research_context_str,
        repo_profile=repo_profile_str,
        max_pages_instruction=max_pages_instruction,
    )

    step_start = time.perf_counter()
    proposal = _llm_step(llm, PROPOSE_SYSTEM, propose_prompt, "propose")
    scan.planner_timings["propose"] = time.perf_counter() - step_start
    if not proposal:
        console.print(
            "[yellow]⚠ Bucket proposal failed — falling back to auto-plan[/yellow]"
        )
        return _fallback_plan(scan, cfg)

    proposal = _refine_proposal(proposal, scan, classification)
    _print_proposal_summary(proposal)

    # ── Step 3: Assign Files ─────────────────────────────────────────────
    console.print(
        Panel(
            "[bold]Planner Step 3/3: Assigning files to buckets[/bold]",
            border_style="cyan",
        )
    )

    proposed_buckets_str = json.dumps(proposal.get("buckets", []), indent=2)
    all_files_str = "\n".join(f"- {f}" for f in sorted(scan.file_summaries.keys()))
    setup_artifacts_str = "\n".join(f"- {f}" for f in scan.config_files) or "(none)"

    assign_prompt = ASSIGN_PROMPT.format(
        proposed_buckets=proposed_buckets_str[:15000],
        all_files=all_files_str[:12000],
        endpoints=endpoints_str[:3000],
        giant_files=giant_files_str,
        setup_artifacts=setup_artifacts_str,
    )

    step_start = time.perf_counter()
    assignment = _llm_step(llm, ASSIGN_SYSTEM, assign_prompt, "assign")
    scan.planner_timings["assign"] = time.perf_counter() - step_start
    if not assignment:
        console.print(
            "[yellow]⚠ Assignment failed — using deterministic file assignment fallback[/yellow]"
        )
        assignment = _build_heuristic_assignment(proposal, scan)
        if not assignment.get("buckets"):
            console.print(
                "[yellow]⚠ Deterministic assignment had no buckets — falling back to auto-plan[/yellow]"
            )
            return _fallback_plan(scan, cfg)

    # ── Merge proposal + assignment into final plan ──────────────────────
    plan = _merge_plan(proposal, assignment, classification, scan)
    plan = _refine_bucket_ownership(plan, scan, classification)

    # ── Step 3.5: Decompose broad buckets into focused sub-topics ────────
    repo_profile = classification.get("repo_profile", {})
    console.print("[dim]Decomposing broad buckets...[/dim]")
    step_start = time.perf_counter()
    plan = _decompose_buckets(plan, scan, cfg, llm, repo_profile)
    scan.planner_timings["decompose"] = time.perf_counter() - step_start

    # ── Step 3.6: Consolidate near-duplicate buckets ────────────────────
    console.print("[dim]Consolidating similar buckets...[/dim]")
    step_start = time.perf_counter()
    plan = _consolidate_similar_buckets(plan, cfg)
    scan.planner_timings["consolidate"] = time.perf_counter() - step_start

    plan = _inject_research_context_buckets(plan, scan, classification)

    # ── Step 4: Attach endpoint reference details without one-page-per-route spam ─
    plan = _auto_generate_endpoint_refs(
        plan,
        scan,
        include_endpoint_pages=cfg.get("include_endpoint_pages", True),
    )
    plan = _ensure_database_runtime_and_interface_buckets(plan, scan, cfg)

    # ── Inject Start Here and Debug Runbook buckets ──────────────────────
    plan = _inject_start_here_and_debug_buckets(plan, scan, cfg)

    plan = _assign_publication_tiers(plan, scan, classification)
    plan = _shape_plan_nav(plan, classification)
    plan = _apply_page_contracts(plan, scan, classification)

    step_start = time.perf_counter()
    plan = _attach_orphans_semantically(plan, scan, classification)
    scan.planner_timings["attach_orphans"] = time.perf_counter() - step_start

    # Validate coverage
    console.print("[dim]Validating file coverage...[/dim]")
    step_start = time.perf_counter()
    plan = _validate_coverage(plan, scan)
    scan.planner_timings["validate_coverage"] = time.perf_counter() - step_start
    if plan.orphaned_files:
        console.print(
            f"[yellow]⚠ {len(plan.orphaned_files)} file(s) were unassigned → auto-assigned[/yellow]"
        )

    scan.planner_timings["total"] = time.perf_counter() - phase_start
    summary = ", ".join(
        f"{name}={duration:.2f}s"
        for name, duration in scan.planner_timings.items()
        if duration >= 0.01
    )
    if summary:
        console.print(f"[dim]Planner timings: {summary}[/dim]")

    _print_plan_summary(plan)
    return plan


def scan_repo(repo_root: Path, cfg: dict[str, Any]) -> RepoScan:
    """Scan the entire repo without making any LLM calls.

    Enhanced from v1: also records line counts and parsed files for
    giant-file detection and symbol-level bucket assignment.
    """
    exclude = cfg.get("exclude", [])
    include = cfg.get("include", [])
    extensions = supported_extensions()

    file_tree: dict[str, list[str]] = defaultdict(list)
    file_summaries: dict[str, str] = {}
    raw_api_endpoints: list[APIEndpoint] = []
    api_endpoints: list[dict] = []
    lang_counts: dict[str, int] = defaultdict(int)
    frameworks: set[str] = set()
    entry_points: list[str] = []
    config_files: list[str] = []
    openapi_paths: list[str] = []
    file_line_counts: dict[str, int] = {}
    parsed_files: dict[str, ParsedFile] = {}
    file_contents: dict[str, str] = {}
    doc_contexts: dict[str, str] = {}
    research_contexts: list[dict[str, Any]] = []
    source_kind_by_file: dict[str, str] = {}
    file_frameworks: dict[str, list[str]] = {}

    ext_to_lang = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".go": "go",
        ".php": "php",
        ".mjs": "javascript",
        ".cjs": "javascript",
        ".vue": "vue",
    }

    # First pass: collect all files
    all_files_to_scan: list[Path] = []
    for root, dirs, files in os.walk(repo_root):
        root_path = Path(root)
        dirs[:] = [d for d in dirs if not _matches_any(d, exclude)]
        for fname in sorted(files):
            fpath = root_path / fname
            rel = str(fpath.relative_to(repo_root))
            if not _matches_any(rel, exclude) and not _matches_any(fname, exclude):
                all_files_to_scan.append(fpath)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(
            "[dim]Scanning files...[/dim]", total=len(all_files_to_scan)
        )

        for fpath in all_files_to_scan:
            fname = fpath.name
            rel = str(fpath.relative_to(repo_root))
            rel_dir = (
                str(fpath.parent.relative_to(repo_root))
                if fpath.parent != repo_root
                else "."
            )

            progress.update(task, description=f"[dim]Scanning {rel}[/dim]")
            source_kind_by_file[rel] = classify_source_kind(rel)

            # Detect config files
            if fname in CONFIG_FILE_PATTERNS or any(
                p in rel for p in CONFIG_FILE_PATTERNS
            ):
                config_files.append(rel)

            # Detect OpenAPI/Swagger specs
            if fname.lower() in (
                "openapi.json",
                "openapi.yaml",
                "openapi.yml",
                "swagger.json",
                "swagger.yaml",
                "swagger.yml",
            ):
                openapi_paths.append(rel)

            # Only parse supported source files
            if _is_doc_context_candidate(rel, fname):
                try:
                    doc_content = fpath.read_text(encoding="utf-8", errors="replace")
                    if fname.lower().endswith(".ipynb"):
                        summary, context = _summarize_notebook_context(rel, doc_content)
                    else:
                        summary, context = _summarize_doc_context(rel, doc_content)
                    if summary:
                        doc_contexts[rel] = summary
                    if context:
                        research_contexts.append(context)
                except Exception:
                    pass

            if fpath.suffix.lower() not in extensions:
                file_tree[rel_dir].append(fname)
                progress.advance(task)
                continue

            if include and not _matches_any(rel, include):
                progress.advance(task)
                continue

            file_tree[rel_dir].append(fname)

            lang = ext_to_lang.get(fpath.suffix.lower(), "")
            if lang:
                lang_counts[lang] += 1

            # Detect entry points
            if fname.lower() in ENTRY_POINT_NAMES or fname.lower().rstrip(
                ".py.ts.js.go.php"
            ) in {"main", "app", "server", "index"}:
                entry_points.append(rel)

            # Parse file for summary
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                line_count = len(content.splitlines())
                file_line_counts[rel] = line_count
                file_contents[rel] = content
            except Exception:
                progress.advance(task)
                continue

            # Detect frameworks
            matched_frameworks: list[str] = []
            for fw, indicators in FRAMEWORK_INDICATORS.items():
                if any(ind in content for ind in indicators):
                    frameworks.add(fw)
                    matched_frameworks.append(fw)
            if lang == "go":
                frameworks.add("go")
                matched_frameworks.append("go")
            if fpath.suffix.lower() == ".vue":
                frameworks.add("vue")
                matched_frameworks.append("vue")
            if matched_frameworks:
                file_frameworks[rel] = sorted(set(matched_frameworks))

            # Parse symbols
            parsed = parse_file(fpath)
            if parsed:
                parsed_files[rel] = parsed
                summary_parts = []
                if parsed.symbols:
                    sym_names = [f"{s.kind}:{s.name}" for s in parsed.symbols[:15]]
                    summary_parts.append(f"symbols=[{', '.join(sym_names)}]")
                if parsed.imports:
                    summary_parts.append(f"imports={len(parsed.imports)}")
                summary_parts.append(f"lines={line_count}")
                file_summaries[rel] = " | ".join(summary_parts)

            # Detect API endpoints
            if lang:
                eps = detect_endpoints(fpath, content, lang)
                raw_api_endpoints.extend(eps)

            progress.advance(task)

    if raw_api_endpoints:
        resolved_endpoints = resolve_repo_endpoints(
            repo_root, raw_api_endpoints, file_contents
        )
        for ep in resolved_endpoints:
            if ep.path and ep.path.startswith("(see add_route for "):
                continue
            route_file = _normalize_repo_rel_path(repo_root, ep.route_file or ep.file)
            handler_file = _normalize_repo_rel_path(
                repo_root, ep.handler_file or ep.file or route_file
            )
            publication_ready, confidence, reason = endpoint_publication_decision(
                ep.path,
                route_file=route_file,
                handler_file=handler_file or route_file,
                framework=ep.framework,
                source_kind_by_file=source_kind_by_file,
            )
            api_endpoints.append(
                {
                    "method": ep.method,
                    "path": ep.path,
                    "handler": ep.handler,
                    "file": handler_file or route_file,
                    "route_file": route_file,
                    "handler_file": handler_file or route_file,
                    "line": ep.line,
                    "middleware": list(ep.middleware or []),
                    "request_body": ep.request_body,
                    "response_type": ep.response_type,
                    "raw_path": ep.raw_path,
                    "framework": ep.framework,
                    "provenance": ep.provenance,
                    "source_kind": source_kind_by_file.get(
                        handler_file or route_file,
                        classify_source_kind(handler_file or route_file),
                    ),
                    "publication_ready": publication_ready,
                    "publication_confidence": confidence,
                    "publication_reason": reason,
                }
            )

    return RepoScan(
        file_tree=dict(file_tree),
        file_summaries=file_summaries,
        api_endpoints=api_endpoints,
        languages=dict(lang_counts),
        has_openapi=len(openapi_paths) > 0,
        openapi_paths=openapi_paths,
        total_files=sum(len(files) for files in file_tree.values()),
        frameworks_detected=sorted(frameworks),
        entry_points=entry_points,
        config_files=config_files,
        file_line_counts=file_line_counts,
        parsed_files=parsed_files,
        file_contents=file_contents,
        doc_contexts=doc_contexts,
        research_contexts=research_contexts,
        source_kind_by_file=source_kind_by_file,
        file_frameworks=file_frameworks,
    )


def run_phase2_scans(scan: RepoScan, cfg: dict[str, Any], llm: LLMClient) -> RepoScan:
    """Enrich the basic scan with Phase 2 capabilities.

    Runs giant-file clustering, endpoint bundle building, integration discovery,
    and artifact discovery. Mutates and returns the scan object.
    """
    from ..scanner import (
        build_endpoint_bundles,
        cluster_giant_file,
        discover_artifacts,
        discover_config_impacts,
        discover_integrations,
        discover_runtime_surfaces,
    )

    giant_threshold = cfg.get("giant_file_lines", 2000)
    integration_mode = cfg.get("integration_detection", "auto")

    # 2.1 Giant-file clustering (parallelized)
    giant_files = {
        path: lc
        for path, lc in scan.file_line_counts.items()
        if lc >= giant_threshold and path in scan.parsed_files
    }
    if giant_files:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        max_workers = min(cfg.get("max_parallel_workers", 6), len(giant_files))
        console.print(
            f"  [bold]Clustering {len(giant_files)} giant file(s) "
            f"({max_workers} workers)...[/bold]"
        )
        for path, lc in sorted(giant_files.items(), key=lambda x: -x[1]):
            console.print(f"    [dim]{path} ({lc} lines)[/dim]")

        def _cluster_one(path: str) -> tuple[str, object]:
            parsed = scan.parsed_files[path]
            content = scan.file_contents.get(path, "")
            return path, cluster_giant_file(path, parsed, content, llm)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_cluster_one, path): path for path in giant_files
            }
            for future in as_completed(futures):
                path, analysis = future.result()
                scan.giant_file_clusters[path] = analysis
                cluster_names = [c.cluster_name for c in analysis.clusters]
                console.print(
                    f"    [green]✓[/green] {path}: {len(analysis.clusters)} clusters: "
                    f"{', '.join(cluster_names)}"
                )

    # 2.2 Endpoint evidence bundles
    published_api_endpoints = scan.published_api_endpoints
    if published_api_endpoints and cfg.get("include_endpoint_pages", True):
        console.print("  [bold]Building endpoint evidence bundles...[/bold]")
        scan.endpoint_bundles = build_endpoint_bundles(
            published_api_endpoints,
            scan.parsed_files,
            scan.file_summaries,
            Path("."),  # not used for resolution, just for typing
        )
        console.print(
            f"  [green]✓[/green] {len(scan.endpoint_bundles)} endpoint bundle(s)"
        )
        for b in scan.endpoint_bundles:
            console.print(
                f"    • {b.endpoint_family}: {len(b.evidence)} evidence files, {len(b.methods_paths)} routes"
            )

    # 2.3 Integration discovery
    if integration_mode == "auto" and cfg.get("include_integration_pages", True):
        console.print("  [bold]Discovering integrations...[/bold]")
        scan.integration_identities = discover_integrations(
            scan.parsed_files,
            scan.file_contents,
            scan.config_files,
            Path("."),
            llm=llm,
        )
        if scan.integration_identities:
            console.print(
                f"  [green]✓[/green] {len(scan.integration_identities)} integration(s) identified:"
            )
            for i in scan.integration_identities:
                marker = "📄" if i.is_substantial else "📎"
                console.print(f"    {marker} {i.display_name} ({len(i.files)} files)")

    # 2.4 Artifact discovery
    console.print("  [bold]Scanning for setup/deploy/test artifacts...[/bold]")
    scan.artifact_scan = discover_artifacts(
        Path("."),
        scan.file_tree,
        scan.parsed_files,
        scan.file_contents,
    )
    scan.runtime_scan = discover_runtime_surfaces(
        scan.parsed_files,
        scan.file_contents,
        scan.api_endpoints,
    )
    scan.config_impacts = discover_config_impacts(
        scan.file_contents, scan.api_endpoints
    )
    a = scan.artifact_scan
    if a and a.database_scan:
        scan.graphql_interfaces = list(a.database_scan.graphql_interfaces or [])
        scan.knex_artifacts = list(a.database_scan.knex_artifacts or [])
    db_info = ""
    if a.database_scan and a.database_scan.model_files:
        db = a.database_scan
        db_info = f", {len(db.model_files)} model files ({db.total_models} models, ORM: {db.orm_framework or '?'})"
    runtime_info = ""
    if scan.runtime_scan:
        runtime_info = (
            f", {len(scan.runtime_scan.tasks)} runtime task(s), "
            f"{len(scan.runtime_scan.schedulers)} scheduler(s), "
            f"{len(scan.runtime_scan.realtime_consumers)} realtime consumer(s)"
        )
    config_info = ""
    if scan.config_impacts:
        config_info = f", {len(scan.config_impacts)} config/env impact(s)"
    console.print(
        f"  [green]✓[/green] {len(a.setup_artifacts)} setup, {len(a.deploy_artifacts)} deploy, "
        f"{len(a.ci_artifacts)} CI, {len(a.test_artifacts)} test, {len(a.ops_artifacts)} ops{db_info}{runtime_info}{config_info}"
    )

    # 2.5 Call graph extraction
    console.print("  [bold]Building call graph...[/bold]")
    scan.call_graph = build_call_graph(
        scan.parsed_files, scan.file_contents, scan.api_endpoints
    )
    stats = scan.call_graph.stats()
    console.print(
        f"  [green]✓[/green] Call graph: {stats['total_edges']} edges "
        f"({stats['local']} local, {stats['celery_dispatch']} Celery, "
        f"{stats['signal_dispatch']} signals, {stats['event_dispatch']} events)"
    )

    # 2.6 Debug signal discovery
    console.print("  [bold]Discovering debug signals...[/bold]")
    scan.debug_signals = discover_debug_signals(
        scan.parsed_files,
        scan.file_contents,
        scan.api_endpoints,
    )
    if scan.debug_signals:
        console.print(f"  [green]✓[/green] {len(scan.debug_signals)} debug signal(s):")
        for sig in scan.debug_signals:
            console.print(f"    • {sig.signal_type}: {sig.name}")
    else:
        console.print("  [dim]No debug signals detected[/dim]")

    return scan


def _matches_any(path: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if (
            fnmatch.fnmatch(path, pattern)
            or fnmatch.fnmatch(os.path.basename(path), pattern)
            or pattern in path.split(os.sep)
        ):
            return True
    return False


from .heuristics import _apply_page_contracts, _assign_publication_tiers, _attach_orphans_semantically, _auto_generate_endpoint_refs, _build_heuristic_assignment, _consolidate_similar_buckets, _decompose_buckets, _derive_topic_candidates, _fallback_plan, _inject_research_context_buckets, _inject_start_here_and_debug_buckets, _llm_step, _merge_plan, _normalize_repo_profile, _refine_bucket_ownership, _refine_proposal, _shape_plan_nav, _validate_coverage
from .utils import _build_classification_summary, _format_endpoints, _format_file_tree_compressed, _format_research_context, _format_summaries_compressed, _format_topic_candidates, _is_doc_context_candidate, _normalize_repo_rel_path, _print_classification_summary, _print_plan_summary, _print_proposal_summary, _summarize_doc_context, _summarize_notebook_context
from .specializations import _ensure_database_runtime_and_interface_buckets
