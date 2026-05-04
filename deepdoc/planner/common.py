from __future__ import annotations
from collections import defaultdict
import fnmatch
import json
import os
from pathlib import Path
import re
import time
from typing import Any
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)
from rich.table import Table
from ..call_graph import build_call_graph
from ..llm import LLMClient
from ..parser import parse_file, supported_extensions
from ..parser.api_detector import APIEndpoint, detect_endpoints
from ..parser.base import ParsedFile
from ..parser.routes import resolve_repo_endpoints
from ..scanner import discover_debug_signals
from ..source_metadata import (
    classify_source_kind,
    endpoint_publication_decision,
    infer_publication_tier,
    source_kind_counts,
    supporting_section_for_kinds,
)
from ..v2_models import (
    DocBucket,
    DocPlan,
    RepoScan,
    endpoint_owned_files,
    tracked_bucket_files,
)

console = Console()

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]+")

PROPOSAL_BUCKET_TOKEN_CACHE: dict[int, set[str]] = {}


def _normalize_tokens(*values: str) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        for token in TOKEN_RE.findall(value or ""):
            normalized = token.lower().strip("_-+")
            if len(normalized) < 3 or normalized in STOPWORD_TOKENS:
                continue
            tokens.add(normalized)
    return tokens

ENTRY_POINT_NAMES = {
    "main.py",
    "app.py",
    "server.py",
    "manage.py",
    "wsgi.py",
    "asgi.py",
    "index.ts",
    "index.js",
    "server.ts",
    "server.js",
    "app.ts",
    "app.js",
    "main.go",
    "cmd",
    "main.ts",
    "main.js",
    "artisan",
    "index.php",
}

CONFIG_FILE_PATTERNS = {
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    ".env.example",
    ".env.sample",
    "Makefile",
    "Taskfile.yml",
    "package.json",
    "tsconfig.json",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "go.mod",
    "composer.json",
    ".github",
    "Procfile",
    "vercel.json",
    "netlify.toml",
    "nginx.conf",
    "supervisord.conf",
    "requirements.txt",
    "requirements-dev.txt",
}

FRAMEWORK_INDICATORS = {
    "express": ["express()", "require('express')", "from 'express'"],
    "fastify": ["fastify()", "require('fastify')", "from 'fastify'"],
    "nestjs": ["@nestjs/", "@Controller", "@Injectable"],
    "vue": ["from 'vue'", 'from "vue"', "createApp(", "defineComponent(", "<template"],
    "django": ["django.conf", "urlpatterns", "INSTALLED_APPS"],
    "laravel": ["Route::", "Illuminate\\", "artisan"],
    "gin": ["gin.Default()", "gin.New()", "gin.Engine"],
    "echo": ["echo.New()", "echo.Echo"],
    "fiber": ["fiber.New()", "fiber.App"],
    "falcon": ["falcon.App", "falcon.API"],
}

DOC_CONTEXT_FILENAMES = {
    "readme.md",
    "readme.mdx",
    "changelog.md",
    "history.md",
    "design.md",
    "architecture.md",
    "glossary.md",
    "notes.md",
    "experiments.md",
}

CLASSIFY_SYSTEM = """You are a senior software architect analyzing a repository. You are given pre-computed topology clusters derived from the call graph -- groups of files that are already structurally related. Your job is to NAME each cluster (give it a human-readable domain name and nav section) and identify cross-cutting concerns, integrations, and the repo profile. Respond with valid JSON only -- no markdown, no explanation.
"""

