from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from deepdoc import cli


def test_clean_removes_deepdoc_artifacts_and_config(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path
    output_dir = repo_root / "documentation"
    output_dir.mkdir()
    (output_dir / "index.mdx").write_text("# docs\n", encoding="utf-8")

    (repo_root / ".deepdoc.yaml").write_text("output_dir: documentation\n", encoding="utf-8")
    (repo_root / ".deepdoc").mkdir()
    (repo_root / ".deepdoc" / "plan.json").write_text("{}", encoding="utf-8")
    (repo_root / "site").mkdir()
    (repo_root / "site" / "package.json").write_text("{}", encoding="utf-8")
    (repo_root / "chatbot_backend").mkdir()
    (repo_root / "chatbot_backend" / "app.py").write_text("app = None\n", encoding="utf-8")
    (repo_root / ".deepdoc_plan.json").write_text("{}", encoding="utf-8")
    (repo_root / ".deepdoc_file_map.json").write_text("{}", encoding="utf-8")
    (repo_root / "keep.txt").write_text("leave me alone\n", encoding="utf-8")

    monkeypatch.chdir(repo_root)

    result = CliRunner().invoke(cli.main, ["clean", "--yes"])

    assert result.exit_code == 0, result.output
    assert not output_dir.exists()
    assert not (repo_root / ".deepdoc.yaml").exists()
    assert not (repo_root / ".deepdoc").exists()
    assert not (repo_root / "site").exists()
    assert not (repo_root / "chatbot_backend").exists()
    assert not (repo_root / ".deepdoc_plan.json").exists()
    assert not (repo_root / ".deepdoc_file_map.json").exists()
    assert (repo_root / "keep.txt").exists()


def test_generate_clean_keeps_config_for_rebuilds(monkeypatch, tmp_path: Path) -> None:
    cfg = {
        "project_name": "Demo",
        "output_dir": "documentation",
        "llm": {"provider": "anthropic", "model": "claude-test"},
    }
    captured: dict[str, object] = {}

    class FakePipeline:
        def __init__(self, repo_root: Path, pipeline_cfg: dict):
            captured["repo_root"] = repo_root
            captured["cfg"] = pipeline_cfg

        def run(self, force: bool, reconcile: bool) -> None:
            captured["force"] = force
            captured["reconcile"] = reconcile

    repo_root = tmp_path
    output_dir = repo_root / "documentation"
    output_dir.mkdir()
    (output_dir / "index.mdx").write_text("# docs\n", encoding="utf-8")
    (repo_root / ".deepdoc.yaml").write_text("output_dir: documentation\n", encoding="utf-8")
    (repo_root / ".deepdoc").mkdir()
    (repo_root / ".deepdoc" / "plan.json").write_text("{}", encoding="utf-8")
    (repo_root / "site").mkdir()
    (repo_root / "chatbot_backend").mkdir()

    monkeypatch.setattr(cli, "_load_or_exit", lambda: dict(cfg))
    monkeypatch.setattr(cli, "_find_repo_root", lambda: repo_root)

    import deepdoc.pipeline_v2 as pipeline_v2

    monkeypatch.setattr(pipeline_v2, "PipelineV2", FakePipeline)

    result = CliRunner().invoke(cli.main, ["generate", "--clean", "--yes"])

    assert result.exit_code == 0, result.output
    assert captured["repo_root"] == repo_root
    assert captured["force"] is True
    assert captured["reconcile"] is False
    assert (repo_root / ".deepdoc.yaml").exists()
    assert not output_dir.exists()
    assert not (repo_root / ".deepdoc").exists()
    assert not (repo_root / "site").exists()
    assert not (repo_root / "chatbot_backend").exists()


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
