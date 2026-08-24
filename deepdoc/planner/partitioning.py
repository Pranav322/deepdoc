"""Deterministic per-service planning units for bounded multi-unit planning.

Groups a large repo's files by `RepoScan.file_services` into bounded
`PlanningUnit`s so each can be planned independently and merged, instead of
sending the whole repo through one unbounded prompt.
"""

from __future__ import annotations

import dataclasses
import posixpath
import re

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


def make_sub_scan(scan: RepoScan, unit: PlanningUnit) -> RepoScan:
    """Project a `RepoScan` down to the files owned by `unit`.

    Never mutates `scan`; returns a new `RepoScan` with every file-scoped
    field filtered to `unit.files`. `call_graph` is dropped rather than
    filtered — it's a whole-repo structure with no cheap per-unit
    projection, and local planning never legitimately needs another unit's
    call edges. `languages` is recomputed from this unit's own files rather
    than carried over from the global scan.
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
        planner_timings={},
    )


def _deepest_path_groups(files: tuple[str, ...]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for f in files:
        key = f.rsplit("/", 1)[0] if "/" in f else f
        groups.setdefault(key, []).append(f)
    return groups


def split_planning_unit(unit: PlanningUnit, max_files: int) -> list[PlanningUnit]:
    """Split an over-budget unit deterministically so each part fits.

    First tries grouping by the deepest shared directory. If that still
    leaves files ungrouped (e.g. everything in one flat directory), falls
    back to stable numbered chunks. `max_files` is a cheap seed for how the
    split is shaped — `bound_planning_unit` is what actually proves each
    resulting part fits the real model budget.
    """
    if len(unit.files) <= max_files:
        return [unit]

    groups = _deepest_path_groups(unit.files)
    if len(groups) > 1 and all(len(files) <= max_files for files in groups.values()):
        return [
            PlanningUnit(slug=key, label=key, files=tuple(sorted(groups[key])))
            for key in sorted(groups)
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


def unit_fits_model_budget(scan: RepoScan, llm) -> bool:
    """Exact-token pre-flight check for one unit's real required planner sections.

    This is the acceptance gate `bound_planning_unit` uses — never `max_files`
    alone. It renders the actual PROPOSE named-clusters representation
    (`_build_named_clusters_str`, the same function `_plan_local` calls; with
    no classify output yet this is exactly its graceful-degradation branch)
    and the actual ASSIGN all-files inventory (every product-kind file — the
    worst case before topology preassignment can shrink it), counts both
    with the real model tokenizer (`count_message_tokens`), and pads by a
    fixed constant for the PROPOSE/ASSIGN prompt template text that isn't
    part of either bare required section (see `_TEMPLATE_OVERHEAD_TOKENS`).
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


def bound_planning_unit(
    unit: PlanningUnit, scan: RepoScan, llm, *, max_files_seed_cap: int = 0
) -> list[PlanningUnit]:
    """Recursively split `unit` until every part fits the real model budget.

    `split_planning_unit` (deepest-path grouping, falling back to numbered
    chunks) seeds each split attempt; `unit_fits_model_budget` — the exact
    token gate, not the seed's file count — decides whether a part is done.
    A single indivisible file that still doesn't fit is returned with
    `coarse=True` instead of looping forever or ever being handed to the
    LLM: callers must plan a coarse unit as an explicit, deterministic
    placeholder bucket rather than a normal classify/propose/assign pass.

    `max_files_seed_cap` (from config `planning_unit_max_files_seed`, 0 =
    unset) only shapes the first split attempt's guess; it is never treated
    as proof a part fits — `unit_fits_model_budget` still gates every part.
    """
    if unit_fits_model_budget(make_sub_scan(scan, unit), llm):
        return [unit]
    if len(unit.files) <= 1:
        return [dataclasses.replace(unit, coarse=True)]

    seed = max(1, len(unit.files) // 2)
    if max_files_seed_cap > 0:
        seed = min(seed, max_files_seed_cap)
    parts = split_planning_unit(unit, max_files=seed)
    if len(parts) == 1:
        # The seed didn't actually reduce it (e.g. a two-file unit already
        # at max_files=1 but still grouped as one directory) — force a
        # numbered bisection so recursion always makes progress.
        sorted_files = tuple(sorted(unit.files))
        half = len(sorted_files) // 2
        parts = [
            PlanningUnit(slug=f"{unit.slug}/part-1", label=f"{unit.label} part 1", files=sorted_files[:half]),
            PlanningUnit(slug=f"{unit.slug}/part-2", label=f"{unit.label} part 2", files=sorted_files[half:]),
        ]

    result: list[PlanningUnit] = []
    for part in parts:
        result.extend(
            bound_planning_unit(part, scan, llm, max_files_seed_cap=max_files_seed_cap)
        )
    return result


__all__ = [
    "PlanningUnit",
    "build_planning_units",
    "make_sub_scan",
    "split_planning_unit",
    "unit_fits_model_budget",
    "bound_planning_unit",
]
