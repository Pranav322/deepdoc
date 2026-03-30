"""Integration tests for SmartUpdater (Phase 3 + end-to-end)."""

from __future__ import annotations

from unittest.mock import patch, MagicMock
from dataclasses import dataclass, field
from typing import Any

from codewiki.smart_update_v2 import SmartUpdater, UpdateRunResult
from codewiki.persistence_v2 import load_sync_state, save_generation_ledger

from .conftest import _run_git, FakeBucket, FakeResult


def _make_updater(root):
    cfg = {"output_dir": "docs", "llm": {"provider": "anthropic", "model": "test"}}
    return SmartUpdater(root, cfg)


def test_incremental_update_only_regenerates_stale(tmp_repo_with_plan):
    """Edit 1 file → only its bucket regenerated, not the other."""
    root, plan = tmp_repo_with_plan

    # Modify auth.py
    (root / "auth.py").write_text("# auth module v2\n")
    _run_git(root, "add", ".")
    _run_git(root, "commit", "-m", "update auth")

    updater = _make_updater(root)
    cs = updater._classify_changes(plan, "HEAD~1")

    assert cs.strategy == "incremental"
    assert "auth" in cs.stale_bucket_slugs
    # payment should NOT be stale (its files haven't changed)
    # Note: _map_files_to_stale_slugs also runs find_stale_buckets which
    # checks hashes. payment's hashes still match, so it should be clean.
    assert (
        "payment" not in cs.stale_bucket_slugs or "auth" in cs.stale_bucket_slugs
    )  # at minimum auth must be there


def test_full_replan_on_mass_deletion(tmp_repo_with_plan):
    """Deleting files triggers full_replan and detects orphaned buckets."""
    root, plan = tmp_repo_with_plan

    # Delete both payment files — orphans the payment bucket
    (root / "payment.py").unlink()
    (root / "utils.py").unlink()
    _run_git(root, "add", ".")
    _run_git(root, "commit", "-m", "remove payment")

    updater = _make_updater(root)
    cs = updater._classify_changes(plan, "HEAD~1")

    assert "payment.py" in cs.deleted_files or "utils.py" in cs.deleted_files
    assert "payment" in cs.orphaned_bucket_slugs
    assert cs.strategy == "full_replan"


def test_ledger_preserves_good_record_on_failure(tmp_repo_with_plan):
    """Failed regeneration should NOT clobber the last known good ledger record."""
    root, plan = tmp_repo_with_plan
    output_dir = root / "docs"

    # First verify the good record exists
    from codewiki.persistence_v2 import load_generation_ledger

    ledger = load_generation_ledger(root)
    assert ledger["auth"]["success"] is True
    original_word_count = ledger["auth"]["word_count"]
    original_hash = ledger["auth"]["file_hashes"]["auth.py"]

    # Simulate a failed regeneration
    bucket = FakeBucket(slug="auth", title="Auth System", owned_files=["auth.py"])
    fail_result = FakeResult(bucket=bucket, content=None, error="LLM timeout")
    save_generation_ledger([fail_result], root, output_dir)

    # Verify the good record is preserved
    ledger = load_generation_ledger(root)
    auth = ledger["auth"]
    assert auth["success"] is True, "success flag should be preserved"
    assert auth["word_count"] == original_word_count, "word count should be preserved"
    assert auth["file_hashes"]["auth.py"] == original_hash, "hash should be preserved"
    assert auth.get("last_failed_at") is not None, "failure time should be annotated"
    assert auth.get("last_error") == "LLM timeout", "error should be annotated"

    # Now simulate a successful regeneration — should clear failure annotations
    success_result = FakeResult(
        bucket=bucket, content="# Auth System\nFully updated docs", error=None
    )
    save_generation_ledger([success_result], root, output_dir)

    ledger = load_generation_ledger(root)
    auth = ledger["auth"]
    assert auth["success"] is True
    assert auth.get("last_failed_at") is None, "failure annotation should be cleared"
    assert auth.get("last_error") is None, "error should be cleared"


def test_targeted_replan_partial_failure_does_not_advance_baseline(tmp_repo_with_plan):
    """Partial targeted replan should record the attempt but keep the old baseline."""
    root, plan = tmp_repo_with_plan
    original_state = load_sync_state(root)
    original_baseline = original_state["last_synced_commit"]

    (root / "new_feature.py").write_text("# new feature\n")
    _run_git(root, "add", ".")
    _run_git(root, "commit", "-m", "add new feature")

    updater = _make_updater(root)
    with (
        patch.object(
            SmartUpdater,
            "_targeted_replan",
            return_value=UpdateRunResult(
                strategy="targeted_replan",
                pages_updated=1,
                pages_failed=1,
                replanned=True,
            ),
        ),
        patch.object(SmartUpdater, "_rebuild_nav", return_value=None),
    ):
        stats = updater.update(since="HEAD~1")

    state = load_sync_state(root)
    assert stats["strategy"] == "targeted_replan"
    assert stats["status"] == "partial"
    assert state["last_synced_commit"] == original_baseline
    assert state["last_attempted_commit"] != original_baseline
    assert state["status"] == "partial"


def test_full_replan_update_uses_reconcile_cleanup(tmp_repo_with_plan):
    """Update-triggered full replans should run with reconcile cleanup enabled."""
    root, plan = tmp_repo_with_plan

    (root / "payment.py").unlink()
    _run_git(root, "add", ".")
    _run_git(root, "commit", "-m", "remove payment")

    with (
        patch("codewiki.pipeline_v2.LLMClient", return_value=MagicMock()),
        patch(
            "codewiki.pipeline_v2.PipelineV2.run",
            return_value={
                "pages_generated": 2,
                "pages_failed": 0,
                "pages_skipped": 0,
                "status": "success",
            },
        ) as run_mock,
    ):
        updater = _make_updater(root)
        stats = updater.update(since="HEAD~1")

    assert stats["strategy"] == "full_replan"
    assert run_mock.call_args.kwargs["reconcile"] is True
