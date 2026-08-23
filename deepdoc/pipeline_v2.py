"""V2 Pipeline — AI-planned, batched, diagram-rich generation.

Flow:
    1. SCAN  — collect file tree, symbols, endpoints, OpenAPI specs (no LLM)
    2. PLAN  — multi-step bucket planner (3 LLM calls) OR legacy single-call planner
    3. GENERATE — execute plan page-by-page, batched (N LLM calls)
    4. API REF — stage OpenAPI assets for the generated API reference page
    5. BUILD — write the Next.js + Fumadocs site scaffold (site/ + deepdoc.config.json)

The manifest tracks: source_file → content_hash → [page_slugs]
So `deepdoc update` can diff changed files → find affected pages → regenerate only those.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .persistence_v2 import DocPage
    from .v2_models import DocPlan, RepoScan

from rich.console import Console
from rich.panel import Panel

from .chatbot.settings import chatbot_enabled
from .generator import (
    BucketGenerationEngine,
    summarize_generation_results,
)
from .llm import LLMClient
from .manifest import Manifest
from .openapi import (
    extract_endpoints_from_spec,
    find_openapi_specs,
    parse_openapi_spec,
)
from .changelog_writer import record_and_write as _record_changelog
from .persistence_v2 import (
    atomic_write_json,
    atomic_write_text,
    cleanup_stale_generated_files,
    deepdoc_state_lock,
    load_changelog,
    load_generation_ledger,
    load_plan,
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
from .source_metadata import KNOWN_UNSUPPORTED_LANGUAGE_EXTENSIONS
from .telemetry import RunTelemetry

console = Console()




def _endpoint_ref_slug(method: str, path: str) -> str:
    """Build the canonical endpoint_ref slug used by the planner."""
    import re

    path_slug = re.sub(r"[/:{}<>]+", "-", path).strip("-").lower()
    return f"{method.lower()}-{path_slug}"


def _spec_base_path(spec: dict) -> str:
    """Return the base path from the first server URL, e.g. '/api/v2'."""
    from urllib.parse import urlparse
    if "openapi" in spec:
        servers = spec.get("servers", [])
        if servers:
            url = str(servers[0].get("url", "") or "").strip()
            parsed = urlparse(url)
            base = parsed.path if (parsed.scheme or parsed.netloc) else url
            return base.rstrip("/")
    elif "swagger" in spec:
        return spec.get("basePath", "").rstrip("/")
    return ""


def _write_spec(dest: Path, spec: dict) -> None:
    """Write spec dict to dest as YAML or JSON depending on suffix."""
    if dest.suffix == ".json":
        atomic_write_text(dest, json.dumps(spec, indent=2) + "\n")
    else:
        try:
            import yaml
            atomic_write_text(
                dest,
                yaml.dump(spec, allow_unicode=True, sort_keys=False, default_flow_style=False),
            )
        except ImportError:
            atomic_write_text(dest, json.dumps(spec, indent=2) + "\n")


def _build_endpoint_to_bucket_map(
    plan: "DocPlan | None",
    scanned_endpoints: list[dict] | None,
) -> dict[tuple[str, str], tuple[str, str]]:
    """Map (METHOD, path) → (owning_bucket_slug, owning_bucket_title).

    Resolution: find the scanned endpoint whose method+path matches, then look up
    the feature/endpoint-family bucket whose owned_files contains that handler file.
    """
    if not plan or not scanned_endpoints:
        return {}

    file_to_bucket: dict[str, tuple[str, str]] = {}
    for bucket in plan.buckets:
        hints = bucket.generation_hints or {}
        if hints.get("is_endpoint_ref"):
            continue
        is_endpoint_owner = (
            hints.get("is_endpoint_family")
            or hints.get("include_endpoint_detail")
            or hints.get("prompt_style") == "endpoint"
        )
        for f in bucket.owned_files:
            if f in file_to_bucket and not is_endpoint_owner:
                continue
            file_to_bucket[f] = (bucket.slug, bucket.title)

    mapping: dict[tuple[str, str], tuple[str, str]] = {}
    for ep in scanned_endpoints:
        method = str(ep.get("method") or "").upper()
        path = str(ep.get("path") or "")
        file = str(ep.get("file") or "")
        if not (method and path and file):
            continue
        owner = file_to_bucket.get(file)
        if owner:
            mapping[(method, path)] = owner
    return mapping


def stage_openapi_assets(
    repo_root: Path,
    openapi_paths: list[str] | None = None,
    plan: "DocPlan | None" = None,
    scanned_endpoints: list[dict] | None = None,
) -> bool:
    """Stage all detected OpenAPI specs for the generated site."""
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

    endpoint_owner_map = _build_endpoint_to_bucket_map(plan, scanned_endpoints)

    combined_manifest: list[dict[str, str]] = []
    for index, spec_rel_path in enumerate(detected_paths, start=1):
        spec_src = repo_root / spec_rel_path
        if not spec_src.exists():
            continue

        spec_name = _staged_spec_name(spec_rel_path, index)
        staged_spec = site_openapi_dir / spec_name

        spec = parse_openapi_spec(spec_src)
        if not spec:
            console.print(
                f"[yellow]⚠[/yellow] Could not parse {spec_name} — skipping API pages"
            )
            continue

        # Bake the server base path into each path key so the rendered spec
        # shows full paths without relying on the server URL prefix.
        base_path = _spec_base_path(spec)
        if base_path and not any(
            k.startswith(base_path) for k in spec.get("paths", {})
        ):
            spec = {
                **spec,
                "paths": {base_path + k: v for k, v in spec["paths"].items()},
                "servers": [{"url": "/"}],
            }

        _write_spec(staged_spec, spec)

        endpoints = extract_endpoints_from_spec(spec)
        manifest: list[dict[str, str]] = []
        for ep in endpoints:
            if ep.get("deprecated"):
                continue

            method = ep["method"].upper()
            path = ep["path"]
            summary = ep.get("summary") or f"{method} {path}"
            entry: dict[str, Any] = {
                "slug": _endpoint_ref_slug(method, path),
                "title": summary,
                "method": method,
                "path": path,
                "source_spec": spec_name,
                "source_path": spec_rel_path,
            }
            owner = endpoint_owner_map.get((method, path))
            if owner is None and base_path and path.startswith(base_path):
                owner = endpoint_owner_map.get((method, path[len(base_path):] or "/"))
            if owner:
                entry["owning_bucket_slug"] = owner[0]
                entry["owning_bucket_title"] = owner[1]
            manifest.append(entry)

        if manifest:
            combined_manifest.extend(manifest)
            console.print(
                f"[green]✓[/green] Staged {len(manifest)} OpenAPI endpoints from {spec_rel_path}"
            )
            continue

        console.print(f"[yellow]⚠[/yellow] No endpoints found in {spec_name}")

    if combined_manifest:
        atomic_write_text(
            site_openapi_dir / "manifest.json",
            json.dumps(combined_manifest, indent=2) + "\n",
        )
        return True

    manifest_path = site_openapi_dir / "manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()
    return False


def _staged_spec_name(spec_rel_path: str, index: int) -> str:
    """Return a non-colliding generated OpenAPI spec filename."""
    import re

    src = Path(spec_rel_path)
    suffix = src.suffix if src.suffix.lower() in {".json", ".yaml", ".yml"} else ".json"
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", src.with_suffix("").as_posix()).strip("-")
    digest = hashlib.sha1(spec_rel_path.encode("utf-8")).hexdigest()[:8]
    return f"deepdoc-openapi-{index}-{stem}-{digest}{suffix}"


class PipelineV2:
    def __init__(
        self,
        repo_root: Path,
        cfg: dict[str, Any],
        telemetry: RunTelemetry | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.cfg = cfg
        self.output_dir = repo_root / cfg.get("output_dir", "docs")
        self.telemetry = telemetry or RunTelemetry(repo_root, "generate")
        self._owns_telemetry = telemetry is None
        self.llm = LLMClient(cfg, telemetry=self.telemetry)
        self.manifest = Manifest(self.output_dir)

    def run(self, force: bool = False, reconcile: bool = False) -> dict[str, Any]:
        try:
            with deepdoc_state_lock(self.repo_root):
                stats = self._run_locked(
                    force=force,
                    reconcile=True if force else reconcile,
                )
            if self._owns_telemetry:
                self.telemetry.finish(
                    stats.get("status", "success"),
                    files_scanned=stats.get("files_scanned", 0),
                    pages_planned=stats.get("pages_planned", 0),
                    pages_generated=stats.get("pages_generated", 0),
                    pages_failed=stats.get("pages_failed", 0),
                    pages_skipped=stats.get("pages_skipped", 0),
                )
            return stats
        except BaseException as exc:
            if self._owns_telemetry:
                self.telemetry.finish("failed", error_type=type(exc).__name__)
            raise

    def _run_locked(self, force: bool = False, reconcile: bool = False) -> dict[str, Any]:
        stats: dict[str, Any] = {}
        phase_timings: dict[str, float] = {}
        previous_ledger = load_generation_ledger(self.repo_root) if reconcile else {}
        chatbot_sync_ok = True

        # ── Phase 1: Scan ──────────────────────────────────────────────
        console.print(
            Panel("[bold]Phase 1/5: Scanning repository[/bold]", border_style="blue")
        )
        phase_start = time.perf_counter()
        with self.telemetry.span("pipeline.scan"):
            scan = bucket_scan_repo(
                self.repo_root,
                self.cfg,
                telemetry=self.telemetry,
            )
        phase_timings["scan"] = time.perf_counter() - phase_start
        self._print_scan(scan)
        stats["files_scanned"] = scan.total_files

        # ── Phase 2: Plan ──────────────────────────────────────────────
        # When force=False and a saved plan exists with the same file count,
        # reuse it so an interrupted generate can resume without re-planning.
        cached_plan = None if force else load_plan(self.repo_root)
        _plan_reused = False
        if cached_plan is not None and hasattr(cached_plan, "buckets"):
            cached_files = {f for b in cached_plan.buckets for f in (b.owned_files or [])}
            scan_files = set(scan.file_summaries.keys())
            # Accept cached plan when ≥90% of its files still exist in the scan.
            overlap = len(cached_files & scan_files)
            if not cached_files or overlap / len(cached_files) >= 0.90:
                plan = cached_plan
                _plan_reused = True
                console.print(
                    Panel(
                        f"[bold]Phase 2/5: Reusing saved plan[/bold] "
                        f"[dim]({len(plan.buckets)} buckets — use --clean to re-plan)[/dim]",
                        border_style="dim",
                    )
                )

        if not _plan_reused:
            console.print(
                Panel(
                    "[bold]Phase 2/5: Multi-step bucket planner (3 LLM calls)[/bold]",
                    border_style="blue",
                )
            )
            phase_start = time.perf_counter()
            with self.telemetry.span("pipeline.plan"):
                plan = bucket_plan_docs(
                    scan,
                    self.cfg,
                    self.llm,
                    repo_root=self.repo_root,
                )
            phase_timings["plan"] = time.perf_counter() - phase_start

        stats["pages_planned"] = len(plan.pages)
        self._print_coverage(scan, plan)

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
        with self.telemetry.span("pipeline.generate_pages"):
            gen_results = engine.generate_all(force=force)
        phase_timings["generate"] = time.perf_counter() - phase_start
        from .generator.consistency import CrossBucketConsistencyPass
        with self.telemetry.span("pipeline.consistency"):
            injected = CrossBucketConsistencyPass(
                self.llm,
                self.output_dir,
                self.cfg,
            ).run(gen_results)
        if injected:
            console.print(f"[dim]  ↳ consistency pass: {injected} cross-link(s) injected[/dim]")

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

        # ── Glossary auto-link pass ───────────────────────────────────
        try:
            with self.telemetry.span("pipeline.glossary"):
                self._apply_glossary_links()
        except Exception as exc:
            console.print(f"[dim]Glossary auto-link skipped: {exc}[/dim]")

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
            with self.telemetry.span("pipeline.openapi"):
                openapi_ready = self._setup_playground(scan, plan)
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

        # ── Persist state ──────────────────────────────────────────────
        phase_start = time.perf_counter()
        with self.telemetry.span("pipeline.persist_state"):
            save_all(plan, scan, gen_results, self.repo_root, self.output_dir)
        stats["llm_usage"] = dict(getattr(self.llm, "usage", {}) or {})
        self._save_quality_report(stats)
        phase_timings["persist"] = time.perf_counter() - phase_start

        # ── Record changelog after save_all so entries reference persisted pages ──
        try:
            import git as _git

            _repo_cl = _git.Repo(self.repo_root)
            _head_cl = _repo_cl.head.commit
            _changelog_exists = bool(load_changelog(self.repo_root))
            with self.telemetry.span("pipeline.changelog"):
                _record_changelog(
                    self.repo_root,
                    self.output_dir,
                    commit=_head_cl.hexsha,
                    commit_message=_head_cl.message.strip().splitlines()[0],
                    commit_date=_head_cl.committed_datetime.strftime("%Y-%m-%d"),
                    strategy="full_generate",
                    pages_updated=[b.slug for b in plan.buckets],
                    files_changed=[],
                    is_initial=not _changelog_exists,
                )
        except Exception:
            pass  # Not a git repo or detached HEAD — skip silently

        # ── Phase 5: Build site ────────────────────────────────────────
        console.print(
            Panel("[bold]Phase 5/5: Building site[/bold]", border_style="blue")
        )
        phase_start = time.perf_counter()
        # Inject whats-changed into nav before the site is built so the page
        # appears in the sidebar from the very first generate run.
        _wc_section = plan.nav_structure.setdefault("Start Here", [])
        if "whats-changed" not in _wc_section:
            _wc_section.append("whats-changed")
        with self.telemetry.span("pipeline.site_scaffold"):
            self._build_site(plan, has_openapi=openapi_ready)
        phase_timings["build_site"] = time.perf_counter() - phase_start
        stats["site"] = 1

        if chatbot_enabled(self.cfg):
            try:
                from .chatbot.indexer import ChatbotIndexer

                console.print("[dim]Starting chatbot index sync...[/dim]")
                with self.telemetry.span("pipeline.chatbot_sync"):
                    chatbot_stats = ChatbotIndexer(
                        self.repo_root,
                        self.cfg,
                        telemetry=self.telemetry,
                    ).sync_full(
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
        final_sync_start = time.perf_counter()
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
        finally:
            self.telemetry.record_duration(
                "pipeline.final_sync",
                time.perf_counter() - final_sync_start,
            )

        if reconcile:
            with self.telemetry.span("pipeline.stale_cleanup"):
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

        unsupported_langs = {
            ext: count
            for ext, count in scan.unsupported_extensions.items()
            if ext in KNOWN_UNSUPPORTED_LANGUAGE_EXTENSIONS
        }
        if unsupported_langs:
            named = ", ".join(
                f"{KNOWN_UNSUPPORTED_LANGUAGE_EXTENSIONS[ext]} ({ext}, {count} file"
                f"{'s' if count != 1 else ''})"
                for ext, count in sorted(unsupported_langs.items(), key=lambda x: -x[1])
            )
            console.print(
                f"[yellow]⚠ Unsupported languages present, not parsed or documented: "
                f"{named}[/yellow]"
            )

    def _print_coverage(self, scan: RepoScan, plan) -> None:
        """Surface how much of the repo actually made it into documentation.

        DeepDoc can silently document a small slice of a repo and report
        success. This reports total scanned source files vs. documented vs.
        orphaned/skipped, so a partially-invisible repo is visible, not hidden.
        """
        from rich.table import Table

        total_source_files = len(scan.file_contents)
        documented_files = {
            f for bucket in plan.buckets for f in (bucket.owned_files or [])
        } & set(scan.file_contents)
        orphaned_or_skipped = (set(plan.orphaned_files) | set(plan.skipped_files)) & set(
            scan.file_contents
        )
        coverage_pct = (
            (len(documented_files) / total_source_files * 100)
            if total_source_files
            else 0.0
        )

        t = Table(
            title="Coverage",
            show_header=True,
            header_style="bold",
        )
        t.add_column("Metric", style="cyan")
        t.add_column("Value", justify="right")
        t.add_row("Source files scanned", str(total_source_files))
        t.add_row("Documented", str(len(documented_files)))
        t.add_row("Orphaned / skipped", str(len(orphaned_or_skipped)))
        t.add_row("Coverage", f"{coverage_pct:.1f}%")
        console.print(t)
        style = "green" if coverage_pct >= 80 else "yellow" if coverage_pct >= 40 else "red"
        console.print(f"[{style}]Coverage: {coverage_pct:.1f}%[/{style}]")

    # ──────────────────────────────────────────────────────────────────────
    # Phase 4: API Playground
    # ──────────────────────────────────────────────────────────────────────

    def _apply_glossary_links(self) -> None:
        """Auto-link domain-glossary terms across all generated pages.

        Single pass: parse `### term` headings from the glossary page, then for
        every other generated .md, replace the first occurrence of each term
        with a link to domain-glossary.md#<slug>. Skips code blocks, headings,
        existing links, and the glossary page itself.
        """
        from .generator.post_processors import (
            extract_glossary_terms,
            link_glossary_terms,
        )

        glossary_path = self.output_dir / "domain-glossary.md"
        if not glossary_path.exists():
            return
        try:
            glossary_content = glossary_path.read_text(encoding="utf-8")
        except OSError:
            return
        terms = extract_glossary_terms(glossary_content)
        if not terms:
            return

        rewritten = 0
        for md_path in self.output_dir.glob("*.md"):
            if md_path.name == "domain-glossary.md":
                continue
            try:
                original = md_path.read_text(encoding="utf-8")
            except OSError:
                continue
            updated = link_glossary_terms(original, terms)
            if updated != original:
                atomic_write_text(md_path, updated)
                rewritten += 1
        if rewritten:
            console.print(
                f"[dim]✓ Auto-linked glossary terms across {rewritten} pages "
                f"({len(terms)} terms)[/dim]"
            )

    def _setup_playground(self, scan: RepoScan, plan: "DocPlan | None" = None) -> bool:
        """Stage OpenAPI assets for the generated API reference page."""
        return stage_openapi_assets(
            self.repo_root,
            scan.openapi_paths,
            plan=plan,
            scanned_endpoints=scan.api_endpoints,
        )

    # ──────────────────────────────────────────────────────────────────────
    # Phase 5: Build site
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
                key_files = ", ".join(f"`{f}`" for f in page.source_files[:4])
                if len(page.source_files) > 4:
                    key_files += f" +{len(page.source_files) - 4} more"
                lines.append(f"- [{page.title}](/{page.slug}) — {page.description}")
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
        2. depends_on: explicit page-slug dependencies from the AI plan.
        """
        from .parser import parse_file

        file_to_pages: dict[str, list[DocPage]] = {}
        for p in plan.pages:
            for f in p.source_files:
                file_to_pages.setdefault(f, []).append(p)

        slug_to_page: dict[str, DocPage] = {p.slug: p for p in plan.pages}

        related: dict[str, DocPage] = {}

        for src_file in page.source_files[:15]:
            src_path = self.repo_root / src_file
            if not src_path.exists():
                continue
            try:
                parsed = parse_file(src_path)
                if not parsed or not parsed.imports:
                    continue
                lang = parsed.language or ""
                for imp_stmt in parsed.imports:
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

        for dep_slug in page.depends_on or []:
            if dep_slug in slug_to_page and dep_slug != page.slug:
                related[dep_slug] = slug_to_page[dep_slug]

        if not related:
            return ""

        lines = [
            "**Dependency Links** (pages this module's files import from — you MUST link to these):"
        ]
        for p in related.values():
            lines.append(f"- [{p.title}](/{p.slug}) — {p.description}")

        return "\n".join(lines)

    def _normalize_import_statement(self, stmt: str, lang: str) -> list[str]:
        """Extract raw module path(s) from a full import statement string."""
        import re

        stmt = stmt.strip()
        paths: list[str] = []

        if lang == "python":
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
                paths.append(m.group(1).replace(".", "/"))
                return paths
        elif lang in ("javascript", "typescript"):
            m = re.search(r"""from\s+['"]([^'"]+)['"]""", stmt)
            if m:
                paths.append(m.group(1))
                return paths
            m = re.search(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""", stmt)
            if m:
                paths.append(m.group(1))
                return paths
        elif lang == "go":
            found = re.findall(r'"([^"]+)"', stmt)
            paths.extend(found)
            return paths
        elif lang == "php":
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

        return [stmt]

    def _resolve_import(
        self, path_hint: str, current_file: str, all_files: dict
    ) -> str | None:
        """Resolve a normalized module path hint to an actual file path in the repo."""
        imp = path_hint.strip()
        if not imp:
            return None

        STDLIB = {
            "os", "sys", "json", "re", "io", "math", "time", "path", "fs", "http",
            "https", "net", "crypto", "util", "stream", "events", "fmt", "log",
            "strings", "strconv", "sort", "errors", "bytes", "context", "sync",
            "reflect", "regexp", "testing", "collections", "typing", "abc", "enum",
            "dataclasses", "functools", "itertools", "pathlib", "datetime", "copy",
            "threading", "subprocess", "hashlib", "base64", "struct", "socket",
        }
        base = imp.split("/")[0].lstrip(".")
        if base in STDLIB:
            return None

        if imp.startswith("@") and not imp.startswith("@/") and "/" in imp:
            org, pkg = imp.lstrip("@").split("/", 1)
            if not (self.repo_root / org / pkg).exists():
                return None

        if imp.startswith("@/") or imp.startswith("~/"):
            rel_hint = imp[2:]
        elif imp.startswith("./") or imp.startswith("../"):
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
            segments = [s for s in imp.replace("\\", "/").split("/") if s]
            rel_hint = (
                "/".join(segments[-2:])
                if len(segments) >= 2
                else (segments[0] if segments else imp)
            )

        rel_hint_lower = rel_hint.lower().replace("-", "_")
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
            if f_no_ext == hint_no_ext or f_no_ext.endswith("/" + hint_no_ext):
                if len(f) > best_score:
                    best = f
                    best_score = len(f)
            elif hint_no_ext and hint_no_ext in f_no_ext and len(hint_no_ext) > 3:
                score = len(hint_no_ext)
                if score > best_score:
                    best = f
                    best_score = score

        return best

    def _build_site(self, plan: DocPlan, has_openapi: bool) -> None:
        """Build the Next.js + Fumadocs site scaffold from the AI's nav plan."""
        from .site.builder import build_next_from_plan

        build_next_from_plan(
            self.repo_root, self.output_dir, self.cfg, plan, has_openapi
        )
        console.print("[green]✓[/green] Next.js site scaffold written")

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
            "llm_usage": stats.get("llm_usage", {}),
        }
        atomic_write_json(
            state_dir / "generation_quality.json",
            quality_payload,
            trailing_newline=True,
        )
