"""V2 Mintlify builder — builds site from AI-generated doc plan.

Generates:
- mint.json              (site config, navigation, theme, OpenAPI)
- logo/light.svg         (placeholder logo for light mode)
- logo/dark.svg          (placeholder logo for dark mode)
- favicon.svg            (placeholder favicon)
- docs/introduction.mdx  (landing page if overview page exists as index.md)

Replaces the old docusaurus_builder_v2.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..planner_v2 import DocPlan


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def build_mintlify_from_plan(
    repo_root: Path,
    output_dir: Path,
    cfg: dict[str, Any],
    plan: DocPlan,
    has_openapi: bool = False,
) -> None:
    """Build Mintlify site config from the AI's doc plan."""
    project_name = cfg.get("project_name") or repo_root.name
    repo_url = cfg.get("site", {}).get("repo_url", "")

    # Ensure docs dir exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Rename index.md → introduction.mdx (Mintlify convention)
    _rename_index_to_introduction(output_dir)

    # Rename all .md → .mdx
    _rename_md_to_mdx(output_dir)

    # Ensure a landing page always exists
    _ensure_landing_page(output_dir, project_name, plan)

    # Build navigation from plan
    navigation = _build_navigation_from_plan(plan, has_openapi, output_dir, repo_root)

    # Ensure the introduction page is the first entry
    intro_slug = _docs_relative_slug(output_dir, "introduction.mdx", repo_root)
    first_pages = navigation[0]["pages"] if navigation else []
    if intro_slug and intro_slug not in first_pages:
        if navigation:
            navigation[0]["pages"].insert(0, intro_slug)
        else:
            navigation.insert(0, {"group": "Overview", "pages": [intro_slug]})

    # Write config + static assets
    _write_mint_json(repo_root, project_name, repo_url, navigation, has_openapi, output_dir)
    _write_static_assets(repo_root)


# ─────────────────────────────────────────────────────────────────────────────
# Navigation builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_navigation_from_plan(
    plan: DocPlan, has_openapi: bool, output_dir: Path, repo_root: Path | None = None,
) -> list[dict]:
    """Convert DocPlan nav_structure to Mintlify navigation format.

    Mintlify navigation is an array of group objects:
    [
        {"group": "Getting Started", "pages": ["docs/introduction", "docs/setup"]},
        {"group": "Features", "pages": ["docs/feature-a", "docs/feature-b"]},
    ]

    Page paths are relative to the repo root (where mint.json lives).
    Only includes pages whose .mdx file actually exists on disk.
    """
    # Determine the docs dir prefix relative to the repo root
    docs_prefix = ""
    if repo_root and output_dir != repo_root:
        try:
            docs_prefix = str(output_dir.relative_to(repo_root)).replace("\\", "/")
        except ValueError:
            pass

    def _prefixed(page_id: str) -> str:
        """Prefix a slug with the docs directory path for Mintlify navigation."""
        return f"{docs_prefix}/{page_id}" if docs_prefix else page_id

    # Collect slugs with actual .mdx files
    existing_slugs: set[str] = set()
    for page in plan.pages:
        if page.page_type == "overview":
            if (output_dir / "introduction.mdx").exists():
                existing_slugs.add(page.slug)
        elif (output_dir / f"{page.slug}.mdx").exists():
            existing_slugs.add(page.slug)

    # Parse nav_structure into flat + nested sections
    nested_sections: dict[str, dict[str, list[str]]] = {}
    flat_sections: list[tuple[str, list[str]]] = []

    for section_name, slugs in plan.nav_structure.items():
        section_pages = []
        for slug in slugs:
            if slug not in existing_slugs:
                continue
            page_id = "introduction" if _is_overview(plan, slug) else slug
            section_pages.append(_prefixed(page_id))

        if not section_pages:
            continue

        if " > " in section_name:
            parent, child = section_name.split(" > ", 1)
            nested_sections.setdefault(parent, {})[child] = section_pages
        else:
            flat_sections.append((section_name, section_pages))

    nav_groups: list[dict] = []

    # Flat sections → groups
    for section_name, pages in flat_sections:
        nav_groups.append({"group": section_name, "pages": pages})

    # Nested sections → groups with nested groups
    for parent_name, children in sorted(nested_sections.items()):
        parent_pages: list = []
        for child_name, child_pages in children.items():
            if len(child_pages) == 1:
                parent_pages.append(child_pages[0])
            else:
                parent_pages.append({
                    "group": child_name,
                    "pages": child_pages,
                })
        if parent_pages:
            nav_groups.append({"group": parent_name, "pages": parent_pages})

    # Orphan pages (not in any section)
    in_nav: set[str] = set()
    for _section_name, slugs in plan.nav_structure.items():
        in_nav.update(slugs)

    orphan_pages = [
        _prefixed("introduction") if p.page_type == "overview" else _prefixed(p.slug)
        for p in plan.pages
        if p.slug not in in_nav and p.slug in existing_slugs
    ]
    if orphan_pages:
        nav_groups.append({"group": "Other", "pages": orphan_pages})

    # Native Mintlify API reference pages (generated from OpenAPI spec)
    if has_openapi:
        api_dir = output_dir / "api"
        if api_dir.exists():
            # Collect all .mdx files in docs/api/ that have openapi: frontmatter
            api_pages = sorted(
                f for f in api_dir.iterdir()
                if f.suffix == ".mdx" and "openapi:" in f.read_text(encoding="utf-8")[:200]
            )
            if api_pages:
                nav_groups.append({
                    "group": "API Reference",
                    "pages": [_prefixed(f"api/{f.stem}") for f in api_pages],
                })

    return nav_groups


