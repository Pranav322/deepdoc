"""Next.js + Fumadocs site builder for deepdoc-generated documentation.

Replaces mkdocs_builder.py. Uses @shikijs/rehype + remark pipeline (no MDX
JSX compiler) so LLM-generated content never causes build failures.

Entry point: build_next_from_plan()
"""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...v2_models import DocPlan

# ── constants ────────────────────────────────────────────────────────────────

_TEMPLATE_DIR = Path(__file__).parent / "next_template"

_DEFAULT_PRIMARY = "#eb3e25"
_DEFAULT_LIGHT = "#ef624e"
_DEFAULT_DARK = "#c1331f"

_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\Z")

from .presets import PRESETS as _PRESET_TOKENS

_PRESETS = tuple(_PRESET_TOKENS)

_TOC_STYLES = ("clerk", "normal")

# The Fumadocs design tokens that may be overridden via site.theme.tokens.
_FD_TOKENS = (
    "background", "foreground", "muted", "muted-foreground", "popover",
    "popover-foreground", "card", "card-foreground", "border", "primary",
    "primary-foreground", "secondary", "secondary-foreground", "accent",
    "accent-foreground", "ring", "error", "warning", "success", "info",
)


def _warn(message: str) -> None:
    """Report a bad config value without failing the build.

    A typo in a colour must never stop a site from being generated; it falls
    back to the default and says so.
    """
    print(f"[deepdoc] {message}")


def _valid_hex(value: str) -> bool:
    return bool(_HEX_RE.match(value))


# ── public API ────────────────────────────────────────────────────────────────


def build_next_from_plan(
    repo_root: Path,
    output_dir: Path,
    cfg: dict[str, Any],
    plan: DocPlan,
    has_openapi: bool = False,
) -> set[Path]:
    """Generate the Next.js + Fumadocs site scaffold and per-run config files.

    Args:
        repo_root:   Repository root.
        output_dir:  Path to the generated docs directory.
        cfg:         Full ``.deepdoc.yaml`` config dict.
        plan:        Planned documentation structure with nav_structure.
        has_openapi: Whether an OpenAPI spec was staged (adds API nav entry).
    """
    site_dir = repo_root / str(cfg.get("site_dir") or "deepdoc-site")
    site_dir.mkdir(parents=True, exist_ok=True)

    written = _copy_template_files(site_dir)
    written |= _copy_brand_assets(site_dir, repo_root, cfg)
    written.add(_write_deepdoc_config(site_dir, cfg, plan, has_openapi, repo_root, output_dir))
    written.add(_write_docs_env(site_dir, output_dir))
    return written


def _copy_brand_assets(site_dir: Path, repo_root: Path, cfg: dict[str, Any]) -> set[Path]:
    """Copy the configured logo/favicon into ``<site_dir>/public/``.

    Paths are resolved against the repository root. Next serves ``public/`` at
    the site root, so the page references them as ``/<filename>``.
    """
    site_cfg = cfg.get("site") or {}
    written: set[Path] = set()
    for key in ("logo", "logo_dark", "favicon"):
        rel = str(site_cfg.get(key) or "").strip()
        if not rel:
            continue
        src = (repo_root / rel).resolve()
        if not src.is_file():
            _warn(f"site.{key}: {rel!r} not found — skipping.")
            continue
        dst = site_dir / "public" / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        written.add(dst)
    return written


def brand_asset_urls(repo_root: Path, cfg: dict[str, Any]) -> dict[str, str]:
    """Public URLs for the brand assets that actually exist on disk."""
    site_cfg = cfg.get("site") or {}
    urls: dict[str, str] = {}
    for key in ("logo", "logo_dark", "favicon"):
        rel = str(site_cfg.get(key) or "").strip()
        if not rel:
            continue
        src = (repo_root / rel).resolve()
        if src.is_file():
            urls[key] = f"/{src.name}"
    return urls


