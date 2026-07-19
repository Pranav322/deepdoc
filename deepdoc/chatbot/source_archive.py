"""Standalone source archive management to power chatbot operations without a local repo."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from ..source_metadata import classify_source_kind
from .persistence import (
    LEGACY_SOURCE_ARCHIVE_FILE,
    SOURCE_ARCHIVE_DB_FILE,
    SOURCE_ARCHIVE_SCHEMA_VERSION,
    apply_source_archive_changes,
    load_source_archive,
    load_source_catalog,
    save_source_archive,
    source_archive_metadata,
)
from .types import SourceCatalogEntry

DEFAULT_SOURCE_ARCHIVE_EXCLUDES = [
    ".deepdoc",
    ".deepdoc/**",
    ".deepdoc_plan.json",
    ".deepdoc_file_map.json",
    ".deepdoc*.json",
    "docs",
    "docs/**",
    "site",
    "site/**",
    "chatbot_backend",
    "chatbot_backend/**",
]


def build_source_archive(
    repo_root: Path,
    index_dir: Path,
    cfg: dict[str, Any],
) -> None:
    """Scan the local repo root and pack raw source text into a compressed archive.

    This archive is used by the chatbot (e.g. `service.py` or `deep_research.py`) at
    query time so that grep, exact-match lookups, and deep codebase reading still work
    even when the documentation is exported and hosted remotely without the full repository.
    """
    indexing_cfg = cfg.get("chatbot", {}).get("indexing", {})
    max_file_bytes = int(indexing_cfg.get("max_file_bytes", 250000))
    exclude_patterns = _source_archive_exclude_patterns(cfg)

    archive_data: dict[str, str] = {}
    for root, dirs, file_names in os.walk(repo_root):
        root_path = Path(root)
        rel_dir = (
            root_path.relative_to(repo_root).as_posix()
            if root_path != repo_root
            else "."
        )
        dirs[:] = [
            directory
            for directory in dirs
            if not _matches_any_exclude(directory, exclude_patterns)
            and not _matches_any_exclude(
                f"{rel_dir}/{directory}" if rel_dir != "." else directory,
                exclude_patterns,
            )
        ]
        for file_name in sorted(file_names):
            rel_path = (root_path / file_name).relative_to(repo_root).as_posix()
            content = _read_archiveable_text(
                repo_root,
                rel_path,
                max_file_bytes=max_file_bytes,
                exclude_patterns=exclude_patterns,
            )
            if content is None:
                continue
            archive_data[rel_path] = content

    save_source_archive(
        index_dir,
        archive_data,
        entries=_source_catalog_entries(archive_data),
        policy_fingerprint=_source_archive_policy_fingerprint(cfg),
    )


def update_source_archive(
    repo_root: Path,
    index_dir: Path,
    cfg: dict[str, Any],
    changed_files: list[str],
    deleted_files: list[str],
) -> None:
    """Incrementally updates the source archive with changed file contents."""
    indexing_cfg = cfg.get("chatbot", {}).get("indexing", {})
    max_file_bytes = int(indexing_cfg.get("max_file_bytes", 250000))
    exclude_patterns = _source_archive_exclude_patterns(cfg)
    policy_fingerprint = _source_archive_policy_fingerprint(cfg)
    archive_path = index_dir / SOURCE_ARCHIVE_DB_FILE

    if not archive_path.exists():
        legacy_path = index_dir / LEGACY_SOURCE_ARCHIVE_FILE
        legacy_archive = load_source_archive(index_dir) if legacy_path.exists() else {}
        if legacy_archive:
            save_source_archive(
                index_dir,
                legacy_archive,
                entries=_source_catalog_entries(legacy_archive),
                policy_fingerprint=policy_fingerprint,
            )
            legacy_path.unlink(missing_ok=True)
            (index_dir / "source_catalog.json").unlink(missing_ok=True)
        else:
            build_source_archive(repo_root, index_dir, cfg)
            return

    metadata = source_archive_metadata(index_dir)
    if (
        metadata.get("schema_version") != str(SOURCE_ARCHIVE_SCHEMA_VERSION)
        or metadata.get("policy_fingerprint") != policy_fingerprint
    ):
        build_source_archive(repo_root, index_dir, cfg)
        return

    deleted_paths = set(deleted_files)
    upserts: dict[str, tuple[str, SourceCatalogEntry]] = {}
    for rel_path in sorted(set(changed_files)):
        content = _read_archiveable_text(
            repo_root,
            rel_path,
            max_file_bytes=max_file_bytes,
            exclude_patterns=exclude_patterns,
        )
        if content is None:
            deleted_paths.add(rel_path)
            continue
        entry = _source_catalog_entries({rel_path: content})[0]
        upserts[rel_path] = (content, entry)

    if not upserts and not deleted_paths:
        return

    apply_source_archive_changes(
        index_dir,
        upserts=upserts,
        deleted_paths=deleted_paths,
        policy_fingerprint=policy_fingerprint,
    )


def source_archive_needs_rebuild(
    repo_root: Path,
    index_dir: Path,
    cfg: dict[str, Any],
) -> bool:
    """Return whether the source archive or catalog is missing/stale."""
    archive_path = index_dir / SOURCE_ARCHIVE_DB_FILE
    if archive_path.exists():
        metadata = source_archive_metadata(index_dir)
        if metadata.get("schema_version") != str(SOURCE_ARCHIVE_SCHEMA_VERSION):
            return True
        if metadata.get(
            "policy_fingerprint"
        ) != _source_archive_policy_fingerprint(cfg):
            return True
        try:
            import sqlite3

            conn = sqlite3.connect(archive_path)
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            missing_blobs = conn.execute(
                """
                SELECT COUNT(*) FROM files
                LEFT JOIN blobs USING (content_hash)
                WHERE blobs.content_hash IS NULL
                """
            ).fetchone()
            return (
                not integrity
                or integrity[0] != "ok"
                or not missing_blobs
                or int(missing_blobs[0]) != 0
            )
        except Exception:
            return True
        finally:
            if "conn" in locals():
                conn.close()

    legacy_path = index_dir / LEGACY_SOURCE_ARCHIVE_FILE
    if not legacy_path.exists():
        return True
    archive_data = load_source_archive(index_dir)
    catalog_entries = load_source_catalog(index_dir)
    return not archive_data or {
        entry.file_path for entry in catalog_entries
    } != set(archive_data)


def _source_archive_policy_fingerprint(cfg: dict[str, Any]) -> str:
    indexing_cfg = cfg.get("chatbot", {}).get("indexing", {})
    payload = {
        "schema_version": SOURCE_ARCHIVE_SCHEMA_VERSION,
        "max_file_bytes": int(indexing_cfg.get("max_file_bytes", 250000)),
        "exclude": sorted(_source_archive_exclude_patterns(cfg)),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def source_path_is_archiveable(
    repo_root: Path,
    rel_path: str,
    cfg: dict[str, Any],
) -> bool:
    """Return whether a repo path is currently allowed in source-backed indexes."""
    indexing_cfg = cfg.get("chatbot", {}).get("indexing", {})
    max_file_bytes = int(indexing_cfg.get("max_file_bytes", 250000))
    exclude_patterns = _source_archive_exclude_patterns(cfg)
    return (
        _read_archiveable_text(
            repo_root,
            rel_path,
            max_file_bytes=max_file_bytes,
            exclude_patterns=exclude_patterns,
        )
        is not None
    )


def _source_catalog_entries(archive_data: dict[str, str]) -> list[SourceCatalogEntry]:
    entries: list[SourceCatalogEntry] = []
    for rel_path, content in sorted(archive_data.items()):
        encoded = content.encode("utf-8", errors="replace")
        entries.append(
            SourceCatalogEntry(
                file_path=rel_path,
                content_hash=hashlib.sha256(encoded).hexdigest(),
                source_kind=classify_source_kind(rel_path),
                language=_language_for_path(rel_path),
                total_lines=len(content.splitlines()),
                size_bytes=len(encoded),
            )
        )
    return entries


def _language_for_path(rel_path: str) -> str:
    suffix = Path(rel_path).suffix.lower()
    return {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".go": "go",
        ".php": "php",
        ".java": "java",
        ".rb": "ruby",
        ".rs": "rust",
        ".vue": "vue",
        ".svelte": "svelte",
        ".html": "html",
        ".css": "css",
        ".scss": "scss",
        ".sass": "sass",
        ".json": "json",
        ".toml": "toml",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".ini": "ini",
        ".cfg": "ini",
    }.get(suffix, suffix.lstrip("."))


def _repo_has_archiveable_files(
    repo_root: Path,
    *,
    max_file_bytes: int,
    exclude_patterns: list[str],
) -> bool:
    for root, dirs, file_names in os.walk(repo_root):
        root_path = Path(root)
        rel_dir = (
            root_path.relative_to(repo_root).as_posix()
            if root_path != repo_root
            else "."
        )
        dirs[:] = [
            directory
            for directory in dirs
            if not _matches_any_exclude(directory, exclude_patterns)
            and not _matches_any_exclude(
                f"{rel_dir}/{directory}" if rel_dir != "." else directory,
                exclude_patterns,
            )
        ]
        for file_name in file_names:
            rel_path = (root_path / file_name).relative_to(repo_root).as_posix()
            content = _read_archiveable_text(
                repo_root,
                rel_path,
                max_file_bytes=max_file_bytes,
                exclude_patterns=exclude_patterns,
            )
            if content is not None:
                return True
    return False


def _source_archive_exclude_patterns(cfg: dict[str, Any]) -> list[str]:
    indexing_cfg = cfg.get("chatbot", {}).get("indexing", {})
    return (
        list(DEFAULT_SOURCE_ARCHIVE_EXCLUDES)
        + list(cfg.get("exclude", []))
        + list(indexing_cfg.get("exclude_globs", []))
    )


def _read_archiveable_text(
    repo_root: Path,
    rel_path: str,
    *,
    max_file_bytes: int,
    exclude_patterns: list[str],
) -> str | None:
    if _matches_any_exclude(rel_path, exclude_patterns):
        return None
    path = repo_root / rel_path
    try:
        if not path.exists() or not path.is_file():
            return None
        if path.stat().st_size > max_file_bytes:
            return None
        with path.open("rb") as handle:
            sample = handle.read(2048)
        if b"\x00" in sample:
            return None
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if not content.strip():
        return None
    return content


def _matches_any_exclude(path: str, patterns: list[str]) -> bool:
    normalized = path.replace("\\", "/")
    for pattern in patterns:
        if (
            fnmatch.fnmatch(normalized, pattern)
            or fnmatch.fnmatch(Path(normalized).name, pattern)
            or pattern in normalized.split("/")
        ):
            return True
    return False