CLASSIFY_PROMPT = """Analyze this repository and name its topology clusters.

## Repository Overview
- **Languages**: {languages}
- **Frameworks**: {frameworks}
- **Total source files**: {total_files}
- **API endpoints found**: {endpoint_count}
- **Entry points**: {entry_points}
- **Config files**: {config_files}

## Topology Clusters (derived from call graph -- groups are already structurally correct)
{topology_clusters}

## File Summaries (for context on files not covered by clusters)
{file_summaries}

## API Endpoints
{endpoints}

---

For each cluster give it a domain name and a nav section.
For the foundational cluster, give it an appropriate infrastructure name.

Return JSON:
{{
  "cluster_names": {{
    "<cluster_id>": {{
      "name": "Human-readable domain name, e.g. Order Management",
      "section": "Nav section name, e.g. Order Management or Payments > Gateway",
      "description": "One sentence: what this cluster does",
      "nav_position": "primary|secondary|infrastructure"
    }}
  }},
  "setup_artifacts": ["Dockerfile", "docker-compose.yml", ...],
  "test_artifacts": ["tests/...", ...],
  "deploy_artifacts": [".github/workflows/...", "Procfile", ...],
  "integration_signals": [
    {{
      "name": "short identifier like vinculum or juspay",
      "evidence": ["import VinculumClient from...", "VINCULUM_API_URL in .env", ...],
      "files": ["path/to/vinculum_client.py", "path/to/sync_task.py"]
    }}
  ],
  "cross_cutting": [
    {{
      "concern": "authentication|logging|error_handling|caching|database|rate_limiting|...",
      "files": ["path/to/middleware/auth.py", ...]
    }}
  ],
  "giant_files": ["path/to/huge_controller.py"],
  "repo_profile": {{
    "primary_type": "backend_service|falcon_backend|framework_library|frontend_admin|platform_monorepo|cli_tooling|research_training|hybrid|other",
    "secondary_traits": ["has_frontend", "has_cli", "has_training_scripts", "has_evaluation", "has_ci_release", "has_docker", "has_database", "has_public_api", "has_pipeline_stages", "uses_falcon", "uses_django", "uses_express", "uses_fastify", "uses_laravel", "uses_vue"],
    "confidence": "high|medium|low",
    "evidence": "brief justification"
  }}
}}

Rules:
- cluster_names: name EVERY cluster id listed above, including "foundational".
- section: use product/domain language -- "Order Management", "Payment Processing",
  "Authentication", "Infrastructure & Shared Code". NOT technical-layer names
  like "Services", "Controllers", "Core Workflows".
- nav_position: "primary" for user-facing entry-point clusters, "secondary" for
  internal feature clusters, "infrastructure" for the foundational cluster.
- integration_signals: HTTP clients, SDK imports, env vars with API/URL/KEY suffixes,
  webhook handlers, named wrappers, queue tasks that sync with external systems.
- cross_cutting: shared concerns spanning multiple features (auth, logging, caching, etc.).
- giant_files: any source file with {giant_file_threshold}+ lines.
- repo_profile: infer from frameworks, entry points, and file patterns.
  falcon_backend: Falcon app, add_route calls, responder classes, middleware chain.
  backend_service: route handlers, middleware, request/response cycles, REST/GraphQL.
  framework_library: reusable APIs, rendering, plugins, parsers, developer-facing abstractions.
  frontend_admin: UI/component/state-heavy admin or frontend applications.
  platform_monorepo: multiple packages, build orchestration, shared infrastructure.
  cli_tooling: CLI-first repos, internal tooling, automation, developer workflow surfaces.
  research_training: training loops, model definitions, optimizers, dataloaders, eval scripts.
  hybrid: no single shape dominates.
  other: none of the above clearly dominates.
"""

