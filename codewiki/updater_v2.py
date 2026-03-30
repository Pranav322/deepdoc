"""V2 Updater — uses the saved plan + file-page map to update only affected pages.

Flow:
    1. git diff → find changed files
    2. Load .codewiki_file_map.json → find which doc pages those files affect
    3. Regenerate only those pages (using saved plan for context)
    4. Rebuild nav if needed
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel

from .llm import LLMClient
from .manifest import Manifest, file_hash
from .parser import parse_file, supported_extensions
from ._legacy_types import DocPage, DocPlan, RepoScan
from .planner_v2 import scan_repo
from .prompts_v2 import SYSTEM_V2, UPDATE_PAGE_V2
from .persistence_v2 import (
    load_plan, load_file_map, load_generation_ledger,
    find_stale_buckets, save_all,
)

console = Console()


class UpdaterV2:
    def __init__(self, repo_root: Path, cfg: dict[str, Any]) -> None:
        self.repo_root = repo_root
        self.cfg = cfg
        self.output_dir = repo_root / cfg.get("output_dir", "docs")
        self.llm = LLMClient(cfg)
        self.manifest = Manifest(self.output_dir)

    def update(self, since: str = "HEAD~1") -> int:
        """Update docs for files changed since `since`. Returns page count.

        Routes to bucket-aware update if the saved plan is v2_buckets,
        otherwise falls back to legacy page-level update.
        """
        # Step 1: Load saved plan (determines which code path to take)
        plan = load_plan(self.repo_root)

        # Route to bucket-aware updater for v2 plans
        if plan is not None and hasattr(plan, "buckets"):
            return self._update_buckets(plan, since)

        # ── Legacy update path ─────────────────────────────────────────
        # Step 2: Find changed files
        changed_files = self._get_changed_files(since)
        if not changed_files:
            console.print("[yellow]No changed source files.[/yellow]")
            return 0

        console.print(f"[bold]{len(changed_files)} file(s) changed since {since}[/bold]")
        for f in changed_files[:10]:
            console.print(f"  [dim]{f}[/dim]")
        if len(changed_files) > 10:
            console.print(f"  [dim]... +{len(changed_files) - 10} more[/dim]")

        # Step 3: Load file→page map
        file_map = load_file_map(self.repo_root)
        if not file_map:
            console.print("[yellow]No file-page map found. Run [bold]codewiki generate[/bold] first.[/yellow]")
            console.print("[dim]Falling back to full regeneration of affected pages...[/dim]")
            return self._fallback_update(changed_files)

        # Step 4: Find affected pages
        affected_slugs: set[str] = set()
        for f in changed_files:
            rel = str(f.relative_to(self.repo_root))
            if rel in file_map:
                affected_slugs.update(file_map[rel])

        if not affected_slugs:
            console.print("[yellow]Changed files don't belong to any doc page. Consider running [bold]codewiki generate[/bold] to replan.[/yellow]")
            return 0

        affected_pages = [p for p in (plan.pages if plan else []) if p.slug in affected_slugs]

        if not affected_pages and plan:
            console.print("[yellow]Could not find page details. Regenerating by slug...[/yellow]")
            return 0

        console.print(f"\n[bold]{len(affected_pages)} page(s) to update:[/bold]")
        for p in affected_pages:
            console.print(f"  [cyan]{p.title}[/cyan] ({p.page_type})")

        # Step 5: Regenerate affected pages
        updated = 0
        changed_rels = {str(f.relative_to(self.repo_root)) for f in changed_files}

        for page in affected_pages:
            try:
                doc_content = self._update_page(page, changed_rels)
                doc_path = self.output_dir / f"{page.slug}.mdx"
                doc_path.parent.mkdir(parents=True, exist_ok=True)
                doc_path.write_text(doc_content, encoding="utf-8")

                for src_file in page.source_files:
                    src_path = self.repo_root / src_file
                    if src_path.exists():
                        try:
                            content = src_path.read_text(encoding="utf-8", errors="replace")
                            self.manifest.update(src_file, file_hash(content), page.slug)
                        except Exception:
                            pass

                updated += 1
                console.print(f"  [green]✓[/green] {page.title}")

            except Exception as e:
                console.print(f"  [red]✗[/red] {page.title}: {e}")

        self.manifest.save()

        # Step 6: Rebuild nav
        from .site.mintlify_builder_v2 import build_mintlify_from_plan
        if plan:
            has_openapi = any(
                (self.repo_root / p).exists()
                for p in ["openapi.json", "openapi.yaml", "swagger.json", "swagger.yaml"]
            )
            build_mintlify_from_plan(self.repo_root, self.output_dir, self.cfg, plan, has_openapi)

        console.print(f"\n[bold green]✓ Updated {updated} page(s)[/bold green]")
        return updated

    def _update_page(self, page: DocPage, changed_files: set[str]) -> str:
        """Regenerate a page with context about what changed."""
        # Load previous doc
        doc_path = self.output_dir / f"{page.slug}.mdx"
        previous_doc = ""
        if doc_path.exists():
            previous_doc = doc_path.read_text(encoding="utf-8")

        # Build context for changed files
        changed_context_parts = []
        for src_file in page.source_files:
            if src_file not in changed_files:
                continue
            src_path = self.repo_root / src_file
            if not src_path.exists():
                changed_context_parts.append(f"### DELETED: `{src_file}`")
                continue
            try:
                content = src_path.read_text(encoding="utf-8", errors="replace")
                parsed = parse_file(src_path)
                part = f"### Changed: `{src_file}`\n"
                if parsed and parsed.symbols:
                    part += "Symbols: " + ", ".join(f"{s.kind}:{s.name}" for s in parsed.symbols[:15]) + "\n"
                part += f"```\n{content[:3000]}\n```\n"
                changed_context_parts.append(part)
            except Exception:
                continue

        # Build full context for all source files (for reference)
        full_context_parts = []
        for src_file in page.source_files:
            if src_file in changed_files:
                continue  # already in changed context
            src_path = self.repo_root / src_file
            if not src_path.exists():
                continue
            try:
                content = src_path.read_text(encoding="utf-8", errors="replace")
                parsed = parse_file(src_path)
                part = f"### `{src_file}`\n"
                if parsed and parsed.symbols:
                    part += "Symbols: " + ", ".join(f"{s.kind}:{s.name}" for s in parsed.symbols[:10]) + "\n"
                part += f"(first 500 chars)\n```\n{content[:500]}\n```\n"
                full_context_parts.append(part)
            except Exception:
                continue

        # Build sitemap context for cross-linking (needs plan)
        plan = load_plan(self.repo_root)
        sitemap_context = ""
        dependency_links = ""
        if plan:
            from .pipeline_v2 import PipelineV2
            pipeline = PipelineV2(self.repo_root, self.cfg)
            sitemap_context = pipeline._build_sitemap_context(plan, page.slug)
            scan = scan_repo(self.repo_root, self.cfg)
            dependency_links = pipeline._build_dependency_context(page, scan, plan)

        prompt = UPDATE_PAGE_V2.format(
            title=page.title,
            page_type=page.page_type,
            page_description=page.description,
            previous_doc=previous_doc[:6000],
            changed_files_context="\n".join(changed_context_parts)[:6000],
            full_source_context="\n".join(full_context_parts)[:4000],
            sitemap_context=sitemap_context,
            dependency_links=dependency_links,
        )

        console.print(f"  [dim]→ Calling LLM to update [cyan]{page.title}[/cyan]...[/dim]")
        return self.llm.complete(SYSTEM_V2, prompt)

    def _get_changed_files(self, since: str) -> list[Path]:
        try:
            import git
            repo = git.Repo(self.repo_root)
        except Exception:
            return self._manifest_stale()

        try:
            diff = repo.git.diff("--name-only", since, "HEAD")
        except Exception:
            try:
                diff = repo.git.diff("--name-only", "HEAD~1", "HEAD")
            except Exception:
                diff = repo.git.diff("--name-only", "--cached")

        extensions = supported_extensions()
        changed = []
        for line in diff.strip().splitlines():
            fp = self.repo_root / line.strip()
            if fp.exists() and fp.suffix.lower() in extensions:
                changed.append(fp)
        return changed

    def _manifest_stale(self) -> list[Path]:
        extensions = supported_extensions()
        stale = []
        for file_str in self.manifest.all_files():
            fp = self.repo_root / file_str
            if not fp.exists() or fp.suffix.lower() not in extensions:
                continue
            try:
                content = fp.read_text(encoding="utf-8", errors="replace")
                if self.manifest.is_stale(file_str, content):
                    stale.append(fp)
            except Exception:
                continue
        return stale

    def _update_buckets(self, plan: Any, since: str) -> int:
        """Bucket-aware update path for v2 plans.

        Uses the ledger to find stale buckets, then re-generates only those
        using the full BucketGenerationEngine (evidence assembly + validation).
        """
        from .planner_v2 import DocPlan as BucketDocPlan
        from .generator_v2 import BucketGenerationEngine

        # Step 1: Determine stale buckets via ledger + current file hashes
        stale_slugs = set(find_stale_buckets(plan, self.repo_root, output_dir=self.output_dir))

        # Also check git diff for any additional changed files
        changed_files = self._get_changed_files(since)
        if changed_files:
            file_map = load_file_map(self.repo_root)
            for f in changed_files:
                rel = str(f.relative_to(self.repo_root))
                for slug in file_map.get(rel, []):
                    stale_slugs.add(slug)

        if not stale_slugs:
            console.print("[green]✓ All pages are up-to-date.[/green]")
            return 0

        stale_buckets = [b for b in plan.buckets if b.slug in stale_slugs]
        console.print(Panel(
            f"[bold]{len(stale_buckets)} bucket(s) need updating[/bold]",
            border_style="yellow",
        ))
        for b in stale_buckets:
            console.print(f"  [yellow]→[/yellow] {b.title} ({b.bucket_type})")

        # Step 2: Re-scan (lightweight — no LLM)
        console.print("\n[dim]Re-scanning repo...[/dim]")
        scan = scan_repo(self.repo_root, self.cfg)

        # Step 3: Build a mini-plan containing only stale buckets
        # (generator uses full plan for sitemap/cross-refs, but only generates stale ones)
        from .planner_v2 import DocPlan as BucketPlan
        mini_plan = BucketPlan(
            buckets=stale_buckets,
            nav_structure=plan.nav_structure,
            skipped_files=plan.skipped_files,
        )
        # Swap in the full plan for cross-ref lookups
        mini_plan._full_plan = plan

        engine = BucketGenerationEngine(
            repo_root=self.repo_root,
            cfg=self.cfg,
            llm=self.llm,
            scan=scan,
            plan=plan,           # full plan for sitemap + cross-refs
            output_dir=self.output_dir,
        )
        # Override: only generate the stale buckets
        engine.plan = mini_plan

        gen_results = engine.generate_all(force=True)
        engine.update_manifest(gen_results)

        # Step 4: Update ledger + file map with results
        save_all(plan, None, gen_results, self.repo_root, self.output_dir)

        updated = sum(1 for r in gen_results if r.content and not r.error)

        # Step 5: Rebuild nav
        from .site.mintlify_builder_v2 import build_mintlify_from_plan
        has_openapi = any(
            (self.repo_root / p).exists()
            for p in ["openapi.json", "openapi.yaml", "swagger.json", "swagger.yaml"]
        )
        build_mintlify_from_plan(self.repo_root, self.output_dir, self.cfg, plan, has_openapi)

        console.print(f"\n[bold green]✓ Updated {updated} bucket page(s)[/bold green]")
        return updated

    def _fallback_update(self, changed_files: list[Path]) -> int:
        """Fallback: full regeneration."""
        from .pipeline_v2 import PipelineV2
        pipeline = PipelineV2(self.repo_root, self.cfg)
        return pipeline.run(force=False).get("pages_generated", 0)
