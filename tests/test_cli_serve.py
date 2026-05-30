from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from deepdoc import cli


def test_ensure_mkdocs_installed_raises_when_missing(monkeypatch) -> None:
    import importlib

    # mkdocs absent → clear ClickException with a pip command.
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(cli, "_find_repo_root", lambda: Path("/nonexistent"))

    import pytest

    with pytest.raises(cli.click.ClickException) as exc:
        cli._ensure_mkdocs_installed({})

    assert "pip install" in str(exc.value)
    assert "deepdoc[site]" in str(exc.value)


def test_ensure_mkdocs_installed_passes_when_present(monkeypatch) -> None:
    import importlib

    # All specs resolve → no exception. No OpenAPI dir, so swagger plugin not required.
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(cli, "_find_repo_root", lambda: Path("/nonexistent"))

    cli._ensure_mkdocs_installed({})  # should not raise


def test_find_available_loopback_port_skips_busy_port(monkeypatch) -> None:
    checked: list[int] = []

    def _fake_is_available(port: int) -> bool:
        checked.append(port)
        return port == 4101

    monkeypatch.setattr(cli, "_is_loopback_port_available", _fake_is_available)

    chosen = cli._find_available_loopback_port(4100)

    assert chosen == 4101
    assert checked[:2] == [4100, 4101]


def test_start_chatbot_backend_skips_local_spawn_for_external_url(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def _fail(*args, **kwargs):
        raise AssertionError("subprocess should not be started")

    monkeypatch.setattr(cli.subprocess, "Popen", _fail)

    proc, backend_url = cli._start_chatbot_backend(
        tmp_path,
        {
            "chatbot": {
                "enabled": True,
                "backend": {"base_url": "http://internal-chat:9000"},
            }
        },
        frontend_port=3000,
    )

    assert proc is None
    assert backend_url == "http://internal-chat:9000"


def test_deploy_refuses_invalid_generated_docs(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path
    site_dir = repo_root / "site"
    docs_dir = repo_root / "docs"
    quality_dir = repo_root / ".deepdoc"
    site_dir.mkdir()
    docs_dir.mkdir()
    quality_dir.mkdir()

    (site_dir / "mkdocs.yml").write_text("site_name: Demo\n", encoding="utf-8")
    (docs_dir / "start-here.md").write_text(
        '---\ndeepdoc_status: "invalid"\n---\n', encoding="utf-8"
    )
    (quality_dir / "generation_quality.json").write_text(
        '{"pages_failed": 0, "pages_invalid": 1}\n', encoding="utf-8"
    )

    monkeypatch.setattr(cli, "_load_or_exit", lambda: {"output_dir": "docs", "chatbot": {"enabled": False}})
    monkeypatch.setattr(cli, "_find_repo_root", lambda: repo_root)

    def _fail(*args, **kwargs):
        raise AssertionError("build should not run when docs are invalid")

    monkeypatch.setattr(cli.subprocess, "run", _fail)

    result = CliRunner().invoke(cli.main, ["deploy"])

    assert result.exit_code != 0
    assert "Refusing to deploy docs with unresolved quality issues" in result.output
    assert "invalid docs present: start-here" in result.output


def test_update_deploy_refuses_partial_chatbot_update(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path
    monkeypatch.setattr(cli, "_load_or_exit", lambda: {"output_dir": "docs"})
    monkeypatch.setattr(cli, "_find_repo_root", lambda: repo_root)

    class _FakeUpdater:
        def __init__(self, repo_root, cfg):
            pass

        def update(self, *, since, force_replan=False):
            return {
                "strategy": "incremental",
                "pages_updated": 1,
                "pages_failed": 1,
                "chatbot_failed": True,
            }

    def _fail_deploy(*args, **kwargs):
        raise AssertionError("deploy should not run after a partial update")

    monkeypatch.setattr("deepdoc.smart_update_v2.SmartUpdater", _FakeUpdater)
    monkeypatch.setattr(cli, "_deploy", _fail_deploy)

    result = CliRunner().invoke(cli.main, ["update", "--since", "HEAD", "--deploy"])

    assert result.exit_code != 0
    assert "Chatbot index refresh failed" in result.output


def test_update_without_deploy_fails_on_chatbot_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path
    monkeypatch.setattr(cli, "_load_or_exit", lambda: {"output_dir": "docs"})
    monkeypatch.setattr(cli, "_find_repo_root", lambda: repo_root)

    class _FakeUpdater:
        def __init__(self, repo_root, cfg):
            pass

        def update(self, *, since, force_replan=False):
            return {
                "strategy": "incremental",
                "pages_updated": 1,
                "pages_failed": 1,
                "chatbot_failed": True,
            }

    monkeypatch.setattr("deepdoc.smart_update_v2.SmartUpdater", _FakeUpdater)

    result = CliRunner().invoke(cli.main, ["update", "--since", "HEAD"])

    assert result.exit_code != 0
    assert "Chatbot index refresh failed" in result.output


def test_update_deploy_refuses_partial_doc_update(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path
    monkeypatch.setattr(cli, "_load_or_exit", lambda: {"output_dir": "docs"})
    monkeypatch.setattr(cli, "_find_repo_root", lambda: repo_root)

    class _FakeUpdater:
        def __init__(self, repo_root, cfg):
            pass

        def update(self, *, since, force_replan=False):
            return {
                "strategy": "incremental",
                "pages_updated": 1,
                "pages_failed": 1,
                "chatbot_failed": False,
            }

    def _fail_deploy(*args, **kwargs):
        raise AssertionError("deploy should not run after a partial update")

    monkeypatch.setattr("deepdoc.smart_update_v2.SmartUpdater", _FakeUpdater)
    monkeypatch.setattr(cli, "_deploy", _fail_deploy)

    result = CliRunner().invoke(cli.main, ["update", "--since", "HEAD", "--deploy"])

    assert result.exit_code != 0
    assert "Refusing to deploy" in result.output


def test_deprecated_generated_version_warning_is_configurable(
    tmp_path: Path,
    capsys,
) -> None:
    repo_root = tmp_path
    docs_dir = repo_root / "docs"
    docs_dir.mkdir()
    (docs_dir / "index.md").write_text(
        '---\ndeepdoc_generated_version: "0.9.0"\n---\n# Docs\n',
        encoding="utf-8",
    )
    cli._DEPRECATED_VERSION_WARNING_REPOS.clear()

    cli._warn_if_deprecated_generated_version(
        {
            "output_dir": "docs",
            "compatibility": {
                "deprecated_version_warning": {
                    "enabled": True,
                    "minimum_version": "1.0.0",
                    "upgrade_command": "deepdoc-upgrade",
                }
            },
        },
        repo_root,
    )

    output = capsys.readouterr().out
    assert "Docs need regeneration" in output
    assert "0.9.0" in output
    assert "deepdoc generate" in output

    cli._warn_if_deprecated_generated_version(
        {
            "output_dir": "docs",
            "compatibility": {
                "deprecated_version_warning": {
                    "enabled": False,
                    "minimum_version": "1.0.0",
                    "upgrade_command": "deepdoc-upgrade",
                }
            },
        },
        repo_root,
    )

    assert capsys.readouterr().out == ""
