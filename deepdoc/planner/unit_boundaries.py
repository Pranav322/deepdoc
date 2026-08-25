"""Deterministic semantic refinement of Slice A planning units.

Uses only in-repo call-graph, topology, endpoint-bundle, runtime, and flow
evidence that already lives on `RepoScan` — no LLM calls, no GitNexus. Two responsibilities:

1. `refine_unit_ownership()` conservatively moves an *unclaimed* (`core`)
   file into exactly one named service unit when deterministic evidence has
   one unambiguous dominant affinity; ambiguous/weak files stay in `core`.
2. `compute_boundary_stubs()` aggregates a compact, bounded summary of one
   unit's relationship to every other unit — remote slug, direction,
   aggregate score/count, evidence kinds, and a handful of flow labels.
   Never remote file paths, symbol names, or raw graph edges.

See .hermes/plans/SLICE_B_SEMANTIC_UNITS_PLAN.md for the product contract.
"""

from __future__ import annotations

import dataclasses
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..v2_models import RepoScan
    from .partitioning import PlanningUnit

CORE_SLUG = "core"

# A `core` file must clear this raw affinity score before it is eligible to
# move into a single named unit.
_MIN_AFFINITY_SCORE = 3.0
# ...and the winning unit's score must be at least this many times the
# runner-up's score. A close call is ambiguous and stays in core rather than
# picking a marginal favorite.
_MIN_MARGIN_RATIO = 2.0

_CALL_EDGE_WEIGHT = 1.0
_CLUSTER_COMEMBERSHIP_WEIGHT = 5.0
_FLOW_COOCCURRENCE_WEIGHT = 2.0
# Endpoint/runtime evidence is an *independent* signal — flow candidates are
# optional and may not exist yet when refinement runs, so a service's own
# endpoint bundle or background task is the only evidence some helpers have.
# One such vote is exactly `_MIN_AFFINITY_SCORE`: sufficient on its own, but
# still subject to the margin rule, so two services claiming the same helper
# stays ambiguous and keeps it in core.
_ENDPOINT_EVIDENCE_WEIGHT = 3.0
_RUNTIME_PRODUCER_WEIGHT = 3.0

# Cross-unit boundary stub bounds — keep this compact and cheap to render in
# a local prompt, never an unbounded inventory.
_MAX_STUBS_PER_UNIT = 5
_MAX_FLOW_LABELS_PER_STUB = 3
_STUB_FLOW_WEIGHT = 3.0

# A flow label reaching a local prompt must be safe *by construction*, not by
# trusting the producer's formatting: `FlowCandidate.title` is built from
# arbitrary upstream text (`endpoint_family` can be `POST /orders/process`) and
# `flow_id` can be anything a caller passes. Only a short lowercase
# alnum/dash identifier is allowed through — no separators, no dots, so no
# path or file extension can survive.
_SAFE_FLOW_LABEL_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,47}")
# ...and reject a slugified path whose last segment is a source extension
# ("services-payments-app-py"), which would still echo a remote file.
_EXTENSION_TOKENS = frozenset(
    "py pyi ts tsx js jsx mjs cjs go rb java kt kts php rs cs c cc cpp h hpp "
    "swift scala m mm vue svelte sql yml yaml json toml".split()
)
_GENERIC_FLOW_LABEL = "flow"


@dataclasses.dataclass(frozen=True)
class BoundaryStub:
    """A compact, serializable summary of one unit's relationship to
    another. Deliberately excludes remote file paths, symbol names, and raw
    graph edges by construction — only a slug, a direction, aggregate
    counts, and a handful of flow labels ever reach a local planning
    prompt."""

    remote_unit: str
    direction: str  # "inbound" | "outbound" | "bidirectional"
    score: float
    call_count: int
    evidence_kinds: tuple[str, ...] = ()
    flow_labels: tuple[str, ...] = ()


def _local_call_edges(scan: "RepoScan") -> list[tuple[str, str]]:
    """(caller_file, callee_file) pairs for local, non-external call edges,
    sorted so aggregation never depends on graph insertion order.

    Deliberately NOT deduped to distinct file pairs: `CallGraph.serialize()`
    already collapses identical (file, symbol) edges, so a surviving
    duplicate file pair here means multiple distinct call sites/symbols
    between the same two files — that multiplicity is real affinity signal
    strength, not noise.
    """
    if scan.call_graph is None:
        return []
    from ..call_graph import CALL_KIND_EXTERNAL

    pairs: list[tuple[str, str]] = []
    for edge in scan.call_graph.serialize()["edges"]:
        if edge["call_kind"] == CALL_KIND_EXTERNAL:
            continue
        caller, callee = edge["caller_file"], edge["callee_file"]
        if caller and callee and caller != callee:
            pairs.append((caller, callee))
    return sorted(pairs)


