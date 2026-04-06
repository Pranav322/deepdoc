from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any
from rich.console import Console
from ..llm import LLMClient
from ..parser.base import ParsedFile, Symbol
from ..source_metadata import classify_integration_party

console = Console()

IMPORT_FROM_RE = re.compile(r"from\s+([\w.]+)\s+import")

IMPORT_PLAIN_RE = re.compile(r"import\s+([\w.]+)")

JS_FROM_RE = re.compile(r"""from\s+['"]([^'"]+)['"]""")

JS_REQUIRE_RE = re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""")

GO_IMPORT_RE = re.compile(r'"([^"]+)"')

PHP_USE_RE = re.compile(r"use\s+([\w\\]+)")

FILE_EXT_RE = re.compile(r"\.(py|ts|js|tsx|jsx|go|php|mjs|cjs)$")

WORD_TOKEN_RE = re.compile(r"[\w]+")

@dataclass
class SymbolCluster:
    """A group of related symbols within a giant file."""

    cluster_name: str  # e.g. "checkout", "cancel_refund"
    description: str
    symbols: list[str] = field(default_factory=list)  # symbol names
    line_ranges: list[tuple[int, int]] = field(
        default_factory=list
    )  # (start, end) per symbol
    related_imports: list[str] = field(default_factory=list)

@dataclass
class GiantFileAnalysis:
    """Result of decomposing a giant file into feature clusters."""

    file_path: str
    line_count: int
    total_symbols: int
    clusters: list[SymbolCluster] = field(default_factory=list)

@dataclass
class EvidenceUnit:
    """A single piece of evidence for an endpoint bundle."""

    file_path: str
    role: str  # "handler", "service", "model", "validator", "task", "config", "test", "auth"
    symbols: list[str] = field(default_factory=list)
    relevance: float = 1.0  # 0.0 to 1.0

@dataclass
class EndpointBundle:
    """Evidence bundle for an endpoint or endpoint family."""

    endpoint_family: str  # e.g. "orders" or "POST /orders/process"
    methods_paths: list[str]  # ["POST /orders", "GET /orders/:id"]
    handler_file: str
    handler_symbols: list[str]
    evidence: list[EvidenceUnit] = field(default_factory=list)
    integration_edges: list[str] = field(
        default_factory=list
    )  # integration names touched

MAX_EVIDENCE_DEPTH = 2

MAX_EVIDENCE_FILES = 15

@dataclass
class IntegrationCandidate:
    """A raw integration signal before normalization."""

    signal_type: str  # "http_client", "sdk_import", "env_var", "webhook", "queue_task", "vendor_constant"
    name_hint: str  # best guess at the integration name
    file_path: str
    evidence: str  # the actual line/import/pattern found
    confidence: float = 0.5

@dataclass
class IntegrationIdentity:
    """A normalized integration after LLM grouping."""

    name: str  # canonical name: "vinculum", "juspay", "delivery_partners"
    display_name: str  # human-readable: "Vinculum Warehouse Management"
    description: str
    files: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    is_substantial: bool = True  # True = standalone page; False = embed in feature page
    party: str = "third_party"

@dataclass
class ModelFileInfo:
    """Info about a model/schema definition file."""

    file_path: str
    orm_framework: str  # django, sqlalchemy, prisma, typeorm, sequelize, eloquent, mongoose, gorm, generic
    model_names: list[str] = field(default_factory=list)  # detected class/table names
    is_migration: bool = False

@dataclass
class DatabaseGroup:
    """Deterministic documentation grouping for related model/schema files."""

    key: str
    label: str
    file_paths: list[str] = field(default_factory=list)
    model_names: list[str] = field(default_factory=list)
    orm_frameworks: list[str] = field(default_factory=list)
    external_refs: list[str] = field(default_factory=list)

@dataclass
class GraphQLInterface:
    """Detected GraphQL schema surface."""

    name: str
    file_path: str
    kind: str  # object_type | mutation | schema | resolver | field
    fields: list[str] = field(default_factory=list)
    related_types: list[str] = field(default_factory=list)

@dataclass
class KnexArtifact:
    """Knex schema/query evidence extracted from JS/TS files."""

    file_path: str
    artifact_type: str  # schema | query
    table_name: str = ""
    columns: list[str] = field(default_factory=list)
    foreign_keys: list[str] = field(default_factory=list)
    query_patterns: list[str] = field(default_factory=list)

@dataclass
class RuntimeTask:
    """Background task or job definition."""

    name: str
    file_path: str
    runtime_kind: str  # celery | scheduled_job
    decorator: str = ""
    queue: str = ""
    retry_policy: str = ""
    schedule_sources: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    producer_files: list[str] = field(default_factory=list)
    linked_endpoints: list[str] = field(default_factory=list)

@dataclass
class RuntimeScheduler:
    """Scheduler or cron registration."""

    name: str
    file_path: str
    scheduler_type: str  # beat | node_cron | crontab
    cron: str = ""
    invoked_targets: list[str] = field(default_factory=list)
    linked_endpoints: list[str] = field(default_factory=list)

@dataclass
class RealtimeConsumer:
    """Realtime/websocket surface such as a Django Channels consumer."""

    name: str
    file_path: str
    consumer_type: str
    routes: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    auth_hints: list[str] = field(default_factory=list)

@dataclass
class RuntimeScan:
    """Runtime/background-job/realtime discovery results."""

    tasks: list[RuntimeTask] = field(default_factory=list)
    schedulers: list[RuntimeScheduler] = field(default_factory=list)
    realtime_consumers: list[RealtimeConsumer] = field(default_factory=list)

@dataclass
class ConfigImpact:
    """A concrete config/env key and the code surfaces it influences."""

    key: str
    kind: str  # env_var | setting | config_key
    file_path: str
    default_value: str = ""
    related_files: list[str] = field(default_factory=list)
    related_endpoints: list[str] = field(default_factory=list)

@dataclass
class DatabaseScan:
    """Database/schema discovery results."""

    model_files: list[ModelFileInfo] = field(default_factory=list)
    migration_files: list[str] = field(default_factory=list)
    schema_files: list[str] = field(
        default_factory=list
    )  # prisma.schema, schema.graphql, etc.
    orm_framework: str = ""  # primary detected ORM
    orm_frameworks: list[str] = field(default_factory=list)
    total_models: int = 0
    groups: list[DatabaseGroup] = field(default_factory=list)
    graphql_interfaces: list[GraphQLInterface] = field(default_factory=list)
    knex_artifacts: list[KnexArtifact] = field(default_factory=list)

@dataclass
class ArtifactScan:
    """Categorized artifact discovery results."""

    setup_artifacts: list[str] = field(default_factory=list)
    deploy_artifacts: list[str] = field(default_factory=list)
    test_artifacts: list[str] = field(default_factory=list)
    ci_artifacts: list[str] = field(default_factory=list)
    ops_artifacts: list[str] = field(default_factory=list)
    database_scan: DatabaseScan | None = None

SETUP_PATTERNS = [
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-prod.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "Pipfile",
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "go.mod",
    "go.sum",
    "composer.json",
    "composer.lock",
    ".env.example",
    ".env.sample",
    ".env.template",
    "Makefile",
    "Taskfile.yml",
    "justfile",
    "tsconfig.json",
    "babel.config",
    "webpack.config",
    ".eslintrc",
    ".prettierrc",
    ".editorconfig",
]

DEPLOY_PATTERNS = [
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "docker-compose.prod.yml",
    "Procfile",
    "vercel.json",
    "netlify.toml",
    "fly.toml",
    "nginx.conf",
    "supervisord.conf",
    "gunicorn.conf",
    "Vagrantfile",
    "terraform",
    ".tf",
    "k8s",
    "kubernetes",
    "helm",
    "serverless.yml",
    "sam-template",
]

CI_PATTERNS = [
    ".github/workflows",
    ".github/actions",
    ".gitlab-ci.yml",
    "Jenkinsfile",
    ".circleci",
    ".travis.yml",
    "bitbucket-pipelines.yml",
    "azure-pipelines.yml",
    ".buildkite",
]

TEST_PATTERNS = [
    "pytest.ini",
    "conftest.py",
    "jest.config",
    "vitest.config",
    "karma.conf",
    ".nycrc",
    "phpunit.xml",
    "codecov.yml",
]

OPS_PATTERNS = [
    "crontab",
    "celery",
    "beat",
    "scheduler",
    "monitoring",
    "prometheus",
    "grafana",
    "sentry",
    "newrelic",
    "datadog",
    "logrotate",
    "fluentd",
    "filebeat",
]

@dataclass
class DebugSignal:
    """An observability / debug signal detected in the codebase."""

    signal_type: str  # "logger" | "exception_handler" | "health_endpoint" | "monitoring" | "retry" | "cache_keys" | "circuit_breaker"
    name: str
    file_path: str
    description: str
    patterns: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)

_LOG_RE = re.compile(
    r"""(?:logger|log|logging|LOG)\.(debug|info|warning|warn|error|critical|exception)\s*\(""",
    re.IGNORECASE,
)

_EXCEPT_RE = re.compile(r"except\s+([\w., ]+?)(?:\s+as\s+\w+)?:")

_MONITORING_RE = re.compile(
    r"""(?:newrelic|sentry|prometheus|statsd|datadog|honeycomb|opentelemetry|
          metrics\.|counter\.|histogram\.|gauge\.)""",
    re.IGNORECASE | re.VERBOSE,
)

_REDIS_KEY_RE = re.compile(
    r"""(?:cache|redis|r|client)\.(?:set|get|delete|exists|hset|hget|lpush|rpush)\s*\(\s*[f'"]([^'"]{3,80})""",
)

_RETRY_RE = re.compile(
    r"(?:max_retries|retry_backoff|autoretry_for|countdown|bind=True|retry\s*=\s*True)"
)

_CIRCUIT_RE = re.compile(r"(?:circuit.?breaker|fallback|bulkhead)", re.IGNORECASE)

_HEALTH_PATHS = frozenset(
    {"/health", "/ready", "/ping", "/status", "/liveness", "/readiness", "/healthz"}
)


__all__ = [k for k in list(globals().keys()) if not k.startswith('__')]
