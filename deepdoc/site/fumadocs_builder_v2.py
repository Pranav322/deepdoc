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
    _ensure_landing_page(output_dir, project_name, plan)

    docs_dir_relative = os.path.relpath(output_dir, repo_root / "site").replace("\\", "/")
    page_tree = _build_page_tree_from_plan(plan, output_dir, project_name, has_openapi)

    _ensure_app_scaffold(repo_root, project_name, repo_url, docs_dir_relative, cfg)
    _write_page_tree(repo_root, page_tree)
    _write_static_assets(repo_root)
    _cleanup_legacy_artifacts(repo_root)


def _ensure_app_scaffold(
    repo_root: Path,
    project_name: str,
    repo_url: str,
    docs_dir_relative: str,
    cfg: dict[str, Any],
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
        site_dir / "mdx-components.tsx": _mdx_components_tsx(),
        site_dir / "app" / "layout.tsx": _app_layout_tsx(project_name),
        site_dir / "app" / "global.css": _global_css(cfg),
        site_dir / "app" / "ask" / "page.tsx": _chatbot_ask_page_tsx(),
        site_dir / "app" / "search" / "route.ts": _search_route_ts(),
        site_dir / "app" / "[[...slug]]" / "layout.tsx": _docs_layout_tsx(),
        site_dir / "app" / "[[...slug]]" / "page.tsx": _docs_page_tsx(),
        site_dir / "app" / "api" / "[[...slug]]" / "layout.tsx": _api_layout_tsx(),
        site_dir / "app" / "api" / "[[...slug]]" / "page.tsx": _api_page_tsx(),
        site_dir / "components" / "api-page.tsx": _api_page_component_tsx(),
        site_dir / "components" / "api-page.client.tsx": _api_page_client_tsx(),
        site_dir / "components" / "chatbot-panel.tsx": _chatbot_panel_tsx(),
        site_dir / "components" / "chatbot-toggle.tsx": _chatbot_toggle_tsx(),
        site_dir / "components" / "mdx" / "mermaid.tsx": _mermaid_component_tsx(),
        site_dir / "lib" / "chatbot-config.ts": _chatbot_config_ts(repo_root, cfg),
        site_dir / "lib" / "source.ts": _source_ts(),
        site_dir / "lib" / "layout-options.ts": _layout_options_ts(project_name, repo_url),
        site_dir / "lib" / "openapi.ts": _openapi_ts(),
        site_dir / "openapi" / ".gitkeep": "",
    }

    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _build_page_tree_from_plan(
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
        import type {{ Root }} from 'fumadocs-core/page-tree';

        export const pageTree: Root = {json.dumps(page_tree, indent=2)};
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
                "fumadocs-core": "^15.7.9",
                "fumadocs-mdx": "^11.9.0",
                "fumadocs-openapi": "^9.3.9",
                "fumadocs-ui": "^15.7.11",
                "mermaid": "^11.6.0",
                "next": "^15.3.0",
                "next-themes": "^0.4.6",
                "react": "^19.0.0",
                "react-dom": "^19.0.0",
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

        /** @type {import('next').NextConfig} */
        const config = {
          reactStrictMode: true,
          output: 'export',
          images: {
            unoptimized: true,
          },
          experimental: {
            externalDir: true,
          },
          outputFileTracingRoot: repoRoot,
          turbopack: {
            root: repoRoot,
          },
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


def _mdx_components_tsx() -> str:
    return dedent(
        """\
        import defaultMdxComponents from 'fumadocs-ui/mdx';
        import * as AccordionComponents from 'fumadocs-ui/components/accordion';
        import * as StepsComponents from 'fumadocs-ui/components/steps';
        import * as TabsComponents from 'fumadocs-ui/components/tabs';
        import { APIPage } from '@/components/api-page';
        import { Mermaid } from '@/components/mdx/mermaid';
        import type { MDXComponents } from 'mdx/types';

        export function getMDXComponents(components?: MDXComponents): MDXComponents {
          return {
            ...defaultMdxComponents,
            ...AccordionComponents,
            ...StepsComponents,
            ...TabsComponents,
            APIPage,
            Mermaid,
            ...components,
          };
        }

        export const useMDXComponents = getMDXComponents;
        """
    )


def _app_layout_tsx(project_name: str) -> str:
    return dedent(
        f"""\
        import './global.css';
        import {{ ChatbotToggle }} from '@/components/chatbot-toggle';
        import {{ RootProvider }} from 'fumadocs-ui/provider/next';
        import type {{ Metadata }} from 'next';
        import type {{ ReactNode }} from 'react';

        export const metadata: Metadata = {{
          title: '{project_name}',
          description: 'Auto-generated developer documentation',
          icons: {{
            icon: '/favicon.svg',
          }},
        }};

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
                      api: '/search',
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

        .deepdoc-chatbot-panel,
        .deepdoc-chatbot-sidebar {
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
          border: 1px solid color-mix(in srgb, var(--deepdoc-brand-light) 14%, var(--color-fd-border) 86%);
          border-radius: 1rem;
          padding: 0.8rem 0.9rem;
          background: white;
        }

        .deepdoc-chatbot-citation-list strong {
          display: block;
          margin-bottom: 0.2rem;
          color: #2f120d;
        }

        .deepdoc-chatbot-citation-list span {
          display: block;
          font-size: 0.88rem;
          color: var(--color-fd-muted-foreground);
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

        .deepdoc-chatbot-answer pre {
          overflow-x: auto;
          border: 1px solid var(--color-fd-border);
          border-radius: 0.75rem;
          padding: 0.875rem;
          background: color-mix(in srgb, var(--color-fd-card) 92%, black 8%);
        }

        .deepdoc-chatbot-answer code {
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

        export function generateStaticParams() {
          return docsSource.generateParams();
        }

        export default async function Page(props: {
          params: Promise<{ slug?: string[] }>;
        }) {
          const params = await props.params;
          const page = docsSource.getPage(params.slug ?? []);
          if (!page) notFound();

          const MDX = page.data.body;

          return (
            <DocsPage toc={page.data.toc}>
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
        import { apiSource } from '@/lib/openapi';

        export function generateStaticParams() {
          return apiSource ? apiSource.generateParams() : [];
        }

        export default async function Page(props: {
          params: Promise<{ slug?: string[] }>;
        }) {
          const params = await props.params;
          if (!apiSource) notFound();

          const page = apiSource.getPage(params.slug ?? []);
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
        import { ChatbotPanel } from '@/components/chatbot-panel';

        export default function AskPage() {
          return <ChatbotPanel />;
        }
        """
    )


def _api_page_component_tsx() -> str:
    return dedent(
        """\
        import client from './api-page.client';
        import { openapi } from '@/lib/openapi';
        import { createAPIPage } from 'fumadocs-openapi/ui';

        function EmptyAPIPage() {
          return null;
        }

        export const APIPage = openapi
          ? createAPIPage(openapi, { client })
          : EmptyAPIPage;
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
        import { loader } from 'fumadocs-core/source';
        import { createOpenAPI, openapiPlugin, openapiSource } from 'fumadocs-openapi/server';

        const schemaDir = path.join(process.cwd(), 'openapi');
        const schemaFiles = fs.existsSync(schemaDir)
          ? fs
              .readdirSync(schemaDir)
              .filter((file) => /\\.(json|ya?ml)$/i.test(file))
              .map((file) => `./openapi/${file}`)
          : [];

        export const openapi =
          schemaFiles.length > 0
            ? createOpenAPI({
                input: schemaFiles,
              })
            : null;

        export const apiSource = openapi
          ? loader({
              baseUrl: '/api',
              source: await openapiSource(openapi, {
                baseDir: '',
              }),
              plugins: [openapiPlugin()],
            })
          : null;
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
                      if (event.key === 'Enter' && !event.shiftKey) {
                        event.preventDefault();
                        submit();
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
        import { startTransition, useEffect, useState, type FormEvent, type KeyboardEvent } from 'react';
        import { useRouter, useSearchParams } from 'next/navigation';
        import ReactMarkdown from 'react-markdown';
        import { chatbotConfig } from '@/lib/chatbot-config';

        type ChatResponse = {
          answer: string;
          code_citations: Array<{
            file_path: string;
            start_line: number;
            end_line: number;
            symbol_names?: string[];
          }>;
          artifact_citations: Array<{
            file_path: string;
            start_line: number;
            end_line: number;
            artifact_type?: string;
          }>;
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
          const [draft, setDraft] = useState(question);
          const [activeQuestion, setActiveQuestion] = useState(question);
          const [loading, setLoading] = useState(false);
          const [error, setError] = useState('');
          const [response, setResponse] = useState<ChatResponse | null>(null);
          const [history, setHistory] = useState<ChatHistoryItem[]>([]);
          const [loadedQuestion, setLoadedQuestion] = useState('');

          useEffect(() => {
            setDraft(question);
            if (!question) {
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
              setError('Chatbot backend URL is not configured.');
              return;
            }
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
              setActiveQuestion(nextQuestion);
              setResponse(data);
              setHistory([
                ...nextHistory,
                { role: 'user', content: nextQuestion },
                { role: 'assistant', content: data.answer },
              ]);
            } catch (err) {
              setError(err instanceof Error ? err.message : 'Chatbot unavailable');
            } finally {
              setLoading(false);
            }
          }

          function submit(event?: FormEvent<HTMLFormElement>) {
            event?.preventDefault();
            const trimmed = draft.trim();
            if (!trimmed) return;
            const nextHistory = activeQuestion && response ? history.slice(-4) : [];
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
                          <ReactMarkdown>{response.answer}</ReactMarkdown>
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
                      <h3 className="deepdoc-chatbot-panel__section-title mb-3 text-sm font-semibold">Code citations</h3>
                      <ul className="deepdoc-chatbot-citation-list">
                        {response.code_citations.map((citation) => (
                          <li key={`${citation.file_path}-${citation.start_line}`}>
                            <strong>{citation.file_path}</strong>
                            <span>{formatLines(citation.start_line, citation.end_line)}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}

                  {!loading && response?.artifact_citations.length ? (
                    <div className="mb-5">
                      <h3 className="deepdoc-chatbot-panel__section-title mb-3 text-sm font-semibold">Artifact citations</h3>
                      <ul className="deepdoc-chatbot-citation-list">
                        {response.artifact_citations.map((citation) => (
                          <li key={`${citation.file_path}-${citation.start_line}`}>
                            <strong>{citation.file_path}</strong>
                            <span>{formatLines(citation.start_line, citation.end_line)}</span>
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
                    <p className="deepdoc-chatbot-dock__hint">
                      No mode picker needed here. This view always stays grounded in your indexed repository.
                    </p>
                  </div>
                  <div className="deepdoc-chatbot-dock__row">
                    <textarea
                      className="deepdoc-chatbot-dock__input text-sm"
                      onChange={(event) => setDraft(event.target.value)}
                      onKeyDown={(event: KeyboardEvent<HTMLTextAreaElement>) => {
                        if (event.key === 'Enter' && !event.shiftKey) {
                          event.preventDefault();
                          submit();
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
