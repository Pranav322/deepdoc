"""V2 Fumadocs builder — builds a local docs site from the AI-generated plan.

Generates:
- site/                  (Next.js + Fumadocs app scaffold)
- site/public/*          (placeholder logo + favicon assets)
- site/lib/page-tree.generated.ts
- docs/index.mdx         (landing page if a legacy overview page needs migration)

The generated site reads MDX content from the configurable docs output directory.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from textwrap import dedent
from typing import Any

from ..chatbot.settings import chatbot_site_api_base_url
from ..planner_v2 import DocPlan


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

    docs_dir_relative = os.path.relpath(output_dir, repo_root / "site").replace("\\", "/")
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
        site_dir / "lib" / "layout-options.ts": _layout_options_ts(project_name, repo_url),
        site_dir / "openapi" / ".gitkeep": "",
    }

    if has_openapi:
        files.update(
            {
                site_dir / "app" / "api" / "[[...slug]]" / "layout.tsx": _api_layout_tsx(),
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

    overview_page = next((page for page in plan.pages if is_overview(page) and page_exists(page)), None)
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

    def _tree_to_fumadocs(tree: OrderedDict[str, dict[str, Any]]) -> list[dict[str, Any]]:
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
                "children": [_page_tree_node(page_url(page), page.title) for page in orphan_pages],
            }
        )

    if has_openapi:
        api_pages = [
            page
            for page in plan.pages
            if page_exists(page) and is_endpoint_ref(page)
        ]
        if api_pages:
            root_children.append(
                {
                    "type": "folder",
                    "name": "API Reference",
                    "children": [
                        _page_tree_node(f"/api/{page.slug}", page.title) for page in api_pages
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
                        if child.get("type") == "folder" and child.get("name") == "API Reference"
                    ),
                    None,
                )
                if existing_api_folder:
                    existing_api_folder.setdefault("children", []).append(operations_folder)
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
        try:
            legacy_logo_dir.rmdir()
        except OSError:
            pass


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
        line for line in lines[1:end_idx]
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

    body = "\n\n".join(cards_section) if cards_section else "_Documentation is being generated..._"
    content = f"""\
---
title: {project_name}
description: Auto-generated developer documentation
_deepdoc_autogen_: true
---

# {project_name}

Welcome to the **{project_name}** developer documentation.

