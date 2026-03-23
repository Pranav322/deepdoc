"""V2 Smart Update — decides whether to replan or just regenerate stale buckets.

Phase 5 of the bucket-based doc pipeline.

Decision logic:
  1. Load the saved plan + ledger from persistence_v2
  2. Detect changed files (via git diff or manifest staleness)
  3. Classify the change set:
     - TRIVIAL: only content changed within existing files → regenerate stale buckets only
     - STRUCTURAL: new files added, files deleted, or >REPLAN_THRESHOLD% of files changed
       → trigger a full replan + regeneration
     - NEW_INTEGRATION: new integration signals detected in changed files
       → trigger a targeted replan (keep existing buckets, add new ones)
  4. Execute the appropriate strategy
  5. Update ledger and manifest

The replan threshold is configurable (default 20% of total files).
"""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .llm import LLMClient
from .manifest import Manifest, file_hash
from .parser import parse_file, supported_extensions
from .persistence_v2 import (
    load_plan, load_file_map, load_scan_cache,
    find_stale_buckets, ledger_summary, save_all,
)
from .planner_v2 import DocPlan, DocBucket

console = Console()

# What fraction of total files changed triggers a replan
REPLAN_THRESHOLD = 0.20
# New files added beyond this count also triggers replan
NEW_FILES_REPLAN_THRESHOLD = 5


# ─────────────────────────────────────────────────────────────────────────────
# Change classification
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ChangeSet:
    """Classification of what changed in the repo since last generation."""
    changed_files: list[str] = field(default_factory=list)   # modified existing files
    new_files: list[str] = field(default_factory=list)        # added files not in any bucket
    deleted_files: list[str] = field(default_factory=list)    # files that were deleted
    new_integration_signals: list[str] = field(default_factory=list)  # new integration hints
    stale_bucket_slugs: list[str] = field(default_factory=list)

    @property
    def strategy(self) -> str:
        """Determine the update strategy based on what changed."""
        if not self.changed_files and not self.new_files and not self.deleted_files:
            return "noop"
        if self.deleted_files or len(self.new_files) >= NEW_FILES_REPLAN_THRESHOLD:
            return "full_replan"
        if self.new_integration_signals:
            return "targeted_replan"
        return "incremental"

    @property
    def total_changes(self) -> int:
        return len(self.changed_files) + len(self.new_files) + len(self.deleted_files)