# ─────────────────────────────────────────────────────────────────────────────
# Config writer
# ─────────────────────────────────────────────────────────────────────────────

def _write_mint_json(
    repo_root: Path,
    project_name: str,
    repo_url: str,
    navigation: list[dict],
    has_openapi: bool,
    output_dir: Path,
) -> None:
    """Generate mint.json — the single config file Mintlify needs."""
    docs_dir = str(output_dir.relative_to(repo_root))

    config: dict[str, Any] = {
        "$schema": "https://mintlify.com/schema.json",
        "name": project_name,
        "logo": {
            "dark": "/logo/dark.svg",
            "light": "/logo/light.svg",
        },
        "favicon": "/favicon.svg",
        "colors": {
            "primary": "#6366f1",
            "light": "#818cf8",
            "dark": "#4f46e5",
            "background": {
                "dark": "#0f0f0f",
                "light": "#ffffff",
            },
        },
        "mermaid": {},
        # Anchors appear as icon buttons at the bottom of the sidebar
        "anchors": [
            {
                "name": "API Reference",
                "icon": "square-terminal",
                "url": f"{docs_dir}/introduction",
            },
        ],
        "search": {
            "prompt": f"Search {project_name} docs...",
        },
        "navigation": navigation,
        "footerSocials": {},
        "feedback": {
            "thumbsRating": True,
            "suggestEdit": True,
        },
    }

    # Add GitHub topbar link + CTA button if repo URL is provided
    if repo_url:
        config["topbarLinks"] = [
            {"name": "GitHub", "url": repo_url},
        ]
        config["topbarCtaButton"] = {
            "name": "View on GitHub",
            "url": repo_url,
        }

    # OpenAPI spec reference
    if has_openapi:
        for spec_name in ["openapi.yaml", "openapi.json", "swagger.yaml", "swagger.json"]:
            if (repo_root / spec_name).exists():
                config["openapi"] = spec_name
                # Replace the generic anchor with a proper API Reference anchor
                config["anchors"] = [
                    {
                        "name": "API Reference",
                        "icon": "square-terminal",
                        "url": f"{docs_dir}/api",
                    },
                ]
                break

    (repo_root / "mint.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Static assets
# ─────────────────────────────────────────────────────────────────────────────

def _write_static_assets(repo_root: Path) -> None:
    """Create Mintlify static assets (logos + favicon)."""
    logo_dir = repo_root / "logo"
    logo_dir.mkdir(parents=True, exist_ok=True)

    # Light mode logo
    light_logo = """\
<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32" fill="none">
  <rect width="32" height="32" rx="8" fill="#6366f1"/>
  <path d="M9 10h14M9 16h10M9 22h14" stroke="white" stroke-width="2.5" stroke-linecap="round"/>
</svg>
"""
    (logo_dir / "light.svg").write_text(light_logo, encoding="utf-8")

    # Dark mode logo (same design, works on dark backgrounds)
    dark_logo = """\
<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32" fill="none">
  <rect width="32" height="32" rx="8" fill="#818cf8"/>
  <path d="M9 10h14M9 16h10M9 22h14" stroke="white" stroke-width="2.5" stroke-linecap="round"/>
</svg>
"""
    (logo_dir / "dark.svg").write_text(dark_logo, encoding="utf-8")

    # Favicon
    favicon_svg = """\
<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32" fill="none">
  <rect width="32" height="32" rx="8" fill="#6366f1"/>
  <path d="M9 10h14M9 16h10M9 22h14" stroke="white" stroke-width="2.5" stroke-linecap="round"/>
</svg>
"""
    (repo_root / "favicon.svg").write_text(favicon_svg, encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# File renaming
# ─────────────────────────────────────────────────────────────────────────────

def _rename_index_to_introduction(output_dir: Path) -> None:
    """Rename index.md → introduction.mdx for Mintlify convention."""
    index_md = output_dir / "index.md"
    intro_mdx = output_dir / "introduction.mdx"

    if index_md.exists() and not intro_mdx.exists():
        content = index_md.read_text(encoding="utf-8")
        intro_mdx.write_text(content, encoding="utf-8")
        index_md.unlink()

    # Also handle intro.md (from previous Docusaurus runs)
    intro_md = output_dir / "intro.md"
    if intro_md.exists() and not intro_mdx.exists():
        content = intro_md.read_text(encoding="utf-8")
        # Strip Docusaurus-specific frontmatter fields
        content = _strip_docusaurus_frontmatter(content)
        intro_mdx.write_text(content, encoding="utf-8")
        intro_md.unlink()


def _rename_md_to_mdx(output_dir: Path) -> None:
    """Rename all .md files to .mdx for Mintlify compatibility.

    Skips files that already have a .mdx counterpart.
    """
    for md_file in list(output_dir.rglob("*.md")):
        mdx_file = md_file.with_suffix(".mdx")
        if not mdx_file.exists():
            content = md_file.read_text(encoding="utf-8")
            # Strip Docusaurus-specific frontmatter fields
            content = _strip_docusaurus_frontmatter(content)
            mdx_file.write_text(content, encoding="utf-8")
        md_file.unlink()


def _strip_docusaurus_frontmatter(content: str) -> str:
    """Remove Docusaurus-specific frontmatter fields (slug, sidebar_position)."""
    if not content.startswith("---"):
        return content

    lines = content.split("\n")
    try:
        end_idx = lines.index("---", 1)
    except ValueError:
        return content

    # Filter out Docusaurus-specific fields
    docusaurus_fields = {"slug:", "sidebar_position:", "sidebar_label:"}
    fm_lines = [
        line for line in lines[1:end_idx]
        if not any(line.strip().startswith(f) for f in docusaurus_fields)
    ]

    # If frontmatter is now empty, remove it entirely
    if not any(line.strip() for line in fm_lines):
        return "\n".join(lines[end_idx + 1:]).lstrip("\n")

    return "---\n" + "\n".join(fm_lines) + "\n---\n" + "\n".join(lines[end_idx + 1:])


# ─────────────────────────────────────────────────────────────────────────────
# Landing page
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_landing_page(output_dir: Path, project_name: str, plan: DocPlan) -> None:
    """Ensure an introduction.mdx landing page exists.

    If introduction.mdx already exists and contains real AI-generated content,
    we leave it as-is. Otherwise we generate a polished Mintlify landing page
    with a <CardGroup> grid so the page index is never stale.
    """
    intro_mdx = output_dir / "introduction.mdx"

    # If the AI wrote real content (not our auto-generated page), keep it
    if intro_mdx.exists():
        existing = intro_mdx.read_text(encoding="utf-8")
        # Our auto-generated pages contain this exact marker
        if "_codewiki_autogen_" not in existing:
            return  # AI-generated content, don't overwrite

    # Pick a sensible Heroicon per bucket_type
    _ICON_BY_TYPE: dict[str, str] = {
        "system":      "server",
        "feature":     "bolt",
        "endpoint":    "globe-alt",
        "endpoint_ref":"globe-alt",
        "integration": "puzzle-piece",
        "database":    "database",
    }

    # Group existing pages by section for the CardGroup
    sections: dict[str, list[tuple[str, str, str]]] = {}  # section → [(title, slug, icon)]
    for page in plan.pages:
        if page.page_type == "overview":
            continue
        slug = page.slug
        if not (output_dir / f"{slug}.mdx").exists():
            continue
        section = getattr(page, "section", None) or "Docs"
        icon = _ICON_BY_TYPE.get(str(page.page_type), "book-open")
        sections.setdefault(section, []).append((page.title, slug, icon))

    # Build card blocks per section
    card_blocks: list[str] = []
    for section_name, pages in sections.items():
        card_items = []
        for title, slug, icon in pages:
            card_items.append(
                f'  <Card title="{title}" icon="{icon}" href="/{slug}">\n'
                f"    {title} documentation\n"
                f"  </Card>"
            )
        if card_items:
            card_blocks.append(
                f"### {section_name}\n\n"
                "<CardGroup cols={2}>\n"
                + "\n".join(card_items)
                + "\n</CardGroup>"
            )

    cards_section = (
        "\n\n".join(card_blocks)
        if card_blocks
        else "_Documentation is being generated..._"
    )

    content = f"""\
---
title: {project_name}
description: Auto-generated developer documentation
_codewiki_autogen_: true
---

# {project_name}

Welcome to the **{project_name}** developer documentation.

{cards_section}
"""
    intro_mdx.write_text(content, encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_overview(plan: DocPlan, slug: str) -> bool:
    """Check if a slug corresponds to an overview page."""
    page = next((p for p in plan.pages if p.slug == slug), None)
    return page is not None and page.page_type == "overview"


def _docs_relative_slug(output_dir: Path, filename: str, repo_root: Path) -> str | None:
    """Get the Mintlify page slug for a file in the docs directory."""
    filepath = output_dir / filename
    if not filepath.exists():
        return None
    # Mintlify page slugs are the file path relative to root, without extension
    rel = filepath.relative_to(repo_root)
    return str(rel.with_suffix("")).replace("\\", "/")
