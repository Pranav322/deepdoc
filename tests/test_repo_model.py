"""Tests for universal RepositoryModel, coverage reporting, and adversarial fixtures.

These tests verify that:
1. RepositoryModel is correctly constructed from RepoScan
2. Coverage reports are accurate for all fixture types
3. Adversarial fixtures catch regressions (test-trap, fixture-trap, etc.)
"""

from __future__ import annotations

from pathlib import Path
import pytest

from deepdoc.planner import scan_repo
from deepdoc.repo_model import (
    RepositoryModel,
    ParseStatus,
    SourceKind,
    FileEntry,
    LanguageInfo,
    CoverageReport,
    LanguageCoverage,
    build_repo_model_from_scan,
)
from deepdoc.planner.engine import _build_repo_model_if_wanted


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "adversarial"


def _scan_and_model(fixture_name: str) -> tuple:
    """Scan an adversarial fixture and return (RepoScan, RepositoryModel)."""
    repo_root = FIXTURES_DIR / fixture_name
    cfg = {"scan": {"build_repo_model": True}}
    scan = scan_repo(repo_root, cfg)
    model = build_repo_model_from_scan(scan, str(repo_root))
    return scan, model


# ---------------------------------------------------------------------------
# RepositoryModel construction
# ---------------------------------------------------------------------------


class TestRepositoryModelConstruction:
    def test_model_from_scan(self):
        scan, model = _scan_and_model("test-file-trap")
        assert isinstance(model, RepositoryModel)
        assert len(model.files) > 0
        assert model.repo_root

    def test_all_files_have_entries(self):
        _, model = _scan_and_model("name-collision")
        paths = {entry.path for entry in model.files.values()}
        assert "src/user_service.py" in paths
        assert "src/order_service.py" in paths
        assert "src/product_service.py" in paths
        assert "src/payment_service.py" in paths
        assert "src/notification_service.py" in paths
        assert len(paths) == 5

    def test_coverage_report_built(self):
        _, model = _scan_and_model("copy-paste-trap")
        assert model.coverage.total_files_discovered == 3
        assert model.coverage.total_files_parsed == 3
        assert len(model.coverage.languages) == 1
        assert model.coverage.languages[0].language == "python"


# ---------------------------------------------------------------------------
# Source kind classification
# ---------------------------------------------------------------------------


class TestSourceKindClassification:
    def test_file_in_test_path_is_classified_as_test(self):
        _, model = _scan_and_model("test-file-trap")
        entry = model.files.get("tests/app/controllers.py")
        assert entry is not None
        assert entry.source_kind == SourceKind.TEST
        assert entry.source_trust < 0.5
        assert entry.is_low_trust

    def test_file_in_fixture_path_is_classified_as_fixture(self):
        _, model = _scan_and_model("fixture-trap")
        entry = model.files.get("tests/fixtures/payment_api.py")
        assert entry is not None
        assert entry.source_kind == SourceKind.FIXTURE
        assert entry.source_trust < 0.5

    def test_generated_file_is_classified_as_generated(self):
        _, model = _scan_and_model("generated-trap")
        entry = model.files.get("src/generated/models.generated.ts")
        assert entry is not None
        assert entry.source_kind == SourceKind.GENERATED

    def test_product_source_has_high_trust(self):
        _, model = _scan_and_model("name-collision")
        entry = model.files.get("src/user_service.py")
        assert entry is not None
        assert entry.source_kind == SourceKind.PRODUCT
        assert entry.source_trust >= 0.9
        assert entry.is_product_source


# ---------------------------------------------------------------------------
# Parse status classification
# ---------------------------------------------------------------------------


