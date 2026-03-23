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
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from .llm import LLMClient
from .parser import parse_file, supported_extensions
from .parser.base import ParsedFile, Symbol
from .planner_v2 import DocBucket, DocPlan, RepoScan, _BucketAsPage
from .prompts_v2 import SYSTEM_V2, get_prompt_for_page_type

console = Console()

# ═════════════════════════════════════════════════════════════════════════════
# 3.1  Evidence Assembly
# ═════════════════════════════════════════════════════════════════════════════


@dataclass
class AssembledEvidence:
    """All evidence gathered for a single bucket, ready for prompt injection."""
    bucket: DocBucket
    source_context: str              # tiered source code
    endpoints_detail: str            # endpoint listing (for endpoint/feature buckets)
    integration_context: str         # integration identity info
    cluster_context: str             # giant-file cluster info
    artifact_context: str            # setup/deploy/test file content
    graph_context: str               # static edges for diagram seeds
    cross_ref_context: str           # which other buckets reference this one's files
    database_context: str = ""       # database/schema info for database-type buckets
    total_evidence_chars: int = 0
    files_included: int = 0
    files_omitted: int = 0


class EvidenceAssembler:
    """Gathers and formats evidence for a single bucket from the full scan output.

    The assembler is bucket-type-aware: endpoint buckets get richer endpoint detail,
    integration buckets get integration identity context, etc.
    """

    # Total char budget for source context per page
    SOURCE_BUDGET = 80_000
    # How many chars to reserve for non-source evidence
    NON_SOURCE_BUDGET = 15_000

    def __init__(self, repo_root: Path, scan: RepoScan, plan: DocPlan, cfg: dict[str, Any]):
        self.repo_root = repo_root
        self.scan = scan
        self.plan = plan
        self.cfg = cfg
        # Pre-index: file → bucket slugs for cross-referencing
        self._file_to_buckets: dict[str, list[str]] = defaultdict(list)
        for b in plan.buckets:
            for f in b.owned_files:
                self._file_to_buckets[f].append(b.slug)
        # Pre-index: slug → bucket
        self._slug_to_bucket: dict[str, DocBucket] = {b.slug: b for b in plan.buckets}

    def assemble(self, bucket: DocBucket) -> AssembledEvidence:
        """Build the complete evidence package for one bucket."""
        source_ctx, files_included, files_omitted = self._build_source_context(bucket)
        endpoints_detail = self._build_endpoints_detail(bucket)
        integration_ctx = self._build_integration_context(bucket)
        cluster_ctx = self._build_cluster_context(bucket)
        artifact_ctx = self._build_artifact_context(bucket)
        graph_ctx = self._build_graph_context(bucket)
        cross_ref_ctx = self._build_cross_ref_context(bucket)
        database_ctx = self._build_database_context(bucket)

        total = sum(len(s) for s in [source_ctx, endpoints_detail, integration_ctx,
                                      cluster_ctx, artifact_ctx, graph_ctx, cross_ref_ctx,
                                      database_ctx])

        return AssembledEvidence(
            bucket=bucket,
            source_context=source_ctx,
            endpoints_detail=endpoints_detail,
            integration_context=integration_ctx,
            cluster_context=cluster_ctx,
            artifact_context=artifact_ctx,
            graph_context=graph_ctx,
            cross_ref_context=cross_ref_ctx,
            database_context=database_ctx,
            total_evidence_chars=total,
            files_included=files_included,
            files_omitted=files_omitted,
        )

    # ── Source context (tiered) ──────────────────────────────────────────

    def _build_source_context(self, bucket: DocBucket) -> tuple[str, int, int]:
        """Build tiered source context for the bucket's owned files.

        Tier 1 (≤200 lines): full source
        Tier 2 (201-500 lines): signatures + docstrings + first body lines
        Tier 3 (>500 lines): header + key symbol signatures
          - If giant-file clusters exist, include only symbols from relevant clusters

        Returns (context_str, files_included, files_omitted).
        """
        max_chars = self.SOURCE_BUDGET
        total_chars = 0
        parts: list[str] = []
        included = 0
        omitted = 0

        # Collect all files: owned_files + artifact_refs
        all_files = list(bucket.owned_files)
        for ar in bucket.artifact_refs:
            if ar not in all_files:
                all_files.append(ar)

        # Load file data, sort smallest first for maximum inclusion
        files_data: list[tuple[str, str, int, ParsedFile | None]] = []
        for src_file in all_files:
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

        files_data.sort(key=lambda x: x[2])  # smallest first

        # If bucket has owned_symbols, we can filter giant file content
        owned_symbols_set = set(bucket.owned_symbols) if bucket.owned_symbols else set()

        for src_file, content, line_count, parsed in files_data:
            lang = parsed.language if parsed else ""

            # Build header block
            header = f"\n### File: `{src_file}` ({line_count} lines)\n"
            if parsed and parsed.symbols:
                header += "**Symbols:**\n"
                for s in parsed.symbols:
                    # If we have owned_symbols, mark which ones are relevant
                    marker = " ⭐" if owned_symbols_set and s.name in owned_symbols_set else ""
                    header += f"- {s.kind} `{s.name}` (line {s.start_line}){marker}"
                    if s.docstring:
                        header += f": {s.docstring[:150]}"
                    header += "\n"
                header += "\n"
            if parsed and parsed.imports:
                header += f"**Imports**: {', '.join(parsed.imports[:15])}\n\n"

            # Choose tier
            if line_count <= 200:
                code = content
            elif line_count <= 500:
                code = self._extract_signatures(parsed, content)
            else:
                # Tier 3 — if giant file with clusters, focus on relevant symbols
                code = self._extract_key_sections(
                    parsed, content, src_file, owned_symbols_set
                )

            remaining = max_chars - total_chars - len(header)
            if remaining <= 200:
                omitted += 1
                parts.append(header + "> *[Source omitted — context budget reached.]*\n")
                continue

            if len(code) > remaining:
                code = code[:remaining] + "\n... [truncated — file continues]"

            file_section = header + f"```{lang}\n{code}\n```\n"
            parts.append(file_section)
            total_chars += len(file_section)
            included += 1

        return "\n".join(parts), included, omitted

    def _extract_signatures(self, parsed: ParsedFile | None, content: str) -> str:
        """Tier 2: signatures + up to 10 body lines each."""
        if not parsed or not parsed.symbols:
            lines = content.splitlines()
            return "\n".join(lines[:100]) + ("\n... [truncated]" if len(lines) > 100 else "")

        content_lines = content.splitlines()
        result: list[str] = []
        seen: set[int] = set()

        for symbol in parsed.symbols:
            start = max(0, symbol.start_line - 1)
            end = min(start + 12, len(content_lines))
            for i in range(start, end):
                if i not in seen:
                    result.append(content_lines[i])
                    seen.add(i)
            if end < len(content_lines) and end not in seen:
                result.append("    ...")

        return "\n".join(result)

    def _extract_key_sections(
        self,
        parsed: ParsedFile | None,
        content: str,
        file_path: str,
        owned_symbols: set[str],
    ) -> str:
        """Tier 3: header + key symbol signatures, optionally filtered by owned_symbols."""
        lines = content.splitlines()
        header = "\n".join(lines[:30])

        if not parsed or not parsed.symbols:
            return header + "\n... [large file — see symbol list above]"

        # If we have owned_symbols AND this is a giant file with clusters,
        # prioritize showing those symbols
        symbols_to_show = parsed.symbols
        if owned_symbols:
            priority = [s for s in parsed.symbols if s.name in owned_symbols]
            others = [s for s in parsed.symbols if s.name not in owned_symbols]
            # Show priority symbols first, then fill with others up to 25
            symbols_to_show = priority + others[:max(0, 25 - len(priority))]
        else:
            symbols_to_show = parsed.symbols[:25]

        sig_lines: list[str] = ["\n\n# [Key Symbol Signatures]"]
        for symbol in symbols_to_show:
            start = max(0, symbol.start_line - 1)
            end = min(start + 5, len(lines))
            marker = " [OWNED]" if symbol.name in owned_symbols else ""
            sig_lines.append(f"\n# {symbol.kind}: {symbol.name}{marker}")
            sig_lines.extend(lines[start:end])
            sig_lines.append("    ...")

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
        if bucket.bucket_type not in ("endpoint", "endpoint_ref", "feature"):
            return ""

        page_files = set(bucket.owned_files)
        page_symbols = set(bucket.owned_symbols)
        lines: list[str] = []

        # ── endpoint_ref: match specific endpoint, pull deep evidence ─────
        if bucket.bucket_type == "endpoint_ref":
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
                        if ref_method and ref_path and ref_method in mp and ref_path in mp:
                            matched_bundle = bundle
                            break
                    if matched_bundle:
                        break

            if matched_bundle:
                lines.append(f"**Endpoint: {bucket.title}**")
                lines.append(f"  Handler file: `{matched_bundle.handler_file}`")
                if matched_bundle.handler_symbols:
                    lines.append(f"  Handler functions: {', '.join(matched_bundle.handler_symbols)}")
                lines.append(f"  Family: {matched_bundle.endpoint_family}")
                if matched_bundle.evidence:
                    lines.append("\n  **Evidence chain** (files involved in this endpoint's flow):")
                    for eu in matched_bundle.evidence:
                        syms = f" — symbols: {', '.join(eu.symbols[:5])}" if eu.symbols else ""
                        lines.append(f"    - `{eu.file_path}` ({eu.role}){syms}")
                    # Also add evidence files to source context by injecting them into owned_files
                    # (non-destructive: only for this assembly run)
                    for eu in matched_bundle.evidence:
                        if eu.file_path not in bucket.owned_files:
                            bucket.owned_files.append(eu.file_path)
                if matched_bundle.integration_edges:
                    lines.append(f"  Integrations touched: {', '.join(matched_bundle.integration_edges)}")
            else:
                # Fallback: raw endpoint data matching this handler
                for ep in self.scan.api_endpoints:
                    ep_handler = ep.get("handler", "")
                    ep_method = ep.get("method", "").upper()
                    ep_path = ep.get("path", "")
                    if ((ep_handler and ep_handler in page_symbols) or
                            (ref_method == ep_method and ref_path == ep_path)):
                        lines.append(
                            f"- {ep_method} {ep_path} → "
                            f"{ep_handler} (`{ep.get('file', '')}:{ep.get('line', 0)}`)"
                        )
            return "\n".join(lines) if lines else ""

        # ── endpoint / feature: family-level evidence ─────────────────────
        # Check endpoint bundles first (richer evidence)
        if self.scan.endpoint_bundles:
            for bundle in self.scan.endpoint_bundles:
                # Match if handler is in our files or family matches slug
                if (bundle.handler_file in page_files or
                        bundle.endpoint_family.lower() in bucket.slug.lower()):
                    lines.append(f"\n**Endpoint Family: {bundle.endpoint_family}**")
                    for mp in bundle.methods_paths:
                        lines.append(f"- {mp}")
                    lines.append(f"  Handler: `{bundle.handler_file}`")
                    if bundle.handler_symbols:
                        lines.append(f"  Symbols: {', '.join(bundle.handler_symbols[:10])}")
                    if bundle.evidence:
                        lines.append("  Evidence chain:")
                        for eu in bundle.evidence[:8]:
                            lines.append(f"    - `{eu.file_path}` ({eu.role})")
                    if bundle.integration_edges:
                        lines.append(f"  Integrations: {', '.join(bundle.integration_edges)}")

        # Fallback: raw endpoint data from scan
        if not lines:
            relevant_eps = [
                ep for ep in self.scan.api_endpoints
                if ep.get("file", "") in page_files
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

        for identity in self.scan.integration_identities:
            if bucket.bucket_type == "integration":
                # Match if slug contains the identity name
                if (identity.name.lower() in bucket.slug.lower() or
                        identity.display_name.lower() in bucket.title.lower() or
                        any(f in page_files for f in identity.files)):
                    lines.append(f"\n**Integration: {identity.display_name}**")
                    lines.append(f"Description: {identity.description}")
                    lines.append(f"Files involved: {', '.join(identity.files[:10])}")
                    lines.append(f"Substantial: {'yes' if identity.is_substantial else 'no'}")
                    if identity.evidence:
                        lines.append("Evidence:")
                        for ev in identity.evidence[:8]:
                            if isinstance(ev, dict):
                                ev_type = ev.get("signal_type", "unknown")
                                ev_file = ev.get("file_path", "?")
                                ev_hint = ev.get("name_hint", "")
                                lines.append(f"  - [{ev_type}] {ev_hint} in `{ev_file}`")
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
            lines.append(f"\n**Giant file: `{fpath}`** ({analysis.line_count} lines, "
                         f"{analysis.total_symbols} symbols, {len(analysis.clusters)} clusters)")
            for cluster in analysis.clusters:
                sym_list = ", ".join(cluster.symbols[:8])
                more = f" +{len(cluster.symbols) - 8} more" if len(cluster.symbols) > 8 else ""
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
                    content = content[:budget - used] + "\n... [truncated]"
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
                lines.append(f"- [{other.title}]({slug}.md) via {shared_list}")

        return "\n".join(lines)

    # ── Database/Schema context ──────────────────────────────────────────

    def _build_database_context(self, bucket: DocBucket) -> str:
        """Build database schema context for database-tagged buckets.

        Extracts model definitions, table structures, relationships, and
        migration info from the DatabaseScan attached to the artifact_scan.
        Only activates for buckets that look like database/model documentation.
        """
        # Only enrich database-relevant buckets
        db_keywords = ("database", "data model", "schema", "model", "table", "orm")
        is_db_bucket = (
            bucket.bucket_type == "system"
            and any(kw in bucket.title.lower() or kw in bucket.slug.lower() for kw in db_keywords)
        ) or bucket.bucket_type == "database"
        if not is_db_bucket:
            return ""

        # Get the database scan from artifact_scan
        artifact_scan = getattr(self.scan, "artifact_scan", None)
        if artifact_scan is None:
            return ""
        db_scan = getattr(artifact_scan, "database_scan", None)
        if db_scan is None or not db_scan.model_files:
            return ""

        lines: list[str] = ["**Database Schema Information**\n"]

        # ORM framework
        if db_scan.orm_framework:
            lines.append(f"ORM Framework: **{db_scan.orm_framework}**")
            lines.append(f"Total Models Detected: **{db_scan.total_models}**\n")

        # Model files with extracted model names
        lines.append("### Model Definitions\n")
        for mf in db_scan.model_files:
            if mf.is_migration:
                continue
            model_list = ", ".join(mf.model_names[:20]) if mf.model_names else "(no models extracted)"
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
                        model_snippets = self._extract_model_snippets(content, mf.model_names)
                        if model_snippets:
                            lines.append(f"\n```python\n# {mf.file_path} (key models)\n{model_snippets}\n```\n")
                except Exception:
                    pass

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


# ═════════════════════════════════════════════════════════════════════════════
# 3.2  Single-Pass Page Generation
# ═════════════════════════════════════════════════════════════════════════════


class PageGenerator:
    """Generates a single doc page from assembled evidence in one LLM pass."""

    def __init__(self, llm: LLMClient, cfg: dict[str, Any], repo_root: Path):
        self.llm = llm
        self.cfg = cfg
        self.repo_root = repo_root

    def generate(
        self,
        evidence: AssembledEvidence,
        sitemap_context: str,
        dependency_links: str,
        openapi_context: str = "",
    ) -> str:
        """Generate the complete page from evidence. Returns markdown string."""
        bucket = evidence.bucket

        # Route system buckets about the database to the dedicated database prompt
        effective_type = bucket.bucket_type
        if bucket.bucket_type == "system":
            db_keywords = ("database", "data model", "schema", "model", "table", "orm")
            if any(kw in bucket.title.lower() or kw in bucket.slug.lower() for kw in db_keywords):
                effective_type = "database"

        prompt_template = get_prompt_for_page_type(effective_type)

        # Compose the enriched source context
        full_source = evidence.source_context
        if evidence.cluster_context:
            full_source += f"\n\n## Giant File Clusters\n{evidence.cluster_context}"
        if evidence.integration_context:
            full_source += f"\n\n## Integration Context\n{evidence.integration_context}"
        if evidence.database_context:
            full_source += f"\n\n## Database Schema\n{evidence.database_context}"
        if evidence.artifact_context:
            full_source += f"\n\n## Artifacts\n{evidence.artifact_context}"
        if evidence.graph_context:
            full_source += f"\n\n## Dependency Graph\n{evidence.graph_context}"
        if evidence.cross_ref_context:
            full_source += f"\n\n{evidence.cross_ref_context}"

        # Format required sections/diagrams/coverage
        required_sections = (
            ", ".join(bucket.required_sections) if bucket.required_sections else "default"
        )
        required_diagrams = (
            ", ".join(bucket.required_diagrams) if bucket.required_diagrams else "architecture_flow"
        )
        coverage_targets = (
            ", ".join(bucket.coverage_targets) if bucket.coverage_targets else ""
        )

        # Resource group for endpoint pages
        resource_group = bucket.slug.replace("-api", "").replace("-", " ").title()

        user_prompt = prompt_template.format(
            title=bucket.title,
            project_name=self.cfg.get("project_name", self.repo_root.name),
            description=self.cfg.get("description", ""),
            page_description=bucket.description,
            languages=", ".join(
                k for k in (self.cfg.get("languages") or ["python", "javascript"])
            ),
            frameworks="",
            source_context=full_source,
            endpoints_detail=evidence.endpoints_detail,
            openapi_context=openapi_context,
            resource_group=resource_group,
            required_sections=required_sections,
            required_diagrams=required_diagrams,
            coverage_targets=coverage_targets,
            sitemap_context=sitemap_context,
            dependency_links=dependency_links,
        )

        return self.llm.complete(SYSTEM_V2, user_prompt)


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


class PageValidator:
    """Validates generated markdown against bucket requirements."""

    def __init__(self, repo_root: Path, scan: RepoScan):
        self.repo_root = repo_root
        self.known_files = set(scan.file_summaries.keys())

    def validate(self, content: str, bucket: DocBucket) -> ValidationResult:
        """Run all validation checks on generated content."""
        result = ValidationResult(is_valid=True)
        result.word_count = len(content.split())

        # 1. Check required sections appear as headings
        self._check_sections(content, bucket, result)

        # 2. Check that owned files are referenced
        self._check_file_refs(content, bucket, result)

        # 3. Check for hallucinated file paths
        self._check_hallucinated_paths(content, result)

        # 4. Count mermaid diagrams
        result.mermaid_block_count = len(re.findall(r"```mermaid", content))

        # 5. Minimum content check
        if result.word_count < 100:
            result.warnings.append("Very short page (<100 words) — may be incomplete")
            result.is_valid = False

        # 6. Check for required diagrams
        if bucket.required_diagrams and result.mermaid_block_count == 0:
            result.warnings.append(
                f"No Mermaid diagrams found but required: {', '.join(bucket.required_diagrams)}"
            )

        return result

    def _check_sections(self, content: str, bucket: DocBucket, result: ValidationResult):
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
                section_lower in h or
                all(word in h for word in section_lower.split())
                for h in headings
            )
            if not found:
                result.missing_sections.append(section)

        if result.missing_sections:
            result.warnings.append(
                f"Missing sections: {', '.join(result.missing_sections)}"
            )

    def _check_file_refs(self, content: str, bucket: DocBucket, result: ValidationResult):
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
        refs = re.findall(r"`([a-zA-Z][a-zA-Z0-9_./-]*\.[a-zA-Z]{1,8})(?::\d+)?`", content)
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


