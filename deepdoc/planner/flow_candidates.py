from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Iterable

from ..call_graph import (
    CALL_KIND_CELERY,
    CALL_KIND_EVENT,
    CALL_KIND_EXTERNAL,
    CALL_KIND_SIGNAL,
    CallEdge,
)
from ..scanner.common import EndpointBundle, RuntimeScan, RuntimeTask, RuntimeScheduler
from ..v2_models import RepoScan


_SIDE_EFFECT_KINDS = {CALL_KIND_CELERY, CALL_KIND_SIGNAL, CALL_KIND_EVENT}


@dataclass
class EntryPoint:
    kind: str
    label: str
    handler_file: str
    handler_symbol: str
    endpoint_family: str | None = None
    framework: str | None = None


@dataclass
class FlowCandidate:
    flow_id: str
    title: str
    entry_kind: str
    entry_points: list[EntryPoint]
    call_chain_edges: list[tuple[int, CallEdge]] = field(default_factory=list)
    involved_files: list[str] = field(default_factory=list)
    involved_symbols: list[str] = field(default_factory=list)
    external_touchpoints: list[str] = field(default_factory=list)
    side_effects: list[str] = field(default_factory=list)
    score: float = 0.0
    evidence: dict[str, Any] = field(default_factory=dict)


def build_flow_candidates(
    scan: RepoScan,
    *,
    max_depth: int = 4,
    max_flows: int = 12,
    max_edges_per_flow: int = 80,
) -> list[FlowCandidate]:
    if not scan.call_graph:
        return []

    candidates: list[FlowCandidate] = []
    candidates.extend(
        _build_endpoint_flow_candidates(
            scan,
            max_depth=max_depth,
            max_edges_per_flow=max_edges_per_flow,
        )
    )
    candidates.extend(
        _build_runtime_flow_candidates(
            scan,
            max_depth=max_depth,
            max_edges_per_flow=max_edges_per_flow,
        )
    )

    merged = _merge_candidates(candidates)
    merged.sort(key=lambda c: (-c.score, c.title, c.flow_id))
    return merged[:max_flows]


def _build_endpoint_flow_candidates(
    scan: RepoScan,
    *,
    max_depth: int,
    max_edges_per_flow: int,
) -> list[FlowCandidate]:
    bundles = list(scan.endpoint_bundles or [])
    if not bundles:
        return []

    results: list[FlowCandidate] = []
    for bundle in bundles:
        if not bundle.handler_file:
            continue
        handler_symbols = [s for s in bundle.handler_symbols if s] if bundle.handler_symbols else []
        entry_points = [
            EntryPoint(
                kind="endpoint",
                label=mp,
                handler_file=bundle.handler_file,
                handler_symbol=handler_symbols[0] if handler_symbols else "",
                endpoint_family=bundle.endpoint_family,
                framework=None,
            )
            for mp in bundle.methods_paths
        ]

        edges = _collect_edges(
            scan,
            entry_files=[bundle.handler_file],
            entry_symbols=[(bundle.handler_file, s) for s in handler_symbols],
            max_depth=max_depth,
            max_edges=max_edges_per_flow,
        )

        involved_files, involved_symbols, external, side_effects = _collect_edge_context(
            edges,
            entry_files=[bundle.handler_file],
            entry_symbols=[(bundle.handler_file, s) for s in handler_symbols],
        )

        external_touchpoints = sorted(set(bundle.integration_edges or []) | external)
        side_effects_list = sorted(side_effects)
        score = _score_flow(
            entry_points=entry_points,
            involved_files=involved_files,
            side_effects=side_effects_list,
            external_touchpoints=external_touchpoints,
            endpoint_count=len(bundle.methods_paths),
        )

        flow_id = _slugify(f"{bundle.endpoint_family}-flow")
        title = f"{_titleize(bundle.endpoint_family)} Flow"
        results.append(
            FlowCandidate(
                flow_id=flow_id,
                title=title,
                entry_kind="endpoint_family",
                entry_points=entry_points,
                call_chain_edges=edges,
                involved_files=involved_files,
                involved_symbols=involved_symbols,
                external_touchpoints=external_touchpoints,
                side_effects=side_effects_list,
                score=score,
                evidence={
                    "endpoint_family": bundle.endpoint_family,
                    "methods_paths": list(bundle.methods_paths),
                    "handler_file": bundle.handler_file,
                    "handler_symbols": list(handler_symbols),
                },
            )
        )

    return results


