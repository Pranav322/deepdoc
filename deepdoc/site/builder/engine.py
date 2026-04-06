from .common import *

def build_fumadocs_from_plan(
    repo_root: Path,
    output_dir: Path,
    cfg: dict[str, Any],
    plan: DocPlan,
    has_openapi: bool = False,
) -> None:
    """Build the generated Fumadocs site from the current doc plan."""
    project_name = cfg.get("project_name") or repo_root.name
    repo_url = cfg.get("site", {}).get("repo_url", "")

    output_dir.mkdir(parents=True, exist_ok=True)

    _rename_md_to_mdx(output_dir)
    _rename_legacy_intro_to_index(output_dir)
    _ensure_mdx_frontmatter(output_dir)
    _ensure_landing_page(output_dir, project_name, plan)

    docs_dir_relative = os.path.relpath(output_dir, repo_root / "site").replace(
        "\\", "/"
    )
    page_tree = _build_page_tree_from_plan(
        repo_root,
        plan,
        output_dir,
        project_name,
        has_openapi,
    )

    _ensure_app_scaffold(
        repo_root,
        project_name,
        repo_url,
        docs_dir_relative,
        cfg,
        has_openapi=has_openapi,
    )
    _write_page_tree(repo_root, page_tree)
    _write_static_assets(repo_root)
    _cleanup_legacy_artifacts(repo_root)


def _ensure_app_scaffold(
    repo_root: Path,
    project_name: str,
    repo_url: str,
    docs_dir_relative: str,
    cfg: dict[str, Any],
    has_openapi: bool,
) -> None:
    """Write or update the DeepDoc-managed Fumadocs app scaffold."""
    site_dir = repo_root / "site"
    site_dir.mkdir(parents=True, exist_ok=True)

    files = {
        site_dir / "package.json": _package_json(project_name),
        site_dir / "postcss.config.mjs": _postcss_config_mjs(),
        site_dir / "tsconfig.json": _tsconfig_json(),
        site_dir / "next-env.d.ts": _next_env_d_ts(),
        site_dir / "next.config.mjs": _next_config_mjs(),
        site_dir / "source.config.mjs": _source_config_mjs(docs_dir_relative),
        site_dir / "mdx-components.tsx": _mdx_components_tsx(has_openapi),
        site_dir / "app" / "layout.tsx": _app_layout_tsx(project_name),
        site_dir / "app" / "global.css": _global_css(cfg),
        site_dir / "app" / "ask" / "page.tsx": _chatbot_ask_page_tsx(),
        site_dir / "app" / "search" / "route.ts": _search_route_ts(),
        site_dir / "app" / "[[...slug]]" / "layout.tsx": _docs_layout_tsx(),
        site_dir / "app" / "[[...slug]]" / "page.tsx": _docs_page_tsx(),
        site_dir / "components" / "chatbot-panel.tsx": _chatbot_panel_tsx(),
        site_dir / "components" / "chatbot-toggle.tsx": _chatbot_toggle_tsx(),
        site_dir / "components" / "mdx" / "mermaid.tsx": _mermaid_component_tsx(),
        site_dir / "lib" / "chatbot-config.ts": _chatbot_config_ts(repo_root, cfg),
        site_dir / "lib" / "source.ts": _source_ts(),
        site_dir / "lib" / "layout-options.ts": _layout_options_ts(
            project_name, repo_url
        ),
        site_dir / "openapi" / ".gitkeep": "",
    }

    if has_openapi:
        files.update(
            {
                site_dir
                / "app"
                / "api"
                / "[[...slug]]"
                / "layout.tsx": _api_layout_tsx(),
                site_dir / "app" / "api" / "[[...slug]]" / "page.tsx": _api_page_tsx(),
                site_dir / "components" / "api-page.tsx": _api_page_component_tsx(),
                site_dir / "components" / "api-page.client.tsx": _api_page_client_tsx(),
                site_dir / "lib" / "openapi.ts": _openapi_ts(),
            }
        )

    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    if not has_openapi:
        stale_paths = [
            site_dir / "app" / "api" / "[[...slug]]" / "layout.tsx",
            site_dir / "app" / "api" / "[[...slug]]" / "page.tsx",
            site_dir / "components" / "api-page.tsx",
            site_dir / "components" / "api-page.client.tsx",
            site_dir / "lib" / "openapi.ts",
        ]
        for path in stale_paths:
            if path.exists():
                path.unlink()


def _build_page_tree_from_plan(
    repo_root: Path,
    plan: DocPlan,
    output_dir: Path,
    project_name: str,
    has_openapi: bool,
) -> dict[str, Any]:
    """Create a Fumadocs page tree from the saved nav structure."""

    def is_overview(page) -> bool:
        hints = (page._b.generation_hints or {}) if hasattr(page, "_b") else {}
        return hints.get("is_introduction_page") or page.page_type == "overview"

    def is_endpoint_ref(page) -> bool:
        hints = (page._b.generation_hints or {}) if hasattr(page, "_b") else {}
        return hints.get("is_endpoint_ref") or page.page_type == "endpoint_ref"

    def page_exists(page) -> bool:
        if is_overview(page):
            return (output_dir / "index.mdx").exists()
        if has_openapi and is_endpoint_ref(page):
            return True
        return (output_dir / f"{page.slug}.mdx").exists()

    def page_url(page) -> str:
        if is_overview(page):
            return "/"
        if has_openapi and is_endpoint_ref(page):
            return f"/api/{page.slug}"
        return f"/{page.slug}"

    def load_openapi_manifest() -> list[dict[str, str]]:
        manifest_path = repo_root / "site" / "openapi" / "manifest.json"
        if not manifest_path.exists():
            return []
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        out: list[dict[str, str]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            slug = str(item.get("slug") or "").strip()
            title = str(item.get("title") or "").strip()
            method = str(item.get("method") or "").strip().upper()
            path = str(item.get("path") or "").strip()
            if slug and title and method and path:
                out.append(
                    {
                        "slug": slug,
                        "title": title,
                        "method": method,
                        "path": path,
                    }
                )
        return out

    def display_openapi_path(path: str) -> str:
        if "://" in path:
            from urllib.parse import urlparse

            parsed = urlparse(path)
            return parsed.path or "/"
        return path

    slug_to_page = {page.slug: page for page in plan.pages if page_exists(page)}
    root_children: list[dict[str, Any]] = []

    overview_page = next(
        (page for page in plan.pages if is_overview(page) and page_exists(page)), None
    )
    if overview_page or (output_dir / "index.mdx").exists():
        root_children.append(
            {
                "type": "page",
                "name": getattr(overview_page, "title", None) or project_name,
                "url": "/",
            }
        )

    from collections import OrderedDict

    grouped_slugs: set[str] = set()
    nav_tree: OrderedDict[str, dict[str, Any]] = OrderedDict()
    section_insert_order = 0

    for section_name, slugs in plan.nav_structure.items():
        pages = []
        for slug in slugs:
            page = slug_to_page.get(slug)
            if not page:
                continue
            if has_openapi and is_endpoint_ref(page):
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

    def _tree_to_fumadocs(
        tree: OrderedDict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        result = []
        for name, data in sorted(tree.items(), key=lambda item: item[1]["_order"]):
            sub_children: list[dict[str, Any]] = []
            for page in data["_pages"]:
                sub_children.append(_page_tree_node(page_url(page), page.title))
            sub_children.extend(_tree_to_fumadocs(data["_children"]))
            if sub_children:
                result.append(
                    {
                        "type": "folder",
                        "name": name,
                        "children": sub_children,
                    }
                )
        return result

    root_children.extend(_tree_to_fumadocs(nav_tree))

    orphan_pages = [
        page
        for page in plan.pages
        if page.slug in slug_to_page
        and page.slug not in grouped_slugs
        and not is_overview(page)
        and not (has_openapi and is_endpoint_ref(page))
    ]
    if orphan_pages:
        root_children.append(
            {
                "type": "folder",
                "name": "Other",
                "children": [
                    _page_tree_node(page_url(page), page.title) for page in orphan_pages
                ],
            }
        )

    if has_openapi:
        api_pages = [
            page for page in plan.pages if page_exists(page) and is_endpoint_ref(page)
        ]
        if api_pages:
            root_children.append(
                {
                    "type": "folder",
                    "name": "API Reference",
                    "children": [
                        _page_tree_node(f"/api/{page.slug}", page.title)
                        for page in api_pages
                    ],
                }
            )
        else:
            manifest_entries = load_openapi_manifest()
            if manifest_entries:
                operations_folder = {
                    "type": "folder",
                    "name": "OpenAPI Operations",
                    "children": [
                        _page_tree_node(
                            f"/api/{entry['slug']}",
                            f"{entry['method']} {display_openapi_path(entry['path'])}",
                        )
                        for entry in manifest_entries
                    ],
                }

                existing_api_folder = next(
                    (
                        child
                        for child in root_children
                        if child.get("type") == "folder"
                        and child.get("name") == "API Reference"
                    ),
                    None,
                )
                if existing_api_folder:
                    existing_api_folder.setdefault("children", []).append(
                        operations_folder
                    )
                else:
                    root_children.append(
                        {
                            "type": "folder",
                            "name": "API Reference",
                            "children": [operations_folder],
                        }
                    )

    return {"name": project_name, "children": root_children}


def _page_tree_node(url: str, name: str) -> dict[str, str]:
    return {"type": "page", "name": name, "url": url}


def _write_page_tree(repo_root: Path, page_tree: dict[str, Any]) -> None:
    """Write the generated Fumadocs page tree module."""
    site_dir = repo_root / "site"
    site_dir.mkdir(parents=True, exist_ok=True)
    content = dedent(
        f"""\
        // DeepDoc-managed file. Regenerated by `deepdoc generate`.
        import type {{ PageTree }} from 'fumadocs-core/server';

        export const pageTree = {json.dumps(page_tree, indent=2)} satisfies PageTree.Root;
        """
    )
    (site_dir / "lib" / "page-tree.generated.ts").write_text(content, encoding="utf-8")


def _write_static_assets(repo_root: Path) -> None:
    """Create placeholder site assets under the generated Fumadocs app."""
    public_dir = repo_root / "site" / "public"
    public_dir.mkdir(parents=True, exist_ok=True)

    light_logo = """\
<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32" fill="none">
  <rect width="32" height="32" rx="8" fill="#0f766e"/>
  <path d="M9 10h14M9 16h10M9 22h14" stroke="white" stroke-width="2.5" stroke-linecap="round"/>
</svg>
"""
    dark_logo = """\
<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32" fill="none">
  <rect width="32" height="32" rx="8" fill="#14b8a6"/>
  <path d="M9 10h14M9 16h10M9 22h14" stroke="white" stroke-width="2.5" stroke-linecap="round"/>
</svg>
"""

    (public_dir / "logo-light.svg").write_text(light_logo, encoding="utf-8")
    (public_dir / "logo-dark.svg").write_text(dark_logo, encoding="utf-8")
    (public_dir / "favicon.svg").write_text(light_logo, encoding="utf-8")


def _cleanup_legacy_artifacts(repo_root: Path) -> None:
    """Remove legacy root artifacts left behind by earlier site builders."""
    for path in (
        repo_root / "mint.json",
        repo_root / "favicon.svg",
    ):
        if path.exists():
            path.unlink()

    legacy_logo_dir = repo_root / "logo"
    if legacy_logo_dir.exists():
        for child in legacy_logo_dir.iterdir():
            if child.is_file():
                child.unlink()
        with contextlib.suppress(OSError):
            legacy_logo_dir.rmdir()


def _rename_legacy_intro_to_index(output_dir: Path) -> None:
    """Migrate legacy overview filenames to Fumadocs' index.mdx."""
    for legacy_name in ("introduction.mdx", "intro.mdx", "index.md", "intro.md"):
        legacy_path = output_dir / legacy_name
        index_mdx = output_dir / "index.mdx"
        if legacy_path.exists() and not index_mdx.exists():
            content = legacy_path.read_text(encoding="utf-8")
            content = _strip_docusaurus_frontmatter(content)
            index_mdx.write_text(content, encoding="utf-8")
        if legacy_path.exists() and legacy_path.name != "index.mdx":
            legacy_path.unlink()


def _rename_md_to_mdx(output_dir: Path) -> None:
    """Rename generated Markdown pages to MDX."""
    for md_file in list(output_dir.rglob("*.md")):
        mdx_file = md_file.with_suffix(".mdx")
        if not mdx_file.exists():
            content = md_file.read_text(encoding="utf-8")
            content = _strip_docusaurus_frontmatter(content)
            mdx_file.write_text(content, encoding="utf-8")
        md_file.unlink()


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


def _ensure_landing_page(output_dir: Path, project_name: str, plan: DocPlan) -> None:
    """Ensure the landing page exists as docs/index.mdx."""
    index_mdx = output_dir / "index.mdx"
    if index_mdx.exists():
        existing = index_mdx.read_text(encoding="utf-8")
        if "_deepdoc_autogen_" not in existing:
            return

    sections: dict[str, list[tuple[str, str]]] = {}
    for page in plan.pages:
        hints = (page._b.generation_hints or {}) if hasattr(page, "_b") else {}
        if hints.get("is_introduction_page") or page.page_type == "overview":
            continue
        if not (output_dir / f"{page.slug}.mdx").exists():
            continue
        section = getattr(page, "section", None) or "Docs"
        sections.setdefault(section, []).append((page.title, page.slug))

    cards_section: list[str] = []
    for section_name, pages in sections.items():
        cards = []
        for title, slug in pages:
            cards.append(
                f'  <Card title="{title}" href="/{slug}">\n'
                f"    {title} documentation.\n"
                f"  </Card>"
            )
        cards_section.append(
            f"## {section_name}\n\n<Cards>\n" + "\n".join(cards) + "\n</Cards>"
        )

    body = (
        "\n\n".join(cards_section)
        if cards_section
        else "_Documentation is being generated..._"
    )
    content = f"""\
---
title: {json.dumps(project_name)}
description: {json.dumps("Auto-generated developer documentation")}
_deepdoc_autogen_: true
---

# {project_name}

Welcome to the **{project_name}** developer documentation.

{body}
"""
    index_mdx.write_text(content, encoding="utf-8")


from .templates import _api_layout_tsx, _api_page_client_tsx, _api_page_component_tsx, _api_page_tsx, _app_layout_tsx, _chatbot_ask_page_tsx, _chatbot_config_ts, _chatbot_panel_tsx, _chatbot_toggle_tsx, _docs_layout_tsx, _docs_page_tsx, _global_css, _layout_options_ts, _mdx_components_tsx, _mermaid_component_tsx, _next_config_mjs, _next_env_d_ts, _openapi_ts, _package_json, _postcss_config_mjs, _search_route_ts, _source_config_mjs, _source_ts, _tsconfig_json
from .mdx_utils import _ensure_mdx_frontmatter