# ═════════════════════════════════════════════════════════════════════════════
# 3.4  Mermaid Post-Processing
# ═════════════════════════════════════════════════════════════════════════════


def fix_mermaid_diagrams(content: str) -> str:
    """Find and fix common LLM Mermaid syntax errors in generated markdown."""

    def fix_block(match: re.Match) -> str:
        diagram = match.group(1)
        fixed = _fix_mermaid_diagram(diagram)
        return f"```mermaid\n{fixed}\n```"

    return re.sub(r"```mermaid\n(.*?)\n```", fix_block, content, flags=re.DOTALL)


def _fix_mermaid_diagram(diagram: str) -> str:
    """Fix the most common Mermaid mistakes LLMs make."""
    lines = diagram.splitlines()
    fixed: list[str] = []
    diagram_type = ""

    for line in lines:
        stripped = line.strip().lower()

        if not diagram_type and stripped:
            for dtype in ("flowchart", "graph", "sequencediagram", "classdiagram",
                          "erdiagram", "gantt", "pie", "statediagram"):
                if stripped.startswith(dtype):
                    diagram_type = dtype
                    break

        # Fix: Unquoted labels with parentheses in flowchart
        if diagram_type in ("flowchart", "graph", ""):
            line = re.sub(
                r'\b(\w[\w-]*)\(([^()]*\([^()]*\)[^()]*)\)',
                lambda m: f'{m.group(1)}["{m.group(2)}"]',
                line,
            )

        # Fix: Node labels with colons not in quotes
        line = re.sub(
            r'\[([^\]"]*:[^\]"]*)\]',
            lambda m: (f'["{m.group(1)}"]'
                       if ":" in m.group(1) and not m.group(1).startswith('"')
                       else f'[{m.group(1)}]'),
            line,
        )

        # Fix: classDiagram -> instead of --
        if diagram_type == "classdiagram":
            line = re.sub(r'\s+->\s+', ' --> ', line)

        fixed.append(line)

    result = "\n".join(fixed)

    # Warn about duplicate node IDs
    if diagram_type in ("flowchart", "graph"):
        node_ids = re.findall(r'\b([A-Za-z][\w-]*)\s*[\[({\|]', result)
        seen: set[str] = set()
        dupes: list[str] = []
        for nid in node_ids:
            if nid in seen:
                dupes.append(nid)
            seen.add(nid)
        if dupes:
            result = f"%% Note: possible duplicate node IDs: {', '.join(set(dupes))}\n" + result

    return result


