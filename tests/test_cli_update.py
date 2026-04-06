from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from deepdoc import cli


def test_update_requires_saved_baseline_without_since(
    monkeypatch, tmp_path: Path
) -> None:
    repo_root = tmp_path

    monkeypatch.setattr(
        cli,
        "_load_or_exit",
        lambda: {
            "output_dir": "docs",
            "generation_mode": "feature_buckets",
            "llm": {"provider": "anthropic", "model": "test"},
        },
    )
    monkeypatch.setattr(cli, "_find_repo_root", lambda: repo_root)

    import deepdoc.persistence_v2 as persistence_v2

    monkeypatch.setattr(persistence_v2, "load_sync_state", lambda repo_root: None)

    result = CliRunner().invoke(cli.main, ["update"])

    assert result.exit_code != 0
    assert "No sync baseline found" in result.output


def test_update_uses_saved_baseline_by_default(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        cli,
        "_load_or_exit",
        lambda: {
            "output_dir": "docs",
            "generation_mode": "feature_buckets",
            "llm": {"provider": "anthropic", "model": "test"},
        },
    )
    monkeypatch.setattr(cli, "_find_repo_root", lambda: repo_root)

    import deepdoc.persistence_v2 as persistence_v2
    import deepdoc.smart_update_v2 as smart_update_v2

    monkeypatch.setattr(
        persistence_v2,
        "load_sync_state",
        lambda repo_root: {
            "last_synced_commit": "abc123def456",
            "synced_at": "2026-04-06T10:00:00+00:00",
        },
    )

    class FakeUpdater:
        def __init__(self, repo_root: Path, cfg: dict):
            captured["repo_root"] = repo_root
            captured["cfg"] = cfg

        def update(self, since: str, force_replan: bool) -> dict[str, object]:
            captured["since"] = since
            captured["force_replan"] = force_replan
            return {"pages_updated": 0, "status": "success"}

    monkeypatch.setattr(smart_update_v2, "SmartUpdater", FakeUpdater)

    result = CliRunner().invoke(cli.main, ["update"])

    assert result.exit_code == 0, result.output
    assert captured["repo_root"] == repo_root
    assert captured["since"] == "abc123def456"
    assert captured["force_replan"] is False
