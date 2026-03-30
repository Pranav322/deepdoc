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

from .generator_v2 import summarize_generation_results
from .llm import LLMClient
from .manifest import Manifest, file_hash
from .parser import parse_file, supported_extensions
from .persistence_v2 import (
    load_plan,
    load_file_map,
    load_scan_cache,
    find_stale_buckets,
    ledger_summary,
    save_all,
    save_sync_state,
    load_sync_state,
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

    changed_files: list[str] = field(default_factory=list)  # modified existing files
    new_files: list[str] = field(default_factory=list)  # added files not in any bucket
    deleted_files: list[str] = field(default_factory=list)  # files that were deleted
    new_integration_signals: list[str] = field(
        default_factory=list
    )  # new integration hints
    stale_bucket_slugs: list[str] = field(default_factory=list)
    orphaned_bucket_slugs: list[str] = field(
        default_factory=list
    )  # buckets with ALL files gone
    total_plan_files: int = 0  # total files tracked in the plan (for threshold calc)

    @property
    def strategy(self) -> str:
        """Determine the update strategy based on what changed."""
        if (
            not self.changed_files
            and not self.new_files
            and not self.deleted_files
            and not self.orphaned_bucket_slugs
        ):
            return "noop"
        if self.deleted_files or self.orphaned_bucket_slugs:
            return "full_replan"
        if len(self.new_files) >= NEW_FILES_REPLAN_THRESHOLD:
            return "full_replan"
        # If total changes exceed the percentage threshold, replan
        if (
            self.total_plan_files > 0
            and self.total_changes / self.total_plan_files > REPLAN_THRESHOLD
        ):
            return "full_replan"
        if self.new_files or self.new_integration_signals:
            return "targeted_replan"
        return "incremental"

    @property
    def total_changes(self) -> int:
        return len(self.changed_files) + len(self.new_files) + len(self.deleted_files)


@dataclass
class UpdateRunResult:
    """Outcome of executing one smart-update strategy."""

    strategy: str
    pages_updated: int = 0
    pages_failed: int = 0
    pages_skipped: int = 0
    replanned: bool = False

    @property
    def status(self) -> str:
        if self.strategy == "noop" or self.pages_failed == 0:
            return "success"
        return "partial" if self.pages_updated > 0 else "failed"


class SmartUpdater:
    """Orchestrates smart update/replan decisions for the v2 bucket pipeline."""

    def __init__(self, repo_root: Path, cfg: dict[str, Any]) -> None:
        self.repo_root = repo_root
        self.cfg = cfg
        self.output_dir = repo_root / cfg.get("output_dir", "docs")
        self.llm = LLMClient(cfg)
        self.manifest = Manifest(self.output_dir)

    def update(
        self, since: str = "HEAD~1", force_replan: bool = False
    ) -> dict[str, Any]:
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
        console.print(
            Panel(
                f"[bold]Smart Update[/bold]\n\n"
                f"Existing plan: {len(plan.buckets)} buckets "
                f"({prev_summary.get('total', 0)} generated, "
                f"{prev_summary.get('total_words', 0):,} words)\n"
                f"Bucket types: {prev_summary.get('by_bucket_type', {})}",
                border_style="blue",
            )
        )

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
        run_result = UpdateRunResult(strategy=change_set_strategy)

        if change_set_strategy == "noop":
            console.print("[green]✓ All documentation is up-to-date.[/green]")
            stats["strategy"] = "noop"
            stats["pages_updated"] = 0
            stats["pages_failed"] = 0
            stats["pages_skipped"] = 0
            stats["replanned"] = False
            stats["status"] = "success"
            # Noop: persist sync state — refresh synced_at if HEAD hasn't
            # changed, or advance baseline if HEAD moved but nothing is stale
            # (docs confirmed in sync).
            self._save_update_sync_state(
                strategy="noop",
                pages_updated=0,
                pages_failed=0,
                plan=plan,
            )
            return stats

        elif change_set_strategy == "full_replan":
            console.print(
                Panel(
                    "[bold yellow]Strategy: Full Replan[/bold yellow]\n"
                    f"Reason: {len(change_set.new_files)} new files, "
                    f"{len(change_set.deleted_files)} deleted files",
                    border_style="yellow",
                )
            )
            run_result = self._full_replan_and_generate()

        elif change_set_strategy == "targeted_replan":
            reasons: list[str] = []
            if change_set.new_files:
                reasons.append(f"{len(change_set.new_files)} new file(s)")
            if change_set.new_integration_signals:
                reasons.append(
                    f"{len(change_set.new_integration_signals)} new integration signal(s): "
                    f"{', '.join(change_set.new_integration_signals[:5])}"
                )
            console.print(
                Panel(
                    "[bold cyan]Strategy: Targeted Replan[/bold cyan]\n"
                    f"Reason: {'; '.join(reasons) or 'structural change detected'}",
                    border_style="cyan",
                )
            )
            run_result = self._targeted_replan(plan, change_set)

        else:  # incremental
            console.print(
                Panel(
                    f"[bold green]Strategy: Incremental Update[/bold green]\n"
                    f"{len(change_set.stale_bucket_slugs)} stale bucket(s) to regenerate",
                    border_style="green",
                )
            )
            run_result = self._incremental_update(plan, change_set)

        executed_strategy = run_result.strategy
        stats["strategy"] = executed_strategy
        stats["pages_updated"] = run_result.pages_updated
        stats["pages_failed"] = run_result.pages_failed
        stats["pages_skipped"] = run_result.pages_skipped
        stats["replanned"] = run_result.replanned
        stats["status"] = run_result.status

        # ── Step 4: Rebuild site nav ───────────────────────────────────
        if executed_strategy not in {"noop", "full_replan"}:
            updated_plan = load_plan(self.repo_root) or plan
            self._rebuild_nav(updated_plan)

        # ── Step 5: Persist sync baseline ──────────────────────────────
        # full_replan already saves via pipeline_v2.py, so skip it here
        if executed_strategy != "full_replan":
            self._save_update_sync_state(
                strategy=executed_strategy,
                pages_updated=run_result.pages_updated,
                pages_failed=run_result.pages_failed,
                plan=plan,
            )

        console.print(
            Panel.fit(
                f"[bold green]Smart Update Complete[/bold green]\n\n"
                f"  Strategy:      [cyan]{executed_strategy}[/cyan]\n"
                f"  Pages updated: [cyan]{stats.get('pages_updated', 0)}[/cyan]\n"
                f"  Pages failed:  [cyan]{stats.get('pages_failed', 0)}[/cyan]\n"
                f"  Replanned:     [cyan]{'yes' if stats.get('replanned') else 'no'}[/cyan]",
                border_style="green",
            )
        )
        return stats

    # ── Strategy implementations ─────────────────────────────────────────

    def _full_replan_and_generate(self) -> UpdateRunResult:
        """Run the full pipeline from scratch."""
        from .pipeline_v2 import PipelineV2

        pipeline = PipelineV2(self.repo_root, self.cfg)
        result = pipeline.run(force=True, reconcile=True)
        return UpdateRunResult(
            strategy="full_replan",
            pages_updated=result.get("pages_generated", 0),
            pages_failed=result.get("pages_failed", 0),
            pages_skipped=result.get("pages_skipped", 0),
            replanned=True,
        )

    def _targeted_replan(self, plan: DocPlan, change_set: ChangeSet) -> UpdateRunResult:
        """Replan only to discover new buckets for new integrations/files,
        then merge with existing plan and regenerate stale buckets.
        """
        from .planner_v2 import (
            scan_repo as bucket_scan_repo,
            plan_docs as bucket_plan_docs,
        )
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
            console.print(
                f"[yellow]⚠ Targeted replan failed ({e}) — falling back to incremental[/yellow]"
            )
            return self._incremental_update(plan, change_set)

        # Merge: add new buckets, keep existing
        existing_slugs = {b.slug for b in plan.buckets}
        added = [b for b in new_plan.buckets if b.slug not in existing_slugs]

        if change_set.new_files and not added:
            console.print(
                "[yellow]⚠ New files did not map cleanly to new buckets — escalating to full replan[/yellow]"
            )
            return self._full_replan_and_generate()

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

        summary = summarize_generation_results(gen_results)
        return UpdateRunResult(
            strategy="targeted_replan",
            pages_updated=summary.succeeded,
            pages_failed=summary.failed,
            pages_skipped=summary.skipped,
            replanned=True,
        )

    def _incremental_update(
        self, plan: DocPlan, change_set: ChangeSet
    ) -> UpdateRunResult:
        """Regenerate only the stale buckets identified in the change set."""
        from .planner_v2 import scan_repo as bucket_scan_repo
        from .generator_v2 import BucketGenerationEngine
        from .planner_v2 import run_phase2_scans

        stale_slugs = set(change_set.stale_bucket_slugs)
        if not stale_slugs:
            console.print("[green]✓ No stale buckets.[/green]")
            return UpdateRunResult(strategy="incremental")

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

        summary = summarize_generation_results(gen_results)
        return UpdateRunResult(
            strategy="incremental",
            pages_updated=summary.succeeded,
            pages_failed=summary.failed,
            pages_skipped=summary.skipped,
        )

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
        cs.total_plan_files = len(plan_files)

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
            f for f in added_git if f not in plan_files and self._is_source_file(f)
        )

        # If no git, fall back to ledger hash comparison
        if not git_changes:
            cs.stale_bucket_slugs = find_stale_buckets(
                plan, self.repo_root, output_dir=self.output_dir
            )
            cs.changed_files = [
                f
                for b_slug in cs.stale_bucket_slugs
                for b in plan.buckets
                if b.slug == b_slug
                for f in b.owned_files
                if (self.repo_root / f).exists()
            ]
            cs.new_files = self._discover_new_source_files(plan_files)
        else:
            cs.stale_bucket_slugs = self._map_files_to_stale_slugs(
                plan, set(cs.changed_files + cs.deleted_files)
            )

        # Check for new integration signals in changed/new files
        cs.new_integration_signals = self._scan_for_new_integrations(
            plan, cs.new_files + cs.changed_files
        )

        # Detect orphaned buckets: buckets where ALL owned files are gone.
        # These need a replan — their docs describe code that no longer exists.
        for b in plan.buckets:
            if not b.owned_files:
                continue
            all_gone = all(not (self.repo_root / f).exists() for f in b.owned_files)
            if all_gone:
                cs.orphaned_bucket_slugs.append(b.slug)

        return cs

    def _get_git_changes(self, since: str) -> list[tuple[str, str]]:
        """Get list of (relative_path, change_type) from git diff.

        Handles M (modified), A (added), D (deleted), and R (renamed).
        Renames are decomposed into D (old path) + A (new path).

        Also includes staged + unstaged working-tree changes so that
        ``codewiki update`` syncs docs to the repo as it exists right now,
        not just as of the last commit.
        """
        try:
            import git

            repo = git.Repo(self.repo_root)
        except Exception:
            return []

        # ── Committed changes: since..HEAD ────────────────────────────
        try:
            diff = repo.git.diff("--name-status", since, "HEAD")
        except Exception:
            try:
                diff = repo.git.diff("--name-status", "HEAD~1", "HEAD")
            except Exception:
                return []

        status_by_path: dict[str, str] = {}

        def merge_change(path: str, status: str, *, overwrite: bool) -> None:
            if not path:
                return
            if overwrite or path not in status_by_path:
                status_by_path[path] = status

        for line in diff.strip().splitlines():
            if not line.strip():
                continue
            parts = line.strip().split("\t")
            if len(parts) < 2:
                continue
            status_code = parts[0][0]  # First char: M/A/D/R/C
            if status_code == "R" and len(parts) >= 3:
                # Rename: treat as delete old + add new
                old_path, new_path = parts[1], parts[2]
                merge_change(old_path, "D", overwrite=True)
                merge_change(new_path, "A", overwrite=True)
            else:
                merge_change(parts[-1], status_code, overwrite=True)

        # ── Working-tree changes: staged + unstaged ───────────────────
        try:
            wt_diff = repo.git.diff("--name-status", "HEAD")
            for line in wt_diff.strip().splitlines():
                if not line.strip():
                    continue
                parts = line.strip().split("\t")
                if len(parts) < 2:
                    continue
                status_code = parts[0][0]
                if status_code == "R" and len(parts) >= 3:
                    merge_change(parts[1], "D", overwrite=False)
                    merge_change(parts[2], "A", overwrite=False)
                else:
                    merge_change(parts[-1], status_code, overwrite=False)
        except Exception:
            pass  # Working tree check is best-effort

        # ── Untracked source files ─────────────────────────────────────
        try:
            for rel_path in repo.untracked_files:
                merge_change(rel_path, "A", overwrite=False)
        except Exception:
            pass

        return sorted(status_by_path.items())

    def _discover_new_source_files(self, plan_files: set[str]) -> list[str]:
        """Find source files on disk that are not yet covered by the saved plan."""

        ignored_dirs = {
            ".git",
            ".codewiki",
            ".pytest_cache",
            ".venv",
            ".venv-help",
            "__pycache__",
            "node_modules",
            "build",
        }
        discovered: list[str] = []

        for path in self.repo_root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in ignored_dirs for part in path.parts):
                continue
            try:
                path.relative_to(self.output_dir)
                continue
            except ValueError:
                pass

            rel_path = path.relative_to(self.repo_root).as_posix()
            if rel_path in plan_files:
                continue
            if self._is_source_file(rel_path):
                discovered.append(rel_path)

        return sorted(set(discovered))

    def _map_files_to_stale_slugs(
        self, plan: DocPlan, changed_files: set[str]
    ) -> list[str]:
        """Find bucket slugs that own any of the changed files."""
        stale: set[str] = set()
        for b in plan.buckets:
            if set(b.owned_files) & changed_files:
                stale.add(b.slug)
        # Also include buckets whose ledger is missing/failed
        stale.update(
            find_stale_buckets(plan, self.repo_root, output_dir=self.output_dir)
        )
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
            r"requests\.(get|post|put|patch|delete)\s*\(",
            r"httpx\.(get|post|put)\s*\(",
            r"axios\.(get|post|put)\s*\(",
            r"fetch\s*\(",
            r"urllib\.request",
        ]
        SDK_PATTERNS = [
            r"import\s+(\w+)Client",
            r"from\s+(\w+)\s+import.*[Cc]lient",
            r"new\s+(\w+)Client\s*\(",
            r"(\w+)SDK\s*\(",
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

    # ── Sync state ─────────────────────────────────────────────────────

    def _save_update_sync_state(
        self,
        strategy: str,
        pages_updated: int,
        pages_failed: int,
        plan: DocPlan,
    ) -> None:
        """Persist commit-baseline after an update run.

        Advancement semantics:
        - noop: refresh synced_at. Advance last_synced_commit only if HEAD
          changed (docs confirmed in sync because nothing is stale).
        - Full success (pages_failed == 0, pages_updated > 0): advance baseline.
        - Partial success (some pages failed): do NOT advance baseline; write
          last_attempted_commit only. This prevents skipping still-stale changes.
        - Total failure (pages_updated == 0 and not noop): do NOT advance.
        """
        try:
            import git as _git

            repo = _git.Repo(self.repo_root)
            head_sha = repo.head.commit.hexsha
        except Exception:
            return  # Not a git repo — skip

        plan_version = "v2_buckets" if hasattr(plan, "buckets") else "v1_legacy"

        if strategy == "noop":
            # Noop: docs are confirmed in sync. Check if HEAD moved.
            existing = load_sync_state(self.repo_root)
            if existing and existing.get("last_synced_commit") == head_sha:
                # HEAD hasn't changed — just refresh synced_at
                save_sync_state(
                    self.repo_root,
                    commit_sha=head_sha,
                    status="success",
                    generator_version=plan_version,
                    advance_baseline=True,  # refreshes synced_at
                )
            else:
                # HEAD moved but nothing is stale — docs are in sync
                save_sync_state(
                    self.repo_root,
                    commit_sha=head_sha,
                    status="success",
                    generator_version=plan_version,
                    advance_baseline=True,
                )
            return

        if pages_failed <= 0 and pages_updated > 0:
            # Full success — advance baseline
            save_sync_state(
                self.repo_root,
                commit_sha=head_sha,
                status="success",
                generator_version=plan_version,
                advance_baseline=True,
            )
        else:
            # Partial or total failure — record attempt but don't advance
            status = "partial" if pages_updated > 0 else "failed"
            save_sync_state(
                self.repo_root,
                commit_sha=head_sha,
                status=status,
                generator_version=plan_version,
                advance_baseline=False,
            )

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
        """Rebuild Mintlify config from the current plan."""
        try:
            from .site.mintlify_builder_v2 import build_mintlify_from_plan

            has_openapi = any(
                (self.repo_root / p).exists()
                for p in [
                    "openapi.json",
                    "openapi.yaml",
                    "swagger.json",
                    "swagger.yaml",
                ]
            )
            build_mintlify_from_plan(
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
        t.add_row(
            "Modified files",
            str(len(cs.changed_files)),
            ", ".join(cs.changed_files[:4])
            + ("..." if len(cs.changed_files) > 4 else ""),
        )
        t.add_row(
            "New files",
            str(len(cs.new_files)),
            ", ".join(cs.new_files[:4]) + ("..." if len(cs.new_files) > 4 else ""),
        )
        t.add_row(
            "Deleted files",
            str(len(cs.deleted_files)),
            ", ".join(cs.deleted_files[:4])
            + ("..." if len(cs.deleted_files) > 4 else ""),
        )
        t.add_row(
            "Stale buckets",
            str(len(cs.stale_bucket_slugs)),
            ", ".join(cs.stale_bucket_slugs[:4])
            + ("..." if len(cs.stale_bucket_slugs) > 4 else ""),
        )
        if cs.orphaned_bucket_slugs:
            t.add_row(
                "[red]Orphaned buckets[/red]",
                str(len(cs.orphaned_bucket_slugs)),
                ", ".join(cs.orphaned_bucket_slugs[:4])
                + ("..." if len(cs.orphaned_bucket_slugs) > 4 else ""),
            )
        if cs.new_integration_signals:
            t.add_row(
                "New integrations",
                str(len(cs.new_integration_signals)),
                ", ".join(cs.new_integration_signals),
            )
        t.add_row("[bold]Strategy[/bold]", "", f"[bold]{cs.strategy}[/bold]")
        console.print(t)