def fix_file_references(content: str, repo_root: Path, known_files: set[str],
                        page_files: list[str]) -> str:
    """Remove hallucinated file:line refs, fix out-of-range line numbers."""
    file_line_counts: dict[str, int] = {}

    def get_line_count(path: str) -> int:
        if path not in file_line_counts:
            try:
                text = (repo_root / path).read_text(encoding="utf-8", errors="replace")
                file_line_counts[path] = len(text.splitlines())
            except Exception:
                file_line_counts[path] = 0
        return file_line_counts[path]

    def fix_ref(match: re.Match) -> str:
        path = match.group(1)
        line_str = match.group(2)

        if path not in known_files and not (repo_root / path).exists():
            return f"`{path}`"

        if line_str:
            try:
                line_num = int(line_str)
                total = get_line_count(path)
                if total > 0 and line_num > total:
                    return f"`{path}`"
            except ValueError:
                pass

        return match.group(0)

    return re.sub(
        r"`([a-zA-Z][a-zA-Z0-9_./-]*\.[a-zA-Z]{1,8}):(\d+)`",
        fix_ref,
        content,
    )


# ═════════════════════════════════════════════════════════════════════════════
# 3.5  Parallel Generation Orchestrator
# ═════════════════════════════════════════════════════════════════════════════