def _safe_flow_label(flow_id: str) -> str:
    """A prompt-safe label for one flow, derived only from its stable ID.

    Titles are dropped entirely — see `_SAFE_FLOW_LABEL_RE`. Anything that
    isn't a plain short identifier degrades to a generic label rather than
    risking a remote path in a local prompt.
    """
    candidate = (flow_id or "").strip().lower()
    if not _SAFE_FLOW_LABEL_RE.fullmatch(candidate):
        return _GENERIC_FLOW_LABEL
    if candidate.rsplit("-", 1)[-1] in _EXTENSION_TOKENS:
        return _GENERIC_FLOW_LABEL
    return candidate


def _flow_file_groups(scan: "RepoScan") -> list[tuple[str, frozenset[str]]]:
    """(flow_id, involved_files) pairs, sorted for determinism. Titles are
    deliberately not carried — nothing derived from a title may reach a
    local prompt (see `_safe_flow_label`)."""
    groups = [
        (flow.flow_id, frozenset(flow.involved_files))
        for flow in (scan.flow_candidates or [])
        if flow.involved_files
    ]
    return sorted(groups, key=lambda g: (g[0], sorted(g[1])))


def _sole_owner(
    file_path: str, unit_files: dict[str, frozenset[str]]
) -> str | None:
    """The named unit owning `file_path`, or None when unclaimed. Units are
    disjoint by construction, so "exactly one" needs no tie-breaking."""
    if not file_path:
        return None
    for slug in sorted(unit_files):
        if file_path in unit_files[slug]:
            return slug
    return None


def _endpoint_affinity(
    scan: "RepoScan", unit_files: dict[str, frozenset[str]]
) -> dict[str, dict[str, float]]:
    """Votes from `scan.endpoint_bundles`: file -> {slug: score}.

    A bundle only votes when its `handler_file` is anchored to exactly one
    named unit *and* none of its own bounded `evidence` files belong to a
    different named unit (a bundle spanning services is ambiguous, so it
    stays silent). Only the bundle's real `EvidenceUnit.file_path` entries
    are used — never text inferred from `endpoint_family`/`methods_paths`.
    """
    affinity: dict[str, dict[str, float]] = {}
    bundles = sorted(
        scan.endpoint_bundles or [],
        key=lambda b: (
            getattr(b, "endpoint_family", "") or "",
            getattr(b, "handler_file", "") or "",
        ),
    )
    for bundle in bundles:
        handler = getattr(bundle, "handler_file", "") or ""
        anchor = _sole_owner(handler, unit_files)
        if anchor is None:
            continue
        evidence_files = sorted(
            {
                getattr(unit, "file_path", "") or ""
                for unit in (getattr(bundle, "evidence", None) or [])
            }
            - {"", handler}
        )
        owners = {_sole_owner(f, unit_files) for f in evidence_files}
        if owners - {None, anchor}:
            continue
        for f in evidence_files:
            if _sole_owner(f, unit_files) is not None:
                continue
            bucket = affinity.setdefault(f, {})
            bucket[anchor] = bucket.get(anchor, 0.0) + _ENDPOINT_EVIDENCE_WEIGHT
    return affinity


