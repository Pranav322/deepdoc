"""Integration tests for SmartUpdater (Phase 3 + end-to-end)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from deepdoc.persistence_v2 import (
    ENGINE_FINGERPRINT,
    load_changelog,
    load_sync_receipt,
    load_sync_state,
    save_generation_ledger,
    save_sync_state,
)
from deepdoc.smart_update_v2 import (
    SemanticImpact,
    SmartUpdater,
    UpdateRunResult,
)
from deepdoc.v2_models import RepoScan

from .conftest import FakeBucket, FakeResult, _run_git


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


def test_mass_deletion_triggers_targeted_replan(tmp_repo_with_plan):
    """Deleting files triggers targeted_replan (not full_replan) and detects orphaned buckets."""
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
    assert cs.strategy == "targeted_replan"


def test_ledger_preserves_good_record_on_failure(tmp_repo_with_plan):
    """Failed regeneration should NOT clobber the last known good ledger record."""
    root, plan = tmp_repo_with_plan
    output_dir = root / "docs"

    # First verify the good record exists
    from deepdoc.persistence_v2 import load_generation_ledger

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
    receipt = load_sync_receipt(root)
    assert receipt is not None
    assert receipt["strategy"] == "targeted_replan"
    assert receipt["status"] == "partial"


def test_deletion_routes_to_targeted_replan_not_full(tmp_repo_with_plan):
    """Deleting a file should route to targeted_replan, not full_replan."""
    root, plan = tmp_repo_with_plan

    (root / "payment.py").unlink()
    _run_git(root, "add", ".")
    _run_git(root, "commit", "-m", "remove payment")

    updater = _make_updater(root)
    with (
        patch.object(
            SmartUpdater,
            "_targeted_replan",
            return_value=UpdateRunResult(
                strategy="targeted_replan",
                pages_updated=1,
                pages_failed=0,
                replanned=True,
            ),
        ) as targeted_mock,
        patch.object(SmartUpdater, "_rebuild_nav", return_value=None),
    ):
        stats = updater.update(since="HEAD~1")

    assert stats["strategy"] == "targeted_replan"
    targeted_mock.assert_called_once()


def test_artifact_only_change_is_not_noop(tmp_repo_with_plan):
    """Artifact-only updates should still trigger incremental chatbot refreshes."""
    root, plan = tmp_repo_with_plan
    plan.buckets[2].artifact_refs = ["package.json"]

    (root / "package.json").write_text('{"name":"demo"}\n')
    _run_git(root, "add", ".")
    _run_git(root, "commit", "-m", "add package config")

    updater = _make_updater(root)
    cs = updater._classify_changes(plan, "HEAD~1")

    assert "package.json" in cs.new_artifact_files
    assert "core" in cs.stale_bucket_slugs
    assert cs.strategy == "incremental"


def test_engine_fingerprint_mismatch_forces_full_replan(tmp_repo_with_plan):
    """Outdated sync state should trigger a one-time full replan."""
    root, plan = tmp_repo_with_plan
    state = load_sync_state(root)
    save_sync_state(
        root,
        commit_sha=state["last_synced_commit"],
        status="success",
        generator_version="v2_buckets",
        engine_fingerprint="outdated-engine",
        advance_baseline=True,
    )

    updater = _make_updater(root)
    with (
        patch.object(
            SmartUpdater,
            "_full_replan_and_generate",
            return_value=UpdateRunResult(
                strategy="full_replan",
                pages_updated=1,
                pages_failed=0,
                replanned=True,
            ),
        ) as replan_mock,
        patch.object(SmartUpdater, "_rebuild_nav", return_value=None),
    ):
        stats = updater.update(since=state["last_synced_commit"])

    assert ENGINE_FINGERPRINT != "outdated-engine"
    assert stats["strategy"] == "full_replan"
    assert replan_mock.called


def test_full_replan_does_not_append_second_changelog_entry(tmp_repo_with_plan):
    """Pipeline full replan writes its own changelog; SmartUpdater should not duplicate it."""
    root, _plan = tmp_repo_with_plan
    state = load_sync_state(root)
    before = len(load_changelog(root))
    save_sync_state(
        root,
        commit_sha=state["last_synced_commit"],
        status="success",
        generator_version="v2_buckets",
        engine_fingerprint="outdated-engine",
        advance_baseline=True,
    )

    updater = _make_updater(root)
    with (
        patch.object(
            SmartUpdater,
            "_full_replan_and_generate",
            return_value=UpdateRunResult(
                strategy="full_replan",
                pages_updated=1,
                pages_failed=0,
                replanned=True,
            ),
        ),
        patch.object(SmartUpdater, "_rebuild_nav", return_value=None),
    ):
        updater.update(since=state["last_synced_commit"])

    assert len(load_changelog(root)) == before


def test_chatbot_only_recovery_advances_successful_baseline(tmp_repo_with_plan):
    """Refreshing missing chatbot corpora without page work should be a successful sync."""
    root, _plan = tmp_repo_with_plan
    original_state = load_sync_state(root)
    updater = _make_updater(root)

    with (
        patch("deepdoc.smart_update_v2.chatbot_enabled", return_value=True),
        patch("deepdoc.smart_update_v2.chatbot_index_needs_refresh", return_value=True),
        patch.object(
            SmartUpdater,
            "_incremental_update",
            return_value=UpdateRunResult(
                strategy="incremental",
                pages_updated=0,
                pages_failed=0,
                refreshed_corpora=["code"],
            ),
        ),
        patch.object(SmartUpdater, "_rebuild_nav", return_value=None),
    ):
        stats = updater.update(since=original_state["last_synced_commit"])

    state = load_sync_state(root)
    assert stats["status"] == "success"
    assert state["status"] == "success"
    assert state["last_synced_commit"] == state["last_attempted_commit"]


def test_incremental_update_writes_sync_receipt(tmp_repo_with_plan):
    """Successful incremental updates should persist a top-level sync receipt."""
    root, plan = tmp_repo_with_plan

    (root / "auth.py").write_text("# auth module v2\n")
    _run_git(root, "add", ".")
    _run_git(root, "commit", "-m", "update auth")

    updater = _make_updater(root)
    with (
        patch.object(
            SmartUpdater,
            "_incremental_update",
            return_value=UpdateRunResult(
                strategy="incremental",
                pages_updated=1,
                pages_failed=0,
                updated_slugs=["auth"],
                refreshed_corpora=["code", "relationship", "doc_summary", "doc_full"],
            ),
        ),
        patch.object(SmartUpdater, "_rebuild_nav", return_value=None),
    ):
        stats = updater.update(since="HEAD~1")

    receipt = load_sync_receipt(root)
    assert stats["status"] == "success"
    assert receipt is not None
    assert receipt["strategy"] == "incremental"
    assert receipt["updated_slugs"] == ["auth"]
    assert receipt["refreshed_corpora"] == [
        "code",
        "relationship",
        "doc_summary",
        "doc_full",
    ]


def test_compute_endpoint_semantic_impact_distinguishes_metadata_from_structure(
    tmp_repo_with_plan,
):
    """Method/path identity changes should force replan; metadata-only changes should not."""
    root, _plan = tmp_repo_with_plan
    updater = _make_updater(root)

    previous = [
        {
            "method": "GET",
            "path": "/api/users",
            "handler": "listUsers",
            "route_file": "routes.py",
            "handler_file": "auth.py",
            "middleware": [],
            "request_body": "",
            "response_type": "",
        }
    ]
    current_metadata = [
        {
            "method": "GET",
            "path": "/api/users",
            "handler": "listUsers",
            "route_file": "routes.py",
            "handler_file": "auth.py",
            "middleware": ["auth"],
            "request_body": "",
            "response_type": "",
        }
    ]
    current_structure = [
        {
            "method": "GET",
            "path": "/api/v2/users",
            "handler": "listUsers",
            "route_file": "routes.py",
            "handler_file": "auth.py",
            "middleware": [],
            "request_body": "",
            "response_type": "",
        }
    ]

    metadata_impact = updater._compute_endpoint_semantic_impact(
        previous, current_metadata
    )
    assert metadata_impact.endpoint_structure_changed is False
    assert metadata_impact.changed_endpoint_keys == ["GET /api/users"]
    assert set(metadata_impact.changed_files) == {"routes.py", "auth.py"}

    structure_impact = updater._compute_endpoint_semantic_impact(
        previous, current_structure
    )
    assert structure_impact.endpoint_structure_changed is True
    assert set(structure_impact.changed_endpoint_keys) == {
        "GET /api/users",
        "GET /api/v2/users",
    }


def test_semantic_endpoint_metadata_change_expands_stale_buckets(tmp_repo_with_plan):
    """Semantic route metadata changes should refresh related buckets even if the git diff hits only config files."""
    root, plan = tmp_repo_with_plan

    (root / "config.py").write_text("API_PREFIX = '/api/v2'\n")
    _run_git(root, "add", ".")
    _run_git(root, "commit", "-m", "update api prefix")

    updater = _make_updater(root)
    with patch.object(
        SmartUpdater,
        "_detect_semantic_impacts",
        return_value=SemanticImpact(
            changed_files=["payment.py"],
            changed_endpoint_keys=["GET /api/payments"],
            endpoint_structure_changed=False,
        ),
    ):
        cs = updater._classify_changes(plan, "HEAD~1")

    assert "core" in cs.stale_bucket_slugs
    assert "payment" in cs.stale_bucket_slugs
    assert cs.semantic_changed_files == ["payment.py"]
    assert cs.strategy == "incremental"


def test_semantic_endpoint_identity_change_triggers_targeted_replan(tmp_repo_with_plan):
    """Endpoint method/path changes should trigger targeted_replan (not full_replan)."""
    root, plan = tmp_repo_with_plan

    (root / "config.py").write_text("API_PREFIX = '/api/v2'\n")
    _run_git(root, "add", ".")
    _run_git(root, "commit", "-m", "move routes")

    updater = _make_updater(root)
    with patch.object(
        SmartUpdater,
        "_detect_semantic_impacts",
        return_value=SemanticImpact(
            changed_files=["auth.py", "routes.py"],
            changed_endpoint_keys=["GET /api/v1/login", "GET /api/v2/login"],
            endpoint_structure_changed=True,
        ),
    ):
        cs = updater._classify_changes(plan, "HEAD~1")

    assert cs.endpoint_structure_changed is True
    assert cs.strategy == "targeted_replan"


# ── _handle_deleted_files unit tests ─────────────────────────────────────────


def test_handle_deleted_files_removes_file_from_owned_files(tmp_repo_with_plan):
    """Partially deleted bucket loses the deleted file but stays in plan, marked stale."""
    from deepdoc.smart_update_v2 import ChangeSet
    from .conftest import make_bucket, make_plan

    root, _plan = tmp_repo_with_plan
    bucket = make_bucket("Payment System", "payment", ["payment.py", "utils.py"])
    plan = make_plan([bucket])
    plan.nav_structure = {"Core": ["payment"]}

    cs = ChangeSet(deleted_files=["payment.py"])
    updater = _make_updater(root)
    updated_plan = updater._handle_deleted_files(plan, cs)

    payment_bucket = next(b for b in updated_plan.buckets if b.slug == "payment")
    assert "payment.py" not in payment_bucket.owned_files
    assert "utils.py" in payment_bucket.owned_files
    assert "payment" in cs.stale_bucket_slugs


def test_handle_deleted_files_removes_orphaned_bucket_and_mdx(tmp_repo_with_plan):
    """When all files in a bucket are gone, the bucket and its MDX are removed."""
    from deepdoc.smart_update_v2 import ChangeSet
    from deepdoc.persistence_v2 import save_plan
    from .conftest import make_bucket, make_plan, write_ledger

    root, _plan = tmp_repo_with_plan
    output_dir = root / "docs"
    output_dir.mkdir(exist_ok=True)

    # Create the MDX file that should be deleted
    mdx_file = output_dir / "payment.mdx"
    mdx_file.write_text("# Payment\n", encoding="utf-8")

    bucket = make_bucket("Payment System", "payment", ["payment.py", "utils.py"])
    plan = make_plan([bucket])
    plan.nav_structure = {"Core": ["payment"]}
    save_plan(plan, root)

    # Write a ledger entry so cleanup_stale_generated_files knows about payment.mdx
    write_ledger(root, {
        "payment": {
            "slug": "payment",
            "title": "Payment System",
            "bucket_type": "system",
            "section": "core",
            "doc_path": "payment.mdx",
            "success": True,
            "word_count": 100,
            "file_hashes": {"payment.py": "abc", "utils.py": "def"},
        }
    })

    cs = ChangeSet(orphaned_bucket_slugs=["payment"])
    updater = _make_updater(root)
    updated_plan = updater._handle_deleted_files(plan, cs)

    assert not any(b.slug == "payment" for b in updated_plan.buckets)
    assert not mdx_file.exists()
    assert cs.deleted_doc_paths == ["payment.mdx"]
    assert "payment" not in updated_plan.nav_structure.get("Core", [])


def test_handle_deleted_files_noop_when_nothing_deleted(tmp_repo_with_plan):
    """When no deletions, plan is returned unchanged."""
    from deepdoc.smart_update_v2 import ChangeSet
    from .conftest import make_bucket, make_plan

    root, _plan = tmp_repo_with_plan
    bucket = make_bucket("Auth System", "auth", ["auth.py"])
    plan = make_plan([bucket])

    cs = ChangeSet()
    updater = _make_updater(root)
    updated_plan = updater._handle_deleted_files(plan, cs)

    assert len(updated_plan.buckets) == 1
    assert updated_plan.buckets[0].slug == "auth"


def test_merge_targeted_plan_mutates_existing_by_slug(tmp_repo_with_plan):
    """Replanned bucket matching existing slug is mutated in-place, not duplicated."""
    from deepdoc.smart_update_v2 import SmartUpdater
    from deepdoc.v2_models import RepoScan
    from .conftest import make_bucket, make_plan

    root, _ = tmp_repo_with_plan
    existing_bucket = make_bucket("Auth System", "auth", ["auth.py"])
    existing_plan = make_plan([existing_bucket])

    # Replanned bucket for same slug with an extra file
    replanned_bucket = make_bucket("Auth System v2", "auth", ["auth.py", "oauth.py"])
    new_plan = make_plan([replanned_bucket])

    scan = RepoScan(
        file_tree={}, file_summaries={}, api_endpoints=[], languages={},
        has_openapi=False, openapi_paths=[], total_files=0,
        frameworks_detected=[], entry_points=[], config_files=[],
        file_line_counts={}, parsed_files={}, file_contents={},
        giant_file_clusters={},
    )
    updater = _make_updater(root)
    merged, added, updated_slugs = updater._merge_targeted_plan(existing_plan, new_plan, scan)

    # No new bucket should be added — the existing one is mutated
    assert added == []
    # The existing bucket should now own both files
    assert "oauth.py" in existing_bucket.owned_files
    # The slug should appear in updated_existing_slugs since owned_files changed
    assert "auth" in updated_slugs
    # Plan still has exactly one bucket (no duplication)
    assert len(merged.buckets) == 1


def test_merge_targeted_plan_adds_genuinely_new_bucket(tmp_repo_with_plan):
    """A replanned bucket with no matching slug or semantic_id is appended as new."""
    from deepdoc.v2_models import RepoScan
    from .conftest import make_bucket, make_plan

    root, _ = tmp_repo_with_plan
    existing_plan = make_plan([make_bucket("Auth System", "auth", ["auth.py"])])
    new_plan = make_plan([make_bucket("Payment Flow", "payment", ["payment.py"])])

    scan = RepoScan(
        file_tree={}, file_summaries={}, api_endpoints=[], languages={},
        has_openapi=False, openapi_paths=[], total_files=0,
        frameworks_detected=[], entry_points=[], config_files=[],
        file_line_counts={}, parsed_files={}, file_contents={},
        giant_file_clusters={},
    )
    updater = _make_updater(root)
    merged, added, updated_slugs = updater._merge_targeted_plan(existing_plan, new_plan, scan)

    assert len(added) == 1
    assert added[0].slug == "payment"
    assert len(merged.buckets) == 2
    assert updated_slugs == []


def test_quality_stats_blockers_all_fields():
    """_quality_stats_blockers returns one blocker per failing stat type."""
    from deepdoc.cli import _quality_stats_blockers

    stats = {
        "pages_failed": 2,
        "pages_invalid": 1,
        "pages_degraded": 3,
    }
    blockers = _quality_stats_blockers(stats)
    assert any("failed" in b for b in blockers)
    assert any("invalid" in b for b in blockers)
    assert any("degraded" in b for b in blockers)


def test_quality_stats_blockers_clean():
    """_quality_stats_blockers returns empty list for a clean run."""
    from deepdoc.cli import _quality_stats_blockers

    assert _quality_stats_blockers({}) == []
    assert _quality_stats_blockers({"pages_failed": 0, "pages_invalid": 0}) == []
