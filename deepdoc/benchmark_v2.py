"""Benchmark and scorecard harness for DeepDoc quality tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from .llm import LLMClient
from .planner import plan_docs, scan_repo
from .v2_models import DocPlan


@dataclass
class BenchmarkResult:
    name: str
    family: str
    repo_path: str
    holdout: bool
    score: float
    details: dict[str, float]
    notes: list[str]


DEFAULT_SCORECARD_THRESHOLDS: dict[str, float] = {
    "docs_completeness_min": 95.0,
    "chatbot_completeness_min": 95.0,
    "grounded_accuracy_min": 95.0,
    "citation_precision_min": 97.0,
    "evidence_recall_min": 95.0,
    "abstain_precision_min": 90.0,
}

CHATBOT_REQUIRED_ARTIFACT_FILES: tuple[str, ...] = (
    "code_chunks.jsonl",
    "code_meta.json",
    "code.faiss",
    "artifact_chunks.jsonl",
    "artifact_meta.json",
    "artifacts.faiss",
    "relationship_chunks.jsonl",
    "relationship_meta.json",
    "relationship.faiss",
    "doc_chunks.jsonl",
    "doc_summary_meta.json",
    "docs.faiss",
    "doc_full_chunks.jsonl",
    "doc_full_meta.json",
    "docs_full.faiss",
    "repo_doc_chunks.jsonl",
    "repo_doc_meta.json",
    "repo_docs.faiss",
)

CHATBOT_CORPUS_FILES: dict[str, str] = {
    "code": "code_chunks.jsonl",
    "artifact": "artifact_chunks.jsonl",
    "relationship": "relationship_chunks.jsonl",
    "doc_summary": "doc_chunks.jsonl",
    "doc_full": "doc_full_chunks.jsonl",
    "repo_doc": "repo_doc_chunks.jsonl",
}


def load_catalog(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("cases", [])


def load_chatbot_eval_rows(path: Path) -> list[dict[str, Any]]:
    """Load chatbot evaluation rows from JSON file.

    Supported shapes:
      - [{...}, {...}]
      - {"cases": [{...}]}
      - {"results": [{...}]}
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, dict)]
    if isinstance(raw, dict):
        for key in ("cases", "results"):
            rows = raw.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    return []


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


def summarize_benchmark_results(results: list[BenchmarkResult]) -> dict[str, Any]:
    """Aggregate planner benchmark results into a docs completeness summary."""
    if not results:
        return {
            "cases_total": 0,
            "holdout_cases": 0,
            "avg_score": 0.0,
            "holdout_avg_score": 0.0,
            "pass_rate_90": 0.0,
            "pass_rate_95": 0.0,
            "detail_avgs": {},
            "notes_total": 0,
            "completeness_score": 0.0,
        }

    holdout_scores = [result.score for result in results if result.holdout]
    metric_keys = sorted(
        {metric for result in results for metric in result.details.keys()}
    )
    detail_avgs = {
        key: round(_mean(result.details.get(key, 0.0) for result in results), 4)
        for key in metric_keys
    }
    avg_score = _mean(result.score for result in results)

    return {
        "cases_total": len(results),
        "holdout_cases": len(holdout_scores),
        "avg_score": round(avg_score, 2),
        "holdout_avg_score": round(_mean(holdout_scores), 2),
        "pass_rate_90": round(
            100.0 * _mean(1.0 if result.score >= 90.0 else 0.0 for result in results),
            2,
        ),
        "pass_rate_95": round(
            100.0 * _mean(1.0 if result.score >= 95.0 else 0.0 for result in results),
            2,
        ),
        "detail_avgs": detail_avgs,
        "notes_total": sum(len(result.notes) for result in results),
        "completeness_score": round(avg_score, 2),
    }


