"""Deterministic per-service planning units for bounded multi-unit planning.

Groups a large repo's files by `RepoScan.file_services` into bounded
`PlanningUnit`s so each can be planned independently and merged, instead of
sending the whole repo through one unbounded prompt.
"""

from __future__ import annotations

import dataclasses
import posixpath
import re

from ..llm import ModelCapabilityError
from ..source_metadata import classify_source_kind
from ..v2_models import RepoScan, endpoint_owned_files
from .topology import TopologyMap

CORE_SLUG = "core"

# Fixed PROPOSE/ASSIGN template scaffolding (instructions, section headers,
# json blocks) that isn't captured by rendering just the bare required
# section — see `unit_fits_model_budget`. Padding the measured tokens by
# this constant keeps the pre-flight gate conservative (never a false
# "fits") without duplicating the full prompt-rendering closures from
# engine.py, which need classify/propose output this check runs before.
_TEMPLATE_OVERHEAD_TOKENS = 900

# Small, stable extension→language map for recomputing a sub-scan's own
# `languages` counts. Intentionally duplicated from `scan_repo`'s inline map
# rather than importing it (that map is a local variable, not exported) —
# both are small and rarely change.
_EXT_TO_LANG = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".php": "php",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".vue": "vue",
}


@dataclasses.dataclass(frozen=True)
class PlanningUnit:
    """A bounded, independently plannable slice of the repo."""

    slug: str
    label: str
    files: tuple[str, ...] = ()
    # True when this unit is a single indivisible file (or otherwise
    # unsplittable) that still doesn't fit the model budget. Callers must
    # not send a coarse unit through normal LLM planning — see
    # `bound_planning_unit`.
    coarse: bool = False


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or CORE_SLUG


def _group_key(scan: RepoScan, path: str) -> tuple[bool, str]:
    service = scan.file_services.get(path)
    return (True, service) if service else (False, "")


def build_planning_units(scan: RepoScan) -> list[PlanningUnit]:
    """Group files by `scan.file_services`; unclaimed files go to `core`.

    Returns a single unit (slug "core" or the sole named service) when the
    repo has zero or one meaningful service, so callers can detect the
    single-unit parity path. Callers must still run this unit through
    `bound_planning_unit` — a single meaningful service can still be too
    large for the model budget.
    """
    groups: dict[tuple[bool, str], list[str]] = {}
    for path in sorted(scan.file_summaries):
        groups.setdefault(_group_key(scan, path), []).append(path)

    if not groups:
        return [PlanningUnit(slug=CORE_SLUG, label=CORE_SLUG, files=())]

    if len(groups) == 1:
        (is_named, raw), files = next(iter(groups.items()))
        slug = _slugify(raw) if is_named else CORE_SLUG
        label = raw if is_named else CORE_SLUG
        return [PlanningUnit(slug=slug, label=label, files=tuple(sorted(files)))]

    slug_counts: dict[str, int] = {}
    units: list[PlanningUnit] = []
    for key in sorted(groups, key=lambda k: (k[0], k[1])):
        is_named, raw = key
        base_slug = _slugify(raw) if is_named else CORE_SLUG
        label = raw if is_named else CORE_SLUG
        seen = slug_counts.get(base_slug, 0)
        slug_counts[base_slug] = seen + 1
        slug = base_slug if seen == 0 else f"{base_slug}-{seen + 1}"
        units.append(PlanningUnit(slug=slug, label=label, files=tuple(sorted(groups[key]))))

    units.sort(key=lambda u: u.slug)
    return units


def _filter_dict(source: dict, files: set[str]) -> dict:
    return {k: v for k, v in source.items() if k in files}


def _unit_dirs(files: set[str]) -> set[str]:
    return {f.rsplit("/", 1)[0] if "/" in f else "" for f in files}


def _belongs_to_unit(path: str, files: set[str], unit_dirs: set[str]) -> bool:
    """A path belongs to the unit if it's an owned file, or sits alongside one.

    Config/entry-point files (e.g. a service's Dockerfile) usually aren't
    tracked in `file_services`, so exact membership would drop them from
    every unit; directory co-location keeps them with their service.
    """
    if path in files:
        return True
    directory = path.rsplit("/", 1)[0] if "/" in path else ""
    return directory in unit_dirs


def _filter_list(source: list[str], files: set[str], unit_dirs: set[str]) -> list[str]:
    return [v for v in source if _belongs_to_unit(v, files, unit_dirs)]


