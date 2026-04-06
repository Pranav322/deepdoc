"""V2 Generation Engine — evidence-assembled, single-pass, validated page generation.

Phase 3 of the bucket-based doc pipeline:

  3.1 Evidence assembly: per-bucket, section-aware context gathering from scan data
  3.2 Single-pass generation: one LLM call per bucket with full evidence + mandatory outline
  3.3 Validation: check required sections, evidence citations, no hallucinated paths
  3.4 Graph-lite diagrams: static import/endpoint edges → Mermaid seed context
  3.5 Parallel generation: concurrent LLM calls for independent buckets
  3.6 Graceful degradation: fallbacks for sparse evidence, malformed output, LLM failures
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
)

from ..llm import LLMClient
from ..parser import parse_file, supported_extensions
from ..parser.base import ParsedFile, Symbol
from ..planner import DocBucket, DocPlan, RepoScan, tracked_bucket_files
from ..prompts_v2 import SYSTEM_V2, get_prompt_for_bucket
from ..scanner import _classify_file_role
from ..openapi import parse_openapi_spec, spec_to_context_string

console = Console()

# ═════════════════════════════════════════════════════════════════════════════
# 3.1  Evidence Assembly
# ═════════════════════════════════════════════════════════════════════════════


from .evidence import AssembledEvidence
# ═════════════════════════════════════════════════════════════════════════════
# 3.3  Validation
# ═════════════════════════════════════════════════════════════════════════════


@dataclass
class ValidationResult:
    """Result of validating a generated page against bucket requirements."""

    is_valid: bool
    missing_sections: list[str] = field(default_factory=list)
    missing_file_refs: list[str] = field(default_factory=list)
    hallucinated_paths: list[str] = field(default_factory=list)
    mermaid_block_count: int = 0
    word_count: int = 0
    warnings: list[str] = field(default_factory=list)
    missing_sibling_links: list[str] = field(default_factory=list)
    missing_contract_concepts: list[str] = field(default_factory=list)
    unmatched_routes: list[str] = field(default_factory=list)
    out_of_evidence_refs: list[str] = field(default_factory=list)
    missing_runtime_entities: list[str] = field(default_factory=list)
    missing_config_keys: list[str] = field(default_factory=list)
    missing_integrations: list[str] = field(default_factory=list)


class PageValidator:
    """Validates generated markdown against bucket requirements."""

    def __init__(self, repo_root: Path, scan: RepoScan):
        self.repo_root = repo_root
        self.scan = scan
        self.known_files = set(scan.file_summaries.keys())
        self.known_route_paths = {
            self._normalize_route_path(ep.get("path", ""))
            for ep in scan.published_api_endpoints
            if ep.get("path")
        }

    def validate(
        self,
        content: str,
        bucket: DocBucket,
        evidence: AssembledEvidence | None = None,
    ) -> ValidationResult:
        """Run all validation checks on generated content."""
        result = ValidationResult(is_valid=True)
        result.word_count = len(content.split())

        # 1. Check required sections appear as headings
        self._check_sections(content, bucket, result)

        # 2. Check that owned files are referenced
        self._check_file_refs(content, bucket, result)

        # 3. Check for hallucinated file paths
        self._check_hallucinated_paths(content, result)

        # 4. Check references against assembled evidence when available
        self._check_evidence_backed_refs(content, evidence, result)

        # 5. Check route/path claims for API and operations-heavy pages
        self._check_route_claims(content, bucket, result)

        # 6. Count mermaid diagrams
        result.mermaid_block_count = len(re.findall(r"```mermaid", content))

        # 6a. Check specialized evidence grounding
        self._check_runtime_grounding(content, bucket, evidence, result)
        self._check_config_grounding(content, bucket, evidence, result)
        self._check_integration_grounding(content, bucket, evidence, result)

        # 7. Minimum content check
        if result.word_count < 100:
            result.warnings.append("Very short page (<100 words) — may be incomplete")
            result.is_valid = False

        # 8. Check for required diagrams
        if bucket.required_diagrams and result.mermaid_block_count == 0:
            result.warnings.append(
                f"No Mermaid diagrams found but required: {', '.join(bucket.required_diagrams)}"
            )

        # 9. Check page contract
        self._check_page_contract(content, bucket, result)

        # 10. Check overview grounding depth
        self._check_overview_grounding(content, bucket, result)

        return result

    def _check_sections(
        self, content: str, bucket: DocBucket, result: ValidationResult
    ):
        """Check that required sections appear as markdown headings."""
        if not bucket.required_sections:
            return

        # Extract all headings from the content
        headings = set()
        for match in re.finditer(r"^#{1,4}\s+(.+)$", content, re.MULTILINE):
            headings.add(match.group(1).strip().lower())

        for section in bucket.required_sections:
            section_lower = section.lower()
            # Fuzzy match: check if any heading contains the key words
            found = any(
                section_lower in h or all(word in h for word in section_lower.split())
                for h in headings
            )
            if not found:
                result.missing_sections.append(section)

        if result.missing_sections:
            result.warnings.append(
                f"Missing sections: {', '.join(result.missing_sections)}"
            )

    def _check_file_refs(
        self, content: str, bucket: DocBucket, result: ValidationResult
    ):
        """Check that at least some of the bucket's owned files are referenced."""
        if not bucket.owned_files:
            return

        content_lower = content.lower()
        referenced = 0
        for f in bucket.owned_files:
            # Check if file path appears in the content (case-insensitive)
            if f.lower() in content_lower:
                referenced += 1

        # At least 30% of files should be referenced
        coverage = referenced / len(bucket.owned_files) if bucket.owned_files else 1.0
        unreferenced = [f for f in bucket.owned_files if f.lower() not in content_lower]

        if coverage < 0.3 and len(unreferenced) > 2:
            result.missing_file_refs = unreferenced[:5]
            result.warnings.append(
                f"Low file coverage: {referenced}/{len(bucket.owned_files)} files referenced "
                f"({coverage:.0%})"
            )

    def _check_hallucinated_paths(self, content: str, result: ValidationResult):
        """Find file paths in backticks that don't exist in the repo."""
        # Match `path/to/file.ext` or `path/to/file.ext:123`
        refs = re.findall(
            r"`([a-zA-Z][a-zA-Z0-9_./-]*\.[a-zA-Z]{1,8})(?::\d+)?`", content
        )
        hallucinated = []
        for ref in refs:
            # Skip common non-path patterns
            if ref.startswith("http") or ref.startswith("www."):
                continue
            if "." not in ref.split("/")[-1]:
                continue
            # Check if it looks like a file path and doesn't exist
            if "/" in ref and ref not in self.known_files:
                if not (self.repo_root / ref).exists():
                    hallucinated.append(ref)

        # Only flag if there are many — some may be examples in code blocks
        if len(hallucinated) > 5:
            result.hallucinated_paths = hallucinated[:10]
            result.warnings.append(
                f"{len(hallucinated)} potentially hallucinated file paths found"
            )
            result.is_valid = False

    def _check_evidence_backed_refs(
        self,
        content: str,
        evidence: AssembledEvidence | None,
        result: ValidationResult,
    ) -> None:
        if evidence is None or not evidence.evidence_file_paths:
            return

        referenced_files = set(
            re.findall(r"`([a-zA-Z][a-zA-Z0-9_./-]*\.[a-zA-Z]{1,8})(?::\d+)?`", content)
        )
        violations = sorted(
            ref
            for ref in referenced_files
            if ref in self.known_files and ref not in evidence.evidence_file_paths
        )
        if violations:
            result.out_of_evidence_refs = violations[:10]
            result.warnings.append(
                f"References files outside assembled evidence: {', '.join(violations[:4])}"
            )
            if len(violations) >= 4:
                result.is_valid = False

    def _check_route_claims(
        self, content: str, bucket: DocBucket, result: ValidationResult
    ) -> None:
        if not self.known_route_paths:
            return

        hints = bucket.generation_hints or {}
        title_lower = bucket.title.lower()
        if not (
            hints.get("include_endpoint_detail")
            or hints.get("is_endpoint_ref")
            or hints.get("is_endpoint_family")
            or bucket.section == "API Reference"
            or "health" in title_lower
            or "deployment" in title_lower
            or "api" in title_lower
        ):
            return

        candidates = {
            self._normalize_route_path(match)
            for match in re.findall(r"(\/[A-Za-z0-9{}_<>\-./]+)", content)
        }
        candidates = {
            route for route in candidates if route and "." not in route.split("/")[-1]
        }
        unmatched = sorted(
            route for route in candidates if route not in self.known_route_paths
        )
        if unmatched:
            result.unmatched_routes = unmatched[:10]
            result.warnings.append(
                f"Unmatched route/path claims: {', '.join(unmatched[:4])}"
            )
            if len(unmatched) >= 2 or any("health" in route for route in unmatched):
                result.is_valid = False

    @staticmethod
    def _normalize_route_path(path: str) -> str:
        path = path.strip()
        if not path:
            return ""
        path = re.sub(r"^https?://[^/]+", "", path)
        path = path.split("?", 1)[0].split("#", 1)[0]
        if not path.startswith("/"):
            path = "/" + path.lstrip("/")
        if path != "/" and path.endswith("/"):
            path = path[:-1]
        return path

    def _check_page_contract(
        self, content: str, bucket: DocBucket, result: ValidationResult
    ) -> None:
        contract = (bucket.generation_hints or {}).get("page_contract", {})
        if not contract:
            return

        content_lower = content.lower()
        for concept in contract.get("must_cover_concepts", []):
            concept_lower = concept.lower()
            concept_tokens = [
                token
                for token in re.findall(r"[a-z0-9]+", concept_lower)
                if len(token) > 2
            ]
            if not concept_tokens:
                continue
            if not all(token in content_lower for token in concept_tokens[:2]):
                result.missing_contract_concepts.append(concept)

        for sibling_slug in contract.get("required_sibling_links", []):
            if f"/{sibling_slug}" not in content and sibling_slug not in content:
                result.missing_sibling_links.append(sibling_slug)

        generic_headings = {
            "details",
            "diagrams",
            "implementation",
            "summary",
        }
        headings = {
            match.group(1).strip().lower()
            for match in re.finditer(r"^#{1,4}\s+(.+)$", content, re.MULTILINE)
        }
        if len(headings & generic_headings) >= 2:
            result.warnings.append("Too many generic section headings")

        if result.missing_contract_concepts:
            result.warnings.append(
                f"Missing contract concepts: {', '.join(result.missing_contract_concepts)}"
            )
            result.is_valid = False
        if result.missing_sibling_links:
            result.warnings.append(
                f"Missing sibling links: {', '.join(result.missing_sibling_links[:4])}"
            )

    def _check_overview_grounding(
        self, content: str, bucket: DocBucket, result: ValidationResult
    ) -> None:
        """Warn if overview/landing pages lack key structural elements."""
        hints = bucket.generation_hints or {}
        if not hints.get("is_introduction_page"):
            return

        content_lower = content.lower()
        headings = {
            match.group(1).strip().lower()
            for match in re.finditer(r"^#{1,4}\s+(.+)$", content, re.MULTILINE)
        }

        # Check for key structural elements
        has_flow = any(
            token in content_lower
            for token in ("runtime flow", "request lifecycle", "end-to-end", "sequence")
        )
        has_subsystem = any(
            token in content_lower
            for token in (
                "subsystem",
                "major component",
                "key component",
                "architecture",
            )
        )
        has_key_files = any("key file" in h or "files to know" in h for h in headings)
        has_mermaid = "```mermaid" in content

        if not has_flow:
            result.warnings.append("Overview page lacks runtime flow explanation")
        if not has_subsystem:
            result.warnings.append("Overview page lacks subsystem or component map")
        if not has_key_files:
            result.warnings.append("Overview page missing Key Files section")
        if not has_mermaid:
            result.warnings.append("Overview page has no Mermaid diagrams")

    def _check_runtime_grounding(
        self,
        content: str,
        bucket: DocBucket,
        evidence: AssembledEvidence | None,
        result: ValidationResult,
    ) -> None:
        hints = bucket.generation_hints or {}
        if (
            evidence is None
            or not evidence.runtime_context
            or not hints.get("include_runtime_context")
        ):
            return

        owned_files = set(bucket.owned_files)
        runtime_scan = getattr(self.scan, "runtime_scan", None)
        if runtime_scan is None:
            return

        group_kind = hints.get("runtime_group_kind", "")
        expected: list[str] = []
        for task in getattr(runtime_scan, "tasks", []) or []:
            if hints.get("is_runtime_overview"):
                expected.append(task.name)
            elif (
                group_kind == "celery"
                and getattr(task, "runtime_kind", "") == "celery"
                and task.file_path in owned_files
            ):
                expected.append(task.name)
            elif (
                group_kind == "django"
                and getattr(task, "runtime_kind", "")
                in {"django_command", "django_signal"}
                and task.file_path in owned_files
            ):
                expected.append(task.name)
            elif (
                group_kind == "laravel"
                and getattr(task, "runtime_kind", "").startswith("laravel_")
                and task.file_path in owned_files
            ):
                expected.append(task.name)
            elif (
                group_kind == "schedulers"
                and task.file_path in owned_files
                and getattr(task, "schedule_sources", [])
            ):
                expected.append(task.name)
            elif (
                group_kind == "workers"
                and task.file_path in owned_files
                and getattr(task, "runtime_kind", "")
                not in {"celery", "django_command", "django_signal"}
                and not getattr(task, "runtime_kind", "").startswith("laravel_")
            ):
                expected.append(task.name)

        for scheduler in getattr(runtime_scan, "schedulers", []) or []:
            if hints.get("is_runtime_overview"):
                expected.append(scheduler.name)
            elif (
                group_kind == "laravel"
                and getattr(scheduler, "scheduler_type", "") == "laravel_schedule"
                and scheduler.file_path in owned_files
            ):
                expected.append(scheduler.name)
            elif group_kind == "schedulers" and scheduler.file_path in owned_files:
                expected.append(scheduler.name)
            elif group_kind == "celery" and scheduler.file_path in owned_files:
                expected.append(scheduler.name)
            elif group_kind == "workers" and scheduler.file_path in owned_files:
                expected.append(scheduler.name)

        for consumer in getattr(runtime_scan, "realtime_consumers", []) or []:
            if hints.get("is_runtime_overview") or (
                group_kind == "realtime" and consumer.file_path in owned_files
            ):
                expected.append(consumer.name)

        expected = [item for item in dict.fromkeys(expected) if item]
        if not expected:
            return

        content_lower = content.lower()
        missing = [name for name in expected if name.lower() not in content_lower]
        if not missing:
            return

        result.missing_runtime_entities = missing[:8]
        result.warnings.append(
            f"Runtime context missing named entities: {', '.join(result.missing_runtime_entities[:4])}"
        )
        if len(missing) == len(expected) or (
            len(expected) >= 4 and len(missing) / len(expected) > 0.6
        ):
            result.is_valid = False

    def _check_config_grounding(
        self,
        content: str,
        bucket: DocBucket,
        evidence: AssembledEvidence | None,
        result: ValidationResult,
    ) -> None:
        expected: list[str] = []
        if evidence and evidence.config_env_context:
            expected.extend(
                re.findall(r"`([A-Z][A-Z0-9_]+)`", evidence.config_env_context)
            )

        tracked_files = set(bucket.owned_files) | set(bucket.artifact_refs)
        hints = bucket.generation_hints or {}
        for impact in getattr(self.scan, "config_impacts", []) or []:
            if isinstance(impact, dict):
                related_files = set(impact.get("related_files", []))
                file_path = impact.get("file_path", "")
                key = impact.get("key", "")
            else:
                related_files = set(getattr(impact, "related_files", []) or [])
                file_path = getattr(impact, "file_path", "")
                key = getattr(impact, "key", "")
            if not key:
                continue
            if (
                hints.get("is_introduction_page")
                or file_path in tracked_files
                or related_files & tracked_files
            ):
                expected.append(key)

        expected = [item for item in dict.fromkeys(expected) if item]
        if not expected:
            return

        content_lower = content.lower()
        mentioned = [key for key in expected if key.lower() in content_lower]
        if mentioned:
            return

        result.missing_config_keys = expected[:8]
        result.warnings.append(
            f"Config grounding missing key references: {', '.join(result.missing_config_keys[:4])}"
        )
        if bucket.section == "Getting Started" or "config" in bucket.title.lower():
            result.is_valid = False

    def _check_integration_grounding(
        self,
        content: str,
        bucket: DocBucket,
        evidence: AssembledEvidence | None,
        result: ValidationResult,
    ) -> None:
        if evidence is None or not evidence.integration_context:
            return

        hints = bucket.generation_hints or {}
        owned_files = set(bucket.owned_files)
        expected: list[str] = []
        for identity in getattr(self.scan, "integration_identities", []) or []:
            display_name = getattr(identity, "display_name", "")
            name = getattr(identity, "name", "")
            files = set(getattr(identity, "files", []) or [])
            if hints.get("include_integration_detail") or files & owned_files:
                expected.append(display_name or name)

        expected = [item for item in dict.fromkeys(expected) if item]
        if not expected:
            return

        content_lower = content.lower()
        missing = [name for name in expected if name.lower() not in content_lower]
        if not missing:
            return

        result.missing_integrations = missing[:8]
        result.warnings.append(
            f"Integration context missing named references: {', '.join(result.missing_integrations[:4])}"
        )
        if bucket.bucket_type == "integration" or hints.get(
            "include_integration_detail"
        ):
            result.is_valid = False
