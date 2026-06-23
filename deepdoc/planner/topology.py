"""Topology analysis — derives nav structure from the call graph without LLM.

Computes per-file metrics (indegree, call_depth) and groups files into
topology clusters using BFS from entry points + Jaccard-based merging.

The resulting TopologyMap drives:
  - Nav section ordering  (entry-point clusters first, foundational last)
  - LLM classify context  (clusters replace the compressed file-tree blob)
  - Flow embedding        (call chain attached to owning cluster's bucket)
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..v2_models import RepoScan

from ..call_graph import CALL_KIND_CELERY, CALL_KIND_EVENT, CALL_KIND_EXTERNAL, CALL_KIND_SIGNAL

_SIDE_EFFECT_KINDS = {CALL_KIND_CELERY, CALL_KIND_SIGNAL, CALL_KIND_EVENT}

# Files called by >= this fraction of all repo files are "foundational".
# Lower fraction = more files treated as shared infra (excluded from cluster
# bodies), which prevents a single BaseController / db.py from gluing every
# cluster together. See docs/planner_tuning.md.
_FOUNDATIONAL_FRACTION = 0.05

# BFS depth cap when assigning files to clusters. Shallower depth stops a
# cluster from sweeping the whole call graph from an entry point — a
# controller no longer drags in everything 9 layers deep. See
# docs/planner_tuning.md.
_MAX_CLUSTER_DEPTH = 4

# Jaccard threshold for merging two clusters. Higher threshold = clusters
# stay separate unless they have substantial file overlap (was 0.40, which
# was merging weakly-related clusters via shared utility files). See
# docs/planner_tuning.md.
_MERGE_JACCARD = 0.60

# Two clusters whose cross-call ratio exceeds this threshold merge even when
# their file-Jaccard is low. Prevents tightly coupled micro-clusters from
# getting separate doc pages.
_CROSS_EDGE_DENSITY = 0.35


@dataclass
class TopologyCluster:
    """A group of repo files that form a cohesive functional unit."""

    cluster_id: str
    entry_files: list[str]       # files at call_depth == 0 (entry points)
    entry_symbols: list[str]     # key handler/task symbols in entry files
    all_files: list[str]         # every file owned by this cluster
    min_depth: int               # shallowest call_depth among owned files
    max_depth: int               # deepest call_depth among owned files
    side_effects: list[str]      # celery/signal/event dispatches within cluster
    external_calls: list[str]    # external service names called within cluster
    shared_dep_files: list[str]  # foundational files this cluster calls into
    avg_indegree: float          # mean indegree of owned files
    is_foundational: bool        # True for the shared-infrastructure cluster


@dataclass
class TopologyMap:
    """Complete topology analysis of a repository."""

    clusters: list[TopologyCluster]
    file_indegree: dict[str, int]
    file_call_depth: dict[str, int]
    file_cluster_id: dict[str, str]
    foundational_files: list[str]

    def cluster_for_file(self, file_path: str) -> TopologyCluster | None:
        cid = self.file_cluster_id.get(file_path)
        if not cid:
            return None
        return next((c for c in self.clusters if c.cluster_id == cid), None)

    def nav_ordered_clusters(self) -> list[TopologyCluster]:
        """Clusters in nav order: entry-point-first, foundational last."""
        return list(self.clusters)  # already sorted by build_topology_map


def build_topology_map(scan: "RepoScan") -> TopologyMap:
    """Derive a nav-driving topology from the call graph and scan data.

    Returns an empty TopologyMap when no call graph is available so callers
    can fall back gracefully (flat repos keep the existing heuristic flow).
    """
    cg = scan.call_graph
    repo_files = set(scan.file_summaries.keys())
    if not cg or not repo_files:
        return _empty_map()

    # ── 1. Build file-level call maps in one pass over all edges ─────────
    # file_calls:   caller_file → {callee_file, ...}
    # file_called_by: callee_file → {caller_file, ...}  (for indegree)
    # file_side_effects:  file → ["{kind}:{symbol}", ...]
    # file_external_calls: file → [symbol, ...]
    file_calls: dict[str, set[str]] = defaultdict(set)
    file_called_by: dict[str, set[str]] = defaultdict(set)
    file_side_effects: dict[str, list[str]] = defaultdict(list)
    file_external_calls: dict[str, list[str]] = defaultdict(list)

    for caller_key, edges in cg._callees.items():
        caller_file = caller_key.split("::")[0] if "::" in caller_key else caller_key
        if caller_file not in repo_files:
            continue
        for edge in edges:
            callee_file = edge.callee_file or ""
            if callee_file and callee_file in repo_files and callee_file != caller_file:
                file_calls[caller_file].add(callee_file)
                file_called_by[callee_file].add(caller_file)

            if edge.call_kind in _SIDE_EFFECT_KINDS and edge.callee_symbol:
                file_side_effects[caller_file].append(
                    f"{edge.call_kind}:{edge.callee_symbol}"
                )
            elif edge.call_kind == CALL_KIND_EXTERNAL and edge.callee_symbol:
                file_external_calls[caller_file].append(edge.callee_symbol)

    # ── 2. Per-file indegree (distinct caller-file count) ────────────────
    file_indegree: dict[str, int] = {
        f: len(file_called_by.get(f, set())) for f in repo_files
    }

    # ── 3. Foundational files ─────────────────────────────────────────────
    # Augment call indegree with import indegree so that heavily-imported files
    # (models.py, constants.py, exceptions.py) are treated as foundational even
    # when they have few direct call-graph edges.
    import_indegree, file_imports = _build_import_maps(scan, repo_files)
    effective_indegree = {
        f: max(file_indegree.get(f, 0), import_indegree.get(f, 0))
        for f in repo_files
    }
    threshold = max(3, int(len(repo_files) * _FOUNDATIONAL_FRACTION))
    foundational_set = {f for f, deg in effective_indegree.items() if deg >= threshold}

    # ── 4. Entry-point files ──────────────────────────────────────────────
    entry_point_files: set[str] = set()

    if scan.endpoint_bundles:
        for bundle in scan.endpoint_bundles:
            if bundle.handler_file and bundle.handler_file in repo_files:
                entry_point_files.add(bundle.handler_file)

    if scan.runtime_scan:
        for task in scan.runtime_scan.tasks:
            if task.file_path and task.file_path in repo_files:
                entry_point_files.add(task.file_path)
        for scheduler in scan.runtime_scan.schedulers:
            if scheduler.file_path and scheduler.file_path in repo_files:
                entry_point_files.add(scheduler.file_path)

    for ep in scan.entry_points:
        if ep in repo_files:
            entry_point_files.add(ep)

    # Indegree-0 non-foundational, non-test files as fallback entry points
    for f, deg in file_indegree.items():
        if deg == 0 and f not in foundational_set and not _is_test_file(f):
            entry_point_files.add(f)

    # ── 5. BFS to assign call_depth from entry points ────────────────────
    file_call_depth: dict[str, int] = {}
    bfs: deque[tuple[str, int]] = deque()
    for f in sorted(entry_point_files):
        if f not in file_call_depth:
            file_call_depth[f] = 0
            bfs.append((f, 0))

    while bfs:
        current, depth = bfs.popleft()
        for callee in sorted(file_calls.get(current, set())):
            if callee not in file_call_depth:
                file_call_depth[callee] = depth + 1
                bfs.append((callee, depth + 1))

    for f in repo_files:
        if f not in file_call_depth:
            file_call_depth[f] = 999  # unreachable from any entry point

    # ── 6. Assign files to clusters via BFS from entry points ────────────
    file_cluster_id: dict[str, str] = {}
    proto: dict[str, set[str]] = {}

    bfs = deque()
    for f in sorted(entry_point_files):
        if f in foundational_set:
            continue
        cid = _path_to_cluster_id(f)
        # Disambiguate truncation collisions: if this slug already belongs to a
        # different entry point's cluster, append a counter suffix.
        _base = cid
        _counter = 1
        while cid in proto and f not in proto[cid]:
            cid = f"{_base[:58]}-{_counter}"
            _counter += 1
        if cid not in proto:
            proto[cid] = set()
        file_cluster_id[f] = cid
        proto[cid].add(f)
        bfs.append((f, cid, 0))

    while bfs:
        current, cid, depth = bfs.popleft()
        if depth >= _MAX_CLUSTER_DEPTH:
            continue
        for callee in sorted(file_calls.get(current, set())):
            if callee in foundational_set or callee in file_cluster_id:
                continue
            file_cluster_id[callee] = cid
            proto[cid].add(callee)
            bfs.append((callee, cid, depth + 1))

    # Files not reached by any entry-point BFS (but not foundational):
    # assign to the cluster whose owned files they have the most calls with
    unassigned = [
        f for f in repo_files
        if f not in file_cluster_id and f not in foundational_set
    ]
    for f in sorted(unassigned):
        best_cid = _best_cluster_for_orphan(
            f, file_calls, file_called_by, proto, file_imports
        )
        if best_cid:
            file_cluster_id[f] = best_cid
            proto[best_cid].add(f)
        elif proto:
            fallback = max(proto, key=lambda c: len(proto[c]))
            file_cluster_id[f] = fallback
            proto[fallback].add(f)

    # ── 7. Merge high-overlap clusters ───────────────────────────────────
    merged = _merge_proto_clusters(proto, file_cluster_id, file_calls)

    # ── 8. Build TopologyCluster objects ─────────────────────────────────
    clusters: list[TopologyCluster] = []

    for cid, files in merged.items():
        entry_files = sorted(f for f in files if f in entry_point_files)
        entry_symbols: list[str] = []
        for ef in entry_files[:3]:
            pf = scan.parsed_files.get(ef)
            if pf and pf.symbols:
                entry_symbols.extend(s.name for s in pf.symbols[:4])

        side_effects: list[str] = []
        ext_calls: list[str] = []
        shared_deps: set[str] = set()

        for f in files:
            side_effects.extend(file_side_effects.get(f, []))
            ext_calls.extend(file_external_calls.get(f, []))
            for callee in file_calls.get(f, set()):
                if callee in foundational_set:
                    shared_deps.add(callee)

        depths = [file_call_depth.get(f, 999) for f in files]
        reachable = [d for d in depths if d < 999]
        min_d = min(reachable) if reachable else 999
        max_d = max(reachable) if reachable else 0
        avg_ind = sum(file_indegree.get(f, 0) for f in files) / max(len(files), 1)

        clusters.append(TopologyCluster(
            cluster_id=cid,
            entry_files=entry_files,
            entry_symbols=list(dict.fromkeys(entry_symbols))[:10],
            all_files=sorted(files),
            min_depth=min_d,
            max_depth=max_d,
            side_effects=sorted(set(side_effects)),
            external_calls=sorted(set(ext_calls)),
            shared_dep_files=sorted(shared_deps),
            avg_indegree=avg_ind,
            is_foundational=False,
        ))

    # ── 9. Foundational cluster ───────────────────────────────────────────
    if foundational_set:
        inf_files = sorted(foundational_set)
        avg_ind = sum(file_indegree.get(f, 0) for f in inf_files) / max(len(inf_files), 1)
        clusters.append(TopologyCluster(
            cluster_id="foundational",
            entry_files=[],
            entry_symbols=[],
            all_files=inf_files,
            min_depth=999,
            max_depth=0,
            side_effects=[],
            external_calls=[],
            shared_dep_files=[],
            avg_indegree=avg_ind,
            is_foundational=True,
        ))
        for f in foundational_set:
            file_cluster_id.setdefault(f, "foundational")

    # Sort: shallowest entry-point clusters first; foundational always last.
    # is_foundational as primary key makes the intent explicit (min_depth=999 is a proxy).
    clusters.sort(key=lambda c: (c.is_foundational, c.min_depth, -len(c.all_files)))

    return TopologyMap(
        clusters=clusters,
        file_indegree=file_indegree,
        file_call_depth=file_call_depth,
        file_cluster_id=file_cluster_id,
        foundational_files=sorted(foundational_set),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _empty_map() -> TopologyMap:
    return TopologyMap(
        clusters=[],
        file_indegree={},
        file_call_depth={},
        file_cluster_id={},
        foundational_files=[],
    )


def _merge_proto_clusters(
    proto: dict[str, set[str]],
    file_cluster_id: dict[str, str],
    file_calls: dict[str, set[str]] | None = None,
) -> dict[str, set[str]]:
    """Merge clusters whose file Jaccard overlap or cross-call density is high."""
    cluster_ids = list(proto.keys())
    parent: dict[str, str] = {}
    _fc = file_calls or {}

    def find(cid: str) -> str:
        while cid in parent:
            cid = parent[cid]
        return cid

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        # Keep the larger cluster as root
        if len(proto.get(ra, set())) >= len(proto.get(rb, set())):
            parent[rb] = ra
            proto[ra] = proto.get(ra, set()) | proto.pop(rb, set())
        else:
            parent[ra] = rb
            proto[rb] = proto.get(rb, set()) | proto.pop(ra, set())

    for i in range(len(cluster_ids)):
        for j in range(i + 1, len(cluster_ids)):
            ci, cj = find(cluster_ids[i]), find(cluster_ids[j])
            if ci == cj:
                continue
            si = proto.get(ci, set())
            sj = proto.get(cj, set())
            if not si or not sj:
                continue
            jaccard = len(si & sj) / len(si | sj)
            if jaccard >= _MERGE_JACCARD:
                union(ci, cj)
                continue
            # Also merge when cross-call traffic between the two clusters is dense
            cross = sum(1 for f in si for c in _fc.get(f, set()) if c in sj)
            cross += sum(1 for f in sj for c in _fc.get(f, set()) if c in si)
            if cross and cross / min(len(si), len(sj)) >= _CROSS_EDGE_DENSITY:
                union(ci, cj)

    # Re-assign file_cluster_id to canonical roots
    for f in list(file_cluster_id.keys()):
        file_cluster_id[f] = find(file_cluster_id[f])

    return {find(cid): files for cid, files in proto.items() if files}


def _build_import_maps(
    scan: "RepoScan",
    repo_files: set[str],
) -> tuple[dict[str, int], dict[str, set[str]]]:
    """Build import indegree and file→imported-files adjacency in one pass.

    Resolves relative and absolute imports to repo file paths; ignores
    third-party/stdlib. Returns (indegree, file_imports) where:
      - indegree[f] = number of distinct repo files that import f
      - file_imports[f] = set of repo files that f imports
    """
    indegree: dict[str, int] = defaultdict(int)
    file_imports: dict[str, set[str]] = defaultdict(set)

    _suffix_index: dict[str, list[str]] = defaultdict(list)
    for rp in repo_files:
        no_ext = re.sub(r"\.[^/]+$", "", rp)
        _suffix_index[no_ext].append(rp)
        _suffix_index[no_ext.replace("/", ".")].append(rp)

    import_re = re.compile(
        r"^(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.MULTILINE
    )

    for src_path, pf in scan.parsed_files.items():
        if src_path not in repo_files:
            continue
        pkg_dir = src_path.rsplit("/", 1)[0] if "/" in src_path else ""

        for imp_str in pf.imports:
            m = import_re.match(imp_str.strip())
            if not m:
                continue
            module = (m.group(1) or m.group(2) or "").strip()
            if not module:
                continue

            candidates: list[str] = []

            if module.startswith("."):
                dots = len(module) - len(module.lstrip("."))
                rel_mod = module[dots:].replace(".", "/")
                base = pkg_dir
                for _ in range(dots - 1):
                    base = base.rsplit("/", 1)[0] if "/" in base else ""
                rel_path = f"{base}/{rel_mod}".lstrip("/") if rel_mod else base
                for ext in (".py", "/__init__.py"):
                    candidates.append(rel_path + ext)
            else:
                as_path = module.replace(".", "/")
                for ext in (".py", "/__init__.py"):
                    candidates.append(as_path + ext)
                candidates.extend(_suffix_index.get(module, []))
                candidates.extend(_suffix_index.get(as_path, []))

            for candidate in candidates:
                if candidate in repo_files and candidate != src_path:
                    indegree[candidate] += 1
                    file_imports[src_path].add(candidate)
                    break

    return dict(indegree), dict(file_imports)


def _best_cluster_for_orphan(
    file_path: str,
    file_calls: dict[str, set[str]],
    file_called_by: dict[str, set[str]],
    proto: dict[str, set[str]],
    import_targets: dict[str, set[str]] | None = None,
) -> str | None:
    """Find the cluster an unassigned file has the most relationships with."""
    scores: dict[str, float] = defaultdict(float)
    cluster_file_index: dict[str, str] = {}
    for cid, files in proto.items():
        for f in files:
            cluster_file_index[f] = cid

    for callee in file_calls.get(file_path, set()):
        cid = cluster_file_index.get(callee)
        if cid:
            scores[cid] += 2  # weight outgoing calls more

    for caller in file_called_by.get(file_path, set()):
        cid = cluster_file_index.get(caller)
        if cid:
            scores[cid] += 1

    # Import edges provide a weaker signal than call edges
    for imp_target in (import_targets or {}).get(file_path, set()):
        cid = cluster_file_index.get(imp_target)
        if cid:
            scores[cid] += 0.5

    if not scores:
        return None
    return max(scores, key=lambda c: scores[c])


def _path_to_cluster_id(file_path: str) -> str:
    """Stable slug from a file path used as initial cluster ID."""
    slug = re.sub(r"[^a-z0-9]+", "-", file_path.lower()).strip("-")
    return slug[:64] or "cluster"


def _is_test_file(file_path: str) -> bool:
    lower = file_path.lower()
    return (
        "/tests/" in lower
        or "/test/" in lower
        or lower.startswith("test")
        or lower.endswith("_test.py")
        or lower.endswith("_spec.ts")
        or lower.endswith(".test.ts")
        or lower.endswith(".spec.ts")
        or lower.endswith(".test.js")
        or lower.endswith(".spec.js")
    )


__all__ = ["TopologyCluster", "TopologyMap", "build_topology_map"]
