"""Manifest — tracks which files have been documented and at what content hash.

The manifest is stored at {output_dir}/.deepdoc_manifest.json
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
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
        self.path.write_text(json.dumps(self._data, indent=2))

    def get_hash(self, file_path: str) -> str | None:
        return self._data.get(file_path, {}).get("hash")

    def get_doc_path(self, file_path: str) -> str | None:
        return self._data.get(file_path, {}).get("doc_path")

    def update(self, file_path: str, content_hash: str, doc_path: str) -> None:
        self._data[file_path] = {
            "hash": content_hash,
            "doc_path": doc_path,
        }

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