def _build_runtime_flow_candidates(
    scan: RepoScan,
    *,
    max_depth: int,
    max_edges_per_flow: int,
) -> list[FlowCandidate]:
    runtime = scan.runtime_scan
    if not runtime:
        return []

    results: list[FlowCandidate] = []
    results.extend(
        _build_task_flow_candidates(
            scan,
            runtime,
            max_depth=max_depth,
            max_edges_per_flow=max_edges_per_flow,
        )
    )
    results.extend(
        _build_scheduler_flow_candidates(
            scan,
            runtime,
            max_depth=max_depth,
            max_edges_per_flow=max_edges_per_flow,
        )
    )
    return results


def _build_task_flow_candidates(
    scan: RepoScan,
    runtime: RuntimeScan,
    *,
    max_depth: int,
    max_edges_per_flow: int,
) -> list[FlowCandidate]:
    results: list[FlowCandidate] = []
    for task in runtime.tasks:
        if not task.name or not task.file_path:
            continue

        entry_points = _task_entry_points(scan, task)
        entry_symbols = [(ep.handler_file, ep.handler_symbol) for ep in entry_points if ep.handler_symbol]
        entry_files = [ep.handler_file for ep in entry_points if ep.handler_file]

        edges = _collect_edges(
            scan,
            entry_files=entry_files,
            entry_symbols=entry_symbols,
            max_depth=max_depth,
            max_edges=max_edges_per_flow,
        )

        involved_files, involved_symbols, external, side_effects = _collect_edge_context(
            edges,
            entry_files=entry_files or [task.file_path],
            entry_symbols=entry_symbols,
        )

        external_touchpoints = sorted(external)
        side_effects_list = sorted(side_effects)
        score = _score_flow(
            entry_points=entry_points,
            involved_files=involved_files,
            side_effects=side_effects_list,
            external_touchpoints=external_touchpoints,
            endpoint_count=0,
        )

        flow_id = _slugify(f"{task.name}-runtime")
        title = f"{_titleize(task.name)} Runtime Flow"
        results.append(
            FlowCandidate(
                flow_id=flow_id,
                title=title,
                entry_kind="runtime_task",
                entry_points=entry_points,
                call_chain_edges=edges,
                involved_files=involved_files,
                involved_symbols=involved_symbols,
                external_touchpoints=external_touchpoints,
                side_effects=side_effects_list,
                score=score,
                evidence={
                    "runtime_kind": task.runtime_kind,
                    "task_name": task.name,
                    "task_file": task.file_path,
                    "linked_endpoints": list(task.linked_endpoints or []),
                },
            )
        )

    return results


def _build_scheduler_flow_candidates(
    scan: RepoScan,
    runtime: RuntimeScan,
    *,
    max_depth: int,
    max_edges_per_flow: int,
) -> list[FlowCandidate]:
    results: list[FlowCandidate] = []
    for scheduler in runtime.schedulers:
        if not scheduler.name or not scheduler.file_path:
            continue

        entry_points = _scheduler_entry_points(scan, scheduler)
        entry_symbols = [(ep.handler_file, ep.handler_symbol) for ep in entry_points if ep.handler_symbol]
        entry_files = [ep.handler_file for ep in entry_points if ep.handler_file]

        edges = _collect_edges(
            scan,
            entry_files=entry_files,
            entry_symbols=entry_symbols,
            max_depth=max_depth,
            max_edges=max_edges_per_flow,
        )

        involved_files, involved_symbols, external, side_effects = _collect_edge_context(
            edges,
            entry_files=entry_files or [scheduler.file_path],
            entry_symbols=entry_symbols,
        )

        external_touchpoints = sorted(external)
        side_effects_list = sorted(side_effects)
        score = _score_flow(
            entry_points=entry_points,
            involved_files=involved_files,
            side_effects=side_effects_list,
            external_touchpoints=external_touchpoints,
            endpoint_count=0,
        )

        flow_id = _slugify(f"{scheduler.name}-scheduler")
        title = f"{_titleize(scheduler.name)} Scheduler Flow"
        results.append(
            FlowCandidate(
                flow_id=flow_id,
                title=title,
                entry_kind="runtime_scheduler",
                entry_points=entry_points,
                call_chain_edges=edges,
                involved_files=involved_files,
                involved_symbols=involved_symbols,
                external_touchpoints=external_touchpoints,
                side_effects=side_effects_list,
                score=score,
                evidence={
                    "scheduler_type": scheduler.scheduler_type,
                    "scheduler_name": scheduler.name,
                    "scheduler_file": scheduler.file_path,
                    "invoked_targets": list(scheduler.invoked_targets or []),
                },
            )
        )

    return results


