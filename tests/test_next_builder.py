"""Tests for the Next.js + Fumadocs site builder (next_builder.py)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from deepdoc.site.builder.next_builder import (
    _build_nav,
    _patch_brand_vars,
    _slug_in_nav,
    _slug_to_title,
    build_next_from_plan,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_plan(nav_structure: dict | None = None, pages: list | None = None):
    plan = SimpleNamespace()
    plan.nav_structure = nav_structure or {}
    plan.pages = pages or []
    return plan


def _make_page(slug: str, title: str):
    return SimpleNamespace(slug=slug, title=title, _b=None)


# ── _slug_to_title ─────────────────────────────────────────────────────────────


def test_slug_to_title_basic():
    assert _slug_to_title("my-page") == "My Page"
    assert _slug_to_title("database-schema") == "Database Schema"
    assert _slug_to_title("index") == "Index"


# ── _slug_in_nav ──────────────────────────────────────────────────────────────


def test_slug_in_nav_finds_top_level_page():
    nav = [{"type": "page", "slug": "index", "title": "Overview"}]
    assert _slug_in_nav(nav, "index") is True
    assert _slug_in_nav(nav, "other") is False


def test_slug_in_nav_finds_nested_item():
    nav = [
        {
            "type": "section",
            "title": "Guide",
            "items": [{"slug": "setup", "title": "Setup"}],
        }
    ]
    assert _slug_in_nav(nav, "setup") is True
    assert _slug_in_nav(nav, "index") is False


# ── _build_nav ────────────────────────────────────────────────────────────────


def test_build_nav_always_includes_whats_changed():
    plan = _make_plan()
    nav = _build_nav(plan, has_openapi=False)
    assert _slug_in_nav(nav, "whats-changed")


def test_build_nav_adds_api_entry_when_openapi():
    plan = _make_plan()
    nav = _build_nav(plan, has_openapi=True)
    assert _slug_in_nav(nav, "api")


def test_build_nav_no_api_entry_without_openapi():
    plan = _make_plan()
    nav = _build_nav(plan, has_openapi=False)
    assert not _slug_in_nav(nav, "api")


def test_build_nav_sections_from_nav_structure():
    pages = [_make_page("setup", "Setup Guide"), _make_page("auth", "Auth")]
    plan = _make_plan(
        nav_structure={"Getting Started": ["setup", "auth"]},
        pages=pages,
    )
    nav = _build_nav(plan, has_openapi=False)
    sections = [e for e in nav if e.get("type") == "section"]
    assert len(sections) == 1
    assert sections[0]["title"] == "Getting Started"
    slugs = [i["slug"] for i in sections[0]["items"]]
    assert "setup" in slugs
    assert "auth" in slugs


def test_build_nav_uses_page_title_not_slug():
    pages = [_make_page("db-schema", "Database Schema")]
    plan = _make_plan(
        nav_structure={"Data": ["db-schema"]},
        pages=pages,
    )
    nav = _build_nav(plan, has_openapi=False)
    section = next(e for e in nav if e.get("type") == "section")
    assert section["items"][0]["title"] == "Database Schema"


def test_build_nav_overview_slug_becomes_top_level_page():
    pages = [_make_page("index", "Overview"), _make_page("setup", "Setup")]
    plan = _make_plan(
        nav_structure={"Guide": ["index", "setup"]},
        pages=pages,
    )
    nav = _build_nav(plan, has_openapi=False)
    top_pages = [e for e in nav if e.get("type") == "page"]
    assert any(e["slug"] == "index" for e in top_pages)
    # index should NOT appear inside the section too
    sections = [e for e in nav if e.get("type") == "section"]
    if sections:
        section_slugs = [i["slug"] for i in sections[0]["items"]]
        assert "index" not in section_slugs


# ── _patch_brand_vars ─────────────────────────────────────────────────────────


_SAMPLE_CSS = """\
@import "fumadocs-ui/style.css";

/* Brand colors — overwritten by `deepdoc generate` with project values */
:root {
  --brand: #eb3e25;
  --brand-light: #ef624e;
  --brand-dark: #c1331f;
}

