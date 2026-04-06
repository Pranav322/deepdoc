"""Tests for ChangeSet classification logic (Phase 2)."""

from __future__ import annotations

import git as _git

from deepdoc.smart_update_v2 import (
    ChangeSet,
    SmartUpdater,
    UpdateRunResult,
)

from .conftest import _run_git


def _make_updater(root):
    cfg = {"output_dir": "docs", "llm": {"provider": "anthropic", "model": "test"}}
    return SmartUpdater(root, cfg)


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_modified_existing_file(tmp_repo_with_plan):
    """Editing a file owned by a bucket → changed_files populated, strategy=incremental."""
    root, plan = tmp_repo_with_plan

    (root / "auth.py").write_text("# auth module v2 — updated\n")
    _run_git(root, "add", ".")
    _run_git(root, "commit", "-m", "update auth")

    updater = _make_updater(root)
    cs = updater._classify_changes(plan, "HEAD~1")

    assert "auth.py" in cs.changed_files
    assert cs.strategy == "incremental"


def test_new_file_after_commits(tmp_repo_with_plan):
    """Adding 3 new files over 3 commits should classify them all as new files."""
    root, plan = tmp_repo_with_plan

    for i in range(3):
        (root / f"feature_{i}.py").write_text(f"# feature {i}\n")
        _run_git(root, "add", ".")
        _run_git(root, "commit", "-m", f"add feature_{i}")

    updater = _make_updater(root)
    # Diff from 3 commits back
    cs = updater._classify_changes(plan, "HEAD~3")

    assert len(cs.new_files) == 3
    assert set(cs.new_files) == {"feature_0.py", "feature_1.py", "feature_2.py"}
    assert cs.strategy == "full_replan"


def test_committed_new_file_triggers_targeted_replan(tmp_repo_with_plan):
    """A committed new source file should trigger targeted replan."""
    root, plan = tmp_repo_with_plan

    (root / "draft_feature.py").write_text("# committed feature\n")
    _run_git(root, "add", ".")
    _run_git(root, "commit", "-m", "add draft feature")

    updater = _make_updater(root)
    cs = updater._classify_changes(plan, "HEAD~1")

    assert "draft_feature.py" in cs.new_files
    assert cs.strategy == "targeted_replan"


def test_untracked_file_is_ignored_by_commit_based_update(tmp_repo_with_plan):
    """Untracked files should not affect commit-based update classification."""
    root, plan = tmp_repo_with_plan

    (root / "draft_feature.py").write_text("# not committed yet\n")

    updater = _make_updater(root)
    repo = _git.Repo(root)
    cs = updater._classify_changes(plan, repo.head.commit.hexsha)

    assert "draft_feature.py" not in cs.new_files
    assert cs.strategy == "noop"


def test_staged_change_is_ignored_by_commit_based_update(tmp_repo_with_plan):
    """Staged but uncommitted changes should not affect update classification."""
    root, plan = tmp_repo_with_plan

    (root / "auth.py").write_text("# staged change only\n")
    _run_git(root, "add", "auth.py")

    updater = _make_updater(root)
    repo = _git.Repo(root)
    cs = updater._classify_changes(plan, repo.head.commit.hexsha)

    assert cs.changed_files == []
    assert cs.stale_bucket_slugs == []
    assert cs.strategy == "noop"


def test_untracked_generated_site_files_are_ignored(tmp_repo_with_plan):
    """DeepDoc-managed generated files should not trigger replans."""
    root, plan = tmp_repo_with_plan

    site_dir = root / "site" / "app"
    site_dir.mkdir(parents=True)
    (site_dir / "page.tsx").write_text(
        "export default function Page() { return null }\n"
    )
    (root / "site" / "package.json").write_text('{"name":"generated-site"}\n')

    updater = _make_updater(root)
    import git as _git

    repo = _git.Repo(root)
    cs = updater._classify_changes(plan, repo.head.commit.hexsha)

    assert cs.new_files == []
    assert cs.changed_artifact_files == []
    assert cs.new_artifact_files == []
    assert cs.strategy == "noop"


def test_deleted_file(tmp_repo_with_plan):
    """Deleting a file owned by a bucket → deleted_files populated, strategy=full_replan."""
    root, plan = tmp_repo_with_plan

    (root / "payment.py").unlink()
    _run_git(root, "add", ".")
    _run_git(root, "commit", "-m", "remove payment.py")

    updater = _make_updater(root)
    cs = updater._classify_changes(plan, "HEAD~1")

    assert "payment.py" in cs.deleted_files
    assert cs.strategy == "full_replan"


def test_renamed_file(tmp_repo_with_plan):
    """git mv old.py new.py → appears as delete + add."""
    root, plan = tmp_repo_with_plan

    _run_git(root, "mv", "auth.py", "authentication.py")
    _run_git(root, "commit", "-m", "rename auth to authentication")

    updater = _make_updater(root)
    changes = updater._get_git_changes("HEAD~1")

    change_dict = {path: status for path, status in changes}
    assert change_dict.get("auth.py") == "D", "old path should appear as deleted"
    assert change_dict.get("authentication.py") == "A", (
        "new path should appear as added"
    )


def test_replan_threshold_triggers(tmp_repo_with_plan):
    """Changing >20% of plan files → strategy=full_replan via REPLAN_THRESHOLD."""
    root, plan = tmp_repo_with_plan

    # Plan has 3 files: auth.py, payment.py, utils.py
    # Changing 1 file = 33% > 20% threshold
    # But deleted_files takes precedence in strategy. So let's test with
    # the ChangeSet directly to isolate threshold logic.
    cs = ChangeSet()
    cs.total_plan_files = 10
    cs.changed_files = ["a.py", "b.py", "c.py"]  # 3/10 = 30% > 20%

    assert cs.strategy == "full_replan"

    # Exactly at threshold: 2/10 = 20% — NOT over
    cs2 = ChangeSet()
    cs2.total_plan_files = 10
    cs2.changed_files = ["a.py", "b.py"]

    assert cs2.strategy == "incremental"


def test_noop_when_nothing_changed(tmp_repo_with_plan):
    """No changes since last commit → strategy=noop."""
    root, plan = tmp_repo_with_plan

    updater = _make_updater(root)
    # HEAD~1..HEAD is the initial commit range — but since the plan's files
    # match the ledger hashes exactly, there should be no changes.
    # Use a commit that IS HEAD to get an empty diff.
    repo = _git.Repo(root)
    cs = updater._classify_changes(plan, repo.head.commit.hexsha)

    assert cs.changed_files == []
    assert cs.new_files == []
    assert cs.deleted_files == []
    assert cs.orphaned_bucket_slugs == []
    assert cs.strategy == "noop"


def test_update_recovers_chatbot_index_even_when_repo_changes_are_noop(
    tmp_repo_with_plan, monkeypatch
):
    root, _plan = tmp_repo_with_plan

    updater = SmartUpdater(
        root,
        {
            "output_dir": "docs",
            "llm": {"provider": "anthropic", "model": "test"},
            "chatbot": {"enabled": True},
        },
    )

    called = {"incremental": 0}

    def _fake_incremental(plan, change_set):
        called["incremental"] += 1
        return UpdateRunResult(
            strategy="incremental", pages_updated=0, pages_failed=0, pages_skipped=0
        )

    monkeypatch.setattr(updater, "_incremental_update", _fake_incremental)
    monkeypatch.setattr(updater, "_save_update_sync_state", lambda **kwargs: None)

    repo = _git.Repo(root)
    stats = updater.update(since=repo.head.commit.hexsha)

    assert called["incremental"] == 1
    assert stats["strategy"] == "incremental"