def _task_entry_points(scan: RepoScan, task: RuntimeTask) -> list[EntryPoint]:
    entry_points: list[EntryPoint] = []
    call_graph = scan.call_graph
    if call_graph:
        callers = call_graph.get_callers(task.file_path, task.name)
        for edge in callers[:3]:
            entry_points.append(
                EntryPoint(
                    kind="task_trigger",
                    label=task.name,
                    handler_file=edge.caller_file,
                    handler_symbol=edge.caller_symbol,
                )
            )

    if not entry_points:
        symbol = _find_symbol_in_file(scan, task.file_path, task.name)
        if symbol:
            entry_points.append(
                EntryPoint(
                    kind="task",
                    label=task.name,
                    handler_file=task.file_path,
                    handler_symbol=symbol,
                )
            )

    if not entry_points and task.producer_files:
        for producer in task.producer_files[:2]:
            symbol = _first_callable_symbol(scan, producer)
            if symbol:
                entry_points.append(
                    EntryPoint(
                        kind="task_producer",
                        label=task.name,
                        handler_file=producer,
                        handler_symbol=symbol,
                    )
                )

    if not entry_points:
        entry_points.append(
            EntryPoint(
                kind="task",
                label=task.name,
                handler_file=task.file_path,
                handler_symbol="",
            )
        )

    return entry_points


def _scheduler_entry_points(scan: RepoScan, scheduler: RuntimeScheduler) -> list[EntryPoint]:
    entry_points: list[EntryPoint] = []
    if scheduler.invoked_targets:
        for target in scheduler.invoked_targets[:3]:
            symbol_file, symbol_name = _find_symbol_anywhere(scan, target)
            if symbol_file and symbol_name:
                entry_points.append(
                    EntryPoint(
                        kind="scheduler",
                        label=target,
                        handler_file=symbol_file,
                        handler_symbol=symbol_name,
                    )
                )

    if not entry_points:
        symbol = _first_callable_symbol(scan, scheduler.file_path)
        if symbol:
            entry_points.append(
                EntryPoint(
                    kind="scheduler",
                    label=scheduler.name,
                    handler_file=scheduler.file_path,
                    handler_symbol=symbol,
                )
            )
        else:
            entry_points.append(
                EntryPoint(
                    kind="scheduler",
                    label=scheduler.name,
                    handler_file=scheduler.file_path,
                    handler_symbol="",
                )
            )

    return entry_points


def _collect_edges(
    scan: RepoScan,
    *,
    entry_files: list[str],
    entry_symbols: list[tuple[str, str]],
    max_depth: int,
    max_edges: int,
) -> list[tuple[int, CallEdge]]:
    call_graph = scan.call_graph
    if not call_graph:
        return []

    edges: list[tuple[int, CallEdge]] = []
    for file_path, symbol in entry_symbols:
        if not file_path or not symbol:
            continue
        chain = call_graph.get_execution_chain(
            file_path,
            symbol,
            max_depth=max_depth,
            local_only=False,
        )
        edges.extend(chain)
        if len(edges) >= max_edges:
            break

    if not edges and entry_files:
        # No symbol-level chains; try first callable in each entry file
        for file_path in entry_files:
            symbol = _first_callable_symbol(scan, file_path)
            if not symbol:
                continue
            chain = call_graph.get_execution_chain(
                file_path,
                symbol,
                max_depth=max_depth,
                local_only=False,
            )
            edges.extend(chain)
            if len(edges) >= max_edges:
                break

    return _dedupe_edges(edges)[:max_edges]