.dd-prose { color: var(--brand); }
"""


def test_patch_brand_vars_replaces_colors():
    patched = _patch_brand_vars(_SAMPLE_CSS, "#123456", "#abcdef", "#000000")
    assert "--brand: #123456;" in patched
    assert "--brand-light: #abcdef;" in patched
    assert "--brand-dark: #000000;" in patched
    # prose style should be preserved
    assert ".dd-prose" in patched


def test_patch_brand_vars_unchanged_when_no_block():
    css = ".foo { color: red; }"
    assert _patch_brand_vars(css, "#000", "#111", "#222") == css


# ── build_next_from_plan (integration) ───────────────────────────────────────


def _minimal_cfg(primary: str = "#eb3e25") -> dict[str, Any]:
    return {
        "project_name": "Test Docs",
        "site": {"colors": {"primary": primary, "light": "#ef624e", "dark": "#c1331f"}},
        "chatbot": {"enabled": False},
    }


def test_build_next_from_plan_creates_site_dir(tmp_path: Path):
    plan = _make_plan()
    build_next_from_plan(tmp_path, tmp_path / "docs", _minimal_cfg(), plan)
    assert (tmp_path / "site").is_dir()


def test_build_next_from_plan_writes_deepdoc_config(tmp_path: Path):
    plan = _make_plan()
    build_next_from_plan(tmp_path, tmp_path / "docs", _minimal_cfg(), plan)
    cfg_path = tmp_path / "site" / "deepdoc.config.json"
    assert cfg_path.exists()
    cfg = json.loads(cfg_path.read_text())
    assert cfg["project_name"] == "Test Docs"
    assert "nav" in cfg
    assert "colors" in cfg
    assert "chatbot" in cfg


def test_build_next_from_plan_config_colors(tmp_path: Path):
    plan = _make_plan()
    build_next_from_plan(tmp_path, tmp_path / "docs", _minimal_cfg("#ff0000"), plan)
    cfg = json.loads((tmp_path / "site" / "deepdoc.config.json").read_text())
    assert cfg["colors"]["primary"] == "#ff0000"


def test_build_next_from_plan_copies_package_json(tmp_path: Path):
    plan = _make_plan()
    build_next_from_plan(tmp_path, tmp_path / "docs", _minimal_cfg(), plan)
    pkg = tmp_path / "site" / "package.json"
    assert pkg.exists()
    data = json.loads(pkg.read_text())
    assert "fumadocs-ui" in data.get("dependencies", {})


def test_build_next_from_plan_writes_globals_css(tmp_path: Path):
    plan = _make_plan()
    build_next_from_plan(tmp_path, tmp_path / "docs", _minimal_cfg("#aabbcc"), plan)
    css = (tmp_path / "site" / "app" / "globals.css").read_text()
    assert "--brand: #aabbcc;" in css


def test_build_next_from_plan_removes_mkdocs_yml(tmp_path: Path):
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    (site_dir / "mkdocs.yml").write_text("site_name: old\n")
    plan = _make_plan()
    build_next_from_plan(tmp_path, tmp_path / "docs", _minimal_cfg(), plan)
    assert not (site_dir / "mkdocs.yml").exists()


def test_build_next_from_plan_does_not_overwrite_custom_files(tmp_path: Path):
    plan = _make_plan()
    # First run — copies template
    build_next_from_plan(tmp_path, tmp_path / "docs", _minimal_cfg(), plan)
    # User edits a non-overwrite file
    custom_layout = tmp_path / "site" / "app" / "layout.tsx"
    custom_layout.write_text("// custom layout\n")
    # Second run — should NOT overwrite the custom layout
    build_next_from_plan(tmp_path, tmp_path / "docs", _minimal_cfg(), plan)
    assert custom_layout.read_text() == "// custom layout\n"


def test_build_next_from_plan_always_overwrites_config(tmp_path: Path):
    plan = _make_plan()
    build_next_from_plan(tmp_path, tmp_path / "docs", _minimal_cfg("#111111"), plan)
    # Run again with different color — config must be updated
    build_next_from_plan(tmp_path, tmp_path / "docs", _minimal_cfg("#222222"), plan)
    cfg = json.loads((tmp_path / "site" / "deepdoc.config.json").read_text())
    assert cfg["colors"]["primary"] == "#222222"


def test_build_next_from_plan_chatbot_config(tmp_path: Path):
    cfg = {
        "project_name": "Chatbot Docs",
        "site": {"colors": {}},
        "chatbot": {
            "enabled": True,
            "backend": {"base_url": "http://localhost:8100"},
        },
    }
    plan = _make_plan()
    build_next_from_plan(tmp_path, tmp_path / "docs", cfg, plan)
    data = json.loads((tmp_path / "site" / "deepdoc.config.json").read_text())
    assert data["chatbot"]["enabled"] is True
    assert data["chatbot"]["backend_url"] == "http://localhost:8100"
