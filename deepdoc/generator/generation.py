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


from .evidence import AssembledEvidence, EvidenceAssembler
from .validation import PageValidator, ValidationResult
from .post_processors import *
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
        quality_feedback: str = "",
    ) -> str:
        """Generate the complete page from evidence. Returns markdown string."""
        bucket = evidence.bucket

        # Select prompt template via generation_hints.prompt_style
        prompt_template = get_prompt_for_bucket(bucket)

        # Compose the enriched source context
        full_source = evidence.source_context
        if evidence.compressed_cards_context:
            full_source += (
                "\n\n## Compressed File Coverage\n"
                "These files were not dropped. They are represented by derived evidence "
                "cards and still count as authoritative coverage inputs.\n\n"
                f"{evidence.compressed_cards_context}"
            )
        if evidence.cluster_context:
            full_source += f"\n\n## Giant File Clusters\n{evidence.cluster_context}"
        if evidence.integration_context:
            full_source += f"\n\n## Integration Context\n{evidence.integration_context}"
        if evidence.database_context:
            full_source += f"\n\n## Database Schema\n{evidence.database_context}"
        if evidence.runtime_context:
            full_source += (
                f"\n\n## Runtime & Background Jobs\n{evidence.runtime_context}"
            )
        if evidence.artifact_context:
            full_source += f"\n\n## Artifacts\n{evidence.artifact_context}"
        if evidence.graph_context:
            full_source += f"\n\n## Dependency Graph\n{evidence.graph_context}"
        if evidence.cross_ref_context:
            full_source += f"\n\n{evidence.cross_ref_context}"
        if evidence.plan_summary_context:
            full_source += f"\n\n## Repository Map\n{evidence.plan_summary_context}"
        if evidence.repo_docs_context:
            full_source += f"\n\n{evidence.repo_docs_context}"
        if evidence.helper_context:
            full_source += f"\n\n{evidence.helper_context}"
        if evidence.config_env_context:
            full_source += (
                f"\n\n## Config & Environment Evidence\n{evidence.config_env_context}"
            )
        page_contract = (bucket.generation_hints or {}).get("page_contract", {})
        if page_contract:
            contract_lines = [
                f"Intent: {page_contract.get('intent', bucket.description or bucket.title)}"
            ]
            must_cover = page_contract.get("must_cover_concepts", [])
            if must_cover:
                contract_lines.append(f"Must cover: {', '.join(must_cover)}")
            sibling_links = page_contract.get("required_sibling_links", [])
            if sibling_links:
                contract_lines.append(
                    f"Required sibling links: {', '.join(sibling_links)}"
                )
            forbidden = page_contract.get("forbidden_filler", [])
            if forbidden:
                contract_lines.append(f"Forbidden filler: {', '.join(forbidden)}")
            full_source += "\n\n## Page Contract\n" + "\n".join(
                f"- {line}" for line in contract_lines
            )

        # Format required sections/diagrams/coverage
        required_sections = (
            ", ".join(bucket.required_sections)
            if bucket.required_sections
            else "default"
        )
        required_diagrams = (
            ", ".join(bucket.required_diagrams)
            if bucket.required_diagrams
            else "architecture_flow"
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
            frameworks=", ".join(self.cfg.get("frameworks") or []),
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

        if quality_feedback:
            user_prompt += (
                "\n\n## Quality Feedback From Previous Draft\n"
                "Revise the page to address these issues while staying grounded in the same evidence:\n"
                f"{quality_feedback}\n"
            )

        return self.llm.complete(SYSTEM_V2, user_prompt)


# ═════════════════════════════════════════════════════════════════════════════
# 3.5  Parallel Generation Orchestrator
# ═════════════════════════════════════════════════════════════════════════════

# Rate limiting constants — tuned for provisioned providers (Azure PTU, etc.)
# Override via .deepdoc.yaml: batch_size, max_parallel_workers
BATCH_SIZE = 10
RATE_LIMIT_PAUSE = 0.5  # seconds between batches (Azure rarely 429s within quota)
RATE_LIMIT_BACKOFF = 3.0  # initial backoff on 429; doubles each retry
MAX_RETRIES = 5
MAX_PARALLEL_WORKERS = 6  # LLM concurrency — safe for most Azure/OpenAI deployments


@dataclass
class GenerationResult:
    """Result of generating a single page."""

    bucket: DocBucket
    content: str | None = None
    validation: ValidationResult | None = None
    error: str | None = None
    elapsed_seconds: float = 0.0
    retries: int = 0
    degraded: bool = False


@dataclass
class GenerationSummary:
    """Aggregate summary for a generation run."""

    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    invalid: int = 0
    degraded: int = 0
    warnings_total: int = 0
    invalid_slugs: list[str] = field(default_factory=list)
    degraded_slugs: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.failed == 0 and self.invalid == 0 and self.degraded == 0:
            return "success"
        return "partial" if self.succeeded > 0 else "failed"


def summarize_generation_results(results: list[GenerationResult]) -> GenerationSummary:
    """Summarize successful, failed, and skipped generation results."""

    summary = GenerationSummary(attempted=len(results))
    for result in results:
        if result.error:
            summary.failed += 1
        elif result.content:
            summary.succeeded += 1
            validation = getattr(result, "validation", None)
            if validation:
                summary.warnings_total += len(validation.warnings)
                if not validation.is_valid:
                    summary.invalid += 1
                    summary.invalid_slugs.append(result.bucket.slug)
            if getattr(result, "degraded", False):
                summary.degraded += 1
                summary.degraded_slugs.append(result.bucket.slug)
        else:
            summary.skipped += 1
    return summary


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
        self.rate_limit_pause = cfg.get("rate_limit_pause", RATE_LIMIT_PAUSE)
        self._repo_file_paths = set(self.scan.file_summaries.keys())
        self._openapi_context = self._precompute_openapi_context()
        self._doc_pages = self._planned_doc_pages()
        (
            self._valid_doc_urls,
            self._doc_title_to_url,
            self._doc_alias_map,
        ) = build_internal_doc_link_maps(self._doc_pages)

    def _precompute_openapi_context(self) -> str:
        """Parse the first available OpenAPI spec once per run."""
        if not self.scan.has_openapi:
            return ""
        for spec_path in self.scan.openapi_paths:
            spec = parse_openapi_spec(self.repo_root / spec_path)
            if spec:
                return (
                    f"\n## OpenAPI Spec ({spec_path}):\n"
                    f"{spec_to_context_string(spec)[:4000]}"
                )
        return ""

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
                batch = buckets[batch_start : batch_start + self.batch_size]

                # Use thread pool for parallel LLM calls within batch
                with ThreadPoolExecutor(
                    max_workers=min(self.max_workers, len(batch))
                ) as executor:
                    futures = {}
                    for bucket in batch:
                        progress.update(
                            task, description=f"[dim]Queuing {bucket.title}...[/dim]"
                        )

                        # Check staleness
                        if not force and not self._bucket_is_stale(bucket):
                            results.append(
                                GenerationResult(bucket=bucket, content=None)
                            )
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
                                if result.degraded:
                                    warnings += " [yellow]degraded[/yellow]"
                                if v and not v.is_valid:
                                    warnings += " [red]invalid[/red]"
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
                            results.append(
                                GenerationResult(bucket=bucket, error=str(e))
                            )
                            console.print(
                                f"  [red]✗[/red] [bold]{bucket.title}[/bold]: {e}"
                            )

                        progress.advance(task)

                # Rate limit between batches
                if batch_start + self.batch_size < total and self.rate_limit_pause > 0:
                    time.sleep(self.rate_limit_pause)

        if failed_count > 0:
            console.print(f"[yellow]⚠ {failed_count} page(s) failed[/yellow]")

        console.print(f"[green]✓ Generated {generated_count}/{total} pages[/green]")

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
            degraded = False

            if evidence.files_compressed > 0:
                total_files = evidence.coverage_files_total
                console.print(
                    f'[yellow]⚠ bucket "{bucket.title}": '
                    f"{evidence.files_compressed} of {total_files} tracked files "
                    f"compressed into derived evidence cards[/yellow]"
                )

            # Step 2: Build OpenAPI context for endpoint pages
            openapi_context = ""
            hints = bucket.generation_hints or {}
            if hints.get("include_openapi") and self.scan.has_openapi:
                openapi_context = self._openapi_context

            # Step 3: Generate with retry
            content = self._call_with_retry(
                evidence, sitemap_context, dependency_links, openapi_context
            )

            # Step 4: Post-process
            content = fix_mermaid_diagrams(content)
            content = fix_file_references(
                content,
                self.repo_root,
                self._repo_file_paths,
                bucket.owned_files,
            )
            content = normalize_html_code_blocks(content)
            content = normalize_code_fence_languages(content)
            content = normalize_mdx_steps(content)
            content = escape_mdx_route_params(content)
            content = escape_mdx_text_hazards(content)
            content = repair_internal_doc_links(
                content,
                self._valid_doc_urls,
                self._doc_title_to_url,
                self._doc_alias_map,
            )

            # Step 5: Validate
            validation = self.validator.validate(content, bucket, evidence)

            # Step 6: Retry once on weak quality before degrading.
            if not validation.is_valid:
                quality_feedback = "\n".join(
                    f"- {warning}" for warning in validation.warnings[:8]
                )
                try:
                    content = self._call_with_retry(
                        evidence,
                        sitemap_context,
                        dependency_links,
                        openapi_context,
                        quality_feedback=quality_feedback,
                    )
                    content = fix_mermaid_diagrams(content)
                    content = fix_file_references(
                        content,
                        self.repo_root,
                        self._repo_file_paths,
                        bucket.owned_files,
                    )
                    content = normalize_html_code_blocks(content)
                    content = normalize_code_fence_languages(content)
                    content = normalize_mdx_steps(content)
                    content = escape_mdx_route_params(content)
                    content = escape_mdx_text_hazards(content)
                    content = repair_internal_doc_links(
                        content,
                        self._valid_doc_urls,
                        self._doc_title_to_url,
                        self._doc_alias_map,
                    )
                    validation = self.validator.validate(content, bucket, evidence)
                except Exception:
                    pass

            # Step 7: If validation fails badly, try graceful degradation
            if not validation.is_valid:
                degraded = True
                content = self._apply_degradation_fixes(content, bucket, validation)
                # Re-validate after fixes
                validation = self.validator.validate(content, bucket, evidence)

            elapsed = time.time() - start

            # Step 8: Write to disk
            bucket_hints = bucket.generation_hints or {}
            filename = (
                "index.mdx"
                if bucket_hints.get("is_introduction_page")
                else f"{bucket.slug}.mdx"
            )
            doc_path = self.output_dir / filename
            doc_path.parent.mkdir(parents=True, exist_ok=True)
            doc_path.write_text(content, encoding="utf-8")

            return GenerationResult(
                bucket=bucket,
                content=content,
                validation=validation,
                elapsed_seconds=elapsed,
                degraded=degraded,
            )

        except Exception as e:
            elapsed = time.time() - start
            # Graceful degradation: generate a stub page
            stub = self._generate_stub_page(bucket)
            bucket_hints = bucket.generation_hints or {}
            filename = (
                "index.mdx"
                if bucket_hints.get("is_introduction_page")
                else f"{bucket.slug}.mdx"
            )
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
        markers = (
            "rate",
            "429",
            "overloaded",
            "timeout",
            "timed out",
            "502",
            "503",
            "504",
            "bad gateway",
            "service unavailable",
            "connection",
            "temporary",
            "throttl",
            "capacity",
            "server_error",
            "internal_error",
        )
        lower = err_str.lower()
        return any(m in lower for m in markers)

    def _call_with_retry(
        self,
        evidence: AssembledEvidence,
        sitemap_context: str,
        dependency_links: str,
        openapi_context: str,
        quality_feedback: str = "",
    ) -> str:
        """Call LLM with exponential backoff + jitter on transient errors."""
        import random

        for attempt in range(MAX_RETRIES):
            try:
                return self.generator.generate(
                    evidence,
                    sitemap_context,
                    dependency_links,
                    openapi_context,
                    quality_feedback=quality_feedback,
                )
            except Exception as e:
                err = str(e)
                is_last = attempt == MAX_RETRIES - 1

                if self._is_retryable(err):
                    if is_last:
                        raise
                    # Exponential backoff with jitter to avoid thundering herd
                    wait = RATE_LIMIT_BACKOFF * (2**attempt) + random.uniform(0, 1.5)
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
                '\n\n<Callout type="warn">\n'
                "This page was auto-generated with limited evidence. "
                "Some sections may be incomplete.\n"
                "</Callout>\n"
            )
            content = notice + content

        return content

    def _generate_stub_page(self, bucket: DocBucket) -> str:
        """Generate a minimal stub page when LLM generation completely fails."""
        files_list = "\n".join(f"- `{f}`" for f in bucket.owned_files[:20])
        more = (
            f"\n- ... and {len(bucket.owned_files) - 20} more"
            if len(bucket.owned_files) > 20
            else ""
        )

        deps = ""
        if bucket.depends_on:
            deps = "\n## Related Pages\n" + "\n".join(
                f"- [{slug}](/{slug})" for slug in bucket.depends_on
            )

        return f"""# {bucket.title}

<Callout type="warn">
This page could not be fully generated. It contains a file listing only.
Re-run `deepdoc generate` to retry.
</Callout>

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

    def _planned_doc_pages(self) -> list[tuple[str, str]]:
        """Return planned titles mapped to their eventual site URLs."""
        pages: list[tuple[str, str]] = []
        for bucket in self.plan.buckets:
            hints = bucket.generation_hints or {}
            if hints.get("is_introduction_page"):
                url = "/"
            elif self.scan.has_openapi and (
                hints.get("is_endpoint_ref")
                or hints.get("prompt_style") == "endpoint_ref"
                or bucket.bucket_type == "endpoint_ref"
            ):
                url = f"/api/{bucket.slug}"
            else:
                url = f"/{bucket.slug}"
            pages.append((bucket.title, url))
        return pages

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
                page_path = f"/{b.slug}"
                key_files = ", ".join(f"`{f}`" for f in b.owned_files[:4])
                if len(b.owned_files) > 4:
                    key_files += f" +{len(b.owned_files) - 4} more"
                lines.append(f"- [{b.title}]({page_path}) — {b.description}")
                if key_files:
                    lines.append(f"  *Covers: {key_files}*")

        return "\n".join(lines) if lines else "(no other pages)"

    def _build_dependency_links_for(self, bucket: DocBucket) -> str:
        """Build dependency links from explicit depends_on + import analysis."""
        slug_to_bucket = {b.slug: b for b in self.plan.buckets}
        related: dict[str, DocBucket] = {}
        bucket_files = set(bucket.owned_files)

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
                    stem = (
                        known_file.rsplit(".", 1)[0]
                        .replace("/", ".")
                        .replace("\\", ".")
                    )
                    if stem and stem in imp.replace("/", "."):
                        for linked_bucket in file_to_buckets.get(known_file, []):
                            if linked_bucket.slug != bucket.slug:
                                related[linked_bucket.slug] = linked_bucket
                        break

        # Strong overlap-based links for database/runtime/interface pages
        for candidate in self.plan.buckets:
            if candidate.slug == bucket.slug:
                continue
            hints = candidate.generation_hints or {}
            if not (
                hints.get("is_database_overview")
                or hints.get("is_database_group")
                or hints.get("is_runtime_overview")
                or hints.get("runtime_group_kind")
                or hints.get("prompt_style") == "graphql"
            ):
                continue
            if bucket_files & set(candidate.owned_files):
                related[candidate.slug] = candidate

        if not related:
            return ""

        lines = [
            "**Dependency Links** (pages this module imports from — MUST link to these):"
        ]
        for b in related.values():
            lines.append(f"- [{b.title}](/{b.slug}) — {b.description}")

        return "\n".join(lines)

    def _bucket_is_stale(self, bucket: DocBucket) -> bool:
        """Check if any source file for this bucket has changed since last generation."""
        from ..manifest import Manifest, file_hash as compute_hash

        manifest = Manifest(self.output_dir)

        for src_file in tracked_bucket_files(bucket):
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
        from ..manifest import Manifest, file_hash as compute_hash

        manifest = Manifest(self.output_dir)

        for result in results:
            if result.content and not result.error:
                for src_file in tracked_bucket_files(result.bucket):
                    src_path = self.repo_root / src_file
                    if src_path.exists():
                        try:
                            content = src_path.read_text(
                                encoding="utf-8", errors="replace"
                            )
                            manifest.update(
                                src_file, compute_hash(content), result.bucket.slug
                            )
                        except Exception:
                            pass
        manifest.save()