def _runtime_affinity(
    scan: "RepoScan", unit_files: dict[str, frozenset[str]]
) -> dict[str, dict[str, float]]:
    """Votes from `scan.runtime_scan`: file -> {slug: score}.

    Only `RuntimeTask.producer_files` is used: it is the one bounded
    dependent-*file* list the live runtime model carries.
    `RuntimeScheduler.invoked_targets` holds task/symbol names (not files)
    and `RealtimeConsumer` only names its own `file_path`, so neither can
    identify a bounded dependent file and neither votes. `linked_endpoints`
    is likewise endpoint names, not files.

    `scan.entry_points` is a flat list of entry *files* with no dependent
    files attached, so it can only re-state ownership that `file_services`
    already anchors — it adds no independent evidence and is not used.
    """
    tasks = sorted(
        getattr(scan.runtime_scan, "tasks", None) or [],
        key=lambda t: (getattr(t, "name", "") or "", getattr(t, "file_path", "") or ""),
    )
    affinity: dict[str, dict[str, float]] = {}
    for task in tasks:
        anchor = _sole_owner(getattr(task, "file_path", "") or "", unit_files)
        if anchor is None:
            continue
        producers = sorted(
            {p for p in (getattr(task, "producer_files", None) or []) if p}
        )
        owners = {_sole_owner(p, unit_files) for p in producers}
        if owners - {None, anchor}:
            continue
        for p in producers:
            if _sole_owner(p, unit_files) is not None:
                continue
            bucket = affinity.setdefault(p, {})
            bucket[anchor] = bucket.get(anchor, 0.0) + _RUNTIME_PRODUCER_WEIGHT
    return affinity


def refine_unit_ownership(
    scan: "RepoScan", units: list["PlanningUnit"]
) -> list["PlanningUnit"]:
    """Conservatively attach unclaimed (`core`) files to one named unit when
    deterministic evidence has a single unambiguous dominant affinity.

    No-op unless there are 2+ named units and a non-empty `core` unit
    exists — the single-unit parity path never reaches here. Never moves a
    file `scan.file_services` already assigns to a named service; that
    ownership is a hard anchor. Never force-assigns a topology-foundational
    file merely because it has high fan-in — those stay shared/core.
    """
    named = {u.slug: u for u in units if u.slug != CORE_SLUG}
    core = next((u for u in units if u.slug == CORE_SLUG), None)
    if len(named) < 2 or core is None or not core.files:
        return units

    topology = scan.topology_map
    foundational = set(getattr(topology, "foundational_files", []) or [])
    cluster_of: dict[str, str] = dict(getattr(topology, "file_cluster_id", {}) or {})
    unit_clusters = {
        slug: {cluster_of[f] for f in unit.files if f in cluster_of}
        for slug, unit in named.items()
    }
    unit_files = {slug: frozenset(unit.files) for slug, unit in named.items()}
    call_edges = _local_call_edges(scan)
    flow_groups = _flow_file_groups(scan)
    endpoint_affinity = _endpoint_affinity(scan, unit_files)
    runtime_affinity = _runtime_affinity(scan, unit_files)

    # file -> {slug: incident local call-edge count, either direction}
    call_affinity: dict[str, dict[str, float]] = {}
    for caller, callee in call_edges:
        for endpoint, other in ((caller, callee), (callee, caller)):
            for slug, files in unit_files.items():
                if other in files:
                    bucket = call_affinity.setdefault(endpoint, {})
                    bucket[slug] = bucket.get(slug, 0.0) + _CALL_EDGE_WEIGHT

    # file -> {slug: flow co-occurrence count}
    flow_affinity: dict[str, dict[str, float]] = {}
    for _flow_id, files in flow_groups:
        for f in files:
            for slug, unit_fset in unit_files.items():
                if unit_fset & (files - {f}):
                    bucket = flow_affinity.setdefault(f, {})
                    bucket[slug] = bucket.get(slug, 0.0) + _FLOW_COOCCURRENCE_WEIGHT

    reassignments: dict[str, str] = {}
    for f in sorted(core.files):
        if f in foundational:
            continue
        scores: dict[str, float] = {}
        for slug in sorted(named):
            score = call_affinity.get(f, {}).get(slug, 0.0)
            score += flow_affinity.get(f, {}).get(slug, 0.0)
            score += endpoint_affinity.get(f, {}).get(slug, 0.0)
            score += runtime_affinity.get(f, {}).get(slug, 0.0)
            if cluster_of.get(f) and cluster_of[f] in unit_clusters.get(slug, set()):
                score += _CLUSTER_COMEMBERSHIP_WEIGHT
            if score:
                scores[slug] = score
        if not scores:
            continue
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        winner_slug, winner_score = ranked[0]
        runner_up_score = ranked[1][1] if len(ranked) > 1 else 0.0
        if winner_score < _MIN_AFFINITY_SCORE:
            continue
        if runner_up_score and winner_score < runner_up_score * _MIN_MARGIN_RATIO:
            continue
        reassignments[f] = winner_slug

    if not reassignments:
        return units

    remaining_core = sorted(set(core.files) - set(reassignments))
    refined: list["PlanningUnit"] = []
    for unit in units:
        if unit.slug == CORE_SLUG:
            refined.append(dataclasses.replace(unit, files=tuple(remaining_core)))
            continue
        added = sorted(f for f, slug in reassignments.items() if slug == unit.slug)
        if added:
            refined.append(
                dataclasses.replace(
                    unit, files=tuple(sorted(set(unit.files) | set(added)))
                )
            )
        else:
            refined.append(unit)
    return refined


