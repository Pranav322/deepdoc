"""Tests for changelog persistence and whats-changed page generation."""

from __future__ import annotations

from pathlib import Path

import pytest

from deepdoc.persistence_v2 import (
    CHANGELOG_MAX_ENTRIES,
    _state_dir,
    append_changelog_entry,
    load_changelog,
)
from deepdoc.changelog_writer import _build_md, write_whats_changed_page


def _make_entry(n: int, is_initial: bool = False) -> dict:
    return {
        "commit": f"abc{n:05d}",
        "date": f"2026-05-{n:02d}",
        "commit_message": f"feat: change {n}",
        "strategy": "incremental",
        "pages_updated": [f"page-{n}"],
        "files_changed": [f"file_{n}.py"],
        "is_initial": is_initial,
    }


def test_append_changelog_entry_creates_file(tmp_path):
    append_changelog_entry(tmp_path, _make_entry(1))
    entries = load_changelog(tmp_path)
    assert len(entries) == 1
    assert entries[0]["commit_message"] == "feat: change 1"


def test_append_changelog_entry_prepends_newest_first(tmp_path):
    append_changelog_entry(tmp_path, _make_entry(1))
    append_changelog_entry(tmp_path, _make_entry(2))
    entries = load_changelog(tmp_path)
    assert entries[0]["commit_message"] == "feat: change 2"
    assert entries[1]["commit_message"] == "feat: change 1"


def test_append_changelog_caps_at_max_entries(tmp_path):
    for i in range(CHANGELOG_MAX_ENTRIES + 1):
        append_changelog_entry(tmp_path, _make_entry(i))
    entries = load_changelog(tmp_path)
    assert len(entries) == CHANGELOG_MAX_ENTRIES


def test_load_changelog_returns_empty_list_if_missing(tmp_path):
    assert load_changelog(tmp_path) == []


def test_write_whats_changed_page_generates_md(tmp_path):
    output_dir = tmp_path / "docs"
    output_dir.mkdir()

    append_changelog_entry(tmp_path, _make_entry(1, is_initial=True))
    append_changelog_entry(tmp_path, _make_entry(2))

    write_whats_changed_page(tmp_path, output_dir)

    md_path = output_dir / "whats-changed.md"
    assert md_path.exists()
    content = md_path.read_text(encoding="utf-8")

    assert "What's Changed" in content
    assert "/// details |" in content
    assert "feat: change 2" in content
    assert "feat: change 1" in content
    assert "created from scratch" in content
    assert "[Page 2](page-2.md)" in content
    assert "[Page 1](page-1.md)" in content
    assert "Incremental update" in content
