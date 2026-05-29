from __future__ import annotations

from pathlib import Path

from deepdoc.chatbot.scaffold import scaffold_chatbot_backend


def test_chatbot_backend_scaffold_is_generated(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    scaffold_chatbot_backend(
        repo_root,
        {
            "chatbot": {
                "enabled": True,
                "backend": {"base_url": "http://127.0.0.1:8010"},
            }
        },
    )

    assert (repo_root / "chatbot_backend" / "app.py").exists()
    assert (repo_root / "chatbot_backend" / "requirements.txt").exists()
    assert (repo_root / "chatbot_backend" / ".env.example").exists()
    settings = (repo_root / "chatbot_backend" / "settings.py").read_text(
        encoding="utf-8"
    )
    assert "http://127.0.0.1:8010" in settings


def test_chatbot_backend_scaffold_is_removed_when_disabled(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    backend_dir = repo_root / "chatbot_backend"
    backend_dir.mkdir()
    (backend_dir / "app.py").write_text("# stale\n", encoding="utf-8")

    scaffold_chatbot_backend(repo_root, {"chatbot": {"enabled": False}})

    assert not backend_dir.exists()