PROPOSE_SYSTEM = """You are a senior documentation architect. Given a repository with pre-named topology clusters, propose documentation buckets for each cluster. The nav section names come from the cluster naming step -- do NOT invent new section names. Propose bucket granularity (how many pages a cluster needs) and what each page covers. Respond with valid JSON only -- no markdown, no explanation.

bucket_type is a FREE-FORM label. Common examples: "architecture", "setup", "feature", "endpoint-family", "integration", "database", "deployment", "testing", "cli-commands", "sdk-module", "plugin", "pipeline-stage", "package", "middleware", "auth", "config" -- but invent your own if the repo needs it.

Each bucket MUST include a "generation_hints" object with these flags (set true only when applicable):
- include_endpoint_detail: this bucket documents API endpoints
- is_endpoint_ref: single-endpoint reference page (OpenAPI pages only)
- is_endpoint_family: groups related endpoints (all /orders/* routes)
- include_openapi: inject OpenAPI spec context when generating
- include_database_context: inject DB schema, ER diagrams, model definitions
- include_integration_detail: full external-system integration context
- is_introduction_page: landing/overview page (becomes index.mdx)
- prompt_style: one of "system", "feature", "endpoint", "endpoint_ref",   "integration", "database", "training", "architecture_component",   "data_pipeline", or "general"
- icon: Heroicon name (e.g. "server", "bolt", "globe-alt", "database",   "puzzle-piece", "book-open", "command-line", "cube", "cog")

Rules:
- SECTION NAMES: use the section names from cluster_names exactly.   Do NOT invent new sections. You may use "Parent > Child" sub-sections   within a cluster's section if the cluster is large.
- FLOW PAGES: do NOT create separate "Core Workflows" or "Flow" pages.   Flow content (call chain, sequence diagram, side effects) belongs inside   the domain bucket that owns those entry-point files. Set   required_diagrams: ["sequence_diagram"] on any bucket with entry-point files.
- PREFER DEPTH: fewest buckets that cover every concept deeply. One rich page   beats three thin pages.
- NO DUPLICATION: each concept appears in exactly ONE bucket.
- INTEGRATION BUCKETS: one page per external system (unless 5+ dedicated files).
- BUCKET COUNT: Small (<20 files): ~8-15, Medium (20-80): ~15-25, Large (80+): ~25-40.   Never invent filler pages to hit a number.
- AVOID catch-all buckets: no "Utilities", "Helpers", "Common Logic", "Miscellaneous".
- Group by BUSINESS WORKFLOW or LOGICAL CONCERN, not by file path.
- Every bucket MUST have required_sections and required_diagrams specific to its content.
- DEMOTION: do NOT create single-file utility buckets unless the file has a   substantial algorithm or subsystem.
"""

PROPOSE_PROMPT = """Based on these named topology clusters, propose documentation buckets.

## Named Clusters (section names are FIXED -- use them verbatim)
{named_clusters}

## API Endpoints ({endpoint_count} total)
{endpoints}

## Integration Signals
{integration_signals}

## Cross-Cutting Concerns
{cross_cutting}

## Giant Files (need decomposition)
{giant_files}

## Database / Schema Info
{database_info}

## Research / Markdown Context
{research_context}

## Repo Profile
{repo_profile}

## Constraints
{max_pages_instruction}
- Must include: 1 introduction/overview bucket (is_introduction_page: true)
- If setup artifacts exist, include a setup/getting-started bucket
- If database models detected: include a database bucket with   include_database_context: true, prompt_style: "database",   required_sections: ["er_diagram", "table_definitions", "relationships", "migrations"]
- Endpoint-entry-point buckets MUST have required_diagrams: ["sequence_diagram"]   to embed the call flow inline -- no separate flow pages
- Group by business workflow, NOT file directories
- Endpoint family buckets group by resource family, NOT one-per-route

Return JSON:
{{
  "buckets": [
    {{
      "bucket_type": "your-chosen-category-label",
      "title": "Page Title",
      "slug": "page-slug",
      "section": "Exact section name from named_clusters above",
      "cluster_id": "the cluster_id this bucket belongs to",
      "description": "What this page covers",
      "rationale": "Why this bucket exists and what it groups",
      "candidate_files": ["path/to/file.py", ...],
      "candidate_domains": ["orders", "payments"],
      "depends_on": ["other-bucket-slug"],
      "required_sections": ["overview", "main_workflows", "state_transitions", ...],
      "required_diagrams": ["sequence_diagram", "er_diagram", ...],
      "coverage_targets": ["OrderController checkout flow", "payment auth", ...],
      "generation_hints": {{
        "include_endpoint_detail": false,
        "is_endpoint_ref": false,
        "is_endpoint_family": false,
        "include_openapi": false,
        "include_database_context": false,
        "include_integration_detail": false,
        "is_introduction_page": false,
        "prompt_style": "system|feature|endpoint|integration|database|training|architecture_component|data_pipeline|general",
        "icon": "heroicon-name"
      }}
    }}
  ]
}}

Repo profile: {repo_profile}
"""

