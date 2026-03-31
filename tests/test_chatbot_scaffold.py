from __future__ import annotations

from pathlib import Path

from deepdoc.chatbot.scaffold import scaffold_chatbot_backend
from deepdoc.chatbot.settings import chatbot_site_api_base_url
from deepdoc.site.fumadocs_builder_v2 import build_fumadocs_from_plan
from tests.conftest import make_bucket, make_plan


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
    settings = (repo_root / "chatbot_backend" / "settings.py").read_text(encoding="utf-8")
    assert "http://127.0.0.1:8010" in settings


def test_fumadocs_builder_emits_chatbot_files_when_enabled(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    output_dir = repo_root / "docs"
    output_dir.mkdir()
    (output_dir / "index.mdx").write_text("# Demo\n", encoding="utf-8")

    overview = make_bucket(
        "Overview",
        "overview",
        ["README.md"],
        generation_hints={"is_introduction_page": True},
    )
    plan = make_plan([overview])

    build_fumadocs_from_plan(
        repo_root,
        output_dir,
        {
            "project_name": "Demo",
            "site": {"repo_url": "https://example.com/repo"},
            "chatbot": {
                "enabled": True,
            },
        },
        plan,
        has_openapi=False,
    )

    assert (repo_root / "site" / "components" / "chatbot-panel.tsx").exists()
    assert (repo_root / "site" / "components" / "chatbot-toggle.tsx").exists()
    config = (repo_root / "site" / "lib" / "chatbot-config.ts").read_text(encoding="utf-8")
    panel = (repo_root / "site" / "components" / "chatbot-panel.tsx").read_text(encoding="utf-8")
    assert "enabled: true" in config
    assert "NEXT_PUBLIC_DEEPDOC_CHATBOT_BASE_URL" in config
    assert f"apiBaseUrl: envApiBaseUrl || {chatbot_site_api_base_url({'chatbot': {'enabled': True}})!r}" in config
    assert "ReactMarkdown" in panel
    assert "max-h-[min(80vh,56rem)]" in panel
    assert "Chatbot backend URL is not configured." in panel
