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

    _ensure_app_scaffold(repo_root, project_name, repo_url, docs_dir_relative)
    _write_page_tree(repo_root, page_tree)
    _write_static_assets(repo_root)
    _cleanup_legacy_artifacts(repo_root)


def _ensure_app_scaffold(
    repo_root: Path,
    project_name: str,
    repo_url: str,
    docs_dir_relative: str,
) -> None:
    """Write or update the CodeWiki-managed Fumadocs app scaffold."""
    site_dir = repo_root / "site"
    site_dir.mkdir(parents=True, exist_ok=True)

    files = {
        site_dir / "package.json": _package_json(project_name),
        site_dir / "tsconfig.json": _tsconfig_json(),
        site_dir / "next-env.d.ts": _next_env_d_ts(),
        site_dir / "next.config.mjs": _next_config_mjs(),
        site_dir / "source.config.ts": _source_config_ts(docs_dir_relative),
        site_dir / "mdx-components.tsx": _mdx_components_tsx(),
        site_dir / "app" / "layout.tsx": _app_layout_tsx(project_name),
        site_dir / "app" / "global.css": _global_css(),
        site_dir / "app" / "search" / "route.ts": _search_route_ts(),
        site_dir / "app" / "[[...slug]]" / "layout.tsx": _docs_layout_tsx(),
        site_dir / "app" / "[[...slug]]" / "page.tsx": _docs_page_tsx(),
        site_dir / "app" / "api" / "[[...slug]]" / "layout.tsx": _api_layout_tsx(),
        site_dir / "app" / "api" / "[[...slug]]" / "page.tsx": _api_page_tsx(),
        site_dir / "components" / "api-page.tsx": _api_page_component_tsx(),
        site_dir / "components" / "api-page.client.tsx": _api_page_client_tsx(),
        site_dir / "components" / "mdx" / "mermaid.tsx": _mermaid_component_tsx(),
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

    grouped_slugs: set[str] = set()
    nested_sections: dict[str, dict[str, Any]] = {}
    flat_sections: dict[str, list[Any]] = {}
    section_order: list[tuple[str, str]] = []

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

        if " > " in section_name:
            parent, child = section_name.split(" > ", 1)
            if parent not in nested_sections:
                section_order.append(("nested", parent))
            parent_entry = nested_sections.setdefault(
                parent, {"order": [], "children": {}}
            )
            if child not in parent_entry["children"]:
                parent_entry["order"].append(child)
            parent_entry["children"][child] = pages
        else:
            if section_name not in flat_sections:
                section_order.append(("flat", section_name))
            flat_sections[section_name] = pages

    for section_kind, section_name in section_order:
        if section_kind == "flat":
            pages = flat_sections[section_name]
            root_children.append(
                {
                    "type": "folder",
                    "name": section_name,
                    "children": [_page_tree_node(page_url(page), page.title) for page in pages],
                }
            )
            continue

        section_data = nested_sections[section_name]
        child_nodes: list[dict[str, Any]] = []
        for child_name in section_data["order"]:
            child_pages = section_data["children"][child_name]
            if len(child_pages) == 1:
                page = child_pages[0]
                child_nodes.append(_page_tree_node(page_url(page), page.title))
            else:
                child_nodes.append(
                    {
                        "type": "folder",
                        "name": child_name,
                        "children": [
                            _page_tree_node(page_url(page), page.title)
                            for page in child_pages
                        ],
                    }
                )
        if child_nodes:
            root_children.append(
                {"type": "folder", "name": section_name, "children": child_nodes}
            )

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
        // CodeWiki-managed file. Regenerated by `codewiki generate`.
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
        if "_codewiki_autogen_" not in existing:
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
_codewiki_autogen_: true
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
                "fumadocs-core": "^15.6.1",
                "fumadocs-mdx": "^11.5.0",
                "fumadocs-openapi": "^6.4.2",
                "fumadocs-ui": "^15.6.1",
                "mermaid": "^11.6.0",
                "next": "^15.3.0",
                "next-themes": "^0.4.6",
                "react": "^19.0.0",
                "react-dom": "^19.0.0",
                "tailwindcss": "^4.1.3",
            },
            "devDependencies": {
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
          configPath: './source.config.ts',
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


def _source_config_ts(docs_dir_relative: str) -> str:
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
                  search={{
                    options: {{
                      api: '/search',
                      type: 'static',
                    }},
                  }}
                >
                  {{children}}
                </RootProvider>
              </body>
            </html>
          );
        }}
        """
    )


def _global_css() -> str:
    return dedent(
        """\
        @import 'tailwindcss';
        @import 'fumadocs-ui/css/neutral.css';
        @import 'fumadocs-ui/css/preset.css';
        @import 'fumadocs-openapi/css/preset.css';

        :root {
          --codewiki-accent: oklch(0.62 0.11 183);
        }

        body {
          font-feature-settings: 'liga' 1, 'calt' 1;
        }
        """
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
        import { DocsBody, DocsPage } from 'fumadocs-ui/layouts/docs/page';
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
        import { DocsBody, DocsPage } from 'fumadocs-ui/layouts/docs/page';
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
              return mermaid.render(id, chart.replaceAll('\\n', '\n'));
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
        import { loader } from 'fumadocs-core/source';
        import { docs } from 'fumadocs-mdx:collections/server';

        export const docsSource = loader({
          baseUrl: '/',
          source: docs.toFumadocsSource(),
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
