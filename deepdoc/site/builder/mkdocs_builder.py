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
from ...chatbot.settings import chatbot_backend_base_url, chatbot_enabled
from .mdx_utils import _ensure_md_frontmatter

# Default brand palette (carried over from the previous scaffold default).
_DEFAULT_PRIMARY = "#EB3E25"
_DEFAULT_LIGHT = "#EF624E"
_DEFAULT_DARK = "#C1331F"

# ─────────────────────────────────────────────────────────────────────────────
# Nav ordering + legacy filename migration (formerly in the Fumadocs engine)
# ─────────────────────────────────────────────────────────────────────────────

_START_HERE_SLUG_ORDER: tuple[str, ...] = (
    "start-here",
    "local-development-setup",
    "domain-glossary",
    "debug-runbook",
    "whats-changed",
)


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
    nav schema. Section ordering uses the planner-set ``_order`` value (topology depth);
    Start Here pages use :func:`_start_here_page_rank` for internal ordering.
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
        key=lambda item: item[1]["_order"],
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

    sections: dict[str, list[tuple[str, str, str]]] = {}
    for page in plan.pages:
        hints = (page._b.generation_hints or {}) if hasattr(page, "_b") else {}
        if hints.get("is_introduction_page") or page.page_type == "overview":
            continue
        if not (output_dir / f"{page.slug}.md").exists():
            continue
        section = getattr(page, "section", None) or "Docs"
        desc = (getattr(page, "description", None) or "").strip()
        sections.setdefault(section, []).append((page.title, page.slug, desc))

    ordered_section_names = list(sections.keys())
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
            f"- **[{title}]({slug}.md)**{(' — ' + desc) if desc else ''}"
            for title, slug, desc in pages
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
    """Write mkdocs.yml, brand stylesheet, and optional chatbot widget assets."""
    # docs_dir_relative is relative to site_dir (e.g. "../docs" when output_dir=repo_root/docs)
    actual_docs_dir = (site_dir / docs_dir_relative).resolve()
    (actual_docs_dir / "stylesheets").mkdir(parents=True, exist_ok=True)
    is_chatbot = chatbot_enabled(cfg)
    (site_dir / "mkdocs.yml").write_text(
        _mkdocs_yml(project_name, repo_url, docs_dir_relative, nav, has_openapi, chatbot=is_chatbot),
        encoding="utf-8",
    )
    (actual_docs_dir / "stylesheets" / "extra.css").write_text(
        _extra_css(cfg), encoding="utf-8"
    )
    if is_chatbot:
        js_dir = actual_docs_dir / "javascripts"
        js_dir.mkdir(parents=True, exist_ok=True)
        api_url = chatbot_backend_base_url(cfg, site_dir.parent)
        (js_dir / "chatbot-config.js").write_text(
            _chatbot_config_js(api_url), encoding="utf-8"
        )
        (js_dir / "chatbot.js").write_text(_chatbot_widget_js(), encoding="utf-8")
        (js_dir / "chatbot-ask.js").write_text(_ask_page_js(), encoding="utf-8")
        (actual_docs_dir / "stylesheets" / "chatbot.css").write_text(
            _chatbot_css(), encoding="utf-8"
        )
        (actual_docs_dir / "stylesheets" / "chatbot-ask.css").write_text(
            _ask_page_css(), encoding="utf-8"
        )
        _copy_vendor_assets(js_dir, actual_docs_dir / "stylesheets")
        _ensure_ask_page(actual_docs_dir, project_name)


# Vendored client libraries (bundled, no CDN) the chatbot /ask workspace needs:
# markdown-it for CommonMark/GFM rendering and highlight.js for syntax colors.
_VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
_VENDOR_JS = ("markdown-it.min.js", "highlight.min.js")
_VENDOR_CSS = ("hljs-theme.css",)


def _copy_vendor_assets(js_dir: Path, css_dir: Path) -> None:
    """Copy the bundled markdown/highlight libraries into the generated site."""
    for name in _VENDOR_JS:
        (js_dir / name).write_bytes((_VENDOR_DIR / name).read_bytes())
    for name in _VENDOR_CSS:
        (css_dir / name).write_bytes((_VENDOR_DIR / name).read_bytes())


def _mkdocs_yml(
    project_name: str,
    repo_url: str,
    docs_dir_relative: str,
    nav: list[Any],
    has_openapi: bool,
    chatbot: bool = False,
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

    chatbot_css_line = (
        # hljs theme first so chatbot-ask.css can override its base bg/padding.
        "\n  - stylesheets/hljs-theme.css"
        "\n  - stylesheets/chatbot.css\n  - stylesheets/chatbot-ask.css"
        if chatbot
        else ""
    )
    chatbot_js_block = (
        "\nextra_javascript:\n"
        # Vendored libs first — they define window.markdownit / window.hljs
        # that chatbot-ask.js consumes when rendering answers.
        "  - javascripts/markdown-it.min.js\n"
        "  - javascripts/highlight.min.js\n"
        "  - javascripts/chatbot-config.js\n"
        "  - javascripts/chatbot.js\n"
        "  - javascripts/chatbot-ask.js\n"
        if chatbot
        else ""
    )
    not_in_nav_block = "\nnot_in_nav: |\n  ask.md\n" if chatbot else ""

    return f"""\
# DeepDoc-managed file. Regenerated by `deepdoc generate`.
site_name: {_yaml_scalar(project_name)}
{repo_line}docs_dir: {_yaml_scalar(docs_dir_relative)}
site_dir: out
{not_in_nav_block}
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
  - stylesheets/extra.css{chatbot_css_line}
{chatbot_js_block}
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


# ─────────────────────────────────────────────────────────────────────────────
# Chatbot widget assets
# ─────────────────────────────────────────────────────────────────────────────


def _chatbot_config_js(api_url: str) -> str:
    import json as _json

    return (
        "/* DeepDoc chatbot config. Regenerated by `deepdoc generate`. */\n"
        "(function () {\n"
        f"  window.__DEEPDOC_CHATBOT_URL__ = {_json.dumps(api_url)};\n"
        "})();\n"
    )


def _chatbot_widget_js() -> str:
    return r"""/* DeepDoc quick-ask widget. Regenerated by `deepdoc generate`. */
(function () {
  'use strict';

  var API = (window.__DEEPDOC_CHATBOT_URL__ || '').replace(/\/$/, '');
  if (!API) return;

  var SUGGESTED = [
    'How does authentication work?',
    'Walk me through the data model',
    'Where are API routes defined?',
    'What happens on a deploy?',
  ];

  var SVG_CHAT  = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';
  var SVG_ARROW = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>';

  var _mode = 'fast';
  var overlay = null, fab = null, popup = null, inp = null, isOpen = false;

  // Build the FAB + popup and wire listeners. Invoked by sync() whenever we are
  // on a docs page that does not already have one.
  function build() {
    overlay = mk('div', { id: 'dd-ov' });
    fab = mk('button', { id: 'dd-fab', 'aria-label': 'Ask AI about this codebase' });
    fab.innerHTML = SVG_CHAT + '<span>Ask AI</span>';

    popup = mk('div', { id: 'dd-popup', 'aria-hidden': 'true', role: 'dialog', 'aria-label': 'Ask the codebase' });
    popup.innerHTML = [
      '<div class="dd-dock">',
      '  <div class="dd-dock-head">',
      '    <p class="dd-eyebrow"><span class="dd-eyebrow-dot"></span>Ask the codebase</p>',
      '    <div class="dd-modes" role="radiogroup" aria-label="Answer depth">',
      '      <button class="dd-mode dd-mode-on" type="button" data-mode="fast" role="radio" aria-checked="true">Fast</button>',
      '      <button class="dd-mode" type="button" data-mode="deep" role="radio" aria-checked="false">Deep Research</button>',
      '    </div>',
      '  </div>',
      '  <form id="dd-popup-form" class="dd-dock-row" autocomplete="off">',
      '    <textarea id="dd-popup-inp" rows="1" placeholder="Where is auth handled? How is deployment configured?"></textarea>',
      '    <button type="submit" id="dd-popup-sub" aria-label="Ask">' + SVG_ARROW + '<span>Ask</span></button>',
      '  </form>',
      '  <div id="dd-popup-sugs">',
      SUGGESTED.slice(0, 3).map(function (s) {
        return '<button class="dd-sug-pill" type="button">' + esc(s) + '</button>';
      }).join(''),
      '  </div>',
      '</div>',
    ].join('');

    document.body.appendChild(overlay);
    document.body.appendChild(fab);
    document.body.appendChild(popup);
    inp = popup.querySelector('#dd-popup-inp');
    isOpen = false;

    fab.addEventListener('click', function () { isOpen ? close() : show(); });
    overlay.addEventListener('click', close);

    popup.querySelector('.dd-modes').addEventListener('click', function (e) {
      var t = e.target.closest && e.target.closest('.dd-mode');
      if (!t) return;
      _mode = t.dataset.mode;
      popup.querySelectorAll('.dd-mode').forEach(function (b) {
        var on = b.dataset.mode === _mode;
        b.classList.toggle('dd-mode-on', on);
        b.setAttribute('aria-checked', on ? 'true' : 'false');
      });
      inp.focus();
    });

    popup.querySelector('#dd-popup-form').addEventListener('submit', function (e) {
      e.preventDefault();
      var q = inp.value.trim();
      if (q) goAsk(q);
    });

    inp.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); var q = inp.value.trim(); if (q) goAsk(q); }
    });

    inp.addEventListener('input', function () {
      this.style.height = 'auto';
      this.style.height = Math.min(this.scrollHeight, 120) + 'px';
    });

    popup.querySelector('#dd-popup-sugs').addEventListener('click', function (e) {
      var b = e.target.closest && e.target.closest('.dd-sug-pill');
      if (b) goAsk(b.textContent.trim());
    });
  }

  function teardown() {
    if (!fab) return;
    close();
    overlay.remove(); fab.remove(); popup.remove();
    overlay = fab = popup = inp = null;
  }

  // Re-evaluate on every navigation. Material `navigation.instant` swaps page
  // content without re-running this script, and /ask is reached via a full load
  // then SPA-navigated back — so a one-shot injector leaves the FAB missing
  // until a hard refresh. Hide it on /ask; (re)inject it on every docs page.
  function sync() {
    if (document.getElementById('dd-ask-root')) {
      teardown();
    } else if (!fab || !document.body.contains(fab)) {
      build();
    }
  }

  function show() {
    isOpen = true;
    popup.classList.add('dd-popup-on');
    popup.setAttribute('aria-hidden', 'false');
    overlay.classList.add('dd-ov-on');
    fab.classList.add('dd-fab-on');
    setTimeout(function () { if (inp) inp.focus(); }, 40);
  }

  function close() {
    isOpen = false;
    if (popup) { popup.classList.remove('dd-popup-on'); popup.setAttribute('aria-hidden', 'true'); }
    if (overlay) overlay.classList.remove('dd-ov-on');
    if (fab) fab.classList.remove('dd-fab-on');
  }

  function goAsk(question) {
    var base = window.location.origin + (window.__DEEPDOC_SITE_BASE__ || '');
    window.location.href = base + '/ask/?q=' + encodeURIComponent(question) + '&mode=' + _mode;
  }

  function esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function mk(tag, attrs) {
    var el = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { el.setAttribute(k, attrs[k]); });
    return el;
  }

  // Escape closes the popup (attached once, document-level).
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && isOpen) close(); });

  if (window.document$ && typeof window.document$.subscribe === 'function') {
    window.document$.subscribe(sync);
  } else {
    sync();
  }
})();
"""


def _chatbot_css() -> str:
    return r"""/* DeepDoc quick-ask widget. Regenerated by `deepdoc generate`. */

