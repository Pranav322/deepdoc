from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from deepdoc import cli


def test_generate_skip_api_overrides_config(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    cfg = {
        "project_name": "Demo",
        "output_dir": "docs",
        "llm": {"provider": "anthropic", "model": "claude-test"},
        "include_endpoint_pages": True,
    }

    class FakePipeline:
        def __init__(self, repo_root: Path, pipeline_cfg: dict):
            captured["repo_root"] = repo_root
            captured["cfg"] = pipeline_cfg

        def run(self, force: bool, reconcile: bool) -> None:
            captured["force"] = force
            captured["reconcile"] = reconcile

    monkeypatch.setattr(cli, "_load_or_exit", lambda: dict(cfg))
    monkeypatch.setattr(cli, "_find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        cli,
        "_inspect_output_state",
        lambda repo_root, output_dir: {"deepdoc_managed": False, "has_files": False},
    )

    import deepdoc.pipeline_v2 as pipeline_v2

    monkeypatch.setattr(pipeline_v2, "PipelineV2", FakePipeline)

    result = CliRunner().invoke(cli.main, ["generate", "--skip-api"])

    assert result.exit_code == 0, result.output
    assert captured["repo_root"] == tmp_path
    assert captured["cfg"]["include_endpoint_pages"] is False


def test_generate_api_flag_can_reenable_endpoint_pages(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    cfg = {
        "project_name": "Demo",
        "output_dir": "docs",
        "llm": {"provider": "anthropic", "model": "claude-test"},
        "include_endpoint_pages": False,
    }

    class FakePipeline:
        def __init__(self, repo_root: Path, pipeline_cfg: dict):
            captured["cfg"] = pipeline_cfg

        def run(self, force: bool, reconcile: bool) -> None:
            return None

    monkeypatch.setattr(cli, "_load_or_exit", lambda: dict(cfg))
    monkeypatch.setattr(cli, "_find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        cli,
        "_inspect_output_state",
        lambda repo_root, output_dir: {"deepdoc_managed": False, "has_files": False},
    )

    import deepdoc.pipeline_v2 as pipeline_v2

    monkeypatch.setattr(pipeline_v2, "PipelineV2", FakePipeline)

    result = CliRunner().invoke(cli.main, ["generate", "--api"])

    assert result.exit_code == 0, result.output
    assert captured["cfg"]["include_endpoint_pages"] is True
