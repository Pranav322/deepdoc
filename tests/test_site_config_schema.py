"""Validation for the generated-site config surface (`site.*`).

Two rules hold everywhere here:

* A bad value must never fail a build. It warns and falls back, because a typo
  in a colour should not stop documentation from being generated.
* `config set` is the exception: it persists to disk, so an unknown key is a
  hard error rather than a silently-created setting that does nothing.
"""

from __future__ import annotations

from copy import deepcopy

import pytest
from click.testing import CliRunner

from deepdoc import cli
from deepdoc.config import DEFAULT_CONFIG
from deepdoc.site.builder.next_builder import resolve_chrome, resolve_theme


def _cfg(**site) -> dict:
    cfg = deepcopy(DEFAULT_CONFIG)
    for key, value in site.items():
        cfg["site"][key] = value
    return cfg


# ── defaults must be silent and unchanged ─────────────────────────────────────


def test_shipped_defaults_produce_no_warnings(capsys):
    """An untouched .deepdoc.yaml must render exactly as before, silently."""
    resolve_theme(deepcopy(DEFAULT_CONFIG))
    resolve_chrome(deepcopy(DEFAULT_CONFIG))
    assert capsys.readouterr().out == ""


def test_empty_config_falls_back_to_defaults():
    theme = resolve_theme({})
    assert theme["preset"] == ""
    assert theme["fonts"] == {"sans": "", "mono": ""}
    assert theme["code_theme"]["light"] == "github-light"
    assert resolve_chrome({})["toc_style"] == "clerk"


def test_fonts_are_opt_in():
    """Empty fonts mean no webfont request is made from the docs site."""
    assert resolve_theme(deepcopy(DEFAULT_CONFIG))["fonts"] == {"sans": "", "mono": ""}


# ── theme ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("preset", ["neutral", "vitepress", "ocean", "shadcn"])
def test_known_presets_are_accepted(preset):
    cfg = _cfg(theme={"preset": preset})
    assert resolve_theme(cfg)["preset"] == preset


def test_unknown_preset_warns_and_falls_back(capsys):
    resolved = resolve_theme(_cfg(theme={"preset": "nonsense"}))
    assert resolved["preset"] == ""
    assert "nonsense" in capsys.readouterr().out


def test_token_overrides_accept_bare_and_prefixed_names():
    cfg = _cfg(theme={"tokens": {"light": {"background": "#ffffff",
                                           "--color-fd-border": "#e5e5e5"}}})
    assert resolve_theme(cfg)["tokens"]["light"] == {
        "background": "#ffffff",
        "border": "#e5e5e5",
    }


def test_unknown_token_is_ignored_with_a_warning(capsys):
    cfg = _cfg(theme={"tokens": {"light": {"bogus": "#fff"}}})
    assert resolve_theme(cfg)["tokens"]["light"] == {}
    assert "bogus" in capsys.readouterr().out


@pytest.mark.parametrize("bad", ["red", "#ff00", "ff0000", "rgb(1,2,3)"])
def test_malformed_token_colour_is_ignored(bad, capsys):
    cfg = _cfg(theme={"tokens": {"dark": {"background": bad}}})
    assert resolve_theme(cfg)["tokens"]["dark"] == {}
    assert "not a hex colour" in capsys.readouterr().out


def test_code_theme_is_configurable():
    cfg = _cfg(theme={"code_theme": {"light": "min-light", "dark": "dracula"}})
    assert resolve_theme(cfg)["code_theme"] == {"light": "min-light", "dark": "dracula"}


# ── chrome ────────────────────────────────────────────────────────────────────


def test_invalid_toc_style_warns_and_falls_back(capsys):
    assert resolve_chrome(_cfg(chrome={"toc_style": "fancy"}))["toc_style"] == "clerk"
    assert "fancy" in capsys.readouterr().out


@pytest.mark.parametrize("bad", [["x"], [], [9, 12], None])
def test_invalid_toc_depth_falls_back(bad):
    assert resolve_chrome(_cfg(chrome={"toc_depth": bad}))["toc_depth"] == [2, 3]


def test_toc_depth_is_normalised():
    assert resolve_chrome(_cfg(chrome={"toc_depth": [3, 2, 2, 4]}))["toc_depth"] == [2, 3, 4]


def test_edit_link_without_repo_url_is_disabled(capsys):
    """An edit link with no repository would render a dead anchor."""
    cfg = _cfg(repo_url="", chrome={"edit_link": True})
    assert resolve_chrome(cfg)["edit_link"] is False
    assert "repo_url" in capsys.readouterr().out


def test_edit_link_with_repo_url_is_kept():
    cfg = _cfg(repo_url="https://github.com/acme/widgets", chrome={"edit_link": True})
    assert resolve_chrome(cfg)["edit_link"] is True


def test_malformed_navbar_link_is_dropped(capsys):
    cfg = _cfg(chrome={"links": [{"text": "OK", "url": "/a"}, {"text": "no url"}, "nope"]})
    assert resolve_chrome(cfg)["links"] == [{"text": "OK", "url": "/a"}]
    assert "needs both" in capsys.readouterr().out


# ── config set is a trust boundary: unknown keys are a hard error ─────────────


def test_config_set_accepts_a_known_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from deepdoc.config import save_config

    save_config(deepcopy(DEFAULT_CONFIG), tmp_path / ".deepdoc.yaml")
    result = CliRunner().invoke(cli.main, ["config", "set", "site.theme.preset", "ocean"])
    assert result.exit_code == 0


def test_config_set_rejects_an_unknown_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from deepdoc.config import save_config

    path = tmp_path / ".deepdoc.yaml"
    save_config(deepcopy(DEFAULT_CONFIG), path)
    before = path.read_text()

    result = CliRunner().invoke(cli.main, ["config", "set", "site.theme.presset", "ocean"])

    assert result.exit_code != 0
    assert "Unknown config key" in result.output
    assert "site.theme.preset" in result.output  # suggestion
    assert path.read_text() == before, "a rejected key must not touch the file"


def test_config_set_allows_user_defined_maps(tmp_path, monkeypatch):
    """Token/label/rename maps are user-defined, so any key there is valid."""
    monkeypatch.chdir(tmp_path)
    from deepdoc.config import save_config

    save_config(deepcopy(DEFAULT_CONFIG), tmp_path / ".deepdoc.yaml")
    for key in (
        "site.labels.toc",
        "site.nav.rename.auth-service",
        "site.theme.tokens.light.background",
    ):
        result = CliRunner().invoke(cli.main, ["config", "set", key, "x"])
        assert result.exit_code == 0, f"{key} should be settable: {result.output}"
