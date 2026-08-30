"""Tests for the LanguageSupport registry — Slice 1.

Verifies that the registry produces identical mappings to the existing
parser/registry.py _REGISTRY and planner/engine.py ext_to_lang dict.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from deepdoc.language_support import (
    LanguageSupport,
    get_language_support_registry,
    get_language_support,
    supported_extensions_from_registry,
    language_name_for_extension,
)
from deepdoc.parser.registry import _REGISTRY, supported_extensions as old_supported_extensions
from deepdoc.parser.routes.registry import ROUTE_DETECTOR_REGISTRY


# ---------------------------------------------------------------------------
# Registry correctness
# ---------------------------------------------------------------------------


class TestRegistryCorrectness:
    """Every extension must map identically in old and new registries."""

    def test_all_extensions_present(self):
        reg = get_language_support_registry()
        for ext in old_supported_extensions():
            assert ext in reg, f"Extension {ext} missing from LanguageSupport registry"

    def test_no_extra_extensions(self):
        reg = get_language_support_registry()
        for ext in reg:
            assert ext in old_supported_extensions(), f"Extension {ext} not in old registry"

    def test_language_name_matches(self):
        reg = get_language_support_registry()
        for ext, (old_lang, _old_fn) in _REGISTRY.items():
            entry = reg[ext]
            assert entry.language == old_lang, f"Language for {ext}: {entry.language} != {old_lang}"

    def test_parser_fn_matches(self):
        reg = get_language_support_registry()
        for ext, (old_lang, old_fn) in _REGISTRY.items():
            entry = reg[ext]
            assert entry.parser_fn is old_fn, (
                f"Parser for {ext} differs: {entry.parser_fn} vs {old_fn}"
            )

    def test_shared_instance_per_language(self):
        reg = get_language_support_registry()
        assert reg[".js"] is reg[".jsx"]
        assert reg[".js"] is reg[".mjs"]
        assert reg[".js"] is reg[".cjs"]
        assert reg[".ts"] is reg[".tsx"]

    def test_correct_language_count(self):
        reg = get_language_support_registry()
        unique_langs = {entry.language for entry in reg.values()}
        assert len(unique_langs) == 8  # python, javascript, typescript, go, php, vue, java, rust


# ---------------------------------------------------------------------------
# Route detector attachment
# ---------------------------------------------------------------------------


class TestRouteDetectorAttachment:
    """Route detectors must be registered for every supported language."""

    def test_python_has_detectors(self):
        reg = get_language_support_registry()
        py_entry = reg[".py"]
        assert len(py_entry.route_detectors) == 3
        names = {d.name for d in py_entry.route_detectors}
        assert names == {"falcon", "django", "fastapi"}

    def test_javascript_has_detectors(self):
        reg = get_language_support_registry()
        js_entry = reg[".js"]
        assert len(js_entry.route_detectors) == 3
        names = {d.name for d in js_entry.route_detectors}
        assert names == {"express", "fastify", "nestjs"}

    def test_typescript_has_detectors(self):
        reg = get_language_support_registry()
        ts_entry = reg[".ts"]
        assert len(ts_entry.route_detectors) == 3
        names = {d.name for d in ts_entry.route_detectors}
        assert names == {"express", "fastify", "nestjs"}

    def test_go_has_detector(self):
        reg = get_language_support_registry()
        go_entry = reg[".go"]
        assert len(go_entry.route_detectors) == 1
        assert go_entry.route_detectors[0].name == "go"

    def test_php_has_detector(self):
        reg = get_language_support_registry()
        php_entry = reg[".php"]
        assert len(php_entry.route_detectors) == 1
        assert php_entry.route_detectors[0].name == "laravel"

    def test_vue_has_detectors(self):
        reg = get_language_support_registry()
        vue_entry = reg[".vue"]
        assert len(vue_entry.route_detectors) == 2
        names = {d.name for d in vue_entry.route_detectors}
        assert names == {"express", "fastify"}

    def test_route_detector_registry_matches(self):
        reg = get_language_support_registry()
        for lang, detectors in ROUTE_DETECTOR_REGISTRY.items():
            entry = [e for e in reg.values() if e.language == lang]
            assert entry, f"No LanguageSupport entry for {lang}"
            assert entry[0].route_detectors == detectors


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------


class TestConvenienceFunctions:
    def test_language_name_for_extension_known(self):
        assert language_name_for_extension(".py") == "python"
        assert language_name_for_extension(".ts") == "typescript"
        assert language_name_for_extension(".go") == "go"

    def test_language_name_for_extension_unknown(self):
        assert language_name_for_extension(".rb") == "rb"
        assert language_name_for_extension("") == ""

    def test_language_name_for_extension_mixed_case(self):
        assert language_name_for_extension(".PY") == "python"
        assert language_name_for_extension(".Ts") == "typescript"

    def test_get_language_support_known(self):
        entry = get_language_support(".py")
        assert entry is not None
        assert entry.language == "python"
        assert entry.is_supported

    def test_get_language_support_unknown(self):
        entry = get_language_support(".xyz")
        assert entry is None

    def test_supported_extensions_match(self):
        new_ext = supported_extensions_from_registry()
        old_ext = old_supported_extensions()
        assert new_ext == old_ext

    def test_unsupported_entry_has_no_parser(self):
        # Even though we don't register unsupported entries in Slice 1, test the pattern
        noop = LanguageSupport(language="ruby", extensions=[".rb"])
        assert not noop.is_supported
        assert noop.parser_fn is None


# ---------------------------------------------------------------------------
# End-to-end: scan_repo produces identical output
# ---------------------------------------------------------------------------


class TestScanRepoIntegration:
    def test_scan_produces_same_languages(self):
        from deepdoc.planner import scan_repo

        d = Path(__file__).parent / "fixtures" / "adversarial" / "name-collision"
        scan = scan_repo(d, {})
        assert scan.languages == {"python": 5}
        assert scan.total_files > 0

    def test_scan_copies_paste_trap(self):
        from deepdoc.planner import scan_repo

        d = Path(__file__).parent / "fixtures" / "adversarial" / "copy-paste-trap"
        scan = scan_repo(d, {})
        assert scan.languages == {"python": 3}
        assert len(scan.file_contents) == 3
        assert len(scan.parsed_files) == 3


# ---------------------------------------------------------------------------
# Java + Rust registry entries (Slice 3)
# ---------------------------------------------------------------------------


class TestJavaRustSupport:
    def test_java_is_in_registry(self):
        reg = get_language_support_registry()
        assert ".java" in reg
        entry = reg[".java"]
        assert entry.language == "java"
        assert entry.is_supported

    def test_rust_is_in_registry(self):
        reg = get_language_support_registry()
        assert ".rs" in reg
        entry = reg[".rs"]
        assert entry.language == "rust"
        assert entry.is_supported

    def test_java_and_rust_have_parser(self):
        from deepdoc.parser.java_parser import parse_java
        from deepdoc.parser.rust_parser import parse_rust
        reg = get_language_support_registry()
        assert reg[".java"].parser_fn is parse_java
        assert reg[".rs"].parser_fn is parse_rust

    def test_java_and_rust_have_no_route_detectors(self):
        reg = get_language_support_registry()
        assert reg[".java"].route_detectors == ()
        assert reg[".rs"].route_detectors == ()

    def test_java_not_in_unsupported_languages(self):
        from deepdoc.source_metadata import KNOWN_UNSUPPORTED_LANGUAGE_EXTENSIONS
        assert ".java" not in KNOWN_UNSUPPORTED_LANGUAGE_EXTENSIONS

    def test_rust_not_in_unsupported_languages(self):
        from deepdoc.source_metadata import KNOWN_UNSUPPORTED_LANGUAGE_EXTENSIONS
        assert ".rs" not in KNOWN_UNSUPPORTED_LANGUAGE_EXTENSIONS

    def test_scan_java_fixture(self):
        from deepdoc.planner import scan_repo

        d = Path(__file__).parent / "fixtures" / "frameworks" / "java_app"
        scan = scan_repo(d, {})
        assert "java" in scan.languages
        assert scan.languages["java"] == 4

    def test_scan_rust_fixture(self):
        from deepdoc.planner import scan_repo

        d = Path(__file__).parent / "fixtures" / "frameworks" / "rust_app"
        scan = scan_repo(d, {})
        assert "rust" in scan.languages
        assert scan.languages["rust"] == 1