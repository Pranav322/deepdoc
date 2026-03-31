"""Tests for find_stale_buckets() (Phase 2 fixes)."""
from __future__ import annotations

from codewiki.persistence_v2 import find_stale_buckets

from .conftest import _sha256_short, make_bucket, make_plan, write_ledger


def test_modified_file_marks_bucket_stale(tmp_repo_with_plan):
    """Changing file content → hash mismatch → bucket is stale."""
    root, plan = tmp_repo_with_plan
    output_dir = root / "docs"

    # Modify auth.py so its hash no longer matches the ledger
    (root / "auth.py").write_text("# auth module v2 — completely rewritten\n")

    stale = find_stale_buckets(plan, root, output_dir=output_dir)
    assert "auth" in stale
    assert "payment" not in stale, "payment should still be clean"


def test_deleted_file_marks_bucket_stale(tmp_repo_with_plan):
    """Deleting an owned file → bucket is stale (not silently skipped)."""
    root, plan = tmp_repo_with_plan
    output_dir = root / "docs"

    # Delete one of payment's owned files
    (root / "utils.py").unlink()

    stale = find_stale_buckets(plan, root, output_dir=output_dir)
    assert "payment" in stale, "payment should be stale because utils.py was deleted"
    assert "auth" not in stale


def test_missing_output_doc_marks_stale(tmp_repo_with_plan):
    """Deleting the generated .mdx file → bucket is stale."""
    root, plan = tmp_repo_with_plan
    output_dir = root / "docs"

    # Delete the auth output doc
    (output_dir / "auth.mdx").unlink()

    stale = find_stale_buckets(plan, root, output_dir=output_dir)
    assert "auth" in stale, "auth should be stale because its .mdx is missing"

    # Without output_dir, the missing doc should NOT be detected
    stale_no_dir = find_stale_buckets(plan, root)
    assert "auth" not in stale_no_dir, \
        "without output_dir, missing doc should not be checked"


def test_new_bucket_with_no_ledger_entry(tmp_repo):
    """A bucket that exists in the plan but has no ledger entry → stale."""
    root = tmp_repo
    output_dir = root / "docs"
    output_dir.mkdir(exist_ok=True)

    b_new = make_bucket("New Feature", "new-feature", ["auth.py"])
    plan = make_plan([b_new])

    # Write an empty ledger — new-feature has no record
    write_ledger(root, {})

    stale = find_stale_buckets(plan, root, output_dir=output_dir)
    assert "new-feature" in stale


def test_previously_failed_bucket_is_stale(tmp_repo):
    """A bucket with success=false in the ledger → stale."""
    root = tmp_repo
    output_dir = root / "docs"
    output_dir.mkdir(exist_ok=True)

    b = make_bucket("Auth", "auth", ["auth.py"])
    plan = make_plan([b])

    write_ledger(root, {
        "auth": {
            "slug": "auth",
            "success": False,
            "error": "LLM timeout",
            "doc_path": "auth.mdx",
            "file_hashes": {"auth.py": _sha256_short("# auth module\n")},
        }
    })

    stale = find_stale_buckets(plan, root, output_dir=output_dir)
    assert "auth" in stale


def test_modified_artifact_marks_bucket_stale(tmp_repo):
    """Changing an artifact_ref should invalidate the owning bucket."""
    root = tmp_repo
    output_dir = root / "docs"
    output_dir.mkdir(exist_ok=True)
    (output_dir / "setup.mdx").write_text("# Setup\n", encoding="utf-8")
    (root / "package.json").write_text('{"name":"demo"}\n', encoding="utf-8")

    plan = make_plan([make_bucket("Setup", "setup", ["auth.py"], artifact_refs=["package.json"])])
    write_ledger(
        root,
        {
            "setup": {
                "slug": "setup",
                "success": True,
                "doc_path": "setup.mdx",
                "file_hashes": {
                    "auth.py": _sha256_short((root / "auth.py").read_text()),
                    "package.json": _sha256_short('{"name":"demo"}\n'),
                },
            }
        },
    )

    (root / "package.json").write_text('{"name":"demo","private":true}\n', encoding="utf-8")

    stale = find_stale_buckets(plan, root, output_dir=output_dir)
    assert "setup" in stale