def compute_boundary_stubs(
    scan: "RepoScan",
    unit_files: frozenset[str],
    own_baseline_slug: str,
    baseline_unit_files: dict[str, frozenset[str]],
) -> tuple[BoundaryStub, ...]:
    """Aggregate compact, bounded cross-unit evidence for `unit_files`
    against every other baseline unit.

    Recomputed fresh from `unit_files` every call — a unit produced by
    splitting (`next_split`/`bound_planning_unit`, or a runtime
    `UnitNeedsSplit` retry) gets stubs for exactly its own child files,
    never a stale copy of its parent's aggregate. `own_baseline_slug` is the
    pre-split unit slug (see partitioning's `slug/part-N` convention) so a
    split unit is never compared against its own siblings.
    """
    others = {
        slug: files
        for slug, files in baseline_unit_files.items()
        if slug != own_baseline_slug and files
    }
    if not unit_files or not others:
        return ()

    call_edges = _local_call_edges(scan)
    flow_groups = _flow_file_groups(scan)

    outbound: dict[str, int] = {slug: 0 for slug in others}
    inbound: dict[str, int] = {slug: 0 for slug in others}
    for caller, callee in call_edges:
        if caller in unit_files:
            for slug, files in others.items():
                if callee in files:
                    outbound[slug] += 1
        if callee in unit_files:
            for slug, files in others.items():
                if caller in files:
                    inbound[slug] += 1

    flow_hits: dict[str, list[str]] = {slug: [] for slug in others}
    for flow_id, files in flow_groups:
        if not (unit_files & files):
            continue
        for slug, other_files in others.items():
            if other_files & files:
                flow_hits[slug].append(_safe_flow_label(flow_id))

    stubs: list[BoundaryStub] = []
    for slug in sorted(others):
        out_count = outbound[slug]
        in_count = inbound[slug]
        hits = sorted(set(flow_hits[slug]))
        score = float(out_count + in_count) + len(flow_hits[slug]) * _STUB_FLOW_WEIGHT
        if score <= 0:
            continue
        if out_count and in_count:
            direction = "bidirectional"
        elif out_count:
            direction = "outbound"
        elif in_count:
            direction = "inbound"
        else:
            direction = "bidirectional"
        evidence_kinds = tuple(
            kind
            for kind, present in (
                ("call", bool(out_count or in_count)),
                ("flow", bool(flow_hits[slug])),
            )
            if present
        )
        stubs.append(
            BoundaryStub(
                remote_unit=slug,
                direction=direction,
                score=score,
                call_count=out_count + in_count,
                evidence_kinds=evidence_kinds,
                flow_labels=tuple(hits[:_MAX_FLOW_LABELS_PER_STUB]),
            )
        )

    stubs.sort(key=lambda s: (-s.score, s.remote_unit))
    return tuple(stubs[:_MAX_STUBS_PER_UNIT])


def format_boundary_stubs(stubs: tuple[BoundaryStub, ...]) -> str:
    """Compact, human-readable rendering for the local planning prompt's
    optional cross-unit context section. Contains only what `BoundaryStub`
    itself carries — no remote file paths."""
    if not stubs:
        return ""
    lines = []
    for stub in stubs:
        kinds = ", ".join(stub.evidence_kinds) or "none"
        line = (
            f"- {stub.remote_unit}: {stub.direction}, score={stub.score:.1f}, "
            f"calls={stub.call_count}, evidence=[{kinds}]"
        )
        if stub.flow_labels:
            line += f", flows=[{', '.join(stub.flow_labels)}]"
        lines.append(line)
    return "\n".join(lines)


__all__ = [
    "BoundaryStub",
    "refine_unit_ownership",
    "compute_boundary_stubs",
    "format_boundary_stubs",
]
