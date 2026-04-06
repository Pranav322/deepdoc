"""V2 Persistence — save and load plan, scan cache, and generation ledger.

Phase 4 of the bucket-based doc pipeline. Three stores:

  plan.json         — full bucket plan (DocPlan with DocBuckets)
  scan_cache.json   — lightweight scan metadata (no AST/file-contents — those are huge)
  ledger.json       — per-page generation record (word count, mermaid count, warnings,
                      file hashes, timestamp) used by Phase 5 for smart invalidation

All files live in {repo_root}/.deepdoc/
The legacy .deepdoc_plan.json / .deepdoc_file_map.json in repo root are kept for
backwards-compatibility with the legacy updater, but the canonical source of truth is
the new .deepdoc/ directory.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from ._legacy_types import DocPage
from ._legacy_types import DocPlan as LegacyDocPlan
from .v2_models import DocBucket, DocPlan, tracked_bucket_files

# ─────────────────────────────────────────────────────────────────────────────
# File locations
# ─────────────────────────────────────────────────────────────────────────────

DEEPDOC_DIR = ".deepdoc"
PLAN_FILE = "plan.json"
SCAN_CACHE_FILE = "scan_cache.json"
LEDGER_FILE = "ledger.json"
FILE_MAP_FILE = "file_map.json"
STATE_FILE = "state.json"
SYNC_RECEIPT_FILE = "sync_receipt.json"
ENGINE_FINGERPRINT = "routes_repo_resolution_v2_trimmed_scope"

# Legacy top-level files (kept for backwards-compat)
LEGACY_PLAN_FILE = ".deepdoc_plan.json"
LEGACY_FILE_MAP_FILE = ".deepdoc_file_map.json"


def _state_dir(repo_root: Path) -> Path:
    """Return the .deepdoc state directory, creating it if necessary."""
    d = repo_root / DEEPDOC_DIR
    d.mkdir(exist_ok=True)
    return d


# ─────────────────────────────────────────────────────────────────────────────
# Sync state persistence (commit baseline tracking)
# ─────────────────────────────────────────────────────────────────────────────


def save_sync_state(
    repo_root: Path,
    *,
    commit_sha: str,
    status: str = "success",
    generator_version: str = "v2_buckets",
    engine_fingerprint: str = ENGINE_FINGERPRINT,
    advance_baseline: bool = True,
) -> None:
    """Write .deepdoc/state.json to track the last synced commit.

    Args:
        repo_root: Repository root path.
        commit_sha: The HEAD commit SHA at the time of this generate/update.
        status: "success" | "partial" | "failed".
        generator_version: Plan version used ("v2_buckets" | "v1_legacy").
        advance_baseline: If True, update last_synced_commit. If False, only
            update last_attempted_commit (used for partial/failed runs).
    """
    state = _state_dir(repo_root)
    path = state / STATE_FILE

    # Load existing state to preserve fields we're not updating
    existing: dict[str, Any] = {}
    if path.exists():
        with contextlib.suppress(Exception):
            existing = json.loads(path.read_text(encoding="utf-8"))

    data = dict(existing)
    data["last_attempted_commit"] = commit_sha
    data["status"] = status
    data["generator_version"] = generator_version
    data["engine_fingerprint"] = engine_fingerprint

    if advance_baseline:
        data["last_synced_commit"] = commit_sha
        data["synced_at"] = _now_iso()

    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_sync_state(repo_root: Path) -> dict[str, Any] | None:
    """Read .deepdoc/state.json. Returns None if not present or corrupt."""
    path = _state_dir(repo_root) / STATE_FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_sync_receipt(repo_root: Path, receipt: dict[str, Any]) -> None:
    """Write a top-level receipt for the latest generate/update sync run."""
    path = _state_dir(repo_root) / SYNC_RECEIPT_FILE
    path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")


def load_sync_receipt(repo_root: Path) -> dict[str, Any] | None:
    """Read .deepdoc/sync_receipt.json. Returns None if not present or corrupt."""
    path = _state_dir(repo_root) / SYNC_RECEIPT_FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Plan persistence
# ─────────────────────────────────────────────────────────────────────────────


def save_plan(plan: DocPlan | LegacyDocPlan, repo_root: Path) -> None:
    """Serialise the doc plan to .deepdoc/plan.json.

    Handles both bucket-based DocPlan and legacy DocPlan.
    Also writes the legacy .deepdoc_plan.json for updater_v2 compatibility.
    """
    state = _state_dir(repo_root)

    if hasattr(plan, "buckets"):
        # v2 bucket plan
        data: dict[str, Any] = {
            "version": "v2_buckets",
            "generated_at": _now_iso(),
            "buckets": [_bucket_to_dict(b) for b in plan.buckets],
            "nav_structure": plan.nav_structure,
            "skipped_files": plan.skipped_files,
            "orphaned_files": plan.orphaned_files,
            "integration_candidates": plan.integration_candidates,
            "classification": plan.classification,
        }
    else:
        # legacy plan
        data = {
            "version": "v1_legacy",
            "generated_at": _now_iso(),
            "pages": [
                {
                    "title": p.title,
                    "slug": p.slug,
                    "page_type": p.page_type,
                    "description": p.description,
                    "source_files": p.source_files,
                    "section": p.section,
                    "priority": p.priority,
                    "depends_on": getattr(p, "depends_on", []),
                }
                for p in plan.pages
            ],
            "nav_structure": plan.nav_structure,
            "skipped_files": plan.skipped_files,
        }

    json_str = json.dumps(data, indent=2)
    (state / PLAN_FILE).write_text(json_str, encoding="utf-8")

    # Also write legacy location for backwards-compat
    (repo_root / LEGACY_PLAN_FILE).write_text(json_str, encoding="utf-8")


def load_plan(repo_root: Path) -> DocPlan | LegacyDocPlan | None:
    """Load the saved plan. Returns DocPlan (v2) or LegacyDocPlan, or None."""
    # Prefer the new location, fall back to legacy
    state_file = _state_dir(repo_root) / PLAN_FILE
    legacy_file = repo_root / LEGACY_PLAN_FILE

    plan_path = (
        state_file
        if state_file.exists()
        else (legacy_file if legacy_file.exists() else None)
    )
    if not plan_path:
        return None

    try:
        data = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    version = data.get("version", "v1_legacy")

    if version == "v2_buckets":
        return _load_bucket_plan(data)
    else:
        return _load_legacy_plan(data)


def _load_bucket_plan(data: dict) -> DocPlan:
    """Deserialise a v2 bucket plan."""
    buckets = [_dict_to_bucket(b) for b in data.get("buckets", [])]
    return DocPlan(
        buckets=buckets,
        nav_structure=data.get("nav_structure", {}),
        skipped_files=data.get("skipped_files", []),
        orphaned_files=data.get("orphaned_files", []),
        classification=data.get("classification", {}),
        integration_candidates=data.get("integration_candidates", []),
    )


def _load_legacy_plan(data: dict) -> LegacyDocPlan:
    """Deserialise a v1 legacy plan."""
    pages = [
        DocPage(
            title=p["title"],
            slug=p["slug"],
            page_type=p.get("page_type", "guide"),
            description=p.get("description", ""),
            source_files=p.get("source_files", []),
            section=p.get("section", ""),
            priority=p.get("priority", 0),
            depends_on=p.get("depends_on", []),
        )
        for p in data.get("pages", [])
    ]
    return LegacyDocPlan(
        pages=pages,
        nav_structure=data.get("nav_structure", {}),
        skipped_files=data.get("skipped_files", []),
    )


def _bucket_to_dict(b: DocBucket) -> dict:
    return {
        "bucket_type": b.bucket_type,
        "title": b.title,
        "slug": b.slug,
        "section": b.section,
        "description": b.description,
        "depends_on": b.depends_on,
        "owned_files": b.owned_files,
        "owned_symbols": b.owned_symbols,
        "artifact_refs": b.artifact_refs,
        "required_sections": b.required_sections,
        "required_diagrams": b.required_diagrams,
        "coverage_targets": b.coverage_targets,
        "generation_hints": b.generation_hints,
        "priority": b.priority,
        "parent_slug": b.parent_slug,
        "publication_tier": b.publication_tier,
        "source_kind_summary": b.source_kind_summary,
    }


# Infer generation_hints from legacy bucket_type for old serialized plans
_LEGACY_TYPE_HINTS: dict[str, dict] = {
    "system": {"prompt_style": "system", "icon": "server"},
    "feature": {"prompt_style": "feature", "icon": "bolt"},
    "endpoint": {
        "is_endpoint_family": True,
        "include_endpoint_detail": True,
        "include_openapi": True,
        "prompt_style": "endpoint",
        "icon": "globe-alt",
    },
    "endpoint_ref": {
        "is_endpoint_ref": True,
        "include_endpoint_detail": True,
        "include_openapi": True,
        "prompt_style": "endpoint_ref",
        "icon": "globe-alt",
    },
    "integration": {
        "include_integration_detail": True,
        "prompt_style": "integration",
        "icon": "puzzle-piece",
    },
    "database": {
        "include_database_context": True,
        "prompt_style": "database",
        "icon": "database",
    },
}


def _dict_to_bucket(d: dict) -> DocBucket:
    hints = d.get("generation_hints", {})
    # Backward compat: infer hints from legacy bucket_type if hints are missing
    if not hints:
        legacy_type = d.get("bucket_type", "")
        hints = dict(_LEGACY_TYPE_HINTS.get(legacy_type, {}))
    return DocBucket(
        bucket_type=d.get("bucket_type", "general"),
        title=d["title"],
        slug=d["slug"],
        section=d.get("section", ""),
        description=d.get("description", ""),
        depends_on=d.get("depends_on", []),
        owned_files=d.get("owned_files", []),
        owned_symbols=d.get("owned_symbols", []),
        artifact_refs=d.get("artifact_refs", []),
        required_sections=d.get("required_sections", []),
        required_diagrams=d.get("required_diagrams", []),
        coverage_targets=d.get("coverage_targets", []),
        generation_hints=hints,
        priority=d.get("priority", 0),
        parent_slug=d.get("parent_slug"),
        publication_tier=d.get("publication_tier", "core"),
        source_kind_summary=d.get("source_kind_summary", {}),
    )


# ─────────────────────────────────────────────────────────────────────────────
# File → page map persistence
# ─────────────────────────────────────────────────────────────────────────────


def save_file_map(plan: DocPlan | LegacyDocPlan, repo_root: Path) -> None:
    """Save file → [slug, ...] mapping for the updater."""
    mapping: dict[str, list[str]] = {}
    for page in plan.pages:
        tracked_files = (
            tracked_bucket_files(page._b)
            if hasattr(page, "_b")
            else list(page.source_files)
        )
        for src_file in tracked_files:
            mapping.setdefault(src_file, []).append(page.slug)

    json_str = json.dumps(mapping, indent=2)
    (_state_dir(repo_root) / FILE_MAP_FILE).write_text(json_str, encoding="utf-8")
    (repo_root / LEGACY_FILE_MAP_FILE).write_text(json_str, encoding="utf-8")


def load_file_map(repo_root: Path) -> dict[str, list[str]]:
    """Load the file → [slug] map. Returns empty dict if missing."""
    state_file = _state_dir(repo_root) / FILE_MAP_FILE
    legacy_file = repo_root / LEGACY_FILE_MAP_FILE
    path = (
        state_file
        if state_file.exists()
        else (legacy_file if legacy_file.exists() else None)
    )
    if not path:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Scan cache persistence
# ─────────────────────────────────────────────────────────────────────────────


def save_scan_cache(scan: Any, repo_root: Path) -> None:
    """Save a lightweight scan snapshot to .deepdoc/scan_cache.json.

    We deliberately omit: parsed_files (AST objects), file_contents (raw strings),
    and giant_file_clusters (large nested objects). Those are rebuilt cheaply on demand.
    """

    def _config_impact_to_dict(item: Any) -> dict[str, Any]:
        if isinstance(item, dict):
            return {
                "key": item.get("key", ""),
                "kind": item.get("kind", ""),
                "file_path": item.get("file_path", ""),
                "default_value": item.get("default_value", ""),
                "related_files": list(item.get("related_files", []))[:20],
                "related_endpoints": list(item.get("related_endpoints", []))[:20],
            }
        return {
            "key": getattr(item, "key", ""),
            "kind": getattr(item, "kind", ""),
            "file_path": getattr(item, "file_path", ""),
            "default_value": getattr(item, "default_value", ""),
            "related_files": list(getattr(item, "related_files", []))[:20],
            "related_endpoints": list(getattr(item, "related_endpoints", []))[:20],
        }

    data = {
        "version": "v2",
        "generated_at": _now_iso(),
        "total_files": scan.total_files,
        "languages": scan.languages,
        "frameworks_detected": scan.frameworks_detected,
        "entry_points": scan.entry_points,
        "config_files": scan.config_files,
        "has_openapi": scan.has_openapi,
        "openapi_paths": scan.openapi_paths,
        "file_line_counts": scan.file_line_counts,
        "api_endpoints": scan.api_endpoints,
        "source_kind_by_file": scan.source_kind_by_file,
        "file_frameworks": scan.file_frameworks,
        # Lightweight integration summary
        "integration_summary": [
            {
                "name": i.name,
                "display_name": i.display_name,
                "description": i.description,
                "files": i.files[:20],
                "is_substantial": i.is_substantial,
                "party": getattr(i, "party", "third_party"),
            }
            for i in (scan.integration_identities or [])
        ],
        # Lightweight endpoint bundle summary
        "endpoint_bundle_summary": [
            {
                "endpoint_family": b.endpoint_family,
                "methods_paths": b.methods_paths,
                "handler_file": b.handler_file,
                "handler_symbols": b.handler_symbols,
                "integration_edges": b.integration_edges,
            }
            for b in (scan.endpoint_bundles or [])
        ],
        "runtime_summary": {
            "tasks": [
                {
                    "name": t.name,
                    "file_path": t.file_path,
                    "runtime_kind": t.runtime_kind,
                    "queue": getattr(t, "queue", ""),
                    "schedule_sources": getattr(t, "schedule_sources", []),
                    "triggers": getattr(t, "triggers", []),
                    "producer_files": getattr(t, "producer_files", []),
                    "linked_endpoints": getattr(t, "linked_endpoints", []),
                }
                for t in getattr(getattr(scan, "runtime_scan", None), "tasks", [])[:100]
            ],
            "schedulers": [
                {
                    "name": s.name,
                    "file_path": s.file_path,
                    "scheduler_type": s.scheduler_type,
                    "cron": getattr(s, "cron", ""),
                    "invoked_targets": getattr(s, "invoked_targets", []),
                    "linked_endpoints": getattr(s, "linked_endpoints", []),
                }
                for s in getattr(getattr(scan, "runtime_scan", None), "schedulers", [])[
                    :100
                ]
            ],
            "realtime_consumers": [
                {
                    "name": c.name,
                    "file_path": c.file_path,
                    "consumer_type": c.consumer_type,
                    "routes": getattr(c, "routes", []),
                }
                for c in getattr(
                    getattr(scan, "runtime_scan", None), "realtime_consumers", []
                )[:100]
            ],
        },
        "database_groups": [
            {
                "key": g.key,
                "label": g.label,
                "file_paths": g.file_paths,
                "model_names": g.model_names,
                "orm_frameworks": g.orm_frameworks,
                "external_refs": g.external_refs,
            }
            for g in getattr(
                getattr(scan, "artifact_scan", None), "database_scan", None
            ).groups[:100]
        ]
        if getattr(getattr(scan, "artifact_scan", None), "database_scan", None)
        else [],
        "config_impacts": [
            _config_impact_to_dict(item)
            for item in (getattr(scan, "config_impacts", []) or [])[:200]
        ],
        "graphql_interfaces": [
            {
                "name": g.name,
                "file_path": g.file_path,
                "kind": g.kind,
                "fields": g.fields,
                "related_types": g.related_types,
            }
            for g in (getattr(scan, "graphql_interfaces", None) or [])[:100]
        ],
        "knex_artifacts": [
            {
                "file_path": k.file_path,
                "artifact_type": k.artifact_type,
                "table_name": k.table_name,
                "columns": k.columns,
                "foreign_keys": k.foreign_keys,
                "query_patterns": k.query_patterns,
            }
            for k in (getattr(scan, "knex_artifacts", None) or [])[:100]
        ],
    }
    (_state_dir(repo_root) / SCAN_CACHE_FILE).write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


def load_scan_cache(repo_root: Path) -> dict | None:
    """Load the saved scan cache. Returns raw dict or None."""
    path = _state_dir(repo_root) / SCAN_CACHE_FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def scan_cache_age_seconds(repo_root: Path) -> float | None:
    """Return how many seconds ago the scan cache was written, or None if missing."""
    path = _state_dir(repo_root) / SCAN_CACHE_FILE
    if not path.exists():
        return None
    try:
        mtime = path.stat().st_mtime
        return datetime.now(tz=timezone.utc).timestamp() - mtime
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Generation ledger
# ─────────────────────────────────────────────────────────────────────────────


def save_generation_ledger(
    results: list[Any], repo_root: Path, output_dir: Path
) -> None:
    """Save a per-page generation record to .deepdoc/ledger.json.

    Each record contains:
    - slug, title, bucket_type
    - word_count, mermaid_block_count
    - validation warnings list
    - file_hashes: sha256 of each owned_file at generation time
    - generated_at: ISO timestamp
    - success: bool
    """
    ledger: dict[str, Any] = {}

    # Load existing ledger (keep records for pages not in this run)
    existing = load_generation_ledger(repo_root)
    ledger.update(existing)

    import re as _re

    for result in results:
        bucket = result.bucket
        is_success = result.content is not None and not result.error

        # If this generation failed, preserve the last known good record
        # and only annotate it with failure info. This prevents staleness
        # checks from getting noisy after transient LLM failures.
        if not is_success:
            existing_record = ledger.get(bucket.slug)
            if existing_record and existing_record.get("success"):
                existing_record["last_failed_at"] = _now_iso()
                existing_record["last_error"] = result.error
                existing_record["last_failed_retries"] = getattr(result, "retries", 0)
                ledger[bucket.slug] = existing_record
                continue
            # No previous good record — fall through and write the failure

        record: dict[str, Any] = {
            "slug": bucket.slug,
            "title": bucket.title,
            "bucket_type": bucket.bucket_type,
            "section": bucket.section,
            "publication_tier": getattr(bucket, "publication_tier", "core"),
            "source_kind_summary": getattr(bucket, "source_kind_summary", {}),
            "generation_hints": getattr(bucket, "generation_hints", {}),
            "doc_path": "index.mdx"
            if (getattr(bucket, "generation_hints", {}) or {}).get(
                "is_introduction_page"
            )
            else f"{bucket.slug}.mdx",
            "success": is_success,
            "error": result.error,
            "generated_at": _now_iso(),
            "elapsed_seconds": round(result.elapsed_seconds, 2),
            "retries": getattr(result, "retries", 0),
        }

        # Word + diagram counts
        if result.content:
            record["word_count"] = len(result.content.split())
            record["mermaid_block_count"] = len(
                _re.findall(r"```mermaid", result.content)
            )
        else:
            record["word_count"] = 0
            record["mermaid_block_count"] = 0

        # Validation metadata
        if result.validation:
            record["validation"] = {
                "is_valid": result.validation.is_valid,
                "warnings": result.validation.warnings,
                "missing_sections": result.validation.missing_sections,
            }

        # File hashes at generation time (for smart invalidation)
        file_hashes: dict[str, str] = {}
        for src_file in tracked_bucket_files(bucket):
            src_path = (
                output_dir.parent / src_file
            )  # output_dir is docs/, repo is parent
            if src_path.exists():
                try:
                    content = src_path.read_text(encoding="utf-8", errors="replace")
                    file_hashes[src_file] = hashlib.sha256(
                        content.encode("utf-8")
                    ).hexdigest()[:16]
                except Exception:
                    pass
        record["file_hashes"] = file_hashes

        # Clear any stale failure annotations from previous runs
        record.pop("last_failed_at", None)
        record.pop("last_error", None)
        record.pop("last_failed_retries", None)

        ledger[bucket.slug] = record

    (_state_dir(repo_root) / LEDGER_FILE).write_text(
        json.dumps(ledger, indent=2), encoding="utf-8"
    )


def load_generation_ledger(repo_root: Path) -> dict[str, Any]:
    """Load the generation ledger. Returns {slug: record} dict."""
    path = _state_dir(repo_root) / LEDGER_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def prune_generation_ledger(repo_root: Path, keep_slugs: set[str]) -> None:
    """Remove stale bucket records from the generation ledger."""
    ledger = load_generation_ledger(repo_root)
    if not ledger:
        return

    pruned = {slug: record for slug, record in ledger.items() if slug in keep_slugs}
    (_state_dir(repo_root) / LEDGER_FILE).write_text(
        json.dumps(pruned, indent=2), encoding="utf-8"
    )


def cleanup_stale_generated_files(
    repo_root: Path,
    output_dir: Path,
    keep_slugs: set[str],
    previous_ledger: dict[str, Any] | None = None,
) -> list[str]:
    """Delete previously generated Markdown pages that no longer belong to the plan.

    Only files tracked in the generation ledger are eligible for deletion.
    """
    ledger = (
        previous_ledger
        if previous_ledger is not None
        else load_generation_ledger(repo_root)
    )
    deleted: list[str] = []

    for slug, record in ledger.items():
        if slug in keep_slugs:
            continue

        doc_rel = record.get("doc_path") or _fallback_doc_path(record)
        if not doc_rel:
            continue

        doc_path = output_dir / doc_rel
        try:
            resolved = doc_path.resolve()
            output_root = output_dir.resolve()
            if output_root not in resolved.parents and resolved != output_root:
                continue
        except Exception:
            continue

        if doc_path.exists() and doc_path.is_file():
            doc_path.unlink()
            deleted.append(doc_rel)
            _prune_empty_parents(doc_path, output_dir)

    return deleted


def find_stale_buckets(
    plan: DocPlan,
    repo_root: Path,
    output_dir: Path | None = None,
) -> list[str]:
    """Compare current file hashes to ledger records. Returns list of stale bucket slugs.

    A bucket is stale if:
    - It has no ledger record (never generated)
    - Any of its tracked source/artifact files has changed since the recorded hash
    - Any of its tracked source/artifact files has been deleted
    - Its generated doc output file doesn't exist on disk

    Args:
        plan: The current doc plan with buckets.
        repo_root: Repository root path.
        output_dir: Directory where generated docs live. If provided, missing
            output files are treated as stale. No hardcoded fallback.
    """
    ledger = load_generation_ledger(repo_root)
    stale: list[str] = []

    for bucket in plan.buckets:
        slug = bucket.slug
        record = ledger.get(slug)

        # Never generated
        if not record:
            stale.append(slug)
            continue

        # Generation previously failed
        if not record.get("success", False):
            stale.append(slug)
            continue

        # Check that the generated doc output file still exists on disk
        if output_dir is not None:
            doc_rel = record.get("doc_path") or _fallback_doc_path(record)
            if doc_rel:
                doc_path = output_dir / doc_rel
                if not doc_path.exists():
                    stale.append(slug)
                    continue

        # Check file hashes (and detect deleted tracked files)
        recorded_hashes = record.get("file_hashes", {})
        changed = False
        for src_file in tracked_bucket_files(bucket):
            src_path = repo_root / src_file
            if not src_path.exists():
                # File was deleted — bucket is stale
                changed = True
                break
            try:
                content = src_path.read_text(encoding="utf-8", errors="replace")
                current_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
                if (
                    src_file not in recorded_hashes
                    or recorded_hashes[src_file] != current_hash
                ):
                    changed = True
                    break
            except Exception:
                changed = True
                break

        if changed:
            stale.append(slug)

    return stale


def ledger_summary(repo_root: Path) -> dict[str, Any]:
    """Return a high-level summary of the generation ledger."""
    ledger = load_generation_ledger(repo_root)
    if not ledger:
        return {"total": 0}

    total = len(ledger)
    successful = sum(1 for r in ledger.values() if r.get("success"))
    failed = total - successful
    total_words = sum(r.get("word_count", 0) for r in ledger.values())
    total_diagrams = sum(r.get("mermaid_block_count", 0) for r in ledger.values())
    by_type: dict[str, int] = {}
    for r in ledger.values():
        bt = r.get("bucket_type", "unknown")
        by_type[bt] = by_type.get(bt, 0) + 1

    return {
        "total": total,
        "successful": successful,
        "failed": failed,
        "total_words": total_words,
        "total_diagrams": total_diagrams,
        "by_bucket_type": by_type,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Convenience: save everything in one call
# ─────────────────────────────────────────────────────────────────────────────


def save_all(
    plan: Any, scan: Any, results: list[Any], repo_root: Path, output_dir: Path
) -> None:
    """Save plan + file map + scan cache + generation ledger in one call."""
    save_plan(plan, repo_root)
    save_file_map(plan, repo_root)
    if scan is not None:
        try:
            save_scan_cache(scan, repo_root)
        except Exception:
            pass  # scan cache is best-effort
    if results:
        save_generation_ledger(results, repo_root, output_dir)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _fallback_doc_path(record: dict[str, Any]) -> str | None:
    slug = record.get("slug")
    if not slug:
        return None
    hints = record.get("generation_hints", {})
    if hints.get("is_introduction_page"):
        return "index.mdx"
    return f"{slug}.mdx"


def _prune_empty_parents(path: Path, stop_at: Path) -> None:
    current = path.parent
    stop = stop_at.resolve()
    while True:
        try:
            if current.resolve() == stop:
                break
        except Exception:
            break

        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent
