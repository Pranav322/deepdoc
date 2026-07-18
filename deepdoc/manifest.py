"""Manifest — tracks which files have been documented and at what content hash.

The manifest is stored at {output_dir}/.deepdoc_manifest.json
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

MANIFEST_FILE = ".deepdoc_manifest.json"


class Manifest:
    """Tracks file → content hash → doc path mappings."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.path = output_dir / MANIFEST_FILE
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except Exception:
                return {}
        return {}

    def save(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._data, indent=2, sort_keys=True) + "\n"
        fd, temp_name = tempfile.mkstemp(
            dir=str(self.output_dir),
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def get_hash(self, file_path: str) -> str | None:
        return self._data.get(file_path, {}).get("hash")

    def get_doc_path(self, file_path: str) -> str | None:
        paths = self.get_doc_paths(file_path)
        return paths[0] if paths else None

    def get_doc_paths(self, file_path: str) -> list[str]:
        record = self._data.get(file_path, {})
        paths = record.get("doc_paths")
        if isinstance(paths, list):
            return sorted({str(path) for path in paths if path})
        legacy_path = record.get("doc_path")
        return [str(legacy_path)] if legacy_path else []

    def update(self, file_path: str, content_hash: str, doc_path: str) -> None:
        doc_paths = set(self.get_doc_paths(file_path))
        if doc_path:
            doc_paths.add(doc_path)
        self._data[file_path] = {
            "hash": content_hash,
            "doc_paths": sorted(doc_paths),
        }

    def is_hash_stale(self, file_path: str, current_hash: str) -> bool:
        return self.get_hash(file_path) != current_hash

    def is_stale(self, file_path: str, current_content: str) -> bool:
        """Returns True if the file has changed since last documentation."""
        current_hash = file_hash(current_content)
        stored_hash = self.get_hash(file_path)
        return stored_hash != current_hash

    def remove(self, file_path: str) -> None:
        self._data.pop(file_path, None)

    def all_files(self) -> list[str]:
        return list(self._data.keys())


def file_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
