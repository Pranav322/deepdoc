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
    written.add(_write_deepdoc_config(site_dir, cfg, plan, has_openapi))
    written.add(_write_docs_env(site_dir, output_dir))
    return written


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
        if not _HEX_RE.match(value):
            print(
                f"[deepdoc] site.colors.{key}: {value!r} is not a hex colour "
                f"(expected #rgb or #rrggbb) — using {default}."
            )
            resolved[key] = default
            continue
        resolved[key] = value
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
) -> Path:
    colors = resolve_colors(cfg)
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
        "nav": _build_nav(plan, has_openapi),
        "colors": colors,
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
