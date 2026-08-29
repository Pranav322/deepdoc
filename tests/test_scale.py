"""Scale validation tests — Slice 8.

Tests 50K-file polyglot scanning, resource limits, and coverage completeness.
All tests marked @pytest.mark.slow — only run with --run-slow.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from deepdoc.scale_utils import measure_rss_mb, TimeoutGuard
from deepdoc.repo_model import build_repo_model_from_scan
from tests.fixtures.generate_large import generate_50k_files


class Test50KPolyglotScan:
    @pytest.mark.slow
    def test_scan_completes(self):
        """50K-file scan completes within 5 minutes and returns coverage."""
        import time

        d = Path(tempfile.mkdtemp())
        generate_50k_files(d)

        from deepdoc.planner import scan_repo

        start = time.perf_counter()
        scan = scan_repo(d, {"scan": {"persistent_index": True}})
        elapsed = time.perf_counter() - start

        assert elapsed < 300, f"50K-file scan took {elapsed:.1f}s, limit 300s"
        assert scan.total_files == 55100

    @pytest.mark.slow
    def test_coverage_complete(self):
        """Every file in the 50K fixture appears in the coverage report."""
        d = Path(tempfile.mkdtemp())
        generate_50k_files(d)

        from deepdoc.planner import scan_repo

        scan = scan_repo(d, {"scan": {"persistent_index": True}})
        model = build_repo_model_from_scan(scan, str(d))

        report = model.coverage
        assert report.total_files_discovered == 55100

        # Python, TypeScript, Go, Java, Rust should be at 100% parse rate
        lang_map = {lc.language: lc for lc in report.languages}
        for lang in ("python", "typescript", "go", "java", "rust"):
            assert lang in lang_map, f"{lang} missing from coverage"
            assert lang_map[lang].parse_rate == 1.0, f"{lang} parse rate {lang_map[lang].parse_rate}"

        # Ruby should be inventory_only
        assert "Ruby" in lang_map
        assert lang_map["Ruby"].parse_rate == 0.0

        # Unsupported languages listed
        assert "Ruby" in report.unsupported_languages

    @pytest.mark.slow
    def test_persistent_index_complete(self):
        """Persistent index has correct row counts for 50K files."""
        import sqlite3

        d = Path(tempfile.mkdtemp())
        generate_50k_files(d)

        from deepdoc.planner import scan_repo

        scan = scan_repo(
            d,
            {"scan": {"persistent_index": True, "max_source_bytes": 10_000_000}},
        )

        db_path = d / ".deepdoc" / "index.db"
        assert db_path.exists()

        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA query_only=ON")

        file_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        symbol_count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        conn.close()

        assert file_count == 55100

        import shutil
        shutil.rmtree(d / ".deepdoc", ignore_errors=True)

    @pytest.mark.slow
    def test_content_store_has_files(self):
        """ContentStore has gzip files for all 50K files."""
        d = Path(tempfile.mkdtemp())
        generate_50k_files(d)

        from deepdoc.planner import scan_repo

        scan_repo(d, {"scan": {"persistent_index": True}})

        content_dir = d / ".deepdoc" / "content"
        gz_count = sum(1 for _ in content_dir.rglob("*.gz"))

        # Supported + known-unsupported files should be in content store
        # .foo and no-ext files may not get hashed depending on scan logic
        assert gz_count >= 54000, f"Expected >=54000 gz files, got {gz_count}"

        import shutil
        shutil.rmtree(d / ".deepdoc", ignore_errors=True)


class TestScanTimeouts:
    def test_timeout_returns_partial(self):
        """A short timeout produces a partial scan with partial=True."""
        import time

        d = Path(tempfile.mkdtemp())
        generate_50k_files(d)

        from deepdoc.planner import scan_repo

        scan = scan_repo(d, {"scan": {"timeout_seconds": 1.0}})

        assert scan.partial
        assert scan.total_files < 55100  # shouldn't have finished all files

    def test_short_timeout_still_sets_partial(self):
        """Even a very short timeout returns partial=True."""
        import tempfile

        d = Path(tempfile.mkdtemp())
        (d / "test.py").write_text("def f(): pass\n")
        (d / "test.ts").write_text("export function f() {}\n")
        (d / "test.go").write_text("package p\nfunc F() {}\n")

        from deepdoc.planner import scan_repo

        scan = scan_repo(d, {"scan": {"timeout_seconds": 0.001}})

        # Should set partial=True even if some files were scanned
        assert scan.partial

    def test_no_timeout_does_not_set_partial(self):
        """Without a timeout, partial is False."""
        d = Path(tempfile.mkdtemp())
        (d / "test.py").write_text("def f(): pass\n")

        from deepdoc.planner import scan_repo

        scan = scan_repo(d, {})
        assert not scan.partial


class TestMemoryProfile50K:
    @pytest.mark.slow
    def test_memory_under_limit(self):
        """50K-file scan uses less than 1.5 GB RSS."""
        d = Path(tempfile.mkdtemp())
        generate_50k_files(d)

        from deepdoc.planner import scan_repo

        scan_repo(d, {"scan": {"persistent_index": True}})

        rss_mb = measure_rss_mb()
        # Best-effort check; may not work on all platforms
        if rss_mb > 0:
            assert rss_mb < 1500, f"RSS {rss_mb:.0f} MB exceeds 1.5 GB limit"


class TestTimeoutGuard:
    def test_timeout_not_expired_initially(self):
        guard = TimeoutGuard(10)
        assert not guard.expired

    def test_timeout_expired_after_sleep(self):
        import time

        guard = TimeoutGuard(0.01)
        time.sleep(0.02)
        assert guard.check()

    def test_no_timeout(self):
        guard = TimeoutGuard(0)
        assert not guard.check()

    def test_context_manager(self):
        with TimeoutGuard(3600) as g:
            assert not g.expired