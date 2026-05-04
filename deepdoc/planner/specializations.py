from .common import *


def _ensure_database_runtime_and_interface_buckets(
    plan: DocPlan,
    scan: RepoScan,
    cfg: dict[str, Any],
) -> DocPlan:
    """Inject deterministic database/runtime/interface bucket branches."""
    plan.buckets = _replace_specialized_buckets(
        plan.buckets,
        prefixes=("database-", "background-jobs", "graphql-"),
        prompt_styles={
            "database",
            "database_overview",
            "database_group",
            "runtime",
            "runtime_overview",
            "graphql",
        },
    )
    plan.buckets.extend(_build_database_buckets(scan, cfg))
    plan.buckets.extend(_build_runtime_buckets(scan, cfg))
    plan.buckets.extend(_build_graphql_buckets(scan, cfg))
    plan.buckets = sorted(plan.buckets, key=lambda bucket: bucket.priority)
    return plan


def _attach_flow_hints_to_cluster_buckets(
    plan: DocPlan,
    scan: RepoScan,
    cfg: dict[str, Any],
) -> DocPlan:
    """Embed flow context (call chain, entrypoints, side effects) into the
    domain buckets that own the entry-point files.

    Instead of creating a separate "Core Workflows" section, each flow
    candidate's context is attached to whichever existing bucket already
    owns the flow's entry files. If no owning bucket is found, the candidate
    is skipped — the topology-based bucket assignment should cover it.
    """
    candidates = list(getattr(scan, "flow_candidates", []) or [])
    if not candidates and scan.call_graph:
        from .flow_candidates import build_flow_candidates
        candidates = build_flow_candidates(scan)
        scan.flow_candidates = candidates

    if not candidates:
        return plan

    max_flow_files = int(cfg.get("max_flow_files", 45))
    max_flow_symbols = int(cfg.get("max_flow_symbols", 80))

    # Build entry-file → bucket index for fast lookup
    file_to_bucket: dict[str, DocBucket] = {}
    for bucket in plan.buckets:
        for f in bucket.owned_files:
            file_to_bucket.setdefault(f, bucket)

    for candidate in candidates:
        entry_files = sorted({ep.handler_file for ep in candidate.entry_points if ep.handler_file})
        entry_symbols = sorted({ep.handler_symbol for ep in candidate.entry_points if ep.handler_symbol})

        # Find the bucket that owns the most entry files
        score: dict[str, int] = {}
        for f in entry_files:
            b = file_to_bucket.get(f)
            if b:
                score[b.slug] = score.get(b.slug, 0) + 1
        if not score:
            continue
        best_slug = max(score, key=lambda s: score[s])
        owner = next((b for b in plan.buckets if b.slug == best_slug), None)
        if not owner:
            continue

        hints = owner.generation_hints or {}

        # Attach flow data — never overwrite existing explicit hints
        if "flow_entrypoints" not in hints:
            hints["flow_entrypoints"] = [
                {
                    "kind": ep.kind,
                    "label": ep.label,
                    "file": ep.handler_file,
                    "symbol": ep.handler_symbol,
                    "family": ep.endpoint_family,
                    "framework": ep.framework,
                }
                for ep in candidate.entry_points
            ]
        if "flow_id" not in hints:
            hints["flow_id"] = candidate.flow_id
        if "flow_entry_kind" not in hints:
            hints["flow_entry_kind"] = candidate.entry_kind

        owner.generation_hints = hints

        # Expand file and symbol ownership with the full call chain
        if candidate.involved_files:
            owner.owned_files = _merge_ordered(
                owner.owned_files,
                candidate.involved_files[:max_flow_files],
            )
        if candidate.involved_symbols:
            owner.owned_symbols = _merge_ordered(
                owner.owned_symbols,
                candidate.involved_symbols[:max_flow_symbols],
            )

        # Ensure sequence diagram is in required_diagrams
        if "sequence_diagram" not in (owner.required_diagrams or []):
            owner.required_diagrams = list(owner.required_diagrams or []) + ["sequence_diagram"]

        # Update file_to_bucket index for newly added files
        for f in owner.owned_files:
            file_to_bucket.setdefault(f, owner)

    return plan


def _merge_ordered(existing: list[str], incoming: list[str]) -> list[str]:
    seen = set(existing)
    merged = list(existing)
    for item in incoming:
        if item and item not in seen:
            merged.append(item)
            seen.add(item)
    return merged


