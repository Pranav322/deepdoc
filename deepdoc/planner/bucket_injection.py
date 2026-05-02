from .common import *
from .bucket_refinement import _bucket_semantic_tokens


LOW_TRUST_KINDS = {"test", "fixture", "example", "generated"}


def _is_high_trust_path(scan: RepoScan, rel_path: str) -> bool:
    kind = scan.source_kind_by_file.get(rel_path, classify_source_kind(rel_path))
    return kind not in LOW_TRUST_KINDS


def _unique_paths(paths: list[str]) -> list[str]:
    return list(dict.fromkeys(path for path in paths if path))


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
    high_trust_files = [path for path in all_files if _is_high_trust_path(scan, path)]
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
    artifact_files: list[str] = []
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
    artifact_files = [path for path in _unique_paths(artifact_files) if _is_high_trust_path(scan, path)][:20]

    trusted_entry_points = [path for path in scan.entry_points if _is_high_trust_path(scan, path)]
    trusted_config_files = [path for path in scan.config_files if _is_high_trust_path(scan, path)]

    start_here_files = _unique_paths(
        [
            *trusted_entry_points,
            *trusted_config_files,
            *[
                path
                for path in high_trust_files
                if Path(path).name.lower() in {"readme.md", "readme.mdx", "pyproject.toml", "package.json", "go.mod", "composer.json"}
            ],
            *[
                path
                for path in high_trust_files
                if any(token in path.lower() for token in ("cli", "pipeline", "planner", "generator", "scanner", "chatbot"))
            ][:16],
        ]
    )[:24]
    if not start_here_files:
        start_here_files = high_trust_files[:24]

    # Start Here Index (orientation)
    plan.buckets.insert(
        0,
        DocBucket(
            bucket_type="start_here_index",
            title="Start Here",
            slug="start-here",
            section="Start Here",
            description="New-joiner orientation: what this service does, who uses it, how to navigate the docs, and the 5 files every developer must know.",
            owned_files=start_here_files,
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
        for f in high_trust_files
        if any(
            kw in f.lower()
            for kw in (
                "readme",
                "cli",
                "config",
                "setting",
                "env",
                "docker",
                "requirement",
                "package.json",
                "pyproject.toml",
                "go.mod",
                ".env",
            )
        )
    ]
    setup_files = _unique_paths([*trusted_entry_points, *trusted_config_files, *setup_files])[:24]

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
        debug_owned_files: list[str] = []
        for sig in debug_signals:
            if hasattr(sig, "file_path") and sig.file_path:
                if _is_high_trust_path(scan, sig.file_path):
                    debug_owned_files.append(sig.file_path)
            if hasattr(sig, "files"):
                debug_owned_files.extend(
                    file_path
                    for file_path in sig.files[:3]
                    if _is_high_trust_path(scan, file_path)
                )
        debug_owned_files = _unique_paths(debug_owned_files)[:20]

        # Also include middleware, config, and monitoring files
        debug_owned_files += [
            f
            for f in high_trust_files
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

        filtered_debug_signals = []
        for sig in debug_signals:
            signal_files = [
                file_path
                for file_path in getattr(sig, "files", [])[:5]
                if _is_high_trust_path(scan, file_path)
            ]
            signal_file = getattr(sig, "file_path", "")
            if signal_file and _is_high_trust_path(scan, signal_file):
                signal_files.insert(0, signal_file)
            signal_files = _unique_paths(signal_files)
            if not signal_files and getattr(sig, "signal_type", "") in {"health_endpoint", "background_job"}:
                continue
            filtered_debug_signals.append((sig, signal_files))

        if not filtered_debug_signals:
            return plan

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
                    for sig, _ in filtered_debug_signals
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
                            "files": signal_files,
                        }
                        for sig, signal_files in filtered_debug_signals
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