ASSIGN_SYSTEM = """\
You are a documentation planner finalizing file assignments. Given proposed \
documentation buckets and a full file inventory, assign every source file to at \
least one bucket. Respond with valid JSON only.

Rules:
- EVERY source file must be assigned to at least one bucket or explicitly skipped.
- A file CAN belong to multiple buckets if it serves multiple purposes.
- Only skip: pure test files, auto-generated files, type-only files with no logic.
- For giant files, assign to the bucket that covers its PRIMARY feature cluster. \
  Giant-file decomposition happens later in the pipeline.
- artifact_refs: config/env/deploy/test files relevant to this bucket.
- owned_symbols: specific classes/functions from shared files (for focused docs).
- For buckets with is_endpoint_ref hint, assign the handler file and \
  the specific handler function as owned_symbols.
- For buckets with include_database_context hint, assign model definition files, \
  migration files, and schema files.
"""

ASSIGN_PROMPT = """\
Finalize file assignments for these documentation buckets.

## Proposed Buckets
{proposed_buckets}

## All Source Files (must all be assigned or skipped)
{all_files}

## API Endpoints
{endpoints}

## Giant Files (assign to most relevant bucket, decomposition happens later)
{giant_files}

## Setup/Config Artifacts
{setup_artifacts}

---

Return JSON:
{{
  "buckets": [
    {{
      "slug": "bucket-slug",
      "owned_files": ["path/to/file.py", ...],
      "owned_symbols": ["ClassName.method_name", "function_name", ...],
      "artifact_refs": ["Dockerfile", ".env.example", ...],
      "priority": 0
    }}
  ],
  "skipped_files": ["test/...", "types/index.d.ts", ...],
  "file_to_buckets": {{
    "path/to/file.py": ["bucket-slug-1", "bucket-slug-2"]
  }}
}}

Important:
- Every file in the source file list MUST appear either in a bucket's owned_files \
  or in skipped_files.
- owned_symbols is optional but encouraged for large shared files — it tells the \
  generator which parts of a file are relevant to this specific bucket.
- priority: 0 = generate first (overview/architecture), higher = later.
"""

STOPWORD_TOKENS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "into",
    "file",
    "files",
    "module",
    "modules",
    "page",
    "pages",
    "core",
    "system",
    "logic",
    "utils",
    "utility",
    "common",
    "service",
    "services",
    "workflow",
    "workflows",
    "overview",
    "architecture",
}

