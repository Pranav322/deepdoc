from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from deepdoc.generator import BucketGenerationEngine, GenerationResult
from deepdoc.manifest import Manifest
from deepdoc.persistence_v2 import load_generation_ledger, save_generation_ledger
from deepdoc.planner import DocBucket, DocPlan, RepoScan


def _bucket(slug: str, *, introduction: bool = False) -> DocBucket:
    return DocBucket(
        bucket_type="feature",
        title=slug.title(),
        slug=slug,
        section="Guide",
        description=slug,
        owned_files=[f"src/{slug}.py"],
        generation_hints={"is_introduction_page": introduction},
    )


def _scan(buckets: list[DocBucket]) -> RepoScan:
    hashes = {bucket.owned_files[0]: f"hash-{idx}" for idx, bucket in enumerate(buckets)}
    return RepoScan(
        file_tree={},
        file_summaries={path: "summary" for path in hashes},
        api_endpoints=[],
        languages={"python": len(hashes)},
        has_openapi=False,
        openapi_paths=[],
        total_files=len(hashes),
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
        file_content_hashes=hashes,
    )


def test_manifest_reads_legacy_doc_path_and_migrates_to_all_paths(tmp_path: Path) -> None:
    output_dir = tmp_path / "docs"
    output_dir.mkdir()
    (output_dir / ".deepdoc_manifest.json").write_text(
        json.dumps({"src/auth.py": {"hash": "old", "doc_path": "auth.md"}}),
        encoding="utf-8",
    )
    manifest = Manifest(output_dir)

    assert manifest.get_doc_paths("src/auth.py") == ["auth.md"]
    manifest.update("src/auth.py", "new", "security.md")
    manifest.save()

    stored = json.loads((output_dir / ".deepdoc_manifest.json").read_text())
    assert stored["src/auth.py"] == {
        "hash": "new",
        "doc_paths": ["auth.md", "security.md"],
    }
    assert not list(output_dir.glob("*.tmp"))


def test_manifest_doc_paths_are_deterministic(tmp_path: Path) -> None:
    manifest = Manifest(tmp_path / "docs")
    manifest.update("src/auth.py", "hash", "security.md")
    manifest.update("src/auth.py", "hash", "overview.md")
    manifest.update("src/auth.py", "hash", "security.md")

    assert manifest.get_doc_paths("src/auth.py") == ["overview.md", "security.md"]
    assert manifest.get_doc_path("src/auth.py") == "overview.md"


def test_ledger_uses_cached_hash_when_source_is_absent(tmp_path: Path) -> None:
    bucket = _bucket("auth")
    result = GenerationResult(bucket=bucket, content="# Auth\n")

    save_generation_ledger(
        [result],
        tmp_path,
        tmp_path / "docs",
        file_content_hashes={"src/auth.py": "cached-hash"},
    )

    ledger = load_generation_ledger(tmp_path)
    assert ledger["auth"]["file_hashes"] == {"src/auth.py": "cached-hash"}


def test_generation_checkpoints_manifest_every_ten_pages_and_at_end(
    tmp_path: Path,
) -> None:
    buckets = [_bucket("start-here", introduction=True)] + [
        _bucket(f"page-{idx}") for idx in range(20)
    ]
    plan = DocPlan(
        buckets=buckets,
        nav_structure={"Guide": [bucket.slug for bucket in buckets]},
        skipped_files=[],
    )
    engine = BucketGenerationEngine(
        repo_root=tmp_path,
        cfg={
            "batch_size": 50,
            "max_parallel_workers": 6,
            "manifest_checkpoint_pages": 10,
            "manifest_checkpoint_seconds": 999,
        },
        llm=MagicMock(),
        scan=_scan(buckets),
        plan=plan,
        output_dir=tmp_path / "docs",
    )
    engine._generate_one = lambda bucket, _: GenerationResult(
        bucket=bucket,
        content=f"# {bucket.title}\n",
    )

    with patch.object(Manifest, "save", autospec=True) as save:
        results = engine.generate_all(force=True)

    assert len(results) == 21
    assert save.call_count == 3


def test_source_hash_prefers_scan_cache_without_disk(tmp_path: Path) -> None:
    bucket = _bucket("auth")
    plan = DocPlan(
        buckets=[_bucket("start-here", introduction=True), bucket],
        nav_structure={"Guide": ["start-here", "auth"]},
        skipped_files=[],
    )
    scan = _scan(plan.buckets)
    engine = BucketGenerationEngine(
        repo_root=tmp_path,
        cfg={},
        llm=MagicMock(),
        scan=scan,
        plan=plan,
        output_dir=tmp_path / "docs",
    )

    assert engine._source_hash("src/auth.py") == scan.file_content_hashes["src/auth.py"]
