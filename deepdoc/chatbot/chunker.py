"""Chunk builders for code and artifact corpora."""

from __future__ import annotations

from collections import defaultdict
import fnmatch
import hashlib
from pathlib import Path
from typing import Any

from ..call_graph import (
    REL_KIND_COMPONENT_EMITS,
    REL_KIND_COMPONENT_PROP,
    REL_KIND_COMPONENT_USES,
    REL_KIND_DEFINES,
    REL_KIND_IMPORTS,
    REL_KIND_REFERENCES,
    REL_KIND_ROUTE_DECLARES,
    REL_KIND_ROUTE_HANDLER,
    REL_KIND_ROUTE_MIDDLEWARE,
)
from ..parser.base import ParsedFile, Symbol
from ..source_metadata import (
    classify_source_kind,
    infer_publication_tier,
    is_low_trust_source_kind,
    select_primary_framework,
)
from ..v2_models import DocPlan, RepoScan
from .linking import LinkInfo, build_plan_link_maps
from .settings import get_chatbot_cfg
from .types import ChunkRecord

ARTIFACT_EXACT_NAMES = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
    "composer.json",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Dockerfile",
    ".env.example",
    ".env.sample",
    "openapi.json",
    "openapi.yaml",
    "openapi.yml",
}
ARTIFACT_GLOBS = [
    ".github/workflows/*",
    "**/migrations/*.sql",
    "**/migrations/*",
    "**/migration/*",
    "**/alembic/*",
]
IGNORED_PARTS = {
    ".git",
    ".deepdoc",
    "site",
    "docs",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".next",
    "dist",
    "build",
    "coverage",
}

# Safe limit for text-embedding-3-small (8,192 token limit ≈ 6,000 chars for code)
MAX_CHUNK_CHARS = 6000
EMPTY_LINK_INFO = LinkInfo()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def is_artifact_file_path(path: str) -> bool:
    file_name = Path(path).name
    if file_name in ARTIFACT_EXACT_NAMES:
        return True
    if path.startswith(".github/workflows/"):
        return True
    lowered = path.lower()
    if lowered.endswith((".sql", ".yaml", ".yml")) and any(
        token in lowered for token in ("migration", "migrations", "alembic", "openapi")
    ):
        return True
    return any(fnmatch.fnmatch(path, pattern) for pattern in ARTIFACT_GLOBS)


def _bucket_map(plan: DocPlan) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = defaultdict(list)
    for bucket in plan.buckets:
        for rel_path in set(bucket.owned_files + bucket.artifact_refs):
            mapping[rel_path].append(bucket.slug)
    return mapping


def _bucket_tier_map(plan: DocPlan) -> dict[str, str]:
    return {bucket.slug: bucket.publication_tier for bucket in plan.buckets}


def _related_publication_tier(
    related_bucket_slugs: list[str], bucket_tiers: dict[str, str], rel_path: str
) -> str:
    if any(bucket_tiers.get(slug) == "core" for slug in related_bucket_slugs):
        return "core"
    if any(bucket_tiers.get(slug) == "supporting" for slug in related_bucket_slugs):
        return "supporting"
    return infer_publication_tier(
        [rel_path], {rel_path: classify_source_kind(rel_path)}
    )


def _trust_score(source_kind: str, publication_tier: str) -> float:
    score = 1.0
    if publication_tier == "supporting":
        score -= 0.2
    elif publication_tier == "retrieval_only":
        score -= 0.35
    if is_low_trust_source_kind(source_kind):
        score -= 0.35
    return max(0.1, score)


def build_code_chunks(
    scan: RepoScan,
    plan: DocPlan,
    cfg: dict[str, Any],
    files: list[str] | None = None,
) -> list[ChunkRecord]:
    chatbot_cfg = get_chatbot_cfg(cfg)
    max_lines = chatbot_cfg["chunking"]["code_chunk_lines"]
    overlap = chatbot_cfg["chunking"]["code_chunk_overlap"]
    related = _bucket_map(plan)
    plan_links = build_plan_link_maps(plan)
    endpoint_index = _endpoint_index(scan)
    bucket_tiers = _bucket_tier_map(plan)
    chunks: list[ChunkRecord] = []

    target_files = files or sorted(scan.file_contents.keys())
    giant = scan.giant_file_clusters or {}
    for rel_path in target_files:
        content = scan.file_contents.get(rel_path)
        if not content:
            continue
        parsed = scan.parsed_files.get(rel_path)
        source_kind = scan.source_kind_by_file.get(
            rel_path, classify_source_kind(rel_path)
        )
        framework = select_primary_framework(scan.file_frameworks.get(rel_path, []))
        link_info = plan_links.file_links.get(rel_path, EMPTY_LINK_INFO)
        framework_context = _framework_context_lines(
            scan,
            rel_path,
            parsed,
            framework=framework,
            endpoint_index=endpoint_index,
        )
        publication_tier = _related_publication_tier(
            related.get(rel_path, []), bucket_tiers, rel_path
        )
        if rel_path in giant and getattr(giant[rel_path], "clusters", None):
            chunks.extend(
                _chunks_from_giant_file(
                    rel_path,
                    content,
                    parsed,
                    giant[rel_path],
                    related.get(rel_path, []),
                    source_kind=source_kind,
                    publication_tier=publication_tier,
                    framework=framework,
                    link_info=link_info,
                    framework_context=framework_context,
                    max_lines=max_lines,
                    overlap=overlap,
                )
            )
            continue
        if parsed and parsed.symbols:
            chunks.extend(
                _chunks_from_symbols(
                    rel_path,
                    parsed,
                    content,
                    related.get(rel_path, []),
                    source_kind=source_kind,
                    publication_tier=publication_tier,
                    framework=framework,
                    link_info=link_info,
                    framework_context=framework_context,
                    max_lines=max_lines,
                    overlap=overlap,
                )
            )
            continue
        chunks.extend(
            _chunks_from_windows(
                rel_path,
                content,
                related.get(rel_path, []),
                source_kind=source_kind,
                publication_tier=publication_tier,
                framework=framework,
                language=parsed.language if parsed else "",
                link_info=link_info,
                framework_context=framework_context,
                max_lines=max_lines,
                overlap=overlap,
            )
        )
    return _deduplicate_overlapping(chunks)