def _dedupe_edges(edges: Iterable[tuple[int, CallEdge]]) -> list[tuple[int, CallEdge]]:
    seen: set[tuple[str, str, str, str, str]] = set()
    result: list[tuple[int, CallEdge]] = []
    for depth, edge in edges:
        key = (
            edge.caller_file,
            edge.caller_symbol,
            edge.callee_file,
            edge.callee_symbol,
            edge.call_kind,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append((depth, edge))
    return result


def _collect_edge_context(
    edges: list[tuple[int, CallEdge]],
    *,
    entry_files: list[str],
    entry_symbols: list[tuple[str, str]],
) -> tuple[list[str], list[str], set[str], set[str]]:
    files = set(entry_files)
    symbols = {f"{f}::{s}" for f, s in entry_symbols if f and s}
    external: set[str] = set()
    side_effects: set[str] = set()

    for _, edge in edges:
        if edge.caller_file:
            files.add(edge.caller_file)
            if edge.caller_symbol:
                symbols.add(f"{edge.caller_file}::{edge.caller_symbol}")
        if edge.callee_file:
            files.add(edge.callee_file)
            if edge.callee_symbol:
                symbols.add(f"{edge.callee_file}::{edge.callee_symbol}")
        if edge.call_kind in _SIDE_EFFECT_KINDS:
            side_effects.add(f"{edge.call_kind}:{edge.callee_symbol}")
        if edge.call_kind == CALL_KIND_EXTERNAL and edge.callee_symbol:
            external.add(edge.callee_symbol)

    return sorted(files), sorted(symbols), external, side_effects


def _score_flow(
    *,
    entry_points: list[EntryPoint],
    involved_files: list[str],
    side_effects: list[str],
    external_touchpoints: list[str],
    endpoint_count: int,
) -> float:
    score = 0.0
    score += len(entry_points) * 2.0
    score += len(involved_files) * 1.5
    score += len(side_effects) * 2.0
    score += len(external_touchpoints) * 1.0
    score += endpoint_count * 3.0
    return score


def _merge_candidates(candidates: list[FlowCandidate]) -> list[FlowCandidate]:
    merged: list[FlowCandidate] = []
    for candidate in candidates:
        target = None
        for existing in merged:
            if _should_merge(existing, candidate):
                target = existing
                break
        if not target:
            merged.append(candidate)
            continue
        _merge_into(target, candidate)

    return merged


def _should_merge(a: FlowCandidate, b: FlowCandidate) -> bool:
    if a.evidence.get("endpoint_family") and a.evidence.get("endpoint_family") == b.evidence.get("endpoint_family"):
        return True
    overlap = _jaccard(set(a.involved_files), set(b.involved_files))
    return overlap >= 0.6


def _merge_into(target: FlowCandidate, incoming: FlowCandidate) -> None:
    target.entry_points = _unique_entry_points(target.entry_points + incoming.entry_points)
    target.call_chain_edges = _dedupe_edges(target.call_chain_edges + incoming.call_chain_edges)
    target.involved_files = sorted(set(target.involved_files) | set(incoming.involved_files))
    target.involved_symbols = sorted(set(target.involved_symbols) | set(incoming.involved_symbols))
    target.external_touchpoints = sorted(set(target.external_touchpoints) | set(incoming.external_touchpoints))
    target.side_effects = sorted(set(target.side_effects) | set(incoming.side_effects))
    target.score = max(target.score, incoming.score)
    if not target.title and incoming.title:
        target.title = incoming.title
    if not target.flow_id and incoming.flow_id:
        target.flow_id = incoming.flow_id


def _unique_entry_points(points: list[EntryPoint]) -> list[EntryPoint]:
    seen: set[tuple[str, str, str]] = set()
    result: list[EntryPoint] = []
    for point in points:
        key = (point.kind, point.handler_file, point.handler_symbol)
        if key in seen:
            continue
        seen.add(key)
        result.append(point)
    return result


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _first_callable_symbol(scan: RepoScan, file_path: str) -> str:
    parsed = scan.parsed_files.get(file_path)
    if not parsed or not parsed.symbols:
        return ""
    for sym in parsed.symbols:
        if sym.kind in {"function", "method", "async_function"}:
            return sym.name
    return parsed.symbols[0].name if parsed.symbols else ""


def _find_symbol_in_file(scan: RepoScan, file_path: str, name: str) -> str:
    parsed = scan.parsed_files.get(file_path)
    if not parsed or not parsed.symbols:
        return ""
    for sym in parsed.symbols:
        if sym.name == name:
            return sym.name
    return ""


def _find_symbol_anywhere(scan: RepoScan, name: str) -> tuple[str, str]:
    for file_path, parsed in scan.parsed_files.items():
        if not parsed or not parsed.symbols:
            continue
        for sym in parsed.symbols:
            if sym.name == name:
                return file_path, sym.name
    return "", ""


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug or "flow"


def _titleize(text: str) -> str:
    clean = re.sub(r"[_\-]+", " ", (text or "")).strip()
    return clean.title() if clean else "Flow"


__all__ = [
    "FlowCandidate",
    "EntryPoint",
    "build_flow_candidates",
]
