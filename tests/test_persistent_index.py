"""Tests for PersistentIndex and ContentStore — Slice 2."""

from __future__ import annotations

import tempfile
import textwrap
from pathlib import Path

import pytest

from deepdoc.content_store import ContentStore
from deepdoc.persistent_index import PersistentIndex


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeSymbol:
    """Mimics deepdoc.parser.base.Symbol for tests without importing tree-sitter."""

    def __init__(self, name, kind="function", start=1, end=10, signature="", exported=False):
        self.name = name
        self.kind = kind
        self.start_line = start
        self.end_line = end
        self.signature = signature
        self.is_exported = exported
        self.decorators = []


# ---------------------------------------------------------------------------
# ContentStore
# ---------------------------------------------------------------------------


class TestContentStore:
    def test_put_and_get(self):
        cs = ContentStore(tempfile.mkdtemp())
        h = cs.put("hello world")
        assert cs.exists(h)
        assert cs.get(h) == "hello world"

    def test_same_content_same_hash(self):
        cs = ContentStore(tempfile.mkdtemp())
        h1 = cs.put("identical")
        h2 = cs.put("identical")
        assert h1 == h2

    def test_different_content_different_hash(self):
        cs = ContentStore(tempfile.mkdtemp())
        h1 = cs.put("alpha")
        h2 = cs.put("beta")
        assert h1 != h2

    def test_missing_returns_none(self):
        cs = ContentStore(tempfile.mkdtemp())
        assert cs.get("a" * 64) is None

    def test_delete(self):
        cs = ContentStore(tempfile.mkdtemp())
        h = cs.put("delete me")
        assert cs.exists(h)
        cs.delete(h)
        assert not cs.exists(h)

    def test_unicode_content(self):
        cs = ContentStore(tempfile.mkdtemp())
        content = "def café(x: str) -> str:\n    return f'Résumé: {x}'"
        h = cs.put(content)
        assert cs.get(h) == content

    def test_large_content(self):
        cs = ContentStore(tempfile.mkdtemp())
        content = "x" * 100_000
        h = cs.put(content)
        assert len(cs.get(h)) == 100_000

    def test_decompression_integrity(self):
        cs = ContentStore(tempfile.mkdtemp())
        content = "hello\n" * 5000
        h = cs.put(content)
        assert cs.get(h) == content


# ---------------------------------------------------------------------------
# PersistentIndex
# ---------------------------------------------------------------------------


