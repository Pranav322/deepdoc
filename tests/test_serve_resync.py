"""`deepdoc serve` re-applies .deepdoc.yaml without regenerating docs.

The product requirement: edit .deepdoc.yaml, run `deepdoc serve`, see the new
UI — with no regeneration and no LLM calls. `_resync_site_from_config` rebuilds
the site config from the saved `.deepdoc/plan.json`, so nothing is planned,
scanned or generated.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from deepdoc import cli


def _plan() -> SimpleNamespace:
    return SimpleNamespace(
        nav_structure={"Guides": ["guide"]},
        pages=[
            SimpleNamespace(slug="index", title="Home", _b=None),
            SimpleNamespace(slug="guide", title="Guide", _b=None),
        ],
    )


def _cfg(site_dir: Path, primary: str = "#eb3e25") -> dict:
    return {
        "project_name": "Resync Docs",
        "site_dir": str(site_dir),
        "site": {"colors": {"primary": primary, "light": "#ef624e", "dark": "#c1331f"}},
        "chatbot": {"enabled": False},
    }


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "index.md").write_text("# Home\n")
    (docs / "guide.md").write_text("# Guide\n")
    return tmp_path


def _site_config(site_dir: Path) -> dict:
    return json.loads((site_dir / "deepdoc.config.json").read_text())


def test_resync_applies_a_changed_colour(repo: Path, monkeypatch):
    monkeypatch.setattr("deepdoc.persistence_v2.load_plan", lambda _r: _plan())
    site, docs = repo / "site", repo / "docs"

    cli._resync_site_from_config(repo, docs, site, _cfg(site))
    assert _site_config(site)["colors"]["primary"] == "#eb3e25"

    cli._resync_site_from_config(repo, docs, site, _cfg(site, "#7c3aed"))
    assert _site_config(site)["colors"]["primary"] == "#7c3aed"


def test_resync_preserves_nav_from_the_saved_plan(repo: Path, monkeypatch):
    monkeypatch.setattr("deepdoc.persistence_v2.load_plan", lambda _r: _plan())
    site, docs = repo / "site", repo / "docs"

    cli._resync_site_from_config(repo, docs, site, _cfg(site))
    first = _site_config(site)["nav"]
    cli._resync_site_from_config(repo, docs, site, _cfg(site, "#123456"))

    assert _site_config(site)["nav"] == first


def test_resync_makes_no_llm_calls(repo: Path, monkeypatch):
    """The core guarantee — a config change must never cost an LLM request."""
    import deepdoc.llm.client as llm_client

    def _boom(*_a, **_kw):  # pragma: no cover - must never run
        raise AssertionError("resync constructed an LLM client")

    monkeypatch.setattr(llm_client, "LLMClient", _boom)
    monkeypatch.setattr("deepdoc.persistence_v2.load_plan", lambda _r: _plan())

    site, docs = repo / "site", repo / "docs"
    cli._resync_site_from_config(repo, docs, site, _cfg(site, "#00ff00"))

    assert _site_config(site)["colors"]["primary"] == "#00ff00"


def test_resync_without_a_saved_plan_warns_and_continues(tmp_path: Path, monkeypatch):
    """A missing plan must not stop the preview."""
    monkeypatch.setattr("deepdoc.persistence_v2.load_plan", lambda _r: None)
    site = tmp_path / "site"

    cli._resync_site_from_config(tmp_path, tmp_path / "docs", site, _cfg(site))

    assert not (site / "deepdoc.config.json").exists()


def test_resync_with_a_legacy_plan_warns_and_continues(tmp_path: Path, monkeypatch):
    """A v1 plan carries no nav_structure; serve what is on disk instead."""
    legacy = SimpleNamespace(pages=[])  # no nav_structure attribute
    monkeypatch.setattr("deepdoc.persistence_v2.load_plan", lambda _r: legacy)
    site = tmp_path / "site"

    cli._resync_site_from_config(tmp_path, tmp_path / "docs", site, _cfg(site))

    assert not (site / "deepdoc.config.json").exists()


# ── change reporting ──────────────────────────────────────────────────────────


def test_report_lists_changed_keys(capsys):
    cli._report_site_config_changes({"colors": {"primary": "#000"}}, {"colors": {"primary": "#fff"}})
    assert "colors" in capsys.readouterr().out


def test_report_ignores_volatile_keys(capsys):
    """generated_at/commit_sha change every build and are not user edits."""
    cli._report_site_config_changes(
        {"colors": {"primary": "#000"}, "generated_at": "Jan 01, 2020", "commit_sha": "aaaaaaa"},
        {"colors": {"primary": "#000"}, "generated_at": "Feb 02, 2026", "commit_sha": "bbbbbbb"},
    )
    assert capsys.readouterr().out.strip() == ""


def test_report_silent_on_first_write(capsys):
    """Nothing to diff against when the site had no previous config."""
    cli._report_site_config_changes({}, {"colors": {"primary": "#fff"}})
    assert capsys.readouterr().out.strip() == ""


# ── the product requirement, end to end ───────────────────────────────────────


def test_every_ui_setting_applies_on_serve_with_no_llm(repo: Path, monkeypatch):
    """Edit .deepdoc.yaml -> `deepdoc serve` -> new UI. No regeneration.

    Covers all six live-appliable families at once and trips hard if anything
    on this path constructs an LLM client.
    """
    import deepdoc.llm.client as llm_client
    from copy import deepcopy
    from deepdoc.config import DEFAULT_CONFIG

    def _boom(*_a, **_kw):  # pragma: no cover - must never run
        raise AssertionError("an LLM client was constructed during serve resync")

    monkeypatch.setattr(llm_client, "LLMClient", _boom)
    monkeypatch.setattr("deepdoc.persistence_v2.load_plan", lambda _r: _plan())

    site, docs = repo / "site", repo / "docs"
    cfg = deepcopy(DEFAULT_CONFIG)
    cfg.update({"project_name": "E2E", "site_dir": str(site)})
    cfg["chatbot"] = {"enabled": False}

    cli._resync_site_from_config(repo, docs, site, cfg)
    before = _site_config(site)

    # The user edits their config.
    s = cfg["site"]
    s["colors"]["primary"] = "#7c3aed"
    s["theme"]["preset"] = "vitepress"
    s["theme"]["fonts"]["sans"] = "Inter"
    s["chrome"]["toc_style"] = "normal"
    s["labels"] = {"toc": "On this page"}
    s["nav"] = {"rename": {"guide": "Handbook"}}

    cli._resync_site_from_config(repo, docs, site, cfg)
    after = _site_config(site)

    assert after["colors"]["primary"] == "#7c3aed"
    assert after["theme"]["preset"] == "vitepress"
    assert "--color-fd-card" in after["theme"]["css"], "preset tokens not emitted"
    assert "family=Inter" in after["theme"]["google_fonts"]
    assert after["chrome"]["toc_style"] == "normal"
    assert after["labels"]["ui"]["toc"] == "On this page"
    assert "Handbook" in json.dumps(after["nav"])
    assert after != before


# ── a missing site directory is recoverable without regenerating ──────────────


def test_resync_rebuilds_a_site_that_does_not_exist(repo: Path, monkeypatch):
    """site_dir is normally gitignored, so a fresh clone has docs and a saved
    plan but no site. That is rebuildable with no LLM call, so `serve` and
    `deploy` must not refuse before trying."""
    import deepdoc.llm.client as llm_client

    def _boom(*_a, **_kw):  # pragma: no cover - must never run
        raise AssertionError("rebuilding a missing site should not need an LLM")

    monkeypatch.setattr(llm_client, "LLMClient", _boom)
    monkeypatch.setattr("deepdoc.persistence_v2.load_plan", lambda _r: _plan())

    site = repo / "site"
    assert not site.exists()

    cli._resync_site_from_config(repo, repo / "docs", site, _cfg(site))

    assert (site / "package.json").exists(), "scaffold not rebuilt"
    assert (site / "deepdoc.config.json").exists()


def test_serve_resyncs_before_checking_for_package_json(tmp_path: Path, monkeypatch):
    """Ordering guard: the guard used to run first, so a missing site sent the
    user to `deepdoc generate` — and its LLM bill — for something free."""
    import inspect

    source = inspect.getsource(cli.serve.callback)
    resync_at = source.index("_resync_site_from_config")
    guard_at = source.index('"package.json"')
    assert resync_at < guard_at, "package.json guard must not precede the resync"


def test_deploy_resyncs_before_checking_for_package_json():
    import inspect

    source = inspect.getsource(cli._deploy.callback)
    resync_at = source.index("_resync_site_from_config")
    guard_at = source.index('"package.json"')
    assert resync_at < guard_at, "package.json guard must not precede the resync"


def test_deploy_resyncs_exactly_once():
    """An earlier revision left a second, redundant resync in deploy."""
    import inspect

    assert inspect.getsource(cli._deploy.callback).count("_resync_site_from_config") == 1
