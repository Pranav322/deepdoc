from __future__ import annotations

from pathlib import Path

from codewiki.config import DEFAULT_CONFIG, load_config, save_config


def test_chatbot_defaults_are_present() -> None:
    chatbot = DEFAULT_CONFIG["chatbot"]

    assert chatbot["enabled"] is False
    assert chatbot["vector_store"]["kind"] == "faiss"
    assert chatbot["retrieval"]["top_k_code"] == 8
    assert chatbot["answer"]["api_key_env"] == "CODEWIKI_CHAT_API_KEY"
    assert chatbot["embeddings"]["api_key_env"] == "CODEWIKI_EMBED_API_KEY"
    assert "http://localhost:3000" in chatbot["backend"]["allowed_origins"]
    assert "http://127.0.0.1:3000" in chatbot["backend"]["allowed_origins"]


def test_chatbot_config_merges_nested_values(tmp_path: Path) -> None:
    cfg_path = tmp_path / ".codewiki.yaml"
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
    assert cfg["chatbot"]["answer"]["api_key_env"] == "CODEWIKI_CHAT_API_KEY"
