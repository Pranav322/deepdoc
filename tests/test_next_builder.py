"""Tests for the Next.js + Fumadocs site builder (next_builder.py)."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from deepdoc.site.builder.next_builder import (
    _DEFAULT_DARK,
    _DEFAULT_LIGHT,
    _DEFAULT_PRIMARY,
    _build_nav,
    _slug_in_nav,
    _slug_to_title,
    build_next_from_plan,
    resolve_colors,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_plan(nav_structure: dict | None = None, pages: list | None = None):
    plan = SimpleNamespace()
    plan.nav_structure = nav_structure or {}
    plan.pages = pages or []
    return plan


def _make_page(slug: str, title: str, *, introduction: bool = False):
    bucket = SimpleNamespace(
        generation_hints={"is_introduction_page": introduction}
    )
    return SimpleNamespace(slug=slug, title=title, _b=bucket)


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
    assert any(e["slug"] == "/" for e in top_pages)
    # index should NOT appear inside the section too
    sections = [e for e in nav if e.get("type") == "section"]
    if sections:
        section_slugs = [i["slug"] for i in sections[0]["items"]]
        assert "index" not in section_slugs


def test_build_nav_introduction_hint_always_links_root():
    pages = [
        _make_page("start-here", "Start Here", introduction=True),
        _make_page("setup", "Setup"),
    ]
    plan = _make_plan(
        nav_structure={"Guide": ["start-here", "setup"]},
        pages=pages,
    )

    nav = _build_nav(plan, has_openapi=False)

    top_pages = [entry for entry in nav if entry.get("type") == "page"]
    assert any(entry["title"] == "Start Here" and entry["slug"] == "/" for entry in top_pages)
    section = next(entry for entry in nav if entry.get("type") == "section")
    assert [item["slug"] for item in section["items"]] == ["setup"]


def test_build_nav_group_keeps_parent_and_child_reachable():
    pages = [
        _make_page("security", "Security"),
        _make_page("security-oauth", "OAuth"),
    ]
    plan = _make_plan(
        nav_structure={
            "Security": [{
                "parent_slug": "security",
                "display_title": "Security",
                "children": ["security-oauth"],
            }]
        },
        pages=pages,
    )

    nav = _build_nav(plan, has_openapi=False)
    top_section = next(entry for entry in nav if entry.get("title") == "Security")
    group = top_section["items"][0]

    assert group["type"] == "section"
    assert [item["slug"] for item in group["items"]] == [
        "security",
        "security-oauth",
    ]
    assert _slug_in_nav(nav, "security")
    assert _slug_in_nav(nav, "security-oauth")


def test_nav_template_recursively_builds_nested_sections():
    template = (
        Path(__file__).parents[1]
        / "deepdoc"
        / "site"
        / "builder"
        / "next_template"
        / "lib"
        / "nav.ts"
    ).read_text()
    assert "function buildNode" in template
    assert ".map(buildNode)" in template


# ── resolve_colors ────────────────────────────────────────────────────────────


def test_resolve_colors_uses_configured_values():
    cfg = {"site": {"colors": {"primary": "#123456", "light": "#abcdef", "dark": "#000000"}}}
    assert resolve_colors(cfg) == {
        "primary": "#123456",
        "light": "#abcdef",
        "dark": "#000000",
    }


def test_resolve_colors_empty_strings_fall_back_to_defaults():
    """Regression: DEFAULT_CONFIG ships site.colors.* as "".

    The key exists, so a plain ``.get(key, default)`` returns "" instead of the
    default and the builder emitted the invalid declaration ``--brand: ;``.
    """
    cfg = {"site": {"colors": {"primary": "", "light": "", "dark": ""}}}
    assert resolve_colors(cfg) == {
        "primary": _DEFAULT_PRIMARY,
        "light": _DEFAULT_LIGHT,
        "dark": _DEFAULT_DARK,
    }


def test_resolve_colors_defaults_from_real_default_config():
    """The shipped defaults must resolve to real hex, never "" ."""
    from deepdoc.config import DEFAULT_CONFIG

    for value in resolve_colors(deepcopy(DEFAULT_CONFIG)).values():
        assert value.startswith("#") and len(value) in (4, 7)


def test_resolve_colors_missing_blocks():
    assert resolve_colors({})["primary"] == _DEFAULT_PRIMARY
    assert resolve_colors({"site": {}})["primary"] == _DEFAULT_PRIMARY
    assert resolve_colors({"site": {"colors": None}})["primary"] == _DEFAULT_PRIMARY


@pytest.mark.parametrize("bad", ["red", "#ff00", "ff0000", "#gggggg", "rgb(1,2,3)"])
def test_resolve_colors_rejects_malformed_hex(bad):
    resolved = resolve_colors({"site": {"colors": {"primary": bad}}})
    assert resolved["primary"] == _DEFAULT_PRIMARY


def test_resolve_colors_accepts_shorthand_hex():
    assert resolve_colors({"site": {"colors": {"primary": "#f00"}}})["primary"] == "#f00"


# ── build_next_from_plan (integration) ───────────────────────────────────────


def _minimal_cfg(primary: str = "#eb3e25") -> dict[str, Any]:
    return {
        "project_name": "Test Docs",
        "site_dir": "site",
        "site": {"colors": {"primary": primary, "light": "#ef624e", "dark": "#c1331f"}},
        "chatbot": {"enabled": False},
    }


def test_build_next_from_plan_creates_site_dir(tmp_path: Path):
    plan = _make_plan()
    build_next_from_plan(tmp_path, tmp_path / "docs", _minimal_cfg(), plan)
    assert (tmp_path / "site").is_dir()


def test_build_next_from_plan_honors_configured_site_dir(tmp_path: Path):
    plan = _make_plan()
    cfg = _minimal_cfg()
    cfg["site_dir"] = "deepdoc-site"
    build_next_from_plan(tmp_path, tmp_path / "deepdoc-docs", cfg, plan)
    assert (tmp_path / "deepdoc-site" / "package.json").is_file()
    assert not (tmp_path / "site").exists()
    assert (
        (tmp_path / "deepdoc-site" / ".env.local").read_text().strip()
        == "DEEPDOC_DOCS_DIR=../deepdoc-docs"
    )


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


def test_build_next_from_plan_writes_colors_to_config(tmp_path: Path):
    """Colours live only in deepdoc.config.json now.

    They are injected into <head> from there at request time, so a colour change
    applies on `deepdoc serve` without regenerating any Markdown.
    """
    plan = _make_plan()
    build_next_from_plan(tmp_path, tmp_path / "docs", _minimal_cfg("#aabbcc"), plan)
    cfg = json.loads((tmp_path / "site" / "deepdoc.config.json").read_text())
    assert cfg["colors"]["primary"] == "#aabbcc"


def test_generated_css_has_no_dead_fumadocs_v14_vars(tmp_path: Path):
    """Guard against the v14 pattern returning.

    Fumadocs v15 renamed colour tokens to --color-fd-* and their values are
    complete colours, so both `--fd-<colour>` and any `hsl(var(...))` wrapper
    are dead. Size vars (--fd-sidebar-width etc.) are still valid.
    """
    plan = _make_plan()
    build_next_from_plan(tmp_path, tmp_path / "docs", _minimal_cfg(), plan)
    site = tmp_path / "site"
    for rel in ("app/globals.css", "app/(main)/layout.tsx", "components/chatbot.tsx"):
        text = (site / rel).read_text()
        assert "hsl(var(" not in text, f"{rel} still wraps a token in hsl()"
        for dead in ("--fd-primary", "--fd-foreground", "--fd-background",
                     "--fd-border", "--fd-muted", "--fd-sidebar-background"):
            assert dead not in text, f"{rel} still references {dead}"


def test_build_next_from_plan_preserves_mkdocs_yml(tmp_path: Path):
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    (site_dir / "mkdocs.yml").write_text("site_name: old\n")
    plan = _make_plan()
    build_next_from_plan(tmp_path, tmp_path / "docs", _minimal_cfg(), plan)
    assert (site_dir / "mkdocs.yml").exists()


def test_build_next_from_plan_refreshes_template_files(tmp_path: Path):
    """The builder owns every file in next_template/.

    Previously template files were skipped when they already existed, so a fix
    to a layout, lib/*.ts or the chatbot never reached an already-generated
    site — only deepdoc.config.json and globals.css were refreshed.
    """
    plan = _make_plan()
    build_next_from_plan(tmp_path, tmp_path / "docs", _minimal_cfg(), plan)

    layout = tmp_path / "site" / "app" / "layout.tsx"
    layout.write_text("// stale\n")
    build_next_from_plan(tmp_path, tmp_path / "docs", _minimal_cfg(), plan)

    assert layout.read_text() != "// stale\n"
    assert "RootProvider" in layout.read_text()


def test_build_next_from_plan_preserves_user_added_files(tmp_path: Path):
    """Files the template does not contain are the user's and must survive."""
    plan = _make_plan()
    build_next_from_plan(tmp_path, tmp_path / "docs", _minimal_cfg(), plan)

    site = tmp_path / "site"
    mine = site / "app" / "my-page" / "page.tsx"
    mine.parent.mkdir(parents=True, exist_ok=True)
    mine.write_text("// mine\n")
    (site / "public").mkdir(exist_ok=True)
    (site / "public" / "logo.svg").write_text("<svg/>")

    build_next_from_plan(tmp_path, tmp_path / "docs", _minimal_cfg(), plan)

    assert mine.read_text() == "// mine\n"
    assert (site / "public" / "logo.svg").read_text() == "<svg/>"


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
        "site_dir": "site",
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


# ── mermaid rendering (template contract) ─────────────────────────────────────


def test_generated_site_ships_mermaid_dark_mode_and_zoom(tmp_path: Path):
    """Diagrams must follow the site theme and open full screen.

    'neutral' is a light mermaid theme; hardcoding it made diagrams unreadable
    in dark mode, and there was no way to zoom a large diagram.
    """
    plan = _make_plan()
    build_next_from_plan(tmp_path, tmp_path / "docs", _minimal_cfg(), plan)
    runner = (tmp_path / "site" / "app" / "components" / "mermaid-runner.tsx").read_text()

    # theme follows the live `.dark` class, and re-renders when it flips
    assert "classList.contains('dark')" in runner
    assert "MutationObserver" in runner
    # the graph source is stashed, since mermaid destroys it on first render
    assert "dataset.src" in runner
    # click-to-fullscreen with zoom + pan + Escape
    assert "MermaidLightbox" in runner
    assert "Escape" in runner

    css = (tmp_path / "site" / "app" / "globals.css").read_text()
    assert ".dd-mermaid-overlay" in css
    assert "cursor: zoom-in" in css


# ── search (template contract) ────────────────────────────────────────────────


def test_generated_site_ships_a_search_endpoint(tmp_path: Path):
    """Search was silently dead: the route was lost in the MkDocs migration.

    Fumadocs renders its search UI regardless, so the box opened and could
    never return anything because /api/search did not exist.
    """
    plan = _make_plan()
    build_next_from_plan(tmp_path, tmp_path / "docs", _minimal_cfg(), plan)
    site = tmp_path / "site"

    route = site / "app" / "api" / "search" / "route.ts"
    assert route.exists(), "no /api/search route in the generated site"
    body = route.read_text()
    # static export has no server at runtime, so the index must be prebuilt
    assert "staticGET" in body
    assert "force-static" in body
    assert "createSearchAPI" in body

    # the client must be told to search the static index, not call a server
    layout = (site / "app" / "layout.tsx").read_text()
    assert "'static'" in layout

    docs_lib = (site / "lib" / "docs.ts").read_text()
    assert "getSearchIndexes" in docs_lib
    # the whole index ships to the browser, so per-page prose is capped
    assert "MAX_INDEXED_CHARS" in docs_lib