def _replace_specialized_buckets(
    buckets: list[DocBucket],
    *,
    prefixes: tuple[str, ...],
    prompt_styles: set[str],
) -> list[DocBucket]:
    filtered: list[DocBucket] = []
    for bucket in buckets:
        hints = bucket.generation_hints or {}
        style = hints.get("prompt_style", "")
        if style in prompt_styles:
            continue
        if any(bucket.slug.startswith(prefix) for prefix in prefixes):
            continue
        filtered.append(bucket)
    return filtered


def _build_database_buckets(scan: RepoScan, cfg: dict[str, Any]) -> list[DocBucket]:
    artifact_scan = getattr(scan, "artifact_scan", None)
    db_scan = getattr(artifact_scan, "database_scan", None) if artifact_scan else None
    if not db_scan:
        return []

    db_files = list(
        dict.fromkeys(
            [mf.file_path for mf in db_scan.model_files]
            + list(db_scan.schema_files)
            + [
                artifact.file_path
                for artifact in getattr(db_scan, "knex_artifacts", [])
            ]
        )
    )
    if not db_files:
        return []

    model_cap = int(cfg.get("database_group_model_cap", 12))
    file_cap = int(cfg.get("database_group_file_cap", 8))
    should_split = cfg.get(
        "database_doc_mode", "overview_plus_groups"
    ) == "overview_plus_groups" and (
        db_scan.total_models > model_cap
        or len(db_files) > file_cap
        or len(getattr(db_scan, "orm_frameworks", []) or []) > 1
        or len(getattr(db_scan, "groups", []) or []) > 1
    )

    buckets: list[DocBucket] = [
        DocBucket(
            bucket_type="database",
            title="Database & Schema",
            slug="database-schema",
            section="Database > Database & Schema",
            description="Database overview, storage topology, schema groups, migrations, and cross-group relationships",
            owned_files=db_files,
            required_sections=[
                "overview",
                "storage_model",
                "schema_group_index",
                "high_level_er_diagram",
                "cross_group_relationships",
                "migrations",
                "query_patterns",
                "configuration",
            ],
            required_diagrams=["er_diagram"],
            generation_hints={
                "include_database_context": True,
                "prompt_style": "database_overview",
                "icon": "database",
                "preserve_section": True,
                "is_database_overview": True,
            },
            priority=3,
        )
    ]

    if not should_split:
        return buckets

    existing = {bucket.slug for bucket in buckets}
    for index, group in enumerate(getattr(db_scan, "groups", []) or [], start=1):
        if not group.file_paths:
            continue
        slug = _stable_specialized_slug(f"database-{group.key}", existing)
        existing.add(slug)
        buckets.append(
            DocBucket(
                bucket_type="database-group",
                title=f"{group.label} Data Model",
                slug=slug,
                section="Database > Database & Schema",
                description=f"Complete schema documentation for the {group.label} data group",
                owned_files=group.file_paths,
                required_sections=[
                    "overview",
                    "models_tables",
                    "relationships",
                    "indexes_constraints",
                    "used_by",
                    "group_diagram",
                ],
                required_diagrams=["er_diagram"],
                generation_hints={
                    "include_database_context": True,
                    "prompt_style": "database_group",
                    "icon": "database",
                    "preserve_section": True,
                    "is_database_group": True,
                    "database_group_key": group.key,
                },
                priority=3 + index,
                parent_slug="database-schema",
                depends_on=["database-schema"],
            )
        )

    if (
        len(db_scan.migration_files) >= 3
        or len(getattr(db_scan, "knex_artifacts", [])) >= 4
    ):
        slug = _stable_specialized_slug("database-migrations-query-patterns", existing)
        buckets.append(
            DocBucket(
                bucket_type="database-support",
                title="Migrations & Query Patterns",
                slug=slug,
                section="Database > Database & Schema",
                description="Migration workflow, schema evolution, and notable query patterns",
                owned_files=db_scan.migration_files[:20]
                + sorted(
                    {
                        artifact.file_path
                        for artifact in getattr(db_scan, "knex_artifacts", [])[:20]
                    }
                ),
                required_sections=[
                    "overview",
                    "migration_strategy",
                    "notable_migrations",
                    "query_patterns",
                    "performance_notes",
                ],
                generation_hints={
                    "include_database_context": True,
                    "prompt_style": "database_group",
                    "icon": "database",
                    "preserve_section": True,
                    "is_database_group": True,
                    "database_group_key": "migrations-query-patterns",
                },
                priority=3 + len(buckets) + 1,
                parent_slug="database-schema",
                depends_on=["database-schema"],
            )
        )

    return buckets


