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


def test_manifest_reads_legacy_doc_path_and_resets_ownership_on_new_hash(
    tmp_path: Path,
) -> None:
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
        "doc_paths": ["security.md"],
    }
    assert not list(output_dir.glob("*.tmp"))


def test_manifest_doc_paths_are_deterministic(tmp_path: Path) -> None:
    manifest = Manifest(tmp_path / "docs")
    manifest.update("src/auth.py", "hash", "security.md")
    manifest.update("src/auth.py", "hash", "overview.md")
    manifest.update("src/auth.py", "hash", "security.md")

    assert manifest.get_doc_paths("src/auth.py") == ["overview.md", "security.md"]
    assert manifest.get_doc_path("src/auth.py") == "overview.md"


def test_same_hash_migrates_legacy_path_and_accumulates_ownership(tmp_path: Path) -> None:
    output_dir = tmp_path / "docs"
    output_dir.mkdir()
    (output_dir / ".deepdoc_manifest.json").write_text(
        json.dumps({"src/auth.py": {"hash": "same", "doc_path": "auth.md"}}),
        encoding="utf-8",
    )
    manifest = Manifest(output_dir)

    manifest.update("src/auth.py", "same", "security.md")

    assert manifest.get_doc_paths("src/auth.py") == ["auth.md", "security.md"]


def test_interrupted_shared_source_keeps_unfinished_page_stale(tmp_path: Path) -> None:
    output_dir = tmp_path / "docs"
    output_dir.mkdir()
    shared = "src/shared.py"
    (output_dir / "overview.md").write_text("old overview", encoding="utf-8")
    (output_dir / "auth.md").write_text("old auth", encoding="utf-8")
    manifest = Manifest(output_dir)
    manifest.update(shared, "H0", "overview.md")
    manifest.update(shared, "H0", "auth.md")

    manifest.update(shared, "H1", "overview.md")

    assert manifest.is_doc_stale(shared, "H1", "overview.md") is False
    assert manifest.is_doc_stale(shared, "H1", "auth.md") is True
    manifest.update(shared, "H1", "auth.md")
    assert manifest.is_doc_stale(shared, "H1", "auth.md") is False


def test_bucket_is_stale_when_output_file_is_missing(tmp_path: Path) -> None:
    intro = _bucket("start-here", introduction=True)
    bucket = _bucket("auth")
    plan = DocPlan(
        buckets=[intro, bucket],
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
    manifest = Manifest(engine.output_dir)
    manifest.update("src/auth.py", scan.file_content_hashes["src/auth.py"], "auth.md")

    assert engine._bucket_is_stale(bucket, manifest) is True


def test_bucket_staleness_is_page_aware_for_shared_source(tmp_path: Path) -> None:
    intro = _bucket("start-here", introduction=True)
    auth = _bucket("auth")
    security = _bucket("security")
    auth.owned_files = ["src/shared.py"]
    security.owned_files = ["src/shared.py"]
    plan = DocPlan(
        buckets=[intro, auth, security],
        nav_structure={"Guide": ["start-here", "auth", "security"]},
        skipped_files=[],
    )
    scan = _scan(plan.buckets)
    scan.file_content_hashes["src/shared.py"] = "H1"
    engine = BucketGenerationEngine(
        repo_root=tmp_path,
        cfg={},
        llm=MagicMock(),
        scan=scan,
        plan=plan,
        output_dir=tmp_path / "docs",
    )
    engine.output_dir.mkdir()
    (engine.output_dir / "auth.md").write_text("new auth", encoding="utf-8")
    (engine.output_dir / "security.md").write_text("old security", encoding="utf-8")
    manifest = Manifest(engine.output_dir)
    manifest.update("src/shared.py", "H1", "auth.md")

    assert engine._bucket_is_stale(auth, manifest) is False
    assert engine._bucket_is_stale(security, manifest) is True


def test_restart_generates_only_unfinished_shared_source_page(tmp_path: Path) -> None:
    intro = _bucket("start-here", introduction=True)
    auth = _bucket("auth")
    security = _bucket("security")
    auth.owned_files = ["src/shared.py"]
    security.owned_files = ["src/shared.py"]
    plan = DocPlan(
        buckets=[intro, auth, security],
        nav_structure={"Guide": ["start-here", "auth", "security"]},
        skipped_files=[],
    )
    scan = _scan(plan.buckets)
    scan.file_content_hashes["src/shared.py"] = "H1"
    engine = BucketGenerationEngine(
        repo_root=tmp_path,
        cfg={"rate_limit_pause": 0},
        llm=MagicMock(),
        scan=scan,
        plan=plan,
        output_dir=tmp_path / "docs",
    )
    engine.output_dir.mkdir()
    for path in ("index.md", "auth.md", "security.md"):
        (engine.output_dir / path).write_text("existing", encoding="utf-8")
    manifest = Manifest(engine.output_dir)
    manifest.update(
        "src/start-here.py",
        scan.file_content_hashes["src/start-here.py"],
        "index.md",
    )
    manifest.update("src/shared.py", "H1", "auth.md")
    manifest.save()
    generated: list[str] = []

    def generate(bucket, _):
        generated.append(bucket.slug)
        return GenerationResult(bucket=bucket, content=f"# {bucket.title}\n")

    engine._generate_one = generate
    engine.generate_all(force=False)

    assert generated == ["security"]


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
