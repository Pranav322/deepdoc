from __future__ import annotations

from pathlib import Path

from deepdoc.config import DEFAULT_CONFIG
from deepdoc.parser.api_detector import detect_endpoints as facade_detect_endpoints
from deepdoc.parser.routes import ROUTE_DETECTOR_REGISTRY, detect_endpoints
from deepdoc.planner import scan_repo


def test_route_registry_is_the_single_dispatch_entrypoint() -> None:
    assert tuple(d.name for d in ROUTE_DETECTOR_REGISTRY["javascript"]) == (
        "express",
        "fastify",
        "nestjs",
    )
    assert tuple(d.name for d in ROUTE_DETECTOR_REGISTRY["python"]) == (
        "falcon",
        "django",
    )
    assert tuple(d.name for d in ROUTE_DETECTOR_REGISTRY["go"]) == ("go",)
    assert tuple(d.name for d in ROUTE_DETECTOR_REGISTRY["php"]) == ("laravel",)


def test_api_detector_facade_delegates_to_routes_package() -> None:
    content = """
const express = require('express')
const app = express()
const router = express.Router()
router.get('/health', healthHandler)
app.use('/api/v1', router)
"""
    facade = facade_detect_endpoints(Path("server.js"), content, "javascript")
    modular = detect_endpoints(Path("server.js"), content, "javascript")

    assert facade == modular
    assert [(ep.method, ep.path, ep.handler) for ep in facade] == [
        ("GET", "/api/v1/health", "healthHandler")
    ]


def test_scan_repo_uses_route_dispatcher_output(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "server.js").write_text(
        """
const express = require('express')
const app = express()
const router = express.Router()
router.get('/health', healthHandler)
app.use('/api/v1', router)
""",
        encoding="utf-8",
    )

    scan = scan_repo(repo_root, DEFAULT_CONFIG)

    assert any(
        ep["method"] == "GET"
        and ep["path"] == "/api/v1/health"
        and ep["handler"] == "healthHandler"
        and ep["file"] == "server.js"
        and ep["route_file"] == "server.js"
        and ep["handler_file"] == "server.js"
        and ep["line"] == 5
        for ep in scan.api_endpoints
    )