def resolve_colors(cfg: dict[str, Any]) -> dict[str, str]:
    """Resolve the brand colours from config, falling back per key.

    Sole owner of colour resolution. ``DEFAULT_CONFIG`` ships ``site.colors.*``
    as empty strings, so the key *exists* and a plain ``.get(key, default)``
    returns ``""`` rather than the default — which previously emitted the
    invalid declaration ``--brand: ;``. Treat empty/invalid as unset.
    """
    colors = (cfg.get("site") or {}).get("colors") or {}
    resolved: dict[str, str] = {}
    for key, default in (
        ("primary", _DEFAULT_PRIMARY),
        ("light", _DEFAULT_LIGHT),
        ("dark", _DEFAULT_DARK),
    ):
        value = str(colors.get(key) or "").strip()
        if not value:
            resolved[key] = default
            continue
        if not _valid_hex(value):
            _warn(
                f"site.colors.{key}: {value!r} is not a hex colour "
                f"(expected #rgb or #rrggbb) — using {default}."
            )
            resolved[key] = default
            continue
        resolved[key] = value
    return resolved


def resolve_theme(cfg: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalise ``site.theme``.

    Invalid values warn and fall back; nothing here can fail a build.
    """
    theme = (cfg.get("site") or {}).get("theme") or {}

    preset = str(theme.get("preset") or "").strip().lower()
    if preset and preset not in _PRESETS:
        _warn(
            f"site.theme.preset: {preset!r} is not a known preset "
            f"({', '.join(_PRESETS)}) — using the default palette."
        )
        preset = ""

    tokens: dict[str, dict[str, str]] = {"light": {}, "dark": {}}
    raw_tokens = theme.get("tokens") or {}
    for mode in ("light", "dark"):
        for name, value in (raw_tokens.get(mode) or {}).items():
            key = str(name).strip().lstrip("-").removeprefix("color-fd-")
            text = str(value or "").strip()
            if key not in _FD_TOKENS:
                _warn(f"site.theme.tokens.{mode}.{name}: unknown design token — ignored.")
                continue
            if not _valid_hex(text):
                _warn(
                    f"site.theme.tokens.{mode}.{name}: {text!r} is not a hex colour — ignored."
                )
                continue
            tokens[mode][key] = text

    fonts = theme.get("fonts") or {}
    code = theme.get("code_theme") or {}
    return {
        "preset": preset,
        "tokens": tokens,
        # Empty means no webfont is loaded and no external request is made.
        "fonts": {
            "sans": str(fonts.get("sans") or "").strip(),
            "mono": str(fonts.get("mono") or "").strip(),
        },
        "code_theme": {
            "light": str(code.get("light") or "").strip() or "github-light",
            "dark": str(code.get("dark") or "").strip() or "github-dark",
        },
    }


def _font_stack(family: str, fallback: str) -> str:
    return f"'{family}', {fallback}" if family else fallback


_SANS_FALLBACK = "ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
_MONO_FALLBACK = "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace"


def theme_css(theme: dict[str, Any], colors: dict[str, str]) -> str:
    """Compose the theme into one CSS block, injected into <head> at request time.

    Emitted from config rather than baked into ``globals.css`` so that editing
    ``.deepdoc.yaml`` and re-running ``deepdoc serve`` applies it with no
    regeneration.

    Precedence, lowest to highest: preset -> brand -> explicit token overrides.
    Every rule is unlayered, and Fumadocs defines its own tokens inside
    ``@layer theme`` / ``@layer utilities`` — unlayered CSS beats any layered
    rule regardless of specificity or source order, so these always win.
    """
    preset = _PRESET_TOKENS.get(theme.get("preset") or "", {})
    tokens = theme.get("tokens") or {}
    fonts = theme.get("fonts") or {}

    def block(selector: str, decls: list[str]) -> str:
        return f"{selector}{{{''.join(decls)}}}" if decls else ""

    light = [f"--color-fd-{k}:{v};" for k, v in (preset.get("light") or {}).items()]
    dark = [f"--color-fd-{k}:{v};" for k, v in (preset.get("dark") or {}).items()]

    light += [
        f"--brand:{colors['primary']};",
        f"--brand-light:{colors['light']};",
        f"--brand-dark:{colors['dark']};",
        "--color-fd-primary:var(--brand);",
        "--color-fd-ring:var(--brand);",
        f"--font-sans:{_font_stack(fonts.get('sans', ''), _SANS_FALLBACK)};",
        f"--font-mono:{_font_stack(fonts.get('mono', ''), _MONO_FALLBACK)};",
    ]
    dark += [
        "--color-fd-primary:var(--brand-light);",
        "--color-fd-ring:var(--brand-light);",
    ]

    # Explicit overrides come last so they beat both preset and brand.
    light += [f"--color-fd-{k}:{v};" for k, v in (tokens.get("light") or {}).items()]
    dark += [f"--color-fd-{k}:{v};" for k, v in (tokens.get("dark") or {}).items()]

    return block(":root", light) + block(".dark", dark)


def google_fonts_href(theme: dict[str, Any]) -> str:
    """Google Fonts URL for the configured families, or "" when none are set.

    Opt-in by design: with no fonts configured the site makes no external
    request at all.
    """
    families = [f for f in (theme.get("fonts") or {}).values() if f]
    if not families:
        return ""
    parts = "&".join(f"family={f.replace(' ', '+')}:wght@400;500;600;700" for f in families)
    return f"https://fonts.googleapis.com/css2?{parts}&display=swap"


def resolve_chrome(cfg: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalise ``site.chrome`` (layout toggles)."""
    from ...config import DEFAULT_CONFIG

    defaults = DEFAULT_CONFIG["site"]["chrome"]
    chrome = (cfg.get("site") or {}).get("chrome") or {}
    resolved = {key: chrome.get(key, default) for key, default in defaults.items()}

    style = str(resolved.get("toc_style") or "").strip().lower()
    if style not in _TOC_STYLES:
        if style:
            _warn(
                f"site.chrome.toc_style: {style!r} is not valid "
                f"({', '.join(_TOC_STYLES)}) — using 'clerk'."
            )
        style = "clerk"
    resolved["toc_style"] = style

    depth = resolved.get("toc_depth") or [2, 3]
    try:
        levels = sorted({int(d) for d in depth if 1 <= int(d) <= 6})
    except (TypeError, ValueError):
        levels = []
    if not levels:
        _warn(f"site.chrome.toc_depth: {depth!r} is not a list of heading levels 1-6 — using [2, 3].")
        levels = [2, 3]
    resolved["toc_depth"] = levels

    # An edit link without a repository URL would render a dead anchor.
    if resolved.get("edit_link") and not str((cfg.get("site") or {}).get("repo_url") or "").strip():
        _warn("site.chrome.edit_link is on but site.repo_url is empty — disabling the edit link.")
        resolved["edit_link"] = False

    links = []
    for item in resolved.get("links") or []:
        if isinstance(item, dict) and item.get("text") and item.get("url"):
            links.append({"text": str(item["text"]), "url": str(item["url"])})
        else:
            _warn(f"site.chrome.links: {item!r} needs both 'text' and 'url' — ignored.")
    resolved["links"] = links
    return resolved


# ── template scaffolding ──────────────────────────────────────────────────────


def _copy_template_files(site_dir: Path) -> set[Path]:
    """Copy next_template/ → configured site_dir, overwriting every template file.

    The builder owns 100% of ``next_template/``. Previously files were skipped
    when they already existed, which meant template fixes never reached an
    already-generated site — only ``deepdoc.config.json`` and ``globals.css``
    were refreshed, so changes to the layouts, ``lib/*.ts`` or the chatbot never
    arrived on upgrade. Anything a user adds is by definition not part of the
    template and is left alone, as are ``node_modules/``, ``.next/``,
    ``openapi/`` and ``public/``, which live outside it.
    """
    written: set[Path] = set()
    for src in _TEMPLATE_DIR.rglob("*"):
        if src.is_dir():
            continue
        dst = site_dir / src.relative_to(_TEMPLATE_DIR)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        written.add(dst)
    return written


# ── deepdoc.config.json ───────────────────────────────────────────────────────


def _build_nav(plan: DocPlan, has_openapi: bool) -> list[dict]:
    """Convert DocPlan.nav_structure into the JSON nav tree consumed by lib/nav.ts."""
    nav: list[dict] = []

    nav_structure: dict[str, list[str]] = getattr(plan, "nav_structure", {}) or {}

    # Collect all page slugs with their titles for lookup
    slug_to_title: dict[str, str] = {}
    for page in getattr(plan, "pages", []):
        slug = getattr(page, "slug", None)
        title = getattr(page, "title", None)
        if slug and title:
            slug_to_title[slug] = title

    # ── top-level Overview / intro page ──────────────────────────────────────
    overview_slug = _find_overview_slug(plan)
    if overview_slug:
        nav.append({
            "type": "page",
            "title": slug_to_title.get(overview_slug, "Overview"),
            "slug": "/",
        })

    # ── nav sections ─────────────────────────────────────────────────────────
    for section_name, items in nav_structure.items():
        nav_items = []
        for entry in items:
            if isinstance(entry, dict):
                parent_title = entry.get("display_title", _slug_to_title(entry["parent_slug"]))
                parent_slug = entry["parent_slug"]
                children = [{
                    "type": "page",
                    "title": slug_to_title.get(parent_slug, parent_title),
                    "slug": parent_slug,
                }]
                for child_slug in entry.get("children", []):
                    if child_slug == overview_slug:
                        continue
                    children.append({
                        "type": "page",
                        "title": slug_to_title.get(child_slug, _slug_to_title(child_slug)),
                        "slug": child_slug,
                    })
                nav_items.append({
                    "type": "section",
                    "title": parent_title,
                    "items": children,
                })
            elif isinstance(entry, str):
                slug = entry
                if slug == overview_slug:
                    continue
                nav_items.append({
                    "title": slug_to_title.get(slug, _slug_to_title(slug)),
                    "slug": slug,
                })
        if nav_items:
            nav.append({"type": "section", "title": section_name, "items": nav_items})

    # ── What's Changed (always present if it exists) ──────────────────────────
    if not _slug_in_nav(nav, "whats-changed"):
        nav.append({
            "type": "page",
            "title": "What's Changed",
            "slug": "whats-changed",
        })

    # ── API Reference ─────────────────────────────────────────────────────────
    if has_openapi and not _slug_in_nav(nav, "api"):
        nav.append({"type": "page", "title": "API Reference", "slug": "api"})

    return nav


def _find_overview_slug(plan: DocPlan) -> str | None:
    """Return the slug of the introduction / overview page, if any."""
    for page in getattr(plan, "pages", []):
        hints = getattr(page, "_b", None)
        generation_hints = getattr(hints, "generation_hints", None) if hints else None
        if generation_hints and generation_hints.get("is_introduction_page"):
            return getattr(page, "slug", None)
        slug = getattr(page, "slug", "")
        if slug in ("index", "overview", "introduction"):
            return slug
    return None


def _walk_nav(nav: list[dict]):
    """Yield every node in the tree, sections included."""
    for entry in nav:
        yield entry
        if entry.get("items"):
            yield from _walk_nav(entry["items"])


def apply_nav_overrides(
    nav: list[dict],
    nav_cfg: dict[str, Any],
    known_slugs: set[str],
) -> tuple[list[dict], list[str]]:
    """Apply ``site.nav`` overrides to the built nav tree.

    Four ordered passes: rename, hide, extra, then pin/order. Everything is
    derived from the already-saved plan, so reordering a sidebar costs no LLM
    call and no scan.

    An override naming a slug that does not exist is reported as a warning and
    skipped — a stale entry must never break a build.
    """
    warnings: list[str] = []
    rename = {str(k): str(v) for k, v in (nav_cfg.get("rename") or {}).items()}
    hide = {str(s) for s in (nav_cfg.get("hide") or [])}
    pin = [str(s) for s in (nav_cfg.get("pin") or [])]
    sections = [str(s) for s in (nav_cfg.get("sections") or [])]

    for name, values in (("hide", hide), ("pin", set(pin))):
        for slug in sorted(values - known_slugs):
            warnings.append(f"site.nav.{name}: no page named {slug!r}")

    # 1. rename — by slug, or by section title.
    # Track what actually matched: checking afterwards would report a
    # successful section rename as missing, since the old title is gone.
    applied: set[str] = set()
    for node in _walk_nav(nav):
        slug = node.get("slug")
        title = node.get("title")
        if slug and slug in rename:
            node["title"] = rename[slug]
            applied.add(slug)
        elif node.get("type") == "section" and title in rename:
            node["title"] = rename[title]
            applied.add(title)
    for key in sorted(set(rename) - applied):
        warnings.append(f"site.nav.rename: no page or section named {key!r}")

    # 2. hide — drop pages, then any section left empty
    def prune(entries: list[dict]) -> list[dict]:
        kept = []
        for entry in entries:
            if entry.get("slug") in hide and entry.get("type") != "section":
                continue
            if entry.get("items") is not None:
                entry["items"] = prune(entry["items"])
                if not entry["items"]:
                    continue
            kept.append(entry)
        return kept

    nav = prune(nav)

    # 3. extra — hand-written pages and external links
    for item in nav_cfg.get("extra") or []:
        if not isinstance(item, dict) or not item.get("title"):
            warnings.append(f"site.nav.extra: {item!r} needs a 'title'")
            continue
        slug, url = str(item.get("slug") or ""), str(item.get("url") or "")
        if not slug and not url:
            warnings.append(f"site.nav.extra: {item['title']!r} needs a 'slug' or a 'url'")
            continue
        if slug and slug not in known_slugs:
            warnings.append(f"site.nav.extra: no page named {slug!r}")
            continue
        node = {"type": "page", "title": str(item["title"])}
        node["url" if url else "slug"] = url or slug

        section_name = str(item.get("section") or "")
        if not section_name:
            nav.append(node)
            continue
        for entry in nav:
            if entry.get("type") == "section" and entry.get("title") == section_name:
                entry.setdefault("items", []).append(node)
                break
        else:
            nav.append({"type": "section", "title": section_name, "items": [node]})

    # 4. pin, then explicit section order; anything unlisted keeps its position
    if pin:
        pinned = [n for slug in pin for n in nav if n.get("slug") == slug]
        nav = pinned + [n for n in nav if n not in pinned]
    if sections:
        order = {title: i for i, title in enumerate(sections)}
        for title in sections:
            if not any(n.get("title") == title for n in nav):
                warnings.append(f"site.nav.sections: no section named {title!r}")
        nav.sort(key=lambda n: order.get(n.get("title", ""), len(order)))

    return nav, warnings


def _slug_in_nav(nav: list[dict], slug: str) -> bool:
    def walk(entries: list[dict]) -> bool:
        for entry in entries:
            if entry.get("slug") == slug and entry.get("type") != "section":
                return True
            if entry.get("type") == "section" and walk(entry.get("items", [])):
                return True
        return False

    return walk(nav)


def _write_deepdoc_config(
    site_dir: Path,
    cfg: dict[str, Any],
    plan: DocPlan,
    has_openapi: bool,
    repo_root: Path | None = None,
    output_dir: Path | None = None,
) -> Path:
    colors = resolve_colors(cfg)
    theme = resolve_theme(cfg)

    # Slugs the user may legitimately reference: planned pages plus any
    # hand-written .md dropped into the output directory (those already render
    # and are URL-reachable; site.nav.extra is how they reach the sidebar).
    known_slugs = {
        str(getattr(page, "slug", "")) for page in getattr(plan, "pages", []) or []
    }
    if output_dir is not None and output_dir.is_dir():
        known_slugs |= {p.stem for p in output_dir.glob("*.md")}
    known_slugs.discard("")

    nav, nav_warnings = apply_nav_overrides(
        _build_nav(plan, has_openapi),
        (cfg.get("site") or {}).get("nav") or {},
        known_slugs,
    )
    for warning in nav_warnings:
        _warn(warning)

    # Hand-written pages that render but are absent from the sidebar.
    if output_dir is not None and output_dir.is_dir():
        in_nav = {n.get("slug") for n in _walk_nav(nav)}
        planned = {str(getattr(p, "slug", "")) for p in getattr(plan, "pages", []) or []}
        orphans = sorted(
            p.stem for p in output_dir.glob("*.md")
            if p.stem not in in_nav and p.stem not in planned and p.stem != "index"
        )
        if orphans:
            _warn(
                f"{len(orphans)} page(s) are not in the sidebar: {', '.join(orphans[:5])}"
                f"{' …' if len(orphans) > 5 else ''}. Add them under site.nav.extra."
            )
    chatbot_cfg = cfg.get("chatbot", {})
    chatbot_enabled = bool(chatbot_cfg.get("enabled"))
    backend_url = ""
    if chatbot_enabled:
        from ...chatbot.settings import chatbot_backend_base_url
        # Falls back to http://127.0.0.1:{port} when base_url is empty,
        # matching the old MkDocs builder behaviour.
        backend_url = chatbot_backend_base_url(cfg, site_dir.parent)

    config = {
        "project_name": cfg.get("project_name", "Docs"),
        "nav": nav,
        "colors": colors,
        "theme": {
            **theme,
            # Precomposed so the page can inject it verbatim; see theme_css().
            "css": theme_css(theme, colors),
            "google_fonts": google_fonts_href(theme),
        },
        "chrome": resolve_chrome(cfg),
        "brand": brand_asset_urls(repo_root or site_dir.parent, cfg),
        "repo": _repo_info(cfg),
        "labels": {
            str(k): str(v) for k, v in ((cfg.get("site") or {}).get("labels") or {}).items()
        },
        "chatbot": {
            "enabled": chatbot_enabled,
            "backend_url": backend_url,
        },
        "generated_at": datetime.now(timezone.utc).strftime("%b %d, %Y"),
        "commit_sha": _head_commit_sha(site_dir.parent),
    }
    path = site_dir / "deepdoc.config.json"
    _write_json(path, config)
    return path


def _repo_info(cfg: dict[str, Any]) -> dict[str, str]:
    """Split ``site.repo_url`` into the parts Fumadocs' edit-link needs."""
    site_cfg = cfg.get("site") or {}
    url = str(site_cfg.get("repo_url") or "").strip().rstrip("/")
    owner = name = ""
    match = re.search(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?\Z", url)
    if match:
        owner, name = match.group(1), match.group(2)
    return {
        "url": url,
        "owner": owner,
        "name": name,
        "branch": str(site_cfg.get("edit_branch") or "main").strip() or "main",
        "path_prefix": str(site_cfg.get("edit_path_prefix") or "").strip(),
    }


def _head_commit_sha(repo_root: Path) -> str:
    """Return the short (7-char) HEAD commit SHA, or empty string if not in a git repo."""
    try:
        import git as _git
        repo = _git.Repo(repo_root, search_parent_directories=True)
        return repo.head.commit.hexsha[:7]
    except Exception:
        return ""


def _write_docs_env(site_dir: Path, output_dir: Path) -> Path:
    """Tell the Next scaffold where generated Markdown lives at build time."""
    relative_docs = os.path.relpath(output_dir, site_dir).replace("\\", "/")
    path = site_dir / ".env.local"
    path.write_text(f"DEEPDOC_DOCS_DIR={relative_docs}\n", encoding="utf-8")
    return path


# ── helpers ───────────────────────────────────────────────────────────────────


def _slug_to_title(slug: str) -> str:
    return slug.replace("-", " ").title()


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
