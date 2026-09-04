#!/usr/bin/env python3
"""Read-only DeepDoc runtime-surface probe for a checked-out repository.

Run from a DeepDoc worktree so its scanner implementation is what gets measured:
    /path/to/.venv/bin/python /path/to/runtime_phase_probe.py /path/to/repository

This deliberately does not call the LLM, write generated docs, or modify the target
repository. It mirrors the engine's source-selection helpers, reads the selected source
corpus, and times discover_runtime_surfaces() only.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, cast

import deepdoc.parser.registry as parser_registry
from deepdoc.config import load_config
from deepdoc.parser.base import ParsedFile
from deepdoc.parser.registry import supported_extensions
from deepdoc.planner.engine import _matches_any, _skip_reason_for_source_file
from deepdoc.scanner import discover_runtime_surfaces
from deepdoc.source_metadata import classify_source_kind

# This probe intentionally targets the runtime-scan-stabilization branch.
# Keep branch-only symbols dynamic so static analysis against older main remains useful.
language_for_extension = cast(Any, getattr(parser_registry, "language_for_extension"))
runtime_surface_discovery = cast(Any, discover_runtime_surfaces)


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {Path(sys.argv[0]).name} <repository-root>", file=sys.stderr)
        return 2

    repo_root = Path(sys.argv[1]).resolve()
    config_path = repo_root / ".deepdoc.yaml"
    if not repo_root.is_dir() or not config_path.is_file():
        print("Repository root and .deepdoc.yaml are required", file=sys.stderr)
        return 2

    config = load_config(config_path)
    exclude = list(config.get("exclude", []))
    for directory in {
        ".deepdoc",
        "site",
        "chatbot_backend",
        str(config.get("output_dir") or "docs"),
    }:
        if directory not in exclude:
            exclude.append(directory)
    include = config.get("include", [])
    max_source_bytes = int((config.get("scan") or {}).get("max_source_bytes", 1_000_000))
    extensions = supported_extensions()

    selected: list[Path] = []
    for root, directories, filenames in os.walk(repo_root):
        root_path = Path(root)
        directories[:] = sorted(
            directory
            for directory in directories
            if not _matches_any(directory, exclude)
        )
        for filename in sorted(filenames):
            path = root_path / filename
            relative_path = path.relative_to(repo_root).as_posix()
            if _matches_any(relative_path, exclude) or _matches_any(filename, exclude):
                continue
            if path.suffix.lower() not in extensions:
                continue
            if include and not _matches_any(relative_path, include):
                continue
            if _skip_reason_for_source_file(path, relative_path, max_source_bytes):
                continue
            selected.append(path)
    selected.sort(key=lambda path: path.relative_to(repo_root).as_posix())

    source_load_started = time.perf_counter()
    parsed_files: dict[str, ParsedFile] = {}
    file_contents: dict[str, str] = {}
    source_kind_by_file: dict[str, str] = {}
    read_errors = 0
    for path in selected:
        relative_path = path.relative_to(repo_root).as_posix()
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            read_errors += 1
            continue
        parsed_files[relative_path] = ParsedFile(
            path=Path(relative_path),
            language=language_for_extension(path.suffix),
        )
        file_contents[relative_path] = content
        source_kind_by_file[relative_path] = classify_source_kind(relative_path)
    source_load_seconds = time.perf_counter() - source_load_started

    runtime_started = time.perf_counter()
    runtime_scan = runtime_surface_discovery(
        parsed_files,
        file_contents,
        source_kind_by_file=source_kind_by_file,
    )
    runtime_seconds = time.perf_counter() - runtime_started

    result = {
        "probe": "runtime-phase-only",
        "repo": str(repo_root),
        "files_selected": len(file_contents),
        "source_bytes": sum(len(content.encode("utf-8")) for content in file_contents.values()),
        "read_errors": read_errors,
        "source_load_seconds": round(source_load_seconds, 6),
        "runtime_seconds": round(runtime_seconds, 6),
        "source_kind_counts": dict(sorted(Counter(source_kind_by_file.values()).items())),
        "runtime_tasks": len(runtime_scan.tasks),
        "runtime_schedulers": len(runtime_scan.schedulers),
        "realtime_consumers": len(runtime_scan.realtime_consumers),
        "runtime_task_source_kinds": dict(
            sorted(
                Counter(
                    source_kind_by_file.get(task.file_path, "unknown")
                    for task in runtime_scan.tasks
                ).items()
            )
        ),
        "runtime_task_languages": dict(
            sorted(
                Counter(
                    parsed_files[task.file_path].language
                    for task in runtime_scan.tasks
                    if task.file_path in parsed_files
                ).items()
            )
        ),
        "scan_stats": runtime_scan.scan_stats,
        "runtime_tasks_detail": [
            {
                "name": task.name,
                "runtime_kind": task.runtime_kind,
                "decorator": task.decorator,
                "queue": task.queue,
                "file": task.file_path,
                "producers": task.producer_files,
            }
            for task in runtime_scan.tasks
        ],
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
