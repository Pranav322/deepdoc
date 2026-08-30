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


@pytest.mark.parametrize("preset", ["neutral", "vitepress", "ocean", "purple"])
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


# ── theme CSS composition ─────────────────────────────────────────────────────


def _css(cfg) -> str:
    from deepdoc.site.builder.next_builder import resolve_colors, theme_css

    return theme_css(resolve_theme(cfg), resolve_colors(cfg))


def test_brand_maps_onto_fumadocs_tokens_in_both_modes():
    css = _css(deepcopy(DEFAULT_CONFIG))
    assert "--color-fd-primary:var(--brand);" in css
    assert "--color-fd-primary:var(--brand-light);" in css  # dark uses the lighter shade


def test_preset_tokens_are_emitted():
    css = _css(_cfg(theme={"preset": "ocean"}))
    assert "--color-fd-card:" in css
    assert ".dark{" in css


def test_token_override_beats_the_preset():
    """Precedence is preset -> brand -> explicit tokens."""
    import re

    cfg = _cfg(theme={"preset": "ocean", "tokens": {"light": {"background": "#fafafa"}}})
    root = re.search(r":root\{(.*?)\}", _css(cfg)).group(1)
    assert root.rindex("--color-fd-background:#fafafa") > root.index("--color-fd-background")


def test_no_preset_still_maps_the_brand():
    css = _css(deepcopy(DEFAULT_CONFIG))
    assert "--brand:#eb3e25;" in css


def test_every_vendored_preset_has_both_modes():
    """A light-only preset would break dark mode, which is why solar/shadcn
    are excluded upstream-side."""
    from deepdoc.site.builder.presets import PRESETS

    assert PRESETS, "no presets vendored"
    for name, modes in PRESETS.items():
        assert modes["light"], f"{name} has no light tokens"
        assert modes["dark"], f"{name} has no dark tokens"


# ── fonts are opt-in ──────────────────────────────────────────────────────────


def test_no_font_config_makes_no_external_request():
    from deepdoc.site.builder.next_builder import google_fonts_href

    assert google_fonts_href(resolve_theme(deepcopy(DEFAULT_CONFIG))) == ""


def test_configured_fonts_produce_a_google_fonts_url():
    from deepdoc.site.builder.next_builder import google_fonts_href

    theme = resolve_theme(_cfg(theme={"fonts": {"sans": "Inter", "mono": "JetBrains Mono"}}))
    href = google_fonts_href(theme)
    assert "family=Inter" in href and "family=JetBrains+Mono" in href


def test_font_stacks_always_include_a_fallback():
    css = _css(_cfg(theme={"fonts": {"sans": "Inter"}}))
    assert "--font-sans:'Inter', ui-sans-serif" in css


# ── repo info / brand assets ──────────────────────────────────────────────────


def test_repo_url_is_split_for_the_edit_link():
    from deepdoc.site.builder.next_builder import _repo_info

    info = _repo_info(_cfg(repo_url="https://github.com/acme/widgets.git"))
    assert (info["owner"], info["name"], info["branch"]) == ("acme", "widgets", "main")


def test_non_github_repo_url_is_kept_without_owner():
    from deepdoc.site.builder.next_builder import _repo_info

    info = _repo_info(_cfg(repo_url="https://gitlab.com/acme/widgets"))
    assert info["url"].endswith("widgets") and info["owner"] == ""


def test_missing_brand_asset_is_dropped(tmp_path):
    """The URL resolver stays silent; the copy step reports it once."""
    from deepdoc.site.builder.next_builder import brand_asset_urls

    assert brand_asset_urls(tmp_path, _cfg(logo="does/not/exist.svg")) == {}


def test_copying_a_missing_brand_asset_warns(tmp_path, capsys):
    from deepdoc.site.builder.next_builder import _copy_brand_assets

    written = _copy_brand_assets(tmp_path / "site", tmp_path, _cfg(logo="nope.svg"))
    assert written == set()
    assert "not found" in capsys.readouterr().out


def test_existing_brand_asset_becomes_a_public_url(tmp_path):
    from deepdoc.site.builder.next_builder import brand_asset_urls

    (tmp_path / "logo.svg").write_text("<svg/>")
    assert brand_asset_urls(tmp_path, _cfg(logo="logo.svg")) == {"logo": "/logo.svg"}


# ── labels ────────────────────────────────────────────────────────────────────


def _labels(**mapping):
    from deepdoc.site.builder.next_builder import resolve_labels

    return resolve_labels(_cfg(labels=mapping))


def test_ui_and_callout_labels_are_separated():
    """Fumadocs owns its own strings; callout headings are DeepDoc's."""
    out = _labels(toc="On this page", note="Heads up")
    assert out["ui"] == {"toc": "On this page"}
    assert out["callouts"] == {"NOTE": "Heads up"}


def test_callout_label_keys_are_case_insensitive():
    assert _labels(WARNING="Careful")["callouts"] == {"WARNING": "Careful"}


def test_unknown_label_warns_and_is_ignored(capsys):
    """A silently-dropped label looks like a bug to whoever set it."""
    out = _labels(bogus="nope")
    assert out == {"ui": {}, "callouts": {}}
    assert "bogus" in capsys.readouterr().out


def test_empty_label_is_skipped():
    assert _labels(toc="")["ui"] == {}


def test_no_labels_by_default():
    from deepdoc.site.builder.next_builder import resolve_labels

    assert resolve_labels(deepcopy(DEFAULT_CONFIG)) == {"ui": {}, "callouts": {}}


# ── repo_url auto-detection ───────────────────────────────────────────────────


def _fake_git(monkeypatch, url: str | None):
    """Stand in for gitpython so tests never touch a real repo."""
    import deepdoc.site.builder.next_builder as nb

    class _Repo:
        def __init__(self, *a, **k):
            if url is None:
                raise RuntimeError("not a repo")
            self.remotes = type("R", (), {"origin": type("O", (), {"url": url})()})()

    monkeypatch.setitem(__import__("sys").modules, "git", type("M", (), {"Repo": _Repo}))
    return nb


@pytest.mark.parametrize("remote,expected", [
    ("https://github.com/acme/widgets.git", "https://github.com/acme/widgets"),
    ("git@github.com:acme/widgets.git", "https://github.com/acme/widgets"),
    ("ssh://git@gitlab.com:acme/widgets.git", "https://gitlab.com/acme/widgets"),
    ("https://github.com/acme/widgets", "https://github.com/acme/widgets"),
])
def test_repo_url_is_detected_from_the_git_remote(remote, expected, monkeypatch, tmp_path):
    """Saves stating what the repository already knows, like the commit SHA."""
    nb = _fake_git(monkeypatch, remote)
    assert nb._detect_repo_url(tmp_path) == expected


def test_detection_is_silent_outside_a_git_repo(monkeypatch, tmp_path):
    nb = _fake_git(monkeypatch, None)
    assert nb._detect_repo_url(tmp_path) == ""


def test_configured_repo_url_beats_detection(monkeypatch, tmp_path):
    nb = _fake_git(monkeypatch, "git@github.com:acme/widgets.git")
    info = nb._repo_info(_cfg(repo_url="https://gitlab.com/me/thing"), tmp_path)
    assert info["url"] == "https://gitlab.com/me/thing"


def test_edit_link_survives_when_the_url_was_detected(capsys):
    """The guard must judge the resolved URL, not just the configured one."""
    cfg = _cfg(repo_url="", chrome={"edit_link": True})
    assert resolve_chrome(cfg, "https://github.com/acme/widgets")["edit_link"] is True
    assert capsys.readouterr().out == ""
