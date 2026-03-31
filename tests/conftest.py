"""Shared fixtures for deepdoc update-hardening tests.

All fixtures use real git repos (not mocked git) for accurate diff testing.
LLM calls are never made — tests mock at the boundary where needed.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from deepdoc.persistence_v2 import (
    _state_dir,
    save_sync_state,
    save_plan,
    LEDGER_FILE,
)
from deepdoc.planner_v2 import DocBucket, DocPlan


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _run_git(cwd: Path, *args: str) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _sha256_short(content: str) -> str:
    """Match the 16-char truncated SHA256 used by the ledger."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def make_bucket(
    title: str,
    slug: str,
    owned_files: list[str],
    bucket_type: str = "system",
    section: str = "core",
    generation_hints: dict | None = None,
    artifact_refs: list[str] | None = None,
) -> DocBucket:
    """Create a DocBucket with sensible defaults for testing."""
    return DocBucket(
        bucket_type=bucket_type,
        title=title,
        slug=slug,
        section=section,
        description=f"Test bucket: {title}",
        owned_files=owned_files,
        artifact_refs=artifact_refs or [],
        generation_hints=generation_hints or {},
    )


def make_plan(buckets: list[DocBucket]) -> DocPlan:
    """Create a DocPlan with sensible defaults for testing."""
    return DocPlan(
        buckets=buckets,
        nav_structure={},
        skipped_files=[],
    )


def write_ledger(repo_root: Path, entries: dict[str, dict]) -> None:
    """Write a ledger.json directly for test setup."""
    state = _state_dir(repo_root)
    (state / LEDGER_FILE).write_text(json.dumps(entries, indent=2), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Fake result objects (for ledger save tests)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FakeBucket:
    slug: str
    title: str
    bucket_type: str = "system"
    section: str = "core"
    owned_files: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    generation_hints: dict = field(default_factory=dict)


@dataclass
class FakeResult:
    bucket: Any = None
    content: str | None = None
    error: str | None = None
    elapsed_seconds: float = 1.0
    validation: Any = None
    retries: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_repo(tmp_path: Path) -> Path:
    """Create a real git repo with Python files and an initial commit.

    We use 6 source files so that editing a single file (1/6 ≈ 17%) stays
    below the 20% REPLAN_THRESHOLD, allowing incremental tests to work.

    Repo layout after fixture:
        auth.py, payment.py, utils.py, models.py, routes.py, config.py
        .gitignore — ignores .deepdoc/ and docs/

    Returns the repo root path.
    """
    root = tmp_path / "repo"
    root.mkdir()

    _run_git(root, "init")
    _run_git(root, "config", "user.email", "test@deepdoc.dev")
    _run_git(root, "config", "user.name", "DeepDoc Test")

    (root / ".gitignore").write_text(".deepdoc/\ndocs/\n")
    (root / "auth.py").write_text("# auth module\n")
    (root / "payment.py").write_text("# payment module\n")
    (root / "utils.py").write_text("# utils module\n")
    (root / "models.py").write_text("# models module\n")
    (root / "routes.py").write_text("# routes module\n")
    (root / "config.py").write_text("# config module\n")

    _run_git(root, "add", ".")
    _run_git(root, "commit", "-m", "initial commit")

    return root


@pytest.fixture()
def tmp_repo_with_plan(tmp_repo: Path) -> tuple[Path, DocPlan]:
    """tmp_repo + a saved plan with 3 buckets and a matching ledger.

    Buckets (6 files total, so 1 edit = 17% < 20% REPLAN_THRESHOLD):
        auth    — owns auth.py
        payment — owns payment.py, utils.py
        core    — owns models.py, routes.py, config.py

    Returns (repo_root, plan).
    """
    root = tmp_repo

    b_auth = make_bucket("Auth System", "auth", ["auth.py"])
    b_payment = make_bucket("Payment System", "payment", ["payment.py", "utils.py"])
    b_core = make_bucket("Core System", "core", ["models.py", "routes.py", "config.py"])
    plan = make_plan([b_auth, b_payment, b_core])

    save_plan(plan, root)

    # Create matching ledger with current file hashes
    auth_hash = _sha256_short((root / "auth.py").read_text())
    payment_hash = _sha256_short((root / "payment.py").read_text())
    utils_hash = _sha256_short((root / "utils.py").read_text())
    models_hash = _sha256_short((root / "models.py").read_text())
    routes_hash = _sha256_short((root / "routes.py").read_text())
    config_hash = _sha256_short((root / "config.py").read_text())

    # Create output docs
    docs_dir = root / "docs"
    docs_dir.mkdir(exist_ok=True)
    (docs_dir / "auth.mdx").write_text("# Auth System\n")
    (docs_dir / "payment.mdx").write_text("# Payment System\n")
    (docs_dir / "core.mdx").write_text("# Core System\n")

    ledger = {
        "auth": {
            "slug": "auth",
            "title": "Auth System",
            "bucket_type": "system",
            "section": "core",
            "doc_path": "auth.mdx",
            "success": True,
            "error": None,
            "generated_at": "2026-01-01T00:00:00+00:00",
            "elapsed_seconds": 2.0,
            "retries": 0,
            "word_count": 100,
            "mermaid_block_count": 0,
            "file_hashes": {"auth.py": auth_hash},
        },
        "payment": {
            "slug": "payment",
            "title": "Payment System",
            "bucket_type": "system",
            "section": "core",
            "doc_path": "payment.mdx",
            "success": True,
            "error": None,
            "generated_at": "2026-01-01T00:00:00+00:00",
            "elapsed_seconds": 3.0,
            "retries": 0,
            "word_count": 200,
            "mermaid_block_count": 1,
            "file_hashes": {
                "payment.py": payment_hash,
                "utils.py": utils_hash,
            },
        },
        "core": {
            "slug": "core",
            "title": "Core System",
            "bucket_type": "system",
            "section": "core",
            "doc_path": "core.mdx",
            "success": True,
            "error": None,
            "generated_at": "2026-01-01T00:00:00+00:00",
            "elapsed_seconds": 2.5,
            "retries": 0,
            "word_count": 150,
            "mermaid_block_count": 0,
            "file_hashes": {
                "models.py": models_hash,
                "routes.py": routes_hash,
                "config.py": config_hash,
            },
        },
    }
    write_ledger(root, ledger)

    # Save sync state baseline at initial commit
    import git as _git
    repo = _git.Repo(root)
    save_sync_state(
        root,
        commit_sha=repo.head.commit.hexsha,
        status="success",
        advance_baseline=True,
    )

    return root, plan
