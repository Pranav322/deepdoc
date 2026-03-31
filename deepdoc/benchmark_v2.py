"""Benchmark harness for DeepDoc planner quality."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .llm import LLMClient
from .planner_v2 import DocPlan, plan_docs, scan_repo


@dataclass
class BenchmarkResult:
    name: str
    family: str
    repo_path: str
    holdout: bool
    score: float
    details: dict[str, float]
    notes: list[str]


def load_catalog(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("cases", [])


def run_case(case: dict[str, Any], cfg: dict[str, Any]) -> BenchmarkResult:
    repo_path = Path(case["repo_path"]).expanduser().resolve()
    llm = LLMClient(cfg)
    scan = scan_repo(repo_path, cfg)
    plan = plan_docs(scan, cfg, llm)
    score, details, notes = score_plan(plan, case.get("gold", {}))
    return BenchmarkResult(
        name=case["name"],
        family=case.get("family", "other"),
        repo_path=str(repo_path),
        holdout=bool(case.get("holdout", False)),
        score=score,
        details=details,
        notes=notes,
    )


def score_plan(plan: DocPlan, gold: dict[str, Any]) -> tuple[float, dict[str, float], list[str]]:
    details: dict[str, float] = {}
    notes: list[str] = []

    primary_type = plan.classification.get("repo_profile", {}).get("primary_type", "other")
    expected_type = gold.get("expected_primary_type")
    details["profile_match"] = 1.0 if not expected_type or primary_type == expected_type else 0.0
    if expected_type and primary_type != expected_type:
        notes.append(f"profile mismatch: expected {expected_type}, got {primary_type}")

    sections = set(plan.nav_structure.keys())
    required_sections = gold.get("required_sections", [])
    if required_sections:
        matched = sum(1 for section in required_sections if section in sections)
        details["section_coverage"] = matched / len(required_sections)
        missing = [section for section in required_sections if section not in sections]
        if missing:
            notes.append(f"missing sections: {', '.join(missing)}")
    else:
        details["section_coverage"] = 1.0

    titles = [bucket.title for bucket in plan.buckets]
    required_titles = gold.get("required_titles", [])
    if required_titles:
        matched_titles = 0
        for title_group in required_titles:
            if isinstance(title_group, list):
                if any(any(candidate.lower() in title.lower() for title in titles) for candidate in title_group):
                    matched_titles += 1
            else:
                if any(title_group.lower() in title.lower() for title in titles):
                    matched_titles += 1
        details["title_coverage"] = matched_titles / len(required_titles)
    else:
        details["title_coverage"] = 1.0

    forbidden_titles = gold.get("forbidden_titles", [])
    if forbidden_titles:
        violations = [
            title
            for title in titles
            if any(forbidden.lower() in title.lower() for forbidden in forbidden_titles)
        ]
        details["noise_suppression"] = max(0.0, 1.0 - (len(violations) / max(len(titles), 1)))
        if violations:
            notes.append(f"forbidden titles present: {', '.join(violations[:5])}")
    else:
        details["noise_suppression"] = 1.0

    orphaned = len(plan.orphaned_files)
    max_orphaned = gold.get("max_orphaned")
    if max_orphaned is not None:
        details["orphan_score"] = 1.0 if orphaned <= max_orphaned else max(0.0, 1 - ((orphaned - max_orphaned) / max(1, max_orphaned + 1)))
        if orphaned > max_orphaned:
            notes.append(f"too many orphaned files: {orphaned} > {max_orphaned}")
    else:
        details["orphan_score"] = 1.0

    overview_limit = gold.get("max_overview_files")
    overview_buckets = [bucket for bucket in plan.buckets if (bucket.generation_hints or {}).get("is_introduction_page")]
    if overview_limit is not None and overview_buckets:
        overview_files = max(len(bucket.owned_files) for bucket in overview_buckets)
        details["overview_focus"] = 1.0 if overview_files <= overview_limit else max(0.0, 1 - ((overview_files - overview_limit) / max(1, overview_limit)))
        if overview_files > overview_limit:
            notes.append(f"overview bucket too large: {overview_files} files")
    else:
        details["overview_focus"] = 1.0

    weighted = {
        "profile_match": 0.15,
        "section_coverage": 0.2,
        "title_coverage": 0.25,
        "noise_suppression": 0.2,
        "orphan_score": 0.1,
        "overview_focus": 0.1,
    }
    score = sum(details[key] * weight for key, weight in weighted.items()) * 100
    return score, details, notes
