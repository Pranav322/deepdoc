from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from deepdoc.planner import run_phase2_scans, scan_repo
from deepdoc.telemetry import RunTelemetry


BASE_SCAN_PHASES = {
    "service_boundaries",
    "file_walk",
    "documentation",
    "source_reads",
    "framework_detection",
    "parsing",
    "endpoint_detection",
    "route_resolution",
}

PHASE_TWO_SCAN_PHASES = {
    "giant_file_clustering",
    "endpoint_bundles",
    "integrations",
    "artifacts",
    "runtime",
    "config_impacts",
    "call_graph",
    "topology",
    "debug_signals",
}


def test_scan_repo_records_subphases_and_file_io(tmp_path: Path) -> None:
    source = "def create_app():\n    return None\n"
    (tmp_path / "app.py").write_text(source, encoding="utf-8")
    (tmp_path / "README.md").write_text("# Example\n", encoding="utf-8")
    telemetry = RunTelemetry(tmp_path, "generate")

    scan = scan_repo(tmp_path, {}, telemetry=telemetry)
    payload = telemetry.finish("success")

    assert BASE_SCAN_PHASES <= set(scan.scan_timings)
    assert all(scan.scan_timings[name] >= 0 for name in BASE_SCAN_PHASES)
    assert payload["counters"]["scan.files_discovered"] == 2
    assert payload["counters"]["scan.source_files_read"] == 1
    assert payload["counters"]["scan.source_bytes_read"] == len(source.encode("utf-8"))
    assert payload["counters"]["scan.source_files_parsed"] == 1
    assert {f"scan.{name}" for name in BASE_SCAN_PHASES} <= set(payload["spans"])


def test_empty_scan_keeps_complete_metric_shape(tmp_path: Path) -> None:
    telemetry = RunTelemetry(tmp_path, "generate")

    scan = scan_repo(tmp_path, {}, telemetry=telemetry)
    payload = telemetry.finish("success")

    assert BASE_SCAN_PHASES <= set(scan.scan_timings)
    assert payload["counters"]["scan.files_discovered"] == 0
    assert {f"scan.{name}" for name in BASE_SCAN_PHASES} <= set(payload["spans"])


def test_phase_two_scans_record_each_family(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    telemetry = RunTelemetry(tmp_path, "generate")
    scan = scan_repo(tmp_path, {}, telemetry=telemetry)
    llm = SimpleNamespace(telemetry=telemetry)

    run_phase2_scans(
        scan,
        {
            "integration_detection": "off",
            "include_endpoint_pages": False,
            "giant_file_lines": 2000,
        },
        llm,
        repo_root=tmp_path,
    )
    payload = telemetry.finish("success")

    assert PHASE_TWO_SCAN_PHASES <= set(scan.scan_timings)
    assert {f"scan.{name}" for name in PHASE_TWO_SCAN_PHASES} <= set(payload["spans"])
