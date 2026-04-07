"""V2 Pipeline — AI-planned, batched, diagram-rich generation.

Flow:
    1. SCAN  — collect file tree, symbols, endpoints, OpenAPI specs (no LLM)
    2. PLAN  — multi-step bucket planner (3 LLM calls) OR legacy single-call planner
    3. GENERATE — execute plan page-by-page, batched (N LLM calls)
    4. API REF — stage OpenAPI assets for generated Fumadocs API reference pages
    5. BUILD — write the generated Fumadocs site scaffold + page tree

The manifest tracks: source_file → content_hash → [page_slugs]
So `deepdoc update` can diff changed files → find affected pages → regenerate only those.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
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

from .chatbot.settings import chatbot_enabled
from .generator import (
    build_internal_doc_link_maps,
    BucketGenerationEngine,
    escape_mdx_route_params,
    escape_mdx_text_hazards,
    normalize_code_fence_languages,
    repair_unbalanced_code_fences,
    repair_mdx_component_blocks,
    repair_internal_doc_links,
    summarize_generation_results,
)
from .llm import LLMClient
from .manifest import Manifest, file_hash
from .openapi import (
    extract_endpoints_from_spec,
    find_openapi_specs,
    parse_openapi_spec,
    spec_to_context_string,
)
from .persistence_v2 import (
    cleanup_stale_generated_files,
    load_generation_ledger,
    prune_generation_ledger,
    save_all,
    save_sync_receipt,
    save_sync_state,
)
from .planner import (
    plan_docs as bucket_plan_docs,
)
from .planner import (
    scan_repo as bucket_scan_repo,
)
from .prompts_v2 import SYSTEM_V2, get_prompt_for_page_type

console = Console()

BATCH_SIZE = 10
RATE_LIMIT_PAUSE = 0.5
RATE_LIMIT_BACKOFF = 3.0
MAX_RETRIES = 5


def _page_is_overview(page: Any) -> bool:
    """Check whether a planned page is the landing page."""
    hints = (page._b.generation_hints or {}) if hasattr(page, "_b") else {}
    return (
        hints.get("is_introduction_page")
        or getattr(page, "page_type", None) == "overview"
    )


def _page_uses_openapi_route(page: Any, has_openapi: bool) -> bool:
    """Check whether a page should resolve to /api/<slug>."""
    if not has_openapi:
        return False
    hints = (page._b.generation_hints or {}) if hasattr(page, "_b") else {}
    return (
        hints.get("is_endpoint_ref")
        or getattr(page, "page_type", None) == "endpoint_ref"
    )


def _page_url(page: Any, has_openapi: bool) -> str:
    """Resolve the public URL for a generated page."""
    if _page_is_overview(page):
        return "/"
    if _page_uses_openapi_route(page, has_openapi):
        return f"/api/{page.slug}"
    return f"/{page.slug}"


def _endpoint_ref_slug(method: str, path: str) -> str:
    """Build the canonical endpoint_ref slug used by the planner."""
    import re

    path_slug = re.sub(r"[/:{}<>]+", "-", path).strip("-").lower()
    return f"{method.lower()}-{path_slug}"


def stage_openapi_assets(
    repo_root: Path, openapi_paths: list[str] | None = None
) -> bool:
    """Stage the first detected OpenAPI spec for the generated Fumadocs app."""
    site_openapi_dir = repo_root / "site" / "openapi"
    site_openapi_dir.mkdir(parents=True, exist_ok=True)

    for existing in site_openapi_dir.iterdir():
        if existing.is_file():
            existing.unlink()

    detected_paths = openapi_paths
    if detected_paths is None:
        detected_paths = [
            str(path.relative_to(repo_root)) for path in find_openapi_specs(repo_root)
        ]

    for spec_rel_path in detected_paths:
        spec_src = repo_root / spec_rel_path
        if not spec_src.exists():
            continue

        spec_name = Path(spec_rel_path).name
        staged_spec = site_openapi_dir / spec_name
        shutil.copy2(spec_src, staged_spec)

        spec = parse_openapi_spec(spec_src)
        if not spec:
            console.print(
                f"[yellow]⚠[/yellow] Could not parse {spec_name} — skipping API pages"
            )
            return False

        endpoints = extract_endpoints_from_spec(spec)
        manifest: list[dict[str, str]] = []
        for ep in endpoints:
            if ep.get("deprecated"):
                continue

            method = ep["method"].upper()
            path = ep["path"]
            summary = ep.get("summary") or f"{method} {path}"
            manifest.append(
                {
                    "slug": _endpoint_ref_slug(method, path),
                    "title": summary,
                    "method": method,
                    "path": path,
                }
            )

        if manifest:
            (site_openapi_dir / "manifest.json").write_text(
                json.dumps(manifest, indent=2) + "\n",
                encoding="utf-8",
            )
            console.print(
                f"[green]✓[/green] Staged {len(manifest)} Fumadocs OpenAPI pages"
            )
            return True

        console.print(f"[yellow]⚠[/yellow] No endpoints found in {spec_name}")
        return False

    return False


class PipelineV2:
    def __init__(self, repo_root: Path, cfg: dict[str, Any]) -> None:
        self.repo_root = repo_root
        self.cfg = cfg
        self.output_dir = repo_root / cfg.get("output_dir", "docs")
        self.llm = LLMClient(cfg)
        self.manifest = Manifest(self.output_dir)
        self.batch_size = cfg.get("batch_size", BATCH_SIZE)

    def run(self, force: bool = False, reconcile: bool = False) -> dict[str, Any]:
        stats: dict[str, Any] = {}
        phase_timings: dict[str, float] = {}
        previous_ledger = load_generation_ledger(self.repo_root) if reconcile else {}
        chatbot_sync_ok = True

        # ── Phase 1: Scan ──────────────────────────────────────────────
        console.print(
            Panel("[bold]Phase 1/5: Scanning repository[/bold]", border_style="blue")
        )
        phase_start = time.perf_counter()
        scan = bucket_scan_repo(self.repo_root, self.cfg)
        phase_timings["scan"] = time.perf_counter() - phase_start
        self._print_scan(scan)
        stats["files_scanned"] = scan.total_files

        # ── Phase 2: Plan ──────────────────────────────────────────────
        console.print(
            Panel(
                "[bold]Phase 2/5: Multi-step bucket planner (3 LLM calls)[/bold]",
                border_style="blue",
            )
        )
        phase_start = time.perf_counter()
        plan = bucket_plan_docs(scan, self.cfg, self.llm)
        phase_timings["plan"] = time.perf_counter() - phase_start
        stats["pages_planned"] = len(plan.pages)

        # ── Phase 3: Generate ──────────────────────────────────────────
        console.print(
            Panel(
                f"[bold]Phase 3/5: Generating {len(plan.pages)} doc pages[/bold]",
                border_style="blue",
            )
        )
        engine = BucketGenerationEngine(
            repo_root=self.repo_root,
            cfg=self.cfg,
            llm=self.llm,
            scan=scan,
            plan=plan,
            output_dir=self.output_dir,
        )
        phase_start = time.perf_counter()
        gen_results = engine.generate_all(force=force)
        phase_timings["generate"] = time.perf_counter() - phase_start
        engine.update_manifest(gen_results)
        generation_summary = summarize_generation_results(gen_results)
        stats["pages_generated"] = generation_summary.succeeded
        stats["pages_failed"] = generation_summary.failed
        stats["pages_skipped"] = generation_summary.skipped
        stats["pages_invalid"] = generation_summary.invalid
        stats["pages_degraded"] = generation_summary.degraded
        stats["page_warnings"] = generation_summary.warnings_total
        stats["quality_report"] = {
            "invalid_slugs": generation_summary.invalid_slugs,
            "degraded_slugs": generation_summary.degraded_slugs,
        }
        stats["status"] = generation_summary.status

        # ── Phase 4: API Playground ────────────────────────────────────
        openapi_ready = False
        if scan.has_openapi:
            console.print(
                Panel(
                    "[bold]Phase 4/5: Generating API reference pages[/bold]",
                    border_style="blue",
                )
            )
            phase_start = time.perf_counter()
            openapi_ready = self._setup_playground(scan)
            phase_timings["openapi"] = time.perf_counter() - phase_start
            stats["playground"] = 1 if openapi_ready else 0
        else:
            console.print(
                Panel(
                    "[dim]Phase 4/5: No OpenAPI spec — skipping API reference generation[/dim]",
                    border_style="dim",
                )
            )
            stats["playground"] = 0
            phase_timings["openapi"] = 0.0

        # ── Phase 5: Build site ────────────────────────────────────────
        console.print(
            Panel("[bold]Phase 5/5: Building site[/bold]", border_style="blue")
        )
        phase_start = time.perf_counter()
        self._build_site(plan, has_openapi=openapi_ready)
        phase_timings["build_site"] = time.perf_counter() - phase_start
        stats["site"] = 1

        # ── Persist state ──────────────────────────────────────────────
        phase_start = time.perf_counter()
        save_all(plan, scan, gen_results, self.repo_root, self.output_dir)
        self._save_quality_report(stats)
        phase_timings["persist"] = time.perf_counter() - phase_start

        if chatbot_enabled(self.cfg):
            try:
                from .chatbot.indexer import ChatbotIndexer

                console.print("[dim]Starting chatbot index sync...[/dim]")
                chatbot_stats = ChatbotIndexer(self.repo_root, self.cfg).sync_full(
                    plan=plan,
                    scan=scan,
                    output_dir=self.output_dir,
                    has_openapi=openapi_ready,
                )
                stats["chatbot"] = chatbot_stats
                total = sum(
                    chatbot_stats.get(k, 0)
                    for k in (
                        "code_chunks",
                        "artifact_chunks",
                        "doc_chunks",
                        "doc_full_chunks",
                        "repo_doc_chunks",
                    )
                )
                console.print(
                    f"[green]✓[/green] Chatbot index: {total} chunks "
                    f"({chatbot_stats.get('code_chunks', 0)} code, "
                    f"{chatbot_stats.get('artifact_chunks', 0)} artifact, "
                    f"{chatbot_stats.get('doc_chunks', 0)} doc summary, "
                    f"{chatbot_stats.get('doc_full_chunks', 0)} doc full, "
                    f"{chatbot_stats.get('repo_doc_chunks', 0)} repo doc)"
                )
                console.print("[green]✓[/green] Backend scaffold: chatbot_backend/")
            except Exception as e:
                chatbot_sync_ok = False
                stats["chatbot_error"] = str(e)
                console.print(f"[yellow]⚠ Chatbot sync failed: {e}[/yellow]")

        # ── Persist commit baseline for future updates ────────────────
        try:
            import git as _git

            _repo = _git.Repo(self.repo_root)
            head_sha = _repo.head.commit.hexsha
            plan_version = "v2_buckets" if hasattr(plan, "buckets") else "v1_legacy"
            overall_status = generation_summary.status
            if not chatbot_sync_ok:
                overall_status = (
                    "partial" if generation_summary.succeeded > 0 else "failed"
                )
            save_sync_state(
                self.repo_root,
                commit_sha=head_sha,
                status=overall_status,
                generator_version=plan_version,
                advance_baseline=generation_summary.failed == 0 and chatbot_sync_ok,
            )
            save_sync_receipt(
                self.repo_root,
                {
                    "baseline_commit": head_sha,
                    "target_commit": head_sha,
                    "strategy": "full_generate",
                    "engine_mismatch": False,
                    "chatbot_recovery_needed": False,
                    "change_count": stats.get("files_scanned", 0),
                    "changed_files": [],
                    "new_files": [],
                    "deleted_files": [],
                    "changed_artifact_files": [],
                    "new_artifact_files": [],
                    "deleted_artifact_files": [],
                    "stale_bucket_slugs": [],
                    "updated_slugs": [
                        result.bucket.slug
                        for result in gen_results
                        if result.content is not None and not result.error
                    ],
                    "failed_slugs": [
                        result.bucket.slug for result in gen_results if result.error
                    ],
                    "deleted_doc_paths": [],
                    "refreshed_corpora": list(
                        (stats.get("chatbot") or {}).get("corpora_refreshed", [])
                    ),
                    "chatbot_failed": not chatbot_sync_ok,
                    "status": overall_status,
                    "pages_updated": generation_summary.succeeded,
                    "pages_failed": generation_summary.failed
                    + (0 if chatbot_sync_ok else 1),
                    "pages_invalid": generation_summary.invalid,
                    "pages_degraded": generation_summary.degraded,
                    "page_warnings": generation_summary.warnings_total,
                    "pages_skipped": generation_summary.skipped,
                    "replanned": True,
                },
            )
        except Exception:
            pass  # Not a git repo or detached HEAD — skip silently

        if reconcile:
            keep_slugs = {bucket.slug for bucket in plan.buckets}
            deleted = cleanup_stale_generated_files(
                self.repo_root,
                self.output_dir,
                keep_slugs,
                previous_ledger=previous_ledger,
            )
            prune_generation_ledger(self.repo_root, keep_slugs)
            stats["stale_pages_removed"] = len(deleted)
            if deleted:
                console.print(
                    f"[dim]Removed {len(deleted)} stale DeepDoc page(s) no longer in the plan.[/dim]"
                )

        if not chatbot_sync_ok:
            stats["status"] = (
                "partial" if generation_summary.succeeded > 0 else "failed"
            )

        stats["timings"] = {
            name: round(duration, 2) for name, duration in phase_timings.items()
        }
        timing_summary = ", ".join(
            f"{name}={duration:.2f}s"
            for name, duration in phase_timings.items()
            if duration >= 0.01
        )
        if timing_summary:
            console.print(f"[dim]Pipeline timings: {timing_summary}[/dim]")

        self._print_summary(stats)
        return stats

    # ──────────────────────────────────────────────────────────────────────
    # Phase 1 helpers
    # ──────────────────────────────────────────────────────────────────────

    def _print_scan(self, scan: RepoScan) -> None:
        from rich.table import Table

        t = Table(show_header=True, header_style="bold")
        t.add_column("Metric", style="cyan")
        t.add_column("Value", justify="right")
        t.add_row("Source files", str(scan.total_files))
        for lang, count in sorted(scan.languages.items(), key=lambda x: -x[1]):
            t.add_row(f"  {lang}", str(count))
        t.add_row("API endpoints", str(len(scan.api_endpoints)))
        t.add_row("Frameworks", ", ".join(scan.frameworks_detected) or "none")
        t.add_row("OpenAPI specs", ", ".join(scan.openapi_paths) or "none")
        t.add_row("Entry points", str(len(scan.entry_points)))
        t.add_row("Config files", str(len(scan.config_files)))
        console.print(t)

    # ──────────────────────────────────────────────────────────────────────
    # Phase 3: Generate pages
    # ──────────────────────────────────────────────────────────────────────

    def _generate_pages(self, plan: DocPlan, scan: RepoScan, force: bool) -> int:
        generated = 0
        failed = 0
        total = len(plan.pages)

        # Batch pages by priority
        pages_sorted = sorted(plan.pages, key=lambda p: p.priority)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Generating...", total=total)

            for i, page in enumerate(pages_sorted):
                progress.update(task, description=f"[dim]{page.title}[/dim]")

                # Check if page needs regeneration
                if not force and not self._page_is_stale(page):
                    progress.advance(task)
                    continue

                try:
                    progress.update(
                        task,
                        description=(
                            f"[bold cyan]{page.title}[/bold cyan] "
                            f"[dim]({page.page_type}, {len(page.source_files)} source files)[/dim]"
                        ),
                    )

                    # Sub-step 1: building context
                    progress.update(
                        task,
                        description=f"[dim]{page.title} — reading source files...[/dim]",
                    )
                    doc_content = self._generate_single_page(page, scan, plan)

                    # Sub-step 2: write to disk
                    filename = (
                        "index.mdx" if _page_is_overview(page) else f"{page.slug}.mdx"
                    )
                    doc_path = self.output_dir / filename
                    doc_path.parent.mkdir(parents=True, exist_ok=True)
                    doc_path.write_text(doc_content, encoding="utf-8")

                    # Update manifest for all source files in this page
                    for src_file in page.source_files:
                        src_path = self.repo_root / src_file
                        if src_path.exists():
                            try:
                                content = src_path.read_text(
                                    encoding="utf-8", errors="replace"
                                )
                                self.manifest.update(
                                    src_file, file_hash(content), page.slug
                                )
                            except Exception:
                                pass

                    generated += 1
                    word_count = len(doc_content.split())
                    console.print(
                        f"  [green]✓[/green] [bold]{page.title}[/bold] "
                        f"[dim]({page.page_type} · {len(page.source_files)} files · ~{word_count} words)[/dim]"
                    )

                except Exception as e:
                    failed += 1
                    console.print(f"  [red]✗[/red] [bold]{page.title}[/bold]: {e}")

                progress.advance(task)

                # Rate limit between pages
                if i < total - 1 and i % self.batch_size == self.batch_size - 1:
                    time.sleep(RATE_LIMIT_PAUSE)

        if failed > 0:
            console.print(f"[yellow]⚠ {failed} page(s) failed[/yellow]")

        return generated

    def _generate_single_page(self, page, scan, plan) -> str:
        """Generate a single doc page with retry logic.

        Works with both legacy DocPage and new DocBucket (via _BucketAsPage adapter).
        """
        # Build source context from the page's source files (tiered, 60k budget)
        source_context = self._build_source_context(page)

        # Build cross-linking context — sitemap + dependency links
        sitemap_context = self._build_sitemap_context(plan, page.slug)
        dependency_links = self._build_dependency_context(page, scan, plan)

        # Get the right prompt — prefer bucket hints, fall back to page_type
        if hasattr(page, "_b"):
            from .prompts_v2 import get_prompt_for_bucket

            prompt_template = get_prompt_for_bucket(page._b)
        else:
            prompt_template = get_prompt_for_page_type(page.page_type)

        # Build OpenAPI context if hints or page_type indicate endpoint/api content
        _hints = (page._b.generation_hints or {}) if hasattr(page, "_b") else {}
        _wants_openapi = _hints.get("include_openapi") or page.page_type in (
            "api_reference",
            "endpoint",
        )
        openapi_context = ""
        if _wants_openapi and scan.has_openapi:
            for spec_path in scan.openapi_paths:
                spec = parse_openapi_spec(self.repo_root / spec_path)
                if spec:
                    openapi_context = f"\n## OpenAPI Spec ({spec_path}):\n{spec_to_context_string(spec)[:4000]}"
                    break

        # Build endpoints detail
        _wants_endpoints = _hints.get("include_endpoint_detail") or page.page_type in (
            "api_reference",
            "endpoint",
        )
        endpoints_detail = ""
        if _wants_endpoints:
            page_files = set(page.source_files)
            relevant_eps = [
                ep for ep in scan.api_endpoints if ep.get("file", "") in page_files
            ]
            if relevant_eps:
                lines = []
                for ep in relevant_eps:
                    lines.append(
                        f"- {ep['method']} {ep['path']} → "
                        f"{ep.get('handler', '?')} ({ep.get('file', '')}:{ep.get('line', 0)})"
                    )
                endpoints_detail = "\n".join(lines)

        # Infer resource group from page slug
        resource_group = page.slug.replace("-api", "").replace("-", " ").title()

        # Extract bucket-specific metadata (for new bucket-type prompts)
        required_sections = ""
        required_diagrams = ""
        coverage_targets = ""
        if hasattr(page, "_b"):
            # This is a _BucketAsPage adapter
            bucket = page._b
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

        # Format the prompt — all templates accept these kwargs; unused ones are silently ignored
        user_prompt = prompt_template.format(
            title=page.title,
            project_name=self.cfg.get("project_name", self.repo_root.name),
            description=self.cfg.get("description", ""),
            page_description=page.description,
            languages=", ".join(scan.languages.keys()),
            frameworks=", ".join(scan.frameworks_detected),
            source_context=source_context,
            endpoints_detail=endpoints_detail,
            openapi_context=openapi_context,
            resource_group=resource_group,
            required_sections=required_sections,
            required_diagrams=required_diagrams,
            coverage_targets=coverage_targets,
            sitemap_context=sitemap_context,
            dependency_links=dependency_links,
        )

        console.print(
            f"    [dim]→ Calling LLM for [cyan]{page.title}[/cyan] "
            f"(~{len(user_prompt.split())} prompt words, {len(page.source_files)} source files)...[/dim]"
        )
        raw = self._call_llm_with_retry(user_prompt)

        # Post-process: validate Mermaid diagrams and file references
        raw = self._validate_and_fix_mermaid(raw)
        raw = self._validate_file_refs(raw, scan, page)
        raw = normalize_code_fence_languages(raw)
        raw = repair_unbalanced_code_fences(raw)
        raw = repair_mdx_component_blocks(raw)
        raw = escape_mdx_route_params(raw)
        raw = escape_mdx_text_hazards(raw)
        doc_pages = [
            (
                candidate.title,
                _canonical_page_url(candidate, scan.has_openapi),
            )
            for candidate in self.plan.pages
        ]
        valid_urls, title_to_url, alias_map = build_internal_doc_link_maps(doc_pages)
        raw = repair_internal_doc_links(raw, valid_urls, title_to_url, alias_map)

        return raw

    def _build_source_context(self, page: DocPage) -> str:
        """Build source context using a tiered strategy based on file size.

        Tier 1 (≤200 lines): full source — LLM sees everything
        Tier 2 (201–500 lines): signatures + docstrings + first body lines
        Tier 3 (>500 lines): symbol list + file header + key function signatures

        Total budget: 60,000 chars (raised from 15,000).
        Files are sorted smallest-first so small files always get full inclusion.
        """
        from .parser import parse_file

        max_chars = 60_000
        total_chars = 0
        parts: list[str] = []
        omitted: list[str] = []

        # Load all files, sort smallest first (they benefit most from full inclusion)
        files_data: list[tuple[str, str, int]] = []
        for src_file in page.source_files:
            src_path = self.repo_root / src_file
            if not src_path.exists():
                continue
            try:
                content = src_path.read_text(encoding="utf-8", errors="replace")
                files_data.append((src_file, content, len(content.splitlines())))
            except Exception:
                continue

        files_data.sort(key=lambda x: x[2])  # smallest first

        for src_file, content, line_count in files_data:
            src_path = self.repo_root / src_file
            parsed = parse_file(src_path)
            lang = parsed.language if parsed else ""

            # Build file header block (symbols + imports — always included)
            header = f"\n### File: `{src_file}` ({line_count} lines)\n"
            if parsed and parsed.symbols:
                header += "**Symbols:**\n"
                for s in parsed.symbols:
                    header += f"- {s.kind} `{s.name}` (line {s.start_line})"
                    if s.docstring:
                        header += f": {s.docstring[:150]}"
                    header += "\n"
                header += "\n"
            if parsed and parsed.imports:
                header += f"**Imports**: {', '.join(parsed.imports[:15])}\n\n"

            # Choose code content by tier
            if line_count <= 200:
                # Tier 1: full source
                code = content
            elif line_count <= 500:
                # Tier 2: signatures + first 10 lines of each function
                code = self._extract_signatures(parsed, content)
            else:
                # Tier 3: file header (first 30 lines) + symbol signatures only
                code = self._extract_key_sections(parsed, content)

            remaining = max_chars - total_chars - len(header)
            if remaining <= 200:
                omitted.append(src_file)
                # Still include the header block so LLM knows the file exists
                parts.append(
                    header
                    + "> *[Source omitted — context budget reached. See symbols above.]*\n"
                )
                continue

            if len(code) > remaining:
                code = code[:remaining] + "\n... [truncated — file continues]"

            file_section = header + f"```{lang}\n{code}\n```\n"
            parts.append(file_section)
            total_chars += len(file_section)

        if omitted:
            console.print(
                f"    [dim]⚠ {len(omitted)} large file(s) symbols-only (budget): "
                f"{', '.join(omitted[:5])}{'...' if len(omitted) > 5 else ''}[/dim]"
            )

        return "\n".join(parts)

    def _extract_signatures(self, parsed, content: str) -> str:
        """Tier 2: extract function/class signatures + up to 10 body lines each."""
        if not parsed or not parsed.symbols:
            lines = content.splitlines()
            return "\n".join(lines[:100]) + (
                "\n... [truncated]" if len(lines) > 100 else ""
            )

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

    def _extract_key_sections(self, parsed, content: str) -> str:
        """Tier 3: file header (30 lines) + just signatures of top symbols."""
        lines = content.splitlines()
        header = "\n".join(lines[:30])
        if not parsed or not parsed.symbols:
            return header + "\n... [large file — see symbol list above]"

        sig_lines: list[str] = ["\n\n# [Key Symbol Signatures]"]
        for symbol in parsed.symbols[:25]:
            start = max(0, symbol.start_line - 1)
            end = min(start + 5, len(lines))
            sig_lines.append(f"\n# {symbol.kind}: {symbol.name}")
            sig_lines.extend(lines[start:end])
            sig_lines.append("    ...")

        return header + "\n".join(sig_lines)

    # ──────────────────────────────────────────────────────────────────────
    # Cross-linking helpers (Fix 1)
    # ──────────────────────────────────────────────────────────────────────

    def _build_sitemap_context(self, plan: DocPlan, current_slug: str) -> str:
        """Build a formatted sitemap of all pages for cross-linking.

        The LLM uses this to know what other pages exist and what they cover,
        so it can link to them using [Title](/slug) syntax.
        """
        lines: list[str] = []
        by_section: dict[str, list] = {}
        for page in plan.pages:
            if page.slug == current_slug:
                continue
            section = page.section or "Other"
            by_section.setdefault(section, []).append(page)

        for section, pages in by_section.items():
            lines.append(f"**{section}**")
            for page in pages:
                page_path = _page_url(page, has_openapi=self._scan_has_openapi(plan))
                key_files = ", ".join(f"`{f}`" for f in page.source_files[:4])
                if len(page.source_files) > 4:
                    key_files += f" +{len(page.source_files) - 4} more"
                lines.append(f"- [{page.title}]({page_path}) — {page.description}")
                if key_files:
                    lines.append(f"  *Covers: {key_files}*")

        return (
            "\n".join(lines) if lines else "(no other pages in this documentation site)"
        )

    def _build_dependency_context(
        self, page: DocPage, scan: RepoScan, plan: DocPlan
    ) -> str:
        """Find pages that this page's files import from — these become cross-page links.

        Two sources of dependency info (combined):
        1. Import-based: parse imports from source files, normalize statements to paths,
           resolve paths to repo files, map files to pages.
        2. depends_on: explicit page-slug dependencies from the AI plan (previously unused).

        Uses multi-page ownership so a file in multiple pages contributes all of them.
        """
        from .parser import parse_file

        # Build file → pages lookup (multi-page: one file can belong to several pages)
        file_to_pages: dict[str, list[DocPage]] = {}
        for p in plan.pages:
            for f in p.source_files:
                file_to_pages.setdefault(f, []).append(p)

        # Build slug → page lookup for depends_on resolution
        slug_to_page: dict[str, DocPage] = {p.slug: p for p in plan.pages}

        related: dict[str, DocPage] = {}  # slug → page (deduplicated)

        # Source 1: import-based dependency analysis
        for src_file in page.source_files[:15]:  # cap to avoid slowdown on large pages
            src_path = self.repo_root / src_file
            if not src_path.exists():
                continue
            try:
                parsed = parse_file(src_path)
                if not parsed or not parsed.imports:
                    continue
                lang = parsed.language or ""
                for imp_stmt in parsed.imports:
                    # Normalize: extract module path(s) from full import statement text
                    path_hints = self._normalize_import_statement(imp_stmt, lang)
                    for path_hint in path_hints:
                        resolved = self._resolve_import(
                            path_hint, src_file, scan.file_summaries
                        )
                        if resolved and resolved in file_to_pages:
                            for linked in file_to_pages[resolved]:
                                if linked.slug != page.slug:
                                    related[linked.slug] = linked
            except Exception:
                continue

        # Source 2: explicit depends_on from the AI plan (previously parsed but unused)
        for dep_slug in page.depends_on or []:
            if dep_slug in slug_to_page and dep_slug != page.slug:
                related[dep_slug] = slug_to_page[dep_slug]

        if not related:
            return ""

        lines = [
            "**Dependency Links** (pages this module's files import from — you MUST link to these):"
        ]
        has_openapi = self._scan_has_openapi(plan)
        for p in related.values():
            page_path = _page_url(p, has_openapi=has_openapi)
            lines.append(f"- [{p.title}]({page_path}) — {p.description}")

        return "\n".join(lines)

    def _scan_has_openapi(self, plan: DocPlan | None = None) -> bool:
        """Check whether the current repo has an OpenAPI spec available."""
        return any(
            (self.repo_root / path).exists()
            for path in (
                "openapi.json",
                "openapi.yaml",
                "openapi.yml",
                "swagger.json",
                "swagger.yaml",
                "swagger.yml",
                "docs/openapi.json",
                "docs/openapi.yaml",
                "docs/openapi.yml",
                "docs/swagger.json",
                "docs/swagger.yaml",
                "docs/swagger.yml",
                "api/openapi.json",
                "api/openapi.yaml",
                "api/openapi.yml",
                "spec/openapi.json",
                "spec/openapi.yaml",
            )
        )

    def _normalize_import_statement(self, stmt: str, lang: str) -> list[str]:
        """Extract raw module path(s) from a full import statement string.

        The parsers store the complete statement text (e.g. 'from app.auth import X',
        'import { User } from "../models/user"', 'import "github.com/repo/pkg/auth"').
        This strips the keyword/syntax and returns just the importable path(s).
        """
        import re

        stmt = stmt.strip()
        paths: list[str] = []

        if lang == "python":
            # 'from .auth import X'       → './auth'  (relative)
            # 'from ..models import X'    → '../models'
            # 'from app.services import X'→ 'app/services'
            # 'import app.config'         → 'app/config'
            m = re.match(r"^from\s+(\.+)(\S*)\s+import", stmt)
            if m:
                dots = len(m.group(1))
                module = m.group(2)
                prefix = "./" if dots == 1 else "../" * (dots - 1)
                paths.append(
                    prefix + module.replace(".", "/") if module else prefix.rstrip("/")
                )
                return paths

            m = re.match(r"^from\s+(\S+)\s+import", stmt)
            if m:
                paths.append(m.group(1).replace(".", "/"))
                return paths

            m = re.match(r"^import\s+(\S+)", stmt)
            if m:
                # 'import os' → 'os' (stdlib filtered later); 'import app.config' → 'app/config'
                paths.append(m.group(1).replace(".", "/"))
                return paths

        elif lang in ("javascript", "typescript"):
            # 'import { X } from "../models/user"' → '../models/user'
            # 'import X from "./config"'            → './config'
            # 'import type { X } from "@/types"'   → '@/types'
            # 'const x = require("./config")'       → './config'
            m = re.search(r"""from\s+['"]([^'"]+)['"]""", stmt)
            if m:
                paths.append(m.group(1))
                return paths
            m = re.search(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""", stmt)
            if m:
                paths.append(m.group(1))
                return paths

        elif lang == "go":
            # Single:  import "github.com/user/repo/pkg/auth"
            # Grouped: import (\n  "fmt"\n  "github.com/repo/auth"\n)
            found = re.findall(r'"([^"]+)"', stmt)
            paths.extend(found)
            return paths

        elif lang == "php":
            # 'use App\Services\AuthService;'         → 'App/Services/AuthService'
            # 'use App\Services\{AuthService, User};' → 'App/Services/AuthService', 'App/Services/User'
            m = re.match(r"^use\s+([\w\\]+)", stmt)
            if m:
                base = m.group(1).replace("\\", "/")
                grouped = re.findall(r"\{([^}]+)\}", stmt)
                if grouped:
                    base_ns = base.rsplit("/", 1)[0]
                    for group in grouped:
                        for name in group.split(","):
                            paths.append(
                                base_ns + "/" + name.strip().replace("\\", "/")
                            )
                else:
                    paths.append(base)
            return paths

        # Fallback: return the raw statement — _resolve_import will try to match it
        return [stmt]

    def _resolve_import(
        self, path_hint: str, current_file: str, all_files: dict
    ) -> str | None:
        """Resolve a normalized module path hint to an actual file path in the repo.

        Receives a clean path (NOT a full statement) from _normalize_import_statement.
        Returns the matching file path from all_files, or None if external/unresolvable.
        """
        imp = path_hint.strip()
        if not imp:
            return None

        # Skip well-known stdlib / built-in identifiers
        STDLIB = {
            "os",
            "sys",
            "json",
            "re",
            "io",
            "math",
            "time",
            "path",
            "fs",
            "http",
            "https",
            "net",
            "crypto",
            "util",
            "stream",
            "events",
            "fmt",
            "log",
            "strings",
            "strconv",
            "sort",
            "errors",
            "bytes",
            "context",
            "sync",
            "reflect",
            "regexp",
            "testing",
            "collections",
            "typing",
            "abc",
            "enum",
            "dataclasses",
            "functools",
            "itertools",
            "pathlib",
            "datetime",
            "copy",
            "threading",
            "subprocess",
            "hashlib",
            "base64",
            "struct",
            "socket",
        }
        base = imp.split("/")[0].lstrip(".")
        if base in STDLIB:
            return None

        # Skip npm @org/package scoped packages (but allow @/ alias = repo root)
        if imp.startswith("@") and not imp.startswith("@/") and "/" in imp:
            org, pkg = imp.lstrip("@").split("/", 1)
            if not (self.repo_root / org / pkg).exists():
                return None

        # Resolve to a normalized relative path hint
        if imp.startswith("@/") or imp.startswith("~/"):
            rel_hint = imp[2:]
        elif imp.startswith("./") or imp.startswith("../"):
            # Resolve relative to current file's directory
            current_dir_parts = current_file.replace("\\", "/").split("/")[:-1]
            imp_parts = imp.replace("\\", "/").split("/")
            resolved_parts = list(current_dir_parts)
            for part in imp_parts:
                if part == "..":
                    if resolved_parts:
                        resolved_parts.pop()
                elif part not in (".", ""):
                    resolved_parts.append(part)
            rel_hint = "/".join(resolved_parts)
        else:
            # Absolute module path (Go pkg, Python dotted, TS alias)
            # Take last 2 segments as a fuzzy hint
            segments = [s for s in imp.replace("\\", "/").split("/") if s]
            rel_hint = (
                "/".join(segments[-2:])
                if len(segments) >= 2
                else (segments[0] if segments else imp)
            )

        rel_hint_lower = rel_hint.lower().replace("-", "_")

        # Match against known files (without extension, case-insensitive)
        hint_no_ext = (
            rel_hint_lower.rsplit(".", 1)[0]
            if "." in rel_hint_lower
            else rel_hint_lower
        )

        best: str | None = None
        best_score = 0

        for f in all_files:
            f_norm = f.lower().replace("\\", "/").replace("-", "_")
            f_no_ext = f_norm.rsplit(".", 1)[0]

            # Score: exact suffix > contained match
            if f_no_ext == hint_no_ext or f_no_ext.endswith("/" + hint_no_ext):
                # Exact or exact-suffix match — highest confidence
                if len(f) > best_score:
                    best = f
                    best_score = len(f)
            elif hint_no_ext and hint_no_ext in f_no_ext and len(hint_no_ext) > 3:
                # Substring match — only if hint is meaningful (>3 chars)
                score = len(hint_no_ext)
                if score > best_score:
                    best = f
                    best_score = score

        return best

    # ──────────────────────────────────────────────────────────────────────
    # Post-processing: Mermaid validation (Fix 5)
    # ──────────────────────────────────────────────────────────────────────

    def _validate_and_fix_mermaid(self, content: str) -> str:
        """Find and fix common LLM Mermaid syntax errors in generated markdown."""
        import re

        def fix_block(match: re.Match) -> str:
            diagram = match.group(1)
            fixed = self._fix_mermaid_diagram(diagram)
            return f"```mermaid\n{fixed}\n```"

        return re.sub(r"```mermaid\n(.*?)\n```", fix_block, content, flags=re.DOTALL)

    def _fix_mermaid_diagram(self, diagram: str) -> str:
        """Fix the most common Mermaid mistakes LLMs make."""
        import re

        lines = diagram.splitlines()
        fixed: list[str] = []
        diagram_type = ""

        for line in lines:
            stripped = line.strip().lower()

            # Detect diagram type from first non-empty line
            if not diagram_type and stripped:
                for dtype in (
                    "flowchart",
                    "graph",
                    "sequencediagram",
                    "classdiagram",
                    "erdiagram",
                    "gantt",
                    "pie",
                    "statediagram",
                ):
                    if stripped.startswith(dtype):
                        diagram_type = dtype
                        break

            # Fix 1: Unquoted node labels with parentheses in flowchart/graph
            # Pattern: A(text with (nested parens)) → A["text with (nested parens)"]
            if diagram_type in ("flowchart", "graph", ""):
                line = re.sub(
                    r"\b(\w[\w-]*)\(([^()]*\([^()]*\)[^()]*)\)",
                    lambda m: f'{m.group(1)}["{m.group(2)}"]',
                    line,
                )
                line = re.sub(
                    r'^(\s*)([A-Za-z][\w-]*)\s*--\s*"([^"]+)"\s*-->\s*([A-Za-z][\w-]*)\s*$',
                    lambda m: (
                        f"{m.group(1)}{m.group(2)} -->|{m.group(3)}| {m.group(4)}"
                    ),
                    line,
                )
                line = re.sub(
                    r"^(\s*)([A-Za-z][\w-]*)\s*<--\s*([A-Za-z][\w-]*)\s*$",
                    lambda m: f"{m.group(1)}{m.group(3)} --> {m.group(2)}",
                    line,
                )
                line = re.sub(
                    r"^(\s*)([A-Za-z][\w-]*)\s*<-->\s*([A-Za-z][\w-]*)\s*$",
                    lambda m: (
                        f"{m.group(1)}{m.group(2)} --> {m.group(3)}\n"
                        f"{m.group(1)}{m.group(3)} --> {m.group(2)}"
                    ),
                    line,
                )

            # Fix 2: Node labels with colons not in quotes (breaks mermaid parser)
            # A[label: value] → A["label: value"]
            line = re.sub(
                r'\[([^\]"]*:[^\]"]*)\]',
                lambda m: (
                    f'["{m.group(1)}"]'
                    if ":" in m.group(1) and not m.group(1).startswith('"')
                    else f"[{m.group(1)}]"
                ),
                line,
            )

            # Fix 3: Bare --> with text that has special chars — wrap in quotes
            # Already valid in most cases, skip aggressive fixes here

            # Fix 4: classDiagram method arrows that use -> instead of --
            if diagram_type == "classdiagram":
                line = re.sub(r"\s+->\s+", " --> ", line)
                line = re.sub(
                    r'(-->\s+)"([A-Za-z][A-Za-z0-9_]*)"',
                    r"\1\2",
                    line,
                )

            # Fix 5: sequenceDiagram participants emitted with flowchart node syntax
            if diagram_type == "sequencediagram":
                line = re.sub(
                    r'^(\s*participant\s+)([A-Za-z][\w-]*)\["([^"]+)"\]\s*$',
                    lambda m: f"{m.group(1)}{m.group(2)} as {m.group(3)}",
                    line,
                )

            if diagram_type in ("statediagram", "statediagram-v2"):
                line = re.sub(
                    r'"([A-Za-z][A-Za-z0-9_]*)"',
                    r"\1",
                    line,
                )

            fixed.append(line)

        result = "\n".join(fixed)

        # Fix 6: Duplicate node IDs in flowcharts (just warn via comment, can't auto-fix safely)
        if diagram_type in ("flowchart", "graph"):
            node_ids = re.findall(r"\b([A-Za-z][\w-]*)\s*[\[({\|]", result)
            seen: set[str] = set()
            dupes: list[str] = []
            for nid in node_ids:
                if nid in seen:
                    dupes.append(nid)
                seen.add(nid)
            if dupes:
                result = (
                    f"%% Note: possible duplicate node IDs: {', '.join(set(dupes))}\n"
                    + result
                )

        return result

    # ──────────────────────────────────────────────────────────────────────
    # Post-processing: File reference validation (Fix 6)
    # ──────────────────────────────────────────────────────────────────────

    def _validate_file_refs(self, content: str, scan: RepoScan, page: DocPage) -> str:
        """Validate `file/path.ts:line` references in generated markdown.

        - Removes references to files that don't exist in the repo
        - Fixes line numbers that exceed file length
        - Cross-checks symbol names against parsed AST where possible
        """
        import re

        from .parser import parse_file

        known_files = set(scan.file_summaries.keys())

        # Build symbol → (file, actual_line) lookup from this page's source files
        symbol_locations: dict[str, tuple[str, int]] = {}
        for src_file in page.source_files:
            src_path = self.repo_root / src_file
            if not src_path.exists():
                continue
            try:
                parsed = parse_file(src_path)
                if parsed and parsed.symbols:
                    for sym in parsed.symbols:
                        # Store both bare name and name() form
                        symbol_locations[sym.name] = (src_file, sym.start_line)
                        symbol_locations[f"{sym.name}()"] = (src_file, sym.start_line)
            except Exception:
                continue

        # Cache for file line counts (avoid re-reading repeatedly)
        file_line_counts: dict[str, int] = {}

        def get_line_count(path: str) -> int:
            if path not in file_line_counts:
                try:
                    text = (self.repo_root / path).read_text(
                        encoding="utf-8", errors="replace"
                    )
                    file_line_counts[path] = len(text.splitlines())
                except Exception:
                    file_line_counts[path] = 0
            return file_line_counts[path]

        def fix_ref(match: re.Match) -> str:
            path = match.group(1)
            line_str = match.group(2)

            # Check if file exists in repo
            if path not in known_files and not (self.repo_root / path).exists():
                # File invented by LLM — strip line ref, keep just the path in backticks
                return f"`{path}`"

            # File exists — validate line number
            if line_str:
                try:
                    line_num = int(line_str)
                    total = get_line_count(path)
                    if total > 0 and line_num > total:
                        # Line number is out of range — strip it
                        return f"`{path}`"
                except ValueError:
                    pass

            return match.group(0)  # unchanged

        # Pattern matches: `path/to/file.ext:123` (backtick-wrapped file:line refs)
        content = re.sub(
            r"`([a-zA-Z][a-zA-Z0-9_./-]*\.[a-zA-Z]{1,8}):(\d+)`",
            fix_ref,
            content,
        )

        return content

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

    def _call_llm_with_retry(self, user_prompt: str) -> str:
        """Call LLM with exponential backoff + jitter on transient errors."""
        import random

        for attempt in range(MAX_RETRIES):
            try:
                return self.llm.complete(SYSTEM_V2, user_prompt)
            except Exception as e:
                err = str(e)
                is_last = attempt == MAX_RETRIES - 1

                if self._is_retryable(err):
                    if is_last:
                        console.print(
                            f"    [red]✗ LLM call failed after {MAX_RETRIES} attempts: {e}[/red]"
                        )
                        raise
                    wait = RATE_LIMIT_BACKOFF * (2**attempt) + random.uniform(0, 1.5)
                    console.print(
                        f"    [yellow]⏳ Transient error — waiting {wait:.1f}s before retry {attempt + 1}/{MAX_RETRIES}...[/yellow]"
                    )
                    time.sleep(wait)
                elif is_last:
                    console.print(
                        f"    [red]✗ LLM call failed after {MAX_RETRIES} attempts: {e}[/red]"
                    )
                    raise
                else:
                    console.print(
                        f"    [yellow]⚠ LLM error (attempt {attempt + 1}/{MAX_RETRIES}): {e} — retrying...[/yellow]"
                    )
                    time.sleep(1 + random.uniform(0, 0.5))
        raise RuntimeError("Max retries exceeded")

    def _page_is_stale(self, page: DocPage) -> bool:
        """Check if any source file for this page has changed."""
        for src_file in page.source_files:
            src_path = self.repo_root / src_file
            if not src_path.exists():
                continue
            try:
                content = src_path.read_text(encoding="utf-8", errors="replace")
                if self.manifest.is_stale(src_file, content):
                    return True
            except Exception:
                return True
        return False

    # ──────────────────────────────────────────────────────────────────────
    # Phase 4: API Playground
    # ──────────────────────────────────────────────────────────────────────

    def _setup_playground(self, scan: RepoScan) -> bool:
        """Stage OpenAPI assets for the generated Fumadocs API reference route."""
        return stage_openapi_assets(self.repo_root, scan.openapi_paths)

    # ──────────────────────────────────────────────────────────────────────
    # Phase 5: Build site
    # ──────────────────────────────────────────────────────────────────────

    def _build_site(self, plan: DocPlan, has_openapi: bool) -> None:
        """Build the generated Fumadocs site from the AI's nav plan."""
        from .site.builder import build_fumadocs_from_plan

        build_fumadocs_from_plan(
            self.repo_root, self.output_dir, self.cfg, plan, has_openapi
        )
        console.print("[green]✓[/green] Fumadocs site built")

    # ──────────────────────────────────────────────────────────────────────
    # Persistence helpers
    # ──────────────────────────────────────────────────────────────────────

    def _save_plan(self, plan) -> None:
        """Save the doc plan as JSON for the updater to use later.

        Handles both legacy DocPlan and new BucketDocPlan.
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Check if this is a bucket-based plan
        if hasattr(plan, "buckets"):
            plan_data = {
                "version": "v2_buckets",
                "buckets": [
                    {
                        "bucket_type": b.bucket_type,
                        "title": b.title,
                        "slug": b.slug,
                        "section": b.section,
                        "description": b.description,
                        "depends_on": b.depends_on,
                        "owned_files": b.owned_files,
                        "owned_symbols": b.owned_symbols,
                        "artifact_refs": b.artifact_refs,
                        "required_sections": b.required_sections,
                        "required_diagrams": b.required_diagrams,
                        "coverage_targets": b.coverage_targets,
                        "priority": b.priority,
                    }
                    for b in plan.buckets
                ],
                "nav_structure": plan.nav_structure,
                "skipped_files": plan.skipped_files,
                "integration_candidates": getattr(plan, "integration_candidates", []),
            }
        else:
            plan_data = {
                "version": "v1_legacy",
                "pages": [
                    {
                        "title": p.title,
                        "slug": p.slug,
                        "page_type": p.page_type,
                        "description": p.description,
                        "source_files": p.source_files,
                        "section": p.section,
                        "priority": p.priority,
                    }
                    for p in plan.pages
                ],
                "nav_structure": plan.nav_structure,
                "skipped_files": plan.skipped_files,
            }

        (self.repo_root / ".deepdoc_plan.json").write_text(
            json.dumps(plan_data, indent=2), encoding="utf-8"
        )

    def _save_file_page_map(self, plan: DocPlan) -> None:
        """Save file→page mapping so the updater knows which pages to regenerate."""
        mapping: dict[str, list[str]] = {}
        for page in plan.pages:
            for src_file in page.source_files:
                mapping.setdefault(src_file, []).append(page.slug)

        (self.repo_root / ".deepdoc_file_map.json").write_text(
            json.dumps(mapping, indent=2), encoding="utf-8"
        )

    def _print_summary(self, stats: dict[str, int]) -> None:
        stale_line = ""
        if stats.get("stale_pages_removed"):
            stale_line = f"  Stale removed:    [cyan]{stats.get('stale_pages_removed', 0)}[/cyan]\n"
        quality_line = ""
        if (
            stats.get("pages_invalid")
            or stats.get("pages_degraded")
            or stats.get("page_warnings")
        ):
            quality_line = (
                f"  Invalid pages:    [cyan]{stats.get('pages_invalid', 0)}[/cyan]\n"
                f"  Degraded pages:   [cyan]{stats.get('pages_degraded', 0)}[/cyan]\n"
                f"  Warnings:         [cyan]{stats.get('page_warnings', 0)}[/cyan]\n"
            )

        console.print()
        console.print(
            Panel.fit(
                f"[bold green]Documentation generated![/bold green]\n\n"
                f"  Files scanned:    [cyan]{stats.get('files_scanned', 0)}[/cyan]\n"
                f"  Pages planned:    [cyan]{stats.get('pages_planned', 0)}[/cyan]\n"
                f"  Pages generated:  [cyan]{stats.get('pages_generated', 0)}[/cyan]\n"
                f"  Status:           [cyan]{stats.get('status', 'unknown')}[/cyan]\n"
                f"{quality_line}"
                f"{stale_line}"
                f"  API reference:    [cyan]{'yes' if stats.get('playground') else 'no'}[/cyan]\n\n"
                f"[dim]Preview: [bold]deepdoc serve[/bold]  |  Deploy: [bold]deepdoc deploy[/bold][/dim]",
                title="DeepDoc",
                border_style="green",
            )
        )

    def _save_quality_report(self, stats: dict[str, Any]) -> None:
        state_dir = self.repo_root / ".deepdoc"
        state_dir.mkdir(parents=True, exist_ok=True)
        quality_payload = {
            "status": stats.get("status", "unknown"),
            "pages_generated": stats.get("pages_generated", 0),
            "pages_failed": stats.get("pages_failed", 0),
            "pages_invalid": stats.get("pages_invalid", 0),
            "pages_degraded": stats.get("pages_degraded", 0),
            "page_warnings": stats.get("page_warnings", 0),
            "quality_report": stats.get("quality_report", {}),
        }
        (state_dir / "generation_quality.json").write_text(
            json.dumps(quality_payload, indent=2) + "\n",
            encoding="utf-8",
        )