def _chunks_from_giant_file(
    rel_path: str,
    content: str,
    parsed: ParsedFile | None,
    analysis: Any,
    related_bucket_slugs: list[str],
    *,
    source_kind: str,
    publication_tier: str,
    framework: str,
    link_info: LinkInfo,
    framework_context: list[str],
    max_lines: int,
    overlap: int,
) -> list[ChunkRecord]:
    lines = content.splitlines()
    imports = (parsed.imports if parsed else [])[:8]
    language = parsed.language if parsed else ""
    records: list[ChunkRecord] = []
    line_count = len(lines)
    for cluster in analysis.clusters:
        if not cluster.line_ranges:
            continue
        valid_ranges = [
            (
                start,
                min(end if end > 0 and end >= start else start, line_count),
            )
            for start, end in cluster.line_ranges
            if start > 0 and start <= line_count
        ]
        if not valid_ranges:
            continue
        cluster_start = min(start for start, _ in valid_ranges)
        cluster_end = max(end for _, end in valid_ranges)
        cluster_lines = lines[cluster_start - 1 : cluster_end]
        cluster_len = len(cluster_lines)

        # Sub-window the cluster into max_lines-sized chunks
        step = max(max_lines - overlap, 1)
        for win_offset in range(0, cluster_len, step):
            win_start = cluster_start + win_offset
            win_end = min(win_start + max_lines - 1, cluster_end)
            win_snippet = "\n".join(cluster_lines[win_offset : win_offset + max_lines])
            text = _format_code_chunk_text(
                rel_path,
                language,
                imports,
                cluster.symbols,
                win_start,
                win_end,
                win_snippet,
                framework_context=framework_context,
            )
            chunk_hash = _hash_text(text)
            records.append(
                ChunkRecord(
                    chunk_id=f"{rel_path}:{win_start}:{win_end}:{chunk_hash[:8]}",
                    kind="code",
                    source_key=rel_path,
                    text=text,
                    chunk_hash=chunk_hash,
                    file_path=rel_path,
                    language=language,
                    framework=framework,
                    source_kind=source_kind,
                    publication_tier=publication_tier,
                    trust_score=_trust_score(source_kind, publication_tier),
                    start_line=win_start,
                    end_line=win_end,
                    symbol_names=list(cluster.symbols),
                    imports_summary=list(imports),
                    related_bucket_slugs=list(related_bucket_slugs),
                    linked_file_paths=list(link_info.linked_file_paths),
                    related_doc_paths=list(link_info.related_doc_paths),
                    related_doc_urls=list(link_info.related_doc_urls),
                    related_doc_titles=list(link_info.related_doc_titles),
                    title=f"{Path(rel_path).name} :: {cluster.cluster_name}",
                )
            )
            if win_end >= cluster_end:
                break
    return records


def _chunks_from_symbols(
    rel_path: str,
    parsed: ParsedFile,
    content: str,
    related_bucket_slugs: list[str],
    *,
    source_kind: str,
    publication_tier: str,
    framework: str,
    link_info: LinkInfo,
    framework_context: list[str],
    max_lines: int,
    overlap: int,
) -> list[ChunkRecord]:
    lines = content.splitlines()
    imports = parsed.imports[:8]
    records: list[ChunkRecord] = []
    for symbol in parsed.symbols:
        windows = _symbol_windows(symbol, max_lines=max_lines, overlap=overlap)
        for start_line, end_line in windows:
            snippet = "\n".join(lines[start_line - 1 : end_line])
            text = _format_code_chunk_text(
                rel_path,
                parsed.language,
                imports,
                [symbol.name],
                start_line,
                end_line,
                snippet,
                signature=symbol.signature,
                framework_context=framework_context,
            )
            chunk_hash = _hash_text(text)
            records.append(
                ChunkRecord(
                    chunk_id=f"{rel_path}:{start_line}:{end_line}:{chunk_hash[:8]}",
                    kind="code",
                    source_key=rel_path,
                    text=text,
                    chunk_hash=chunk_hash,
                    file_path=rel_path,
                    language=parsed.language,
                    framework=framework,
                    source_kind=source_kind,
                    publication_tier=publication_tier,
                    trust_score=_trust_score(source_kind, publication_tier),
                    start_line=start_line,
                    end_line=end_line,
                    symbol_names=[symbol.name],
                    imports_summary=list(imports),
                    related_bucket_slugs=list(related_bucket_slugs),
                    linked_file_paths=list(link_info.linked_file_paths),
                    related_doc_paths=list(link_info.related_doc_paths),
                    related_doc_urls=list(link_info.related_doc_urls),
                    related_doc_titles=list(link_info.related_doc_titles),
                    title=f"{Path(rel_path).name} :: {symbol.name}",
                )
            )
    return records


