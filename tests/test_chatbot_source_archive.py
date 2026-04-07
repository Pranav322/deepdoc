from __future__ import annotations

from pathlib import Path

from deepdoc.chatbot.persistence import load_source_archive, save_source_archive
from deepdoc.chatbot.source_archive import update_source_archive


def test_update_source_archive_removes_stale_entry_when_file_is_oversized(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "src").mkdir()
    source_path = repo_root / "src" / "payments.py"
    source_path.write_text('PAYMENTS_HOST = "old"\n', encoding="utf-8")

    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_source_archive(index_dir, {"src/payments.py": 'PAYMENTS_HOST = "stale"\n'})

    cfg = {"chatbot": {"indexing": {"max_file_bytes": 32}}}
    source_path.write_text("X" * 512, encoding="utf-8")

    update_source_archive(
        repo_root,
        index_dir,
        cfg,
        changed_files=["src/payments.py"],
        deleted_files=[],
    )

    archive = load_source_archive(index_dir)
    assert "src/payments.py" not in archive


def test_update_source_archive_removes_stale_entry_when_file_is_now_excluded(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "src").mkdir()
    source_path = repo_root / "src" / "secret.py"
    source_path.write_text("API_KEY = 'abc'\n", encoding="utf-8")

    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_source_archive(index_dir, {"src/secret.py": "API_KEY = 'stale'\n"})

    cfg = {
        "exclude": ["src/secret.py"],
        "chatbot": {"indexing": {"max_file_bytes": 250000, "exclude_globs": []}},
    }

    update_source_archive(
        repo_root,
        index_dir,
        cfg,
        changed_files=["src/secret.py"],
        deleted_files=[],
    )

    archive = load_source_archive(index_dir)
    assert "src/secret.py" not in archive


def test_update_source_archive_removes_stale_entry_when_file_is_binary(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "src").mkdir()
    source_path = repo_root / "src" / "dump.bin"
    source_path.write_bytes(b"\x00\x10\x20binary")

    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_source_archive(index_dir, {"src/dump.bin": "stale text"})

    cfg = {"chatbot": {"indexing": {"max_file_bytes": 250000}}}
    update_source_archive(
        repo_root,
        index_dir,
        cfg,
        changed_files=["src/dump.bin"],
        deleted_files=[],
    )

    archive = load_source_archive(index_dir)
    assert "src/dump.bin" not in archive


def test_update_source_archive_bootstraps_when_archive_missing(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "src").mkdir()
    source_path = repo_root / "src" / "payments.py"
    source_path.write_text('PAYMENTS_HOST = "live"\n', encoding="utf-8")

    index_dir = repo_root / ".deepdoc" / "chatbot"
    cfg = {"chatbot": {"indexing": {"max_file_bytes": 250000}}}

    update_source_archive(
        repo_root,
        index_dir,
        cfg,
        changed_files=[],
        deleted_files=[],
    )

    archive = load_source_archive(index_dir)
    assert archive.get("src/payments.py") == 'PAYMENTS_HOST = "live"\n'


def test_update_source_archive_bootstraps_when_archive_is_empty(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "src").mkdir()
    source_path = repo_root / "src" / "payments.py"
    source_path.write_text('PAYMENTS_HOST = "live"\n', encoding="utf-8")

    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_source_archive(index_dir, {})
    cfg = {"chatbot": {"indexing": {"max_file_bytes": 250000}}}

    update_source_archive(
        repo_root,
        index_dir,
        cfg,
        changed_files=[],
        deleted_files=[],
    )

    archive = load_source_archive(index_dir)
    assert archive.get("src/payments.py") == 'PAYMENTS_HOST = "live"\n'
