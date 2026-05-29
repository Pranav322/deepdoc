"""Build the generated MkDocs Material site from the current doc plan.

This is the production site builder. It writes a ``mkdocs.yml`` (Material theme,
pymdownx Blocks + Mermaid superfence), a brand stylesheet, a landing page, and an
optional Swagger UI page — all driven off the saved :class:`DocPlan`.

Generated documentation pages themselves are plain CommonMark ``.md`` files that
the LLM already produced; this module only assembles the site scaffold and nav
around them. There is no JSX/MDX compile step, so a page can never fail to build.
"""

from __future__ import annotations

import json
import os
import shutil
from collections import OrderedDict
from pathlib import Path
from typing import Any

import yaml

from ...v2_models import DocPlan
from .mdx_utils import _ensure_md_frontmatter

# Default brand palette (carried over from the previous scaffold default).
_DEFAULT_PRIMARY = "#EB3E25"
_DEFAULT_LIGHT = "#EF624E"
_DEFAULT_DARK = "#C1331F"

# ─────────────────────────────────────────────────────────────────────────────
# Nav ordering + legacy filename migration (formerly in the Fumadocs engine)
# ─────────────────────────────────────────────────────────────────────────────

_SECTION_PRIORITY: tuple[str, ...] = (
    "Start Here",
    "System",
    "Architecture",
    "Features",
    "Workflows",
    "Integrations",
    "API",
    "API Reference",
    "Database",
    "Operations",
    "Research Context",
)

_START_HERE_SLUG_ORDER: tuple[str, ...] = (
    "start-here",
    "local-development-setup",
    "domain-glossary",
    "debug-runbook",
    "whats-changed",
)


def _section_rank(name: str) -> int:
    """Stable sort key for nav sections — earlier = closer to a newcomer's first read."""
    top = name.split(" > ", 1)[0].strip()
    for i, known in enumerate(_SECTION_PRIORITY):
        if top.lower() == known.lower():
            return i
    return len(_SECTION_PRIORITY) + abs(hash(top)) % 1000


def _start_here_page_rank(slug: str) -> int:
    for i, known in enumerate(_START_HERE_SLUG_ORDER):
        if slug == known:
            return i
    return len(_START_HERE_SLUG_ORDER)


def _strip_docusaurus_frontmatter(content: str) -> str:
    """Remove legacy frontmatter fields that should not survive the migration."""
    if not content.startswith("---"):
        return content

    lines = content.split("\n")
    try:
        end_idx = lines.index("---", 1)
    except ValueError:
        return content

    docusaurus_fields = {"slug:", "sidebar_position:", "sidebar_label:"}
    fm_lines = [
        line
        for line in lines[1:end_idx]
        if not any(line.strip().startswith(field) for field in docusaurus_fields)
    ]

    if not any(line.strip() for line in fm_lines):
        return "\n".join(lines[end_idx + 1 :]).lstrip("\n")

    return "---\n" + "\n".join(fm_lines) + "\n---\n" + "\n".join(lines[end_idx + 1 :])


def _rename_legacy_intro_to_index(output_dir: Path) -> None:
    """Migrate legacy overview filenames to docs/index.md."""
    for legacy_name in ("introduction.md", "intro.md", "introduction.mdx", "intro.mdx"):
        legacy_path = output_dir / legacy_name
        index_md = output_dir / "index.md"
        if legacy_path.exists() and not index_md.exists():
            content = legacy_path.read_text(encoding="utf-8")
            content = _strip_docusaurus_frontmatter(content)
            index_md.write_text(content, encoding="utf-8")
        if legacy_path.exists() and legacy_path.name != "index.md":
            legacy_path.unlink()


def build_mkdocs_from_plan(
    repo_root: Path,
    output_dir: Path,
    cfg: dict[str, Any],
    plan: DocPlan,
    has_openapi: bool = False,
) -> None:
    """Build the generated MkDocs Material site from the current doc plan."""
    project_name = cfg.get("project_name") or repo_root.name
    repo_url = cfg.get("site", {}).get("repo_url", "")

    output_dir.mkdir(parents=True, exist_ok=True)
    site_dir = repo_root / "site"
    site_dir.mkdir(parents=True, exist_ok=True)

    _rename_legacy_intro_to_index(output_dir)
    _ensure_md_frontmatter(output_dir)
    _ensure_landing_page(output_dir, project_name, plan)

    if has_openapi:
        _stage_openapi_page(repo_root, output_dir)

    nav = _build_nav_from_plan(plan, output_dir, project_name, has_openapi)

    # docs_dir is given relative to the site/ directory (where mkdocs.yml lives).
    docs_dir_relative = os.path.relpath(output_dir, site_dir).replace("\\", "/")

    _write_mkdocs_scaffold(
        site_dir,
        project_name,
        repo_url,
        docs_dir_relative,
        nav,
        has_openapi,
        cfg,
    )
    _cleanup_fumadocs_artifacts(site_dir)


