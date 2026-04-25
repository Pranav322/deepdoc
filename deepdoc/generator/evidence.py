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


@dataclass
class AssembledEvidence:
    """All evidence gathered for a single bucket, ready for prompt injection."""

    bucket: DocBucket
    source_context: str  # tiered source code
    endpoints_detail: str  # endpoint listing (for endpoint/feature buckets)
    integration_context: str  # integration identity info
    cluster_context: str  # giant-file cluster info
    artifact_context: str  # setup/deploy/test file content
    graph_context: str  # static edges for diagram seeds
    cross_ref_context: str  # which other buckets reference this one's files
    database_context: str = ""  # database/schema info for database-type buckets
    runtime_context: str = ""  # runtime/task/scheduler/realtime info
    plan_summary_context: str = ""  # repo-wide summary for introduction pages
    repo_docs_context: str = (
        ""  # secondary repo-authored docs context for overview/system pages
    )
    total_evidence_chars: int = 0
    compressed_cards_context: str = ""
    files_included_raw: int = 0
    files_compressed: int = 0
    coverage_files_total: int = 0
    helper_context: str = ""  # resolved helper/utility function bodies
    evidence_file_paths: set[str] = field(default_factory=set)
    config_env_context: str = ""  # extracted env var names and config keys


@dataclass
class FileEvidenceCard:
    """Compressed coverage record for a tracked file."""

    file_path: str
    role: str
    summary: str
    key_symbols: list[str] = field(default_factory=list)
    key_routes: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    integration_signals: list[str] = field(default_factory=list)
    config_signals: list[str] = field(default_factory=list)
    database_signals: list[str] = field(default_factory=list)
    raw_source_included: bool = False
    targeted_snippet: str = ""


