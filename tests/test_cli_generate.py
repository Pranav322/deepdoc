from __future__ import annotations

from pathlib import Path
import subprocess

from click.testing import CliRunner

from deepdoc import cli


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "initial"],
        cwd=root,
        check=True,
        capture_output=True,
    )


def test_cli_autoloads_repo_env_file(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("DEEPDOC_SAMPLE_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPDOC_SAMPLE_KEY", raising=False)

    result = CliRunner().invoke(cli.main, ["clean", "--yes"])

    assert result.exit_code == 0, result.output
    assert cli.os.environ["DEEPDOC_SAMPLE_KEY"] == "from-dotenv"


def test_cli_repo_env_does_not_override_existing_exports(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("DEEPDOC_SAMPLE_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEEPDOC_SAMPLE_KEY", "from-shell")

    result = CliRunner().invoke(cli.main, ["clean", "--yes"])

    assert result.exit_code == 0, result.output
    assert cli.os.environ["DEEPDOC_SAMPLE_KEY"] == "from-shell"


def test_init_uses_safe_output_defaults(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli.main, ["init", "--provider", "anthropic"])

    assert result.exit_code == 0, result.output
    config = (tmp_path / ".deepdoc.yaml").read_text(encoding="utf-8")
    assert "output_dir: deepdoc-docs" in config
    assert "site_dir: deepdoc-site" in config


def test_init_accepts_site_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        cli.main,
        ["init", "--provider", "anthropic", "--output-dir", "guide", "--site-dir", "guide-site"],
    )

    assert result.exit_code == 0, result.output
    config = (tmp_path / ".deepdoc.yaml").read_text(encoding="utf-8")
    assert "output_dir: guide" in config
    assert "site_dir: guide-site" in config


def test_clean_removes_deepdoc_artifacts_and_config(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path
    output_dir = repo_root / "documentation"
    output_dir.mkdir()
    (output_dir / "index.md").write_text(
        "---\ndeepdoc_generated_version: 1.0\n---\n# docs\n",
        encoding="utf-8",
    )

    (repo_root / ".deepdoc.yaml").write_text(
        "output_dir: documentation\nsite_dir: deepdoc-site\n", encoding="utf-8"
    )
    (repo_root / ".deepdoc").mkdir()
    (repo_root / ".deepdoc" / "plan.json").write_text("{}", encoding="utf-8")
    (repo_root / "deepdoc-site").mkdir()
    (repo_root / "deepdoc-site" / "deepdoc.config.json").write_text("{}", encoding="utf-8")
    (repo_root / "deepdoc-site" / "package.json").write_text("{}", encoding="utf-8")
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
    assert (repo_root / "deepdoc-site").exists()
    assert (repo_root / "deepdoc-site" / "package.json").exists()
    assert (repo_root / "chatbot_backend").exists()
    assert not (repo_root / ".deepdoc_plan.json").exists()
    assert not (repo_root / ".deepdoc_file_map.json").exists()
    assert (repo_root / "keep.txt").exists()


def test_generate_clean_keeps_config_for_rebuilds(monkeypatch, tmp_path: Path) -> None:
    cfg = {
        "project_name": "Demo",
        "output_dir": "documentation",
        "site_dir": "deepdoc-site",
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
    (output_dir / "index.md").write_text(
        "---\ndeepdoc_generated_version: 1.0\n---\n# docs\n",
        encoding="utf-8",
    )
    (repo_root / ".deepdoc.yaml").write_text(
        "output_dir: documentation\nsite_dir: deepdoc-site\n", encoding="utf-8"
    )
    (repo_root / ".deepdoc").mkdir()
    (repo_root / ".deepdoc" / "plan.json").write_text("{}", encoding="utf-8")
    (repo_root / "deepdoc-site").mkdir()
    (repo_root / "deepdoc-site" / "deepdoc.config.json").write_text("{}", encoding="utf-8")
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
    assert not (repo_root / "deepdoc-site").exists()
    assert (repo_root / "chatbot_backend").exists()


def test_generate_clean_refuses_tracked_docs_collision(monkeypatch, tmp_path: Path) -> None:
    docs = tmp_path / "docs" / "en" / "docs"
    docs.mkdir(parents=True)
    authored = docs / "index.md"
    authored.write_text("# Authored Documentation\n", encoding="utf-8")
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "index.html").write_text("authored site", encoding="utf-8")
    _init_git_repo(tmp_path)

    cfg = {
        "project_name": "Collision",
        "output_dir": "docs",
        "site_dir": "site",
        "llm": {"provider": "anthropic", "model": "claude-test"},
    }
    monkeypatch.setattr(cli, "_load_or_exit", lambda: dict(cfg))
    monkeypatch.setattr(cli, "_find_repo_root", lambda: tmp_path)

    result = CliRunner().invoke(cli.main, ["generate", "--clean", "--yes"])

    assert result.exit_code != 0
    assert "Refusing to write DeepDoc output" in result.output
    assert authored.exists()
    assert (tmp_path / "site" / "index.html").exists()


def test_clean_preserves_unowned_files_in_shared_output(monkeypatch, tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    generated = docs / "generated.md"
    generated.write_text(
        "---\ndeepdoc_generated_version: 1.0\n---\n# Generated\n", encoding="utf-8"
    )
    authored = docs / "architecture.md"
    authored.write_text("# Architecture\n", encoding="utf-8")
    (tmp_path / ".deepdoc.yaml").write_text(
        "output_dir: docs\nsite_dir: deepdoc-site\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli.main, ["clean", "--yes"])

    assert result.exit_code == 0, result.output
    assert not generated.exists()
    assert authored.exists()


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