# ─────────────────────────────────────────────────────────────────────────────
# Nav
# ─────────────────────────────────────────────────────────────────────────────


def _build_nav_from_plan(
    plan: DocPlan,
    output_dir: Path,
    project_name: str,
    has_openapi: bool,
) -> list[Any]:
    """Build a MkDocs ``nav:`` list from the saved nav structure.

    Output shape (list of str | {title: path} | {title: [items]}) matches MkDocs'
    nav schema. Ordering reuses the same section/start-here ranking as the legacy
    builder via :func:`_section_rank` and :func:`_start_here_page_rank`.
    """

    def is_overview(page: Any) -> bool:
        hints = (page._b.generation_hints or {}) if hasattr(page, "_b") else {}
        return bool(hints.get("is_introduction_page") or page.page_type == "overview")

    def is_endpoint_ref(page: Any) -> bool:
        hints = (page._b.generation_hints or {}) if hasattr(page, "_b") else {}
        return bool(hints.get("is_endpoint_ref") or page.page_type == "endpoint_ref")

    def page_exists(page: Any) -> bool:
        if is_overview(page):
            return (output_dir / "index.md").exists()
        return (output_dir / f"{page.slug}.md").exists()

    slug_to_page = {page.slug: page for page in plan.pages if page_exists(page)}

    # whats-changed is a generated page (not a DocBucket) — inject a synthetic entry.
    if (output_dir / "whats-changed.md").exists() and "whats-changed" not in slug_to_page:
        from ...persistence_v2 import DocPage as _DocPage

        slug_to_page["whats-changed"] = _DocPage(
            title="What's Changed",
            slug="whats-changed",
            page_type="changelog",
            description="Documentation changes per commit",
            source_files=[],
            section="Start Here",
        )

    nav: list[Any] = []

    # Overview / landing page first.
    if (output_dir / "index.md").exists():
        overview_page = next(
            (p for p in plan.pages if is_overview(p) and page_exists(p)), None
        )
        nav.append({getattr(overview_page, "title", None) or "Overview": "index.md"})

    grouped_slugs: set[str] = set()
    nav_tree: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    section_insert_order = 0

    for section_name, slugs in plan.nav_structure.items():
        pages = []
        for slug in slugs:
            page = slug_to_page.get(slug)
            if not page:
                continue
            if is_endpoint_ref(page):
                # Endpoint pages are consolidated into the single Swagger UI page.
                grouped_slugs.add(slug)
                continue
            if is_overview(page):
                grouped_slugs.add(slug)
                continue
            pages.append(page)
            grouped_slugs.add(slug)

        if not pages:
            continue

        parts = [p.strip() for p in section_name.split(" > ")]
        node = nav_tree
        for i, part in enumerate(parts):
            if part not in node:
                node[part] = {
                    "_pages": [],
                    "_children": OrderedDict(),
                    "_order": section_insert_order,
                }
                section_insert_order += 1
            if i == len(parts) - 1:
                node[part]["_pages"].extend(pages)
            else:
                node = node[part]["_children"]

    nav.extend(_tree_to_mkdocs_items(nav_tree))

    # Orphan pages that exist but were not placed in any nav section.
    orphan_pages = [
        page
        for page in plan.pages
        if page.slug in slug_to_page
        and page.slug not in grouped_slugs
        and not is_overview(page)
        and not is_endpoint_ref(page)
    ]
    if orphan_pages:
        nav.append(
            {"Other": [{page.title: f"{page.slug}.md"} for page in orphan_pages]}
        )

    if has_openapi:
        nav.append({"API Reference": "api.md"})

    return nav


def _tree_to_mkdocs_items(
    tree: "OrderedDict[str, dict[str, Any]]",
) -> list[Any]:
    """Convert the intermediate section tree into MkDocs nav items."""
    result: list[Any] = []
    sorted_items = sorted(
        tree.items(),
        key=lambda item: (_section_rank(item[0]), item[1]["_order"]),
    )
    for name, data in sorted_items:
        pages = list(data["_pages"])
        if name.strip().lower() == "start here":
            pages.sort(key=lambda p: (_start_here_page_rank(p.slug), p.title.lower()))
        items: list[Any] = [{page.title: f"{page.slug}.md"} for page in pages]
        items.extend(_tree_to_mkdocs_items(data["_children"]))
        if items:
            result.append({name: items})
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Landing page
# ─────────────────────────────────────────────────────────────────────────────


