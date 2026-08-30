"""Tests for unknown-language inventory fallback — Slice 4."""

from __future__ import annotations

from pathlib import Path

from deepdoc.repo_model import ParseStatus, RepositoryModel, build_repo_model_from_scan
from deepdoc.planner import scan_repo


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "adversarial"


def _scan_model(fixture: str):
    d = FIXTURES_DIR / fixture
    s = scan_repo(d, {})
    return s, build_repo_model_from_scan(s, str(d))


class TestUnsupportedLanguageInventory:
    """Every file gets a FileEntry — supported or not."""

    def test_ruby_in_inventory(self):
        _, m = _scan_model("polyglot-small")
        entry = m.get_file("src/legacy.rb")
        assert entry is not None
        assert entry.language.name == "Ruby"
        assert entry.language.parse_status == ParseStatus.INVENTORY_ONLY
        assert not entry.language.is_fully_parseable

    def test_unknown_extension_in_inventory(self):
        _, m = _scan_model("polyglot-small")
        entry = m.get_file("src/config.foo")
        assert entry is not None
        assert entry.language.parse_status == ParseStatus.INVENTORY_ONLY

    def test_no_extension_in_inventory(self):
        _, m = _scan_model("unknown-foo")
        entry = m.get_file("src/README")
        assert entry is not None
        assert entry.language.parse_status == ParseStatus.UNKNOWN
        assert entry.language.name == "unknown"

    def test_supported_files_still_fully_parsed(self):
        _, m = _scan_model("polyglot-small")
        py = m.get_file("src/main.py")
        ts = m.get_file("src/server.ts")
        assert py.language.parse_status == ParseStatus.FULL
        assert ts.language.parse_status == ParseStatus.FULL

    def test_unsupported_files_visible(self):
        _, m = _scan_model("polyglot-small")
        unsup = m.unsupported_files()
        paths = {f.path for f in unsup}
        assert "src/legacy.rb" in paths
        assert "src/config.foo" in paths
        assert len(unsup) == 2


class TestCoverageReport:
    def test_parse_rates_per_language(self):
        _, m = _scan_model("polyglot-small")
        report = m.coverage
        lang_map = {lc.language: lc for lc in report.languages}
        assert lang_map["python"].parse_rate == 1.0
        assert lang_map["typescript"].parse_rate == 1.0
        assert lang_map["Ruby"].parse_rate == 0.0
        assert lang_map["Ruby"].inventory_only == 1

    def test_unsupported_languages_listed(self):
        _, m = _scan_model("polyglot-small")
        assert "Ruby" in m.coverage.unsupported_languages
        assert "foo" in m.coverage.unsupported_languages

    def test_supported_only_repo_no_unsupported(self):
        _, m = _scan_model("name-collision")
        assert not m.coverage.has_unsupported_languages

    def test_total_files_includes_all(self):
        _, m = _scan_model("polyglot-small")
        assert m.coverage.total_files_discovered == 4
        assert m.coverage.total_files_parsed == 2
        assert m.coverage.total_files_inventory_only == 2

    def test_coverage_summary_mentions_inventory(self):
        _, m = _scan_model("polyglot-small")
        summary = m.coverage_summary()
        assert "inventory only" in summary


class TestGuardBehavior:
    """The pipeline guard should allow supported + unsupported mixed repos."""

    def test_mixed_repo_passes_guard(self):
        from deepdoc.pipeline_v2 import PipelineV2

        d = FIXTURES_DIR / "polyglot-small"
        s = scan_repo(d, {})
        p = PipelineV2(d, {"output_dir": "docs", "llm": {"provider": "anthropic", "model": "test"}})
        p._guard_supported_source_files(s)

    def test_unsupported_only_raises(self):
        import tempfile, shutil
        import click
        from deepdoc.pipeline_v2 import PipelineV2

        d = Path(tempfile.mkdtemp())
        (d / "legacy.rb").write_text("class Foo\nend")
        s = scan_repo(d, {})
        p = PipelineV2(d, {"output_dir": "docs", "llm": {"provider": "anthropic", "model": "test"}})
        try:
            p._guard_supported_source_files(s)
            assert False, "Should have raised"
        except click.ClickException as e:
            assert "No parseable source files" in str(e)
        finally:
            shutil.rmtree(d, ignore_errors=True)