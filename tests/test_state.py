"""Tests for commit-baseline tracking via .deepdoc/state.json (Phase 1)."""

from __future__ import annotations

import git as _git
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from deepdoc.persistence_v2 import save_sync_state, load_sync_state
from deepdoc.pipeline_v2 import PipelineV2

from .conftest import FakeResult, _run_git, make_bucket, make_plan


def test_save_and_load_sync_state_roundtrip(tmp_repo):
    """Round-trip: save state with all fields, load it back, verify every field."""
    root = tmp_repo
    repo = _git.Repo(root)
    sha = repo.head.commit.hexsha

    save_sync_state(
        root,
        commit_sha=sha,
        status="success",
        generator_version="v2_buckets",
        advance_baseline=True,
    )

    state = load_sync_state(root)
    assert state is not None
    assert state["last_synced_commit"] == sha
    assert state["last_attempted_commit"] == sha
    assert state["status"] == "success"
    assert state["generator_version"] == "v2_buckets"
    assert "synced_at" in state


def test_update_uses_saved_baseline(tmp_repo_with_plan):
    """generate → 3 commits → update should diff from the saved baseline commit."""
    root, plan = tmp_repo_with_plan
    repo = _git.Repo(root)

    # Record the baseline commit (set by the fixture)
    state_before = load_sync_state(root)
    baseline_sha = state_before["last_synced_commit"]

    # Make 3 commits
    for i in range(3):
        (root / f"feature_{i}.py").write_text(f"# feature {i}\n")
        _run_git(root, "add", ".")
        _run_git(root, "commit", "-m", f"add feature_{i}")

    # Baseline should still be the original commit
    state_after = load_sync_state(root)
    assert state_after["last_synced_commit"] == baseline_sha

    # Git diff from baseline to HEAD should catch all 3 new files
    diff = repo.git.diff("--name-only", baseline_sha, "HEAD")
    changed = set(diff.strip().splitlines())
    assert {"feature_0.py", "feature_1.py", "feature_2.py"} <= changed


def test_explicit_since_overrides_baseline(tmp_repo_with_plan):
    """--since HEAD~1 should only see the last commit, ignoring saved baseline."""
    root, plan = tmp_repo_with_plan
    repo = _git.Repo(root)

    # Make 3 commits
    for i in range(3):
        (root / f"new_{i}.py").write_text(f"# new {i}\n")
        _run_git(root, "add", ".")
        _run_git(root, "commit", "-m", f"commit {i}")

    # HEAD~1 should only show the last commit's changes
    diff = repo.git.diff("--name-only", "HEAD~1", "HEAD")
    changed = diff.strip().splitlines()
    assert changed == ["new_2.py"]


def test_failed_update_does_not_advance_baseline(tmp_repo_with_plan):
    """Partial/failed update writes last_attempted_commit but not last_synced_commit."""
    root, plan = tmp_repo_with_plan
    repo = _git.Repo(root)

    original_state = load_sync_state(root)
    original_baseline = original_state["last_synced_commit"]

    # Make a new commit
    (root / "broken.py").write_text("# this will fail\n")
    _run_git(root, "add", ".")
    _run_git(root, "commit", "-m", "add broken file")

    new_sha = repo.head.commit.hexsha
    assert new_sha != original_baseline

    # Simulate a failed update — advance_baseline=False
    save_sync_state(
        root,
        commit_sha=new_sha,
        status="failed",
        advance_baseline=False,
    )

    state = load_sync_state(root)
    assert state["last_synced_commit"] == original_baseline, (
        "Baseline should NOT advance on failure"
    )
    assert state["last_attempted_commit"] == new_sha, (
        "Attempted commit should be updated"
    )
    assert state["status"] == "failed"


def test_partial_generate_does_not_advance_baseline(tmp_repo):
    """Full generate should record partial status and keep the old baseline on failures."""
    root = tmp_repo
    repo = _git.Repo(root)
    original_sha = repo.head.commit.hexsha
    save_sync_state(
        root, commit_sha=original_sha, status="success", advance_baseline=True
    )

    (root / "models.py").write_text("# models module v2\n")
    _run_git(root, "add", ".")
    _run_git(root, "commit", "-m", "change models before partial generate")
    head_sha = repo.head.commit.hexsha

    plan = make_plan(
        [
            make_bucket("Auth System", "auth", ["auth.py"]),
            make_bucket("Core System", "core", ["models.py"]),
        ]
    )
    fake_scan = SimpleNamespace(
        total_files=2,
        languages={"python": 2},
        api_endpoints=[],
        frameworks_detected=[],
        openapi_paths=[],
        entry_points=[],
        config_files=[],
        has_openapi=False,
    )
    gen_results = [
        FakeResult(bucket=plan.buckets[0], content="# Auth\n", error=None),
        FakeResult(bucket=plan.buckets[1], content="# Core\n", error="LLM timeout"),
    ]

    class FakeEngine:
        def __init__(self, *args, **kwargs):
            pass

        def generate_all(self, force=False):
            return gen_results

        def update_manifest(self, results):
            return None

    with patch("deepdoc.pipeline_v2.LLMClient", return_value=MagicMock()):
        pipeline = PipelineV2(
            root,
            {"output_dir": "docs", "llm": {"provider": "anthropic", "model": "test"}},
        )
    with (
        patch("deepdoc.pipeline_v2.bucket_scan_repo", return_value=fake_scan),
        patch("deepdoc.pipeline_v2.bucket_plan_docs", return_value=plan),
        patch("deepdoc.pipeline_v2.BucketGenerationEngine", FakeEngine),
        patch.object(PipelineV2, "_print_scan", return_value=None),
        patch.object(PipelineV2, "_build_site", return_value=None),
        patch.object(PipelineV2, "_print_summary", return_value=None),
    ):
        stats = pipeline.run(force=True)

    state = load_sync_state(root)
    assert stats["status"] == "partial"
    assert stats["pages_generated"] == 1
    assert stats["pages_failed"] == 1
    assert state["last_synced_commit"] == original_sha
    assert state["last_attempted_commit"] == head_sha
    assert state["status"] == "partial"
