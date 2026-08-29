from __future__ import annotations

from deepdoc import pipeline_v2
from deepdoc.planner import DocBucket, DocPlan
from deepdoc.v2_models import RepoScan


def _scan(**overrides) -> RepoScan:
    defaults = dict(
        file_tree={},
        file_summaries={},
        api_endpoints=[],
        languages={"python": 2},
        has_openapi=False,
        openapi_paths=[],
        total_files=3,
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
    )
    defaults.update(overrides)
    return RepoScan(**defaults)


def test_print_scan_warns_on_known_unsupported_languages(monkeypatch, capsys) -> None:
    scan = _scan(unsupported_extensions={".rb": 2, ".md": 5})
    pipeline = object.__new__(pipeline_v2.PipelineV2)
    pipeline._print_scan(scan)

    out = capsys.readouterr().out
    assert "Ruby" in out
    assert ".rb" in out
    # .md is not a known-unsupported-language extension — must not be flagged.
    assert ".md" not in out.split("Unsupported")[-1] if "Unsupported" in out else True


def test_print_scan_silent_when_no_unsupported_languages(capsys) -> None:
    scan = _scan(unsupported_extensions={".md": 5, ".json": 2})
    pipeline = object.__new__(pipeline_v2.PipelineV2)
    pipeline._print_scan(scan)

    out = capsys.readouterr().out
    assert "Unsupported languages" not in out


def test_print_coverage_reports_documented_vs_orphaned(capsys) -> None:
    scan = _scan(
        file_contents={"a.py": "x", "b.py": "y", "c.py": "z", "d.py": "w"},
    )
    bucket = DocBucket(
        bucket_type="feature",
        title="Feature",
        slug="feature",
        section="Guide",
        description="d",
        owned_files=["a.py", "b.py"],
    )
    plan = DocPlan(
        buckets=[bucket],
        nav_structure={},
        skipped_files=["c.py"],
        orphaned_files=["d.py"],
    )
    pipeline = object.__new__(pipeline_v2.PipelineV2)
    pipeline._print_coverage(scan, plan)

    out = capsys.readouterr().out
    assert "50.0%" in out
    assert "Documented" in out
    assert "Orphaned" in out