class TestParseStatusClassification:
    def test_supported_language_is_fully_parsed(self):
        _, model = _scan_and_model("copy-paste-trap")
        for entry in model.files.values():
            assert entry.language.parse_status == ParseStatus.FULL
            assert entry.language.is_fully_parseable
            assert entry.language.name == "python"

    def test_syntax_errors_cause_partial_parse_status(self):
        model = RepositoryModel(repo_root="/fake")
        entry = FileEntry(
            path="broken.py",
            language=LanguageInfo(name="python", parse_status=ParseStatus.PARTIAL, parse_error="Syntax error at line 3"),
            source_kind=SourceKind.PRODUCT,
        )
        model.add_file(entry)
        model.build_coverage_report()
        assert model.coverage.total_files_partial == 1
        assert model.coverage.total_files_parsed == 0
        assert model.coverage.overall_parse_rate == 0.0

    def test_skipped_files_are_counted(self):
        model = RepositoryModel(repo_root="/fake")
        entry = FileEntry(
            path="huge.py",
            language=LanguageInfo(name="python", parse_status=ParseStatus.SKIPPED, parse_error="File exceeds 1MB limit"),
            source_kind=SourceKind.PRODUCT,
        )
        model.add_file(entry)
        model.build_coverage_report()
        assert model.coverage.total_files_skipped == 1


# ---------------------------------------------------------------------------
# Coverage report accuracy
# ---------------------------------------------------------------------------


class TestCoverageReport:
    def test_polyglot_coverage_has_all_supported_languages(self):
        _, model = _scan_and_model("polyglot-small")
        report = model.coverage
        lang_names = {lc.language for lc in report.languages}
        assert "python" in lang_names
        assert "typescript" in lang_names
        # Ruby and .foo are not in the current scan (Slice 0 — unsupported extensions
        # are not yet tracked as inventory; that's Slice 4's job)

    def test_no_unsupported_languages_in_current_scan(self):
        # Slice 0: unsupported files aren't tracked yet. This test documents that fact.
        # Slice 4 will add them and then this test will change.
        _, model = _scan_and_model("polyglot-small")
        assert not model.coverage.has_unsupported_languages

    def test_overall_parse_rate(self):
        _, model = _scan_and_model("broken-imports")
        assert model.coverage.total_files_discovered == 1
        assert model.coverage.total_files_parsed == 1
        assert model.coverage.overall_parse_rate == 1.0

    def test_coverage_summary_string(self):
        _, model = _scan_and_model("name-collision")
        summary = model.coverage_summary()
        assert "python" in summary
        assert "100%" in summary


# ---------------------------------------------------------------------------
# Edge case: no files
# ---------------------------------------------------------------------------


class TestEmptyModel:
    def test_empty_model_coverage(self):
        model = RepositoryModel(repo_root="/fake")
        model.build_coverage_report()
        assert model.coverage.total_files_discovered == 0
        assert model.coverage.overall_parse_rate == 0.0
        assert model.files == {}


# ---------------------------------------------------------------------------
# Config toggle test
# ---------------------------------------------------------------------------


class TestBuildRepoModelConfig:
    def test_disabled_by_config(self):
        repo_root = FIXTURES_DIR / "copy-paste-trap"
        cfg = {"scan": {"build_repo_model": False}}
        scan = scan_repo(repo_root, cfg)
        assert not hasattr(scan, "_repo_model") or scan._repo_model is None


# ---------------------------------------------------------------------------
# Convenience properties
# ---------------------------------------------------------------------------


class TestConvenienceProperties:
    def test_product_files_filter(self):
        _, model = _scan_and_model("copy-paste-trap")
        product = model.product_files()
        assert len(product) == 3
        assert all(f.source_kind == SourceKind.PRODUCT for f in product)

    def test_files_by_language(self):
        _, model = _scan_and_model("polyglot-small")
        py_files = model.files_by_language("python")
        ts_files = model.files_by_language("typescript")
        assert len(py_files) == 1
        assert len(ts_files) == 1

    def test_no_unsupported_files_yet(self):
        # Slice 0: unsupported extensions are not tracked. Slice 4 will add them.
        _, model = _scan_and_model("polyglot-small")
        unsup = model.unsupported_files()
        assert len(unsup) == 0

    def test_get_file(self):
        _, model = _scan_and_model("broken-imports")
        assert model.get_file("src/main.py") is not None
        assert model.get_file("nonexistent.py") is None