def _chunks_from_windows(
    rel_path: str,
    content: str,
    related_bucket_slugs: list[str],
    *,
    source_kind: str,
    publication_tier: str,
    framework: str,
    language: str,
    link_info: LinkInfo,
    framework_context: list[str],
    max_lines: int,
    overlap: int,
) -> list[ChunkRecord]:
    records: list[ChunkRecord] = []
    lines = content.splitlines()
    step = max(max_lines - overlap, 1)
    for offset in range(0, len(lines), step):
        start_line = offset + 1
        end_line = min(offset + max_lines, len(lines))
        snippet = "\n".join(lines[offset:end_line])
        text = _format_code_chunk_text(
            rel_path,
            language,
            [],
            [],
            start_line,
            end_line,
            snippet,
            framework_context=framework_context,
        )
        chunk_hash = _hash_text(text)
        records.append(
            ChunkRecord(
                chunk_id=f"{rel_path}:{start_line}:{end_line}:{chunk_hash[:8]}",
                kind="code",
                source_key=rel_path,
                text=text,
                chunk_hash=chunk_hash,
                file_path=rel_path,
                language=language,
                framework=framework,
                source_kind=source_kind,
                publication_tier=publication_tier,
                trust_score=_trust_score(source_kind, publication_tier),
                start_line=start_line,
                end_line=end_line,
                related_bucket_slugs=list(related_bucket_slugs),
                linked_file_paths=list(link_info.linked_file_paths),
                related_doc_paths=list(link_info.related_doc_paths),
                related_doc_urls=list(link_info.related_doc_urls),
                related_doc_titles=list(link_info.related_doc_titles),
                title=f"{Path(rel_path).name} :: lines {start_line}-{end_line}",
            )
        )
        if end_line >= len(lines):
            break
    return records


def _symbol_windows(
    symbol: Symbol, *, max_lines: int, overlap: int
) -> list[tuple[int, int]]:
    normalized = symbol.normalized_range()
    if not normalized:
        return []
    start_line, end_line = normalized
    line_count = end_line - start_line + 1
    if line_count <= max_lines:
        return [(start_line, end_line)]

    step = max(max_lines - overlap, 1)
    windows = []
    start = start_line
    while start <= end_line:
        end = min(start + max_lines - 1, end_line)
        windows.append((start, end))
        if end >= end_line:
            break
        start += step
    return windows


def _format_code_chunk_text(
    rel_path: str,
    language: str,
    imports: list[str],
    symbols: list[str],
    start_line: int,
    end_line: int,
    snippet: str,
    *,
    signature: str = "",
    framework_context: list[str] | None = None,
) -> str:
    parts = [
        f"File: {rel_path}",
        f"Language: {language or 'unknown'}",
        f"Lines: {start_line}-{end_line}",
    ]
    if symbols:
        parts.append("Symbols: " + ", ".join(symbols))
    if signature:
        parts.append("Signature: " + signature.strip())
    if imports:
        parts.append("Imports: " + ", ".join(imports[:8]))
    if framework_context:
        parts.append("Framework context:")
        parts.extend(f"- {line}" for line in framework_context[:8])
    parts.append("")
    parts.append(snippet.strip())
    result = "\n".join(parts).strip()
    if len(result) > MAX_CHUNK_CHARS:
        # Truncate the snippet portion to stay within embedding model limits
        header = result[: result.index("\n\n") + 2] if "\n\n" in result else ""
        budget = MAX_CHUNK_CHARS - len(header) - 20  # room for truncation marker
        result = header + snippet.strip()[:budget] + "\n... [truncated]"
    return result


def _endpoint_index(scan: RepoScan) -> dict[str, list[dict[str, Any]]]:
    mapping: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for endpoint in scan.api_endpoints:
        for key in ("file", "handler_file", "route_file"):
            rel_path = str(endpoint.get(key, "") or "").strip()
            if rel_path and endpoint not in mapping[rel_path]:
                mapping[rel_path].append(endpoint)
    return mapping


def _framework_context_lines(
    scan: RepoScan,
    rel_path: str,
    parsed: ParsedFile | None,
    *,
    framework: str,
    endpoint_index: dict[str, list[dict[str, Any]]],
) -> list[str]:
    lines: list[str] = []
    if framework in {"django", "express", "fastify", "laravel", "falcon", "go"}:
        endpoints = endpoint_index.get(rel_path, [])
        if endpoints:
            lines.extend(_backend_framework_lines(framework, endpoints))
    if framework == "vue" and parsed:
        lines.extend(_vue_framework_lines(parsed))
    return lines[:10]


