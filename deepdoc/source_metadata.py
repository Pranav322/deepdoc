"""Shared source-kind and publication metadata helpers."""

from __future__ import annotations

from collections import Counter
from pathlib import Path


SOURCE_KIND_CORE = "product"
SOURCE_KIND_SUPPORTING = {
    "test",
    "fixture",
    "example",
    "generated",
    "docs",
    "config",
    "ops",
    "tooling",
}
LOW_TRUST_SOURCE_KINDS = {"test", "fixture", "example", "generated"}
HEADER_LIKE_SEGMENTS = {
    "authorization",
    "origin",
    "digest",
    "access-control-request-headers",
    "access-control-request-method",
    "convex-client",
    "svix-id",
    "svix-timestamp",
    "svix-signature",
}
FRAMEWORK_PRIORITIES = {
    "falcon": 100,
    "django": 90,
    "fastapi": 90,
    "flask": 85,
    "express": 80,
    "fastify": 80,
    "laravel": 75,
    "vue": 70,
    "go": 65,
    "nestjs": 10,
}


def classify_source_kind(rel_path: str) -> str:
    """Classify a repo-relative path into a coarse source kind."""
    normalized = rel_path.replace("\\", "/").strip("/")
    lowered = normalized.lower()
    parts = [part for part in lowered.split("/") if part]
    name = parts[-1] if parts else lowered

    if any(part in {"fixtures", "fixture"} for part in parts):
        return "fixture"
    if any(part in {"examples", "example", "samples", "sample", "demo", "demos"} for part in parts):
        return "example"
    if (
        any(part in {"tests", "test", "__tests__", "spec"} for part in parts)
        or name.startswith("test_")
        or name.endswith("_test.py")
        or ".spec." in lowered
        or ".test." in lowered
    ):
        return "test"
    if (
        any(part in {"generated", "gen", "__generated__"} for part in parts)
        or name.endswith((".g.dart", ".pb.go", ".gen.ts", ".generated.ts"))
        or "generated" in name
    ):
        return "generated"
    if (
        lowered.startswith("docs/")
        or name in {"readme.md", "readme.mdx", "changelog.md", "history.md", "glossary.md"}
        or any(token in name for token in ("readme", "changelog", "glossary", "notes", "history"))
    ):
        return "docs"
    if name in {
        "dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "requirements_python310.txt",
        "go.mod",
        "composer.json",
        ".env.example",
        ".env.sample",
        "vercel.json",
        "netlify.toml",
        "nginx.conf",
    }:
        return "config"
    if any(part in {".github", "ops", "deploy", "deployment", "helm", "terraform"} for part in parts):
        return "ops"
    if any(part in {"scripts", "script", "tools", "tooling", "bin"} for part in parts):
        return "tooling"
    return SOURCE_KIND_CORE


def source_kind_counts(paths: list[str], source_kind_by_file: dict[str, str]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for path in paths:
        counts[source_kind_by_file.get(path, classify_source_kind(path))] += 1
    return dict(counts)


def infer_publication_tier(
    paths: list[str],
    source_kind_by_file: dict[str, str],
    *,
    is_introduction_page: bool = False,
    is_endpoint_family: bool = False,
    is_endpoint_ref: bool = False,
) -> str:
    """Infer whether a page belongs in the core tree or supporting material."""
    if is_introduction_page or is_endpoint_family or is_endpoint_ref:
        return "core"

    counts = source_kind_counts(paths, source_kind_by_file)
    if not counts:
        return "core"

    core_count = counts.get(SOURCE_KIND_CORE, 0)
    supporting_count = sum(count for kind, count in counts.items() if kind in SOURCE_KIND_SUPPORTING)
    if supporting_count > core_count:
        return "supporting"
    return "core"


def supporting_section_for_kinds(kind_counts: dict[str, int]) -> str | None:
    """Map source-kind makeup to a supporting-material section."""
    if not kind_counts:
        return None
    if kind_counts.get("test"):
        return "Testing"
    if kind_counts.get("example") or kind_counts.get("fixture"):
        return "Examples"
    if kind_counts.get("generated"):
        return "Generated Artifacts"
    if kind_counts.get("tooling"):
        return "Internal Tools"
    if kind_counts.get("ops"):
        return "CI/CD and Release"
    if kind_counts.get("docs"):
        return "Design & Notes"
    if kind_counts.get("config"):
        return "Configuration"
    return None


def is_low_trust_source_kind(source_kind: str) -> bool:
    return source_kind in LOW_TRUST_SOURCE_KINDS


def repo_name_tokens(repo_root: Path) -> set[str]:
    name = repo_root.name.lower().replace("_", "-")
    tokens = {token for token in name.split("-") if token and len(token) > 2}
    return tokens


def classify_integration_party(name: str, repo_root: Path) -> str:
    """Best-effort classify an integration as first-party or third-party."""
    tokens = repo_name_tokens(repo_root)
    normalized = name.lower().replace("_", "-").strip("-")
    name_tokens = {token for token in normalized.split("-") if token and len(token) > 2}
    if tokens & name_tokens:
        return "first_party"
    return "third_party"


def endpoint_publication_decision(
    path: str,
    *,
    route_file: str = "",
    handler_file: str = "",
    framework: str = "",
    source_kind_by_file: dict[str, str] | None = None,
) -> tuple[bool, float, str]:
    """Return (publishable, confidence, reason) for an endpoint candidate."""
    source_kind_by_file = source_kind_by_file or {}
    route_kind = source_kind_by_file.get(route_file, classify_source_kind(route_file)) if route_file else SOURCE_KIND_CORE
    handler_kind = source_kind_by_file.get(handler_file, classify_source_kind(handler_file)) if handler_file else route_kind

    if is_low_trust_source_kind(route_kind) or is_low_trust_source_kind(handler_kind):
        return False, 0.05, "non_product_source"

    path_lower = (path or "").strip().lower()
    if not path_lower.startswith("/"):
        return False, 0.05, "invalid_path"

    parts = [part for part in path.strip("/").split("/") if part]
    if any(part.lower() in HEADER_LIKE_SEGMENTS for part in parts):
        return False, 0.05, "header_like_segment"
    if any(any(ch.isupper() for ch in part) for part in parts if not part.startswith("{")):
        return False, 0.1, "unexpected_uppercase_segment"

    confidence = 0.9
    if framework == "falcon":
        confidence = 0.98
    elif framework in {"express", "fastify", "fastapi", "flask", "django", "laravel", "go"}:
        confidence = 0.92
    elif framework == "nestjs":
        confidence = 0.7

    return True, confidence, "runtime_route"


def select_primary_framework(frameworks: list[str]) -> str:
    """Pick a primary framework tag, keeping Falcon prioritized and NestJS de-prioritized."""
    if not frameworks:
        return ""
    ranked = sorted(
        {framework for framework in frameworks if framework},
        key=lambda framework: (-FRAMEWORK_PRIORITIES.get(framework, 50), framework),
    )
    return ranked[0] if ranked else ""