class EvidenceAssembler:
    """Gathers and formats evidence for a single bucket from the full scan output.

    The assembler is bucket-type-aware: endpoint buckets get richer endpoint detail,
    integration buckets get integration identity context, etc.
    """

    # Total char budget for source context per page
    SOURCE_BUDGET = 200_000
    # How many chars to reserve for non-source evidence
    NON_SOURCE_BUDGET = 40_000
    # Soft target for compressed-card rendering before switching to compact mode
    COMPRESSED_CARD_TARGET = 60_000

    def __init__(
        self, repo_root: Path, scan: RepoScan, plan: DocPlan, cfg: dict[str, Any]
    ):
        self.repo_root = repo_root
        self.scan = scan
        self.plan = plan
        self.cfg = cfg
        self.source_budget = int(cfg.get("source_context_budget", self.SOURCE_BUDGET))
        self.large_file_lines = int(cfg.get("large_file_lines", 500))
        self.giant_file_lines = int(cfg.get("giant_file_lines", 2000))
        # Pre-index: file → bucket slugs for cross-referencing
        self._file_to_buckets: dict[str, list[str]] = defaultdict(list)
        for b in plan.buckets:
            for f in b.owned_files:
                self._file_to_buckets[f].append(b.slug)
        # Pre-index: slug → bucket
        self._slug_to_bucket: dict[str, DocBucket] = {b.slug: b for b in plan.buckets}
        # Pre-index: file → endpoint tuples
        self._file_to_endpoints: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for ep in scan.api_endpoints:
            for key in ("file", "handler_file", "route_file"):
                file_path = ep.get(key, "")
                if file_path:
                    self._file_to_endpoints[file_path].append(ep)
        # Pre-index: file → integration display names
        self._file_to_integrations: dict[str, list[str]] = defaultdict(list)
        for identity in scan.integration_identities or []:
            for file_path in identity.files:
                self._file_to_integrations[file_path].append(identity.display_name)

    def assemble(self, bucket: DocBucket) -> AssembledEvidence:
        """Build the complete evidence package for one bucket."""
        (
            source_ctx,
            compressed_cards_ctx,
            files_included_raw,
            files_compressed,
            coverage_total,
        ) = self._build_source_context(bucket)
        endpoints_detail = self._build_endpoints_detail(bucket)
        integration_ctx = self._build_integration_context(bucket)
        cluster_ctx = self._build_cluster_context(bucket)
        artifact_ctx = self._build_artifact_context(bucket)
        graph_ctx = self._build_graph_context(bucket)
        cross_ref_ctx = self._build_cross_ref_context(bucket)
        database_ctx = self._build_database_context(bucket)
        runtime_ctx = self._build_runtime_context(bucket)
        plan_summary_ctx = self._build_plan_summary_context(bucket)
        helper_ctx, helper_files = self._build_helper_context(bucket, source_ctx)
        repo_docs_ctx, repo_doc_files = self._build_repo_docs_context(bucket)

        evidence_files = set(tracked_bucket_files(bucket))
        evidence_files.update(helper_files)
        if bucket.generation_hints.get("is_introduction_page"):
            evidence_files.update(self.scan.entry_points)
            evidence_files.update(self.scan.config_files)
        evidence_files.update(repo_doc_files)

        total = sum(
            len(s)
            for s in [
                source_ctx,
                compressed_cards_ctx,
                endpoints_detail,
                integration_ctx,
                cluster_ctx,
                artifact_ctx,
                graph_ctx,
                cross_ref_ctx,
                database_ctx,
                runtime_ctx,
                plan_summary_ctx,
                repo_docs_ctx,
                helper_ctx,
            ]
        )

        config_env_ctx = self._build_config_env_context(bucket)

        return AssembledEvidence(
            bucket=bucket,
            source_context=source_ctx,
            compressed_cards_context=compressed_cards_ctx,
            endpoints_detail=endpoints_detail,
            integration_context=integration_ctx,
            cluster_context=cluster_ctx,
            artifact_context=artifact_ctx,
            graph_context=graph_ctx,
            cross_ref_context=cross_ref_ctx,
            database_context=database_ctx,
            runtime_context=runtime_ctx,
            plan_summary_context=plan_summary_ctx,
            repo_docs_context=repo_docs_ctx,
            total_evidence_chars=total,
            files_included_raw=files_included_raw,
            files_compressed=files_compressed,
            coverage_files_total=coverage_total,
            helper_context=helper_ctx,
            evidence_file_paths=evidence_files,
            config_env_context=config_env_ctx,
        )

    # ── Source context (tiered + compressed coverage) ───────────────────

    def _build_source_context(
        self, bucket: DocBucket
    ) -> tuple[str, str, int, int, int]:
        """Build raw-source context plus compressed evidence cards for tracked files.

        Tier 1 (≤large_file_lines): full source
        Tier 2 (large_file_lines+1..giant_file_lines): signatures + bounded body excerpts
        Tier 3 (>giant_file_lines): header + key symbol bodies with deeper owned-symbol coverage
          - If giant-file clusters exist, include only symbols from relevant clusters

        Returns (raw_source_context, compressed_cards_context, raw_count, compressed_count, coverage_total).
        """
        max_chars = self.source_budget
        total_chars = 0
        parts: list[str] = []
        included = 0
        compressed_cards: list[FileEvidenceCard] = []

        # Load file data, sort smallest first for maximum inclusion
        files_data: list[tuple[str, str, int, ParsedFile | None]] = []
        for src_file in tracked_bucket_files(bucket):
            src_path = self.repo_root / src_file
            if not src_path.exists():
                continue
            try:
                content = src_path.read_text(encoding="utf-8", errors="replace")
                line_count = len(content.splitlines())
                parsed = self.scan.parsed_files.get(src_file)
                if not parsed:
                    parsed = parse_file(src_path)
                files_data.append((src_file, content, line_count, parsed))
            except Exception:
                continue

        # If bucket has owned_symbols, we can filter giant file content
        owned_symbols_set = set(bucket.owned_symbols) if bucket.owned_symbols else set()

        ranked_files = sorted(
            files_data,
            key=lambda item: (
                -self._source_priority(
                    bucket, item[0], item[2], item[3], owned_symbols_set
                ),
                item[2],
                item[0],
            ),
        )

        for src_file, content, line_count, parsed in ranked_files:
            lang = parsed.language if parsed else ""

            # Build header block
            header = f"\n### File: `{src_file}` ({line_count} lines)\n"
            if parsed and parsed.symbols:
                header += "**Symbols:**\n"
                for s in parsed.symbols:
                    # If we have owned_symbols, mark which ones are relevant
                    marker = (
                        " ⭐"
                        if owned_symbols_set and s.name in owned_symbols_set
                        else ""
                    )
                    header += f"- {s.kind} `{s.name}` (line {s.start_line}){marker}"
                    if s.docstring:
                        header += f": {s.docstring[:150]}"
                    header += "\n"
                header += "\n"
            if parsed and parsed.imports:
                header += f"**Imports**: {', '.join(parsed.imports[:15])}\n\n"

            # Choose tier
            if line_count <= self.large_file_lines:
                code = content
            elif line_count <= self.giant_file_lines:
                code = self._extract_signatures(parsed, content)
            else:
                # Tier 3 — if giant file with clusters, focus on relevant symbols
                code = self._extract_key_sections(
                    parsed, content, src_file, owned_symbols_set
                )

            remaining = max_chars - total_chars - len(header)
            if remaining <= 80:
                compressed_cards.append(
                    self._build_file_evidence_card(
                        bucket=bucket,
                        src_file=src_file,
                        content=content,
                        line_count=line_count,
                        parsed=parsed,
                        raw_source_included=False,
                    )
                )
                continue

            if len(code) > remaining:
                code = code[:remaining] + "\n... [truncated — file continues]"

            file_section = header + f"```{lang}\n{code}\n```\n"
            parts.append(file_section)
            total_chars += len(file_section)
            included += 1

        cards_context = self._format_compressed_cards(compressed_cards)
        return (
            "\n".join(parts),
            cards_context,
            included,
            len(compressed_cards),
            len(ranked_files),
        )

    # ── Helper/utility resolution ────────────────────────────────────────

    def _build_helper_context(
        self, bucket: DocBucket, source_ctx: str
    ) -> tuple[str, set[str]]:
        """Resolve imported repo-local helpers deterministically.

        Helper following is restricted to imported local modules and imported symbols.
        We do not resolve helpers by call-name alone across the whole repo.
        """
        if not self._should_follow_helpers(bucket):
            return "", set()

        helper_budget = 60_000
        bucket_files = set(tracked_bucket_files(bucket))
        called_names = self._extract_called_symbol_names(source_ctx)
        module_index = self._build_module_file_index()
        symbol_index = self._build_symbol_index()

        helper_sections: list[str] = []
        helper_files: set[str] = set()
        emitted_symbols: set[tuple[str, str]] = set()
        total_chars = 0

        for src_file in bucket_files:
            parsed = self.scan.parsed_files.get(src_file)
            source_content = self.scan.file_contents.get(src_file, "")
            if not parsed:
                continue

            imported_symbols, imported_files = self._resolve_import_targets(
                parsed.imports, source_content, module_index
            )
            for imported_file in imported_files:
                if imported_file in bucket_files:
                    continue
                candidates = symbol_index.get(imported_file, [])
                for symbol in candidates:
                    if symbol.name in self._builtin_helper_skip_names():
                        continue
                    if (
                        imported_symbols.get(imported_file)
                        and symbol.name not in imported_symbols[imported_file]
                    ):
                        continue
                    if called_names and symbol.name not in called_names:
                        continue
                    symbol_key = (imported_file, symbol.name)
                    if symbol_key in emitted_symbols:
                        continue
                    section = self._render_helper_symbol(imported_file, symbol)
                    if not section:
                        continue
                    if total_chars + len(section) > helper_budget:
                        return (
                            "## Resolved Helper Functions\n"
                            + "\n".join(helper_sections)
                            if helper_sections
                            else "",
                            helper_files,
                        )
                    helper_sections.append(section)
                    helper_files.add(imported_file)
                    emitted_symbols.add(symbol_key)
                    total_chars += len(section)

        if not helper_sections:
            return "", set()
        return "## Resolved Helper Functions\n" + "\n".join(
            helper_sections
        ), helper_files

    def _should_follow_helpers(self, bucket: DocBucket) -> bool:
        hints = bucket.generation_hints or {}
        if hints.get("is_introduction_page"):
            return False
        if bucket.bucket_type == "research-context":
            return False
        if bucket.publication_tier == "supporting" and bucket.section in {
            "Testing",
            "Examples",
            "Design & Notes",
            "CI/CD and Release",
        }:
            return False
        style = hints.get("prompt_style", "")
        return style in {
            "endpoint",
            "endpoint_ref",
            "feature",
            "system",
            "architecture_component",
        } or bucket.bucket_type in {"feature", "system", "endpoint", "endpoint-family"}

    def _build_repo_docs_context(self, bucket: DocBucket) -> tuple[str, set[str]]:
        """Build secondary context from repo-authored docs for overview/system pages."""
        hints = bucket.generation_hints or {}
        style = hints.get("prompt_style", "")
        title_tokens = {
            token.lower() for token in re.findall(r"[A-Za-z0-9]+", bucket.title)
        }
        if not (
            hints.get("is_introduction_page")
            or style == "architecture_component"
            or {"architecture", "overview", "system"} & title_tokens
        ):
            return "", set()

        lines: list[str] = [
            "Use this as secondary context only. Runtime/source evidence wins on conflicts.",
        ]
        doc_files: set[str] = set()

        for context in self.scan.research_contexts[:10]:
            file_path = context.get("file_path")
            summary = context.get("summary")
            title = context.get("title") or Path(file_path or "").stem
            if not file_path or not summary:
                continue
            doc_files.add(file_path)
            lines.append(f"- {title} (`{file_path}`): {summary}")

        if self.scan.doc_contexts:
            lines.append("\nAdditional repo documentation:")
            for file_path, summary in list(self.scan.doc_contexts.items())[:10]:
                doc_files.add(file_path)
                lines.append(f"- `{file_path}`: {summary}")

        if len(lines) == 1:
            return "", set()
        return "## Internal Docs Context\n" + "\n".join(lines), doc_files

    def _extract_called_symbol_names(self, source_ctx: str) -> set[str]:
        call_pattern = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
        return {
            name
            for name in call_pattern.findall(source_ctx)
            if name not in self._builtin_helper_skip_names() and len(name) > 2
        }

    def _builtin_helper_skip_names(self) -> set[str]:
        return {
            "print",
            "len",
            "str",
            "int",
            "float",
            "dict",
            "list",
            "set",
            "tuple",
            "range",
            "enumerate",
            "zip",
            "map",
            "filter",
            "sorted",
            "reversed",
            "isinstance",
            "issubclass",
            "hasattr",
            "getattr",
            "setattr",
            "delattr",
            "super",
            "property",
            "staticmethod",
            "classmethod",
            "type",
            "object",
            "open",
            "round",
            "abs",
            "max",
            "min",
            "sum",
            "any",
            "all",
            "format",
            "json",
            "os",
            "sys",
            "re",
            "logging",
            "datetime",
            "time",
            "self",
            "__init__",
            "__str__",
            "__repr__",
        }

    def _build_module_file_index(self) -> dict[str, set[str]]:
        index: dict[str, set[str]] = defaultdict(set)
        for file_path in self.scan.parsed_files:
            rel = Path(file_path)
            stem = rel.with_suffix("")
            parts = stem.parts
            candidates: set[str] = set()
            if parts and parts[-1] == "__init__":
                parts = parts[:-1]
            if parts:
                dotted = ".".join(parts)
                candidates.add(dotted)
                for idx in range(1, len(parts)):
                    candidates.add(".".join(parts[idx:]))
                candidates.add(parts[-1])
            for candidate in candidates:
                index[candidate].add(file_path)
        return index

    def _build_symbol_index(self) -> dict[str, list[Symbol]]:
        index: dict[str, list[Symbol]] = {}
        for file_path, parsed in self.scan.parsed_files.items():
            if not parsed or not parsed.symbols:
                continue
            index[file_path] = [
                sym
                for sym in parsed.symbols
                if sym.kind in {"function", "method", "class"}
            ]
        return index

    def _resolve_import_targets(
        self,
        imports: list[str],
        content: str,
        module_index: dict[str, set[str]],
    ) -> tuple[dict[str, set[str]], set[str]]:
        imported_symbols: dict[str, set[str]] = defaultdict(set)
        imported_files: set[str] = set()

        for module_name in imports or []:
            module_files = self._resolve_repo_local_module(module_name, module_index)
            imported_files.update(module_files)

        for module_name, symbol_names in self._extract_explicit_import_symbols(content):
            module_files = self._resolve_repo_local_module(module_name, module_index)
            for file_path in module_files:
                imported_files.add(file_path)
                imported_symbols[file_path].update(symbol_names)

        return imported_symbols, imported_files

    def _resolve_repo_local_module(
        self, module_name: str, module_index: dict[str, set[str]]
    ) -> set[str]:
        module_name = module_name.strip().strip(".")
        if not module_name:
            return set()
        candidates = [
            module_name,
            module_name.replace("/", "."),
        ]
        resolved: set[str] = set()
        for candidate in candidates:
            if candidate in module_index:
                resolved.update(module_index[candidate])
            else:
                for known_module, files in module_index.items():
                    if known_module.endswith(candidate):
                        resolved.update(files)
        return resolved

    def _extract_explicit_import_symbols(
        self, content: str
    ) -> list[tuple[str, set[str]]]:
        results: list[tuple[str, set[str]]] = []
        for match in re.finditer(
            r"^\s*from\s+([A-Za-z0-9_./]+)\s+import\s+(.+)$", content, re.MULTILINE
        ):
            module_name = match.group(1).strip()
            raw_symbols = match.group(2).split(",")
            names = set()
            for raw in raw_symbols:
                symbol_name = raw.strip().split(" as ", 1)[0].strip()
                if symbol_name and symbol_name != "*":
                    names.add(symbol_name)
            if module_name and names:
                results.append((module_name, names))
        return results

    def _render_helper_symbol(self, file_path: str, symbol: Symbol) -> str:
        src_path = self.repo_root / file_path
        if not src_path.exists():
            return ""
        try:
            file_content = src_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""

        file_lines = file_content.splitlines()
        start = max(0, symbol.start_line - 1)
        parsed = self.scan.parsed_files.get(file_path)
        end = len(file_lines)
        if parsed and parsed.symbols:
            for idx, candidate in enumerate(parsed.symbols):
                if candidate.start_line == symbol.start_line and idx + 1 < len(
                    parsed.symbols
                ):
                    end = parsed.symbols[idx + 1].start_line - 1
                    break

        excerpt_end = min(end, start + 60)
        body = "\n".join(file_lines[start:excerpt_end])
        if excerpt_end < end:
            body += f"\n    ... [{end - excerpt_end} more lines]"
        return (
            f"\n### Helper: `{symbol.name}()` (`{file_path}:{symbol.start_line}`)\n"
            f"```python\n{body}\n```\n"
        )

    def _source_priority(
        self,
        bucket: DocBucket,
        src_file: str,
        line_count: int,
        parsed: ParsedFile | None,
        owned_symbols: set[str],
    ) -> int:
        """Score files for raw-source inclusion."""
        score = 0
        path_lower = src_file.lower()

        if src_file in set(self.scan.entry_points):
            score += 140
        if src_file in bucket.owned_files:
            score += 90
        if src_file in bucket.artifact_refs:
            score += 40
        if src_file in self._file_to_endpoints:
            score += 120
        if src_file in self.scan.giant_file_clusters:
            score += 80
        if src_file in self._file_to_integrations:
            score += 60
        if any(
            token in path_lower
            for token in ("middleware", "auth", "config", "settings")
        ):
            score += 45
        if any(token in path_lower for token in ("route", "controller", "handler")):
            score += 40
        if (
            owned_symbols
            and parsed
            and any(s.name in owned_symbols for s in parsed.symbols)
        ):
            score += 70
        if parsed and parsed.imports:
            score += min(len(parsed.imports), 10)

        # Prefer smaller files when priority is otherwise equal.
        score -= line_count // 50
        return score

    def _build_file_evidence_card(
        self,
        bucket: DocBucket,
        src_file: str,
        content: str,
        line_count: int,
        parsed: ParsedFile | None,
        *,
        raw_source_included: bool,
    ) -> FileEvidenceCard:
        """Create a compressed coverage card for one tracked file."""
        role = _classify_file_role(src_file, parsed)
        endpoint_refs = self._file_to_endpoints.get(src_file, [])
        key_routes = sorted(
            {
                f"{ep.get('method', 'ANY').upper()} {ep.get('path', '')}"
                for ep in endpoint_refs
                if ep.get("path")
            }
        )[:6]
        key_symbols = (
            [
                f"{symbol.kind}:{symbol.name}"
                for symbol in (parsed.symbols[:8] if parsed else [])
            ]
            if parsed
            else []
        )
        imports = parsed.imports[:8] if parsed and parsed.imports else []
        integration_signals = sorted(set(self._file_to_integrations.get(src_file, [])))[
            :5
        ]
        config_signals = self._build_config_signals(
            bucket, src_file, content, endpoint_refs
        )
        database_signals = self._build_database_signals(src_file)
        summary = self._summarize_file_for_card(
            src_file,
            role,
            line_count,
            parsed,
            key_routes,
            integration_signals,
            config_signals,
            database_signals,
        )
        targeted_snippet = self._targeted_card_snippet(content, parsed, key_routes)

        return FileEvidenceCard(
            file_path=src_file,
            role=role,
            summary=summary,
            key_symbols=key_symbols,
            key_routes=key_routes,
            imports=imports,
            integration_signals=integration_signals,
            config_signals=config_signals,
            database_signals=database_signals,
            raw_source_included=raw_source_included,
            targeted_snippet=targeted_snippet,
        )

    def _build_config_signals(
        self,
        bucket: DocBucket,
        src_file: str,
        content: str,
        endpoint_refs: list[dict[str, Any]],
    ) -> list[str]:
        signals: list[str] = []
        if src_file in bucket.artifact_refs:
            signals.append("artifact_ref")
        lowered = src_file.lower()
        if any(
            token in lowered
            for token in ("config", "settings", ".env", "docker", "compose")
        ):
            signals.append("config_root")
        if any(ep.get("route_file") == src_file for ep in endpoint_refs):
            signals.append("route_registration")
        if "process.env" in content or "os.environ" in content or "ENV.get(" in content:
            signals.append("environment_lookup")
        return signals[:5]

    # ── Config / env var extraction ──────────────────────────────────────

    _ENV_VAR_PATTERNS = [
        re.compile(r"""os\.environ\s*\[\s*['"]([\w]+)['"]\s*\]"""),
        re.compile(r"""os\.getenv\s*\(\s*['"]([\w]+)['"]"""),
        re.compile(r"""os\.environ\.get\s*\(\s*['"]([\w]+)['"]"""),
        re.compile(r"""process\.env\.([A-Z][A-Z0-9_]+)"""),
        re.compile(r"""ENV\s*\[\s*['"]([\w]+)['"]\s*\]"""),
        re.compile(r"""getenv\s*\(\s*['"]([\w]+)['"]"""),
        re.compile(r"""env\s*\(\s*['"]([\w]+)['"]"""),
    ]

    def _build_config_env_context(self, bucket: DocBucket) -> str:
        """Extract actual env var names from source files for grounded config docs."""
        env_vars: dict[str, list[str]] = {}  # var_name -> [file_paths]

        for src_file in bucket.owned_files:
            src_path = self.repo_root / src_file
            if not src_path.exists():
                continue
            try:
                content = src_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for pattern in self._ENV_VAR_PATTERNS:
                for match in pattern.finditer(content):
                    var_name = match.group(1)
                    if var_name and len(var_name) > 2:
                        env_vars.setdefault(var_name, []).append(src_file)

        if not env_vars:
            return ""

        lines = ["**Extracted Environment Variables & Config Keys**\n"]
        lines.append("| Variable | Found In |")
        lines.append("|----------|----------|")
        for var_name in sorted(env_vars.keys()):
            files = sorted(set(env_vars[var_name]))
            files_str = ", ".join(f"`{f}`" for f in files[:3])
            lines.append(f"| `{var_name}` | {files_str} |")

        return "\n".join(lines)

    def _build_database_signals(self, src_file: str) -> list[str]:
        artifact_scan = getattr(self.scan, "artifact_scan", None)
        db_scan = (
            getattr(artifact_scan, "database_scan", None) if artifact_scan else None
        )
        if not db_scan:
            return []

        signals: list[str] = []
        if any(
            getattr(model_file, "file_path", "") == src_file
            for model_file in db_scan.model_files
        ):
            signals.append("model_file")
        if src_file in getattr(db_scan, "migration_files", []):
            signals.append("migration_file")
        if src_file in getattr(db_scan, "schema_files", []):
            signals.append("schema_file")
        return signals

    def _summarize_file_for_card(
        self,
        src_file: str,
        role: str,
        line_count: int,
        parsed: ParsedFile | None,
        key_routes: list[str],
        integration_signals: list[str],
        config_signals: list[str],
        database_signals: list[str],
    ) -> str:
        """Build a deterministic one-sentence summary for a file card."""
        clauses = [f"{role} file", f"{line_count} lines"]
        if parsed and parsed.symbols:
            clauses.append(f"{len(parsed.symbols)} symbol(s)")
        if key_routes:
            clauses.append(f"routes: {', '.join(key_routes[:2])}")
        if integration_signals:
            clauses.append(f"integrations: {', '.join(integration_signals[:2])}")
        if config_signals:
            clauses.append(f"signals: {', '.join(config_signals[:2])}")
        if database_signals:
            clauses.append(f"database: {', '.join(database_signals[:2])}")
        return f"{src_file} is a {', '.join(clauses)}."

    def _targeted_card_snippet(
        self,
        content: str,
        parsed: ParsedFile | None,
        key_routes: list[str],
    ) -> str:
        """Include a tiny targeted snippet only when metadata is sparse."""
        if parsed and parsed.symbols:
            preview = self._extract_signatures(parsed, content).strip()
            return preview[:350]
        if key_routes:
            lines = [
                line
                for line in content.splitlines()
                if any(route.split(" ", 1)[-1] in line for route in key_routes)
            ]
            if lines:
                return "\n".join(lines[:6])[:350]
        non_empty = [line for line in content.splitlines() if line.strip()]
        return "\n".join(non_empty[:6])[:240]

    def _format_compressed_cards(self, cards: list[FileEvidenceCard]) -> str:
        """Render compressed evidence cards for files not included as raw source."""
        if not cards:
            return ""

        verbose_blocks: list[str] = []
        for card in cards:
            block = [
                f"### Card: `{card.file_path}`",
                f"- Role: {card.role}",
                f"- Summary: {card.summary}",
            ]
            if card.key_symbols:
                block.append(f"- Key symbols: {', '.join(card.key_symbols)}")
            if card.key_routes:
                block.append(f"- Key routes: {', '.join(card.key_routes)}")
            if card.imports:
                block.append(f"- Imports: {', '.join(card.imports)}")
            if card.integration_signals:
                block.append(
                    f"- Integration signals: {', '.join(card.integration_signals)}"
                )
            if card.config_signals:
                block.append(f"- Config signals: {', '.join(card.config_signals)}")
            if card.database_signals:
                block.append(f"- Database signals: {', '.join(card.database_signals)}")
            if card.targeted_snippet:
                block.append("```")
                block.append(card.targeted_snippet)
                block.append("```")
            verbose_blocks.append("\n".join(block))

        verbose_context = "\n\n".join(verbose_blocks)
        if len(verbose_context) <= self.COMPRESSED_CARD_TARGET and len(cards) <= 25:
            return verbose_context

        compact_lines = []
        for card in cards:
            details: list[str] = [card.role]
            if card.key_symbols:
                details.append(f"symbols={', '.join(card.key_symbols[:4])}")
            if card.key_routes:
                details.append(f"routes={', '.join(card.key_routes[:3])}")
            if card.integration_signals:
                details.append(
                    f"integrations={', '.join(card.integration_signals[:2])}"
                )
            if card.config_signals:
                details.append(f"signals={', '.join(card.config_signals[:2])}")
            if card.database_signals:
                details.append(f"database={', '.join(card.database_signals[:2])}")
            compact_lines.append(
                f"- `{card.file_path}`: {card.summary} [{' | '.join(details)}]"
            )
        return "\n".join(compact_lines)

    def _extract_signatures(self, parsed: ParsedFile | None, content: str) -> str:
        """Tier 2: signatures + deeper body excerpts, scaled from config thresholds."""
        if not parsed or not parsed.symbols:
            lines = content.splitlines()
            fallback_limit = max(150, min(300, self.large_file_lines // 2))
            return "\n".join(lines[:fallback_limit]) + (
                "\n... [truncated]" if len(lines) > fallback_limit else ""
            )

        content_lines = content.splitlines()
        result: list[str] = []
        seen: set[int] = set()
        excerpt_limit = max(30, min(80, self.large_file_lines // 10))
        full_body_limit = max(40, min(100, self.large_file_lines // 8))

        # Calculate actual end line for each symbol (next symbol's start or end of file)
        symbol_ends: list[int] = []
        for idx, symbol in enumerate(parsed.symbols):
            if idx + 1 < len(parsed.symbols):
                symbol_ends.append(parsed.symbols[idx + 1].start_line - 1)
            else:
                symbol_ends.append(len(content_lines))

        for idx, symbol in enumerate(parsed.symbols):
            start = max(0, symbol.start_line - 1)
            actual_end = symbol_ends[idx]
            body_length = actual_end - start

            # Include full short bodies; otherwise take a deeper excerpt.
            if body_length <= full_body_limit:
                end = actual_end
            else:
                end = min(start + excerpt_limit, len(content_lines))

            for i in range(start, end):
                if i not in seen:
                    result.append(content_lines[i])
                    seen.add(i)
            if end < actual_end and end not in seen:
                result.append(
                    f"    ... [{actual_end - end} more lines in {symbol.name}]"
                )

        return "\n".join(result)

    def _extract_key_sections(
        self,
        parsed: ParsedFile | None,
        content: str,
        file_path: str,
        owned_symbols: set[str],
    ) -> str:
        """Tier 3: header + key symbol bodies, prioritizing owned symbols with full bodies."""
        lines = content.splitlines()
        header = "\n".join(lines[:30])

        if not parsed or not parsed.symbols:
            return header + "\n... [large file — see symbol list above]"

        def _symbol_end(idx: int) -> int:
            if idx + 1 < len(parsed.symbols):
                return parsed.symbols[idx + 1].start_line - 1
            return len(lines)

        # If we have owned_symbols AND this is a giant file with clusters,
        # prioritize showing those symbols
        if owned_symbols:
            priority = [
                (i, s) for i, s in enumerate(parsed.symbols) if s.name in owned_symbols
            ]
            others = [
                (i, s)
                for i, s in enumerate(parsed.symbols)
                if s.name not in owned_symbols
            ]
            # Show priority symbols first, then fill with others up to 40
            indexed_symbols = priority + others[: max(0, 40 - len(priority))]
        else:
            indexed_symbols = list(enumerate(parsed.symbols[:40]))

        sig_lines: list[str] = ["\n\n# [Key Symbol Bodies]"]
        owned_excerpt_limit = max(60, min(120, self.giant_file_lines // 25))
        secondary_excerpt_limit = max(20, min(40, self.giant_file_lines // 80))
        for orig_idx, symbol in indexed_symbols:
            start = max(0, symbol.start_line - 1)
            sym_end = _symbol_end(orig_idx)
            is_owned = symbol.name in owned_symbols

            if is_owned:
                max_body = owned_excerpt_limit
            else:
                max_body = secondary_excerpt_limit

            end = min(start + max_body, sym_end, len(lines))
            marker = " [OWNED — full body]" if is_owned else ""
            sig_lines.append(f"\n# {symbol.kind}: {symbol.name}{marker}")
            sig_lines.extend(lines[start:end])
            if end < sym_end:
                sig_lines.append(f"    ... [{sym_end - end} more lines]")

        return header + "\n".join(sig_lines)

    # ── Endpoint detail ──────────────────────────────────────────────────

    def _build_endpoints_detail(self, bucket: DocBucket) -> str:
        """Build endpoint listing relevant to this bucket.

        For endpoint buckets: use endpoint_bundles matched by family or handler file.
        For endpoint_ref buckets: match the specific endpoint via handler symbol or
            method+path in title, pull the full evidence chain from the matching bundle.
        For feature buckets: find endpoints whose handler files overlap with owned_files.
        For others: minimal or empty.
        """
        hints = bucket.generation_hints or {}
        if not hints.get("include_endpoint_detail"):
            return ""

        page_files = set(bucket.owned_files)
        page_symbols = set(bucket.owned_symbols)
        lines: list[str] = []

        # ── endpoint_ref: match specific endpoint, pull deep evidence ─────
        if hints.get("is_endpoint_ref"):
            # The title is e.g. "GET /api/v1/orders" — extract method+path
            title_parts = bucket.title.split(" ", 1)
            ref_method = title_parts[0].upper() if len(title_parts) >= 1 else ""
            ref_path = title_parts[1] if len(title_parts) >= 2 else ""

            # Find matching bundle via handler symbol or method+path
            matched_bundle = None
            if self.scan.endpoint_bundles:
                for bundle in self.scan.endpoint_bundles:
                    # Match by handler symbol
                    if page_symbols and page_symbols & set(bundle.handler_symbols):
                        matched_bundle = bundle
                        break
                    # Match by method+path in bundle's methods_paths
                    for mp in bundle.methods_paths:
                        if (
                            ref_method
                            and ref_path
                            and ref_method in mp
                            and ref_path in mp
                        ):
                            matched_bundle = bundle
                            break
                    if matched_bundle:
                        break

            if matched_bundle:
                lines.append(f"**Endpoint: {bucket.title}**")
                lines.append(f"  Handler file: `{matched_bundle.handler_file}`")
                if matched_bundle.handler_symbols:
                    lines.append(
                        f"  Handler functions: {', '.join(matched_bundle.handler_symbols)}"
                    )
                lines.append(f"  Family: {matched_bundle.endpoint_family}")
                if matched_bundle.evidence:
                    lines.append(
                        "\n  **Evidence chain** (files involved in this endpoint's flow):"
                    )
                    for eu in matched_bundle.evidence:
                        syms = (
                            f" — symbols: {', '.join(eu.symbols[:5])}"
                            if eu.symbols
                            else ""
                        )
                        lines.append(f"    - `{eu.file_path}` ({eu.role}){syms}")
                    # Also add evidence files to source context by injecting them into owned_files
                    # (non-destructive: only for this assembly run)
                    for eu in matched_bundle.evidence:
                        if eu.file_path not in bucket.owned_files:
                            bucket.owned_files.append(eu.file_path)
                if matched_bundle.integration_edges:
                    lines.append(
                        f"  Integrations touched: {', '.join(matched_bundle.integration_edges)}"
                    )
            else:
                # Fallback: raw endpoint data matching this handler
                for ep in self.scan.api_endpoints:
                    ep_handler = ep.get("handler", "")
                    ep_method = ep.get("method", "").upper()
                    ep_path = ep.get("path", "")
                    if (ep_handler and ep_handler in page_symbols) or (
                        ref_method == ep_method and ref_path == ep_path
                    ):
                        lines.append(
                            f"- {ep_method} {ep_path} → "
                            f"{ep_handler} (`{ep.get('file', '')}:{ep.get('line', 0)}`)"
                        )
            return "\n".join(lines) if lines else ""

        # ── endpoint / feature: family-level evidence ─────────────────────
        # Check endpoint bundles first (richer evidence)
        if self.scan.endpoint_bundles:
            bucket_tokens = {
                token
                for token in re.split(
                    r"[^a-z0-9]+",
                    f"{bucket.slug} {bucket.title}".lower().replace("_", "-"),
                )
                if token
            }
            for bundle in self.scan.endpoint_bundles:
                family = bundle.endpoint_family.lower().replace("_", "-")
                family_aliases = {family, family.replace("-", "_")}
                if family.endswith("s") and len(family) > 3:
                    singular = family[:-1]
                    family_aliases.update({singular, singular.replace("-", "_")})
                else:
                    family_aliases.add(f"{family}s")
                # Match if handler is in our files or family matches slug
                if (
                    bundle.handler_file in page_files
                    or bool(bucket_tokens & family_aliases)
                ):
                    lines.append(f"\n**Endpoint Family: {bundle.endpoint_family}**")
                    for mp in bundle.methods_paths:
                        lines.append(f"- {mp}")
                    lines.append(f"  Handler: `{bundle.handler_file}`")
                    if bundle.handler_symbols:
                        lines.append(
                            f"  Symbols: {', '.join(bundle.handler_symbols[:10])}"
                        )
                    if bundle.evidence:
                        lines.append("  Evidence chain:")
                        for eu in bundle.evidence[:8]:
                            lines.append(f"    - `{eu.file_path}` ({eu.role})")
                    if bundle.integration_edges:
                        lines.append(
                            f"  Integrations: {', '.join(bundle.integration_edges)}"
                        )

        # Fallback: raw endpoint data from scan
        if not lines:
            relevant_eps = [
                ep for ep in self.scan.api_endpoints if ep.get("file", "") in page_files
            ]
            for ep in relevant_eps:
                lines.append(
                    f"- {ep['method']} {ep['path']} → "
                    f"{ep.get('handler', '?')} (`{ep.get('file', '')}:{ep.get('line', 0)}`)"
                )

        return "\n".join(lines) if lines else ""

    # ── Integration context ──────────────────────────────────────────────

    def _build_integration_context(self, bucket: DocBucket) -> str:
        """Build integration identity context for this bucket.

        For integration buckets: full identity detail (the bucket IS about this integration).
        For feature/endpoint buckets: which integrations their files touch.
        """
        if not self.scan.integration_identities:
            return ""

        page_files = set(bucket.owned_files)
        lines: list[str] = []

        hints = bucket.generation_hints or {}
        for identity in self.scan.integration_identities:
            if hints.get("include_integration_detail"):
                # Match if slug contains the identity name
                if (
                    identity.name.lower() in bucket.slug.lower()
                    or identity.display_name.lower() in bucket.title.lower()
                    or any(f in page_files for f in identity.files)
                ):
                    lines.append(f"\n**Integration: {identity.display_name}**")
                    lines.append(f"Description: {identity.description}")
                    lines.append(f"Files involved: {', '.join(identity.files[:10])}")
                    lines.append(
                        f"Substantial: {'yes' if identity.is_substantial else 'no'}"
                    )
                    if identity.evidence:
                        lines.append("Evidence:")
                        for ev in identity.evidence[:8]:
                            if isinstance(ev, dict):
                                ev_type = ev.get("signal_type", "unknown")
                                ev_file = ev.get("file_path", "?")
                                ev_hint = ev.get("name_hint", "")
                                lines.append(
                                    f"  - [{ev_type}] {ev_hint} in `{ev_file}`"
                                )
                            else:
                                # Evidence stored as plain string
                                lines.append(f"  - {ev}")
            else:
                # For non-integration buckets, just list which integrations overlap
                overlap = set(identity.files) & page_files
                if overlap:
                    lines.append(
                        f"- **{identity.display_name}**: touches "
                        f"{', '.join(f'`{f}`' for f in sorted(overlap)[:5])}"
                    )

        return "\n".join(lines) if lines else ""

    # ── Giant-file cluster context ───────────────────────────────────────

    def _build_cluster_context(self, bucket: DocBucket) -> str:
        """If any of the bucket's files are giant-file-clustered, show the cluster breakdown."""
        if not self.scan.giant_file_clusters:
            return ""

        lines: list[str] = []
        for fpath in bucket.owned_files:
            analysis = self.scan.giant_file_clusters.get(fpath)
            if not analysis:
                continue
            lines.append(
                f"\n**Giant file: `{fpath}`** ({analysis.line_count} lines, "
                f"{analysis.total_symbols} symbols, {len(analysis.clusters)} clusters)"
            )
            for cluster in analysis.clusters:
                sym_list = ", ".join(cluster.symbols[:8])
                more = (
                    f" +{len(cluster.symbols) - 8} more"
                    if len(cluster.symbols) > 8
                    else ""
                )
                lines.append(f"  - **{cluster.cluster_name}**: {cluster.description}")
                lines.append(f"    Symbols: {sym_list}{more}")

        return "\n".join(lines) if lines else ""

    # ── Artifact context ─────────────────────────────────────────────────

    def _build_artifact_context(self, bucket: DocBucket) -> str:
        """Include content from artifact_refs (config, deploy, test files)."""
        if not bucket.artifact_refs:
            return ""

        lines: list[str] = []
        budget = self.NON_SOURCE_BUDGET
        used = 0

        for ar in bucket.artifact_refs:
            ar_path = self.repo_root / ar
            if not ar_path.exists():
                continue
            try:
                content = ar_path.read_text(encoding="utf-8", errors="replace")
                if used + len(content) > budget:
                    # Truncate
                    content = content[: budget - used] + "\n... [truncated]"
                lines.append(f"\n### Artifact: `{ar}`\n```\n{content}\n```")
                used += len(content)
                if used >= budget:
                    break
            except Exception:
                continue

        return "\n".join(lines) if lines else ""

    # ── Graph-lite context (static edges) ────────────────────────────────

    def _build_graph_context(self, bucket: DocBucket) -> str:
        """Build a static edge summary for diagram seeding.

        Edges come from:
        - Import relationships between bucket files and other files
        - Endpoint → handler → service chains
        - Integration edges from bundles
        """
        edges: list[str] = []
        page_files = set(bucket.owned_files)

        # Import edges
        for src_file in bucket.owned_files:
            parsed = self.scan.parsed_files.get(src_file)
            if not parsed or not parsed.imports:
                continue
            for imp in parsed.imports[:20]:
                # Simplify: just show the import as an edge
                edges.append(f"`{src_file}` → imports → `{imp}`")

        # Endpoint routing edges
        if self.scan.endpoint_bundles:
            for bundle in self.scan.endpoint_bundles:
                if bundle.handler_file in page_files:
                    for eu in bundle.evidence:
                        if eu.file_path != bundle.handler_file:
                            edges.append(
                                f"`{bundle.handler_file}` → {eu.role} → `{eu.file_path}`"
                            )

        if not edges:
            return ""

        # Deduplicate and cap
        seen: set[str] = set()
        unique: list[str] = []
        for e in edges:
            if e not in seen:
                seen.add(e)
                unique.append(e)
        unique = unique[:30]  # cap

        return (
            "**Static dependency edges** (use these to seed your Mermaid diagrams):\n"
            + "\n".join(f"- {e}" for e in unique)
        )

    # ── Cross-reference context ──────────────────────────────────────────

    def _build_cross_ref_context(self, bucket: DocBucket) -> str:
        """Find other buckets that share files with this one."""
        refs: dict[str, set[str]] = defaultdict(set)  # other_slug → shared files
        page_files = set(bucket.owned_files)

        for f in bucket.owned_files:
            for slug in self._file_to_buckets.get(f, []):
                if slug != bucket.slug:
                    refs[slug].add(f)

        if not refs:
            return ""

        lines = ["**Cross-references** (other doc pages sharing files with this one):"]
        for slug, shared in sorted(refs.items(), key=lambda x: -len(x[1])):
            other = self._slug_to_bucket.get(slug)
            if other:
                shared_list = ", ".join(f"`{f}`" for f in sorted(shared)[:4])
                lines.append(f"- [{other.title}](/{slug}) via {shared_list}")

        return "\n".join(lines)

    # ── Database/Schema context ──────────────────────────────────────────

    def _build_database_context(self, bucket: DocBucket) -> str:
        """Build database schema context for database-tagged buckets.

        Extracts model definitions, table structures, relationships, and
        migration info from the DatabaseScan attached to the artifact_scan.
        Only activates for buckets that look like database/model documentation.
        """
        # Only enrich buckets with database context hint
        hints = bucket.generation_hints or {}
        if not hints.get("include_database_context"):
            return ""

        # Get the database scan from artifact_scan
        artifact_scan = getattr(self.scan, "artifact_scan", None)
        if artifact_scan is None:
            return ""
        db_scan = getattr(artifact_scan, "database_scan", None)
        if db_scan is None or not (
            db_scan.model_files
            or db_scan.schema_files
            or getattr(db_scan, "knex_artifacts", [])
        ):
            return ""

        lines: list[str] = ["**Database Schema Information**\n"]
        hints = bucket.generation_hints or {}
        group_key = hints.get("database_group_key", "")

        # ORM framework
        if db_scan.orm_framework:
            lines.append(f"ORM Framework: **{db_scan.orm_framework}**")
            lines.append(f"Total Models Detected: **{db_scan.total_models}**\n")

        # Group overview for overview pages
        if hints.get("is_database_overview"):
            if getattr(db_scan, "groups", None):
                lines.append("### Database Groups\n")
                for group in db_scan.groups:
                    group_slug = f"database-{group.key}"
                    lines.append(
                        f"- [{group.label} Data Model](/{group_slug}): "
                        f"{len(group.file_paths)} file(s), "
                        f"{len(group.model_names)} model(s)"
                    )
                    if group.external_refs:
                        lines.append(
                            f"  External refs: {', '.join(f'`{ref}`' for ref in group.external_refs[:8])}"
                        )
            if db_scan.migration_files:
                lines.append("\n### Migration Files\n")
                for mig in db_scan.migration_files[:15]:
                    lines.append(f"- `{mig}`")
            if getattr(db_scan, "knex_artifacts", None):
                lines.append("\n### Knex Artifacts\n")
                for artifact in db_scan.knex_artifacts[:15]:
                    descriptor = artifact.table_name or artifact.file_path
                    lines.append(
                        f"- `{artifact.file_path}` ({artifact.artifact_type}: {descriptor})"
                    )
            if getattr(db_scan, "graphql_interfaces", None):
                lines.append("\n### GraphQL Interfaces Touching The Data Layer\n")
                for interface in db_scan.graphql_interfaces[:15]:
                    lines.append(f"- `{interface.name}` (`{interface.file_path}`)")
            return "\n".join(lines)

        group_files = set(bucket.owned_files)
        if hints.get("is_database_group") and group_key:
            for group in getattr(db_scan, "groups", []) or []:
                if group.key == group_key:
                    group_files = set(group.file_paths)
                    if group.external_refs:
                        lines.append("### Cross-Group References\n")
                        lines.extend(
                            f"- Related group: `{ref}`"
                            for ref in group.external_refs[:12]
                        )
                    break

        # Model files with extracted model names
        lines.append("### Model Definitions\n")
        for mf in db_scan.model_files:
            if mf.is_migration:
                continue
            if hints.get("is_database_group") and mf.file_path not in group_files:
                continue
            model_list = (
                ", ".join(mf.model_names[:20])
                if mf.model_names
                else "(no models extracted)"
            )
            lines.append(f"- `{mf.file_path}` ({mf.orm_framework}): {model_list}")

            # Try to include actual model source for richer context
            src_path = self.repo_root / mf.file_path
            if src_path.exists():
                try:
                    content = src_path.read_text(encoding="utf-8", errors="replace")
                    line_count = len(content.splitlines())
                    # Include full source for small files, summary for large
                    if line_count <= 300:
                        lines.append(f"\n```python\n# {mf.file_path}\n{content}\n```\n")
                    else:
                        # Extract class/model definitions only (first 50 lines of each class)
                        model_snippets = self._extract_model_snippets(
                            content, mf.model_names
                        )
                        if model_snippets:
                            lines.append(
                                f"\n```python\n# {mf.file_path} (key models)\n{model_snippets}\n```\n"
                            )
                except Exception:
                    pass

        # Knex artifacts relevant to the current page
        page_knex = [
            artifact
            for artifact in getattr(db_scan, "knex_artifacts", []) or []
            if artifact.file_path in set(bucket.owned_files)
        ]
        if page_knex:
            lines.append("\n### Knex Schema & Query Evidence\n")
            for artifact in page_knex[:20]:
                table_display = artifact.table_name or "(unknown table)"
                lines.append(
                    f"- `{artifact.file_path}` [{artifact.artifact_type}] table={table_display}"
                )
                if artifact.columns:
                    lines.append(f"  Columns: {', '.join(artifact.columns[:12])}")
                if artifact.foreign_keys:
                    lines.append(
                        f"  Foreign keys: {', '.join(artifact.foreign_keys[:8])}"
                    )
                if artifact.query_patterns:
                    lines.append(
                        f"  Query patterns: {', '.join(artifact.query_patterns[:4])}"
                    )

        # Migration files
        if db_scan.migration_files:
            lines.append("\n### Migrations\n")
            for mig in db_scan.migration_files[:15]:
                lines.append(f"- `{mig}`")

        # Schema definition files (Prisma, GraphQL, etc.)
        if db_scan.schema_files:
            lines.append("\n### Schema Definition Files\n")
            for sf in db_scan.schema_files:
                lines.append(f"- `{sf}`")
                src_path = self.repo_root / sf
                if src_path.exists():
                    try:
                        content = src_path.read_text(encoding="utf-8", errors="replace")
                        if len(content) < 10_000:
                            lines.append(f"\n```\n{content}\n```\n")
                    except Exception:
                        pass

        return "\n".join(lines)

    def _build_runtime_context(self, bucket: DocBucket) -> str:
        hints = bucket.generation_hints or {}
        if not hints.get("include_runtime_context"):
            return ""

        runtime_scan = getattr(self.scan, "runtime_scan", None)
        if runtime_scan is None:
            return ""

        lines: list[str] = ["**Runtime Surface Information**\n"]
        owned_files = set(bucket.owned_files)
        group_kind = hints.get("runtime_group_kind", "")

        tasks = list(getattr(runtime_scan, "tasks", []) or [])
        schedulers = list(getattr(runtime_scan, "schedulers", []) or [])
        consumers = list(getattr(runtime_scan, "realtime_consumers", []) or [])

        if hints.get("is_runtime_overview"):
            lines.append(
                f"Tasks: **{len(tasks)}**, Schedulers: **{len(schedulers)}**, Realtime consumers: **{len(consumers)}**"
            )
        else:
            if group_kind == "celery":
                tasks = [
                    task
                    for task in tasks
                    if task.file_path in owned_files and task.runtime_kind == "celery"
                ]
                schedulers = [
                    item
                    for item in schedulers
                    if item.file_path in owned_files
                    or item.scheduler_type in {"beat", "crontab"}
                ]
                consumers = []
            elif group_kind == "django":
                tasks = [
                    task
                    for task in tasks
                    if task.file_path in owned_files
                    and task.runtime_kind in {"django_command", "django_signal"}
                ]
                schedulers = []
                consumers = []
            elif group_kind == "laravel":
                tasks = [
                    task
                    for task in tasks
                    if task.file_path in owned_files
                    and task.runtime_kind.startswith("laravel_")
                ]
                schedulers = [
                    item
                    for item in schedulers
                    if item.file_path in owned_files
                    and item.scheduler_type == "laravel_schedule"
                ]
                consumers = []
            elif group_kind == "workers":
                tasks = [
                    task
                    for task in tasks
                    if task.file_path in owned_files
                    and task.runtime_kind
                    not in {"celery", "django_command", "django_signal"}
                    and not task.runtime_kind.startswith("laravel_")
                ]
                schedulers = [
                    item for item in schedulers if item.file_path in owned_files
                ]
                consumers = [
                    item for item in consumers if item.file_path in owned_files
                ]
            elif group_kind == "schedulers":
                schedulers = [
                    item for item in schedulers if item.file_path in owned_files
                ]
                tasks = [
                    task
                    for task in tasks
                    if task.file_path in owned_files and task.schedule_sources
                ]
                consumers = []
            elif group_kind == "realtime":
                consumers = [
                    item for item in consumers if item.file_path in owned_files
                ]
                tasks = []
                schedulers = []

        if tasks:
            lines.append("\n### Tasks\n")
            for task in tasks[:40]:
                detail = [f"`{task.name}` (`{task.file_path}`)"]
                if task.queue:
                    detail.append(f"queue={task.queue}")
                if task.retry_policy:
                    detail.append(f"retry={task.retry_policy}")
                runtime_kind = getattr(task, "runtime_kind", "")
                if runtime_kind and runtime_kind != "celery":
                    detail.append(f"kind={runtime_kind}")
                if getattr(task, "decorator", ""):
                    detail.append(f"source={task.decorator}")
                if getattr(task, "schedule_sources", []):
                    detail.append(f"schedule={'; '.join(task.schedule_sources[:2])}")
                if getattr(task, "triggers", []):
                    detail.append(f"triggers={', '.join(task.triggers[:3])}")
                if getattr(task, "producer_files", []):
                    detail.append(f"producers={', '.join(task.producer_files[:3])}")
                if getattr(task, "linked_endpoints", []):
                    detail.append(f"endpoints={', '.join(task.linked_endpoints[:3])}")
                lines.append("- " + " | ".join(detail))

        if schedulers:
            lines.append("\n### Schedulers\n")
            for scheduler in schedulers[:30]:
                detail = [
                    f"`{scheduler.name}` (`{scheduler.file_path}`)",
                    scheduler.scheduler_type,
                ]
                if scheduler.cron:
                    detail.append(f"cron={scheduler.cron}")
                if getattr(scheduler, "invoked_targets", []):
                    detail.append(f"targets={', '.join(scheduler.invoked_targets[:4])}")
                if getattr(scheduler, "linked_endpoints", []):
                    detail.append(
                        f"endpoints={', '.join(scheduler.linked_endpoints[:3])}"
                    )
                lines.append("- " + " | ".join(detail))

        if consumers:
            lines.append("\n### Realtime Consumers\n")
            for consumer in consumers[:30]:
                detail = [
                    f"`{consumer.name}` (`{consumer.file_path}`)",
                    consumer.consumer_type,
                ]
                if consumer.routes:
                    detail.append(f"routes={', '.join(consumer.routes[:3])}")
                if consumer.groups:
                    detail.append(f"groups={', '.join(consumer.groups[:4])}")
                if consumer.auth_hints:
                    detail.append(f"auth={', '.join(consumer.auth_hints[:3])}")
                lines.append("- " + " | ".join(detail))

        return "\n".join(lines) if len(lines) > 1 else ""

    def _build_plan_summary_context(self, bucket: DocBucket) -> str:
        """Build repo-wide planning context for the landing page."""
        hints = bucket.generation_hints or {}
        if not hints.get("is_introduction_page"):
            return ""

        lines: list[str] = [
            "This is the landing page. Use this summary to explain the system from end to end.",
        ]

        if self.scan.languages:
            languages = ", ".join(
                f"{name} ({count})"
                for name, count in sorted(self.scan.languages.items())
            )
            lines.append(f"Languages detected: {languages}")
        if self.scan.frameworks_detected:
            lines.append(
                "Frameworks detected: "
                + ", ".join(sorted(self.scan.frameworks_detected))
            )
        if self.scan.entry_points:
            lines.append(
                "Primary entry points: "
                + ", ".join(f"`{path}`" for path in self.scan.entry_points[:8])
            )
        if self.scan.config_files:
            lines.append(
                "Key config files: "
                + ", ".join(f"`{path}`" for path in self.scan.config_files[:8])
            )

        if self.plan.nav_structure:
            lines.append("\n## Planned Documentation Map")
            for section, slugs in self.plan.nav_structure.items():
                section_lines: list[str] = []
                for slug in slugs[:8]:
                    page = self._slug_to_bucket.get(slug)
                    if not page:
                        continue
                    section_lines.append(
                        f"- {page.title} (`/{page.slug}`): {page.description}"
                    )
                if section_lines:
                    lines.append(f"\n### {section}")
                    lines.extend(section_lines)

        integration_pages = [
            page
            for page in self.plan.buckets
            if page.bucket_type == "integration" or "integration" in page.slug
        ]
        if integration_pages:
            lines.append("\n## Major Integrations")
            for page in integration_pages[:8]:
                lines.append(f"- {page.title} (`/{page.slug}`): {page.description}")

        workflow_pages = [
            page
            for page in self.plan.buckets
            if page.bucket_type == "feature"
            or any(
                token in page.slug
                for token in (
                    "workflow",
                    "flow",
                    "process",
                    "management",
                    "tracking",
                )
            )
        ]
        if workflow_pages:
            lines.append("\n## Major Workflows Or Domains")
            for page in workflow_pages[:10]:
                lines.append(f"- {page.title} (`/{page.slug}`): {page.description}")

        published_endpoints = [
            ep for ep in self.scan.api_endpoints if ep.get("publication_ready", True)
        ]
        if published_endpoints:
            lines.append("\n## Runtime API Surfaces")
            for ep in published_endpoints[:12]:
                lines.append(
                    f"- {ep.get('method', '').upper()} {ep.get('path', '')} "
                    f"→ `{ep.get('handler_file') or ep.get('file') or '?'}`"
                )

        return "\n".join(lines)

    @staticmethod
    def _extract_model_snippets(content: str, model_names: list[str]) -> str:
        """Extract model class definitions from source for database context."""
        if not model_names:
            return ""

        src_lines = content.splitlines()
        snippets: list[str] = []
        total_chars = 0
        max_chars = 15_000

        for model_name in model_names:
            if total_chars >= max_chars:
                break
            # Find class definition
            for i, line in enumerate(src_lines):
                if f"class {model_name}" in line:
                    # Grab up to 40 lines of the class body
                    end = min(i + 40, len(src_lines))
                    block = "\n".join(src_lines[i:end])
                    snippets.append(block)
                    total_chars += len(block)
                    break

        return "\n\n".join(snippets)
