from __future__ import annotations

from pathlib import Path

from deepdoc.planner import scan_repo


def test_binary_oversized_minified_and_vendored_files_are_skipped_not_clustered(
    tmp_path: Path,
) -> None:
    (tmp_path / "normal.py").write_text(
        "def real_function():\n    return 1\n", encoding="utf-8"
    )
    (tmp_path / "blob.py").write_bytes(b"header" + b"\x00" * 100 + b"tail")
    (tmp_path / "huge.py").write_text("x = 1\n" * 500_000, encoding="utf-8")
    (tmp_path / "bundle.min.py").write_text("x = 1", encoding="utf-8")
    vendored_dir = tmp_path / "thirdparty" / ".min"
    vendored_dir.mkdir(parents=True)
    (vendored_dir / "app.py").write_text("x = 1", encoding="utf-8")

    # exclude=[] so this test exercises only the new scan guards, not the
    # default exclude globs (which would already drop dist/build/vendor/node_modules).
    scan = scan_repo(
        tmp_path, {"scan": {"max_source_bytes": 1_000}, "exclude": []}
    )

    assert "normal.py" in scan.file_contents
    assert "blob.py" not in scan.file_contents
    assert "huge.py" not in scan.file_contents
    assert "bundle.min.py" not in scan.file_contents
    assert "thirdparty/.min/app.py" not in scan.file_contents

    assert scan.skipped_source_files.get("binary") == 1
    assert scan.skipped_source_files.get("oversized") == 1
    assert scan.skipped_source_files.get("minified") == 1
    assert scan.skipped_source_files.get("generated_or_vendored") == 1


def test_normal_file_is_still_parsed(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def f():\n    pass\n", encoding="utf-8")

    scan = scan_repo(tmp_path, {})

    assert "app.py" in scan.file_contents
    assert "app.py" in scan.parsed_files
    assert scan.skipped_source_files == {}