def _backend_framework_lines(
    framework: str, endpoints: list[dict[str, Any]]
) -> list[str]:
    unique_routes: list[str] = []
    middleware: list[str] = []
    request_hints: list[str] = []
    response_hints: list[str] = []
    for endpoint in endpoints[:8]:
        route = (
            f"{endpoint.get('method', '').upper()} {endpoint.get('path', '')}".strip()
        )
        handler = str(endpoint.get("handler", "") or "").strip()
        route_summary = f"{route} -> {handler}" if handler else route
        if route_summary and route_summary not in unique_routes:
            unique_routes.append(route_summary)
        for name in endpoint.get("middleware", []) or []:
            name = str(name).strip()
            if name and name not in middleware:
                middleware.append(name)
        request_body = str(endpoint.get("request_body", "") or "").strip()
        if request_body and request_body not in request_hints:
            request_hints.append(request_body)
        response_type = str(endpoint.get("response_type", "") or "").strip()
        if response_type and response_type not in response_hints:
            response_hints.append(response_type)

    lines = (
        [f"{framework} routes: " + "; ".join(unique_routes[:4])]
        if unique_routes
        else []
    )
    if middleware:
        lines.append("middleware: " + ", ".join(middleware[:6]))
    if request_hints:
        lines.append("request bodies: " + ", ".join(request_hints[:3]))
    if response_hints:
        lines.append("response types: " + ", ".join(response_hints[:3]))
    return lines


def _vue_framework_lines(parsed: ParsedFile) -> list[str]:
    names = {symbol.name for symbol in parsed.symbols}
    props: list[str] = []
    emits: list[str] = []
    runtime_signals: list[str] = []
    for symbol in parsed.symbols:
        if symbol.name == "props" and symbol.props:
            props.extend(name for name in symbol.props if name not in props)
        if symbol.name == "emit" and symbol.fields:
            emits.extend(name for name in symbol.fields if name not in emits)
        if symbol.name in {
            "router",
            "route",
            "pinia",
            "store",
            "storeRefs",
            "composables",
            "model",
            "slots",
        }:
            runtime_signals.append(symbol.name)
    if "components" in names:
        runtime_signals.append("components")
    ordered_signals = []
    for signal in runtime_signals:
        if signal not in ordered_signals:
            ordered_signals.append(signal)

    lines: list[str] = []
    if ordered_signals:
        lines.append("vue signals: " + ", ".join(ordered_signals[:8]))
    if props:
        lines.append("component props: " + ", ".join(props[:8]))
    if emits:
        lines.append("emits: " + ", ".join(emits[:8]))
    return lines


def discover_artifact_files(
    repo_root: Path, scan: RepoScan, output_dir: Path
) -> list[str]:
    discovered: set[str] = set()
    for rel_path in list(scan.config_files) + list(scan.openapi_paths):
        candidate = repo_root / rel_path
        if candidate.is_file():
            discovered.add(rel_path)
        elif candidate.is_dir():
            for child in candidate.rglob("*"):
                if child.is_file():
                    discovered.add(child.relative_to(repo_root).as_posix())

    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        rel_path = path.relative_to(repo_root).as_posix()
        if any(part in IGNORED_PARTS for part in path.parts):
            continue
        try:
            path.relative_to(output_dir)
            continue
        except ValueError:
            pass
        if is_artifact_file_path(rel_path):
            discovered.add(rel_path)
    return sorted(discovered)


def build_artifact_chunks(
    repo_root: Path,
    scan: RepoScan,
    plan: DocPlan,
    output_dir: Path,
    cfg: dict[str, Any],
    files: list[str] | None = None,
) -> list[ChunkRecord]:
    chatbot_cfg = get_chatbot_cfg(cfg)
    max_lines = chatbot_cfg["chunking"]["artifact_chunk_lines"]
    overlap = chatbot_cfg["chunking"]["artifact_chunk_overlap"]
    related = _bucket_map(plan)
    plan_links = build_plan_link_maps(plan)
    bucket_tiers = _bucket_tier_map(plan)
    chunks: list[ChunkRecord] = []
    target_files = files or discover_artifact_files(repo_root, scan, output_dir)
    for rel_path in target_files:
        path = repo_root / rel_path
        if not path.exists() or not path.is_file():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        artifact_type = _artifact_type_for(rel_path)
        source_kind = scan.source_kind_by_file.get(
            rel_path, classify_source_kind(rel_path)
        )
        publication_tier = _related_publication_tier(
            related.get(rel_path, []), bucket_tiers, rel_path
        )
        link_info = plan_links.file_links.get(rel_path, EMPTY_LINK_INFO)
        lines = content.splitlines()
        windows = _artifact_windows(lines, max_lines=max_lines, overlap=overlap)
        for start_line, end_line, section_name in windows:
            snippet = "\n".join(lines[start_line - 1 : end_line])
            header = f"Artifact: {rel_path}\nType: {artifact_type}\nSection: {section_name}\nLines: {start_line}-{end_line}\n\n"
            body = snippet.strip()
            if len(header) + len(body) > MAX_CHUNK_CHARS:
                budget = MAX_CHUNK_CHARS - len(header) - 20
                body = body[:budget] + "\n... [truncated]"
            text = (header + body).strip()
            chunk_hash = _hash_text(text)
            chunks.append(
                ChunkRecord(
                    chunk_id=f"{rel_path}:{start_line}:{end_line}:{chunk_hash[:8]}",
                    kind="artifact",
                    source_key=rel_path,
                    text=text,
                    chunk_hash=chunk_hash,
                    file_path=rel_path,
                    artifact_type=artifact_type,
                    source_kind=source_kind,
                    publication_tier=publication_tier,
                    trust_score=_trust_score(source_kind, publication_tier),
                    section_name=section_name,
                    start_line=start_line,
                    end_line=end_line,
                    related_bucket_slugs=list(related.get(rel_path, [])),
                    linked_file_paths=list(link_info.linked_file_paths),
                    related_doc_paths=list(link_info.related_doc_paths),
                    related_doc_urls=list(link_info.related_doc_urls),
                    related_doc_titles=list(link_info.related_doc_titles),
                    title=f"{Path(rel_path).name} :: {section_name}",
                )
            )
    return chunks


