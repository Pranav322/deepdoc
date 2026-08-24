"""Deterministic per-service planning units for bounded multi-unit planning.

Groups a large repo's files by `RepoScan.file_services` into bounded
`PlanningUnit`s so each can be planned independently and merged, instead of
sending the whole repo through one unbounded prompt.
"""

from __future__ import annotations

import dataclasses
import re

from ..v2_models import RepoScan, endpoint_owned_files
from .topology import TopologyMap

CORE_SLUG = "core"


@dataclasses.dataclass(frozen=True)
class PlanningUnit:
    """A bounded, independently plannable slice of the repo."""

    slug: str
    label: str
    files: tuple[str, ...] = ()


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
    single-unit parity path.
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
    clusters = [
        cluster
        for cluster in topology.clusters
        if any(f in files for f in cluster.all_files)
    ]
    return TopologyMap(
        clusters=clusters,
        file_indegree=_filter_dict(topology.file_indegree, files),
        file_call_depth=_filter_dict(topology.file_call_depth, files),
        file_cluster_id=_filter_dict(topology.file_cluster_id, files),
        foundational_files=[f for f in topology.foundational_files if f in files],
    )


def make_sub_scan(scan: RepoScan, unit: PlanningUnit) -> RepoScan:
    """Project a `RepoScan` down to the files owned by `unit`.

    Never mutates `scan`; returns a new `RepoScan` with every file-scoped
    field filtered to `unit.files`.
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
    back to stable numbered chunks.
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


__all__ = [
    "PlanningUnit",
    "build_planning_units",
    "make_sub_scan",
    "split_planning_unit",
]