PROFILE_TOPIC_TEMPLATES: dict[str, list[tuple[str, list[str], str]]] = {
    "research_training": [
        (
            "Model Architecture",
            [
                "model",
                "transformer",
                "attention",
                "flash",
                "layer",
                "embedding",
                "kv",
                "float8",
                "fp8",
                "quant",
            ],
            "model",
        ),
        (
            "Optimization",
            [
                "optim",
                "optimizer",
                "adam",
                "muon",
                "schedule",
                "scheduler",
                "lr",
                "weight_decay",
            ],
            "optimization",
        ),
        (
            "Training",
            [
                "train",
                "trainer",
                "checkpoint",
                "loss",
                "dist",
                "ddp",
                "backward",
                "gradient",
            ],
            "training",
        ),
        (
            "Data Pipeline",
            [
                "data",
                "dataset",
                "dataloader",
                "tokenizer",
                "parquet",
                "preprocess",
                "conversation",
                "shard",
                "pack",
            ],
            "data_pipeline",
        ),
        (
            "Evaluation",
            ["eval", "metric", "benchmark", "score", "report", "validate"],
            "evaluation",
        ),
        (
            "Inference & Runtime",
            [
                "infer",
                "generate",
                "sampling",
                "chat",
                "serve",
                "cache",
                "runtime",
                "stats",
            ],
            "inference",
        ),
        ("Interfaces", ["cli", "command", "api", "web", "ui"], "interfaces"),
        (
            "Research Context",
            ["experiment", "ablation", "glossary", "history", "design", "notes"],
            "research_context",
        ),
    ],
    "backend_api": [
        (
            "Architecture",
            ["middleware", "auth", "handler", "service", "route", "controller"],
            "architecture",
        ),
        (
            "Domain Flows",
            ["order", "payment", "user", "inventory", "shipping", "checkout"],
            "domain",
        ),
        ("API", ["api", "endpoint", "request", "response", "schema"], "api"),
        (
            "Integrations",
            ["client", "provider", "gateway", "webhook", "sync"],
            "integration",
        ),
        (
            "Data Layer",
            ["model", "schema", "migration", "repository", "orm"],
            "data_layer",
        ),
        (
            "Operations",
            ["logging", "metric", "health", "deploy", "config", "queue"],
            "operations",
        ),
    ],
    "backend_service": [
        (
            "Architecture",
            ["middleware", "auth", "handler", "service", "route", "controller"],
            "architecture",
        ),
        (
            "Domain Flows",
            ["order", "payment", "user", "inventory", "shipping", "checkout"],
            "domain",
        ),
        ("API", ["api", "endpoint", "request", "response", "schema"], "api"),
        (
            "Integrations",
            ["client", "provider", "gateway", "webhook", "sync"],
            "integration",
        ),
        (
            "Data Layer",
            ["model", "schema", "migration", "repository", "orm"],
            "data_layer",
        ),
        (
            "Operations",
            ["logging", "metric", "health", "deploy", "config", "queue"],
            "operations",
        ),
    ],
    "falcon_backend": [
        (
            "Falcon Runtime",
            ["falcon", "add_route", "middleware", "auth", "translator"],
            "falcon_runtime",
        ),
        (
            "Domain Flows",
            ["order", "payment", "user", "inventory", "shipping", "checkout"],
            "domain",
        ),
        ("API", ["api", "endpoint", "request", "response", "resource"], "api"),
        ("Services", ["service", "controller", "handler", "sync", "task"], "services"),
        (
            "Data Layer",
            ["model", "schema", "migration", "repository", "orm"],
            "data_layer",
        ),
        (
            "Operations",
            ["logging", "metric", "deploy", "config", "queue", "celery"],
            "operations",
        ),
    ],
    "monorepo_product": [
        ("Monorepo Structure", ["package", "workspace", "repo", "shared"], "structure"),
        ("Runtime", ["runtime", "worker", "execution", "engine", "process"], "runtime"),
        (
            "API & Services",
            ["api", "server", "service", "handler", "controller"],
            "api_services",
        ),
        ("Frontend", ["component", "ui", "canvas", "editor", "state"], "frontend"),
        ("Configuration", ["config", "env", "docker", "build"], "configuration"),
        ("Release", ["release", "ci", "workflow", "version"], "release"),
    ],
    "platform_monorepo": [
        ("Monorepo Structure", ["package", "workspace", "repo", "shared"], "structure"),
        ("Runtime", ["runtime", "worker", "execution", "engine", "process"], "runtime"),
        (
            "API & Services",
            ["api", "server", "service", "handler", "controller"],
            "api_services",
        ),
        ("Frontend", ["component", "ui", "canvas", "editor", "state"], "frontend"),
        ("Configuration", ["config", "env", "docker", "build"], "configuration"),
        ("Release", ["release", "ci", "workflow", "version"], "release"),
    ],
    "framework_library": [
        (
            "Architecture",
            ["architecture", "parser", "render", "engine", "plugin"],
            "architecture",
        ),
        ("Core API", ["api", "config", "render", "layout", "detect"], "core_api"),
        (
            "Framework Surfaces",
            ["diagram", "component", "syntax", "extension"],
            "framework_surface",
        ),
        ("Development", ["test", "build", "ci", "quality", "bundle"], "development"),
        ("Ecosystem", ["docs", "integration", "plugin", "community"], "ecosystem"),
    ],
    "frontend_admin": [
        ("Overview", ["overview", "architecture", "app"], "overview"),
        ("Frontend", ["component", "ui", "page", "state", "router"], "frontend"),
        ("Data & API", ["api", "query", "mutation", "fetch", "client"], "data_api"),
        ("Operations", ["config", "build", "deploy", "env"], "operations"),
        ("Testing", ["test", "cypress", "playwright", "spec"], "testing"),
    ],
    "cli_tooling": [
        ("Overview", ["overview", "architecture", "workflow"], "overview"),
        ("CLI", ["cli", "command", "args", "flags", "dispatch"], "cli"),
        ("Pipeline", ["pipeline", "generate", "update", "scan", "plan"], "pipeline"),
        ("Integrations", ["provider", "api", "client", "llm"], "integration"),
        ("Operations", ["config", "build", "deploy", "release"], "operations"),
    ],
    "hybrid": [
        ("Architecture", ["architecture", "runtime", "workflow"], "architecture"),
        ("Runtime & Services", ["api", "service", "handler", "controller"], "runtime"),
        ("Frontend", ["component", "ui", "page", "state"], "frontend"),
        ("Data Layer", ["model", "schema", "migration", "repository"], "data_layer"),
        ("Operations", ["config", "deploy", "build", "ci", "queue"], "operations"),
    ],
}

