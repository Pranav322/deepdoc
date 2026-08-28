"""Content-addressed file storage.

Stores gzip-compressed source text keyed by SHA-256 content hash in
``.deepdoc/content/{hash[:2]}/{hash}.gz``. Identical files are de-duplicated
automatically — same content = same hash = same file on disk.

The ``ContentStore`` replaces the in-memory ``file_contents`` dict
while preserving backward compat (``RepoScan.file_contents`` is still
hydrated during the deprecation period).
"""

from __future__ import annotations

import gzip
import hashlib
import os
from pathlib import Path


class ContentStore:
    """Content-addressed gzip-compressed source storage.

    Thread-safe for concurrent reads. Not safe for concurrent writes —
    writes happen during scan_repo() only, which is serialised by the
    state lock.
    """

    def __init__(self, repo_root: Path | str):
        self._root = Path(repo_root)
        self._content_dir = self._root / ".deepdoc" / "content"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def put(self, content: str) -> str:
        """Store content and return its SHA-256 hex hash.

        If content with the same hash already exists this is a no-op.
        """
        content_hash = _sha256(content)
        if self.exists(content_hash):
            return content_hash
        dest = self._path_for(content_hash)
        dest.parent.mkdir(parents=True, exist_ok=True)
        compressed = gzip.compress(content.encode("utf-8"), compresslevel=6)
        _atomic_write(dest, compressed)
        return content_hash

    def get(self, content_hash: str) -> str | None:
        """Return stored content, or None if not found.

        Accepts both full 64-char SHA-256 and the 16-char truncated hash
        used by ``manifest.file_hash()``.
        """
        if len(content_hash) == 16:
            path = self._glob_for_prefix(content_hash)
            if path is None:
                return None
        else:
            path = self._path_for(content_hash)
            if not path.is_file():
                return None
        try:
            compressed = path.read_bytes()
            return gzip.decompress(compressed).decode("utf-8")
        except (OSError, gzip.BadGzipFile, UnicodeDecodeError):
            return None

    def exists(self, content_hash: str) -> bool:
        if len(content_hash) == 16:
            return self._glob_for_prefix(content_hash) is not None
        return self._path_for(content_hash).is_file()

    def delete(self, content_hash: str) -> None:
        """Delete a single content blob."""
        if len(content_hash) == 16:
            path = self._glob_for_prefix(content_hash)
            if path is None:
                return
        else:
            path = self._path_for(content_hash)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        # Clean up empty prefix directory
        parent = path.parent
        if parent != self._content_dir and not any(parent.iterdir()):
            try:
                parent.rmdir()
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _path_for(self, content_hash: str) -> Path:
        return self._content_dir / content_hash[:2] / f"{content_hash}.gz"

    def _glob_for_prefix(self, prefix: str) -> Path | None:
        """Find a content blob by its 16-char truncated hash prefix."""
        prefix_dir = self._content_dir / prefix[:2]
        if not prefix_dir.is_dir():
            return None
        for f in prefix_dir.glob(f"{prefix}*.gz"):
            return f
        return None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    """Write to a temp file, fsync, then rename atomically."""
    import tempfile

    tmp = tempfile.NamedTemporaryFile(dir=path.parent, delete=False, suffix=".tmp")
    try:
        tmp.write(data)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, str(path))
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


__all__ = ["ContentStore"]