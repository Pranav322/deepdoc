from __future__ import annotations

from pathlib import Path

from deepdoc.benchmark_v2 import score_plan
from deepdoc.generator import PageValidator
from deepdoc.parser.base import ParsedFile, Symbol
from deepdoc.persistence_v2 import load_plan, save_plan
from deepdoc.planner import (
    CLASSIFY_PROMPT,
    PROPOSE_PROMPT,
    DocBucket,
    DocPlan,
    RepoScan,
    _apply_page_contracts,
    _auto_generate_endpoint_refs,
    _decompose_buckets,
    _derive_topic_candidates,
    _ensure_database_runtime_and_interface_buckets,
    _inject_research_context_buckets,
    _inject_start_here_and_debug_buckets,
    _normalize_tokens,
    _refine_bucket_ownership,
    _refine_proposal,
    _shape_plan_nav,
    _validate_coverage,
    scan_repo,
)
from deepdoc.prompts_v2 import PROMPT_STYLE_TEMPLATES
from deepdoc.site.builder import build_fumadocs_from_plan


def _make_scan(
    *,
    file_summaries: dict[str, str] | None = None,
    api_endpoints: list[dict] | None = None,
    file_line_counts: dict[str, int] | None = None,
    parsed_files: dict[str, ParsedFile] | None = None,
    giant_file_clusters: dict[str, object] | None = None,
) -> RepoScan:
    summaries = file_summaries or {}
    return RepoScan(
        file_tree={},
        file_summaries=summaries,
        api_endpoints=api_endpoints or [],
        languages={"python": max(len(summaries), 1)},
        has_openapi=False,
        openapi_paths=[],
        total_files=len(summaries),
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
        file_line_counts=file_line_counts or {},
        parsed_files=parsed_files or {},
        file_contents={},
        giant_file_clusters=giant_file_clusters or {},
    )


def _parsed_file(path: str, *, imports: list[str], symbols: list[Symbol]) -> ParsedFile:
    return ParsedFile(
        path=Path(path), language="python", imports=imports, symbols=symbols
    )