def _ensure_landing_page(output_dir: Path, project_name: str, plan: DocPlan) -> None:
    """Ensure the landing page exists as docs/index.md (Material grid cards)."""
    index_md = output_dir / "index.md"
    if index_md.exists():
        existing = index_md.read_text(encoding="utf-8")
        if "_deepdoc_autogen_" not in existing:
            return

    sections: dict[str, list[tuple[str, str]]] = {}
    for page in plan.pages:
        hints = (page._b.generation_hints or {}) if hasattr(page, "_b") else {}
        if hints.get("is_introduction_page") or page.page_type == "overview":
            continue
        if not (output_dir / f"{page.slug}.md").exists():
            continue
        section = getattr(page, "section", None) or "Docs"
        sections.setdefault(section, []).append((page.title, page.slug))

    ordered_section_names = sorted(sections.keys(), key=_section_rank)
    for section_name in ordered_section_names:
        if section_name.strip().lower() == "start here":
            sections[section_name].sort(
                key=lambda tp: (_start_here_page_rank(tp[1]), tp[0].lower())
            )

    cards_blocks: list[str] = []
    for section_name in ordered_section_names:
        pages = sections[section_name]
        if not pages:
            continue
        items = "\n".join(
            f"- **[{title}]({slug}.md)** — {title} documentation." for title, slug in pages
        )
        cards_blocks.append(
            f"## {section_name}\n\n"
            '<div class="grid cards" markdown>\n\n'
            f"{items}\n\n"
            "</div>"
        )

    body = "\n\n".join(cards_blocks) if cards_blocks else "_Documentation is being generated..._"
    content = f"""\
---
title: {_yaml_scalar(project_name)}
description: {_yaml_scalar("Auto-generated developer documentation")}
_deepdoc_autogen_: true
---

# {project_name}

Welcome to the **{project_name}** developer documentation.

{body}
"""
    index_md.write_text(content, encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# OpenAPI (mkdocs-swagger-ui-tag)
# ─────────────────────────────────────────────────────────────────────────────


def _stage_openapi_page(repo_root: Path, output_dir: Path) -> None:
    """Copy staged OpenAPI specs into the docs dir and write the Swagger UI page.

    Specs are staged by ``stage_openapi_assets`` into ``site/openapi/``. We copy
    each into ``docs/openapi/`` (inside docs_dir so the plugin can resolve them)
    and emit a ``<swagger-ui>`` tag per spec on a single ``api.md`` page. The
    plugin resolves ``src`` relative to the page's source file and rewrites the
    final URL, so a flat relative path is robust under ``use_directory_urls``.
    """
    staged_dir = repo_root / "site" / "openapi"
    specs: list[Path] = []
    if staged_dir.exists():
        for path in sorted(staged_dir.iterdir()):
            if not path.is_file():
                continue
            if path.name == "manifest.json":
                continue
            if path.suffix.lower() not in {".json", ".yaml", ".yml"}:
                continue
            specs.append(path)

    docs_openapi_dir = output_dir / "openapi"
    if docs_openapi_dir.exists():
        shutil.rmtree(docs_openapi_dir)

    if not specs:
        # No specs to render — drop a stale api.md if present and bail.
        stale = output_dir / "api.md"
        if stale.exists():
            stale.unlink()
        return

    docs_openapi_dir.mkdir(parents=True, exist_ok=True)
    tags: list[str] = []
    for spec in specs:
        dest = docs_openapi_dir / spec.name
        shutil.copyfile(spec, dest)
        tags.append(f'<swagger-ui src="openapi/{spec.name}"/>')

    content = (
        "---\ntitle: API Reference\n---\n\n# API Reference\n\n"
        + "\n\n".join(tags)
        + "\n"
    )
    (output_dir / "api.md").write_text(content, encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Scaffold writers
# ─────────────────────────────────────────────────────────────────────────────


def _write_mkdocs_scaffold(
    site_dir: Path,
    project_name: str,
    repo_url: str,
    docs_dir_relative: str,
    nav: list[Any],
    has_openapi: bool,
    cfg: dict[str, Any],
) -> None:
    """Write mkdocs.yml and the brand stylesheet."""
    (site_dir / "docs" / "stylesheets").mkdir(parents=True, exist_ok=True)
    (site_dir / "mkdocs.yml").write_text(
        _mkdocs_yml(project_name, repo_url, docs_dir_relative, nav, has_openapi),
        encoding="utf-8",
    )
    (site_dir / "docs" / "stylesheets" / "extra.css").write_text(
        _extra_css(cfg), encoding="utf-8"
    )


def _mkdocs_yml(
    project_name: str,
    repo_url: str,
    docs_dir_relative: str,
    nav: list[Any],
    has_openapi: bool,
) -> str:
    """Render mkdocs.yml. nav is YAML-serialized; the mermaid superfence keeps its
    Python tag via a templated block (yaml.dump cannot emit ``!!python/name:``)."""
    repo_line = f"repo_url: {_yaml_scalar(repo_url)}\n" if repo_url else ""
    plugins_block = "plugins:\n  - search\n"
    if has_openapi:
        plugins_block += "  - swagger-ui-tag\n"

    nav_yaml = yaml.safe_dump(
        {"nav": nav}, sort_keys=False, default_flow_style=False, allow_unicode=True
    )

    return f"""\
# DeepDoc-managed file. Regenerated by `deepdoc generate`.
site_name: {_yaml_scalar(project_name)}
{repo_line}docs_dir: {_yaml_scalar(docs_dir_relative)}
site_dir: out

theme:
  name: material
  palette:
    - media: "(prefers-color-scheme: light)"
      scheme: default
      primary: custom
      accent: custom
      toggle:
        icon: material/brightness-7
        name: Switch to dark mode
    - media: "(prefers-color-scheme: dark)"
      scheme: slate
      primary: custom
      accent: custom
      toggle:
        icon: material/brightness-4
        name: Switch to light mode
  features:
    - navigation.sections
    - navigation.instant
    - navigation.top
    - navigation.tracking
    - toc.follow
    - search.suggest
    - search.highlight
    - content.code.copy
    - content.tabs.link

extra_css:
  - stylesheets/extra.css

{plugins_block}
markdown_extensions:
  - admonition
  - attr_list
  - md_in_html
  - tables
  - toc:
      permalink: true
  - pymdownx.details
  - pymdownx.highlight:
      anchor_linenums: true
  - pymdownx.inlinehilite
  - pymdownx.snippets
  - pymdownx.superfences:
      custom_fences:
        - name: mermaid
          class: mermaid
          format: !!python/name:pymdownx.superfences.fence_code_format
  - pymdownx.blocks.admonition
  - pymdownx.blocks.details
  - pymdownx.blocks.tab:
      alternate_style: true

{nav_yaml}"""


def _extra_css(cfg: dict[str, Any]) -> str:
    """Map configured brand colors onto Material's primary/accent CSS variables."""
    colors = (cfg.get("site", {}) or {}).get("colors", {}) or {}
    primary = colors.get("primary") or _DEFAULT_PRIMARY
    light = colors.get("light") or _DEFAULT_LIGHT
    dark = colors.get("dark") or _DEFAULT_DARK
    return f"""\
/* DeepDoc-managed file. Regenerated by `deepdoc generate`. */
:root {{
  --md-primary-fg-color: {primary};
  --md-primary-fg-color--light: {light};
  --md-primary-fg-color--dark: {dark};
  --md-accent-fg-color: {light};
}}

[data-md-color-scheme="slate"] {{
  --md-primary-fg-color: {primary};
  --md-accent-fg-color: {light};
}}
"""


# ─────────────────────────────────────────────────────────────────────────────
# Cleanup
# ─────────────────────────────────────────────────────────────────────────────


def _cleanup_fumadocs_artifacts(site_dir: Path) -> None:
    """Remove Next.js/Fumadocs scaffold files left by the previous site builder."""
    for name in (
        "next.config.mjs",
        "source.config.mjs",
        "postcss.config.mjs",
        "tsconfig.json",
        "next-env.d.ts",
        "mdx-components.tsx",
        "package.json",
        "package-lock.json",
    ):
        path = site_dir / name
        if path.exists():
            path.unlink()

    for dirname in ("app", "lib", "components", ".next", ".source"):
        path = site_dir / dirname
        if path.is_dir():
            shutil.rmtree(path)


def _yaml_scalar(value: str) -> str:
    """Render a string as a safe single-line YAML scalar.

    A JSON-encoded string is a valid YAML flow scalar and round-trips any
    punctuation (colons, quotes, trailing periods) without ambiguity.
    """
    return json.dumps(value)