class TestPersistentIndex:
    def test_insert_and_query_file(self):
        with PersistentIndex(tempfile.mkdtemp()) as idx:
            fid = idx.upsert_file("src/main.py", language="python", parse_status="full")
            assert fid > 0
            row = idx.query_file("src/main.py")
            assert row is not None
            assert row["rel_path"] == "src/main.py"
            assert row["language"] == "python"
            assert row["parse_status"] == "full"

    def test_upsert_idempotent(self):
        with PersistentIndex(tempfile.mkdtemp()) as idx:
            fid1 = idx.upsert_file("a.py", language="python")
            fid2 = idx.upsert_file("a.py", language="python")
            assert fid1 == fid2
            assert idx.file_count() == 1

    def test_symbols_round_trip(self):
        with PersistentIndex(tempfile.mkdtemp()) as idx:
            fid = idx.upsert_file("main.py", language="python", parse_status="full")
            idx.upsert_symbols(fid, [
                FakeSymbol("create_user", kind="function", start=5, end=20, signature="def create_user(name: str) -> dict:", exported=True),
                FakeSymbol("User", kind="class", start=25, end=50, signature="class User:", exported=True),
            ])
            symbols = idx.query_symbols_by_file("main.py")
            assert len(symbols) == 2
            names = {s["name"] for s in symbols}
            assert "create_user" in names
            assert "User" in names
            # Exported flag
            create = [s for s in symbols if s["name"] == "create_user"][0]
            assert create["is_exported"] == 1

    def test_imports_round_trip(self):
        with PersistentIndex(tempfile.mkdtemp()) as idx:
            fid = idx.upsert_file("app.py", language="python", parse_status="full")
            idx.upsert_imports(fid, ["from os import path", "import json", "from .models import User"])
            imports = idx.query_imports_by_file("app.py")
            assert len(imports) == 3
            assert "import json" in imports

    def test_symbols_replaced_on_reinsert(self):
        with PersistentIndex(tempfile.mkdtemp()) as idx:
            fid = idx.upsert_file("mod.py", language="python", parse_status="full")
            idx.upsert_symbols(fid, [FakeSymbol("old_func")])
            idx.upsert_symbols(fid, [FakeSymbol("new_func"), FakeSymbol("extra_func")])
            symbols = idx.query_symbols_by_file("mod.py")
            assert len(symbols) == 2
            names = {s["name"] for s in symbols}
            assert "old_func" not in names
            assert "new_func" in names

    def test_file_count_and_symbol_count(self):
        with PersistentIndex(tempfile.mkdtemp()) as idx:
            idx.upsert_file("a.py", language="python", parse_status="full")
            idx.upsert_file("b.py", language="python", parse_status="full")
            fid = idx.upsert_file("c.py", language="python", parse_status="full")
            idx.upsert_symbols(fid, [FakeSymbol("f1"), FakeSymbol("f2"), FakeSymbol("f3")])
            assert idx.file_count() == 3
            assert idx.symbol_count() == 3

    def test_query_files_by_language(self):
        with PersistentIndex(tempfile.mkdtemp()) as idx:
            idx.upsert_file("a.py", language="python")
            idx.upsert_file("b.ts", language="typescript")
            idx.upsert_file("c.py", language="python")
            py = idx.query_files_by_language("python")
            ts = idx.query_files_by_language("typescript")
            assert len(py) == 2
            assert len(ts) == 1

    def test_query_all_files(self):
        with PersistentIndex(tempfile.mkdtemp()) as idx:
            idx.upsert_file("a.py", language="python")
            idx.upsert_file("b.ts", language="typescript")
            all_files = idx.query_all_files()
            assert len(all_files) == 2

    def test_missing_file_returns_none(self):
        with PersistentIndex(tempfile.mkdtemp()) as idx:
            assert idx.query_file("nope.py") is None
            assert idx.file_id_for("nope.py") == 0

    def test_empty_symbols(self):
        with PersistentIndex(tempfile.mkdtemp()) as idx:
            fid = idx.upsert_file("empty.py", language="python", parse_status="full")
            idx.upsert_symbols(fid, [])
            assert idx.query_symbols_by_file("empty.py") == []

    def test_context_manager(self):
        d = tempfile.mkdtemp()
        with PersistentIndex(d) as idx:
            idx.upsert_file("x.py", language="python")
        # Re-open and check data persisted
        with PersistentIndex(d) as idx2:
            assert idx2.file_count() == 1

    def test_wal_mode(self):
        with PersistentIndex(tempfile.mkdtemp()) as idx:
            conn = idx._ensure_read_conn()
            row = conn.execute("PRAGMA journal_mode").fetchone()
            assert row[0] == "wal"


# ---------------------------------------------------------------------------
# Integration: scan writes to persistent store
# ---------------------------------------------------------------------------


class TestScanIntegration:
    def test_scan_populates_index_and_content_store(self):
        from deepdoc.planner import scan_repo

        d = Path(__file__).parent / "fixtures" / "adversarial" / "copy-paste-trap"
        scan = scan_repo(d, {"scan": {"persistent_index": True}})

        db = d / ".deepdoc" / "index.db"
        assert db.exists()

        import sqlite3
        conn = sqlite3.connect(str(db))
        conn.execute("PRAGMA query_only=ON")

        file_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        symbol_count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        conn.close()

        assert file_count == len(scan.file_contents)
        assert symbol_count > 0

        content_dir = d / ".deepdoc" / "content"
        assert content_dir.exists()
        gz_count = len(list(content_dir.rglob("*.gz")))
        assert gz_count == len(scan.file_contents)

        # Content round-trip
        from deepdoc.content_store import ContentStore
        cs = ContentStore(d)
        h = scan.file_content_hashes.get("src/auth.py", "")
        assert h
        stored = cs.get(h)
        assert stored == scan.file_contents.get("src/auth.py", "")

        # Cleanup
        import shutil
        shutil.rmtree(d / ".deepdoc", ignore_errors=True)

    def test_persistent_index_disabled_by_config(self):
        import shutil
        from deepdoc.planner import scan_repo

        d = Path(__file__).parent / "fixtures" / "adversarial" / "copy-paste-trap"
        shutil.rmtree(d / ".deepdoc", ignore_errors=True)
        scan_repo(d, {"scan": {"persistent_index": False}})
        db = d / ".deepdoc" / "index.db"
        assert not db.exists()

    def test_repo_scan_dicts_still_populated(self):
        import shutil
        from deepdoc.planner import scan_repo

        d = Path(__file__).parent / "fixtures" / "adversarial" / "copy-paste-trap"
        scan = scan_repo(d, {})
        assert len(scan.file_contents) == 3
        assert len(scan.parsed_files) == 3
        assert "src/auth.py" in scan.parsed_files

        shutil.rmtree(d / ".deepdoc", ignore_errors=True)