def summarize_chatbot_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate chatbot eval rows into a single completeness summary.

    Each row is expected to include groundedness and retrieval quality fields such as:
      - grounded_correct: bool | 0/1 | percentage
      - citation_precision: [0,1] fraction or [0,100] percentage
      - evidence_recall: [0,1] fraction or [0,100] percentage
      - abstain_expected: bool (optional)
      - abstain_correct: bool | 0/1 | percentage (optional)
    """
    if not results:
        return {
            "cases_total": 0,
            "grounded_accuracy": 0.0,
            "citation_precision": 0.0,
            "evidence_recall": 0.0,
            "abstain_precision": 0.0,
            "abstain_cases": 0,
            "completeness_score": 0.0,
        }

    grounded = [
        _normalized_fraction(result.get("grounded_correct")) for result in results
    ]
    citation = [
        _normalized_fraction(result.get("citation_precision", 0.0))
        for result in results
    ]
    recall = [
        _normalized_fraction(result.get("evidence_recall", 0.0)) for result in results
    ]

    abstain_rows = [
        result
        for result in results
        if bool(result.get("abstain_expected")) or "abstain_correct" in result
    ]
    abstain = [
        _normalized_fraction(result.get("abstain_correct", False))
        for result in abstain_rows
    ]
    abstain_score = _mean(abstain) if abstain else 1.0

    grounded_score = _mean(grounded)
    citation_score = _mean(citation)
    recall_score = _mean(recall)
    completeness = (
        grounded_score * 0.40
        + citation_score * 0.25
        + recall_score * 0.25
        + abstain_score * 0.10
    )

    return {
        "cases_total": len(results),
        "grounded_accuracy": round(grounded_score * 100.0, 2),
        "citation_precision": round(citation_score * 100.0, 2),
        "evidence_recall": round(recall_score * 100.0, 2),
        "abstain_precision": round(abstain_score * 100.0, 2),
        "abstain_cases": len(abstain_rows),
        "completeness_score": round(completeness * 100.0, 2),
    }


def build_quality_scorecard(
    *,
    planner_results: list[BenchmarkResult],
    chatbot_results: list[dict[str, Any]],
    thresholds: dict[str, float] | None = None,
    label: str = "baseline",
) -> dict[str, Any]:
    """Build one combined docs/chatbot scorecard payload."""
    docs_summary = summarize_benchmark_results(planner_results)
    chatbot_summary = summarize_chatbot_results(chatbot_results)

    active_thresholds = {**DEFAULT_SCORECARD_THRESHOLDS, **(thresholds or {})}
    docs_score = docs_summary["completeness_score"]
    chatbot_score = chatbot_summary["completeness_score"]
    overall_score = round((docs_score * 0.5) + (chatbot_score * 0.5), 2)

    gates = {
        "docs_completeness": docs_score >= active_thresholds["docs_completeness_min"],
        "chatbot_completeness": chatbot_score
        >= active_thresholds["chatbot_completeness_min"],
        "grounded_accuracy": chatbot_summary["grounded_accuracy"]
        >= active_thresholds["grounded_accuracy_min"],
        "citation_precision": chatbot_summary["citation_precision"]
        >= active_thresholds["citation_precision_min"],
        "evidence_recall": chatbot_summary["evidence_recall"]
        >= active_thresholds["evidence_recall_min"],
        "abstain_precision": chatbot_summary["abstain_precision"]
        >= active_thresholds["abstain_precision_min"],
    }

    return {
        "schema_version": "scorecard_v1",
        "label": label,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "thresholds": active_thresholds,
        "docs": docs_summary,
        "chatbot": chatbot_summary,
        "overall": {
            "completeness_score": overall_score,
            "all_gates_pass": all(gates.values()),
            "gates": gates,
        },
    }


def save_quality_scorecard(path: Path, scorecard: dict[str, Any]) -> None:
    """Persist a scorecard JSON payload to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(scorecard, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _normalized_fraction(raw: Any) -> float:
    if isinstance(raw, bool):
        return 1.0 if raw else 0.0
    if raw is None:
        return 0.0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if value <= 1.0:
        return max(0.0, value)
    if value <= 100.0:
        return max(0.0, min(1.0, value / 100.0))
    return 1.0


def _mean(values: Any) -> float:
    vals = list(values)
    if not vals:
        return 0.0
    return sum(vals) / len(vals)


def build_artifact_scorecard(
    generated_repo_roots: list[Path],
    *,
    thresholds: dict[str, float] | None = None,
    label: str = "artifact-baseline",
    endpoint_sample_limit: int = 80,
) -> dict[str, Any]:
    """Build a combined scorecard from generated `.deepdoc/` artifacts.

    This path does not require a benchmark catalog or human-authored chatbot eval set.
    It computes provisional docs/chatbot completeness from persisted generation metadata
    and bootstrap chatbot endpoint coverage checks.
    """
    snapshots: list[dict[str, Any]] = []
    planner_results: list[BenchmarkResult] = []
    chatbot_rows: list[dict[str, Any]] = []

    for repo_root in generated_repo_roots:
        snapshot = _snapshot_generated_repo(repo_root, endpoint_sample_limit)
        snapshots.append(snapshot)

        docs = snapshot["docs"]
        planner_results.append(
            BenchmarkResult(
                name=snapshot["repo"],
                family="artifact_proxy",
                repo_path=str(repo_root),
                holdout=False,
                score=docs["completeness_score"],
                details={
                    "valid_page_rate": docs["valid_page_rate"],
                    "failure_rate": docs["failure_rate"],
                    "invalid_rate": docs["invalid_rate"],
                },
                notes=docs["notes"],
            )
        )

        chatbot_rows.extend(snapshot["chatbot"]["bootstrap_eval_rows"])

    scorecard = build_quality_scorecard(
        planner_results=planner_results,
        chatbot_results=chatbot_rows,
        thresholds=thresholds,
        label=label,
    )
    scorecard["mode"] = "artifact_proxy"
    scorecard["repo_count"] = len(snapshots)
    scorecard["repos"] = snapshots
    return scorecard


def discover_generated_repo_roots(generated_root: Path) -> list[Path]:
    """Return immediate children that look like generated DeepDoc repo outputs."""
    if not generated_root.exists() or not generated_root.is_dir():
        return []
    candidates = []
    for child in sorted(generated_root.iterdir()):
        if (child / ".deepdoc").exists():
            candidates.append(child)
    return candidates


def _snapshot_generated_repo(
    repo_root: Path, endpoint_sample_limit: int
) -> dict[str, Any]:
    state_dir = repo_root / ".deepdoc"
    quality = _load_json_object(state_dir / "generation_quality.json")
    scan_cache = _load_json_object(state_dir / "scan_cache.json")
    chatbot_dir = state_dir / "chatbot"

    docs_metrics = _docs_metrics_from_quality_payload(quality)
    chatbot_metrics = _chatbot_artifact_metrics(chatbot_dir)
    eval_rows = _bootstrap_chatbot_eval_rows(
        scan_cache=scan_cache,
        searchable_entries=chatbot_metrics["searchable_entries"],
        endpoint_sample_limit=endpoint_sample_limit,
        corpus_health=chatbot_metrics,
    )
    chatbot_summary = summarize_chatbot_results(eval_rows)

    return {
        "repo": repo_root.name,
        "repo_path": str(repo_root),
        "docs": docs_metrics,
        "chatbot": {
            "required_artifacts_present": chatbot_metrics["required_artifacts_present"],
            "required_artifacts_total": chatbot_metrics["required_artifacts_total"],
            "required_artifacts_rate": chatbot_metrics["required_artifacts_rate"],
            "nonempty_corpora": chatbot_metrics["nonempty_corpora"],
            "total_corpora": chatbot_metrics["total_corpora"],
            "nonempty_corpora_rate": chatbot_metrics["nonempty_corpora_rate"],
            "citationable_record_rate": chatbot_metrics["citationable_record_rate"],
            "corpus_chunk_counts": chatbot_metrics["corpus_chunk_counts"],
            "bootstrap_eval_cases": len(eval_rows),
            "bootstrap_completeness_score": chatbot_summary["completeness_score"],
            "bootstrap_eval_rows": eval_rows,
        },
    }


def _docs_metrics_from_quality_payload(quality: dict[str, Any]) -> dict[str, Any]:
    pages_generated = int(quality.get("pages_generated", 0))
    pages_failed = int(quality.get("pages_failed", 0))
    pages_invalid = int(quality.get("pages_invalid", 0))
    pages_degraded = int(quality.get("pages_degraded", 0))
    pages_total = pages_generated + pages_failed
    pages_valid = max(0, pages_generated - pages_invalid)

    valid_rate = (pages_valid / pages_total) if pages_total else 0.0
    invalid_rate = (pages_invalid / pages_total) if pages_total else 0.0
    failure_rate = (pages_failed / pages_total) if pages_total else 0.0
    degraded_rate = (pages_degraded / pages_total) if pages_total else 0.0

    notes = []
    if pages_failed:
        notes.append(f"{pages_failed} failed page(s)")
    if pages_invalid:
        notes.append(f"{pages_invalid} invalid page(s)")
    if pages_degraded:
        notes.append(f"{pages_degraded} degraded page(s)")

    return {
        "status": quality.get("status", "unknown"),
        "pages_total": pages_total,
        "pages_generated": pages_generated,
        "pages_valid": pages_valid,
        "pages_invalid": pages_invalid,
        "pages_failed": pages_failed,
        "pages_degraded": pages_degraded,
        "valid_page_rate": round(valid_rate, 4),
        "invalid_rate": round(invalid_rate, 4),
        "failure_rate": round(failure_rate, 4),
        "degraded_rate": round(degraded_rate, 4),
        "completeness_score": round(valid_rate * 100.0, 2),
        "notes": notes,
    }


def _chatbot_artifact_metrics(chatbot_dir: Path) -> dict[str, Any]:
    required_present = 0
    for rel in CHATBOT_REQUIRED_ARTIFACT_FILES:
        if (chatbot_dir / rel).exists():
            required_present += 1

    corpus_chunk_counts: dict[str, int] = {}
    searchable_entries: list[tuple[str, bool]] = []
    nonempty_corpora = 0
    total_records = 0
    citationable_records = 0

    for corpus, rel in CHATBOT_CORPUS_FILES.items():
        path = chatbot_dir / rel
        count = 0
        if path.exists():
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    payload = line.strip()
                    if not payload:
                        continue
                    count += 1
                    try:
                        record = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    text = str(record.get("text", "")).strip().lower()
                    if not text:
                        continue
                    has_citation = bool(
                        record.get("file_path") or record.get("doc_path")
                    )
                    searchable_entries.append((text, has_citation))
                    total_records += 1
                    if has_citation:
                        citationable_records += 1
        corpus_chunk_counts[corpus] = count
        if count > 0:
            nonempty_corpora += 1

    required_total = len(CHATBOT_REQUIRED_ARTIFACT_FILES)
    total_corpora = len(CHATBOT_CORPUS_FILES)

    return {
        "required_artifacts_present": required_present,
        "required_artifacts_total": required_total,
        "required_artifacts_rate": round(required_present / max(required_total, 1), 4),
        "nonempty_corpora": nonempty_corpora,
        "total_corpora": total_corpora,
        "nonempty_corpora_rate": round(nonempty_corpora / max(total_corpora, 1), 4),
        "citationable_record_rate": round(
            citationable_records / max(total_records, 1), 4
        ),
        "corpus_chunk_counts": corpus_chunk_counts,
        "searchable_entries": searchable_entries,
    }


def _bootstrap_chatbot_eval_rows(
    *,
    scan_cache: dict[str, Any],
    searchable_entries: list[tuple[str, bool]],
    endpoint_sample_limit: int,
    corpus_health: dict[str, Any],
) -> list[dict[str, Any]]:
    endpoints = (
        scan_cache.get("api_endpoints", []) if isinstance(scan_cache, dict) else []
    )
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            continue
        if not endpoint.get("publication_ready", True):
            continue
        method = str(endpoint.get("method", "")).strip().upper() or "GET"
        path = _normalize_endpoint_path(str(endpoint.get("path", "")).strip())
        if not path:
            continue
        key = (method, path)
        if key in seen:
            continue
        seen.add(key)

        token_path = path.lower()
        token_method_path = f"{method.lower()} {token_path}"
        matches = [
            has_citation
            for text, has_citation in searchable_entries
            if token_path in text or token_method_path in text
        ]
        hit = bool(matches)
        citation_precision = _mean(1.0 if matched else 0.0 for matched in matches)

        rows.append(
            {
                "question": f"Which handler serves {method} {path}?",
                "grounded_correct": hit,
                "citation_precision": citation_precision if hit else 0.0,
                "evidence_recall": 1.0 if hit else 0.0,
                "abstain_expected": False,
            }
        )
        if len(rows) >= endpoint_sample_limit:
            break

    rows.append(
        {
            "question": "Is chatbot index corpus healthy?",
            "grounded_correct": (
                corpus_health.get("required_artifacts_rate", 0.0) >= 0.9
                and corpus_health.get("nonempty_corpora_rate", 0.0) >= 0.8
            ),
            "citation_precision": corpus_health.get("citationable_record_rate", 0.0),
            "evidence_recall": corpus_health.get("nonempty_corpora_rate", 0.0),
            "abstain_expected": False,
        }
    )
    return rows


def _normalize_endpoint_path(path: str) -> str:
    path = path.strip()
    if not path:
        return ""
    path = re.sub(r"^https?://[^/]+", "", path)
    if path.startswith("//"):
        path = re.sub(r"^//[^/]+", "", path)
    path = path.split("?", 1)[0].split("#", 1)[0]
    if not path.startswith("/"):
        path = "/" + path.lstrip("/")
    path = re.sub(r"/{2,}", "/", path)
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return path


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def score_plan(
    plan: DocPlan, gold: dict[str, Any]
) -> tuple[float, dict[str, float], list[str]]:
    details: dict[str, float] = {}
    notes: list[str] = []

    primary_type = plan.classification.get("repo_profile", {}).get(
        "primary_type", "other"
    )
    expected_type = gold.get("expected_primary_type")
    details["profile_match"] = (
        1.0 if not expected_type or primary_type == expected_type else 0.0
    )
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
                if any(
                    any(candidate.lower() in title.lower() for title in titles)
                    for candidate in title_group
                ):
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
        details["noise_suppression"] = max(
            0.0, 1.0 - (len(violations) / max(len(titles), 1))
        )
        if violations:
            notes.append(f"forbidden titles present: {', '.join(violations[:5])}")
    else:
        details["noise_suppression"] = 1.0

    orphaned = len(plan.orphaned_files)
    max_orphaned = gold.get("max_orphaned")
    if max_orphaned is not None:
        details["orphan_score"] = (
            1.0
            if orphaned <= max_orphaned
            else max(0.0, 1 - ((orphaned - max_orphaned) / max(1, max_orphaned + 1)))
        )
        if orphaned > max_orphaned:
            notes.append(f"too many orphaned files: {orphaned} > {max_orphaned}")
    else:
        details["orphan_score"] = 1.0

    overview_limit = gold.get("max_overview_files")
    overview_buckets = [
        bucket
        for bucket in plan.buckets
        if (bucket.generation_hints or {}).get("is_introduction_page")
    ]
    if overview_limit is not None and overview_buckets:
        overview_files = max(len(bucket.owned_files) for bucket in overview_buckets)
        details["overview_focus"] = (
            1.0
            if overview_files <= overview_limit
            else max(
                0.0, 1 - ((overview_files - overview_limit) / max(1, overview_limit))
            )
        )
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