# Rate limiting constants — tuned for provisioned providers (Azure PTU, etc.)
# Override via .codewiki.yaml: batch_size, max_parallel_workers
BATCH_SIZE = 10
RATE_LIMIT_PAUSE = 0.5          # seconds between batches (Azure rarely 429s within quota)
RATE_LIMIT_BACKOFF = 3.0        # initial backoff on 429; doubles each retry
MAX_RETRIES = 5
MAX_PARALLEL_WORKERS = 6        # LLM concurrency — safe for most Azure/OpenAI deployments


@dataclass
class GenerationResult:
    """Result of generating a single page."""
    bucket: DocBucket
    content: str | None = None
    validation: ValidationResult | None = None
    error: str | None = None
    elapsed_seconds: float = 0.0
    retries: int = 0


class BucketGenerationEngine:
    """Orchestrates parallel generation of all bucket pages with evidence assembly,
    single-pass generation, validation, post-processing, and graceful degradation.
    """

    def __init__(
        self,
        repo_root: Path,
        cfg: dict[str, Any],
        llm: LLMClient,
        scan: RepoScan,
        plan: DocPlan,
        output_dir: Path,
    ):
        self.repo_root = repo_root
        self.cfg = cfg
        self.llm = llm
        self.scan = scan
        self.plan = plan
        self.output_dir = output_dir
        self.assembler = EvidenceAssembler(repo_root, scan, plan, cfg)
        self.generator = PageGenerator(llm, cfg, repo_root)
        self.validator = PageValidator(repo_root, scan)
        self.max_workers = cfg.get("max_parallel_workers", MAX_PARALLEL_WORKERS)
        self.batch_size = cfg.get("batch_size", BATCH_SIZE)

    def generate_all(self, force: bool = False) -> list[GenerationResult]:
        """Generate all pages. Returns results for each bucket.

        Strategy:
        - Sort buckets by priority
        - Within each priority group, generate pages in parallel
        - Apply rate limiting between batches
        - Validate and post-process each result
        """
        results: list[GenerationResult] = []
        buckets = sorted(self.plan.buckets, key=lambda b: b.priority)

        # Pre-build sitemap context (shared across all pages)
        sitemap_by_slug = self._precompute_sitemaps()

        total = len(buckets)
        generated_count = 0
        failed_count = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Generating pages...", total=total)

            # Process in batches for rate limiting
            for batch_start in range(0, total, self.batch_size):
                batch = buckets[batch_start:batch_start + self.batch_size]

                # Use thread pool for parallel LLM calls within batch
                with ThreadPoolExecutor(max_workers=min(self.max_workers, len(batch))) as executor:
                    futures = {}
                    for bucket in batch:
                        progress.update(task, description=f"[dim]Queuing {bucket.title}...[/dim]")

                        # Check staleness
                        if not force and not self._bucket_is_stale(bucket):
                            results.append(GenerationResult(bucket=bucket, content=None))
                            progress.advance(task)
                            continue

                        future = executor.submit(
                            self._generate_one,
                            bucket,
                            sitemap_by_slug.get(bucket.slug, ("", "")),
                        )
                        futures[future] = bucket

                    # Collect results as they complete
                    for future in as_completed(futures):
                        bucket = futures[future]
                        try:
                            result = future.result()
                            results.append(result)

                            if result.error:
                                failed_count += 1
                                console.print(
                                    f"  [red]✗[/red] [bold]{bucket.title}[/bold]: {result.error}"
                                )
                            elif result.content:
                                generated_count += 1
                                word_count = len(result.content.split())
                                v = result.validation
                                warnings = ""
                                if v and v.warnings:
                                    warnings = f" [yellow]⚠ {len(v.warnings)} warning(s)[/yellow]"
                                diagrams = f" {v.mermaid_block_count}🔀" if v else ""
                                console.print(
                                    f"  [green]✓[/green] [bold]{bucket.title}[/bold] "
                                    f"[dim]({bucket.bucket_type} · "
                                    f"{len(bucket.owned_files)} files · "
                                    f"~{word_count} words{diagrams} · "
                                    f"{result.elapsed_seconds:.1f}s)[/dim]{warnings}"
                                )
                        except Exception as e:
                            failed_count += 1
                            results.append(GenerationResult(bucket=bucket, error=str(e)))
                            console.print(f"  [red]✗[/red] [bold]{bucket.title}[/bold]: {e}")

                        progress.advance(task)

                # Rate limit between batches
                if batch_start + self.batch_size < total:
                    time.sleep(RATE_LIMIT_PAUSE)

        if failed_count > 0:
            console.print(f"[yellow]⚠ {failed_count} page(s) failed[/yellow]")

        console.print(
            f"[green]✓ Generated {generated_count}/{total} pages[/green]"
        )

        return results

    def _generate_one(
        self,
        bucket: DocBucket,
        sitemap_deps: tuple[str, str],
    ) -> GenerationResult:
        """Generate, validate, and post-process a single bucket page.

        This runs in a thread pool worker.
        """
        start = time.time()
        sitemap_context, dependency_links = sitemap_deps

        try:
            # Step 1: Assemble evidence
            evidence = self.assembler.assemble(bucket)

            # Step 2: Build OpenAPI context for endpoint pages
            openapi_context = ""
            if bucket.bucket_type == "endpoint" and self.scan.has_openapi:
                from .openapi import parse_openapi_spec, spec_to_context_string
                for spec_path in self.scan.openapi_paths:
                    spec = parse_openapi_spec(self.repo_root / spec_path)
                    if spec:
                        openapi_context = (
                            f"\n## OpenAPI Spec ({spec_path}):\n"
                            f"{spec_to_context_string(spec)[:4000]}"
                        )
                        break

            # Step 3: Generate with retry
            content = self._call_with_retry(evidence, sitemap_context,
                                            dependency_links, openapi_context)

            # Step 4: Post-process
            content = fix_mermaid_diagrams(content)
            content = fix_file_references(
                content, self.repo_root,
                set(self.scan.file_summaries.keys()),
                bucket.owned_files,
            )

            # Step 5: Validate
            validation = self.validator.validate(content, bucket)

            # Step 6: If validation fails badly, try graceful degradation
            if not validation.is_valid:
                content = self._apply_degradation_fixes(content, bucket, validation)
                # Re-validate after fixes
                validation = self.validator.validate(content, bucket)

            elapsed = time.time() - start

            # Step 7: Write to disk
            filename = "index.md" if bucket.bucket_type == "overview" else f"{bucket.slug}.md"
            doc_path = self.output_dir / filename
            doc_path.parent.mkdir(parents=True, exist_ok=True)
            doc_path.write_text(content, encoding="utf-8")

            return GenerationResult(
                bucket=bucket,
                content=content,
                validation=validation,
                elapsed_seconds=elapsed,
            )

        except Exception as e:
            elapsed = time.time() - start
            # Graceful degradation: generate a stub page
            stub = self._generate_stub_page(bucket)
            filename = f"{bucket.slug}.md"
            doc_path = self.output_dir / filename
            doc_path.parent.mkdir(parents=True, exist_ok=True)
            doc_path.write_text(stub, encoding="utf-8")

            return GenerationResult(
                bucket=bucket,
                content=stub,
                error=f"LLM failed, wrote stub: {e}",
                elapsed_seconds=elapsed,
            )

    @staticmethod
    def _is_retryable(err_str: str) -> bool:
        """Check if an error is transient and worth retrying."""
        markers = ("rate", "429", "overloaded", "timeout", "timed out",
                   "502", "503", "504", "bad gateway", "service unavailable",
                   "connection", "temporary", "throttl", "capacity",
                   "server_error", "internal_error")
        lower = err_str.lower()
        return any(m in lower for m in markers)

    def _call_with_retry(
        self,
        evidence: AssembledEvidence,
        sitemap_context: str,
        dependency_links: str,
        openapi_context: str,
    ) -> str:
        """Call LLM with exponential backoff + jitter on transient errors."""
        import random

        for attempt in range(MAX_RETRIES):
            try:
                return self.generator.generate(
                    evidence, sitemap_context, dependency_links, openapi_context
                )
            except Exception as e:
                err = str(e)
                is_last = attempt == MAX_RETRIES - 1

                if self._is_retryable(err):
                    if is_last:
                        raise
                    # Exponential backoff with jitter to avoid thundering herd
                    wait = RATE_LIMIT_BACKOFF * (2 ** attempt) + random.uniform(0, 1.5)
                    console.print(
                        f"    [yellow]⏳ Transient error ({evidence.bucket.title}) — "
                        f"waiting {wait:.1f}s (attempt {attempt + 1}/{MAX_RETRIES})...[/yellow]"
                    )
                    time.sleep(wait)
                elif is_last:
                    raise
                else:
                    # Non-rate-limit error — short pause and retry once more
                    console.print(
                        f"    [yellow]⚠ LLM error for {evidence.bucket.title} "
                        f"(attempt {attempt + 1}/{MAX_RETRIES}): {e}[/yellow]"
                    )
                    time.sleep(1 + random.uniform(0, 0.5))
        raise RuntimeError(f"Max retries exceeded for {evidence.bucket.title}")

    # ── Graceful degradation ─────────────────────────────────────────────

    def _apply_degradation_fixes(
        self,
        content: str,
        bucket: DocBucket,
        validation: ValidationResult,
    ) -> str:
        """Attempt to fix validation failures without re-calling the LLM.

        Strategies:
        - Append missing sections as empty stubs
        - Remove hallucinated paths
        - Add a notice if page is very short
        """
        # Fix 1: Append stub sections for missing required sections
        if validation.missing_sections:
            content += "\n\n---\n\n"
            for section in validation.missing_sections:
                content += f"## {section}\n\n"
                content += f"*TODO: This section ({section}) needs to be filled in with details "
                content += f"from the source files listed above.*\n\n"

        # Fix 2: Remove hallucinated file paths (replace with just path, no line num)
        for path in validation.hallucinated_paths:
            content = content.replace(f"`{path}", "`[path-not-found]")

        # Fix 3: Add a notice for very short pages
        if validation.word_count < 100:
            notice = (
                "\n\n!!! warning \"Incomplete Documentation\"\n"
                "    This page was auto-generated with limited evidence. "
                "Some sections may be incomplete.\n"
            )
            content = notice + content

        return content

    def _generate_stub_page(self, bucket: DocBucket) -> str:
        """Generate a minimal stub page when LLM generation completely fails."""
        files_list = "\n".join(f"- `{f}`" for f in bucket.owned_files[:20])
        more = f"\n- ... and {len(bucket.owned_files) - 20} more" if len(bucket.owned_files) > 20 else ""

        deps = ""
        if bucket.depends_on:
            deps = "\n## Related Pages\n" + "\n".join(
                f"- [{slug}]({slug}.md)" for slug in bucket.depends_on
            )

        return f"""# {bucket.title}

!!! warning "Auto-Generated Stub"
    This page could not be fully generated. It contains a file listing only.
    Re-run `codewiki generate` to retry.

## Description

{bucket.description}

## Source Files

{files_list}{more}
{deps}
"""

    # ── Helpers ──────────────────────────────────────────────────────────

    def _precompute_sitemaps(self) -> dict[str, tuple[str, str]]:
        """Pre-build sitemap + dependency context for each bucket slug."""
        result: dict[str, tuple[str, str]] = {}

        # Build sitemap by section
        for bucket in self.plan.buckets:
            sitemap = self._build_sitemap_for(bucket.slug)
            deps = self._build_dependency_links_for(bucket)
            result[bucket.slug] = (sitemap, deps)

        return result

    def _build_sitemap_for(self, current_slug: str) -> str:
        """Build formatted sitemap excluding current page."""
        by_section: dict[str, list[DocBucket]] = defaultdict(list)
        for b in self.plan.buckets:
            if b.slug != current_slug:
                by_section[b.section or "Other"].append(b)

        lines: list[str] = []
        for section, buckets in by_section.items():
            lines.append(f"**{section}**")
            for b in buckets:
                md_file = f"{b.slug}.md"
                key_files = ", ".join(f"`{f}`" for f in b.owned_files[:4])
                if len(b.owned_files) > 4:
                    key_files += f" +{len(b.owned_files) - 4} more"
                lines.append(f"- [{b.title}]({md_file}) — {b.description}")
                if key_files:
                    lines.append(f"  *Covers: {key_files}*")

        return "\n".join(lines) if lines else "(no other pages)"

    def _build_dependency_links_for(self, bucket: DocBucket) -> str:
        """Build dependency links from explicit depends_on + import analysis."""
        slug_to_bucket = {b.slug: b for b in self.plan.buckets}
        related: dict[str, DocBucket] = {}

        # Explicit depends_on
        for dep_slug in bucket.depends_on:
            if dep_slug in slug_to_bucket and dep_slug != bucket.slug:
                related[dep_slug] = slug_to_bucket[dep_slug]

        # Import-based: find buckets whose files are imported by this bucket's files
        file_to_buckets: dict[str, list[DocBucket]] = defaultdict(list)
        for b in self.plan.buckets:
            for f in b.owned_files:
                file_to_buckets[f].append(b)

        for src_file in bucket.owned_files[:15]:
            parsed = self.scan.parsed_files.get(src_file)
            if not parsed or not parsed.imports:
                continue
            for imp in parsed.imports:
                # Simple suffix match against known files
                for known_file in self.scan.file_summaries:
                    stem = known_file.rsplit(".", 1)[0].replace("/", ".").replace("\\", ".")
                    if stem and stem in imp.replace("/", "."):
                        for linked_bucket in file_to_buckets.get(known_file, []):
                            if linked_bucket.slug != bucket.slug:
                                related[linked_bucket.slug] = linked_bucket
                        break

        if not related:
            return ""

        lines = ["**Dependency Links** (pages this module imports from — MUST link to these):"]
        for b in related.values():
            lines.append(f"- [{b.title}]({b.slug}.md) — {b.description}")

        return "\n".join(lines)

    def _bucket_is_stale(self, bucket: DocBucket) -> bool:
        """Check if any source file for this bucket has changed since last generation."""
        from .manifest import Manifest, file_hash as compute_hash
        manifest = Manifest(self.output_dir)

        for src_file in bucket.owned_files:
            src_path = self.repo_root / src_file
            if not src_path.exists():
                continue
            try:
                content = src_path.read_text(encoding="utf-8", errors="replace")
                if manifest.is_stale(src_file, content):
                    return True
            except Exception:
                return True
        return False

    def update_manifest(self, results: list[GenerationResult]):
        """Update the manifest with new file hashes for all successfully generated pages."""
        from .manifest import Manifest, file_hash as compute_hash
        manifest = Manifest(self.output_dir)

        for result in results:
            if result.content and not result.error:
                for src_file in result.bucket.owned_files:
                    src_path = self.repo_root / src_file
                    if src_path.exists():
                        try:
                            content = src_path.read_text(encoding="utf-8", errors="replace")
                            manifest.update(src_file, compute_hash(content), result.bucket.slug)
                        except Exception:
                            pass
        manifest.save()
