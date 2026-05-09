from __future__ import annotations

from pathlib import Path

from .persistence_v2 import append_changelog_entry, load_changelog, load_plan, save_plan


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
    """Append one changelog entry and regenerate whats-changed.mdx."""
    entry = {
        "commit": commit[:8],
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
    """Write docs/whats-changed.mdx from .deepdoc/changelog.json."""
    entries = load_changelog(repo_root)
    mdx = _build_mdx(entries)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "whats-changed.mdx").write_text(mdx, encoding="utf-8")
    _ensure_in_nav(repo_root)


def _build_mdx(entries: list[dict]) -> str:
    lines = [
        "---",
        'title: "What\'s Changed"',
        'description: "Documentation changes per commit"',
        "---",
        "",
        "# What's Changed",
        "",
    ]

    if not entries:
        lines.append("No changes recorded yet — this is the initial documentation.")
        return "\n".join(lines)

    lines.append("<Accordions>")
    for entry in entries:
        date = entry.get("date", "")
        msg = entry.get("commit_message", "update")[:80]
        sha = entry.get("commit", "")
        pages = entry.get("pages_updated", [])
        files = entry.get("files_changed", [])
        is_initial = entry.get("is_initial", False)

        title = f"{date} — {msg} ({sha})"
        lines.append(f'<Accordion title="{title}">')
        lines.append("")

        if is_initial:
            lines.append(f"**{len(pages)} pages generated** — initial documentation run.")
        else:
            if pages:
                page_links = ", ".join(f"[{_slug_to_title(s)}](/{s})" for s in pages)
                lines.append(f"**{len(pages)} page(s) updated:** {page_links}")
            else:
                lines.append("No pages regenerated.")

        if files and not is_initial:
            file_list = ", ".join(f"`{f}`" for f in files[:10])
            if len(files) > 10:
                file_list += f" +{len(files) - 10} more"
            lines.append("")
            lines.append(f"**Files changed:** {file_list}")

        lines.append("")
        lines.append("</Accordion>")

    lines.append("</Accordions>")
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