def _artifact_type_for(rel_path: str) -> str:
    name = Path(rel_path).name
    if name.startswith("docker-compose"):
        return "docker_compose"
    if name == "Dockerfile":
        return "dockerfile"
    if rel_path.startswith(".github/workflows/"):
        return "workflow"
    suffix = Path(rel_path).suffix.lower()
    if suffix == ".sql":
        return "migration"
    if suffix in {".yaml", ".yml"} and "openapi" in rel_path.lower():
        return "openapi"
    if suffix in {".yaml", ".yml"}:
        return "yaml"
    if suffix == ".json":
        return "json"
    if suffix == ".toml":
        return "toml"
    return name.replace(".", "_")


def _artifact_windows(
    lines: list[str], *, max_lines: int, overlap: int
) -> list[tuple[int, int, str]]:
    if not lines:
        return []
    if len(lines) <= max_lines:
        return [(1, len(lines), _first_section_name(lines))]

    windows: list[tuple[int, int, str]] = []
    step = max(max_lines - overlap, 1)
    for offset in range(0, len(lines), step):
        start_line = offset + 1
        end_line = min(offset + max_lines, len(lines))
        section_name = (
            _first_section_name(lines[offset:end_line])
            or f"lines {start_line}-{end_line}"
        )
        windows.append((start_line, end_line, section_name))
        if end_line >= len(lines):
            break
    return windows