def test_save_and_load_plan_preserve_parent_slug_and_classification(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    plan = DocPlan(
        buckets=[
            DocBucket(
                bucket_type="system",
                title="Attention",
                slug="attention",
                section="Model Architecture",
                description="Attention docs",
                owned_files=["model.py"],
                parent_slug="transformer",
            )
        ],
        nav_structure={"Model Architecture": ["attention"]},
        skipped_files=[],
        classification={
            "repo_profile": {
                "primary_type": "research_training",
                "secondary_traits": ["has_cli"],
                "confidence": "high",
                "evidence": "training loop and optimizer files",
            }
        },
    )

    save_plan(plan, repo_root)
    loaded = load_plan(repo_root)

    assert isinstance(loaded, DocPlan)
    assert loaded.classification["repo_profile"]["primary_type"] == "research_training"
    assert loaded.buckets[0].parent_slug == "transformer"


def test_decompose_buckets_preserves_parent_overview_and_dedupes_slugs(
    monkeypatch,
) -> None:
    bucket = DocBucket(
        bucket_type="training",
        title="Training Core",
        slug="training-core",
        section="Training",
        description="Broad training docs",
        owned_files=["train.py", "optim.py", "schedule.py"],
        artifact_refs=["pyproject.toml"],
        generation_hints={"prompt_style": "training"},
    )
    plan = DocPlan(
        buckets=[bucket],
        nav_structure={"Training": ["training-core"]},
        skipped_files=[],
        classification={"repo_profile": {"primary_type": "research_training"}},
    )
    scan = _make_scan(
        file_summaries={
            "train.py": "symbols=[function:train]",
            "optim.py": "symbols=[class:Muon]",
            "schedule.py": "symbols=[function:build_schedule]",
        },
        file_line_counts={"train.py": 120, "optim.py": 80, "schedule.py": 60},
        parsed_files={
            "train.py": _parsed_file(
                "train.py",
                imports=["torch", "optim"],
                symbols=[
                    Symbol(name="train", kind="function", signature="def train():")
                ],
            ),
            "optim.py": _parsed_file(
                "optim.py",
                imports=["torch"],
                symbols=[Symbol(name="Muon", kind="class", signature="class Muon:")],
            ),
            "schedule.py": _parsed_file(
                "schedule.py",
                imports=["math"],
                symbols=[
                    Symbol(
                        name="build_schedule",
                        kind="function",
                        signature="def build_schedule():",
                    )
                ],
            ),
        },
    )

    def _fake_llm_step(llm, system, prompt, step_name):
        assert "## Repo Profile:" in prompt
        return {
            "sub_topics": [
                {
                    "title": "Training Loop",
                    "slug": "training-loop",
                    "description": "Forward and backward pass flow",
                    "owned_files": ["train.py"],
                    "owned_symbols": ["train"],
                    "required_sections": ["overview", "implementation_details"],
                    "required_diagrams": ["training_flow"],
                    "prompt_style": "training",
                },
                {
                    "title": "Optimizer and Schedules",
                    "slug": "training-loop",
                    "description": "Optimizer and schedule internals",
                    "owned_files": ["optim.py", "schedule.py"],
                    "owned_symbols": ["Muon", "build_schedule"],
                    "required_sections": ["overview", "implementation_details"],
                    "required_diagrams": ["training_flow"],
                    "prompt_style": "training",
                },
            ],
            "nav_section": "Training > Base Training",
            "keep_parent_overview": True,
        }

    monkeypatch.setattr("deepdoc.planner.heuristics._llm_step", _fake_llm_step)

    result = _decompose_buckets(
        plan,
        scan,
        {"decompose_threshold": 2},
        llm=object(),
        repo_profile={"primary_type": "research_training"},
    )

    assert "Training > Base Training" in result.nav_structure
    assert result.nav_structure["Training > Base Training"][0] == "training-core"
    assert any(b.title == "Training Core Overview" for b in result.buckets)
    assert len({b.slug for b in result.buckets}) == 3
    assert any(
        b.parent_slug == "training-core"
        for b in result.buckets
        if b.slug != "training-core"
    )


def test_auto_generate_endpoint_refs_respects_profile_and_suppresses_noise() -> None:
    non_api_plan = DocPlan(
        buckets=[],
        nav_structure={},
        skipped_files=[],
        classification={"repo_profile": {"primary_type": "research_training"}},
    )
    scan = _make_scan(
        api_endpoints=[
            {
                "method": "GET",
                "path": "/health",
                "handler": "health",
                "file": "serve.py",
            },
            {
                "method": "GET",
                "path": "/logo.svg",
                "handler": "logo",
                "file": "serve.py",
            },
            {
                "method": "POST",
                "path": "/predict",
                "handler": "predict",
                "file": "serve.py",
            },
        ]
    )

    gated = _auto_generate_endpoint_refs(non_api_plan, scan)
    assert not [b for b in gated.buckets if b.generation_hints.get("is_endpoint_ref")]

    api_family = DocBucket(
        bucket_type="endpoint-family",
        title="Orders API",
        slug="orders-api",
        section="API Reference",
        description="Orders endpoints",
        generation_hints={"is_endpoint_family": True, "prompt_style": "endpoint"},
    )
    backend_plan = DocPlan(
        buckets=[api_family],
        nav_structure={"API Reference": ["orders-api"]},
        skipped_files=[],
        classification={"repo_profile": {"primary_type": "backend_api"}},
    )
    backend_scan = _make_scan(
        api_endpoints=[
            {
                "method": "GET",
                "path": "/health",
                "handler": "health",
                "file": "routes.py",
            },
            {
                "method": "GET",
                "path": "/orders/{id}",
                "handler": "get_order",
                "file": "routes.py",
                "route_file": "routes.py",
                "handler_file": "orders.py",
            },
        ]
    )

    expanded = _auto_generate_endpoint_refs(backend_plan, backend_scan)
    slugs = {b.slug for b in expanded.buckets}
    assert "get-orders-id" in slugs
    assert "get-health" not in slugs

    skipped_plan = DocPlan(
        buckets=[api_family],
        nav_structure={"API Reference": ["orders-api"]},
        skipped_files=[],
        classification={"repo_profile": {"primary_type": "backend_api"}},
    )
    skipped = _auto_generate_endpoint_refs(
        skipped_plan,
        backend_scan,
        include_endpoint_pages=False,
    )
    assert not [b for b in skipped.buckets if b.generation_hints.get("is_endpoint_ref")]


def test_start_here_setup_slug_and_section_are_preserved() -> None:
    plan = DocPlan(
        buckets=[],
        nav_structure={"Start Here": []},
        skipped_files=[],
        classification={"repo_profile": {"primary_type": "backend_api"}},
    )
    scan = _make_scan(
        file_summaries={
            "README.md": "overview",
            "settings.py": "config",
            "docker-compose.yml": "docker",
        }
    )
    scan.config_files = ["settings.py"]

    injected = _inject_start_here_and_debug_buckets(plan, scan, {})
    shaped = _shape_plan_nav(
        injected,
        {"repo_profile": {"primary_type": "backend_api"}},
    )

    start_here_slugs = shaped.nav_structure["Start Here"]
    assert "local-development-setup" in start_here_slugs
    assert "setup" not in start_here_slugs
    assert start_here_slugs[:3] == [
        "start-here",
        "local-development-setup",
        "domain-glossary",
    ]
    start_here_bucket = next(
        bucket for bucket in shaped.buckets if bucket.slug == "local-development-setup"
    )
    assert start_here_bucket.section == "Start Here"
    assert start_here_bucket.generation_hints["preserve_section"] is True


def test_shape_plan_nav_backend_uses_reader_flow_and_dedupes_setup() -> None:
    plan = DocPlan(
        buckets=[
            DocBucket(
                bucket_type="start_here_index",
                title="Start Here",
                slug="start-here",
                section="Start Here",
                description="Orientation",
                generation_hints={"preserve_section": True},
                priority=-20,
            ),
            DocBucket(
                bucket_type="start_here_setup",
                title="Local Development Setup",
                slug="local-development-setup",
                section="Start Here",
                description="Setup",
                owned_files=["README.md"],
                generation_hints={"preserve_section": True},
                priority=-19,
            ),
            DocBucket(
                bucket_type="setup",
                title="Setup & Getting Started",
                slug="setup",
                section="Subsystems",
                description="Legacy setup bucket",
                owned_files=["settings.py"],
                priority=1,
            ),
            DocBucket(
                bucket_type="domain_glossary",
                title="Domain Glossary",
                slug="domain-glossary",
                section="Start Here",
                description="Terms",
                generation_hints={"preserve_section": True},
                priority=-18,
            ),
            DocBucket(
                bucket_type="feature",
                title="Orders Workflow",
                slug="orders-workflow",
                section="Architecture",
                description="Orders flow",
                owned_files=["orders.py"],
                priority=10,
            ),
            DocBucket(
                bucket_type="endpoint-family",
                title="Orders API",
                slug="orders-api",
                section="API Reference",
                description="Orders endpoints",
                generation_hints={
                    "is_endpoint_family": True,
                    "prompt_style": "endpoint",
                },
                priority=20,
            ),
            DocBucket(
                bucket_type="endpoint-ref",
                title="GET /orders/{id}",
                slug="get-orders-id",
                section="API Reference",
                description="Endpoint ref",
                generation_hints={
                    "is_endpoint_ref": True,
                    "prompt_style": "endpoint_ref",
                },
                depends_on=["orders-api"],
                priority=25,
            ),
        ],
        nav_structure={},
        skipped_files=[],
        classification={"repo_profile": {"primary_type": "backend_service"}},
    )

    shaped = _shape_plan_nav(
        plan, {"repo_profile": {"primary_type": "backend_service"}}
    )

    slugs = {bucket.slug for bucket in shaped.buckets}
    assert "setup" not in slugs

    sections = list(shaped.nav_structure.keys())
    assert sections[:3] == [
        "Start Here",
        "Core Workflows",
        "API Reference > Orders API",
    ]
    assert shaped.nav_structure["Start Here"] == [
        "start-here",
        "local-development-setup",
        "domain-glossary",
    ]
    assert shaped.nav_structure["API Reference > Orders API"] == [
        "orders-api",
        "get-orders-id",
    ]


def test_specialized_bucket_injection_splits_large_database_docs_and_adds_runtime_pages() -> (
    None
):
    scan = _make_scan(
        file_summaries={
            "orders/models.py": "summary",
            "orders/schema.py": "summary",
            "catalog/models.py": "summary",
            "tasks.py": "summary",
            "scheduler.py": "summary",
        }
    )
    scan.artifact_scan = type(
        "ArtifactScan",
        (),
        {
            "database_scan": type(
                "DatabaseScan",
                (),
                {
                    "model_files": [
                        type(
                            "ModelFileInfo",
                            (),
                            {
                                "file_path": "orders/models.py",
                                "model_names": ["Order", "OrderItem"],
                                "orm_framework": "django",
                                "is_migration": False,
                            },
                        )(),
                        type(
                            "ModelFileInfo",
                            (),
                            {
                                "file_path": "orders/schema.py",
                                "model_names": ["Refund", "Exchange"],
                                "orm_framework": "django",
                                "is_migration": False,
                            },
                        )(),
                        type(
                            "ModelFileInfo",
                            (),
                            {
                                "file_path": "catalog/models.py",
                                "model_names": ["Product"],
                                "orm_framework": "django",
                                "is_migration": False,
                            },
                        )(),
                    ],
                    "schema_files": [],
                    "migration_files": [
                        "orders/migrations/0001_initial.py",
                        "orders/migrations/0002_update.py",
                        "catalog/migrations/0001_initial.py",
                    ],
                    "orm_framework": "django",
                    "orm_frameworks": ["django", "knex"],
                    "total_models": 13,
                    "groups": [
                        type(
                            "DatabaseGroup",
                            (),
                            {
                                "key": "orders",
                                "label": "Orders",
                                "file_paths": ["orders/models.py", "orders/schema.py"],
                                "model_names": [
                                    "Order",
                                    "OrderItem",
                                    "Refund",
                                    "Exchange",
                                ],
                                "orm_frameworks": ["django"],
                                "external_refs": ["catalog"],
                            },
                        )(),
                        type(
                            "DatabaseGroup",
                            (),
                            {
                                "key": "catalog",
                                "label": "Catalog",
                                "file_paths": ["catalog/models.py"],
                                "model_names": ["Product"],
                                "orm_frameworks": ["django"],
                                "external_refs": ["orders"],
                            },
                        )(),
                    ],
                    "knex_artifacts": [
                        type(
                            "KnexArtifact",
                            (),
                            {
                                "file_path": "orders/query.js",
                                "artifact_type": "query",
                                "table_name": "orders",
                            },
                        )(),
                        type(
                            "KnexArtifact",
                            (),
                            {
                                "file_path": "orders/query2.js",
                                "artifact_type": "query",
                                "table_name": "order_items",
                            },
                        )(),
                        type(
                            "KnexArtifact",
                            (),
                            {
                                "file_path": "orders/query3.js",
                                "artifact_type": "query",
                                "table_name": "refunds",
                            },
                        )(),
                        type(
                            "KnexArtifact",
                            (),
                            {
                                "file_path": "orders/query4.js",
                                "artifact_type": "query",
                                "table_name": "exchanges",
                            },
                        )(),
                    ],
                    "graphql_interfaces": [],
                },
            )(),
        },
    )()
    scan.runtime_scan = type(
        "RuntimeScan",
        (),
        {
            "tasks": [
                type(
                    "RuntimeTask",
                    (),
                    {
                        "name": "sync_orders",
                        "file_path": "tasks.py",
                        "runtime_kind": "celery",
                    },
                )(),
            ],
            "schedulers": [
                type(
                    "RuntimeScheduler",
                    (),
                    {
                        "name": "order-cron",
                        "file_path": "scheduler.py",
                        "scheduler_type": "node_cron",
                    },
                )(),
            ],
            "realtime_consumers": [],
        },
    )()

    plan = DocPlan(
        buckets=[],
        nav_structure={},
        skipped_files=[],
        classification={"repo_profile": {"primary_type": "backend_service"}},
    )

    expanded = _ensure_database_runtime_and_interface_buckets(
        plan,
        scan,
        {
            "database_doc_mode": "overview_plus_groups",
            "database_group_model_cap": 12,
            "database_group_file_cap": 8,
            "runtime_doc_mode": "dedicated_pages",
        },
    )

    slugs = {bucket.slug for bucket in expanded.buckets}
    assert "database-schema" in slugs
    assert "database-orders" in slugs
    assert "database-catalog" in slugs
    assert "background-jobs" in slugs
    assert "background-jobs-celery" in slugs
    assert "background-jobs-schedulers" in slugs

    order_bucket = next(
        bucket for bucket in expanded.buckets if bucket.slug == "database-orders"
    )
    assert order_bucket.parent_slug == "database-schema"
    assert order_bucket.generation_hints["database_group_key"] == "orders"
    assert order_bucket.section == "Database > Database & Schema"


def test_specialized_bucket_injection_adds_django_and_laravel_runtime_groups() -> None:
    scan = _make_scan(file_summaries={"signals.py": "summary", "Kernel.php": "summary"})
    scan.runtime_scan = type(
        "RuntimeScan",
        (),
        {
            "tasks": [
                type(
                    "RuntimeTask",
                    (),
                    {
                        "name": "publish_order_update",
                        "file_path": "signals.py",
                        "runtime_kind": "django_signal",
                    },
                )(),
                type(
                    "RuntimeTask",
                    (),
                    {
                        "name": "SyncOrders",
                        "file_path": "app/Jobs/SyncOrders.php",
                        "runtime_kind": "laravel_job",
                    },
                )(),
            ],
            "schedulers": [
                type(
                    "RuntimeScheduler",
                    (),
                    {
                        "name": "laravel-command-1",
                        "file_path": "app/Console/Kernel.php",
                        "scheduler_type": "laravel_schedule",
                    },
                )(),
            ],
            "realtime_consumers": [],
        },
    )()
    plan = DocPlan(buckets=[], nav_structure={}, skipped_files=[])

    expanded = _ensure_database_runtime_and_interface_buckets(
        plan,
        scan,
        {"runtime_doc_mode": "dedicated_pages"},
    )

    slugs = {bucket.slug for bucket in expanded.buckets}
    assert "background-jobs-django" in slugs
    assert "background-jobs-laravel" in slugs


def test_specialized_bucket_injection_adds_generic_worker_runtime_group() -> None:
    scan = _make_scan(file_summaries={"cmd/worker/main.go": "summary"})
    scan.runtime_scan = type(
        "RuntimeScan",
        (),
        {
            "tasks": [
                type(
                    "RuntimeTask",
                    (),
                    {
                        "name": "syncLoop",
                        "file_path": "cmd/worker/main.go",
                        "runtime_kind": "go_worker",
                    },
                )(),
            ],
            "schedulers": [],
            "realtime_consumers": [],
        },
    )()
    plan = DocPlan(buckets=[], nav_structure={}, skipped_files=[])

    expanded = _ensure_database_runtime_and_interface_buckets(
        plan,
        scan,
        {"runtime_doc_mode": "dedicated_pages"},
    )

    slugs = {bucket.slug for bucket in expanded.buckets}
    assert "background-jobs-workers" in slugs


def test_validate_coverage_prefers_semantic_attachment_over_module_bucket() -> None:
    bucket = DocBucket(
        bucket_type="system",
        title="Database Layer",
        slug="database-layer",
        section="Architecture",
        description="Database internals",
        owned_files=["service.py"],
    )
    plan = DocPlan(
        buckets=[bucket],
        nav_structure={"Architecture": ["database-layer"]},
        skipped_files=[],
    )
    scan = _make_scan(
        file_summaries={"service.py": "service", "db_helpers.py": "helpers"},
        parsed_files={
            "service.py": _parsed_file(
                "service.py",
                imports=["sqlalchemy", "common.db", "infra.cache"],
                symbols=[
                    Symbol(name="Service", kind="class", signature="class Service:")
                ],
            ),
            "db_helpers.py": _parsed_file(
                "db_helpers.py",
                imports=["common.db", "infra.cache", "typing"],
                symbols=[
                    Symbol(
                        name="build_engine",
                        kind="function",
                        signature="def build_engine():",
                    )
                ],
            ),
        },
    )

    result = _validate_coverage(plan, scan)

    assert "db_helpers.py" in result.buckets[0].owned_files
    assert not any(
        b.bucket_type == "module" and b.slug == "root-module" for b in result.buckets
    )


def test_recursive_nav_builder_supports_three_levels(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    output_dir = repo_root / "docs"
    output_dir.mkdir()

    overview = DocBucket(
        bucket_type="system",
        title="Overview",
        slug="overview",
        section="Overview",
        description="Overview page",
        generation_hints={"is_introduction_page": True},
    )
    flash = DocBucket(
        bucket_type="architecture_component",
        title="Flash Attention",
        slug="flash-attention",
        section="Model Architecture > Attention > Flash Attention",
        description="Flash attention internals",
    )
    plan = DocPlan(
        buckets=[overview, flash],
        nav_structure={
            "Model Architecture > Attention > Flash Attention": ["flash-attention"]
        },
        skipped_files=[],
    )

    (output_dir / "flash-attention.mdx").write_text(
        "# Flash Attention\n", encoding="utf-8"
    )

    build_fumadocs_from_plan(
        repo_root,
        output_dir,
        {"project_name": "Demo", "site": {"repo_url": ""}},
        plan,
        has_openapi=False,
    )

    page_tree = (repo_root / "site" / "lib" / "page-tree.generated.ts").read_text(
        encoding="utf-8"
    )
    assert '"name": "Model Architecture"' in page_tree
    assert '"name": "Attention"' in page_tree
    assert '"name": "Flash Attention"' in page_tree
    assert '"url": "/flash-attention"' in page_tree


def test_prompt_templates_and_prompts_include_new_granularity_support() -> None:
    assert "training" in PROMPT_STYLE_TEMPLATES
    assert "architecture_component" in PROMPT_STYLE_TEMPLATES
    assert "data_pipeline" in PROMPT_STYLE_TEMPLATES
    assert "research_context" in PROMPT_STYLE_TEMPLATES
    assert "repo_profile" in CLASSIFY_PROMPT
    assert "{repo_profile}" in PROPOSE_PROMPT


def test_scan_repo_collects_research_context(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text(
        "# NanoChat\n\n## Design History\n\nWhy the architecture changed.\n",
        encoding="utf-8",
    )
    (repo_root / "experiments.md").write_text(
        "# Experiments\n\n## Ablations\n\nLoss and optimizer findings.\n",
        encoding="utf-8",
    )
    (repo_root / "train.py").write_text("def train():\n    pass\n", encoding="utf-8")

    scan = scan_repo(repo_root, {"exclude": [], "include": []})

    assert "README.md" in scan.doc_contexts
    kinds = {item["kind"] for item in scan.research_contexts}
    assert "design_history" in kinds
    assert "experiment_log" in kinds


def test_topic_candidates_use_code_and_doc_context() -> None:
    scan = _make_scan(
        file_summaries={"train.py": "train", "model.py": "model"},
        parsed_files={
            "train.py": _parsed_file(
                "train.py",
                imports=["torch.optim", "dataset"],
                symbols=[
                    Symbol(
                        name="train_loop",
                        kind="function",
                        signature="def train_loop():",
                    )
                ],
            ),
            "model.py": _parsed_file(
                "model.py",
                imports=["torch.nn"],
                symbols=[
                    Symbol(
                        name="Transformer", kind="class", signature="class Transformer:"
                    )
                ],
            ),
        },
    )
    scan.research_contexts = [
        {
            "kind": "glossary",
            "title": "Glossary",
            "file_path": "docs/glossary.md",
            "summary": "Terms for model, optimizer, and evaluation.",
            "headings": ["Glossary"],
        }
    ]
    candidates = _derive_topic_candidates(
        scan,
        {"repo_profile": {"primary_type": "research_training"}},
    )

    titles = {item["title"] for item in candidates}
    assert "Model Architecture" in titles
    assert "Training" in titles
    assert "Glossary" in titles


def test_normalize_tokens_preserves_expected_token_shapes() -> None:
    tokens = _normalize_tokens(
        "src/train_loop-v2.py",
        "TransformerBlock HTTPClient API + helpers",
        "__init__ x io",
    )

    assert "train_loop-v2" in tokens
    assert "transformerblock" in tokens
    assert "httpclient" in tokens
    assert "helpers" in tokens
    assert "io" not in tokens


def test_refine_proposal_merges_low_value_utilities_and_http_noise() -> None:
    proposal = {
        "buckets": [
            {
                "bucket_type": "utility-random",
                "title": "Randomness Utilities",
                "slug": "randomness-utilities",
                "section": "Utilities",
                "candidate_files": ["random.py"],
                "coverage_targets": [],
                "required_sections": ["overview"],
                "required_diagrams": [],
                "generation_hints": {"prompt_style": "general"},
            },
            {
                "bucket_type": "utility-string",
                "title": "String Utilities",
                "slug": "string-utilities",
                "section": "Utilities",
                "candidate_files": ["string.py"],
                "coverage_targets": [],
                "required_sections": ["overview"],
                "required_diagrams": [],
                "generation_hints": {"prompt_style": "general"},
            },
            {
                "bucket_type": "http-client-integration",
                "title": "HTTP Client Integrations",
                "slug": "http-client-integrations",
                "section": "Integrations",
                "candidate_files": ["fetch_data.py"],
                "coverage_targets": [],
                "required_sections": ["overview"],
                "required_diagrams": [],
                "generation_hints": {"prompt_style": "integration"},
            },
            {
                "bucket_type": "data-pipeline",
                "title": "Data Pipeline",
                "slug": "data-pipeline",
                "section": "Data Pipeline",
                "candidate_files": ["dataset.py"],
                "coverage_targets": ["data loading"],
                "required_sections": ["overview"],
                "required_diagrams": [],
                "generation_hints": {"prompt_style": "data_pipeline"},
            },
        ],
        "nav_structure": {
            "Utilities": ["randomness-utilities", "string-utilities"],
            "Integrations": ["http-client-integrations"],
            "Data Pipeline": ["data-pipeline"],
        },
    }

    refined = _refine_proposal(
        proposal,
        _make_scan(),
        {"repo_profile": {"primary_type": "research_training"}},
    )

    titles = {bucket["title"] for bucket in refined["buckets"]}
    assert "Common Utilities & Configuration" in titles
    assert "HTTP Client Integrations" not in titles


def test_refine_bucket_ownership_trims_overview_bucket() -> None:
    overview = DocBucket(
        bucket_type="architecture",
        title="System Overview & Architecture",
        slug="system-overview",
        section="Overview",
        description="Overview",
        owned_files=[f"src/file_{idx}.py" for idx in range(12)],
        generation_hints={"is_introduction_page": True},
    )
    training = DocBucket(
        bucket_type="training-script",
        title="Training",
        slug="training",
        section="Training",
        description="Training",
        owned_files=["src/train.py"],
    )
    plan = DocPlan(
        buckets=[overview, training],
        nav_structure={"Overview": ["system-overview"], "Training": ["training"]},
        skipped_files=[],
    )
    parsed_files = {
        f"src/file_{idx}.py": _parsed_file(
            f"src/file_{idx}.py",
            imports=["shared"],
            symbols=[
                Symbol(name=f"helper_{idx}", kind="function", signature="def helper():")
            ],
        )
        for idx in range(12)
    }
    parsed_files["src/train.py"] = _parsed_file(
        "src/train.py",
        imports=["torch", "dataset"],
        symbols=[
            Symbol(name="train_loop", kind="function", signature="def train_loop():")
        ],
    )
    scan = _make_scan(
        file_summaries={path: "summary" for path in parsed_files},
        parsed_files=parsed_files,
    )

    refined = _refine_bucket_ownership(
        plan,
        scan,
        {"repo_profile": {"primary_type": "research_training"}},
    )

    overview_bucket = next(
        bucket for bucket in refined.buckets if bucket.slug == "system-overview"
    )
    assert len(overview_bucket.owned_files) <= 8


def test_inject_research_context_buckets_and_shape_nav() -> None:
    plan = DocPlan(
        buckets=[
            DocBucket(
                bucket_type="system",
                title="System Overview & Architecture",
                slug="system-overview",
                section="Overview",
                description="Overview",
                generation_hints={"is_introduction_page": True},
            ),
            DocBucket(
                bucket_type="utility-random",
                title="Randomness Utilities",
                slug="randomness-utilities",
                section="Utilities",
                description="Random helpers",
                owned_files=["random.py"],
            ),
        ],
        nav_structure={
            "Overview": ["system-overview"],
            "Utilities": ["randomness-utilities"],
        },
        skipped_files=[],
        classification={"repo_profile": {"primary_type": "research_training"}},
    )
    scan = _make_scan()
    scan.research_contexts = [
        {
            "kind": "glossary",
            "title": "Glossary",
            "file_path": "docs/glossary.md",
            "summary": "Project terms.",
            "headings": ["Glossary"],
        }
    ]

    with_context = _inject_research_context_buckets(
        plan,
        scan,
        {"repo_profile": {"primary_type": "research_training"}},
    )
    shaped = _shape_plan_nav(
        with_context, {"repo_profile": {"primary_type": "research_training"}}
    )

    sections = set(shaped.nav_structure.keys())
    assert "Research Context" in sections
    assert "Operations" in sections


def test_page_contracts_drive_validator_checks() -> None:
    bucket = DocBucket(
        bucket_type="training-script",
        title="Training Loop",
        slug="training-loop",
        section="Training",
        description="Training flow",
        owned_files=["train.py"],
    )
    plan = DocPlan(
        buckets=[bucket],
        nav_structure={"Training": ["training-loop"]},
        skipped_files=[],
    )
    scan = _make_scan(
        file_summaries={"train.py": "summary"},
        parsed_files={
            "train.py": _parsed_file(
                "train.py",
                imports=["torch"],
                symbols=[
                    Symbol(
                        name="train_loop",
                        kind="function",
                        signature="def train_loop():",
                    )
                ],
            )
        },
    )
    _apply_page_contracts(
        plan, scan, {"repo_profile": {"primary_type": "research_training"}}
    )
    validator = PageValidator(Path("."), scan)
    content = "# Training Loop\n\n## Overview\nMentions train.py but not the expected details."
    result = validator.validate(content, bucket)

    assert (
        "training loop" in ", ".join(result.missing_contract_concepts).lower()
        or result.missing_contract_concepts
    )


def test_benchmark_score_plan_flags_noise_and_orphans() -> None:
    overview = DocBucket(
        bucket_type="architecture",
        title="System Overview & Architecture",
        slug="system-overview",
        section="Overview",
        description="Overview",
        owned_files=["a.py", "b.py", "c.py", "d.py", "e.py", "f.py"],
        generation_hints={"is_introduction_page": True},
    )
    utility = DocBucket(
        bucket_type="utility-random",
        title="Randomness Utilities",
        slug="randomness-utilities",
        section="Operations",
        description="Helpers",
    )
    plan = DocPlan(
        buckets=[overview, utility],
        nav_structure={
            "Overview": ["system-overview"],
            "Operations": ["randomness-utilities"],
        },
        skipped_files=[],
        orphaned_files=["x.py", "y.py"],
        classification={"repo_profile": {"primary_type": "research_training"}},
    )

    score, details, notes = score_plan(
        plan,
        {
            "expected_primary_type": "research_training",
            "required_sections": ["Overview", "Training"],
            "required_titles": [["Model", "Architecture"]],
            "forbidden_titles": ["Utilities"],
            "max_orphaned": 0,
            "max_overview_files": 4,
        },
    )

    assert score < 100
    assert details["noise_suppression"] < 1.0
    assert any("orphaned" in note or "forbidden" in note for note in notes)
