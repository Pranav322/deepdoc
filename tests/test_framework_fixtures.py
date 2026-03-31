"""Fixture-backed framework scan tests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from deepdoc.config import DEFAULT_CONFIG
from deepdoc.planner_v2 import scan_repo


FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "frameworks"


def _scan_fixture(name: str):
    cfg = deepcopy(DEFAULT_CONFIG)
    return scan_repo(FIXTURES_ROOT / name, cfg)


def test_django_fixture_scan_detects_framework_and_endpoints():
    scan = _scan_fixture("django_app")

    assert "django" in scan.frameworks_detected
    methods_paths = {
        (ep["method"], ep["path"], ep["handler"]) for ep in scan.api_endpoints
    }
    assert ("GET", "/health", "health") in methods_paths
    assert ("GET", "/reports/{slug}", "ReportView") in methods_paths
    assert ("GET", "/api/users", "UserViewSet.list") in methods_paths
    assert ("GET", "/api/users/{id}/stats", "UserViewSet.stats") in methods_paths


def test_express_fixture_scan_detects_prefixed_routes():
    scan = _scan_fixture("express_app")

    assert "express" in scan.frameworks_detected
    methods_paths = {
        (ep["method"], ep["path"], ep["handler"]) for ep in scan.api_endpoints
    }
    assert ("GET", "/api/v1/users", "listUsers") in methods_paths
    assert ("POST", "/api/v1/users", "createUser") in methods_paths
    assert ("GET", "/api/v1/admin/stats", "statsHandler") in methods_paths


def test_fastify_fixture_scan_detects_plugin_prefixed_routes():
    scan = _scan_fixture("fastify_app")

    assert "fastify" in scan.frameworks_detected
    methods_paths = {
        (ep["method"], ep["path"], ep["handler"]) for ep in scan.api_endpoints
    }
    assert ("GET", "/api/v1/users", "listUsers") in methods_paths
    assert ("POST", "/api/v1/users", "createUser") in methods_paths


def test_vue_fixture_scan_detects_framework_and_component_signals():
    scan = _scan_fixture("vue_app")

    assert "vue" in scan.frameworks_detected
    assert scan.languages.get("vue") == 1

    parsed = scan.parsed_files["src/components/UserList.vue"]
    names = {symbol.name for symbol in parsed.symbols}
    assert {"UserList", "props", "emit", "model", "router", "route", "pinia"} <= names