:root {
  --dd-brand:  var(--md-primary-fg-color, #eb3e25);
  --dd-light:  var(--md-primary-fg-color--light, #ff7a5c);
  --dd-dark:   var(--md-primary-fg-color--dark, #9c2a16);
  --dd-border: var(--md-default-fg-color--lightest, rgba(0,0,0,.08));
  /* Material's own secondary-text token (resolves to ~4.6:1 light / ~4.9:1 slate,
     both >= WCAG AA). The opaque fallback keeps muted text legible if the Material
     vars are ever absent — never the old rgba(...,.55) that failed AA. */
  --dd-muted:  var(--md-default-fg-color--light, #6e6e73);
  --dd-fg:     var(--md-default-fg-color, #1c1c1c);
  --dd-bg:     var(--md-default-bg-color, #fff);
}

/* ── Overlay behind popup ────────────────────────────────────────────────── */
#dd-ov {
  display: none;
  position: fixed; inset: 0;
  background: rgba(9, 11, 19, .32);
  backdrop-filter: blur(2px);
  z-index: 299;
}
#dd-ov.dd-ov-on { display: block; animation: dd-fade .15s ease; }
@keyframes dd-fade { from { opacity: 0; } to { opacity: 1; } }

/* ── FAB ─────────────────────────────────────────────────────────────────── */
#dd-fab {
  position: fixed;
  bottom: 1.5rem; right: 1.5rem;
  z-index: 300;
  display: inline-flex; align-items: center; gap: .45rem;
  padding: .62rem 1.15rem .62rem .9rem;
  border-radius: 2rem;
  background: linear-gradient(135deg, var(--dd-light), var(--dd-brand) 58%, var(--dd-dark));
  color: #fff; border: none; cursor: pointer;
  font-size: .8rem; font-weight: 600; font-family: inherit;
  letter-spacing: .02em;
  box-shadow: 0 10px 26px rgba(193, 51, 31, .26), 0 3px 8px rgba(193, 51, 31, .14);
  transition: transform .16s cubic-bezier(.22,1,.36,1), box-shadow .16s ease, opacity .15s, filter .16s;
  user-select: none;
}
#dd-fab svg { width: 14px; height: 14px; flex-shrink: 0; }
#dd-fab:hover  { transform: translateY(-2px); box-shadow: 0 16px 34px rgba(193, 51, 31, .3); filter: saturate(1.05); }
#dd-fab:active { transform: translateY(0); }
#dd-fab.dd-fab-on { opacity: 0; transform: scale(.9); pointer-events: none; }

/* ── Quick-ask dock popup (centered near the bottom, DeepWiki-subtle) ─────── */
#dd-popup {
  position: fixed;
  left: 50%; bottom: clamp(1rem, 3vw, 2rem);
  transform: translateX(-50%);
  z-index: 300;
  width: min(38rem, calc(100vw - 2rem));
  display: none;
}
#dd-popup.dd-popup-on { display: block; }
.dd-dock {
  border: 1px solid color-mix(in srgb, var(--dd-light) 6%, var(--dd-border) 94%);
  border-radius: 1.1rem;
  padding: .8rem;
  background: color-mix(in srgb, var(--dd-bg) 98.5%, var(--dd-light) 1.5%);
  /* Soft, neutral lift — subtle like DeepWiki, not a heavy brand-tinted slab. */
  box-shadow: 0 14px 36px rgba(15, 18, 30, .12), 0 2px 8px rgba(15, 18, 30, .06);
  backdrop-filter: blur(8px);
  transform-origin: center bottom;
}
#dd-popup.dd-popup-on .dd-dock { animation: dd-dock-in .26s cubic-bezier(.22,1,.36,1); }
@keyframes dd-dock-in {
  from { opacity: 0; transform: translateY(14px) scale(.985); }
  to   { opacity: 1; transform: none; }
}

/* Eyebrow + mode pills share one row so the dock stays compact. */
.dd-dock-head {
  display: flex; align-items: center; justify-content: space-between;
  gap: .75rem; flex-wrap: wrap; margin-bottom: .6rem;
}
.dd-eyebrow {
  display: inline-flex; align-items: center; gap: .5rem; margin: 0;
  font-size: .74rem; font-weight: 600; letter-spacing: .08em; text-transform: uppercase;
  color: color-mix(in srgb, var(--dd-dark) 70%, var(--dd-muted) 30%);
}
.dd-eyebrow-dot {
  height: .45rem; width: .45rem; border-radius: 999px;
  background: color-mix(in srgb, var(--dd-brand) 72%, #fff 28%);
  box-shadow: 0 0 0 .18rem color-mix(in srgb, var(--dd-light) 14%, transparent 86%);
  animation: dd-pulse 1.6s ease-in-out infinite;
}
@keyframes dd-pulse {
  0%   { box-shadow: 0 0 0 0 rgba(235, 62, 37, .3); }
  70%  { box-shadow: 0 0 0 .42rem rgba(235, 62, 37, 0); }
  100% { box-shadow: 0 0 0 0 rgba(235, 62, 37, 0); }
}

/* ── Mode pills ──────────────────────────────────────────────────────────── */
.dd-modes { display: flex; gap: .4rem; flex-shrink: 0; }
.dd-mode {
  border: 1px solid color-mix(in srgb, var(--dd-light) 12%, var(--dd-border) 88%);
  border-radius: 999px; padding: .32rem .8rem;
  font-size: .78rem; font-weight: 600; font-family: inherit; cursor: pointer;
  color: var(--dd-muted);
  background: color-mix(in srgb, var(--dd-bg) 90%, var(--dd-light) 10%);
  transition: background .16s ease, color .16s ease, border-color .16s ease;
}
.dd-mode:hover { color: var(--dd-dark); }
.dd-mode-on {
  border-color: color-mix(in srgb, var(--dd-brand) 42%, var(--dd-border) 58%);
  color: var(--dd-dark);
  background: color-mix(in srgb, var(--dd-bg) 72%, var(--dd-light) 28%);
}

/* ── Input row ───────────────────────────────────────────────────────────── */
.dd-dock-row { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: .65rem; align-items: end; }
#dd-popup-inp {
  resize: none;
  border: 1px solid color-mix(in srgb, var(--dd-light) 8%, var(--dd-border) 92%);
  border-radius: .85rem;
  background: var(--dd-bg);
  padding: .7rem .9rem;
  font-size: .86rem; font-family: inherit; outline: none;
  color: var(--dd-fg); line-height: 1.5;
  min-height: 2.6rem; max-height: 8rem; overflow-y: auto;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.4);
  transition: outline .12s, border-color .12s;
}
#dd-popup-inp:focus { outline: 2px solid color-mix(in srgb, var(--dd-light) 24%, transparent 76%); outline-offset: 2px; }
#dd-popup-inp::placeholder { color: color-mix(in srgb, var(--dd-muted) 70%, transparent 30%); }
#dd-popup-sub {
  display: inline-flex; align-items: center; gap: .4rem;
  border: none; border-radius: 999px; padding: .7rem 1.1rem; cursor: pointer;
  font-size: .84rem; font-weight: 600; font-family: inherit; color: #fff;
  background: linear-gradient(135deg, var(--dd-light), var(--dd-brand) 58%, var(--dd-dark));
  box-shadow: 0 10px 22px rgba(193, 51, 31, .16);
  transition: transform .16s ease, box-shadow .16s ease, filter .16s ease;
}
#dd-popup-sub svg { width: 14px; height: 14px; }
#dd-popup-sub:hover { transform: translateY(-1px); box-shadow: 0 14px 28px rgba(193, 51, 31, .22); filter: saturate(1.05); }
#dd-popup-sub:active { transform: translateY(0); }

/* ── Suggestion pills ────────────────────────────────────────────────────── */
#dd-popup-sugs { display: flex; flex-wrap: wrap; gap: .4rem; margin-top: .55rem; }
.dd-sug-pill {
  padding: .4rem .7rem;
  background: color-mix(in srgb, var(--dd-bg) 93%, var(--dd-light) 7%);
  border: 1px solid var(--dd-border);
  border-radius: 999px;
  font-size: .76rem; font-family: inherit;
  color: var(--dd-muted); cursor: pointer; line-height: 1.3;
  transition: background .12s, border-color .12s, color .12s;
}
.dd-sug-pill:hover {
  border-color: color-mix(in srgb, var(--dd-brand) 42%, var(--dd-border) 58%);
  color: var(--dd-dark);
  background: color-mix(in srgb, var(--dd-bg) 72%, var(--dd-light) 28%);
}

@media (max-width: 520px) {
  .dd-dock-row { grid-template-columns: minmax(0,1fr); }
  #dd-popup-sub { justify-content: center; }
}

@media (prefers-reduced-motion: reduce) {
  #dd-fab, .dd-mode, .dd-sug-pill, #dd-popup-sub { transition: none; }
  #dd-fab:hover, #dd-popup-sub:hover { transform: none; }
  .dd-eyebrow-dot { animation: none; }
  #dd-popup.dd-popup-on .dd-dock,
  #dd-ov.dd-ov-on { animation: none; }
}
"""


def _ask_page_js() -> str:
    return r"""/* DeepDoc /ask workspace. Regenerated by `deepdoc generate`. */
(function () {
  'use strict';

  // Keep the focused /ask shell scoped to the ask page only. Under MkDocs
  // Material `navigation.instant` the <body> element persists across SPA
  // navigations, so a one-time classList.add leaks the chrome-hiding rules
  // onto docs pages (header/sidebar/footer hidden until a hard refresh).
  // Re-evaluate on every navigation instead, keyed on #dd-ask-root presence.
  function syncAskClass() {
    document.body.classList.toggle('dd-ask-page', !!document.getElementById('dd-ask-root'));
  }
  if (window.document$ && typeof window.document$.subscribe === 'function') {
    window.document$.subscribe(syncAskClass);
  } else {
    syncAskClass();
  }

  var root = document.getElementById('dd-ask-root');
  if (!root) return;

  var API = (window.__DEEPDOC_CHATBOT_URL__ || '').replace(/\/$/, '');

  var _hist = [], _mode = 'fast', _ctrl = null, _rid = 0, _modal = null;
  // Streaming render state: while true, code fences skip the (costly) syntax
  // highlighter and renders are time-throttled, so a heavier markdown parser
  // never re-parses the whole answer on every single token (was O(n^2)).
  var _streaming = false, _streamTimer = null, _lastRender = 0;

  var SVG = {
    spark: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>',
    back:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>',
    file:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>',
    doc:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>',
    copy:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>',
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg>',
    trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M9 6V4h6v2"/></svg>',
    arrow: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>',
  };

  root.innerHTML = [
    '<div class="ddp">',
    '  <div class="ddp-top">',
    '    <a class="ddp-back" href="../">' + SVG.back + '<span>Back to docs</span></a>',
    '    <button class="ddp-clear" id="ddp-clear" type="button">' + SVG.trash + '<span>New</span></button>',
    '  </div>',
    '  <div class="ddp-hero">',
    '    <div class="ddp-hero-main">',
    '      <p class="ddp-eyebrow"><span class="dd-eyebrow-dot"></span>Answer workspace</p>',
    '      <h1 class="ddp-title" id="ddp-title">Ask the codebase</h1>',
    '      <p class="ddp-lede" id="ddp-lede">Grounded answers with citations straight from your source.</p>',
    '    </div>',
    '    <span class="ddp-chip" id="ddp-chip" hidden></span>',
    '  </div>',
    '  <div class="ddp-grid">',
    '    <section class="ddp-panel">',
    '      <div class="ddp-panel-hd"><p class="ddp-panel-q" id="ddp-qlabel">Ready when you are</p></div>',
    '      <div class="ddp-panel-bd" id="ddp-body">',
    '        <div class="ddp-empty" id="ddp-empty">Ask a question below and this page becomes a focused answer workspace with citations and related docs.</div>',
    '      </div>',
    '    </section>',
    '    <aside class="ddp-side">',
    '      <div class="ddp-side-hd"><h2>Supporting context</h2><p>Code and docs referenced by the current answer appear here.</p></div>',
    '      <div class="ddp-side-bd" id="ddp-sources"><div class="ddp-side-empty">Ask a question to populate this sidebar with citations and suggested documentation.</div></div>',
    '    </aside>',
    '  </div>',
    '  <div class="ddp-dock-shell">',
    '    <form class="ddp-dock" id="ddp-form" autocomplete="off">',
    '      <div class="ddp-dock-meta">',
    '        <p class="dd-eyebrow"><span class="dd-eyebrow-dot"></span><span id="ddp-dock-eyebrow">Ask the codebase</span></p>',
    '        <p class="ddp-dock-sub" id="ddp-dock-sub">Start with a question about architecture, files, or behavior.</p>',
    '      </div>',
    '      <div class="ddp-modes" role="tablist">',
    '        <button class="ddp-mode ddp-mode-on" type="button" data-mode="fast" role="tab" aria-selected="true">Fast</button>',
    '        <button class="ddp-mode" type="button" data-mode="deep" role="tab" aria-selected="false">Deep Research</button>',
    '      </div>',
    '      <div class="ddp-dock-row">',
    '        <textarea id="ddp-inp" rows="1" placeholder="Where is auth handled? How is deployment configured?"></textarea>',
    '        <button type="submit" id="ddp-sub">' + SVG.arrow + '<span>Ask</span></button>',
    '      </div>',
    '    </form>',
    '  </div>',
    '</div>',
  ].join('');

  var titleEl = document.getElementById('ddp-title');
  var ledeEl  = document.getElementById('ddp-lede');
  var chipEl  = document.getElementById('ddp-chip');
  var qlabel  = document.getElementById('ddp-qlabel');
  var bodyEl  = document.getElementById('ddp-body');
  var srcEl   = document.getElementById('ddp-sources');
  var dockEye = document.getElementById('ddp-dock-eyebrow');
  var dockSub = document.getElementById('ddp-dock-sub');
  var inpEl   = document.getElementById('ddp-inp');
  var subEl   = document.getElementById('ddp-sub');

  // -- Conversation thread (client-side only, session-scoped) -----------------
  // Turns live in memory + sessionStorage — nothing is stored server-side. The
  // storage dies with the tab; the "New" button clears it explicitly.
  var _turns = [], _savedSources = null;
  var STORE_KEY = 'dd-ask-thread:' + window.location.pathname;

  function saveThread() {
    try {
      sessionStorage.setItem(STORE_KEY, JSON.stringify({ turns: _turns, sources: _savedSources }));
    } catch (e) {}
  }
  function clearThread() {
    try { sessionStorage.removeItem(STORE_KEY); } catch (e) {}
  }
  // Append a new Q/A turn shell (question header) to the panel body.
  function newTurn(q) {
    var empty = bodyEl.querySelector('.ddp-empty'); if (empty) empty.remove();
    var turn = mk('section', { class: 'dda-turn' });
    var qh = mk('div', { class: 'dda-turn-q' });
    var ql = mk('span', { class: 'dda-turn-q-lbl' }); ql.textContent = 'You asked';
    var qp = mk('p', { class: 'dda-turn-q-txt' }); qp.textContent = q;
    qh.appendChild(ql); qh.appendChild(qp); turn.appendChild(qh);
    bodyEl.appendChild(turn);
    return turn;
  }
  // Rebuild the visible thread (and the backend history) from sessionStorage.
  function restoreThread() {
    var data = null;
    try { data = JSON.parse(sessionStorage.getItem(STORE_KEY) || 'null'); } catch (e) {}
    if (!data || !Array.isArray(data.turns) || !data.turns.length) return false;
    _turns = data.turns; _savedSources = data.sources || null;
    bodyEl.innerHTML = '';
    _hist = [];
    _turns.forEach(function (t) {
      var turn = newTurn(t.q);
      var txt = mk('div', { class: 'dda-txt' }); txt.innerHTML = md(t.a || '');
      turn.appendChild(txt);
      _hist.push({ role: 'user', content: t.q });
      _hist.push({ role: 'assistant', content: t.a || '' });
    });
    if (_hist.length > 10) _hist = _hist.slice(-10);
    var last = _turns[_turns.length - 1];
    titleEl.textContent = last.q;
    qlabel.textContent = 'Conversation';
    dockEye.textContent = 'Ask a follow-up';
    dockSub.textContent = 'Stay on this page and keep the answer flow going.';
    if (_savedSources) {
      renderSources(_savedSources.cites || [], _savedSources.refs || [], _savedSources.inv || []);
      renderChip((_savedSources.cites || []).length, last.mode);
    }
    scrollBottom();
    return true;
  }

  // -- Auto-scroll: stick to bottom while streaming unless the user scrolls up.
  var _pinned = true;
  root.addEventListener('scroll', function () {
    _pinned = root.scrollHeight - root.scrollTop - root.clientHeight < 140;
  }, { passive: true });
  function scrollBottom() { root.scrollTop = root.scrollHeight; }
  function autoScroll() { if (_pinned) scrollBottom(); }

  function stripQParam() {
    try {
      var u = new URL(window.location.href);
      if (u.searchParams.has('q')) {
        u.searchParams.delete('q');
        var qs = u.searchParams.toString();
        history.replaceState(null, '', u.pathname + (qs ? '?' + qs : ''));
      }
    } catch (e) {}
  }

  // -- Mode toggles -----------------------------------------------------------
  function setMode(m) {
    _mode = (m === 'deep') ? 'deep' : 'fast';
    root.querySelectorAll('.ddp-mode').forEach(function (b) {
      var on = b.dataset.mode === _mode;
      b.classList.toggle('ddp-mode-on', on);
      b.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    // Keep ?mode= in sync so a refresh or shared link preserves the choice.
    try {
      var u = new URL(window.location.href);
      u.searchParams.set('mode', _mode);
      history.replaceState(null, '', u.pathname + u.search);
    } catch (e) {}
  }
  root.querySelector('.ddp-modes').addEventListener('click', function (e) {
    var t = e.target.closest && e.target.closest('.ddp-mode');
    if (t) { setMode(t.dataset.mode); inpEl.focus(); }
  });

  // -- New conversation -------------------------------------------------------
  document.getElementById('ddp-clear').addEventListener('click', function () {
    if (_ctrl) { _ctrl.abort(); _ctrl = null; }
    _hist = []; _rid = 0;
    _turns = []; _savedSources = null; clearThread();
    titleEl.textContent = 'Ask the codebase';
    ledeEl.textContent = 'Grounded answers with citations straight from your source.';
    chipEl.hidden = true;
    qlabel.textContent = 'Ready when you are';
    dockEye.textContent = 'Ask the codebase';
    dockSub.textContent = 'Start with a question about architecture, files, or behavior.';
    bodyEl.innerHTML = '<div class="ddp-empty">Ask a question below and this page becomes a focused answer workspace with citations and related docs.</div>';
    srcEl.innerHTML = '<div class="ddp-side-empty">Ask a question to populate this sidebar with citations and suggested documentation.</div>';
    history.replaceState(null, '', window.location.pathname);
    inpEl.focus();
  });

  // -- Input ------------------------------------------------------------------
  inpEl.addEventListener('input', function () {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 140) + 'px';
  });
  inpEl.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      document.getElementById('ddp-form').dispatchEvent(new Event('submit', { cancelable: true }));
    }
  });
  document.getElementById('ddp-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var q = inpEl.value.trim();
    if (q && !subEl.disabled) { inpEl.value = ''; inpEl.style.height = ''; ask(q); }
  });

  // -- Copy code blocks -------------------------------------------------------
  bodyEl.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('.dda-copy');
    if (!b || !navigator.clipboard) return;
    navigator.clipboard.writeText(b.getAttribute('data-code') || '').then(function () {
      b.innerHTML = SVG.check + '<span>Copied</span>'; b.classList.add('dda-copy-ok');
      setTimeout(function () { b.innerHTML = SVG.copy + '<span>Copy</span>'; b.classList.remove('dda-copy-ok'); }, 1800);
    });
  });

  // -- Ask --------------------------------------------------------------------
  function ask(question) {
    if (_ctrl) _ctrl.abort();
    _ctrl = new AbortController();
    var myId = ++_rid;
    // Reset streaming-render state for this turn (cancel any stale throttle).
    _streaming = false; _lastRender = 0;
    if (_streamTimer) { clearTimeout(_streamTimer); _streamTimer = null; }

    var turnMode = _mode;
    titleEl.textContent = question;
    ledeEl.textContent = turnMode === 'deep'
      ? 'Deep research — tracing code paths across the repository.'
      : 'Fast answer — grounded in the most relevant indexed evidence.';
    qlabel.textContent = 'Conversation';
    dockEye.textContent = 'Ask a follow-up';
    dockSub.textContent = 'Stay on this page and keep the answer flow going.';
    // Drop ?q= once the question is asked so a reload restores the saved
    // thread instead of re-running the boot question.
    stripQParam();

    // A superseded in-flight turn keeps its partial text; strip its live
    // cursor and typing dots so only the new turn looks active.
    var oldCur = bodyEl.querySelector('.dda-cur'); if (oldCur) oldCur.remove();
    bodyEl.querySelectorAll('.dda-typing').forEach(function (t) { t.style.display = 'none'; });
    bodyEl.querySelectorAll('.dda-research:not(.dda-research-done)').forEach(function (r) { r.classList.add('dda-research-done'); r.open = false; });

    var turn = newTurn(question);
    var research = mk('details', { class: 'dda-research' });
    research.hidden = true;
    research.innerHTML =
      '<summary class="dda-research-sum">'
      + '<span class="dda-research-ic">✦</span>'
      + '<span class="dda-research-lbl">Research steps</span>'
      + '<span class="dda-research-meta"></span></summary>';
    var stepsEl = mk('div', { class: 'dda-steps' });
    research.appendChild(stepsEl);
    var typEl   = mk('div', { class: 'dda-typing' }); typEl.innerHTML = '<span></span><span></span><span></span>';
    var txtEl   = mk('div', { class: 'dda-txt' });
    turn.appendChild(research); turn.appendChild(typEl); turn.appendChild(txtEl);
    _pinned = true; scrollBottom();
    lock(true);

    // Throttled streaming render: at most one paint per ~80ms regardless of
    // token rate. Avoids re-parsing the whole answer on every token; the final
    // authoritative (syntax-highlighted) render happens once in finish().
    function streamRender() {
      var nowT = Date.now();
      if (nowT - _lastRender >= 80) {
        _lastRender = nowT;
        txtEl.innerHTML = md(stream) + '<span class="dda-cur"></span>';
        autoScroll();
      } else if (!_streamTimer) {
        _streamTimer = setTimeout(function () {
          _streamTimer = null; _lastRender = Date.now();
          if (_rid === myId && _streaming) {
            txtEl.innerHTML = md(stream) + '<span class="dda-cur"></span>';
            autoScroll();
          }
        }, 80);
      }
    }

    var endpoint = _mode === 'deep' ? '/deep/stream' : '/query/stream';
    var reqBody  = { question: question, history: _hist.slice(-6) };
    if (_mode === 'deep') reqBody.max_rounds = 4;

    var buf = '', stream = '', result = null, gotToken = false;

    fetch(API + endpoint, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(reqBody), signal: _ctrl.signal,
    }).then(function (res) {
      if (!res.ok || !res.body) throw new Error('HTTP ' + res.status);
      var reader = res.body.getReader(), dec = new TextDecoder();
      function pump() {
        if (_rid !== myId) return;
        return reader.read().then(function (chunk) {
          if (chunk.done) { finish(myId, question, turnMode, research, typEl, txtEl, stream, result); return; }
          buf += dec.decode(chunk.value, { stream: true });
          var p = parseSse(buf); buf = p.remainder;
          p.events.forEach(function (ev) {
            if (ev.event === 'ping') return;
            try {
              var d = JSON.parse(ev.data);
              if (ev.event === 'token') {
                if (!gotToken) { typEl.style.display = 'none'; gotToken = true; _streaming = true; }
                stream += d.text || '';
                streamRender();
              } else if (ev.event === 'trace') {
                typEl.style.display = 'none'; addStep(research, d);
              } else if (ev.event === 'result') {
                result = d;
              } else if (ev.event === 'error') {
                throw new Error(d.detail || 'Failed');
              }
            } catch (e2) { if (ev.event === 'error') throw e2; }
          });
          return pump();
        });
      }
      return pump();
    }).catch(function (err) {
      if (err.name === 'AbortError' || _rid !== myId) return;
      _streaming = false;
      if (_streamTimer) { clearTimeout(_streamTimer); _streamTimer = null; }
      typEl.style.display = 'none';
      txtEl.innerHTML = '<span class="dda-err">' + esc(err.message || 'Something went wrong') + '</span>';
    }).finally(function () { if (_rid === myId) lock(false); });
  }

  function finish(myId, question, turnMode, research, typEl, txtEl, stream, res) {
    if (_rid !== myId) return;
    // End streaming so the final render runs the syntax highlighter.
    _streaming = false;
    if (_streamTimer) { clearTimeout(_streamTimer); _streamTimer = null; }
    typEl.style.display = 'none';
    var cur = txtEl.querySelector('.dda-cur'); if (cur) cur.remove();
    // Collapse the live research trace once the answer has landed — it stays
    // available on demand but no longer competes with the answer for space.
    if (research) { research.classList.add('dda-research-done'); research.open = false; }
    var answer = (res && res.answer) || stream;
    if (!answer) return;
    txtEl.innerHTML = md(answer);
    _hist.push({ role: 'user', content: question });
    _hist.push({ role: 'assistant', content: answer });
    if (_hist.length > 10) _hist = _hist.slice(-10);
    _turns.push({ q: question, a: answer, mode: turnMode });
    if (_turns.length > 20) _turns = _turns.slice(-20);
    if (res) {
      var cites = normalizeCites(res), refs = normalizeRefs(res), inv = normalizeInv(res);
      _savedSources = { cites: cites, refs: refs, inv: inv, mode: turnMode };
      renderChip(cites.length, turnMode);
      renderSources(cites, refs, inv);
    }
    saveThread();
    autoScroll();
  }

  function renderChip(count, mode) {
    chipEl.textContent = (mode === 'deep' ? 'Deep Research' : 'Fast') + (count ? ' · ' + count + ' source' + (count === 1 ? '' : 's') : '');
    chipEl.hidden = false;
  }

  // -- Sources sidebar --------------------------------------------------------
  function citeKey(c) { return (c.file_path || '') + ':' + (c.start_line || ''); }
  function asCite(c) {
    return { file_path: c.file_path, start_line: c.start_line, end_line: c.end_line,
             text: c.text || c.snippet, language: c.language, symbol_names: c.symbol_names };
  }
  function normalizeCites(res) {
    var list = [], seen = {};
    function push(c) {
      if (!c.file_path) return;
      var k = citeKey(c); if (seen[k]) return; seen[k] = 1; list.push(asCite(c));
    }
    // Evidence is the canonical, curated proof set — prefer it.
    (res.evidence || []).forEach(push);
    // Fold in code-bearing citation lists the answer surfaced separately and
    // the old UI silently dropped (relationship + live archive fallback). When
    // no evidence came back, fall back to the raw code/artifact lists too.
    if (!list.length) { (res.code_citations || []).forEach(push); (res.artifact_citations || []).forEach(push); }
    (res.relationship_citations || []).forEach(push);
    (res.live_fallback_citations || []).forEach(push);
    return list.filter(function (c) {
      var p = c.file_path || '';
      return p && p.indexOf('docs/') !== 0 && p.indexOf('.deepdoc') !== 0;
    });
  }
  function normalizeRefs(res) {
    var list = [], seen = {};
    function push(title, url, path) {
      if (!url || url === '#' || seen[url]) return;
      seen[url] = 1; list.push({ title: title || path || 'Doc', url: url, path: path || '' });
    }
    // references[] is canonical; supplement with doc citation lists the old UI
    // dropped (repo docs + generated-doc summaries), then legacy doc_links.
    (res.references || []).forEach(function (r) { push(r.title || r.path, r.url, r.path); });
    (res.repo_doc_citations || []).forEach(function (d) { push(d.title || d.section_name, d.doc_url, d.doc_path); });
    (res.doc_citations || []).forEach(function (d) { push(d.title || d.section_name, d.doc_url, d.doc_path); });
    (res.doc_links || []).forEach(function (d) { push(d.title, d.url, d.doc_path); });
    return list;
  }
  function normalizeInv(res) {
    return (res.file_inventory || []).filter(function (f) {
      var p = f.file_path || '';
      return p && p.indexOf('docs/') !== 0 && p.indexOf('.deepdoc') !== 0;
    });
  }
  // Takes pre-normalized arrays so a sessionStorage restore can re-render the
  // sidebar without the original response object.
  function renderSources(cites, refs, inv) {
    srcEl.innerHTML = '';
    if (!cites.length && !refs.length && !inv.length) {
      srcEl.innerHTML = '<div class="ddp-side-empty">No citations were returned for this answer.</div>';
      return;
    }
    if (cites.length) {
      srcEl.appendChild(sectionTitle('Source evidence', 'click to view'));
      cites.slice(0, 10).forEach(function (c) {
        var snippet = c.text || c.content || '';
        var card = mk('div', { class: 'dda-src-card' + (snippet ? ' dda-src-clickable' : '') });
        var hd = mk('div', { class: 'dda-src-card-hdr' });
        var shortPath = (c.file_path || '').split('/').slice(-3).join('/');
        var lineInfo = c.start_line ? ':' + c.start_line + (c.end_line && c.end_line !== c.start_line ? '–' + c.end_line : '') : '';
        hd.innerHTML = SVG.file + '<span class="dda-src-path">' + esc(shortPath + lineInfo) + '</span>' + (snippet ? '<span class="dda-src-view">View</span>' : '');
        card.appendChild(hd);
        if (snippet) {
          var pre = mk('pre', { class: 'dda-src-pre' }); var code = mk('code', {});
          code.textContent = snippet.slice(0, 600); pre.appendChild(code); card.appendChild(pre);
          card.addEventListener('click', function () { openModal(c, snippet); });
          card.setAttribute('role', 'button'); card.setAttribute('tabindex', '0');
          card.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openModal(c, snippet); } });
        }
        srcEl.appendChild(card);
      });
    }
    if (refs.length) {
      srcEl.appendChild(sectionTitle('Read next', ''));
      refs.slice(0, 5).forEach(function (r) {
        var card = mk('div', { class: 'dda-src-card dda-src-doc' });
        var hd = mk('div', { class: 'dda-src-card-hdr' });
        hd.innerHTML = SVG.doc + '<a class="dda-src-doc-link" href="' + esc(r.url) + '">' + esc(r.title) + '</a>';
        card.appendChild(hd);
        if (r.path) { var p = mk('p', { class: 'dda-src-excerpt' }); p.textContent = r.path; card.appendChild(p); }
        srcEl.appendChild(card);
      });
    }
    // Files explored (deep mode) — the repo files the researcher actually
    // opened/searched, from res.file_inventory. Collapsed by default.
    if (inv.length) {
      var det = mk('details', { class: 'dda-files' });
      det.innerHTML = '<summary class="dda-files-sum">'
        + '<span>Files explored</span><span class="dda-files-n">' + inv.length + '</span></summary>';
      var wrap = mk('div', { class: 'dda-files-bd' });
      inv.slice(0, 24).forEach(function (f) {
        var row = mk('div', { class: 'dda-file-row' });
        var short  = (f.file_path || '').split('/').slice(-3).join('/');
        var ranges = (f.line_ranges || []).slice(0, 3).join(', ');
        row.innerHTML = SVG.file + '<span class="dda-file-path">' + esc(short) + '</span>'
          + (ranges ? '<span class="dda-file-lines">' + esc(ranges) + '</span>' : '');
        wrap.appendChild(row);
      });
      det.appendChild(wrap);
      srcEl.appendChild(det);
    }
  }
  function sectionTitle(label, hint) {
    var h = mk('p', { class: 'ddp-side-title' });
    h.innerHTML = esc(label) + (hint ? ' <span class="ddp-side-hint">— ' + esc(hint) + '</span>' : '');
    return h;
  }

  // -- Research step ----------------------------------------------------------
  // Maps the deep-research SSE `trace` phases (deep_research.py::_emit_trace)
  // to a readable timeline line. Reveals + expands the panel on first event.
  function addStep(research, trace) {
    if (research.hidden) { research.hidden = false; research.open = true; }
    var stepsEl = research.querySelector('.dda-steps');
    var phase = trace.phase || '', icon = '·', label = '';
    var n = function (v) { return v === 1 ? '' : 's'; };
    if (phase === 'start') return;                       // session boot — no row
    if (phase === 'decompose') {
      var cnt = trace.sub_question_count || (trace.sub_questions || []).length;
      icon = '◇'; label = 'Planned ' + cnt + ' sub-question' + n(cnt);
    } else if (phase === 'step_start') {
      icon = '▸'; label = (trace.step ? 'Q' + trace.step + ': ' : '') + String(trace.question || '').slice(0, 80);
    } else if (phase === 'retrieve') {
      icon = '⚡'; label = 'Retrieved ' + (trace.retrieved || 0) + ' evidence chunk' + n(trace.retrieved);
    } else if (phase === 'fallback_start') {
      icon = '↻'; label = 'Checking archived source';
    } else if (phase === 'fallback_done') {
      icon = '↻'; label = 'Added ' + (trace.fallback_hits || 0) + ' archived snippet' + n(trace.fallback_hits);
    } else if (phase === 'tool_call') {
      var a = trace.action || '';
      icon  = a === 'read_file' ? '↗' : a === 'grep' ? '⌕' : '⚡';
      label = a === 'read_file' ? 'Read ' + (String(trace.path || '').split('/').pop() || 'file')
            : a === 'grep'      ? 'Grep /' + String(trace.pattern || '').slice(0, 50) + '/'
            : a === 'search'    ? 'Searched archive'
            : (a || 'tool');
    } else if (phase === 'tool_result') {
      icon = '⤷'; label = String(trace.output_preview || '').replace(/\s+/g, ' ').trim().slice(0, 90);
    } else if (phase === 'step_answer' || phase === 'step_done') {
      icon = '✓'; label = (trace.step ? 'Q' + trace.step + ' ' : '') + 'answered · ' + (trace.chunks_used || 0) + ' chunks';
    } else if (phase === 'synthesise_start') {
      icon = '✦'; label = 'Composing answer from ' + (trace.step_count || 0) + ' step' + n(trace.step_count);
    } else if (phase === 'done') {
      icon = '●'; label = 'Explored ' + (trace.source_count || 0) + ' source' + n(trace.source_count)
            + ' across ' + (trace.step_count || 0) + ' step' + n(trace.step_count);
    } else if (phase === 'ood_abstention') {
      icon = '∅'; label = 'Question appears out of scope';
    } else if (phase === 'retrieve_error') {
      icon = '⚠'; label = 'Retrieval issue: ' + String(trace.error || '').slice(0, 60);
    } else {
      label = String(trace.message || phase).slice(0, 80);
    }
    if (!label) return;
    var s = mk('div', { class: 'dda-step' });
    s.innerHTML = '<span class="dda-step-ic">' + icon + '</span><span class="dda-step-lbl">' + esc(label) + '</span>';
    stepsEl.appendChild(s);
    // Expand the planned sub-questions inline under the decompose row.
    if (phase === 'decompose') {
      (trace.sub_questions || []).forEach(function (sq) {
        var sub = mk('div', { class: 'dda-step dda-step-sub' });
        sub.innerHTML = '<span class="dda-step-ic">·</span><span class="dda-step-lbl">' + esc(String(sq).slice(0, 90)) + '</span>';
        stepsEl.appendChild(sub);
      });
    }
    var meta = research.querySelector('.dda-research-meta');
    if (meta) {
      var steps = stepsEl.querySelectorAll('.dda-step:not(.dda-step-sub)').length;
      meta.textContent = steps + ' step' + n(steps);
    }
    autoScroll();
  }

  // -- Code modal -------------------------------------------------------------
  function openModal(c, snippet) {
    closeModal();
    var lang = c.language || (c.file_path || '').split('.').pop() || '';
    var lineInfo = c.start_line
      ? 'Lines ' + c.start_line + (c.end_line && c.end_line !== c.start_line ? '–' + c.end_line : '')
      : '';
    var syms = (c.symbol_names || []).slice(0, 8);
    var ov = mk('div', { class: 'dda-modal-ov' });
    ov.innerHTML = [
      '<div class="dda-modal" role="dialog" aria-modal="true">',
      '  <div class="dda-modal-hdr">',
      '    <div class="dda-modal-title"><strong></strong><span></span></div>',
      '    <button class="dda-modal-x" aria-label="Close">✕</button>',
      '  </div>',
      syms.length ? '  <div class="dda-modal-meta"><span class="dda-modal-meta-lbl">Symbols</span><span class="dda-modal-tags"></span></div>' : '',
      '  <div class="dda-modal-body"><pre class="dda-modal-pre"><code></code></pre></div>',
      '</div>',
    ].join('');
    ov.querySelector('.dda-modal-title strong').textContent = c.file_path || '';
    ov.querySelector('.dda-modal-title span').textContent = lineInfo + (lang ? (lineInfo ? ' · ' : '') + lang : '');
    if (syms.length) {
      var tagWrap = ov.querySelector('.dda-modal-tags');
      syms.forEach(function (s) { var t = mk('span', { class: 'dda-modal-tag' }); t.textContent = s; tagWrap.appendChild(t); });
    }
    var mcode = ov.querySelector('.dda-modal-pre code');
    mcode.textContent = snippet;
    hlEl(mcode, snippet, lang);
    ov.addEventListener('click', function (e) { if (e.target === ov) closeModal(); });
    ov.querySelector('.dda-modal-x').addEventListener('click', closeModal);
    document.body.appendChild(ov);
    document.body.style.overflow = 'hidden';
    _modal = ov;
  }
  function closeModal() {
    if (!_modal) return;
    _modal.remove(); _modal = null;
    document.body.style.overflow = '';
  }
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeModal(); });

  // -- Helpers ----------------------------------------------------------------
  function lock(on) {
    subEl.disabled = on; inpEl.disabled = on;
    if (!on) setTimeout(function () { inpEl.focus(); }, 0);
  }
  function parseSse(buf) {
    var blocks = buf.split('\n\n'), done = blocks.slice(0, -1), rem = blocks[blocks.length - 1] || '', evs = [];
    done.forEach(function (b) {
      var ev = 'message', dl = [];
      b.split('\n').forEach(function (l) {
        if (l.indexOf('event:') === 0) ev = l.slice(6).trim();
        else if (l.indexOf('data:') === 0) dl.push(l.slice(5).trim());
      });
      if (dl.length) evs.push({ event: ev, data: dl.join('\n') });
    });
    return { events: evs, remainder: rem };
  }
  // Markdown rendering via the bundled markdown-it. html:false means any raw
  // HTML in the model's output is escaped (XSS-safe — the old renderer also
  // never emitted raw HTML). The fence rule is overridden to keep our code-card
  // chrome (language label + copy button) and to run highlight.js — but only
  // once streaming has finished, since _streaming guards that hot path.
  var MD = null;
  function getMD() {
    if (MD) return MD;
    if (!window.markdownit) return null;
    MD = window.markdownit({ html: false, linkify: true, breaks: false });
    // Linkify only explicit []() links and real http(s):// URLs — not bare
    // domains/emails the model may mention in prose (avoids surprise links).
    MD.linkify.set({ fuzzyLink: false, fuzzyEmail: false });
    MD.renderer.rules.fence = function (tokens, idx) {
      var t = tokens[idx];
      var lang = (t.info || '').trim().split(/\s+/)[0];
      var code = t.content.replace(/\n$/, '');
      var inner;
      if (!_streaming && window.hljs && lang && window.hljs.getLanguage(lang)) {
        try { inner = window.hljs.highlight(code, { language: lang, ignoreIllegals: true }).value; }
        catch (e) { inner = esc(code); }
      } else {
        inner = esc(code);
      }
      return '<div class="dda-code-wrap"><div class="dda-code-hdr">'
        + (lang ? '<span class="dda-lang">' + esc(lang) + '</span>' : '<span></span>')
        + '<button class="dda-copy" type="button" data-code="' + esc(code) + '">' + SVG.copy + '<span>Copy</span></button>'
        + '</div><pre class="dda-pre"><code class="hljs">' + inner + '</code></pre></div>';
    };
    return MD;
  }
  function md(text) {
    if (!text) return '';
    var inst = getMD();
    if (inst) return inst.render(text);
    // Fallback only if the bundled lib failed to load: safe escaped paragraphs.
    return '<p>' + esc(text).replace(/\n{2,}/g, '</p><p>').replace(/\n/g, '<br>') + '</p>';
  }
  // Syntax-highlight a <code> element in place (used by the evidence modal).
  function hlEl(codeEl, text, lang) {
    if (!window.hljs) return;
    try {
      codeEl.innerHTML = (lang && window.hljs.getLanguage(lang))
        ? window.hljs.highlight(text, { language: lang, ignoreIllegals: true }).value
        : window.hljs.highlightAuto(text).value;
      codeEl.classList.add('hljs');
    } catch (e) {}
  }
  function esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }
  function mk(tag, attrs) {
    var el = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { el.setAttribute(k, attrs[k]); });
    return el;
  }

  // -- Boot -------------------------------------------------------------------
  var _params = new URLSearchParams(window.location.search);
  var initQ = (_params.get('q') || '').trim();
  setMode(_params.get('mode'));
  var restored = API ? restoreThread() : false;
  if (!API) {
    bodyEl.innerHTML = '<div class="ddp-empty" style="color:#c62828">Backend not configured. Run <code>deepdoc serve</code> first.</div>';
  } else if (initQ && !(restored && _turns[_turns.length - 1].q === initQ)) {
    // Fresh question from the FAB or a shared link. A reload right after
    // asking lands here too, unless the thread already ends with this question.
    ask(initQ);
  } else {
    stripQParam();
    inpEl.focus();
  }
})();
"""


def _ask_page_css() -> str:
    return r"""/* DeepDoc /ask workspace. Regenerated by `deepdoc generate`. */

