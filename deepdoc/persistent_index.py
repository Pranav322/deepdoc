"""SQLite-backed persistent index for file metadata, symbols, and imports.

Replaces the in-memory ``parsed_files: dict[str, ParsedFile]`` with a
disk-backed store under ``.deepdoc/index.db``. WAL journaling allows
concurrent reads (planner, generator) while the scanner writes.

All insert methods are idempotent — re-scanning the same file overwrites
its rows without creating duplicates.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterator


class PersistentIndex:
    """SQLite index for repo scan results.

    Thread-safe: each thread that calls query methods gets its own
    read-only connection. Write methods use a shared connection protected
    by a mutex.

    Typical usage::

        index = PersistentIndex(repo_root)
        file_id = index.upsert_file(...)
        index.upsert_symbols(file_id, parsed_file.symbols)
        index.upsert_imports(file_id, parsed_file.imports)
        index.close()
    """

    _SCHEMA = """
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;
        PRAGMA foreign_keys=ON;

        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rel_path TEXT UNIQUE NOT NULL,
            language TEXT NOT NULL DEFAULT '',
            source_kind TEXT NOT NULL DEFAULT 'product',
            parse_status TEXT NOT NULL DEFAULT 'inventory_only',
            line_count INTEGER NOT NULL DEFAULT 0,
            byte_count INTEGER NOT NULL DEFAULT 0,
            content_hash TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS symbols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT '',
            start_line INTEGER NOT NULL DEFAULT 0,
            end_line INTEGER NOT NULL DEFAULT 0,
            signature TEXT NOT NULL DEFAULT '',
            is_exported INTEGER NOT NULL DEFAULT 0,
            decorators TEXT NOT NULL DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_id);
        CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);

        CREATE TABLE IF NOT EXISTS imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            raw_text TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_imports_file ON imports(file_id);
    """

    def __init__(self, repo_root: Path | str):
        self._db_path = Path(repo_root) / ".deepdoc" / "index.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self._write_conn: sqlite3.Connection | None = None
        self._write_lock = threading.Lock()
        self._local = threading.local()

        self._init_db()

    # ------------------------------------------------------------------
    # Write API (serialised — only scan_repo writes)
    # ------------------------------------------------------------------

    def upsert_file(
        self,
        rel_path: str,
        language: str = "",
        source_kind: str = "product",
        parse_status: str = "inventory_only",
        line_count: int = 0,
        byte_count: int = 0,
        content_hash: str = "",
    ) -> int:
        """Insert or update a file record. Returns the file id."""
        conn = self._ensure_write_conn()
        with self._write_lock:
            conn.execute(
                """INSERT INTO files (rel_path, language, source_kind, parse_status,
                                     line_count, byte_count, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(rel_path) DO UPDATE SET
                     language=excluded.language,
                     source_kind=excluded.source_kind,
                     parse_status=excluded.parse_status,
                     line_count=excluded.line_count,
                     byte_count=excluded.byte_count,
                     content_hash=excluded.content_hash""",
                (rel_path, language, source_kind, parse_status, line_count, byte_count, content_hash),
            )
            conn.commit()
        return self.file_id_for(rel_path)

    def upsert_symbols(self, file_id: int, symbols: list[Any]) -> None:
        """Replace all symbols for a file."""
        conn = self._ensure_write_conn()
        with self._write_lock:
            conn.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
            rows = [
                (
                    file_id,
                    s.name,
                    getattr(s, "kind", ""),
                    getattr(s, "start_line", 0),
                    getattr(s, "end_line", 0),
                    getattr(s, "signature", ""),
                    1 if getattr(s, "is_exported", False) else 0,
                    json.dumps(getattr(s, "decorators", []) or []),
                )
                for s in symbols
            ]
            conn.executemany(
                """INSERT INTO symbols
                   (file_id, name, kind, start_line, end_line, signature, is_exported, decorators)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            conn.commit()

    def upsert_imports(self, file_id: int, imports: list[str]) -> None:
        """Replace all imports for a file."""
        conn = self._ensure_write_conn()
        with self._write_lock:
            conn.execute("DELETE FROM imports WHERE file_id = ?", (file_id,))
            rows = [(file_id, imp) for imp in imports]
            conn.executemany(
                "INSERT INTO imports (file_id, raw_text) VALUES (?, ?)", rows
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Read API (thread-safe — each thread gets its own connection)
    # ------------------------------------------------------------------

    def file_id_for(self, rel_path: str) -> int:
        conn = self._ensure_read_conn()
        row = conn.execute(
            "SELECT id FROM files WHERE rel_path = ?", (rel_path,)
        ).fetchone()
        return row[0] if row else 0

    def query_file(self, rel_path: str) -> dict[str, Any] | None:
        conn = self._ensure_read_conn()
        row = conn.execute(
            "SELECT id, rel_path, language, source_kind, parse_status, "
            "line_count, byte_count, content_hash FROM files WHERE rel_path = ?",
            (rel_path,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_dict(row, ("id", "rel_path", "language", "source_kind", "parse_status", "line_count", "byte_count", "content_hash"))

    def query_symbols_by_file(self, rel_path: str) -> list[dict[str, Any]]:
        conn = self._ensure_read_conn()
        rows = conn.execute(
            """SELECT s.name, s.kind, s.start_line, s.end_line, s.signature,
                      s.is_exported, s.decorators
               FROM symbols s JOIN files f ON s.file_id = f.id
               WHERE f.rel_path = ?""",
            (rel_path,),
        ).fetchall()
        return [_row_to_dict(r, ("name", "kind", "start_line", "end_line", "signature", "is_exported", "decorators")) for r in rows]

    def query_imports_by_file(self, rel_path: str) -> list[str]:
        conn = self._ensure_read_conn()
        rows = conn.execute(
            "SELECT i.raw_text FROM imports i JOIN files f ON i.file_id = f.id WHERE f.rel_path = ?",
            (rel_path,),
        ).fetchall()
        return [r[0] for r in rows]

    def query_files_by_language(self, language: str) -> list[dict[str, Any]]:
        conn = self._ensure_read_conn()
        rows = conn.execute(
            "SELECT id, rel_path, source_kind, parse_status, line_count, byte_count, content_hash "
            "FROM files WHERE language = ?",
            (language,),
        ).fetchall()
        return [_row_to_dict(r, ("id", "rel_path", "source_kind", "parse_status", "line_count", "byte_count", "content_hash")) for r in rows]

    def query_all_files(self) -> list[dict[str, Any]]:
        conn = self._ensure_read_conn()
        rows = conn.execute(
            "SELECT id, rel_path, language, source_kind, parse_status, line_count, byte_count, content_hash FROM files"
        ).fetchall()
        return [_row_to_dict(r, ("id", "rel_path", "language", "source_kind", "parse_status", "line_count", "byte_count", "content_hash")) for r in rows]

    def file_count(self) -> int:
        conn = self._ensure_read_conn()
        row = conn.execute("SELECT COUNT(*) FROM files").fetchone()
        return row[0] if row else 0

    def symbol_count(self) -> int:
        conn = self._ensure_read_conn()
        row = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()
        return row[0] if row else 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        with self._write_lock:
            if self._write_conn:
                self._write_conn.close()
                self._write_conn = None
        if hasattr(self._local, "read_conn") and self._local.read_conn:
            self._local.read_conn.close()
            self._local.read_conn = None

    def __enter__(self) -> PersistentIndex:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        conn = self._ensure_write_conn()
        with self._write_lock:
            conn.executescript(self._SCHEMA)
            conn.commit()

    def _ensure_write_conn(self) -> sqlite3.Connection:
        if self._write_conn is None:
            self._write_conn = sqlite3.connect(str(self._db_path))
            self._write_conn.execute("PRAGMA journal_mode=WAL")
        return self._write_conn

    def _ensure_read_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "read_conn") or self._local.read_conn is None:
            conn = sqlite3.connect(str(self._db_path), uri=False)
            conn.execute("PRAGMA query_only=ON")
            self._local.read_conn = conn
        return self._local.read_conn


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _row_to_dict(row: tuple, columns: tuple[str, ...]) -> dict[str, Any]:
    return dict(zip(columns, row))


__all__ = ["PersistentIndex"]