def _filter_topology_map(topology: TopologyMap | None, files: set[str]) -> TopologyMap | None:
    if topology is None:
        return None
    clusters = []
    for cluster in topology.clusters:
        all_files = [f for f in cluster.all_files if f in files]
        if not all_files:
            # Every file this cluster owns belongs to another unit — drop it
            # rather than keep a cluster object that still references
            # out-of-unit files.
            continue
        clusters.append(
            dataclasses.replace(
                cluster,
                all_files=all_files,
                entry_files=[f for f in cluster.entry_files if f in files],
                shared_dep_files=[f for f in cluster.shared_dep_files if f in files],
            )
        )
    return TopologyMap(
        clusters=clusters,
        file_indegree=_filter_dict(topology.file_indegree, files),
        file_call_depth=_filter_dict(topology.file_call_depth, files),
        file_cluster_id=_filter_dict(topology.file_cluster_id, files),
        foundational_files=[f for f in topology.foundational_files if f in files],
    )


def _languages_for_files(files: set[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in files:
        _, ext = posixpath.splitext(path)
        lang = _EXT_TO_LANG.get(ext.lower())
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
    return counts


def _filter_by_attr(items: list, files: set[str], attr: str) -> list:
    """Keep items whose single-file `attr` belongs to `files`."""
    return [item for item in items if getattr(item, attr, None) in files]


def _filter_by_list_attr(items: list, files: set[str], attr: str) -> list:
    """Keep items with >=1 file in list-attribute `attr` inside `files`,
    trimming that attribute to just this unit's files (a kept item never
    keeps a reference to another unit's file)."""
    kept = []
    for item in items:
        item_files = [f for f in getattr(item, attr, []) if f in files]
        if item_files:
            kept.append(dataclasses.replace(item, **{attr: item_files}))
    return kept


def _filter_debug_signals(signals: list, files: set[str]) -> list:
    kept = []
    for sig in signals:
        if sig.file_path not in files:
            continue
        kept.append(dataclasses.replace(sig, files=[f for f in sig.files if f in files]))
    return kept


def _filter_config_impacts(impacts: list, files: set[str]) -> list:
    kept = []
    for impact in impacts:
        if impact.file_path not in files:
            continue
        kept.append(
            dataclasses.replace(
                impact, related_files=[f for f in impact.related_files if f in files]
            )
        )
    return kept


def _filter_research_contexts(contexts: list[dict], files: set[str]) -> list[dict]:
    return [c for c in contexts if c.get("file_path") in files]


def _filter_service_boundaries(boundaries: list[dict], files: set[str]) -> list[dict]:
    """Keep only the boundary stub(s) this unit's own files actually sit
    under. A boundary entry is a `{name, root, source}` directory-root
    record, not file-scoped evidence — it can't grant ownership of a
    foreign file — but a unit still shouldn't see every other service's
    root listed alongside its own.
    """
    kept = []
    for boundary in boundaries:
        root = str(boundary.get("root", "")).rstrip("/")
        if any(f == root or f.startswith(f"{root}/") for f in files):
            kept.append(boundary)
    return kept


def _filter_database_scan(db_scan, files: set[str]):
    if db_scan is None:
        return None
    groups = []
    for group in db_scan.groups:
        trimmed = [f for f in group.file_paths if f in files]
        if trimmed:
            groups.append(dataclasses.replace(group, file_paths=trimmed))
    return dataclasses.replace(
        db_scan,
        model_files=_filter_by_attr(db_scan.model_files, files, "file_path"),
        migration_files=[f for f in db_scan.migration_files if f in files],
        schema_files=[f for f in db_scan.schema_files if f in files],
        groups=groups,
        graphql_interfaces=_filter_by_attr(db_scan.graphql_interfaces, files, "file_path"),
        knex_artifacts=_filter_by_attr(db_scan.knex_artifacts, files, "file_path"),
    )


def _filter_artifact_scan(artifact_scan, files: set[str]):
    if artifact_scan is None:
        return None
    return dataclasses.replace(
        artifact_scan,
        setup_artifacts=[f for f in artifact_scan.setup_artifacts if f in files],
        deploy_artifacts=[f for f in artifact_scan.deploy_artifacts if f in files],
        test_artifacts=[f for f in artifact_scan.test_artifacts if f in files],
        ci_artifacts=[f for f in artifact_scan.ci_artifacts if f in files],
        ops_artifacts=[f for f in artifact_scan.ops_artifacts if f in files],
        database_scan=_filter_database_scan(artifact_scan.database_scan, files),
    )


def _filter_runtime_scan(runtime_scan, files: set[str]):
    if runtime_scan is None:
        return None
    return dataclasses.replace(
        runtime_scan,
        tasks=_filter_by_attr(runtime_scan.tasks, files, "file_path"),
        schedulers=_filter_by_attr(runtime_scan.schedulers, files, "file_path"),
        realtime_consumers=_filter_by_attr(runtime_scan.realtime_consumers, files, "file_path"),
    )


def make_sub_scan(scan: RepoScan, unit: PlanningUnit) -> RepoScan:
    """Project a `RepoScan` down to the files owned by `unit`.

    Never mutates `scan`; returns a new `RepoScan` with every file-scoped
    field filtered to `unit.files` — including every Phase-2 enrichment
    record (endpoint bundles, integration identities, artifact/database/
    runtime scans, graphql interfaces, knex artifacts, research contexts,
    the semantic token cache, config impacts, debug signals, flow
    candidates, and service boundaries), so local planning for this unit
    never sees, and can never claim ownership of, another unit's evidence.
    `call_graph` is dropped rather than filtered — it's a whole-repo
    structure with no cheap per-unit projection, and local planning never
    legitimately needs another unit's call edges. `languages` is recomputed
    from this unit's own files rather than carried over from the global
    scan. `scan_timings`/`planner_timings` are reset to fresh dicts so
    concurrent units never share (and silently clobber) the same mutable
    timing dict.
    """
    files = set(unit.files)
    unit_dirs = _unit_dirs(files)

    file_tree: dict[str, list[str]] = {}
    for directory, names in scan.file_tree.items():
        kept = [
            name
            for name in names
            if f"{directory}/{name}" in files or (not directory and name in files)
        ]
        if kept:
            file_tree[directory] = kept

    api_endpoints = [
        ep for ep in scan.api_endpoints if set(endpoint_owned_files(ep)) & files
    ]

    return dataclasses.replace(
        scan,
        file_tree=file_tree,
        file_summaries=_filter_dict(scan.file_summaries, files),
        file_line_counts=_filter_dict(scan.file_line_counts, files),
        parsed_files=_filter_dict(scan.parsed_files, files),
        file_contents=_filter_dict(scan.file_contents, files),
        file_content_hashes=_filter_dict(scan.file_content_hashes, files),
        source_kind_by_file=_filter_dict(scan.source_kind_by_file, files),
        file_frameworks=_filter_dict(scan.file_frameworks, files),
        entry_points=_filter_list(scan.entry_points, files, unit_dirs),
        config_files=_filter_list(scan.config_files, files, unit_dirs),
        api_endpoints=api_endpoints,
        giant_file_clusters=_filter_dict(scan.giant_file_clusters, files),
        doc_contexts=_filter_dict(scan.doc_contexts, files),
        topology_map=_filter_topology_map(scan.topology_map, files),
        total_files=len(files),
        file_services=_filter_dict(scan.file_services, files),
        scan_scope=_filter_list(scan.scan_scope, files, unit_dirs) if scan.scan_scope else [],
        languages=_languages_for_files(files),
        call_graph=None,
        endpoint_bundles=_filter_by_attr(scan.endpoint_bundles, files, "handler_file"),
        integration_identities=_filter_by_list_attr(scan.integration_identities, files, "files"),
        artifact_scan=_filter_artifact_scan(scan.artifact_scan, files),
        runtime_scan=_filter_runtime_scan(scan.runtime_scan, files),
        graphql_interfaces=_filter_by_attr(scan.graphql_interfaces, files, "file_path"),
        knex_artifacts=_filter_by_attr(scan.knex_artifacts, files, "file_path"),
        research_contexts=_filter_research_contexts(scan.research_contexts, files),
        semantic_file_token_cache=_filter_dict(scan.semantic_file_token_cache, files),
        config_impacts=_filter_config_impacts(scan.config_impacts, files),
        debug_signals=_filter_debug_signals(scan.debug_signals, files),
        flow_candidates=_filter_by_list_attr(scan.flow_candidates, files, "involved_files"),
        service_boundaries=_filter_service_boundaries(scan.service_boundaries, files),
        scan_timings={},
        planner_timings={},
    )


def _deepest_path_groups(files: tuple[str, ...]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for f in files:
        key = f.rsplit("/", 1)[0] if "/" in f else f
        groups.setdefault(key, []).append(f)
    return groups


def _pack_groups(groups: dict[str, list[str]], max_files: int) -> list[list[str]]:
    """Greedily pack directory groups into chunks of up to `max_files` each,
    largest-fitting-first, instead of leaving every leaf directory as its
    own singleton part. A repo where every file happens to live in its own
    leaf directory (e.g. `module_00/component_00/handler.py` per file)
    would otherwise explode straight to one-file units the moment any
    directory fits under `max_files` — which is *every* directory, since
    each one only has a single file. Packing keeps parts close to
    `max_files` in size, only falling below that when a directory's own
    files don't divide evenly.
    """
    chunks: list[list[str]] = []
    current: list[str] = []
    for key in sorted(groups):
        group_files = sorted(groups[key])
        if len(group_files) > max_files:
            if current:
                chunks.append(current)
                current = []
            for i in range(0, len(group_files), max_files):
                chunks.append(group_files[i : i + max_files])
            continue
        if current and len(current) + len(group_files) > max_files:
            chunks.append(current)
            current = list(group_files)
        else:
            current.extend(group_files)
    if current:
        chunks.append(current)
    return chunks


def split_planning_unit(unit: PlanningUnit, max_files: int) -> list[PlanningUnit]:
    """Split an over-budget unit deterministically so each part fits.

    Groups by the deepest shared directory, then greedily packs those
    groups into `max_files`-sized parts (`_pack_groups`) — preferring the
    largest parts that still fit, not exploding straight to one file per
    leaf directory. Falls back to plain numbered chunks only when every
    file already shares one flat directory (path grouping can't separate
    them at all). `max_files` is a cheap seed for how the split is shaped —
    `bound_planning_unit` (or, for a real overflow rather than the
    preflight guess, the orchestration layer's retry loop) is what actually
    proves each resulting part fits the real model budget.
    """
    if len(unit.files) <= max_files:
        return [unit]

    groups = _deepest_path_groups(unit.files)
    if len(groups) > 1:
        chunks = _pack_groups(groups, max_files)
        if len(chunks) > 1:
            return [
                PlanningUnit(
                    slug=f"{unit.slug}/part-{i + 1}",
                    label=f"{unit.label} part {i + 1}",
                    files=tuple(chunk),
                )
                for i, chunk in enumerate(chunks)
            ]

    # ponytail: path grouping couldn't separate a flat directory; numbered
    # chunks are a fine terminal fallback since they're still deterministic.
    sorted_files = tuple(sorted(unit.files))
    chunks = [
        sorted_files[i : i + max_files] for i in range(0, len(sorted_files), max_files)
    ]
    return [
        PlanningUnit(
            slug=f"{unit.slug}/part-{i + 1}",
            label=f"{unit.label} part {i + 1}",
            files=chunk,
        )
        for i, chunk in enumerate(chunks)
    ]


def next_split(unit: PlanningUnit, max_files_seed_cap: int = 0) -> list[PlanningUnit]:
    """One splitting attempt for `unit`: seed = half its files (capped by
    `max_files_seed_cap` if set), via `split_planning_unit`; forces a plain
    numbered bisection if that didn't actually reduce it. Shared by
    `bound_planning_unit` (the cheap preflight-driven optimization) and the
    orchestration layer's real retry-on-`UnitNeedsSplit` loop, so both
    split the same way.
    """
    seed = max(1, len(unit.files) // 2)
    if max_files_seed_cap > 0:
        seed = min(seed, max_files_seed_cap)
    parts = split_planning_unit(unit, max_files=seed)
    if len(parts) == 1:
        sorted_files = tuple(sorted(unit.files))
        half = len(sorted_files) // 2
        parts = [
            PlanningUnit(slug=f"{unit.slug}/part-1", label=f"{unit.label} part 1", files=sorted_files[:half]),
            PlanningUnit(slug=f"{unit.slug}/part-2", label=f"{unit.label} part 2", files=sorted_files[half:]),
        ]
    return parts


def _propose_required_text(scan: RepoScan) -> str:
    # Local import: avoids a module-load-order cycle between .utils and
    # .partitioning (both are imported by engine.py, not by each other).
    from .utils import _build_named_clusters_str

    return _build_named_clusters_str({}, scan)


def _assign_required_text(scan: RepoScan) -> str:
    files = sorted(
        f for f in scan.file_summaries if classify_source_kind(f) == "product"
    )
    return "\n".join(f"- {f}" for f in files)


def unit_likely_fits_budget(scan: RepoScan, llm) -> bool:
    """Cheap, conservative PREFLIGHT GUESS — not a guarantee.

    This is an optimization only: it renders an approximation of the real
    required PROPOSE (`_build_named_clusters_str`'s graceful-degradation
    branch, since classify hasn't run yet) and ASSIGN (every product-kind
    file — the worst case before topology preassignment can shrink it)
    sections, counts them with the real tokenizer, and pads by a fixed
    constant for prompt-template text this approximation doesn't render
    (`_TEMPLATE_OVERHEAD_TOKENS`) — but the ASSIGN bucket JSON is
    proposal-dependent and genuinely cannot be known before PROPOSE runs,
    so this can still be wrong in both directions.

    Use it to avoid obviously-oversized units ever reaching classify/
    propose/assign. The actual guarantee — no LLM request is ever sent for
    a required section that doesn't fit — comes from catching
    `UnitNeedsSplit`, raised at the real `fit_prompt_sections` call sites in
    `_plan_local`, and splitting/retrying just the failing unit. Never treat
    a `True` result here as proof; only the real call site's success is
    proof.
    """
    from ..llm import build_prompt_budget, count_message_tokens
    from .common import ASSIGN_SYSTEM, PROPOSE_SYSTEM

    capabilities = llm.capabilities
    budget = build_prompt_budget(
        capabilities, output_reserve_tokens=getattr(llm, "output_reserve_tokens", None)
    )
    maximum_input = (
        budget.context_window_tokens - budget.output_reserve_tokens - budget.safety_tokens
    )

    propose_tokens, _ = count_message_tokens(
        PROPOSE_SYSTEM, _propose_required_text(scan), capabilities
    )
    assign_tokens, _ = count_message_tokens(
        ASSIGN_SYSTEM, _assign_required_text(scan), capabilities
    )
    worst = max(propose_tokens, assign_tokens) + _TEMPLATE_OVERHEAD_TOKENS
    return worst <= maximum_input


# Circuit breaker against pathological fragmentation: each recursion level
# at minimum halves the file count, so this bounds a unit to at most
# 2**_MAX_SPLIT_DEPTH parts — far past any realistic repo — rather than
# fragmenting indefinitely if splitting somehow stalls.
_MAX_SPLIT_DEPTH = 16


def bound_planning_unit(
    unit: PlanningUnit, scan: RepoScan, llm, *, max_files_seed_cap: int = 0, _depth: int = 0
) -> list[PlanningUnit]:
    """Recursively split `unit` until every part likely fits the model budget.

    This is the cheap preflight optimization (`unit_likely_fits_budget`) —
    it avoids ever sending an obviously-oversized unit to `_plan_local` in
    the first place, using `next_split` to shape each attempt. It is NOT
    the real guarantee: `unit_likely_fits_budget` can still be wrong (the
    ASSIGN bucket JSON is proposal-dependent), so callers must still catch
    `UnitNeedsSplit` around the actual `_plan_local` call and retry — see
    `plan_docs`/`_plan_unit_with_retry` in engine.py.

    A single indivisible file that still doesn't likely fit is returned
    with `coarse=True` instead of looping forever or ever being handed to
    the LLM. `_depth` backstops pathological fragmentation (`_MAX_SPLIT_DEPTH`).
    """
    if unit_likely_fits_budget(make_sub_scan(scan, unit), llm):
        return [unit]
    if len(unit.files) <= 1 or _depth >= _MAX_SPLIT_DEPTH:
        return [dataclasses.replace(unit, coarse=True)]

    parts = next_split(unit, max_files_seed_cap)
    result: list[PlanningUnit] = []
    for part in parts:
        assert len(part.files) < len(unit.files), "split must make progress"
        result.extend(
            bound_planning_unit(
                part, scan, llm, max_files_seed_cap=max_files_seed_cap, _depth=_depth + 1
            )
        )
    return result


class UnitNeedsSplit(ModelCapabilityError):
    """Raised from `_plan_local` when a specific unit's real required prompt
    (at classify/propose/assign) exceeds the model budget.

    `unit_likely_fits_budget`/`bound_planning_unit` are only a preflight
    guess — the ASSIGN bucket JSON in particular is proposal-dependent and
    cannot be known before PROPOSE runs, so a unit that passed the preflight
    can still genuinely overflow. This is the real, runtime-verified
    signal: it carries enough context (the failing unit and which step) for
    the orchestration layer to split just that unit and retry, instead of
    failing the whole repo. Subclasses `ModelCapabilityError` so existing
    `except ModelCapabilityError` call sites keep working unchanged.
    """

    def __init__(self, unit: PlanningUnit, step: str, message: str = "") -> None:
        self.unit = unit
        self.step = step
        super().__init__(message or f"unit '{unit.slug}' overflowed the model budget at step '{step}'")


__all__ = [
    "PlanningUnit",
    "UnitNeedsSplit",
    "build_planning_units",
    "make_sub_scan",
    "split_planning_unit",
    "next_split",
    "unit_likely_fits_budget",
    "bound_planning_unit",
]