{body}
"""
    index_mdx.write_text(content, encoding="utf-8")


def _first_mdx_heading(text: str, fallback: str) -> str:
    """Extract the first H1 title from MDX content, or fall back to the file stem."""
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def _split_leading_frontmatter(text: str) -> tuple[list[str], str] | None:
    """Split a leading frontmatter block from the remaining document body."""
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return None

    lines = stripped.splitlines()
    try:
        end_idx = lines.index("---", 1)
    except ValueError:
        return None

    return lines[1:end_idx], "\n".join(lines[end_idx + 1 :])


def _frontmatter_has_yaml_fields(frontmatter_lines: list[str]) -> bool:
    """Return True when the frontmatter block contains YAML-style key/value fields."""
    return any(
        ":" in line and not line.lstrip().startswith("#")
        for line in frontmatter_lines
        if line.strip()
    )


def _ensure_mdx_frontmatter(output_dir: Path) -> None:
    """Add minimal frontmatter to generated MDX pages and repair malformed blocks."""
    for mdx_path in output_dir.glob("*.mdx"):
        text = mdx_path.read_text(encoding="utf-8", errors="replace")
        fallback_title = mdx_path.stem.replace("-", " ").replace("_", " ").title()
        frontmatter_block = _split_leading_frontmatter(text)
        body_text = text.lstrip()

        if frontmatter_block:
            frontmatter_lines, frontmatter_body = frontmatter_block
            if _frontmatter_has_yaml_fields(frontmatter_lines):
                continue
            title = _first_mdx_heading("\n".join(frontmatter_lines) + "\n" + frontmatter_body, fallback_title)
            repaired_intro = "\n".join(frontmatter_lines).strip()
            if repaired_intro and frontmatter_body.lstrip():
                body_text = repaired_intro + "\n\n" + frontmatter_body.lstrip()
            elif repaired_intro:
                body_text = repaired_intro
            else:
                body_text = frontmatter_body.lstrip()
        else:
            title = _first_mdx_heading(text, fallback_title)

        frontmatter_lines = [
            "---",
            f"title: {json.dumps(title)}",
            "description: Auto-generated developer documentation",
        ]
        if mdx_path.name != "index.mdx":
            frontmatter_lines.append("_deepdoc_autogen_: true")
        frontmatter = "\n".join(frontmatter_lines) + "\n---\n\n"
        mdx_path.write_text(frontmatter + body_text.lstrip(), encoding="utf-8")


def _package_json(project_name: str) -> str:
    return json.dumps(
        {
            "name": f"{project_name.lower().replace(' ', '-')}-docs",
            "private": True,
            "type": "module",
            "scripts": {
                "dev": "next dev",
                "build": "next build",
                "start": "next dev",
            },
            "dependencies": {
                "@orama/orama": "^3.1.10",
                "@types/mdx": "^2.0.13",
                "fumadocs-core": "15.7.9",
                "fumadocs-mdx": "11.9.0",
                "fumadocs-openapi": "9.3.9",
                "fumadocs-ui": "15.7.11",
                "mermaid": "^11.6.0",
                "next": "15.3.0",
                "next-themes": "0.4.6",
                "react": "19.1.0",
                "react-dom": "19.1.0",
                "react-markdown": "^10.1.0",
                "tailwindcss": "^4.1.3",
            },
            "devDependencies": {
                "@tailwindcss/postcss": "^4.1.14",
                "@types/node": "^22.13.9",
                "@types/react": "^19.0.12",
                "@types/react-dom": "^19.0.4",
                "typescript": "^5.8.2",
            },
        },
        indent=2,
    ) + "\n"


def _tsconfig_json() -> str:
    return json.dumps(
        {
            "compilerOptions": {
                "target": "ES2022",
                "lib": ["dom", "dom.iterable", "es2022"],
                "allowJs": False,
                "skipLibCheck": True,
                "strict": True,
                "noEmit": True,
                "esModuleInterop": True,
                "module": "esnext",
                "moduleResolution": "bundler",
                "resolveJsonModule": True,
                "isolatedModules": True,
                "jsx": "preserve",
                "incremental": True,
                "baseUrl": ".",
                "paths": {
                    "@/*": ["./*"],
                    "fumadocs-mdx:collections/*": [".source/*"],
                },
                "plugins": [{"name": "next"}],
            },
            "include": [
                "next-env.d.ts",
                "**/*.ts",
                "**/*.tsx",
                ".next/types/**/*.ts",
                ".source/**/*.ts",
            ],
            "exclude": ["node_modules"],
        },
        indent=2,
    ) + "\n"


def _postcss_config_mjs() -> str:
    return dedent(
        """\
        export default {
          plugins: {
            '@tailwindcss/postcss': {},
          },
        };
        """
    )


def _next_env_d_ts() -> str:
    return dedent(
        """\
        /// <reference types="next" />
        /// <reference types="next/image-types/global" />

        // This file is generated by Next.js. Do not edit manually.
        """
    )


def _next_config_mjs() -> str:
    return dedent(
        """\
        import path from 'node:path';
        import { fileURLToPath } from 'node:url';
        import { createMDX } from 'fumadocs-mdx/next';

        const __dirname = path.dirname(fileURLToPath(import.meta.url));
        const repoRoot = path.join(__dirname, '..');
        const withMDX = createMDX({
          configPath: './source.config.mjs',
        });
        const explicitBasePath = (process.env.DEEPDOC_SITE_BASE_PATH ?? '').trim();
        const normalizedExplicitBasePath = explicitBasePath
          ? `/${explicitBasePath.replace(/^\\/+|\\/+$/g, '')}`
          : '';
        const repository = process.env.GITHUB_REPOSITORY ?? '';
        const [, repoName = ''] = repository.split('/');
        const isUserSite = repoName.endsWith('.github.io');
        const githubPagesBasePath =
          process.env.GITHUB_PAGES === 'true' && repoName && !isUserSite
            ? `/${repoName}`
            : '';
        const siteBasePath = normalizedExplicitBasePath || githubPagesBasePath;
        const useTrailingSlash = process.env.GITHUB_PAGES === 'true' || Boolean(siteBasePath);

        /** @type {import('next').NextConfig} */
        const config = {
          reactStrictMode: true,
          output: 'export',
          trailingSlash: useTrailingSlash,
          basePath: siteBasePath || undefined,
          assetPrefix: siteBasePath || undefined,
          images: {
            unoptimized: true,
          },
          experimental: {
            externalDir: true,
          },
          outputFileTracingRoot: repoRoot,
        };

        export default withMDX(config);
        """
    )


def _source_config_mjs(docs_dir_relative: str) -> str:
    return dedent(
        f"""\
        import {{ defineDocs, defineConfig }} from 'fumadocs-mdx/config';
        import {{ remarkMdxMermaid }} from 'fumadocs-core/mdx-plugins';

        export const {{ docs, meta }} = defineDocs({{
          dir: '{docs_dir_relative}',
        }});

        export default defineConfig({{
          mdxOptions: {{
            remarkPlugins: [remarkMdxMermaid],
          }},
        }});
        """
    )


def _mdx_components_tsx(has_openapi: bool) -> str:
    api_import = "import { APIPage } from '@/components/api-page';\n" if has_openapi else ""
    api_component = "    APIPage,\n" if has_openapi else ""
    return dedent(
        f"""\
        import defaultMdxComponents from 'fumadocs-ui/mdx';
        import * as AccordionComponents from 'fumadocs-ui/components/accordion';
        import * as StepsComponents from 'fumadocs-ui/components/steps';
        import * as TabsComponents from 'fumadocs-ui/components/tabs';
        {api_import}import {{ Mermaid }} from '@/components/mdx/mermaid';
        import type {{ MDXComponents }} from 'mdx/types';

        export function getMDXComponents(components?: MDXComponents): MDXComponents {{
          return {{
            ...defaultMdxComponents,
            ...AccordionComponents,
            ...StepsComponents,
            ...TabsComponents,
{api_component}            Mermaid,
            ...components,
          }};
        }}

        export const useMDXComponents = getMDXComponents;
        """
    )


def _app_layout_tsx(project_name: str) -> str:
    return dedent(
        f"""\
        import './global.css';
        import {{ ChatbotToggle }} from '@/components/chatbot-toggle';
        import {{ RootProvider }} from 'fumadocs-ui/provider';
        import type {{ Metadata }} from 'next';
        import type {{ ReactNode }} from 'react';

        export const metadata: Metadata = {{
          title: '{project_name}',
          description: 'Auto-generated developer documentation',
          icons: {{
            icon: 'favicon.svg',
          }},
        }};

        const siteBasePath = (process.env.NEXT_PUBLIC_DEEPDOC_SITE_BASE_PATH ?? '').replace(/\\/+$/, '');
        const searchApiPath = siteBasePath ? `${{siteBasePath}}/search` : '/search';

        export default function RootLayout({{
          children,
        }}: {{
          children: ReactNode;
        }}) {{
          return (
            <html lang="en" suppressHydrationWarning>
              <body className="min-h-screen bg-fd-background text-fd-foreground antialiased">
        <RootProvider
          search={{{{
            options: {{
              api: searchApiPath,
              type: 'static',
            }},
          }}}}
        >
                  {{children}}
                  <ChatbotToggle />
                </RootProvider>
              </body>
            </html>
          );
        }}
        """
    )


def _global_css(cfg: dict[str, Any]) -> str:
    site_cfg = cfg.get("site", {})
    site_colors = site_cfg.get("colors", {}) if isinstance(site_cfg, dict) else {}
    primary = site_colors.get("primary") or "#EB3E25"
    light = site_colors.get("light") or "#EF624E"
    dark = site_colors.get("dark") or "#C1331F"

    css = dedent(
        """\
        @import 'tailwindcss';
        @import 'fumadocs-ui/css/neutral.css';
        @import 'fumadocs-ui/css/preset.css';
        @import 'fumadocs-openapi/css/preset.css';

        :root {
          --deepdoc-accent: __PRIMARY__;
          --deepdoc-brand-primary: __PRIMARY__;
          --deepdoc-brand-light: __LIGHT__;
          --deepdoc-brand-dark: __DARK__;
          --color-fd-primary: var(--deepdoc-brand-primary);
          --color-fd-primary-foreground: #fff7f4;
          --color-fd-ring: color-mix(in srgb, var(--deepdoc-brand-primary) 40%, white 60%);
        }

        body {
          font-feature-settings: 'liga' 1, 'calt' 1;
          background: var(--color-fd-background);
          padding-bottom: clamp(7.5rem, 18vh, 10rem);
        }

        .deepdoc-chatbot-shell {
          pointer-events: none;
          position: fixed;
          left: 50%;
          bottom: clamp(0.9rem, 2vw, 1.5rem);
          z-index: 60;
          width: min(56rem, calc(100vw - 2rem));
          transform: translateX(-50%);
        }

        .deepdoc-chatbot-dock {
          pointer-events: auto;
          border: 1px solid color-mix(in srgb, var(--deepdoc-brand-light) 8%, var(--color-fd-border) 92%);
          border-radius: 1.4rem;
          padding: 0.9rem;
          background: color-mix(in srgb, white 98.5%, var(--deepdoc-brand-light) 1.5%);
          box-shadow:
            0 10px 28px rgba(131, 39, 25, 0.05),
            0 4px 10px rgba(235, 62, 37, 0.025);
          backdrop-filter: blur(8px);
        }

        .deepdoc-chatbot-dock__meta {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 1rem;
          margin-bottom: 0.75rem;
        }

        .deepdoc-chatbot-dock__eyebrow {
          display: inline-flex;
          align-items: center;
          gap: 0.5rem;
          font-size: 0.76rem;
          font-weight: 600;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          color: color-mix(in srgb, var(--deepdoc-brand-dark) 70%, var(--color-fd-muted-foreground) 30%);
        }

        .deepdoc-chatbot-dock__eyebrow::before {
          content: '';
          height: 0.45rem;
          width: 0.45rem;
          border-radius: 999px;
          background: color-mix(in srgb, var(--deepdoc-brand-primary) 72%, white 28%);
          box-shadow: 0 0 0 0.18rem color-mix(in srgb, var(--deepdoc-brand-light) 8%, white 92%);
        }

        .deepdoc-chatbot-dock__hint {
          max-width: 22rem;
          font-size: 0.84rem;
          color: color-mix(in srgb, var(--color-fd-muted-foreground) 82%, transparent 18%);
          text-align: right;
        }

        .deepdoc-chatbot-dock__row {
          display: grid;
          grid-template-columns: minmax(0, 1fr) auto;
          gap: 0.8rem;
          align-items: end;
        }

        .deepdoc-chatbot-dock__input,
        .deepdoc-chatbot-panel__input,
        .deepdoc-chatbot-panel__button {
          border: 1px solid color-mix(in srgb, var(--deepdoc-brand-light) 8%, var(--color-fd-border) 92%);
        }

        .deepdoc-chatbot-dock__input,
        .deepdoc-chatbot-panel__input {
          min-height: 5rem;
          resize: vertical;
          border-radius: 1rem;
          background: white;
          padding: 0.95rem 1rem;
          color: var(--color-fd-foreground);
          box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7);
        }

        .deepdoc-chatbot-dock__input:focus,
        .deepdoc-chatbot-panel__input:focus {
          outline: 2px solid color-mix(in srgb, var(--deepdoc-brand-light) 24%, white 76%);
          outline-offset: 2px;
        }

        .deepdoc-chatbot-dock__submit,
        .deepdoc-chatbot-panel__button {
          border-radius: 999px;
          padding: 0.9rem 1.25rem;
          background: linear-gradient(135deg, var(--deepdoc-brand-light), var(--deepdoc-brand-primary) 58%, var(--deepdoc-brand-dark));
          color: white;
          box-shadow: 0 10px 22px rgba(193, 51, 31, 0.12);
          transition: transform 160ms ease, box-shadow 160ms ease, filter 160ms ease;
        }

        .deepdoc-chatbot-dock__submit:hover:not(:disabled),
        .deepdoc-chatbot-panel__button:hover:not(:disabled) {
          transform: translateY(-1px);
          box-shadow: 0 14px 28px rgba(193, 51, 31, 0.16);
          filter: saturate(1.04);
        }

        .deepdoc-chatbot-dock__submit:disabled,
        .deepdoc-chatbot-panel__button:disabled {
          cursor: wait;
          opacity: 0.74;
        }

        .deepdoc-chatbot-page {
          width: min(76rem, calc(100vw - 2.5rem));
          margin: 0 auto;
          padding: 2.4rem 0 11rem;
        }

        .deepdoc-chatbot-page__back {
          display: inline-flex;
          align-items: center;
          gap: 0.5rem;
          font-size: 0.95rem;
          color: var(--color-fd-muted-foreground);
          text-decoration: none;
        }

        .deepdoc-chatbot-page__back:hover {
          color: var(--deepdoc-brand-dark);
        }

        .deepdoc-chatbot-page__hero {
          display: flex;
          flex-wrap: wrap;
          align-items: flex-end;
          justify-content: space-between;
          gap: 1rem;
          margin: 1rem 0 1.4rem;
        }

        .deepdoc-chatbot-page__eyebrow {
          margin: 0 0 0.45rem;
          font-size: 0.82rem;
          font-weight: 700;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          color: var(--deepdoc-brand-dark);
        }

        .deepdoc-chatbot-page__hero h1 {
          margin: 0;
          max-width: 40rem;
          font-size: clamp(2rem, 3vw, 3rem);
          line-height: 1.04;
          letter-spacing: -0.04em;
          color: #25110d;
        }

        .deepdoc-chatbot-page__hero p {
          margin: 0.65rem 0 0;
          max-width: 38rem;
          color: var(--color-fd-muted-foreground);
        }

        .deepdoc-chatbot-page__chip {
          display: inline-flex;
          align-items: center;
          border: 1px solid color-mix(in srgb, var(--deepdoc-brand-light) 14%, var(--color-fd-border) 86%);
          border-radius: 999px;
          padding: 0.5rem 0.8rem;
          font-size: 0.88rem;
          color: var(--deepdoc-brand-dark);
          background: color-mix(in srgb, white 92%, var(--deepdoc-brand-light) 8%);
        }

        .deepdoc-chatbot-page__grid {
          display: grid;
          grid-template-columns: minmax(0, 1.45fr) minmax(18rem, 0.85fr);
          gap: 1.25rem;
          align-items: start;
        }

        .deepdoc-chatbot-page__grid > * {
          min-width: 0;
        }

        .deepdoc-chatbot-panel,
        .deepdoc-chatbot-sidebar {
          min-width: 0;
          border: 1px solid color-mix(in srgb, var(--deepdoc-brand-light) 14%, var(--color-fd-border) 86%);
          border-radius: 1.5rem;
          background: color-mix(in srgb, white 96%, var(--deepdoc-brand-light) 4%);
          box-shadow: 0 20px 60px rgba(131, 39, 25, 0.08);
        }

        .deepdoc-chatbot-sidebar {
          position: sticky;
          top: 1.5rem;
          padding: 1rem;
        }

        .deepdoc-chatbot-panel__header,
        .deepdoc-chatbot-sidebar__header {
          margin-bottom: 1rem;
          padding-bottom: 0.85rem;
          border-bottom: 1px solid color-mix(in srgb, var(--deepdoc-brand-light) 10%, var(--color-fd-border) 90%);
        }

        .deepdoc-chatbot-panel__header {
          padding: 1.2rem 1.25rem 0;
          background: transparent;
        }

        .deepdoc-chatbot-panel__body {
          padding: 0 1.25rem 1.25rem;
        }

        .deepdoc-chatbot-panel__question {
          margin: 0;
          font-size: 0.84rem;
          font-weight: 600;
          color: var(--color-fd-muted-foreground);
          text-transform: uppercase;
          letter-spacing: 0.06em;
        }

        .deepdoc-chatbot-panel__section-title {
          color: var(--deepdoc-brand-dark);
        }

        .deepdoc-chatbot-panel__empty {
          border: 1px dashed color-mix(in srgb, var(--deepdoc-brand-light) 22%, var(--color-fd-border) 78%);
          border-radius: 1.2rem;
          padding: 1.2rem;
          color: var(--color-fd-muted-foreground);
          background: color-mix(in srgb, white 94%, var(--deepdoc-brand-light) 6%);
        }

        .deepdoc-chatbot-skeleton {
          display: grid;
          gap: 0.85rem;
        }

        .deepdoc-chatbot-skeleton__block,
        .deepdoc-chatbot-skeleton__line,
        .deepdoc-chatbot-skeleton__card {
          position: relative;
          overflow: hidden;
          background: color-mix(in srgb, white 84%, var(--deepdoc-brand-light) 16%);
        }

        .deepdoc-chatbot-skeleton__block::after,
        .deepdoc-chatbot-skeleton__line::after,
        .deepdoc-chatbot-skeleton__card::after {
          content: '';
          position: absolute;
          inset: 0;
          transform: translateX(-100%);
          background: linear-gradient(
            90deg,
            transparent 0%,
            rgba(255, 255, 255, 0.66) 50%,
            transparent 100%
          );
          animation: deepdoc-chatbot-skeleton-shimmer 1.7s ease-in-out infinite;
        }

        .deepdoc-chatbot-skeleton__block {
          height: 12rem;
          border-radius: 1.2rem;
        }

        .deepdoc-chatbot-skeleton__line {
          height: 0.82rem;
          border-radius: 999px;
        }

        .deepdoc-chatbot-skeleton__line--sm {
          width: 28%;
        }

        .deepdoc-chatbot-skeleton__line--md {
          width: 56%;
        }

        .deepdoc-chatbot-skeleton__line--lg {
          width: 82%;
        }

        .deepdoc-chatbot-skeleton__line--full {
          width: 100%;
        }

        .deepdoc-chatbot-skeleton__cards {
          display: grid;
          gap: 0.85rem;
        }

        .deepdoc-chatbot-skeleton__card {
          height: 5.6rem;
          border-radius: 1rem;
        }

        @keyframes deepdoc-chatbot-skeleton-shimmer {
          100% {
            transform: translateX(100%);
          }
        }

        .deepdoc-chatbot-citation-list {
          display: grid;
          gap: 0.75rem;
        }

        .deepdoc-chatbot-citation-list li {
          min-width: 0;
          border: 1px solid color-mix(in srgb, var(--deepdoc-brand-light) 14%, var(--color-fd-border) 86%);
          border-radius: 1rem;
          padding: 0.8rem 0.9rem;
          background: white;
        }

        .deepdoc-chatbot-citation-list strong {
          display: block;
          margin-bottom: 0.2rem;
          color: #2f120d;
          overflow-wrap: anywhere;
          word-break: break-word;
        }

        .deepdoc-chatbot-citation-list span {
          display: block;
          font-size: 0.88rem;
          color: var(--color-fd-muted-foreground);
          overflow-wrap: anywhere;
          word-break: break-word;
        }

        .deepdoc-chatbot-citation-list a,
        .deepdoc-chatbot-answer a,
        main a {
          color: var(--deepdoc-brand-dark);
          text-decoration-color: color-mix(in srgb, var(--deepdoc-brand-primary) 36%, currentColor 64%);
        }

        .deepdoc-chatbot-citation-list a:hover,
        .deepdoc-chatbot-answer a:hover,
        main a:hover {
          color: var(--deepdoc-brand-primary);
        }

        ::selection {
          background: color-mix(in srgb, var(--deepdoc-brand-light) 28%, white 72%);
          color: #2f120d;
        }

        .deepdoc-chatbot-answer {
          overflow-wrap: anywhere;
        }

        .deepdoc-chatbot-answer__pre {
          margin: 1rem 0;
          overflow: hidden;
          border: 1px solid color-mix(in srgb, var(--deepdoc-brand-light) 10%, var(--color-fd-border) 90%);
          border-radius: 1.05rem;
          background:
            linear-gradient(180deg, rgba(36, 38, 53, 0.98), rgba(20, 21, 32, 1));
          box-shadow:
            inset 0 1px 0 rgba(255, 255, 255, 0.04),
            0 18px 40px rgba(17, 24, 39, 0.16);
        }

        .deepdoc-chatbot-answer__pre-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 0.75rem;
          padding: 0.7rem 0.9rem;
          border-bottom: 1px solid rgba(255, 255, 255, 0.06);
          background: rgba(255, 255, 255, 0.03);
        }

        .deepdoc-chatbot-answer__pre-dots {
          display: inline-flex;
          gap: 0.35rem;
        }

        .deepdoc-chatbot-answer__pre-dots span {
          height: 0.55rem;
          width: 0.55rem;
          border-radius: 999px;
          background: rgba(255, 255, 255, 0.2);
        }

        .deepdoc-chatbot-answer__pre-dots span:nth-child(1) {
          background: #f38ba8;
        }

        .deepdoc-chatbot-answer__pre-dots span:nth-child(2) {
          background: #f9e2af;
        }

        .deepdoc-chatbot-answer__pre-dots span:nth-child(3) {
          background: #a6e3a1;
        }

        .deepdoc-chatbot-answer__pre-label {
          font-size: 0.72rem;
          font-weight: 600;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          color: rgba(226, 232, 240, 0.72);
        }

        .deepdoc-chatbot-answer__pre pre {
          margin: 0;
          overflow-x: auto;
          padding: 1rem 1.05rem 1.1rem;
          background: #181a27 !important;
          border: none;
          color: #e5e7eb !important;
        }

        .deepdoc-chatbot-answer__pre code {
          display: block;
          font-family: 'SF Mono', 'JetBrains Mono', 'Fira Code', 'Menlo', monospace;
          font-size: 0.88rem;
          line-height: 1.72;
          color: #e5e7eb !important;
          background: transparent !important;
          white-space: pre;
        }

        .deepdoc-chatbot-answer.prose :where(pre):not(:where([class~="not-prose"] *)) {
          margin: 0 !important;
          padding: 1rem 1.05rem 1.1rem !important;
          background: #181a27 !important;
          border: none !important;
          border-radius: 0 !important;
          box-shadow: none !important;
          color: #e5e7eb !important;
        }

        .deepdoc-chatbot-answer.prose :where(pre code):not(:where([class~="not-prose"] *)) {
          padding: 0 !important;
          background: transparent !important;
          border-radius: 0 !important;
          color: #e5e7eb !important;
          font-size: 0.88rem !important;
          line-height: 1.72 !important;
          white-space: pre !important;
          -webkit-text-fill-color: #e5e7eb;
        }

        .deepdoc-chatbot-answer__inline-code {
          display: inline-flex;
          align-items: center;
          border: 1px solid color-mix(in srgb, var(--deepdoc-brand-light) 12%, var(--color-fd-border) 88%);
          border-radius: 0.6rem;
          padding: 0.12rem 0.42rem;
          background: color-mix(in srgb, white 91%, var(--deepdoc-brand-light) 9%);
          color: var(--deepdoc-brand-dark);
          font-family: 'SF Mono', 'JetBrains Mono', 'Fira Code', 'Menlo', monospace;
          font-size: 0.875em;
        }

        .deepdoc-chatbot-answer p,
        .deepdoc-chatbot-answer ul,
        .deepdoc-chatbot-answer ol,
        .deepdoc-chatbot-answer pre,
        .deepdoc-chatbot-answer blockquote,
        .deepdoc-chatbot-answer h1,
        .deepdoc-chatbot-answer h2,
        .deepdoc-chatbot-answer h3,
        .deepdoc-chatbot-answer h4 {
          margin-top: 0.75rem;
          margin-bottom: 0.75rem;
        }

        .deepdoc-chatbot-answer ul,
        .deepdoc-chatbot-answer ol {
          padding-left: 1.25rem;
        }

        .deepdoc-chatbot-answer blockquote {
          border-left: 3px solid var(--color-fd-border);
          padding-left: 0.875rem;
          color: var(--color-fd-muted-foreground);
        }

        /* Clickable citation cards */
        .deepdoc-chatbot-citation-list__clickable {
          cursor: pointer;
          transition: transform 0.15s, border-color 0.15s, box-shadow 0.15s, background 0.15s;
        }

        .deepdoc-chatbot-citation-list__clickable:hover {
          transform: translateY(-1px);
          border-color: color-mix(in srgb, var(--deepdoc-brand-primary) 50%, white 50%) !important;
          box-shadow:
            0 0 0 1px color-mix(in srgb, var(--deepdoc-brand-primary) 34%, white 66%),
            0 14px 28px rgba(193, 51, 31, 0.08);
          background:
            linear-gradient(180deg, color-mix(in srgb, var(--deepdoc-brand-light) 4%, white 96%), white);
        }

        .deepdoc-chatbot-citation-list__clickable:focus-visible {
          outline: 2px solid var(--deepdoc-brand-primary);
          outline-offset: 2px;
        }

        .deepdoc-chatbot-section-hint {
          font-weight: 400;
          font-size: 0.75rem;
          color: var(--color-fd-muted-foreground);
        }

        .deepdoc-chatbot-citation-list__row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 0.85rem;
        }

        .deepdoc-chatbot-citation-list__text {
          min-width: 0;
          flex: 1;
        }

        .deepdoc-chatbot-citation-list__action {
          flex-shrink: 0;
          display: inline-flex;
          align-items: center;
          gap: 0.35rem;
          border: 1px solid color-mix(in srgb, var(--deepdoc-brand-light) 12%, var(--color-fd-border) 88%);
          border-radius: 999px;
          padding: 0.32rem 0.56rem;
          font-size: 0.72rem;
          font-weight: 600;
          color: var(--deepdoc-brand-dark);
          background: color-mix(in srgb, white 93%, var(--deepdoc-brand-light) 7%);
        }

        .deepdoc-chatbot-citation-list__action::after {
          content: '↗';
          font-size: 0.78rem;
        }

        /* Code modal overlay */
        .deepdoc-code-modal-overlay {
          position: fixed;
          inset: 0;
          z-index: 9999;
          display: flex;
          align-items: center;
          justify-content: center;
          background:
            radial-gradient(circle at top, rgba(235, 62, 37, 0.12), transparent 30%),
            rgba(9, 11, 19, 0.6);
          backdrop-filter: blur(6px);
          animation: deepdoc-modal-fadein 0.15s ease-out;
        }

        @keyframes deepdoc-modal-fadein {
          from { opacity: 0; }
          to { opacity: 1; }
        }

        .deepdoc-code-modal {
          width: min(92vw, 64rem);
          max-height: 84vh;
          display: flex;
          flex-direction: column;
          background: #171824;
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 1.2rem;
          box-shadow: 0 30px 80px rgba(0, 0, 0, 0.5);
          overflow: hidden;
          animation: deepdoc-modal-scalein 0.15s ease-out;
        }

        @keyframes deepdoc-modal-scalein {
          from { transform: scale(0.96); opacity: 0; }
          to { transform: scale(1); opacity: 1; }
        }

        .deepdoc-code-modal__header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 1rem;
          padding: 0.95rem 1.1rem;
          background:
            linear-gradient(180deg, rgba(255, 255, 255, 0.025), rgba(255, 255, 255, 0));
          border-bottom: 1px solid rgba(255, 255, 255, 0.06);
        }
        .deepdoc-code-modal__title strong {
          display: block;
          color: #cdd6f4;
          font-size: 0.875rem;
          font-weight: 600;
          overflow-wrap: anywhere;
        }
        .deepdoc-code-modal__title span {
          display: block;
          font-size: 0.75rem;
          color: #6c7086;
          margin-top: 0.1rem;
        }
        .deepdoc-code-modal__close {
          flex-shrink: 0;
          width: 2rem;
          height: 2rem;
          display: flex;
          align-items: center;
          justify-content: center;
          border: none;
          border-radius: 0.5rem;
          background: transparent;
          color: #6c7086;
          font-size: 1rem;
          cursor: pointer;
          transition: background 0.12s, color 0.12s;
        }
        .deepdoc-code-modal__close:hover {
          background: rgba(255, 255, 255, 0.08);
          color: #cdd6f4;
        }

        /* Metadata strip */
        .deepdoc-code-modal__meta {
          display: flex;
          flex-direction: column;
          gap: 0.4rem;
          padding: 0.7rem 1.1rem;
          background: #11131c;
          border-bottom: 1px solid rgba(255, 255, 255, 0.06);
        }
        .deepdoc-code-modal__meta-row {
          display: flex;
          align-items: baseline;
          gap: 0.5rem;
          flex-wrap: wrap;
        }
        .deepdoc-code-modal__meta-label {
          flex-shrink: 0;
          font-size: 0.68rem;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.06em;
          color: #585b70;
          min-width: 4.5rem;
        }
        .deepdoc-code-modal__meta-tags {
          display: flex;
          flex-wrap: wrap;
          gap: 0.3rem;
        }
        .deepdoc-code-modal__tag {
          display: inline-block;
          padding: 0.12rem 0.5rem;
          border-radius: 999px;
          font-size: 0.72rem;
          font-family: 'SF Mono', 'Fira Code', 'JetBrains Mono', 'Menlo', monospace;
          background: rgba(137, 180, 250, 0.12);
          color: #89b4fa;
          border: 1px solid rgba(137, 180, 250, 0.15);
        }
        .deepdoc-code-modal__tag--dim {
          background: rgba(108, 112, 134, 0.1);
          color: #a6adc8;
          border-color: rgba(108, 112, 134, 0.15);
        }
        .deepdoc-code-modal__sig {
          font-size: 0.76rem;
          font-family: 'SF Mono', 'Fira Code', 'JetBrains Mono', 'Menlo', monospace;
          color: #a6e3a1;
          background: rgba(166, 227, 161, 0.08);
          padding: 0.1rem 0.45rem;
          border-radius: 0.3rem;
          border: 1px solid rgba(166, 227, 161, 0.12);
        }

        /* Code block */
        .deepdoc-code-modal__body {
          flex: 1;
          overflow: auto;
          padding: 0;
          background:
            linear-gradient(180deg, rgba(255, 255, 255, 0.02), rgba(255, 255, 255, 0)),
            #181a27;
        }
        .deepdoc-code-modal__table {
          width: 100%;
          border-collapse: collapse;
          border-spacing: 0;
        }
        .deepdoc-code-modal__line:hover {
          background: rgba(255, 255, 255, 0.03);
        }
        .deepdoc-code-modal__gutter {
          position: sticky;
          left: 0;
          padding: 0 0.75rem 0 1rem;
          text-align: right;
          font-family: 'SF Mono', 'Fira Code', 'JetBrains Mono', 'Menlo', monospace;
          font-size: 0.75rem;
          line-height: 1.7;
          color: #45475a;
          background: #1e1e2e;
          user-select: none;
          white-space: nowrap;
          border-right: 1px solid rgba(255, 255, 255, 0.04);
        }
        .deepdoc-code-modal__code {
          padding: 0 1rem;
          white-space: pre;
          font-family: 'SF Mono', 'Fira Code', 'JetBrains Mono', 'Menlo', monospace;
          font-size: 0.8125rem;
          line-height: 1.7;
          color: #cdd6f4;
          tab-size: 4;
        }
        .deepdoc-code-modal__code pre {
          margin: 0;
          padding: 0;
          background: none;
          border: none;
          font: inherit;
          color: inherit;
          white-space: pre;
        }
        .deepdoc-code-modal__table tr:first-child td {
          padding-top: 0.6rem;
        }
        .deepdoc-code-modal__table tr:last-child td {
          padding-bottom: 0.6rem;
        }

        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-page__back {
          color: rgba(226, 232, 240, 0.76);
        }

        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-page__back:hover {
          color: #f8d1ca;
        }

        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-page__eyebrow,
        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-dock__eyebrow,
        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-panel__section-title,
        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-citation-list__action,
        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-answer__inline-code {
          color: #ffd7cf;
        }

        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-page__hero h1 {
          color: #fff5f2;
        }

        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-page__hero p,
        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-dock__hint,
        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-panel__question,
        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-panel__empty,
        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-citation-list span,
        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-section-hint {
          color: rgba(226, 232, 240, 0.72);
        }

        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-page__chip {
          border-color: rgba(255, 255, 255, 0.1);
          background: rgba(255, 237, 233, 0.08);
          color: #ffcabf;
        }

        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-dock,
        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-panel,
        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-sidebar {
          border-color: rgba(255, 255, 255, 0.08);
          background:
            linear-gradient(180deg, rgba(255, 255, 255, 0.03), rgba(255, 255, 255, 0.015)),
            #14151f;
          box-shadow:
            0 24px 60px rgba(0, 0, 0, 0.34),
            inset 0 1px 0 rgba(255, 255, 255, 0.025);
        }

        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-panel__header,
        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-sidebar__header {
          border-bottom-color: rgba(255, 255, 255, 0.08);
        }

        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-dock__input,
        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-panel__input {
          border-color: rgba(255, 255, 255, 0.08);
          background: #10111a;
          color: #f8fafc;
          box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
        }

        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-dock__input::placeholder,
        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-panel__input::placeholder {
          color: rgba(226, 232, 240, 0.42);
        }

        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-panel__empty {
          border-color: rgba(255, 255, 255, 0.12);
          background: rgba(255, 255, 255, 0.02);
        }

        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-skeleton__block,
        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-skeleton__line,
        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-skeleton__card {
          background: rgba(255, 255, 255, 0.07);
        }

        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-skeleton__block::after,
        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-skeleton__line::after,
        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-skeleton__card::after {
          background: linear-gradient(
            90deg,
            transparent 0%,
            rgba(255, 255, 255, 0.12) 50%,
            transparent 100%
          );
        }

        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-citation-list li {
          border-color: rgba(255, 255, 255, 0.08);
          background:
            linear-gradient(180deg, rgba(255, 255, 255, 0.03), rgba(255, 255, 255, 0.015)),
            #11131c;
        }

        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-citation-list strong {
          color: #fff1ed;
        }

        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-citation-list__clickable:hover {
          border-color: rgba(255, 202, 191, 0.42) !important;
          box-shadow:
            0 0 0 1px rgba(255, 202, 191, 0.16),
            0 14px 28px rgba(0, 0, 0, 0.24);
          background:
            linear-gradient(180deg, rgba(255, 255, 255, 0.045), rgba(255, 255, 255, 0.02)),
            #141722;
        }

        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-citation-list__action {
          border-color: rgba(255, 255, 255, 0.08);
          background: rgba(255, 237, 233, 0.06);
        }

        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-answer__inline-code {
          border-color: rgba(255, 255, 255, 0.08);
          background: rgba(255, 237, 233, 0.08);
        }

        :is(.dark, [data-theme='dark']) .deepdoc-chatbot-answer blockquote {
          border-left-color: rgba(255, 255, 255, 0.14);
          color: rgba(226, 232, 240, 0.78);
        }

        @media (max-width: 960px) {
          .deepdoc-chatbot-page__grid {
            grid-template-columns: minmax(0, 1fr);
          }

          .deepdoc-chatbot-sidebar {
            position: static;
          }
        }

        @media (max-width: 640px) {
          body {
            padding-bottom: 9.5rem;
          }

          .deepdoc-chatbot-shell {
            width: calc(100vw - 1rem);
            bottom: 0.5rem;
          }

          .deepdoc-chatbot-dock {
            padding: 0.8rem;
            border-radius: 1.2rem;
          }

          .deepdoc-chatbot-dock__meta,
          .deepdoc-chatbot-dock__row,
          .deepdoc-chatbot-page__hero {
            display: grid;
            grid-template-columns: minmax(0, 1fr);
          }

          .deepdoc-chatbot-dock__hint {
            max-width: none;
            text-align: left;
          }

          .deepdoc-chatbot-dock__submit,
          .deepdoc-chatbot-panel__button {
            width: 100%;
            justify-content: center;
          }

          .deepdoc-chatbot-page {
            width: min(calc(100vw - 1rem), 100%);
            padding-top: 1.35rem;
          }

          .deepdoc-chatbot-panel__header,
          .deepdoc-chatbot-panel__body,
          .deepdoc-chatbot-sidebar {
            padding-left: 1rem;
            padding-right: 1rem;
          }
        }
        """
    )
    return (
        css.replace("__PRIMARY__", primary)
        .replace("__LIGHT__", light)
        .replace("__DARK__", dark)
    )


def _search_route_ts() -> str:
    return dedent(
        """\
        import { docsSource } from '@/lib/source';
        import { createFromSource } from 'fumadocs-core/search/server';

        export const revalidate = false;
        export const { staticGET: GET } = createFromSource(docsSource);
        """
    )


def _docs_layout_tsx() -> str:
    return dedent(
        """\
        import { DocsLayout } from 'fumadocs-ui/layouts/docs';
        import { layoutOptions } from '@/lib/layout-options';
        import { pageTree } from '@/lib/page-tree.generated';
        import type { ReactNode } from 'react';

        export default function Layout({ children }: { children: ReactNode }) {
          return (
            <DocsLayout tree={pageTree} {...layoutOptions}>
              {children}
            </DocsLayout>
          );
        }
        """
    )


def _docs_page_tsx() -> str:
    return dedent(
        """\
        import { notFound } from 'next/navigation';
        import { DocsBody, DocsPage } from 'fumadocs-ui/page';
        import { docsSource } from '@/lib/source';
        import { getMDXComponents } from '@/mdx-components';
        import type { ComponentType } from 'react';
        import type { TOCItemType } from 'fumadocs-core/server';

        export function generateStaticParams() {
          return docsSource.generateParams();
        }

        export default async function Page(props: {
          params: Promise<{ slug?: string[] }>;
        }) {
          const params = await props.params;
          const page = docsSource.getPage(params.slug ?? []);
          if (!page) notFound();

          const MDX = (page.data as { body: ComponentType<{ components?: ReturnType<typeof getMDXComponents> }> }).body;
          const toc = (page.data as { toc?: TOCItemType[] }).toc;

          return (
            <DocsPage toc={toc}>
              <DocsBody>
                <MDX components={getMDXComponents()} />
              </DocsBody>
            </DocsPage>
          );
        }
        """
    )


def _api_layout_tsx() -> str:
    return _docs_layout_tsx()


def _api_page_tsx() -> str:
    return dedent(
        """\
        import { notFound } from 'next/navigation';
        import { DocsBody, DocsPage } from 'fumadocs-ui/page';
        import { APIPage } from '@/components/api-page';
        import { generateAPIParams, getAPIPage } from '@/lib/openapi';

        export function generateStaticParams() {
          return generateAPIParams();
        }

        export default async function Page(props: {
          params: Promise<{ slug?: string[] }>;
        }) {
          const params = await props.params;
          const page = getAPIPage(params.slug ?? []);
          if (!page || page.data.type !== 'openapi') notFound();

          return (
            <DocsPage full>
              <DocsBody>
                <APIPage {...page.data.getAPIPageProps()} />
              </DocsBody>
            </DocsPage>
          );
        }
        """
    )


def _chatbot_ask_page_tsx() -> str:
    return dedent(
        """\
        import { Suspense } from 'react';
        import { ChatbotPanel } from '@/components/chatbot-panel';

        export default function AskPage() {
          return (
            <Suspense fallback={null}>
              <ChatbotPanel />
            </Suspense>
          );
        }
        """
    )


def _api_page_component_tsx() -> str:
    return dedent(
        """\
        import { openapi } from '@/lib/openapi';
        import { APIPage as FumadocsAPIPage } from 'fumadocs-openapi/ui';
        import type { ApiPageProps } from 'fumadocs-openapi/ui';

        function EmptyAPIPage(_: ApiPageProps) {
          return null;
        }

        export function APIPage(props: ApiPageProps) {
          if (!openapi) return EmptyAPIPage(props);
          return <FumadocsAPIPage {...openapi.getAPIPageProps(props)} />;
        }
        """
    )


def _api_page_client_tsx() -> str:
    return dedent(
        """\
        const client = {};

        export default client;
        """
    )


def _mermaid_component_tsx() -> str:
    return dedent(
        """\
        'use client';

        import { use, useEffect, useId, useState } from 'react';
        import { useTheme } from 'next-themes';

        export function Mermaid({ chart }: { chart: string }) {
          const [mounted, setMounted] = useState(false);

          useEffect(() => {
            setMounted(true);
          }, []);

          if (!mounted) return null;
          return <MermaidContent chart={chart} />;
        }

        const cache = new Map<string, Promise<unknown>>();

        function cachePromise<T>(key: string, setPromise: () => Promise<T>): Promise<T> {
          const cached = cache.get(key);
          if (cached) return cached as Promise<T>;

          const promise = setPromise();
          cache.set(key, promise);
          return promise;
        }

        function MermaidContent({ chart }: { chart: string }) {
          const id = useId();
          const { resolvedTheme } = useTheme();
          const { default: mermaid } = use(
            cachePromise('mermaid', () => import('mermaid')),
          );

          mermaid.initialize({
            startOnLoad: false,
            securityLevel: 'loose',
            fontFamily: 'inherit',
            themeCSS: 'margin: 1.5rem auto 0;',
            theme: resolvedTheme === 'dark' ? 'dark' : 'default',
          });

          const { svg, bindFunctions } = use(
            cachePromise(`${chart}-${resolvedTheme}`, () => {
              return mermaid.render(id, chart.replaceAll('\\\\n', '\\n'));
            }),
          );

          return (
            <div
              ref={(container) => {
                if (container) bindFunctions?.(container);
              }}
              dangerouslySetInnerHTML={{ __html: svg }}
            />
          );
        }
        """
    )


def _source_ts() -> str:
    return dedent(
        """\
        import { resolveFiles } from 'fumadocs-mdx';
        import { loader } from 'fumadocs-core/source';
        import { docs, meta } from '@/.source';

        export const docsSource = loader({
          baseUrl: '/',
          source: {
            files: resolveFiles({ docs, meta }),
          },
        });
        """
    )


def _layout_options_ts(project_name: str, repo_url: str) -> str:
    links = (
        f"[{{ text: 'GitHub', url: '{repo_url}' }}]"
        if repo_url
        else "[]"
    )
    return dedent(
        f"""\
        export const layoutOptions = {{
          nav: {{
            title: '{project_name}',
            url: '/',
          }},
          links: {links},
        }};
        """
    )


def _openapi_ts() -> str:
    return dedent(
        """\
        import fs from 'node:fs';
        import path from 'node:path';
        import { createOpenAPI } from 'fumadocs-openapi/server';
        import type { ApiPageProps } from 'fumadocs-openapi/ui';

        const schemaDir = path.join(process.cwd(), 'openapi');
        const schemaFiles = fs.existsSync(schemaDir)
          ? fs
              .readdirSync(schemaDir)
              .filter(
                (file) =>
                  /\\.(json|ya?ml)$/i.test(file) &&
                  !/^manifest\\.json$/i.test(file) &&
                  /^(openapi|swagger)(\\.|$)/i.test(file),
              )
              .map((file) => path.join(schemaDir, file))
          : [];

        export const openapi =
          schemaFiles.length > 0
            ? createOpenAPI({
                input: schemaFiles,
              })
            : null;

        type ManifestEntry = {
          slug: string;
          title: string;
          method: string;
          path: string;
        };

        const manifestPath = path.join(schemaDir, 'manifest.json');
        const apiManifest: ManifestEntry[] = fs.existsSync(manifestPath)
          ? JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
          : [];

        export function generateAPIParams() {
          return apiManifest.map((entry) => ({
            slug: entry.slug.split('/').filter(Boolean),
          }));
        }

        export function getAPIPage(slugs: string[]) {
          if (!openapi || schemaFiles.length === 0) return null;

          const slug = slugs.join('/');
          const entry = apiManifest.find((item) => item.slug === slug);
          if (!entry) return null;

          return {
            url: `/api/${entry.slug}`,
            data: {
              type: 'openapi' as const,
              title: entry.title,
              getAPIPageProps(): ApiPageProps {
                return {
                  document: schemaFiles[0],
                  hasHead: true,
                  operations: [
                    {
                      path: entry.path,
                      method: entry.method.toLowerCase() as Lowercase<ManifestEntry['method']>,
                    },
                  ],
                };
              },
            },
          };
        }
        """
    )


def _chatbot_config_ts(repo_root: Path, cfg: dict[str, Any]) -> str:
    chatbot_cfg = cfg.get("chatbot", {})
    return dedent(
        f"""\
        const envApiBaseUrl = process.env.NEXT_PUBLIC_DEEPDOC_CHATBOT_BASE_URL?.trim() ?? '';

        export const chatbotConfig = {{
          enabled: {str(bool(chatbot_cfg.get("enabled", False))).lower()},
          apiBaseUrl: envApiBaseUrl || {chatbot_site_api_base_url(cfg)!r},
        }};
        """
    )


def _chatbot_toggle_tsx() -> str:
    return dedent(
        """\
        'use client';

        import { startTransition, useState, type FormEvent, type KeyboardEvent } from 'react';
        import { usePathname, useRouter } from 'next/navigation';
        import { chatbotConfig } from '@/lib/chatbot-config';

        function buildAskUrl(question: string, from: string) {
          const params = new URLSearchParams({
            q: question,
            from: from || '/',
          });
          return `/ask?${params.toString()}`;
        }

        export function ChatbotToggle() {
          const pathname = usePathname();
          const router = useRouter();
          const [question, setQuestion] = useState('');

          if (!chatbotConfig.enabled || pathname === '/ask') return null;

          function submit(event?: FormEvent<HTMLFormElement>) {
            event?.preventDefault();
            const trimmed = question.trim();
            if (!trimmed) return;
            setQuestion('');
            startTransition(() => {
              router.push(buildAskUrl(trimmed, pathname || '/'));
            });
          }

          return (
            <div className="deepdoc-chatbot-shell">
              <form className="deepdoc-chatbot-dock" onSubmit={submit}>
                <div className="deepdoc-chatbot-dock__meta">
                  <div className="min-w-0">
                    <p className="deepdoc-chatbot-dock__eyebrow">Ask the codebase</p>
                    <p className="text-sm font-medium text-fd-muted-foreground">
                      Open a dedicated answer page with grounded citations.
                    </p>
                  </div>
                  <p className="deepdoc-chatbot-dock__hint">
                    Ask from any docs page and keep reading without losing context.
                  </p>
                </div>
                <div className="deepdoc-chatbot-dock__row">
                  <textarea
                    className="deepdoc-chatbot-dock__input text-sm"
                    onChange={(event) => setQuestion(event.target.value)}
                    onKeyDown={(event: KeyboardEvent<HTMLTextAreaElement>) => {
                      if (event.nativeEvent.isComposing) return;
                      if (event.key === 'Enter' && !event.shiftKey) {
                        event.preventDefault();
                        event.currentTarget.form?.requestSubmit();
                      }
                    }}
                    placeholder="Where is auth handled? How is deployment configured?"
                    rows={1}
                    value={question}
                  />
                  <button className="deepdoc-chatbot-dock__submit text-sm font-semibold" type="submit">
                    Ask
                  </button>
                </div>
              </form>
            </div>
          );
        }
        """
    )


def _chatbot_panel_tsx() -> str:
    return dedent(
        """\
        'use client';

        import Link from 'next/link';
        import { isValidElement, startTransition, useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from 'react';
        import { useRouter, useSearchParams } from 'next/navigation';
        import ReactMarkdown from 'react-markdown';
        import { chatbotConfig } from '@/lib/chatbot-config';

        type CitationEntry = {
          file_path: string;
          start_line: number;
          end_line: number;
          text?: string;
          language?: string;
          symbol_names?: string[];
          artifact_type?: string;
        };

        type ChatResponse = {
          answer: string;
          code_citations: CitationEntry[];
          artifact_citations: CitationEntry[];
          doc_links: Array<{
            title: string;
            url: string;
            doc_path: string;
          }>;
          used_chunks: number;
        };

        type ChatHistoryItem = {
          role: 'user' | 'assistant';
          content: string;
        };

        function buildAskUrl(question: string, from: string) {
          const params = new URLSearchParams({
            q: question,
            from: from || '/',
          });
          return `/ask?${params.toString()}`;
        }

        function formatLines(startLine: number, endLine: number) {
          return startLine === endLine ? `Line ${startLine}` : `Lines ${startLine}-${endLine}`;
        }

        function extractCodeLanguage(node: ReactNode): string {
          if (!isValidElement(node)) return '';
          const props = node.props as { className?: string };
          const className = typeof props.className === 'string' ? props.className : '';
          const match = className.match(/language-([\\w-]+)/);
          return match?.[1] ?? '';
        }

        function AnswerPre({ children }: { children?: ReactNode }) {
          const language = extractCodeLanguage(children) || 'code';

          return (
            <div className="deepdoc-chatbot-answer__pre">
              <div className="deepdoc-chatbot-answer__pre-header">
                <span className="deepdoc-chatbot-answer__pre-dots" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </span>
                <span className="deepdoc-chatbot-answer__pre-label">{language}</span>
              </div>
              <pre>{children}</pre>
            </div>
          );
        }

        type ParsedChunk = {
          code: string;
          symbols: string[];
          signature: string;
          imports: string[];
        };

        function parseChunkText(text: string): ParsedChunk {
          const sep = text.indexOf('\\n\\n');
          const headerBlock = sep !== -1 ? text.slice(0, sep) : '';
          const code = sep !== -1 ? text.slice(sep + 2).trim() : text.trim();

          let symbols: string[] = [];
          let signature = '';
          let imports: string[] = [];

          for (const line of headerBlock.split('\\n')) {
            if (line.startsWith('Symbols: ')) {
              symbols = line.slice(9).split(',').map(s => s.trim()).filter(Boolean);
            } else if (line.startsWith('Signature: ')) {
              signature = line.slice(11).trim();
            } else if (line.startsWith('Imports: ')) {
              imports = line.slice(9).split(',').map(s => s.trim()).filter(Boolean);
            }
          }

          return { code, symbols, signature, imports };
        }

        function inferLanguage(filePath: string): string {
          const ext = filePath.split('.').pop()?.toLowerCase() || '';
          const map: Record<string, string> = {
            py: 'python', ts: 'typescript', tsx: 'tsx', js: 'javascript',
            jsx: 'jsx', rs: 'rust', go: 'go', java: 'java', rb: 'ruby',
            yml: 'yaml', yaml: 'yaml', json: 'json', md: 'markdown',
            sql: 'sql', sh: 'bash', bash: 'bash', css: 'css', html: 'html',
            dockerfile: 'dockerfile', toml: 'toml', xml: 'xml',
          };
          return map[ext] || 'text';
        }

        function CodeModal({
          citation,
          onClose,
        }: {
          citation: CitationEntry;
          onClose: () => void;
        }) {
          const lang = citation.language || inferLanguage(citation.file_path);
          const parsed = parseChunkText(citation.text || '');
          const hasMeta = parsed.symbols.length > 0 || parsed.signature || parsed.imports.length > 0;

          useEffect(() => {
            const prev = document.body.style.overflow;
            document.body.style.overflow = 'hidden';
            function handleKey(e: globalThis.KeyboardEvent) {
              if (e.key === 'Escape') onClose();
            }
            document.addEventListener('keydown', handleKey);
            return () => {
              document.body.style.overflow = prev;
              document.removeEventListener('keydown', handleKey);
            };
          }, [onClose]);

          const codeLines = parsed.code.split('\\n');
          const maxNum = citation.start_line + codeLines.length - 1;
          const gutterW = String(maxNum).length;

          return (
            <div className="deepdoc-code-modal-overlay" onClick={onClose}>
              <div className="deepdoc-code-modal" onClick={(e) => e.stopPropagation()}>
                <div className="deepdoc-code-modal__header">
                  <div className="deepdoc-code-modal__title">
                    <strong>{citation.file_path}</strong>
                    <span>{formatLines(citation.start_line, citation.end_line)}{lang ? ` · ${lang}` : ''}</span>
                  </div>
                  <button className="deepdoc-code-modal__close" onClick={onClose} aria-label="Close">✕</button>
                </div>

                {hasMeta ? (
                  <div className="deepdoc-code-modal__meta">
                    {parsed.symbols.length > 0 ? (
                      <div className="deepdoc-code-modal__meta-row">
                        <span className="deepdoc-code-modal__meta-label">Symbols</span>
                        <span className="deepdoc-code-modal__meta-tags">
                          {parsed.symbols.map(s => <span key={s} className="deepdoc-code-modal__tag">{s}</span>)}
                        </span>
                      </div>
                    ) : null}
                    {parsed.signature ? (
                      <div className="deepdoc-code-modal__meta-row">
                        <span className="deepdoc-code-modal__meta-label">Signature</span>
                        <code className="deepdoc-code-modal__sig">{parsed.signature}</code>
                      </div>
                    ) : null}
                    {parsed.imports.length > 0 ? (
                      <div className="deepdoc-code-modal__meta-row">
                        <span className="deepdoc-code-modal__meta-label">Imports</span>
                        <span className="deepdoc-code-modal__meta-tags">
                          {parsed.imports.map(s => <span key={s} className="deepdoc-code-modal__tag deepdoc-code-modal__tag--dim">{s}</span>)}
                        </span>
                      </div>
                    ) : null}
                  </div>
                ) : null}

                <div className="deepdoc-code-modal__body">
                  <table className="deepdoc-code-modal__table">
                    <tbody>
                      {codeLines.map((line, i) => (
                        <tr key={i} className="deepdoc-code-modal__line">
                          <td className="deepdoc-code-modal__gutter">
                            {String(citation.start_line + i).padStart(gutterW, '\\u00a0')}
                          </td>
                          <td className="deepdoc-code-modal__code">
                            <pre>{line || '\\n'}</pre>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          );
        }

        function ChatbotLoadingSkeleton() {
          return (
            <>
              <div className="deepdoc-chatbot-skeleton">
                <div className="deepdoc-chatbot-skeleton__line deepdoc-chatbot-skeleton__line--sm" />
                <div className="deepdoc-chatbot-skeleton__line deepdoc-chatbot-skeleton__line--full" />
                <div className="deepdoc-chatbot-skeleton__line deepdoc-chatbot-skeleton__line--lg" />
                <div className="deepdoc-chatbot-skeleton__block" />
                <div className="deepdoc-chatbot-skeleton__line deepdoc-chatbot-skeleton__line--full" />
                <div className="deepdoc-chatbot-skeleton__line deepdoc-chatbot-skeleton__line--lg" />
                <div className="deepdoc-chatbot-skeleton__line deepdoc-chatbot-skeleton__line--md" />
              </div>
            </>
          );
        }

        function ChatbotSidebarSkeleton() {
          return (
            <div className="deepdoc-chatbot-skeleton">
              <div className="deepdoc-chatbot-skeleton__line deepdoc-chatbot-skeleton__line--md" />
              <div className="deepdoc-chatbot-skeleton__cards">
                <div className="deepdoc-chatbot-skeleton__card" />
                <div className="deepdoc-chatbot-skeleton__card" />
                <div className="deepdoc-chatbot-skeleton__card" />
              </div>
              <div className="deepdoc-chatbot-skeleton__line deepdoc-chatbot-skeleton__line--sm" />
            </div>
          );
        }

        export function ChatbotPanel() {
          const router = useRouter();
          const searchParams = useSearchParams();
          const question = searchParams.get('q')?.trim() ?? '';
          const from = searchParams.get('from')?.trim() || '/';
          const [draft, setDraft] = useState('');
          const [activeQuestion, setActiveQuestion] = useState(question);
          const [loading, setLoading] = useState(false);
          const [error, setError] = useState('');
          const [response, setResponse] = useState<ChatResponse | null>(null);
          const [history, setHistory] = useState<ChatHistoryItem[]>([]);
          const [loadedQuestion, setLoadedQuestion] = useState('');
          const [modalCitation, setModalCitation] = useState<CitationEntry | null>(null);
          const latestRequestIdRef = useRef(0);

          useEffect(() => {
            if (!question) {
              latestRequestIdRef.current += 1;
              setActiveQuestion('');
              setLoading(false);
              setError('');
              setResponse(null);
              setHistory([]);
              setLoadedQuestion('');
              return;
            }
            if (question === loadedQuestion) return;
            void askQuestion(question, []);
          }, [question, loadedQuestion]);

          async function askQuestion(nextQuestion: string, nextHistory: ChatHistoryItem[]) {
            if (!nextQuestion.trim()) return;
            if (!chatbotConfig.apiBaseUrl) {
              setResponse(null);
              setError('Chatbot backend URL is not configured.');
              setLoading(false);
              return;
            }
            const requestId = latestRequestIdRef.current + 1;
            latestRequestIdRef.current = requestId;
            setLoadedQuestion(nextQuestion);
            setLoading(true);
            setError('');
            setResponse(null);
            try {
              const res = await fetch(`${chatbotConfig.apiBaseUrl}/query`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  question: nextQuestion,
                  history: nextHistory,
                }),
              });
              if (!res.ok) {
                throw new Error(`Request failed with ${res.status}`);
              }
              const data = (await res.json()) as ChatResponse;
              if (latestRequestIdRef.current != requestId) {
                return;
              }
              setActiveQuestion(nextQuestion);
              setResponse(data);
              setHistory([
                ...nextHistory,
                { role: 'user', content: nextQuestion },
                { role: 'assistant', content: data.answer },
              ]);
            } catch (err) {
              if (latestRequestIdRef.current != requestId) {
                return;
              }
              setError(err instanceof Error ? err.message : 'Chatbot unavailable');
            } finally {
              if (latestRequestIdRef.current == requestId) {
                setLoading(false);
              }
            }
          }

          function submit(event?: FormEvent<HTMLFormElement>) {
            event?.preventDefault();
            const trimmed = draft.trim();
            if (!trimmed) return;
            const nextHistory = activeQuestion && response ? history.slice(-4) : [];
            setDraft('');
            void askQuestion(trimmed, nextHistory);
            startTransition(() => {
              router.replace(buildAskUrl(trimmed, from));
            });
          }

          return (
            <div className="deepdoc-chatbot-page">
              <Link className="deepdoc-chatbot-page__back" href={from}>
                <span aria-hidden="true">←</span>
                <span>Back to docs</span>
              </Link>

              <div className="deepdoc-chatbot-page__hero">
                <div>
                  <p className="deepdoc-chatbot-page__eyebrow">Grounded answer</p>
                  <h1>{question || 'Ask anything about this codebase'}</h1>
                  <p>
                    {question
                      ? 'Results are generated from indexed code, artifacts, and docs so the answer can stay anchored to the repository.'
                      : 'Ask a question to open a cleaner research-style answer view with source references and suggested follow-up reading.'}
                  </p>
                </div>
                {response ? (
                  <span className="deepdoc-chatbot-page__chip">{response.used_chunks} retrieved chunks</span>
                ) : null}
              </div>

              <div className="deepdoc-chatbot-page__grid">
                <section className="deepdoc-chatbot-panel">
                  <div className="deepdoc-chatbot-panel__header">
                    <p className="deepdoc-chatbot-panel__question">
                      {question ? 'Question' : 'Ready when you are'}
                    </p>
                    {question ? (
                      <h2 className="mt-2 text-2xl font-semibold tracking-tight text-fd-foreground">{question}</h2>
                    ) : null}
                  </div>
                  <div className="deepdoc-chatbot-panel__body">
                    {loading ? (
                      <ChatbotLoadingSkeleton />
                    ) : error ? (
                      <div className="deepdoc-chatbot-panel__empty text-red-600">{error}</div>
                    ) : response ? (
                      <div className="text-sm">
                        <h3 className="deepdoc-chatbot-panel__section-title mb-3 text-base font-semibold">Answer</h3>
                        <div className="deepdoc-chatbot-answer prose prose-sm max-w-none dark:prose-invert">
                          <ReactMarkdown
                            components={{
                              pre({ children }) {
                                return <AnswerPre>{children}</AnswerPre>;
                              },
                              code(props) {
                                const { className, children, ...rest } = props;
                                const content = String(children ?? '');
                                const isInline = !className && !content.includes('\\n');
                                if (isInline) {
                                  return (
                                    <code
                                      {...rest}
                                      className="deepdoc-chatbot-answer__inline-code"
                                    >
                                      {children}
                                    </code>
                                  );
                                }
                                return (
                                  <code {...rest} className={className}>
                                    {children}
                                  </code>
                                );
                              },
                            }}
                          >
                            {response.answer}
                          </ReactMarkdown>
                        </div>
                      </div>
                    ) : (
                      <div className="deepdoc-chatbot-panel__empty">
                        Ask a question below and this page will turn into a focused answer workspace with citations and related docs.
                      </div>
                    )}
                  </div>
                </section>

                <aside className="deepdoc-chatbot-sidebar">
                  <div className="deepdoc-chatbot-sidebar__header">
                    <h2 className="text-sm font-semibold text-fd-foreground">Supporting context</h2>
                    <p className="mt-2 text-sm text-fd-muted-foreground">
                      Code and docs referenced by the current answer appear here.
                    </p>
                  </div>

                  {loading ? <ChatbotSidebarSkeleton /> : null}

                  {!loading && response?.code_citations.length ? (
                    <div className="mb-5">
                      <h3 className="deepdoc-chatbot-panel__section-title mb-3 text-sm font-semibold">
                        Code citations
                        <span className="deepdoc-chatbot-section-hint"> — click to view</span>
                      </h3>
                      <ul className="deepdoc-chatbot-citation-list">
                        {response.code_citations.map((citation) => (
                          <li
                            key={`${citation.file_path}-${citation.start_line}`}
                            className={citation.text ? 'deepdoc-chatbot-citation-list__clickable' : ''}
                            onClick={() => citation.text && setModalCitation(citation)}
                            role={citation.text ? 'button' : undefined}
                            tabIndex={citation.text ? 0 : undefined}
                            onKeyDown={(e) => {
                              if (citation.text && (e.key === 'Enter' || e.key === ' ')) {
                                e.preventDefault();
                                setModalCitation(citation);
                              }
                            }}
                          >
                            <div className="deepdoc-chatbot-citation-list__row">
                              <div className="deepdoc-chatbot-citation-list__text">
                                <strong>{citation.file_path}</strong>
                                <span>{formatLines(citation.start_line, citation.end_line)}</span>
                              </div>
                              {citation.text ? (
                                <span className="deepdoc-chatbot-citation-list__action">Preview</span>
                              ) : null}
                            </div>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}

                  {!loading && response?.artifact_citations.length ? (
                    <div className="mb-5">
                      <h3 className="deepdoc-chatbot-panel__section-title mb-3 text-sm font-semibold">
                        Artifact citations
                        <span className="deepdoc-chatbot-section-hint"> — click to view</span>
                      </h3>
                      <ul className="deepdoc-chatbot-citation-list">
                        {response.artifact_citations.map((citation) => (
                          <li
                            key={`${citation.file_path}-${citation.start_line}`}
                            className={citation.text ? 'deepdoc-chatbot-citation-list__clickable' : ''}
                            onClick={() => citation.text && setModalCitation(citation)}
                            role={citation.text ? 'button' : undefined}
                            tabIndex={citation.text ? 0 : undefined}
                            onKeyDown={(e) => {
                              if (citation.text && (e.key === 'Enter' || e.key === ' ')) {
                                e.preventDefault();
                                setModalCitation(citation);
                              }
                            }}
                          >
                            <div className="deepdoc-chatbot-citation-list__row">
                              <div className="deepdoc-chatbot-citation-list__text">
                                <strong>{citation.file_path}</strong>
                                <span>{formatLines(citation.start_line, citation.end_line)}</span>
                              </div>
                              {citation.text ? (
                                <span className="deepdoc-chatbot-citation-list__action">Preview</span>
                              ) : null}
                            </div>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}

                  {!loading && response?.doc_links.length ? (
                    <div>
                      <h3 className="deepdoc-chatbot-panel__section-title mb-3 text-sm font-semibold">Read next</h3>
                      <ul className="deepdoc-chatbot-citation-list">
                        {response.doc_links.map((link) => (
                          <li key={link.url}>
                            <strong>{link.title}</strong>
                            <span>{link.doc_path}</span>
                            <Link className="mt-2 inline-flex text-sm underline" href={link.url}>
                              Open docs
                            </Link>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}

                  {!response && !loading ? (
                    <div className="deepdoc-chatbot-panel__empty">
                      Ask a question to populate this sidebar with citations and suggested documentation.
                    </div>
                  ) : null}
                </aside>
              </div>

              {modalCitation ? (
                <CodeModal
                  citation={modalCitation}
                  onClose={() => setModalCitation(null)}
                />
              ) : null}

              <div className="deepdoc-chatbot-shell">
                <form className="deepdoc-chatbot-dock" onSubmit={submit}>
                  <div className="deepdoc-chatbot-dock__meta">
                    <div className="min-w-0">
                      <p className="deepdoc-chatbot-dock__eyebrow">
                        {response ? 'Ask a follow-up question' : 'Ask the codebase'}
                      </p>
                      <p className="text-sm font-medium text-fd-muted-foreground">
                        {response
                          ? 'Stay on this page and keep the answer flow going.'
                          : 'Start with a question about architecture, files, or behavior.'}
                      </p>
                    </div>
                  </div>
                  <div className="deepdoc-chatbot-dock__row">
                    <textarea
                      className="deepdoc-chatbot-dock__input text-sm"
                      onChange={(event) => setDraft(event.target.value)}
                      onKeyDown={(event: KeyboardEvent<HTMLTextAreaElement>) => {
                        if (event.nativeEvent.isComposing) return;
                        if (event.key === 'Enter' && !event.shiftKey) {
                          event.preventDefault();
                          event.currentTarget.form?.requestSubmit();
                        }
                      }}
                      placeholder="Ask a follow-up question"
                      rows={1}
                      value={draft}
                    />
                    <button
                      className="deepdoc-chatbot-dock__submit text-sm font-semibold"
                      disabled={loading}
                      type="submit"
                    >
                      {loading ? 'Thinking...' : 'Ask'}
                    </button>
                  </div>
                </form>
              </div>
            </div>
          );
        }
        """
    )