class SmartUpdater:
    """Orchestrates smart update/replan decisions for the v2 bucket pipeline."""

    def __init__(self, repo_root: Path, cfg: dict[str, Any]) -> None:
        self.repo_root = repo_root
        self.cfg = cfg
        self.output_dir = repo_root / cfg.get("output_dir", "docs")
        self.llm = LLMClient(cfg)
        self.manifest = Manifest(self.output_dir)

    def update(self, since: str = "HEAD~1", force_replan: bool = False) -> dict[str, Any]:
        """Run smart update. Returns stats dict."""
        stats: dict[str, Any] = {}

        # ── Step 1: Load saved state ───────────────────────────────────
        plan = load_plan(self.repo_root)
        if plan is None or not hasattr(plan, "buckets"):
            console.print(
                "[yellow]No v2 bucket plan found. Run [bold]codewiki generate[/bold] first.[/yellow]"
            )
            return {"status": "no_plan"}

        prev_summary = ledger_summary(self.repo_root)
        console.print(Panel(
            f"[bold]Smart Update[/bold]\n\n"
            f"Existing plan: {len(plan.buckets)} buckets "
            f"({prev_summary.get('total', 0)} generated, "
            f"{prev_summary.get('total_words', 0):,} words)\n"
            f"Bucket types: {prev_summary.get('by_bucket_type', {})}",
            border_style="blue",
        ))

        # ── Step 2: Classify changes ───────────────────────────────────
        change_set = self._classify_changes(plan, since)
        self._print_change_set(change_set)
        stats["changes"] = change_set.total_changes
        stats["strategy"] = change_set.strategy

        if force_replan:
            change_set_strategy = "full_replan"
        else:
            change_set_strategy = change_set.strategy

        # ── Step 3: Execute strategy ───────────────────────────────────
        if change_set_strategy == "noop":
            console.print("[green]✓ All documentation is up-to-date.[/green]")
            stats["pages_updated"] = 0
            return stats

        elif change_set_strategy == "full_replan":
            console.print(Panel(
                "[bold yellow]Strategy: Full Replan[/bold yellow]\n"
                f"Reason: {len(change_set.new_files)} new files, "
                f"{len(change_set.deleted_files)} deleted files",
                border_style="yellow",
            ))
            updated = self._full_replan_and_generate()
            stats["pages_updated"] = updated
            stats["replanned"] = True

        elif change_set_strategy == "targeted_replan":
            console.print(Panel(
                "[bold cyan]Strategy: Targeted Replan[/bold cyan]\n"
                f"Reason: {len(change_set.new_integration_signals)} new integration signal(s): "
                f"{', '.join(change_set.new_integration_signals[:5])}",
                border_style="cyan",
            ))
            updated = self._targeted_replan(plan, change_set)
            stats["pages_updated"] = updated
            stats["replanned"] = True

        else:  # incremental
            console.print(Panel(
                f"[bold green]Strategy: Incremental Update[/bold green]\n"
                f"{len(change_set.stale_bucket_slugs)} stale bucket(s) to regenerate",
                border_style="green",
            ))
            updated = self._incremental_update(plan, change_set)
            stats["pages_updated"] = updated
            stats["replanned"] = False

        # ── Step 4: Rebuild site nav ───────────────────────────────────
        updated_plan = load_plan(self.repo_root) or plan
        self._rebuild_nav(updated_plan)

        console.print(Panel.fit(
            f"[bold green]Smart Update Complete[/bold green]\n\n"
            f"  Strategy:      [cyan]{change_set_strategy}[/cyan]\n"
            f"  Pages updated: [cyan]{stats.get('pages_updated', 0)}[/cyan]\n"
            f"  Replanned:     [cyan]{'yes' if stats.get('replanned') else 'no'}[/cyan]",
            border_style="green",
        ))
        return stats

    # ── Strategy implementations ─────────────────────────────────────────

    def _full_replan_and_generate(self) -> int:
        """Run the full pipeline from scratch."""
        from .pipeline_v2 import PipelineV2
        pipeline = PipelineV2(self.repo_root, self.cfg)
        result = pipeline.run(force=True)
        return result.get("pages_generated", 0)

    def _targeted_replan(self, plan: DocPlan, change_set: ChangeSet) -> int:
        """Replan only to discover new buckets for new integrations/files,
        then merge with existing plan and regenerate stale buckets.
        """
        from .planner_v2 import scan_repo as bucket_scan_repo, plan_docs as bucket_plan_docs
        from .generator_v2 import BucketGenerationEngine
        from .planner_v2 import run_phase2_scans

        console.print("[dim]Re-scanning repo for targeted replan...[/dim]")
        scan = bucket_scan_repo(self.repo_root, self.cfg)
        run_phase2_scans(scan, self.cfg, self.llm)

        console.print("[dim]Running planner on new files only...[/dim]")
        # Build a mini-config scoped to new + changed files
        mini_cfg = dict(self.cfg)
        mini_cfg["include"] = change_set.new_files + change_set.changed_files

        try:
            new_plan = bucket_plan_docs(scan, mini_cfg, self.llm)
        except Exception as e:
            console.print(f"[yellow]⚠ Targeted replan failed ({e}) — falling back to incremental[/yellow]")
            return self._incremental_update(plan, change_set)

        # Merge: add new buckets, keep existing
        existing_slugs = {b.slug for b in plan.buckets}
        added = [b for b in new_plan.buckets if b.slug not in existing_slugs]

        if added:
            console.print(f"  [green]+{len(added)} new bucket(s) discovered:[/green]")
            for b in added:
                console.print(f"    [cyan]{b.title}[/cyan] ({b.bucket_type})")

        merged_buckets = plan.buckets + added
        merged_plan = DocPlan(
            buckets=merged_buckets,
            nav_structure=self._merge_nav(plan.nav_structure, new_plan.nav_structure),
            skipped_files=list(set(plan.skipped_files + new_plan.skipped_files)),
        )

        # Mark all stale + new buckets for regeneration
        stale_slugs = set(change_set.stale_bucket_slugs) | {b.slug for b in added}
        stale_buckets = [b for b in merged_plan.buckets if b.slug in stale_slugs]

        mini_plan = DocPlan(
            buckets=stale_buckets,
            nav_structure=merged_plan.nav_structure,
            skipped_files=merged_plan.skipped_files,
        )

        engine = BucketGenerationEngine(
            repo_root=self.repo_root,
            cfg=self.cfg,
            llm=self.llm,
            scan=scan,
            plan=merged_plan,
            output_dir=self.output_dir,
        )
        engine.plan = mini_plan
        gen_results = engine.generate_all(force=True)
        engine.update_manifest(gen_results)
        save_all(merged_plan, scan, gen_results, self.repo_root, self.output_dir)

        return sum(1 for r in gen_results if r.content and not r.error)

    def _incremental_update(self, plan: DocPlan, change_set: ChangeSet) -> int:
        """Regenerate only the stale buckets identified in the change set."""
        from .planner_v2 import scan_repo as bucket_scan_repo
        from .generator_v2 import BucketGenerationEngine
        from .planner_v2 import run_phase2_scans

        stale_slugs = set(change_set.stale_bucket_slugs)
        if not stale_slugs:
            console.print("[green]✓ No stale buckets.[/green]")
            return 0

        stale_buckets = [b for b in plan.buckets if b.slug in stale_slugs]

        console.print("[dim]Scanning repo...[/dim]")
        scan = bucket_scan_repo(self.repo_root, self.cfg)

        mini_plan = DocPlan(
            buckets=stale_buckets,
            nav_structure=plan.nav_structure,
            skipped_files=plan.skipped_files,
        )

        engine = BucketGenerationEngine(
            repo_root=self.repo_root,
            cfg=self.cfg,
            llm=self.llm,
            scan=scan,
            plan=plan,
            output_dir=self.output_dir,
        )
        engine.plan = mini_plan

        gen_results = engine.generate_all(force=True)
        engine.update_manifest(gen_results)
        save_all(plan, scan, gen_results, self.repo_root, self.output_dir)

        return sum(1 for r in gen_results if r.content and not r.error)

    # ── Change classification ────────────────────────────────────────────

    def _classify_changes(self, plan: DocPlan, since: str) -> ChangeSet:
        """Classify the current repo state against the saved plan.

        Sources of change info:
        1. Git diff (if available) for file add/delete/modify
        2. Ledger hash comparison for content changes
        3. Integration signal scan for new integrations
        """
        cs = ChangeSet()

        # Known files from the saved plan
        plan_files: set[str] = set()
        for b in plan.buckets:
            plan_files.update(b.owned_files)

        # Get changed files
        git_changes = self._get_git_changes(since)
        modified_git = {r for r, t in git_changes if t == "M"}
        added_git = {r for r, t in git_changes if t == "A"}
        deleted_git = {r for r, t in git_changes if t == "D"}

        # Modified: files in the plan that changed
        cs.changed_files = sorted(modified_git & plan_files)
        cs.deleted_files = sorted(deleted_git & plan_files)

        # New: added files not covered by any bucket
        cs.new_files = sorted(
            f for f in added_git
            if f not in plan_files and self._is_source_file(f)
        )

        # If no git, fall back to ledger hash comparison
        if not git_changes:
            cs.stale_bucket_slugs = find_stale_buckets(plan, self.repo_root)
            cs.changed_files = [
                f for b_slug in cs.stale_bucket_slugs
                for b in plan.buckets if b.slug == b_slug
                for f in b.owned_files
                if (self.repo_root / f).exists()
            ]
        else:
            cs.stale_bucket_slugs = self._map_files_to_stale_slugs(
                plan, set(cs.changed_files + cs.deleted_files)
            )

        # Check for new integration signals in changed/new files
        cs.new_integration_signals = self._scan_for_new_integrations(
            plan, cs.new_files + cs.changed_files
        )

        return cs

    def _get_git_changes(self, since: str) -> list[tuple[str, str]]:
        """Get list of (relative_path, change_type) from git diff."""
        try:
            import git
            repo = git.Repo(self.repo_root)
        except Exception:
            return []

        try:
            diff = repo.git.diff("--name-status", since, "HEAD")
        except Exception:
            try:
                diff = repo.git.diff("--name-status", "HEAD~1", "HEAD")
            except Exception:
                return []

        result = []
        for line in diff.strip().splitlines():
            parts = line.strip().split("\t", 1)
            if len(parts) == 2:
                change_type, filepath = parts[0][0], parts[1]  # M/A/D
                result.append((filepath, change_type))
        return result

    def _map_files_to_stale_slugs(
        self, plan: DocPlan, changed_files: set[str]
    ) -> list[str]:
        """Find bucket slugs that own any of the changed files."""
        stale: set[str] = set()
        for b in plan.buckets:
            if set(b.owned_files) & changed_files:
                stale.add(b.slug)
        # Also include buckets whose ledger is missing/failed
        stale.update(find_stale_buckets(plan, self.repo_root))
        return sorted(stale)

    def _scan_for_new_integrations(
        self, plan: DocPlan, files_to_check: list[str]
    ) -> list[str]:
        """Check changed/new files for integration signals not in the current plan."""
        if not files_to_check:
            return []

        known_integrations = {
            b.title.lower() for b in plan.buckets if b.bucket_type == "integration"
        }

        # Lightweight static scan — HTTP client patterns + SDK imports
        import re
        HTTP_PATTERNS = [
            r'requests\.(get|post|put|patch|delete)\s*\(',
            r'httpx\.(get|post|put)\s*\(',
            r'axios\.(get|post|put)\s*\(',
            r'fetch\s*\(',
            r'urllib\.request',
        ]
        SDK_PATTERNS = [
            r'import\s+(\w+)Client',
            r'from\s+(\w+)\s+import.*[Cc]lient',
            r'new\s+(\w+)Client\s*\(',
            r'(\w+)SDK\s*\(',
        ]

        new_signals: set[str] = set()
        for rel_path in files_to_check[:30]:
            src_path = self.repo_root / rel_path
            if not src_path.exists():
                continue
            try:
                content = src_path.read_text(encoding="utf-8", errors="replace")
                for pattern in HTTP_PATTERNS:
                    if re.search(pattern, content):
                        new_signals.add("http_calls")
                        break
                for pattern in SDK_PATTERNS:
                    m = re.search(pattern, content)
                    if m:
                        name = m.group(1).lower()
                        if name not in known_integrations and len(name) > 3:
                            new_signals.add(name)
            except Exception:
                continue

        return sorted(new_signals - {"http_calls"})

    def _is_source_file(self, path: str) -> bool:
        ext = Path(path).suffix.lower()
        return ext in supported_extensions()

    # ── Helpers ──────────────────────────────────────────────────────────

    def _merge_nav(
        self, existing: dict[str, list[str]], new: dict[str, list[str]]
    ) -> dict[str, list[str]]:
        """Merge two nav_structure dicts, appending new slugs without duplicates."""
        merged = {k: list(v) for k, v in existing.items()}
        for section, slugs in new.items():
            if section not in merged:
                merged[section] = []
            for slug in slugs:
                if slug not in merged[section]:
                    merged[section].append(slug)
        return merged

    def _rebuild_nav(self, plan: DocPlan) -> None:
        """Rebuild mkdocs.yml from the current plan."""
        try:
            from .site.mkdocs_builder_v2 import build_mkdocs_from_plan
            has_openapi = any(
                (self.repo_root / p).exists()
                for p in ["openapi.json", "openapi.yaml", "swagger.json", "swagger.yaml"]
            )
            build_mkdocs_from_plan(
                self.repo_root, self.output_dir, self.cfg, plan, has_openapi
            )
            console.print("[green]✓[/green] Site nav rebuilt")
        except Exception as e:
            console.print(f"[yellow]⚠ Nav rebuild failed: {e}[/yellow]")

    def _print_change_set(self, cs: ChangeSet) -> None:
        """Pretty-print the change classification."""
        t = Table(show_header=True, header_style="bold", box=None)
        t.add_column("Change type", style="cyan")
        t.add_column("Count", justify="right")
        t.add_column("Details")
        t.add_row("Modified files", str(len(cs.changed_files)),
                  ", ".join(cs.changed_files[:4]) + ("..." if len(cs.changed_files) > 4 else ""))
        t.add_row("New files", str(len(cs.new_files)),
                  ", ".join(cs.new_files[:4]) + ("..." if len(cs.new_files) > 4 else ""))
        t.add_row("Deleted files", str(len(cs.deleted_files)),
                  ", ".join(cs.deleted_files[:4]) + ("..." if len(cs.deleted_files) > 4 else ""))
        t.add_row("Stale buckets", str(len(cs.stale_bucket_slugs)),
                  ", ".join(cs.stale_bucket_slugs[:4]) + ("..." if len(cs.stale_bucket_slugs) > 4 else ""))
        if cs.new_integration_signals:
            t.add_row("New integrations", str(len(cs.new_integration_signals)),
                      ", ".join(cs.new_integration_signals))
        t.add_row("[bold]Strategy[/bold]", "", f"[bold]{cs.strategy}[/bold]")
        console.print(t)
