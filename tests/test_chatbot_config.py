from __future__ import annotations

from pathlib import Path

from deepdoc.config import DEFAULT_CONFIG, load_config, save_config
from deepdoc.chatbot.settings import (
    chatbot_allowed_origins,
    chatbot_backend_base_url,
    chatbot_backend_port,
    chatbot_should_start_local_backend,
    chatbot_site_api_base_url,
)


def test_chatbot_defaults_are_present() -> None:
    chatbot = DEFAULT_CONFIG["chatbot"]

    assert chatbot["enabled"] is False
    assert chatbot["vector_store"]["kind"] == "faiss"
    assert chatbot["retrieval"]["top_k_code"] == 15
    assert chatbot["answer"]["api_key_env"] == "DEEPDOC_CHAT_API_KEY"
    assert chatbot["embeddings"]["api_key_env"] == "DEEPDOC_EMBED_API_KEY"
    assert "http://localhost:3000" in chatbot["backend"]["allowed_origins"]
    assert "http://127.0.0.1:3000" in chatbot["backend"]["allowed_origins"]


def test_chatbot_config_merges_nested_values(tmp_path: Path) -> None:
    cfg_path = tmp_path / ".deepdoc.yaml"
    save_config(
        {
            "project_name": "Demo",
            "chatbot": {
                "enabled": True,
                "backend": {"base_url": "http://internal-chat:9000"},
                "embeddings": {"api_key_env": "ALT_EMBED_KEY"},
            },
        },
        cfg_path,
    )

    cfg = load_config(cfg_path)

    assert cfg["chatbot"]["enabled"] is True
    assert cfg["chatbot"]["backend"]["base_url"] == "http://internal-chat:9000"
    assert cfg["chatbot"]["backend"]["allowed_origins"] == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    assert cfg["chatbot"]["embeddings"]["api_key_env"] == "ALT_EMBED_KEY"
    assert cfg["chatbot"]["answer"]["api_key_env"] == "DEEPDOC_CHAT_API_KEY"


def test_chatbot_backend_defaults_are_repo_specific(tmp_path: Path) -> None:
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()

    cfg = {"chatbot": DEFAULT_CONFIG["chatbot"]}

    url_a = chatbot_backend_base_url(cfg, repo_a)
    url_b = chatbot_backend_base_url(cfg, repo_b)

    assert url_a != url_b
    assert chatbot_backend_port(cfg, repo_a) != chatbot_backend_port(cfg, repo_b)
    assert url_a.startswith("http://127.0.0.1:")
    assert chatbot_site_api_base_url(cfg) == ""


def test_chatbot_backend_explicit_loopback_port_is_respected(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    cfg = {
        "chatbot": {
            "enabled": True,
            "backend": {"base_url": "http://127.0.0.1:8001"},
        }
    }

    assert chatbot_backend_base_url(cfg, repo_root) == "http://127.0.0.1:8001"
    assert chatbot_backend_port(cfg, repo_root) == 8001
    assert chatbot_should_start_local_backend(cfg) is True
    assert chatbot_site_api_base_url(cfg) == "http://127.0.0.1:8001"


def test_chatbot_external_backend_is_not_reused_as_local_preview_port(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    cfg = {
        "chatbot": {
            "enabled": True,
            "backend": {"base_url": "http://internal-chat:9000"},
        }
    }

    assert chatbot_backend_base_url(cfg, repo_root) == "http://internal-chat:9000"
    assert chatbot_site_api_base_url(cfg) == "http://internal-chat:9000"
    assert chatbot_should_start_local_backend(cfg) is False
    assert chatbot_backend_port(cfg, repo_root) != 9000


def test_chatbot_allowed_origins_include_preview_port(monkeypatch) -> None:
    monkeypatch.setenv("DEEPDOC_CHATBOT_PREVIEW_PORT", "4123")

    origins = chatbot_allowed_origins({"chatbot": {"enabled": True}})

    assert "http://localhost:4123" in origins
    assert "http://127.0.0.1:4123" in origins