:root {
  --dd-brand:  var(--md-primary-fg-color, #eb3e25);
  --dd-light:  var(--md-primary-fg-color--light, #ff7a5c);
  --dd-dark:   var(--md-primary-fg-color--dark, #9c2a16);
  --dd-border: var(--md-default-fg-color--lightest, rgba(0,0,0,.07));
  /* Material's own secondary-text token (resolves to ~4.6:1 light / ~4.9:1 slate,
     both >= WCAG AA). The opaque fallback keeps muted text legible if the Material
     vars are ever absent — never the old rgba(...,.5) that failed AA. */
  --dd-muted:  var(--md-default-fg-color--light, #6e6e73);
  --dd-fg:     var(--md-default-fg-color, #1d1d1f);
  --dd-bg:     var(--md-default-bg-color, #fff);
  --dd-code-bg: #1b1d28;
}

/* -- Hide MkDocs chrome on /ask -------------------------------------------- */
.dd-ask-page .md-header,
.dd-ask-page .md-sidebar,
.dd-ask-page .md-footer,
.dd-ask-page .md-tabs { display: none !important; }
.dd-ask-page .md-main { padding: 0 !important; }
.dd-ask-page .md-main__inner { margin: 0; max-width: none; padding: 0; }
.dd-ask-page .md-content { padding: 0 !important; max-width: none !important; }
.dd-ask-page .md-content__inner { padding: 0 !important; margin: 0 !important; }
.dd-ask-page .md-typeset h1:first-child,
.dd-ask-page .md-typeset > hr { display: none; }

/* -- Root shell ------------------------------------------------------------ */
#dd-ask-root {
  position: fixed; inset: 0;
  overflow-y: auto;
  background:
    radial-gradient(50rem 26rem at 88% -12%, color-mix(in srgb, var(--dd-light) 6%, transparent 94%), transparent),
    var(--dd-bg);
  font-family: var(--md-text-font, -apple-system, BlinkMacSystemFont, sans-serif);
  -webkit-font-smoothing: antialiased;
  z-index: 100;
}
#dd-ask-root::-webkit-scrollbar { width: 8px; }
#dd-ask-root::-webkit-scrollbar-thumb { background: var(--md-default-fg-color--lighter, rgba(0,0,0,.1)); border-radius: 8px; }

.ddp {
  width: min(60rem, calc(100vw - 3rem));
  margin: 0 auto;
  padding: 1.1rem 0 8.5rem;
}

/* -- Top row --------------------------------------------------------------- */
.ddp-top { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
.ddp-back, .ddp-clear {
  display: inline-flex; align-items: center; gap: .32rem;
  font-size: .78rem; font-weight: 500; font-family: inherit;
  color: var(--dd-muted); text-decoration: none;
  padding: .3rem .55rem; border-radius: 999px;
  border: 1px solid transparent; background: transparent; cursor: pointer;
  transition: background .12s, color .12s;
}
.ddp-back svg, .ddp-clear svg { width: 12px; height: 12px; }
.ddp-back:hover, .ddp-clear:hover {
  color: var(--dd-dark);
  background: color-mix(in srgb, var(--dd-light) 9%, transparent 91%);
}

/* -- Hero ------------------------------------------------------------------ */
.ddp-hero {
  display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between;
  gap: .7rem; margin: .55rem 0 .85rem;
}
.ddp-hero-main { min-width: 0; }
.ddp-eyebrow {
  display: inline-flex; align-items: center; gap: .4rem; margin: 0 0 .35rem;
  font-size: .64rem; font-weight: 600; letter-spacing: .09em; text-transform: uppercase;
  color: var(--dd-dark);
}
.ddp-title {
  margin: 0; max-width: 42rem;
  font-size: clamp(1.15rem, 1.8vw, 1.45rem); line-height: 1.18; letter-spacing: -.02em;
  font-weight: 600; color: var(--dd-fg);
  overflow-wrap: anywhere;
}
.ddp-lede { margin: .4rem 0 0; max-width: 36rem; font-size: .8rem; line-height: 1.5; color: var(--dd-muted); }
.ddp-chip {
  flex-shrink: 0;
  display: inline-flex; align-items: center;
  border: 1px solid color-mix(in srgb, var(--dd-light) 12%, var(--dd-border) 88%);
  border-radius: 999px; padding: .35rem .7rem;
  font-size: .74rem; font-weight: 600; color: var(--dd-dark);
  background: color-mix(in srgb, var(--dd-bg) 92%, var(--dd-light) 8%);
}
.ddp-chip[hidden] { display: none; }

/* -- Grid: answer panel + supporting context ------------------------------- */
.ddp-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(15rem, 0.78fr);
  gap: .85rem; align-items: start;
}
.ddp-grid > * { min-width: 0; }
.ddp-panel, .ddp-side {
  border: 1px solid color-mix(in srgb, var(--dd-light) 9%, var(--dd-border) 91%);
  border-radius: .7rem;
  background: color-mix(in srgb, var(--dd-bg) 98%, var(--dd-light) 2%);
  box-shadow: 0 1px 2px rgba(17,24,39,.04), 0 5px 16px rgba(131, 39, 25, .035);
}
.ddp-panel-hd {
  padding: .7rem .9rem .55rem;
  border-bottom: 1px solid color-mix(in srgb, var(--dd-light) 8%, var(--dd-border) 92%);
}
.ddp-panel-q {
  margin: 0; font-size: .64rem; font-weight: 600; letter-spacing: .08em; text-transform: uppercase;
  color: var(--dd-muted);
}
.ddp-panel-bd { padding: .8rem .9rem .9rem; }

/* -- Conversation turns ----------------------------------------------------- */
.dda-turn + .dda-turn {
  border-top: 1px solid color-mix(in srgb, var(--dd-light) 8%, var(--dd-border) 92%);
  margin-top: 1rem; padding-top: 1rem;
}
.dda-turn-q { margin: 0 0 .55rem; }
.dda-turn-q-lbl {
  display: block; margin-bottom: .15rem;
  font-size: .62rem; font-weight: 600; letter-spacing: .08em; text-transform: uppercase;
  color: var(--dd-muted);
}
.dda-turn-q-txt {
  margin: 0; font-size: .95rem; font-weight: 600; line-height: 1.35;
  color: var(--dd-fg); overflow-wrap: anywhere;
}
.ddp-empty {
  border: 1px dashed color-mix(in srgb, var(--dd-light) 18%, var(--dd-border) 82%);
  border-radius: .6rem; padding: .85rem .9rem;
  color: var(--dd-muted); font-size: .82rem; line-height: 1.55;
  background: color-mix(in srgb, var(--dd-bg) 96%, var(--dd-light) 4%);
}

/* -- Sidebar --------------------------------------------------------------- */
.ddp-side { position: sticky; top: 1.1rem; }
.ddp-side-hd {
  padding: .7rem .9rem .55rem;
  border-bottom: 1px solid color-mix(in srgb, var(--dd-light) 8%, var(--dd-border) 92%);
}
.ddp-side-hd h2 { margin: 0; font-size: .8rem; font-weight: 600; color: var(--dd-fg); }
.ddp-side-hd p { margin: .25rem 0 0; font-size: .75rem; color: var(--dd-muted); line-height: 1.45; }
.ddp-side-bd { padding: .7rem .8rem .85rem; display: flex; flex-direction: column; gap: .5rem; }
.ddp-side-empty { font-size: .8rem; color: var(--dd-muted); line-height: 1.5; }
.ddp-side-title { margin: .3rem 0 .05rem; font-size: .74rem; font-weight: 600; color: var(--dd-dark); }
.ddp-side-hint { font-weight: 400; font-size: .7rem; color: var(--dd-muted); }

/* -- Research steps -------------------------------------------------------- */
.dda-steps {
  display: flex; flex-direction: column; gap: .22rem;
  border: 1px solid color-mix(in srgb, var(--dd-light) 10%, var(--dd-border) 90%);
  border-radius: .8rem; padding: .65rem .8rem; margin-bottom: .85rem;
  background: color-mix(in srgb, var(--dd-bg) 97%, var(--dd-light) 3%);
}
.dda-steps:empty { display: none; }
.dda-steps-done { opacity: .4; transition: opacity .4s ease; }
.dda-step {
  display: flex; align-items: baseline; gap: .4rem; font-size: .73rem;
  font-family: var(--md-code-font, ui-monospace, 'SF Mono', monospace);
  color: var(--dd-muted); line-height: 1.5; animation: dda-fadein .15s ease both;
}
.dda-step-ic { flex-shrink: 0; color: color-mix(in srgb, var(--dd-brand) 65%, var(--dd-muted) 35%); }
.dda-step-lbl { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dda-step-sub { padding-left: 1.1rem; opacity: .82; }
@keyframes dda-fadein { from { opacity: 0; transform: translateY(2px); } to { opacity: 1; transform: none; } }

/* -- Research panel (collapsible trace) ------------------------------------ */
.dda-research {
  border: 1px solid color-mix(in srgb, var(--dd-light) 10%, var(--dd-border) 90%);
  border-radius: .8rem; margin-bottom: .85rem;
  background: color-mix(in srgb, var(--dd-bg) 97%, var(--dd-light) 3%);
}
.dda-research[open] { padding-bottom: .35rem; }
.dda-research-sum {
  display: flex; align-items: center; gap: .45rem; cursor: pointer;
  padding: .55rem .8rem; font-size: .74rem; font-weight: 600; color: var(--dd-dark);
  list-style: none; user-select: none;
}
.dda-research-sum::-webkit-details-marker { display: none; }
.dda-research-ic { color: var(--dd-brand); }
.dda-research-lbl { flex: 1; }
.dda-research-meta { font-weight: 400; font-size: .7rem; color: var(--dd-muted); }
.dda-research[open] .dda-research-sum { border-bottom: 1px solid color-mix(in srgb, var(--dd-light) 8%, var(--dd-border) 92%); }
.dda-research .dda-steps { border: 0; background: none; padding: .55rem .8rem .2rem; margin: 0; }
.dda-research-done { opacity: .72; }

/* -- Files explored (collapsible) ------------------------------------------ */
.dda-files {
  margin-top: .85rem; border: 1px solid color-mix(in srgb, var(--dd-light) 10%, var(--dd-border) 90%);
  border-radius: .7rem; background: color-mix(in srgb, var(--dd-bg) 98%, var(--dd-light) 2%);
}
.dda-files-sum {
  display: flex; align-items: center; justify-content: space-between; cursor: pointer;
  padding: .5rem .7rem; font-size: .74rem; font-weight: 600; color: var(--dd-dark);
  list-style: none; user-select: none;
}
.dda-files-sum::-webkit-details-marker { display: none; }
.dda-files-n {
  font-size: .66rem; font-weight: 600; color: var(--dd-muted);
  background: color-mix(in srgb, var(--dd-light) 12%, transparent 88%);
  border-radius: 999px; padding: .05rem .42rem;
}
.dda-files-bd { padding: .15rem .35rem .45rem; display: flex; flex-direction: column; }
.dda-file-row {
  display: flex; align-items: center; gap: .4rem; padding: .28rem .4rem;
  font-size: .72rem; color: var(--dd-muted); border-radius: .45rem;
  font-family: var(--md-code-font, ui-monospace, 'SF Mono', monospace);
}
.dda-file-row svg { width: 12px; height: 12px; flex-shrink: 0; opacity: .7; }
.dda-file-path { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
.dda-file-lines { flex-shrink: 0; font-size: .66rem; opacity: .8; }

/* -- Typing ---------------------------------------------------------------- */
.dda-typing { display: flex; align-items: center; gap: 4px; padding: .35rem .1rem; }
.dda-typing span {
  display: block; width: 6px; height: 6px; border-radius: 50%;
  background: color-mix(in srgb, var(--dd-brand) 50%, var(--dd-muted) 50%);
  animation: dda-bounce .85s ease-in-out infinite;
}
.dda-typing span:nth-child(2) { animation-delay: .14s; }
.dda-typing span:nth-child(3) { animation-delay: .28s; }
@keyframes dda-bounce { 0%, 80%, 100% { transform: scale(.6); opacity: .3; } 40% { transform: scale(1); opacity: 1; } }

/* -- Answer text ----------------------------------------------------------- */
.dda-txt { font-size: .88rem; line-height: 1.72; color: var(--dd-fg); overflow-wrap: anywhere; }
.dda-txt:empty { display: none; }
.dda-txt code {
  border: 1px solid color-mix(in srgb, var(--dd-light) 10%, var(--dd-border) 90%);
  background: color-mix(in srgb, var(--dd-bg) 92%, var(--dd-light) 8%);
  color: var(--dd-dark);
  padding: .08em .38em; border-radius: .4rem;
  font-size: .84em; font-family: var(--md-code-font, ui-monospace, 'SF Mono', monospace);
}
.dda-txt h1 { font-size: 1.15em; font-weight: 600; margin: 1rem 0 .3rem; letter-spacing: -.01em; }
.dda-txt h2 { font-size: 1.05em; font-weight: 600; margin: .9rem 0 .25rem; }
.dda-txt h3 { font-size: .98em; font-weight: 600; margin: .8rem 0 .2rem; }
.dda-txt p { margin: .55rem 0; }
.dda-txt ul, .dda-txt ol { padding-left: 1.3rem; margin: .45rem 0; }
.dda-txt li { margin: .2rem 0; }
.dda-txt > :first-child { margin-top: 0; }
.dda-txt > :last-child { margin-bottom: 0; }
.dda-txt strong { font-weight: 600; }
.dda-txt a { color: var(--dd-dark); text-decoration-color: color-mix(in srgb, var(--dd-brand) 36%, currentColor 64%); }
.dda-txt a:hover { color: var(--dd-brand); }
.dda-txt ul ul, .dda-txt ol ol, .dda-txt ul ol, .dda-txt ol ul { margin: .15rem 0; }
.dda-txt blockquote {
  margin: .7rem 0; padding: .15rem .9rem;
  border-left: 3px solid color-mix(in srgb, var(--dd-brand) 40%, var(--dd-border) 60%);
  color: var(--dd-muted);
}
.dda-txt hr { border: 0; border-top: 1px solid var(--dd-border); margin: 1.1rem 0; }
.dda-txt table { width: 100%; border-collapse: collapse; margin: .8rem 0; font-size: .92em; }
.dda-txt th, .dda-txt td {
  border: 1px solid color-mix(in srgb, var(--dd-light) 12%, var(--dd-border) 88%);
  padding: .4rem .6rem; text-align: left; vertical-align: top;
}
.dda-txt th { background: color-mix(in srgb, var(--dd-bg) 90%, var(--dd-light) 10%); font-weight: 600; }

/* -- Code blocks in answer (dark, traffic-light header) -------------------- */
.dda-code-wrap {
  margin: .8rem 0; border-radius: .85rem;
  border: 1px solid color-mix(in srgb, var(--dd-light) 8%, var(--dd-border) 92%);
  background: linear-gradient(180deg, rgba(36,38,53,.98), rgba(20,21,32,1));
  box-shadow: 0 12px 30px rgba(17,24,39,.14); overflow: hidden;
}
.dda-code-hdr {
  display: flex; align-items: center; justify-content: space-between;
  padding: .45rem .7rem; border-bottom: 1px solid rgba(255,255,255,.06); background: rgba(255,255,255,.03);
}
.dda-lang {
  font-size: .64rem; font-weight: 600; letter-spacing: .07em; text-transform: uppercase;
  font-family: var(--md-code-font, ui-monospace, 'SF Mono', monospace); color: rgba(226,232,240,.66);
}
.dda-copy {
  display: inline-flex; align-items: center; gap: .25rem; padding: .18rem .45rem;
  background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.08);
  border-radius: 6px; font-size: .64rem; font-family: inherit; color: rgba(226,232,240,.76);
  cursor: pointer; transition: background .1s, color .1s;
}
.dda-copy svg { width: 9px; height: 9px; }
.dda-copy:hover { background: rgba(255,255,255,.1); color: #fff; }
.dda-copy-ok { color: #a6e3a1 !important; }
.dda-pre {
  margin: 0; padding: .8rem .95rem; overflow-x: auto; font-size: .78rem; line-height: 1.65;
  font-family: var(--md-code-font, ui-monospace, 'SF Mono', monospace); white-space: pre;
  color: #e5e7eb; background: var(--dd-code-bg);
}
.dda-pre code { background: none; padding: 0; border: none; color: #e5e7eb; font-family: inherit; }
/* hljs token colors render on our card background, not the theme's own block bg/padding. */
.dda-pre code.hljs, .dda-modal-pre code.hljs { background: transparent; padding: 0; }
.dda-err { color: #c62828; font-size: .86rem; }

/* -- Streaming cursor ------------------------------------------------------ */
@keyframes dda-blink { 50% { opacity: 0; } }
.dda-cur {
  display: inline-block; width: 2px; height: .9em; background: var(--dd-brand);
  border-radius: 1px; vertical-align: text-bottom; margin-left: 2px; animation: dda-blink .55s step-end infinite;
}

/* -- Source cards ---------------------------------------------------------- */
.dda-src-card {
  border: 1px solid color-mix(in srgb, var(--dd-light) 10%, var(--dd-border) 90%);
  border-radius: .75rem; overflow: hidden; background: var(--dd-bg);
  box-shadow: 0 1px 2px rgba(131, 39, 25, .03);
  transition: transform .15s, border-color .15s, box-shadow .15s;
}
.dda-src-clickable { cursor: pointer; }
.dda-src-clickable:hover {
  transform: translateY(-1px);
  border-color: color-mix(in srgb, var(--dd-brand) 45%, var(--dd-bg) 55%);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--dd-brand) 24%, transparent 76%), 0 10px 22px rgba(193, 51, 31, .07);
}
.dda-src-clickable:focus-visible { outline: 2px solid var(--dd-brand); outline-offset: 2px; }
.dda-src-card-hdr {
  display: flex; align-items: center; gap: .4rem; padding: .42rem .6rem;
  background: color-mix(in srgb, var(--dd-bg) 95%, var(--dd-light) 5%);
  border-bottom: 1px solid color-mix(in srgb, var(--dd-light) 8%, var(--dd-border) 92%);
}
.dda-src-card-hdr svg { width: 11px; height: 11px; flex-shrink: 0; color: var(--dd-muted); }
.dda-src-path {
  flex: 1; min-width: 0; font-family: var(--md-code-font, ui-monospace, 'SF Mono', monospace);
  font-size: .67rem; color: var(--dd-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.dda-src-view {
  flex-shrink: 0; display: inline-flex; align-items: center;
  border: 1px solid color-mix(in srgb, var(--dd-light) 10%, var(--dd-border) 90%);
  border-radius: 999px; padding: .1rem .45rem;
  font-size: .58rem; font-weight: 600; letter-spacing: .04em; text-transform: uppercase;
  color: var(--dd-dark); background: color-mix(in srgb, var(--dd-bg) 92%, var(--dd-light) 8%);
}
.dda-src-view::after { content: ' \2197'; }
.dda-src-pre {
  margin: 0; padding: .55rem .7rem; font-size: .69rem;
  font-family: var(--md-code-font, ui-monospace, 'SF Mono', monospace); line-height: 1.5;
  overflow: hidden; white-space: pre; max-height: 130px; color: var(--dd-fg);
  -webkit-mask-image: linear-gradient(180deg, #000 70%, transparent); mask-image: linear-gradient(180deg, #000 70%, transparent);
}
.dda-src-pre code { background: none; padding: 0; border: none; font-family: inherit; }
.dda-src-doc .dda-src-card-hdr svg { color: var(--dd-brand); }
.dda-src-doc-link {
  font-size: .78rem; font-weight: 600; color: var(--dd-dark); text-decoration: none;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.dda-src-doc-link:hover { text-decoration: underline; }
.dda-src-excerpt {
  padding: .35rem .6rem; margin: 0; font-size: .7rem; color: var(--dd-muted); line-height: 1.45;
  font-family: var(--md-code-font, ui-monospace, 'SF Mono', monospace);
}

/* -- Code modal ------------------------------------------------------------ */
.dda-modal-ov {
  position: fixed; inset: 0; z-index: 9999; display: flex; align-items: center; justify-content: center;
  background: radial-gradient(circle at top, rgba(235,62,37,.1), transparent 30%), rgba(9,11,19,.55);
  backdrop-filter: blur(6px); animation: dda-fadein .15s ease-out;
}
.dda-modal {
  width: min(90vw, 56rem); max-height: 82vh; display: flex; flex-direction: column;
  background: #181a26; border: 1px solid rgba(255,255,255,.08);
  border-radius: 1rem; box-shadow: 0 30px 80px rgba(0,0,0,.5); overflow: hidden;
  animation: dda-scalein .15s ease-out;
}
@keyframes dda-scalein { from { transform: scale(.97); opacity: 0; } to { transform: scale(1); opacity: 1; } }
.dda-modal-hdr {
  display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: .8rem 1rem;
  border-bottom: 1px solid rgba(255,255,255,.06);
  background: linear-gradient(180deg, rgba(255,255,255,.025), rgba(255,255,255,0));
}
.dda-modal-title strong { display: block; color: #cdd6f4; font-size: .82rem; font-weight: 600; overflow-wrap: anywhere; }
.dda-modal-title span { display: block; font-size: .72rem; color: #6c7086; margin-top: .1rem; }
.dda-modal-x {
  flex-shrink: 0; width: 1.85rem; height: 1.85rem; display: flex; align-items: center; justify-content: center;
  border: none; border-radius: .5rem; background: transparent; color: #6c7086; font-size: .95rem; cursor: pointer;
  transition: background .12s, color .12s;
}
.dda-modal-x:hover { background: rgba(255,255,255,.08); color: #cdd6f4; }
.dda-modal-meta {
  display: flex; align-items: baseline; gap: .5rem; flex-wrap: wrap; padding: .6rem 1rem;
  background: #12131c; border-bottom: 1px solid rgba(255,255,255,.06);
}
.dda-modal-meta-lbl { flex-shrink: 0; font-size: .65rem; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; color: #585b70; }
.dda-modal-tags { display: flex; flex-wrap: wrap; gap: .3rem; }
.dda-modal-tag {
  padding: .1rem .45rem; border-radius: 999px; font-size: .68rem;
  font-family: var(--md-code-font, ui-monospace, 'SF Mono', monospace);
  background: rgba(137,180,250,.12); color: #89b4fa; border: 1px solid rgba(137,180,250,.15);
}
.dda-modal-body { flex: 1; overflow: auto; background: var(--dd-code-bg); }
.dda-modal-pre {
  margin: 0; padding: .9rem 1rem; font-size: .78rem; line-height: 1.65;
  font-family: var(--md-code-font, ui-monospace, 'SF Mono', monospace); color: #cdd6f4; white-space: pre; tab-size: 4;
}
.dda-modal-pre code { background: none; padding: 0; border: none; color: inherit; font-family: inherit; }

/* -- Bottom dock (follow-up) ----------------------------------------------- */
.ddp-dock-shell {
  position: fixed; left: 50%; bottom: clamp(.8rem, 1.6vw, 1.2rem); transform: translateX(-50%);
  z-index: 120; width: min(42rem, calc(100vw - 2rem)); pointer-events: none;
}
.ddp-dock {
  pointer-events: auto;
  border: 1px solid color-mix(in srgb, var(--dd-light) 7%, var(--dd-border) 93%);
  border-radius: .8rem; padding: .6rem .65rem;
  background: color-mix(in srgb, var(--dd-bg) 80%, transparent 20%);
  box-shadow: 0 8px 26px rgba(131, 39, 25, .07), 0 2px 8px rgba(17,24,39,.05);
  -webkit-backdrop-filter: saturate(1.6) blur(18px); backdrop-filter: saturate(1.6) blur(18px);
}
.ddp-dock-meta { margin-bottom: .5rem; display: flex; align-items: baseline; gap: .6rem; flex-wrap: wrap; }
.dd-eyebrow {
  display: inline-flex; align-items: center; gap: .4rem; margin: 0;
  font-size: .66rem; font-weight: 600; letter-spacing: .08em; text-transform: uppercase;
  color: color-mix(in srgb, var(--dd-dark) 70%, var(--dd-muted) 30%);
}
.dd-eyebrow-dot {
  height: .4rem; width: .4rem; border-radius: 999px;
  background: color-mix(in srgb, var(--dd-brand) 72%, #fff 28%);
  box-shadow: 0 0 0 .16rem color-mix(in srgb, var(--dd-light) 14%, transparent 86%);
  animation: dd-pulse 1.6s ease-in-out infinite;
}
@keyframes dd-pulse {
  0% { box-shadow: 0 0 0 0 rgba(235, 62, 37, .28); }
  70% { box-shadow: 0 0 0 .38rem rgba(235, 62, 37, 0); }
  100% { box-shadow: 0 0 0 0 rgba(235, 62, 37, 0); }
}
.ddp-dock-sub { margin: 0; font-size: .75rem; color: var(--dd-muted); }
.ddp-modes { display: flex; gap: .35rem; margin-bottom: .55rem; }
.ddp-mode {
  border: 1px solid color-mix(in srgb, var(--dd-light) 10%, var(--dd-border) 90%);
  border-radius: 999px; padding: .28rem .7rem; font-size: .74rem; font-weight: 600; font-family: inherit;
  cursor: pointer; color: var(--dd-muted);
  background: color-mix(in srgb, var(--dd-bg) 92%, var(--dd-light) 8%);
  transition: background .16s, color .16s, border-color .16s;
}
.ddp-mode:hover { color: var(--dd-dark); }
.ddp-mode-on {
  border-color: color-mix(in srgb, var(--dd-brand) 40%, var(--dd-border) 60%);
  color: var(--dd-dark); background: color-mix(in srgb, var(--dd-bg) 74%, var(--dd-light) 26%);
}
.ddp-dock-row { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: .5rem; align-items: center; }
#ddp-inp {
  resize: none; border: 1px solid color-mix(in srgb, var(--dd-light) 8%, var(--dd-border) 92%);
  border-radius: .8rem; background: var(--dd-bg); padding: .55rem .8rem;
  font-size: .84rem; font-family: inherit; outline: none; color: var(--dd-fg); line-height: 1.45;
  min-height: 2.4rem; max-height: 8rem; overflow-y: auto;
  transition: outline .12s, border-color .12s;
}
#ddp-inp:focus { outline: 2px solid color-mix(in srgb, var(--dd-light) 22%, transparent 78%); outline-offset: 1px; }
#ddp-inp::placeholder { color: color-mix(in srgb, var(--dd-muted) 65%, transparent 35%); }
#ddp-inp:disabled { opacity: .5; }
#ddp-sub {
  display: inline-flex; align-items: center; gap: .35rem;
  border: none; border-radius: 999px; padding: .55rem 1rem; cursor: pointer;
  font-size: .8rem; font-weight: 600; font-family: inherit; color: #fff;
  background: linear-gradient(135deg, var(--dd-light), var(--dd-brand) 60%, var(--dd-dark));
  box-shadow: 0 6px 16px rgba(193, 51, 31, .18);
  transition: transform .16s, box-shadow .16s, filter .16s;
}
#ddp-sub svg { width: 13px; height: 13px; }
#ddp-sub:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 10px 22px rgba(193, 51, 31, .24); filter: saturate(1.05); }
#ddp-sub:active:not(:disabled) { transform: translateY(0); }
#ddp-sub:disabled { opacity: .55; cursor: wait; }

/* -- Dark mode (Material slate) -------------------------------------------- */
[data-md-color-scheme="slate"] .ddp-panel,
[data-md-color-scheme="slate"] .ddp-side,
[data-md-color-scheme="slate"] .dda-src-card {
  border-color: rgba(255,255,255,.09);
  background: color-mix(in srgb, var(--dd-bg) 92%, #fff 3%);
  box-shadow: 0 12px 34px rgba(0,0,0,.3);
}
[data-md-color-scheme="slate"] .ddp-dock {
  border-color: rgba(255,255,255,.1);
  background: color-mix(in srgb, var(--dd-bg) 70%, transparent 30%);
}
[data-md-color-scheme="slate"] .dda-txt code,
[data-md-color-scheme="slate"] .dda-src-view,
[data-md-color-scheme="slate"] .ddp-chip,
[data-md-color-scheme="slate"] .ddp-mode-on {
  border-color: rgba(255,255,255,.1); background: rgba(255,237,233,.08); color: #ffcabf;
}
[data-md-color-scheme="slate"] .ddp-empty { border-color: rgba(255,255,255,.12); background: rgba(255,255,255,.02); }

/* -- Responsive ------------------------------------------------------------ */
@media (max-width: 900px) {
  .ddp-grid { grid-template-columns: minmax(0, 1fr); }
  .ddp-side { position: static; }
}
@media (max-width: 600px) {
  .ddp { width: calc(100vw - 1.5rem); padding-bottom: 12rem; }
  .ddp-dock-shell { width: calc(100vw - 1rem); }
  .ddp-dock-row { grid-template-columns: minmax(0,1fr); }
  #ddp-sub { justify-content: center; }
}

@media (prefers-reduced-motion: reduce) {
  .dd-eyebrow-dot, .dda-typing span, .dda-cur, .dda-step,
  .dda-modal-ov, .dda-modal { animation: none; }
  .dda-src-clickable, #ddp-sub, .ddp-mode, .ddp-back, .ddp-clear, .dda-copy { transition: none; }
  .dda-src-clickable:hover, #ddp-sub:hover { transform: none; }
}
"""


def _ensure_ask_page(output_dir: Path, project_name: str) -> None:
    """Write docs/ask.md — the full-page AI chat experience."""
    ask_md = output_dir / "ask.md"
    content = f"""\
---
title: "Ask AI"
description: "AI assistant for {project_name}"
hide:
  - navigation
  - toc
search:
  exclude: true
---

<div id="dd-ask-root"></div>
"""
    ask_md.write_text(content, encoding="utf-8")

def _yaml_scalar(value: str) -> str:
    """Render a string as a safe single-line YAML scalar.

    A JSON-encoded string is a valid YAML flow scalar and round-trips any
    punctuation (colons, quotes, trailing periods) without ambiguity.
    """
    return json.dumps(value)
