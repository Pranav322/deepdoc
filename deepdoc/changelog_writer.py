from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .persistence_v2 import (
    append_changelog_entry,
    atomic_write_text,
    load_changelog,
    load_plan,
    save_plan,
)

_STRATEGY_LABEL = {
    "incremental": "Incremental update",
    "targeted_replan": "Targeted replan",
    "full_replan": "Full replan",
    "full_generate": "Full generation",
}


def record_and_write(
    repo_root: Path,
    output_dir: Path,
    *,
    commit: str,
    commit_message: str,
    commit_date: str,
    strategy: str,
    pages_updated: list[str],
    files_changed: list[str],
    is_initial: bool = False,
) -> None:
    """Append one changelog entry and regenerate whats-changed.md."""
    entry = {
        "commit": commit[:8],
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "date": commit_date,
        "commit_message": commit_message,
        "strategy": strategy,
        "pages_updated": pages_updated,
        "files_changed": files_changed[:20],
        "is_initial": is_initial,
    }
    append_changelog_entry(repo_root, entry)
    write_whats_changed_page(repo_root, output_dir)


def write_whats_changed_page(repo_root: Path, output_dir: Path) -> None:
    """Write docs/whats-changed.md from .deepdoc/changelog.json."""
    entries = load_changelog(repo_root)
    content = _build_md(entries)
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(output_dir / "whats-changed.md", content)
    _ensure_in_nav(repo_root)


def _build_md(entries: list[dict]) -> str:
    lines = [
        "---",
        'title: "What\'s Changed"',
        'description: "A commit-by-commit log of every documentation update — which pages changed, which source files triggered the change, and how the update was handled."',
        "---",
        "",
        "# What's Changed",
        "",
        "Every time you run `deepdoc generate` or `deepdoc update`, this page is regenerated automatically.",
        "Each entry shows the commit that triggered the run, the strategy DeepDoc chose, the pages that were",
        "updated, and the source files that caused the change.",
        "",
    ]

    if not entries:
        lines.append(
            "> [!NOTE]\n> No changelog entries yet. Run `deepdoc generate` to create the first entry."
        )
        return "\n".join(lines)

    for entry in entries:
        date = entry.get("date", "")
        msg = entry.get("commit_message", "update")
        sha = entry.get("commit", "")
        pages = entry.get("pages_updated", [])
        files = entry.get("files_changed", [])
        strategy = entry.get("strategy", "")
        is_initial = entry.get("is_initial", False)
        strategy_label = _STRATEGY_LABEL.get(strategy, strategy)

        title = f"{date} — {msg[:72]} ({sha})"
        lines.append(f"<details>")
        lines.append(f"<summary>{title}</summary>")
        lines.append("")

        # Commit metadata row
        lines.append("| | |")
        lines.append("|---|---|")
        lines.append(f"| **Commit** | `{sha}` |")
        lines.append(f"| **Date** | {date} |")
        lines.append(f"| **Strategy** | {strategy_label} |")
        lines.append(f"| **Message** | {msg} |")
        lines.append("")

        if is_initial:
            lines.append(
                f"**Initial generation** — {len(pages)} page(s) created from scratch."
            )
            if pages:
                lines.append("")
                lines.append("**Pages generated:**")
                lines.append("")
                for s in pages:
                    lines.append(f"- [{_slug_to_title(s)}](/{s})")
        else:
            # Pages updated
            if pages:
                lines.append(f"**{len(pages)} page(s) updated:**")
                lines.append("")
                for s in pages:
                    lines.append(f"- [{_slug_to_title(s)}](/{s})")
            else:
                lines.append(
                    "> [!INFO]\n> No pages were regenerated — only metadata or chatbot corpora were refreshed."
                )

            # Source files that changed
            if files:
                lines.append("")
                lines.append(f"**Source files that triggered this update ({len(files)}):**")
                lines.append("")
                for f in files[:20]:
                    lines.append(f"- `{f}`")
                if len(files) > 20:
                    lines.append(f"- *...and {len(files) - 20} more*")

            # What the strategy means
            lines.append("")
            if strategy == "incremental":
                lines.append(
                    "> **Incremental update** — only the pages whose source files changed were regenerated. All other pages were left untouched."
                )
            elif strategy == "targeted_replan":
                lines.append(
                    "> **Targeted replan** — new or deleted files were detected. DeepDoc re-evaluated which buckets own those files, updated the plan, and regenerated affected pages."
                )
            elif strategy == "full_replan":
                lines.append(
                    "> **Full replan** — the engine schema changed or a force-replan was requested. All buckets were re-planned and regenerated."
                )

        lines.append("")
        lines.append("</details>")

    return "\n".join(lines)


def _slug_to_title(slug: str) -> str:
    return slug.replace("-", " ").title()


def _ensure_in_nav(repo_root: Path) -> None:
    """Add whats-changed to Start Here section of the saved plan if not already there."""
    plan = load_plan(repo_root)
    if plan is None or not hasattr(plan, "nav_structure"):
        return
    section = plan.nav_structure.setdefault("Start Here", [])
    if "whats-changed" not in section:
        section.append("whats-changed")
    save_plan(plan, repo_root)