DECOMPOSE_SYSTEM = """\
You are a documentation architect. Given a broad documentation bucket covering \
multiple concepts, decompose it into focused sub-topics. Each sub-topic becomes \
its own documentation page. Respond with valid JSON only.

Rules:
- Each sub-topic should cover ONE specific concept, class, algorithm, or workflow.
- Produce 2-4 sub-topics per bucket. Prefer 2 over 4. Only decompose if the \
  sub-topics are genuinely distinct workflows or subsystems — NOT just different \
  aspects of the same concept.
- Before decomposing, check: could a single well-written page cover all these files \
  coherently? If yes, return an empty sub_topics array to keep the bucket intact.
- If the bucket covers a single integration, external system, or tightly-coupled \
  workflow, do NOT decompose it — a single deep page is better.
- Sub-topic titles must be specific and descriptive: \
  "Attention Mechanisms and Flash Attention" not "Attention Stuff".
- Each file should have ONE primary sub-topic owner. Shared files (configs, base \
  classes, common utilities) MAY appear in multiple sub-topics.
- Do NOT create single-file sub-topics unless that file contains a substantial, \
  distinct concept worth its own page.
- Do NOT create sub-topics that substantially overlap with existing buckets listed \
  below. If a sub-topic would duplicate another bucket, omit it.
- Slugs must be unique and URL-safe (lowercase, hyphens, no special chars).
"""

DECOMPOSE_PROMPT = """\
Decompose this broad bucket into focused sub-topics — but ONLY if the sub-topics \
are genuinely distinct. If the bucket is cohesive, return an empty sub_topics array.

## Bucket to Decompose
- Title: {title}
- Section: {section}
- Type: {bucket_type}
- Description: {description}

## Files ({file_count} total)
{file_list}

## File Details
{file_summaries}

## Other Existing Buckets (do NOT create sub-topics that overlap with these)
{existing_buckets}

## Repo Profile: {repo_profile}

Return JSON:
{{
  "sub_topics": [
    {{
      "title": "Specific Concept Name",
      "slug": "concept-slug",
      "description": "What this sub-topic covers — one sentence",
      "owned_files": ["file1.py", "file2.py"],
      "owned_symbols": ["ClassName", "function_name"],
      "required_sections": ["overview", "implementation_details", "usage_patterns"],
      "required_diagrams": ["relevant_diagram_type"],
      "prompt_style": "system|feature|training|architecture_component|data_pipeline|general"
    }}
  ],
  "nav_section": "{section} > Suggested Parent Label",
  "keep_parent_overview": true
}}

Important:
- Shared files (configs, base classes) may appear in multiple sub-topics.
- Every file from the bucket must appear in at least one sub-topic's owned_files.
- nav_section uses ">" for nested navigation. Use 2 levels by default; use 3 if
  the concept hierarchy is clearly that deep.
- keep_parent_overview: set true if the parent topic deserves a summary/overview
  page in addition to the sub-topic pages. Set false if the parent title is too
  generic to be a useful page on its own.
"""


__all__ = [k for k in list(globals().keys()) if not k.startswith('__')]
