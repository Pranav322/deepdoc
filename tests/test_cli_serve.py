from __future__ import annotations

import os
from pathlib import Path

from deepdoc import cli


def test_site_dependencies_need_install_when_lockfile_missing(tmp_path: Path) -> None:
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    (site_dir / "package.json").write_text("{}", encoding="utf-8")
    (site_dir / "node_modules").mkdir()

    assert cli._site_dependencies_need_install(site_dir) is True


def test_site_dependencies_need_install_when_package_json_is_newer(tmp_path: Path) -> None:
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    package_json = site_dir / "package.json"
    package_lock = site_dir / "package-lock.json"
    (site_dir / "node_modules").mkdir()
    package_lock.write_text("{}", encoding="utf-8")
    package_json.write_text("{}", encoding="utf-8")
    os.utime(package_lock, (1, 1))
    os.utime(package_json, (2, 2))

    assert cli._site_dependencies_need_install(site_dir) is True


def test_site_dependencies_need_install_false_when_lockfile_is_current(tmp_path: Path) -> None:
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    package_json = site_dir / "package.json"
    package_lock = site_dir / "package-lock.json"
    (site_dir / "node_modules").mkdir()
    package_json.write_text("{}", encoding="utf-8")
    package_lock.write_text("{}", encoding="utf-8")
    os.utime(package_json, (1, 1))
    os.utime(package_lock, (2, 2))

    assert cli._site_dependencies_need_install(site_dir) is False


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
