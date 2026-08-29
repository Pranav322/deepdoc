#!/usr/bin/env python3
"""Benchmark runner for DeepDoc.

Measures factual accuracy against gold expectations for adversarial fixtures,
supported-language repos, and polyglot monorepos.  Produces JSON results and
a human-readable report.

Usage:
  python benchmarks/runner.py                          # all categories
  python benchmarks/runner.py --category A              # adversarial only
  python benchmarks/runner.py --compare                 # DeepWiki comparison
"""

from __future__ import annotations

import json
import sys
import time
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class CaseResult:
    fixture_name: str
    category: str
    passed: bool = True
    metrics: dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    scan_time_s: float = 0.0


@dataclass
class BenchmarkSummary:
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    results: list[CaseResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class BenchmarkRunner:
    def __init__(self):
        self.root = Path(__file__).parent.parent
        self.summary = BenchmarkSummary()
        self._load_expectations()

    def _load_expectations(self) -> None:
        path = Path(__file__).parent / "corpus" / "expectations.json"
        self.expectations = json.loads(path.read_text())

    def run_category_a(self) -> None:
        d = self.root / "tests" / "fixtures" / "adversarial"
        for name in sorted(d.iterdir()):
            if name.is_dir() and name.name in self.expectations:
                r = self._run_case(d / name.name, name.name, "A")
                self._record(r)

    def run_category_b(self) -> None:
        d = self.root / "tests" / "fixtures" / "frameworks"
        for name in sorted(d.iterdir()):
            if name.is_dir() and name.name in self.expectations:
                r = self._run_case(d / name.name, name.name, "B")
                self._record(r)

    def run_category_c(self) -> None:
        d = self.root / "benchmarks" / "corpus" / "mini-monorepo"
        if d.is_dir():
            r = self._run_case(d, "mini-monorepo", "C")
            self._record(r)

    def _run_case(self, repo_path: Path, name: str, category: str) -> CaseResult:
        result = CaseResult(fixture_name=name, category=category)
        gold = self.expectations.get(name, {})

        try:
            from deepdoc.planner import scan_repo
            from deepdoc.repo_model import build_repo_model_from_scan

            start = time.perf_counter()
            scan = scan_repo(repo_path, {"scan": {"persistent_index": False}})
            result.scan_time_s = time.perf_counter() - start
            model = build_repo_model_from_scan(scan, str(repo_path))

            # Parse rate
            mp = gold.get("min_parse_rate")
            if mp is not None:
                a = model.coverage.overall_parse_rate
                result.metrics["overall_parse_rate"] = a
                if a < mp:
                    result.passed = False
                    result.failures.append(f"Parse rate {a:.2f} < {mp}")

            # File count
            mf = gold.get("min_files")
            if mf is not None:
                a = len(model.files)
                result.metrics["files"] = a
                if a < mf:
                    result.passed = False
                    result.failures.append(f"Files {a} < {mf}")

            # Parsed files
            mpf = gold.get("min_parsed_files")
            if mpf is not None:
                a = model.coverage.total_files_parsed
                result.metrics["parsed_files"] = a
                if a < mpf:
                    result.passed = False
                    result.failures.append(f"Parsed files {a} < {mpf}")

            # Source kind
            for fp, ek in gold.get("source_kind", {}).items():
                e = model.get_file(fp)
                if e is None:
                    result.passed = False
                    result.failures.append(f"Missing: {fp}")
                    continue
                a = e.source_kind.value
                result.metrics[f"kind:{fp}"] = a
                if a != ek:
                    result.passed = False
                    result.failures.append(f"Kind {fp}: {a} != {ek}")

            # Parse status
            for fp, eps in gold.get("parse_status", {}).items():
                e = model.get_file(fp)
                if e is None:
                    result.passed = False
                    result.failures.append(f"Missing status check: {fp}")
                    continue
                a = e.language.parse_status.value
                result.metrics[f"status:{fp}"] = a
                if a != eps:
                    result.passed = False
                    result.failures.append(f"Status {fp}: {a} != {eps}")

            # Symbols
            ms = gold.get("min_symbols")
            if ms is not None:
                a = sum(len(pf.symbols) for pf in scan.parsed_files.values())
                result.metrics["symbols"] = a
                if a < ms:
                    result.passed = False
                    result.failures.append(f"Symbols {a} < {ms}")

            # Imports
            mi = gold.get("min_imports")
            if mi is not None:
                a = sum(len(pf.imports) for pf in scan.parsed_files.values())
                result.metrics["imports"] = a
                if a < mi:
                    result.passed = False
                    result.failures.append(f"Imports {a} < {mi}")

            # Route records
            mr = gold.get("min_route_records")
            if mr is not None:
                a = len(scan.published_api_endpoints)
                result.metrics["route_records"] = a
                if a < mr:
                    result.passed = False
                    result.failures.append(f"Routes {a} < {mr}")
            xr = gold.get("max_route_records")
            if xr is not None:
                a = len(scan.published_api_endpoints)
                result.metrics["route_records"] = a
                if a > xr:
                    result.passed = False
                    result.failures.append(f"Routes {a} > max {xr}")

            # Call edges
            me = gold.get("min_call_edges")
            if me is not None and scan.call_graph is not None:
                a = sum(len(ef) for ef in scan.call_graph._callees.values())
                result.metrics["call_edges"] = a
                if a < me:
                    result.passed = False
                    result.failures.append(f"Edges {a} < {me}")

            # Frameworks
            efw = gold.get("frameworks")
            if efw is not None:
                a = sorted(scan.frameworks_detected)
                result.metrics["frameworks"] = a
                for fw in efw:
                    if fw not in a:
                        result.warnings.append(f"Framework {fw} not detected (found: {a})")

            # Unsupported languages
            eu = gold.get("unsupported_languages")
            if eu is not None:
                a = model.coverage.unsupported_languages
                result.metrics["unsupported_languages"] = a
                for lang in eu:
                    if lang not in a:
                        result.passed = False
                        result.failures.append(f"Unsupported {lang} not reported")

            shutil.rmtree(repo_path / ".deepdoc", ignore_errors=True)

        except Exception as exc:
            result.passed = False
            result.failures.append(f"Exception: {exc}")

        return result

    def _record(self, result: CaseResult) -> None:
        self.summary.total_cases += 1
        if result.passed:
            self.summary.passed += 1
        else:
            self.summary.failed += 1
        self.summary.results.append(result)

    def write_results(self) -> None:
        out = Path(__file__).parent / "results"
        out.mkdir(exist_ok=True)
        sd = {
            "total": self.summary.total_cases,
            "passed": self.summary.passed,
            "failed": self.summary.failed,
            "pass_rate": (
                self.summary.passed / self.summary.total_cases
                if self.summary.total_cases else 0.0
            ),
            "results": [
                {
                    "fixture": r.fixture_name,
                    "category": r.category,
                    "passed": r.passed,
                    "metrics": r.metrics,
                    "failures": r.failures,
                    "warnings": r.warnings,
                    "scan_time_s": r.scan_time_s,
                }
                for r in self.summary.results
            ],
        }
        (out / "summary.json").write_text(json.dumps(sd, indent=2))

        lines = [
            "# DeepDoc Benchmark Report",
            "",
            f"**Date**: {__import__('datetime').datetime.now().isoformat()}",
            f"**Total**: {self.summary.total_cases}",
            f"**Passed**: {self.summary.passed}",
            f"**Failed**: {self.summary.failed}",
            f"**Pass rate**: {sd['pass_rate']:.0%}",
            "",
            "---",
            "",
        ]
        for r in self.summary.results:
            s = "PASS" if r.passed else "FAIL"
            lines.append(f"## {s} {r.category}/{r.fixture_name} ({r.scan_time_s:.1f}s)")
            if r.failures:
                lines.append("**Failures:**")
                for f in r.failures:
                    lines.append(f"- {f}")
            if r.warnings:
                lines.append("**Warnings:**")
                for w in r.warnings:
                    lines.append(f"- {w}")
            if r.metrics:
                lines.append("**Metrics:**")
                for k, v in sorted(r.metrics.items()):
                    lines.append(f"- {k}: {v}")
            lines.append("")
        (out / "report.md").write_text("\n".join(lines))

    def print_summary(self) -> None:
        print(f"\n{'='*60}")
        print(f" DeepDoc Benchmark Results")
        print(f" {'='*60}")
        print(f" Total: {self.summary.total_cases}")
        print(f" Passed: {self.summary.passed}")
        print(f" Failed: {self.summary.failed}")
        pr = self.summary.passed / self.summary.total_cases * 100 if self.summary.total_cases else 0
        print(f" Pass rate: {pr:.0f}%")
        print(f" {'='*60}")
        for r in self.summary.results:
            s = "PASS" if r.passed else "FAIL"
            print(f" [{s}] {r.category}/{r.fixture_name} ({r.scan_time_s:.1f}s)")
            for f in r.failures:
                print(f"   FAIL: {f}")
        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="DeepDoc benchmark runner")
    p.add_argument("--category", "-c", default="ABC", help="Categories to run")
    p.add_argument("--compare", action="store_true", help="DeepWiki comparison")
    args = p.parse_args()

    runner = BenchmarkRunner()
    if "A" in args.category:
        print("Category A: Adversarial fixtures...")
        runner.run_category_a()
    if "B" in args.category:
        print("Category B: Supported-language fixtures...")
        runner.run_category_b()
    if "C" in args.category:
        print("Category C: Polyglot monorepo...")
        runner.run_category_c()

    runner.print_summary()
    runner.write_results()

    if runner.summary.failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()