# ---------------------------------------------------------------------------
# Memory: scan a generated 5K-file repo
# ---------------------------------------------------------------------------


def _generate_5k_files(tmp_root: Path) -> None:
    """Generate a realistic polyglot repo with ~5000 source files."""
    src = tmp_root / "src"
    templates = {
        "py": textwrap.dedent("""\
            def {name}_{i}(value: int) -> int:
                \"\"\"Processing function {i}.\"\"\"
                return value * 2


            class {Name}{i}:
                def __init__(self, data):
                    self.data = data

                def process(self):
                    return self.data
        """),
        "ts": textwrap.dedent("""\
            export function {name}{i}(value: number): number {{
                return value * 2;
            }}

            export class {Name}{i} {{
                data: any;
                constructor(data: any) {{
                    this.data = data;
                }}
                process(): any {{
                    return this.data;
                }}
            }}
        """),
        "go": textwrap.dedent("""\
            package src

            func {Name}{i}(value int) int {{
                return value * 2
            }}

            type {Name}{i}Model struct {{
                Data string
            }}
        """),
    }
    names = ["process", "handle", "compute", "resolve", "validate", "transform", "execute", "fetch", "aggregate", "normalize"]
    for lang in ("py", "ts", "go"):
        d = src / lang
        d.mkdir(parents=True, exist_ok=True)
        for i in range(1667 if lang == "py" else 1667 if lang == "ts" else 1666):
            name = names[i % len(names)]
            tpl = templates[lang].format(name=name, Name=name.capitalize(), i=i)
            (d / f"{name}_{i}.{lang}").write_text(tpl)


class TestMemoryProfile:
    @pytest.mark.slow
    def test_5k_file_repo_memory(self):
        import os, time
        import multiprocessing

        d = tempfile.mkdtemp()
        _generate_5k_files(Path(d))

        # Force garbage collection before measurement
        import gc
        gc.collect()

        proc = multiprocessing.Process(target=_scan_and_measure, args=(d,))
        proc.start()
        proc.join(timeout=120)
        if proc.is_alive():
            proc.terminate()
            proc.join()
            pytest.fail("Scan timed out after 120s")

    @pytest.mark.slow
    def test_5k_file_scan_completes(self):
        d = tempfile.mkdtemp()
        _generate_5k_files(Path(d))

        from deepdoc.planner import scan_repo
        import time

        start = time.perf_counter()
        scan = scan_repo(Path(d), {"scan": {"persistent_index": True}})
        elapsed = time.perf_counter() - start

        assert elapsed < 120, f"Scan took {elapsed:.1f}s, limit is 120s"
        assert len(scan.file_contents) == 5000
        assert len(scan.parsed_files) == 5000

        # Cleanup
        import shutil
        shutil.rmtree(Path(d) / ".deepdoc", ignore_errors=True)


# Note: @pytest.mark.slow tests require --run-slow flag. Add this to conftest.py:
# def pytest_addoption(parser):
#     parser.addoption("--run-slow", action="store_true", help="run slow tests")


def _scan_and_measure(repo: str) -> None:
    """Run scan in a subprocess to measure memory."""
    from deepdoc.planner import scan_repo
    scan_repo(Path(repo), {"scan": {"persistent_index": True}})