def _build_runtime_buckets(scan: RepoScan, cfg: dict[str, Any]) -> list[DocBucket]:
    runtime_scan = getattr(scan, "runtime_scan", None)
    if (
        cfg.get("runtime_doc_mode", "dedicated_pages") != "dedicated_pages"
        or not runtime_scan
    ):
        return []

    task_files = sorted({task.file_path for task in runtime_scan.tasks})
    scheduler_files = sorted({item.file_path for item in runtime_scan.schedulers})
    realtime_files = sorted(
        {item.file_path for item in runtime_scan.realtime_consumers}
    )
    task_kinds = {
        getattr(task, "runtime_kind", "")
        for task in runtime_scan.tasks
        if getattr(task, "runtime_kind", "")
    }
    if not (task_files or scheduler_files or realtime_files):
        return []

    buckets: list[DocBucket] = [
        DocBucket(
            bucket_type="runtime",
            title="Background Jobs & Runtime",
            slug="background-jobs",
            section="Background Jobs > Background Jobs & Runtime",
            description="Overview of asynchronous tasks, schedulers, and realtime surfaces",
            owned_files=sorted({*task_files, *scheduler_files, *realtime_files}),
            required_sections=[
                "overview",
                "runtime_surfaces",
                "execution_map",
                "schedulers",
                "realtime_surfaces",
                "operational_notes",
            ],
            required_diagrams=["architecture_flow"],
            generation_hints={
                "prompt_style": "runtime_overview",
                "icon": "clock",
                "preserve_section": True,
                "include_runtime_context": True,
                "is_runtime_overview": True,
            },
            priority=4,
        )
    ]

    if task_files and task_kinds <= {"celery"}:
        buckets.append(
            DocBucket(
                bucket_type="runtime-group",
                title="Celery Tasks & Producers",
                slug="background-jobs-celery",
                section="Background Jobs > Background Jobs & Runtime",
                description="Task definitions, queues, retries, producers, and schedule sources",
                owned_files=task_files,
                required_sections=[
                    "overview",
                    "tasks",
                    "queues_retries",
                    "producers_consumers",
                    "schedule_sources",
                ],
                generation_hints={
                    "prompt_style": "runtime",
                    "icon": "clock",
                    "preserve_section": True,
                    "include_runtime_context": True,
                    "runtime_group_kind": "celery",
                },
                priority=5,
                parent_slug="background-jobs",
                depends_on=["background-jobs"],
            )
        )

    django_task_files = sorted(
        {
            task.file_path
            for task in runtime_scan.tasks
            if getattr(task, "runtime_kind", "") in {"django_command", "django_signal"}
        }
    )
    if django_task_files:
        buckets.append(
            DocBucket(
                bucket_type="runtime-group",
                title="Django Commands & Signals",
                slug="background-jobs-django",
                section="Background Jobs > Background Jobs & Runtime",
                description="Management commands, signal handlers, and other Django runtime surfaces",
                owned_files=django_task_files,
                required_sections=[
                    "overview",
                    "commands",
                    "signals",
                    "trigger_points",
                    "operational_notes",
                ],
                generation_hints={
                    "prompt_style": "runtime",
                    "icon": "clock",
                    "preserve_section": True,
                    "include_runtime_context": True,
                    "runtime_group_kind": "django",
                },
                priority=5 if not (task_files and task_kinds <= {"celery"}) else 6,
                parent_slug="background-jobs",
                depends_on=["background-jobs"],
            )
        )

    laravel_task_files = sorted(
        {
            task.file_path
            for task in runtime_scan.tasks
            if getattr(task, "runtime_kind", "").startswith("laravel_")
        }
        | {
            item.file_path
            for item in runtime_scan.schedulers
            if getattr(item, "scheduler_type", "") == "laravel_schedule"
        }
    )
    if laravel_task_files:
        buckets.append(
            DocBucket(
                bucket_type="runtime-group",
                title="Laravel Jobs, Events & Scheduler",
                slug="background-jobs-laravel",
                section="Background Jobs > Background Jobs & Runtime",
                description="Queued jobs, events, listeners, and scheduler registrations for Laravel services",
                owned_files=laravel_task_files,
                required_sections=[
                    "overview",
                    "jobs_events",
                    "listeners",
                    "scheduler_registrations",
                    "trigger_points",
                ],
                generation_hints={
                    "prompt_style": "runtime",
                    "icon": "clock",
                    "preserve_section": True,
                    "include_runtime_context": True,
                    "runtime_group_kind": "laravel",
                },
                priority=6 if not django_task_files else 7,
                parent_slug="background-jobs",
                depends_on=["background-jobs"],
            )
        )

    generic_task_files = sorted(
        {
            task.file_path
            for task in runtime_scan.tasks
            if getattr(task, "runtime_kind", "")
            not in {"celery", "django_command", "django_signal"}
            and not getattr(task, "runtime_kind", "").startswith("laravel_")
        }
    )
    if generic_task_files:
        buckets.append(
            DocBucket(
                bucket_type="runtime-group",
                title="Workers & Async Runners",
                slug="background-jobs-workers",
                section="Background Jobs > Background Jobs & Runtime",
                description="Background workers, async consumers, and non-framework-specific runtime loops",
                owned_files=generic_task_files,
                required_sections=[
                    "overview",
                    "worker_surfaces",
                    "trigger_points",
                    "schedules",
                    "operational_notes",
                ],
                generation_hints={
                    "prompt_style": "runtime",
                    "icon": "clock",
                    "preserve_section": True,
                    "include_runtime_context": True,
                    "runtime_group_kind": "workers",
                },
                priority=7 if not laravel_task_files else 8,
                parent_slug="background-jobs",
                depends_on=["background-jobs"],
            )
        )

    if scheduler_files:
        buckets.append(
            DocBucket(
                bucket_type="runtime-group",
                title="Schedulers & Cron",
                slug="background-jobs-schedulers",
                section="Background Jobs > Background Jobs & Runtime",
                description="Cron schedules, task cadence, and scheduler ownership",
                owned_files=scheduler_files,
                required_sections=[
                    "overview",
                    "registered_schedules",
                    "invoked_targets",
                    "safety_notes",
                ],
                generation_hints={
                    "prompt_style": "runtime",
                    "icon": "clock",
                    "preserve_section": True,
                    "include_runtime_context": True,
                    "runtime_group_kind": "schedulers",
                },
                priority=6,
                parent_slug="background-jobs",
                depends_on=["background-jobs"],
            )
        )

    if realtime_files:
        buckets.append(
            DocBucket(
                bucket_type="runtime-group",
                title="Realtime & WebSockets",
                slug="background-jobs-realtime",
                section="Background Jobs > Background Jobs & Runtime",
                description="Realtime consumers, websocket routing, groups, and auth path",
                owned_files=realtime_files,
                required_sections=[
                    "overview",
                    "consumers_routes",
                    "group_flow",
                    "auth_path",
                    "redis_channel_layer",
                ],
                generation_hints={
                    "prompt_style": "runtime",
                    "icon": "clock",
                    "preserve_section": True,
                    "include_runtime_context": True,
                    "runtime_group_kind": "realtime",
                },
                priority=7,
                parent_slug="background-jobs",
                depends_on=["background-jobs"],
            )
        )

    return buckets