def _first_section_name(lines: list[str]) -> str:
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", "[", "{")):
            return stripped[:80]
        if ":" in stripped:
            return stripped.split(":", 1)[0][:80]
        return stripped[:80]
    return "overview"


def _deduplicate_overlapping(chunks: list[ChunkRecord]) -> list[ChunkRecord]:
    """Remove near-duplicate chunks from the same file with >50% line overlap."""
    if not chunks:
        return chunks

    by_file: dict[str, list[ChunkRecord]] = defaultdict(list)
    for chunk in chunks:
        by_file[chunk.file_path].append(chunk)

    result: list[ChunkRecord] = []
    for _file_path, file_chunks in by_file.items():
        if len(file_chunks) <= 1:
            result.extend(file_chunks)
            continue

        file_chunks.sort(key=lambda c: (c.start_line, c.end_line))
        kept: list[ChunkRecord] = [file_chunks[0]]
        for chunk in file_chunks[1:]:
            prev = kept[-1]
            overlap_start = max(prev.start_line, chunk.start_line)
            overlap_end = min(prev.end_line, chunk.end_line)
            overlap_lines = max(0, overlap_end - overlap_start + 1)
            shorter_len = min(
                prev.end_line - prev.start_line + 1,
                chunk.end_line - chunk.start_line + 1,
            )
            if shorter_len > 0 and overlap_lines / shorter_len > 0.5:
                # Keep the one with more symbol metadata
                if len(chunk.symbol_names) > len(prev.symbol_names):
                    kept[-1] = chunk
            else:
                kept.append(chunk)
        result.extend(kept)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Relationship / import-graph chunks
# ─────────────────────────────────────────────────────────────────────────────


def build_relationship_chunks(
    scan: RepoScan,
    plan: DocPlan,
    cfg: dict[str, Any],
    files: list[str] | None = None,
) -> list[ChunkRecord]:
    """Build lightweight chunks that map file relationships and symbol indexes.

    Two chunk types per file:
    1. **Import graph** — what the file imports and from where.
    2. **Symbol index** — every class, function, method defined in the file.

    These chunks are small (~200-500 chars) and cheap to embed, but they
    dramatically improve the chatbot's ability to follow imports and find
    related files.
    """
    related = _bucket_map(plan)
    plan_links = build_plan_link_maps(plan)
    endpoint_index = _endpoint_index(scan)
    bucket_tiers = _bucket_tier_map(plan)
    chunks: list[ChunkRecord] = []
    target_files = files or sorted(scan.parsed_files.keys())

    for rel_path in target_files:
        parsed = scan.parsed_files.get(rel_path)
        if not parsed:
            continue
        source_kind = scan.source_kind_by_file.get(
            rel_path, classify_source_kind(rel_path)
        )
        framework = select_primary_framework(scan.file_frameworks.get(rel_path, []))
        publication_tier = _related_publication_tier(
            related.get(rel_path, []), bucket_tiers, rel_path
        )
        related_slugs = related.get(rel_path, [])
        link_info = plan_links.file_links.get(rel_path, EMPTY_LINK_INFO)
        framework_lines = _framework_context_lines(
            scan,
            rel_path,
            parsed,
            framework=framework,
            endpoint_index=endpoint_index,
        )

        # 1. Import graph chunk
        if parsed.imports:
            import_lines = []
            for imp in parsed.imports[:30]:  # cap at 30 to stay within embedding limits
                import_lines.append(f"  - {imp}")
            text = (
                f"File: {rel_path}\n"
                f"Language: {parsed.language}\n"
                f"Type: import_graph\n\n"
                f"{Path(rel_path).name} imports:\n" + "\n".join(import_lines)
            )
            chunk_hash = _hash_text(text)
            chunks.append(
                ChunkRecord(
                    chunk_id=f"{rel_path}:imports:{chunk_hash[:8]}",
                    kind="relationship",
                    source_key=rel_path,
                    text=text,
                    chunk_hash=chunk_hash,
                    file_path=rel_path,
                    language=parsed.language,
                    framework=framework,
                    source_kind=source_kind,
                    publication_tier=publication_tier,
                    trust_score=_trust_score(source_kind, publication_tier),
                    imports_summary=list(parsed.imports[:30]),
                    related_bucket_slugs=list(related_slugs),
                    linked_file_paths=list(link_info.linked_file_paths),
                    related_doc_paths=list(link_info.related_doc_paths),
                    related_doc_urls=list(link_info.related_doc_urls),
                    related_doc_titles=list(link_info.related_doc_titles),
                    title=f"{Path(rel_path).name} :: imports",
                )
            )

        # 2. Symbol index chunk
        if parsed.symbols:
            symbol_lines = []
            for sym in parsed.symbols:
                sig = f" — {sym.signature.strip()}" if sym.signature else ""
                lines_info = ""
                normalized = sym.normalized_range()
                if normalized:
                    start_line, end_line = normalized
                    lines_info = f" (lines {start_line}-{end_line})"
                symbol_lines.append(f"  - {sym.kind}: {sym.name}{sig}{lines_info}")
            text = (
                f"File: {rel_path}\n"
                f"Language: {parsed.language}\n"
                f"Type: symbol_index\n\n"
                f"{Path(rel_path).name} defines {len(parsed.symbols)} symbols:\n"
                + "\n".join(symbol_lines)
            )
            # Respect embedding limits
            if len(text) > MAX_CHUNK_CHARS:
                text = text[: MAX_CHUNK_CHARS - 20] + "\n... [truncated]"
            chunk_hash = _hash_text(text)
            chunks.append(
                ChunkRecord(
                    chunk_id=f"{rel_path}:symbols:{chunk_hash[:8]}",
                    kind="relationship",
                    source_key=rel_path,
                    text=text,
                    chunk_hash=chunk_hash,
                    file_path=rel_path,
                    language=parsed.language,
                    framework=framework,
                    source_kind=source_kind,
                    publication_tier=publication_tier,
                    trust_score=_trust_score(source_kind, publication_tier),
                    symbol_names=[sym.name for sym in parsed.symbols],
                    related_bucket_slugs=list(related_slugs),
                    linked_file_paths=list(link_info.linked_file_paths),
                    related_doc_paths=list(link_info.related_doc_paths),
                    related_doc_urls=list(link_info.related_doc_urls),
                    related_doc_titles=list(link_info.related_doc_titles),
                    title=f"{Path(rel_path).name} :: symbol index",
                )
            )

        if framework_lines:
            text = (
                f"File: {rel_path}\n"
                f"Language: {parsed.language}\n"
                f"Framework: {framework or 'unknown'}\n"
                "Type: framework_context\n\n"
                + "\n".join(f"- {line}" for line in framework_lines)
            )
            chunk_hash = _hash_text(text)
            chunks.append(
                ChunkRecord(
                    chunk_id=f"{rel_path}:framework:{chunk_hash[:8]}",
                    kind="relationship",
                    source_key=rel_path,
                    text=text,
                    chunk_hash=chunk_hash,
                    file_path=rel_path,
                    language=parsed.language,
                    framework=framework,
                    source_kind=source_kind,
                    publication_tier=publication_tier,
                    trust_score=_trust_score(source_kind, publication_tier),
                    symbol_names=[framework]
                    + [line.split(":", 1)[0] for line in framework_lines[:4]],
                    related_bucket_slugs=list(related_slugs),
                    linked_file_paths=list(link_info.linked_file_paths),
                    related_doc_paths=list(link_info.related_doc_paths),
                    related_doc_urls=list(link_info.related_doc_urls),
                    related_doc_titles=list(link_info.related_doc_titles),
                    title=f"{Path(rel_path).name} :: framework context",
                    metadata={"chunk_subtype": "framework_context"},
                )
            )

    return chunks


def build_call_graph_chunks(
    call_graph: Any,
    parsed_files: dict[str, Any],
    plan: DocPlan | None = None,
    *,
    has_openapi: bool = False,
    max_chains: int = 200,
) -> list[ChunkRecord]:
    """Build retrieval chunks from the call graph.

    One chunk per function that has outgoing local calls. The chunk text
    describes the execution chain so the chatbot can answer questions like
    "what does X call?" and "what triggers Y?".

    These are stored as 'relationship' kind chunks.
    """
    if call_graph is None:
        return []

    chunks = []
    plan_links = build_plan_link_maps(plan, has_openapi=has_openapi) if plan else None

    # Collect all unique caller → callees relationships
    try:
        all_edges = list(call_graph._callees.values())
        if isinstance(all_edges[0] if all_edges else [], list):
            all_edges = [e for edges in all_edges for e in edges]
    except (AttributeError, IndexError, TypeError):
        return []

    # Filter to local calls (not external imports)
    local_edges = [
        e for e in all_edges if getattr(e, "call_kind", "") != "external"
    ]

    # Group by caller
    by_caller: dict[str, list[Any]] = {}
    for edge in local_edges:
        caller_file = getattr(edge, "caller_file", "")
        caller_symbol = getattr(edge, "caller_symbol", "")
        key = f"{caller_file}::{caller_symbol}"
        if key not in by_caller:
            by_caller[key] = []
        by_caller[key].append(edge)

    processed = 0
    for _caller_key, edges in by_caller.items():
        if processed >= max_chains:
            break
        if not edges:
            continue

        caller_file = edges[0].caller_file
        caller_symbol = edges[0].caller_symbol

        # Build readable call chain text
        local_callees = [
            e
            for e in edges
            if getattr(e, "call_kind", None) == "local"
            and getattr(e, "callee_file", None)
        ]
        celery_dispatches = [
            e for e in edges if getattr(e, "call_kind", None) == "celery_dispatch"
        ]
        signal_dispatches = [
            e for e in edges if getattr(e, "call_kind", None) == "signal_dispatch"
        ]
        event_dispatches = [
            e for e in edges if getattr(e, "call_kind", None) == "event_dispatch"
        ]

        if not (
            local_callees or celery_dispatches or signal_dispatches or event_dispatches
        ):
            continue

        parts = [f"# Call graph for `{caller_symbol}` in `{caller_file}`\n"]

        if local_callees:
            parts.append("## Local calls:")
            for e in local_callees[:12]:
                callee_sym = getattr(e, "callee_symbol", "unknown")
                callee_file = getattr(e, "callee_file", "")
                parts.append(f"- `{callee_sym}` (in `{callee_file}`)")

        if celery_dispatches:
            parts.append("\n## Celery task dispatches (async side-effects):")
            for e in celery_dispatches[:6]:
                callee_sym = getattr(e, "callee_symbol", "unknown")
                callee_file = getattr(e, "callee_file", None)
                msg = f"- dispatches task `{callee_sym}`"
                if callee_file:
                    msg += f" from `{callee_file}`"
                parts.append(msg)

        if signal_dispatches:
            parts.append("\n## Django signal dispatches:")
            for e in signal_dispatches[:6]:
                callee_sym = getattr(e, "callee_symbol", "unknown")
                parts.append(f"- sends signal `{callee_sym}`")

        if event_dispatches:
            parts.append("\n## Event emissions:")
            for e in event_dispatches[:6]:
                callee_sym = getattr(e, "callee_symbol", "unknown")
                parts.append(f"- emits `{callee_sym}`")

        text = "\n".join(parts)
        chunk_hash = _hash_text(text)
        link_info = (
            plan_links.file_links.get(caller_file, EMPTY_LINK_INFO)
            if plan_links
            else EMPTY_LINK_INFO
        )

        chunks.append(
            ChunkRecord(
                chunk_id=f"callgraph_{chunk_hash}",
                kind="relationship",
                source_key=caller_file,
                text=text,
                chunk_hash=chunk_hash,
                title=f"Call graph: {caller_symbol}",
                file_path=caller_file,
                linked_file_paths=list(link_info.linked_file_paths),
                related_doc_paths=list(link_info.related_doc_paths),
                related_doc_urls=list(link_info.related_doc_urls),
                related_doc_titles=list(link_info.related_doc_titles),
                symbol_names=[caller_symbol]
                + [getattr(e, "callee_symbol", "") for e in local_callees[:5]],
                metadata={
                    "chunk_subtype": "call_graph",
                    "caller_symbol": caller_symbol,
                },
            )
        )
        processed += 1

    return chunks


def build_graph_relation_chunks(
    call_graph: Any,
    plan: DocPlan | None = None,
    *,
    has_openapi: bool = False,
    files: list[str] | None = None,
    max_chunks: int = 250,
) -> list[ChunkRecord]:
    """Build file-level graph neighbor summaries from generic graph relations."""
    if call_graph is None:
        return []

    plan_links = build_plan_link_maps(plan, has_openapi=has_openapi) if plan else None
    target_files = set(files or [])
    file_nodes = sorted(
        node_id
        for node_id in getattr(call_graph, "_relations_out", {})
        if node_id.startswith("file:")
        and (not target_files or node_id[5:] in target_files)
    )

    chunks: list[ChunkRecord] = []
    for file_node in file_nodes[:max_chunks]:
        rel_path = file_node[5:]
        outgoing = call_graph.get_outgoing_relations(file_node)
        defined_symbols = [
            relation.dst for relation in outgoing if relation.kind == REL_KIND_DEFINES
        ]
        imports = [
            _graph_node_label(relation.dst)
            for relation in outgoing
            if relation.kind == REL_KIND_IMPORTS
        ]
        route_nodes = [
            relation.dst
            for relation in outgoing
            if relation.kind == REL_KIND_ROUTE_DECLARES
        ]

        handled_routes: list[str] = []
        references: list[str] = []
        component_lines: list[str] = []
        symbol_names: list[str] = []

        for symbol_node in defined_symbols:
            symbol_label = _graph_node_label(symbol_node)
            if symbol_label and symbol_label not in symbol_names:
                symbol_names.append(symbol_label)

            incoming_routes = call_graph.get_incoming_relations(
                symbol_node, kinds={REL_KIND_ROUTE_HANDLER}
            )
            for relation in incoming_routes:
                route_label = _graph_node_label(relation.src)
                if route_label and route_label not in handled_routes:
                    handled_routes.append(route_label)

            for relation in call_graph.get_outgoing_relations(
                symbol_node, kinds={REL_KIND_REFERENCES}
            ):
                ref_label = _graph_node_label(relation.dst)
                if ref_label and ref_label not in references:
                    references.append(ref_label)

            for rel_kind, prefix in (
                (REL_KIND_COMPONENT_USES, "uses"),
                (REL_KIND_COMPONENT_PROP, "props"),
                (REL_KIND_COMPONENT_EMITS, "emits"),
            ):
                for relation in call_graph.get_outgoing_relations(
                    symbol_node, kinds={rel_kind}
                ):
                    node_label = _graph_node_label(relation.dst)
                    line = f"{prefix}: {node_label}"
                    if node_label and line not in component_lines:
                        component_lines.append(line)

        route_lines: list[str] = []
        for route_node in route_nodes:
            route_label = _graph_node_label(route_node)
            handler_labels = [
                _graph_node_label(relation.dst)
                for relation in call_graph.get_outgoing_relations(
                    route_node, kinds={REL_KIND_ROUTE_HANDLER}
                )
            ]
            middleware_labels = [
                _graph_node_label(relation.dst)
                for relation in call_graph.get_outgoing_relations(
                    route_node, kinds={REL_KIND_ROUTE_MIDDLEWARE}
                )
            ]
            line = route_label
            if handler_labels:
                line += " -> " + ", ".join(handler_labels[:2])
            if middleware_labels:
                line += " [middleware: " + ", ".join(middleware_labels[:4]) + "]"
            route_lines.append(line)

        if not (
            imports or route_lines or handled_routes or references or component_lines
        ):
            continue

        sections = [f"File graph neighbors for `{rel_path}`", ""]
        if imports:
            sections.append("## Imports")
            sections.extend(f"- `{item}`" for item in imports[:8])
        if route_lines:
            sections.append("## Declared routes")
            sections.extend(f"- `{item}`" for item in route_lines[:8])
        if handled_routes:
            sections.append("## Handled routes")
            sections.extend(f"- `{item}`" for item in handled_routes[:8])
        if references:
            sections.append("## References")
            sections.extend(f"- `{item}`" for item in references[:10])
        if component_lines:
            sections.append("## Component signals")
            sections.extend(f"- {item}" for item in component_lines[:10])

        text = "\n".join(sections).strip()
        chunk_hash = _hash_text(text)
        link_info = (
            plan_links.file_links.get(rel_path, EMPTY_LINK_INFO)
            if plan_links
            else EMPTY_LINK_INFO
        )
        chunks.append(
            ChunkRecord(
                chunk_id=f"graph_{rel_path}:{chunk_hash[:8]}",
                kind="relationship",
                source_key=rel_path,
                text=text,
                chunk_hash=chunk_hash,
                file_path=rel_path,
                linked_file_paths=list(link_info.linked_file_paths),
                related_doc_paths=list(link_info.related_doc_paths),
                related_doc_urls=list(link_info.related_doc_urls),
                related_doc_titles=list(link_info.related_doc_titles),
                symbol_names=symbol_names[:8],
                metadata={"chunk_subtype": "graph_neighbors"},
                title=f"{Path(rel_path).name} :: graph neighbors",
            )
        )

    return chunks


def _graph_node_label(node_id: str) -> str:
    if node_id.startswith("file:"):
        return node_id[5:]
    if node_id.startswith("symbol:"):
        return node_id.split("::", 1)[-1]
    if node_id.startswith("route:"):
        return node_id[6:]
    if node_id.startswith("middleware:"):
        return node_id[11:]
    if node_id.startswith("import:"):
        return node_id[7:]
    if node_id.startswith("external:vue:prop:"):
        return node_id[len("external:vue:prop:") :]
    if node_id.startswith("external:vue:emit:"):
        return node_id[len("external:vue:emit:") :]
    if node_id.startswith("external:vue:"):
        return node_id[len("external:vue:") :]
    if node_id.startswith("external:"):
        return node_id[9:]
    return node_id
