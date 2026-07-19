from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from deepdoc.parser.registry import parse_file
from deepdoc.planner import scan_repo
from deepdoc.telemetry import RunTelemetry


def _scan_projection(scan):
    return {
        "file_tree": scan.file_tree,
        "file_summaries": scan.file_summaries,
        "api_endpoints": scan.api_endpoints,
        "languages": scan.languages,
        "entry_points": scan.entry_points,
        "config_files": scan.config_files,
        "file_line_counts": scan.file_line_counts,
        "file_contents": scan.file_contents,
        "file_content_hashes": scan.file_content_hashes,
        "source_kind_by_file": scan.source_kind_by_file,
        "file_frameworks": scan.file_frameworks,
        "parsed": {
            path: (
                [(symbol.name, symbol.kind) for symbol in parsed.symbols],
                list(parsed.imports),
            )
            for path, parsed in scan.parsed_files.items()
        },
    }


def test_parallel_scan_matches_serial_scan(tmp_path: Path) -> None:
    for index in range(12):
        (tmp_path / f"module_{index:02d}.py").write_text(
            f"def function_{index}():\n    return {index}\n", encoding="utf-8"
        )
    (tmp_path / "app.py").write_text(
        "import falcon\n\nclass Health:\n    def on_get(self, req, resp):\n        pass\n",
        encoding="utf-8",
    )

    serial = scan_repo(tmp_path, {"scan": {"max_workers": 1}})
    parallel = scan_repo(tmp_path, {"scan": {"max_workers": 4}})

    assert _scan_projection(parallel) == _scan_projection(serial)
    assert list(parallel.file_contents) == sorted(parallel.file_contents)


def test_parallel_scan_records_worker_and_wall_metrics(tmp_path: Path) -> None:
    for index in range(10):
        (tmp_path / f"worker_{index}.py").write_text(
            f"VALUE_{index} = {index}\n", encoding="utf-8"
        )
    telemetry = RunTelemetry(tmp_path, "generate")

    scan = scan_repo(
        tmp_path,
        {"scan": {"max_workers": 4}},
        telemetry=telemetry,
    )
    payload = telemetry.finish("success")

    assert scan.scan_timings["parallel_file_stage"] >= 0
    assert payload["counters"]["scan.worker_limit"] == 4
    assert payload["counters"]["scan.source_files_read"] == 10
    assert payload["counters"]["scan.parsing_work_seconds"] >= 0
    assert "scan.parallel_file_stage" in payload["spans"]


def test_parser_failure_reuses_supplied_content_without_disk_reread() -> None:
    supplied = "def valid_source():\n    return True\n"

    def fail_parser(path, content, language):
        raise RuntimeError("parser failed")

    with (
        patch.dict(
            "deepdoc.parser.registry._REGISTRY",
            {".py": ("python", fail_parser)},
        ),
        patch.object(Path, "read_text", side_effect=AssertionError("disk reread")),
    ):
        parsed = parse_file(Path("module.py"), content=supplied)

    assert parsed is not None
    assert parsed.raw_content == supplied
