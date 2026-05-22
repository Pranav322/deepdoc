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

    Acts as a safety net: each bucket is only injected if the LLM didn't already
    propose an equivalent. The LLM is instructed to propose these when signals exist,
    so injection here fires only on LLM omission.
    """
    # ── Detect what the LLM already proposed ──────────────────────────────
    existing_slugs = {b.slug for b in plan.buckets}
    existing_types = {b.bucket_type for b in plan.buckets}
    existing_hints = {
        k for b in plan.buckets for k, v in (b.generation_hints or {}).items() if v
    }

    has_intro = any(
        (b.generation_hints or {}).get("is_introduction_page") for b in plan.buckets
    )
    has_setup = (
        "start_here_setup" in existing_types
        or "local-development-setup" in existing_slugs
        or any(
            b.bucket_type in ("setup", "getting-started", "local-development")
            or "setup" in b.slug
            or "getting-started" in b.slug
            for b in plan.buckets
        )
    )
    has_glossary = any(
        "glossary" in b.slug or b.bucket_type in ("domain_glossary", "glossary")
        for b in plan.buckets
    )
    has_debug = any(
        "debug" in b.slug
        or "observability" in b.slug
        or b.bucket_type in ("debug_runbook", "debugging", "observability")
        for b in plan.buckets
    )

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

    # Start Here Index (orientation) — inject only if LLM didn't propose one
    if not has_intro:
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
                    "is_introduction_page": True,
                    "icon": "rocket",
                    "always_generate": True,
                    "preserve_section": True,
                },
                priority=-20,
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

    if not has_setup:
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

    if not has_glossary:
        plan.buckets.insert(
            2,
            DocBucket(
                bucket_type="domain_glossary",
                title="Domain Glossary",
                slug="domain-glossary",
                section="Start Here",
                description="Plain-English definitions of every domain-specific term, model name, status code, and internal system name used in this codebase.",
                owned_files=db_model_files[:10] if db_model_files else all_files[:8],
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

    # ── Debug & Observability runbook (safety net) ────────────────────────
    # Inject only if LLM didn't already propose a debug/observability bucket.
    debug_signals = getattr(scan, "debug_signals", []) if scan else []
    if len(debug_signals) >= 2 and not has_debug:
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


_GENERIC_PLACEHOLDER_SECTIONS = {
    "",
    "general",
    "misc",
    "miscellaneous",
    "other",
    "features",
    "pages",
}

_BACKEND_INTEGRATION_TOKENS = {
    "cdn",
    "clickpost",
    "climes",
    "express",
    "gateway",
    "integration",
    "provider",
    "s3",
    "third",
    "vinculum",
    "warehouse",
    "webhook",
    "wms",
}

_BACKEND_OPERATION_TOKENS = {
    "config",
    "cron",
    "debug",
    "health",
    "log",
    "logger",
    "logging",
    "metric",
    "monitor",
    "observability",
    "scheduler",
    "utility",
    "utilities",
}

_BACKEND_RUNTIME_TOKENS = {
    "agenda",
    "async",
    "background",
    "celery",
    "command",
    "consumer",
    "cron",
    "django",
    "job",
    "queue",
    "scheduler",
    "signal",
    "task",
    "worker",
}

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


def _canonical_section_for_bucket(bucket: DocBucket, primary_type: str) -> str:
    hints = bucket.generation_hints or {}
    # Intro/overview pages are rendered at the root level by the site builder —
    # they must not appear in any section or they get duplicated in the sidebar.
    if hints.get("is_introduction_page"):
        return "__root__"
    # Setup buckets always belong in Start Here regardless of LLM assignment.
    if bucket.bucket_type in {"setup", "start_here_setup"}:
        return "Start Here"

    # Route supporting-tier buckets to structural sections by source kind / title tokens
    if bucket.publication_tier == "supporting":
        supporting_section = supporting_section_for_kinds(bucket.source_kind_summary)
        if supporting_section:
            return supporting_section
        title_tokens = _bucket_semantic_tokens(bucket)
        if bucket.bucket_type == "research-context" or any(
            token in title_tokens for token in {"history", "note", "notes", "glossary"}
        ):
            return "Design & Notes"
        if any(token in title_tokens for token in {"test", "cypress", "playwright", "spec"}):
            return "Testing"
        if any(token in title_tokens for token in {"release", "deploy", "build", "workflow", "ci"}):
            return "CI/CD and Release"
        return "Supporting Material"

    # For non-supporting tier: trust the LLM's section assignment if it's meaningful
    existing = (bucket.section or "").strip()
    if (
        existing
        and existing.lower() not in _GENERIC_PLACEHOLDER_SECTIONS
        and not _looks_like_path_slug_section(existing)
    ):
        return existing

    return "Architecture"


def _looks_like_path_slug_section(section: str) -> bool:
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


def _is_backend_placeholder_section(section: str, primary_type: str) -> bool:
    if primary_type not in {"backend_service", "backend_api", "falcon_backend"}:
        return False
    return section.strip().lower() in {
        "architecture",
        "async tasks",
        "background processing",
        "core",
        "customer support",
        "features",
        "jobs",
        "platform utilities",
        "runtime & frameworks",
        "services",
        "subsystems",
        "utilities",
    }
