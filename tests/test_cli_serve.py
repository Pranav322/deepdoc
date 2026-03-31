from __future__ import annotations

from pathlib import Path

from codewiki import cli


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