def _build_graphql_buckets(scan: RepoScan, cfg: dict[str, Any]) -> list[DocBucket]:
    interfaces = list(getattr(scan, "graphql_interfaces", []) or [])
    if not interfaces:
        return []

    files = sorted({item.file_path for item in interfaces})
    buckets: list[DocBucket] = [
        DocBucket(
            bucket_type="graphql",
            title="GraphQL Interfaces",
            slug="graphql-interfaces",
            section="Interfaces > GraphQL",
            description="GraphQL schemas, queries, mutations, and resolver surfaces",
            owned_files=files,
            required_sections=[
                "overview",
                "schema_roots",
                "queries_mutations",
                "resolver_flow",
                "related_models",
            ],
            generation_hints={
                "prompt_style": "graphql",
                "icon": "globe-alt",
                "preserve_section": True,
            },
            priority=8,
        )
    ]

    kind_groups: dict[str, list[Any]] = defaultdict(list)
    for item in interfaces:
        kind_groups[item.kind].append(item)
    if len(interfaces) > 6:
        for index, (kind, items) in enumerate(sorted(kind_groups.items()), start=1):
            buckets.append(
                DocBucket(
                    bucket_type="graphql-group",
                    title=f"GraphQL {kind.replace('_', ' ').title()}",
                    slug=f"graphql-{kind.replace('_', '-')}",
                    section="Interfaces > GraphQL",
                    description=f"GraphQL {kind.replace('_', ' ')} surfaces and related resolvers",
                    owned_files=sorted({item.file_path for item in items}),
                    generation_hints={
                        "prompt_style": "graphql",
                        "icon": "globe-alt",
                        "preserve_section": True,
                    },
                    priority=8 + index,
                    parent_slug="graphql-interfaces",
                    depends_on=["graphql-interfaces"],
                )
            )
    return buckets


from .heuristics import _stable_specialized_slug
