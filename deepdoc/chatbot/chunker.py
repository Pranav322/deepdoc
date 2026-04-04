"""Chunk builders for code and artifact corpora."""

from __future__ import annotations

import fnmatch
import hashlib
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..parser import supported_extensions
from ..parser.base import ParsedFile, Symbol
from ..planner_v2 import DocPlan, RepoScan
from ..source_metadata import (
    classify_source_kind,
    infer_publication_tier,
    is_low_trust_source_kind,
    select_primary_framework,
)
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


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def is_artifact_file_path(path: str) -> bool:
    file_name = Path(path).name
    if file_name in ARTIFACT_EXACT_NAMES:
        return True
    if path.startswith(".github/workflows/"):
        return True
    lowered = path.lower()
    if lowered.endswith((".sql", ".yaml", ".yml")) and any(token in lowered for token in ("migration", "migrations", "alembic", "openapi")):
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


def _related_publication_tier(related_bucket_slugs: list[str], bucket_tiers: dict[str, str], rel_path: str) -> str:
    if any(bucket_tiers.get(slug) == "core" for slug in related_bucket_slugs):
        return "core"
    if any(bucket_tiers.get(slug) == "supporting" for slug in related_bucket_slugs):
        return "supporting"
    return infer_publication_tier([rel_path], {rel_path: classify_source_kind(rel_path)})


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
    bucket_tiers = _bucket_tier_map(plan)
    chunks: list[ChunkRecord] = []

    target_files = files or sorted(scan.file_contents.keys())
    giant = scan.giant_file_clusters or {}
    for rel_path in target_files:
        content = scan.file_contents.get(rel_path)
        if not content:
            continue
        parsed = scan.parsed_files.get(rel_path)
        source_kind = scan.source_kind_by_file.get(rel_path, classify_source_kind(rel_path))
        framework = select_primary_framework(scan.file_frameworks.get(rel_path, []))
        publication_tier = _related_publication_tier(related.get(rel_path, []), bucket_tiers, rel_path)
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
    max_lines: int,
    overlap: int,
) -> list[ChunkRecord]:
    lines = content.splitlines()
    imports = (parsed.imports if parsed else [])[:8]
    language = parsed.language if parsed else ""
    records: list[ChunkRecord] = []
    for cluster in analysis.clusters:
        if not cluster.line_ranges:
            continue
        cluster_start = min(start for start, _ in cluster.line_ranges if start > 0)
        cluster_end = max(end for _, end in cluster.line_ranges if end > 0)
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
                title=f"{Path(rel_path).name} :: lines {start_line}-{end_line}",
            )
        )
        if end_line >= len(lines):
            break
    return records


def _symbol_windows(symbol: Symbol, *, max_lines: int, overlap: int) -> list[tuple[int, int]]:
    if symbol.start_line <= 0 or symbol.end_line <= 0 or symbol.end_line < symbol.start_line:
        return []
    line_count = symbol.end_line - symbol.start_line + 1
    if line_count <= max_lines:
        return [(symbol.start_line, symbol.end_line)]

    step = max(max_lines - overlap, 1)
    windows = []
    start = symbol.start_line
    while start <= symbol.end_line:
        end = min(start + max_lines - 1, symbol.end_line)
        windows.append((start, end))
        if end >= symbol.end_line:
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
    parts.append("")
    parts.append(snippet.strip())
    result = "\n".join(parts).strip()
    if len(result) > MAX_CHUNK_CHARS:
        # Truncate the snippet portion to stay within embedding model limits
        header = result[: result.index("\n\n") + 2] if "\n\n" in result else ""
        budget = MAX_CHUNK_CHARS - len(header) - 20  # room for truncation marker
        result = header + snippet.strip()[:budget] + "\n... [truncated]"
    return result


def discover_artifact_files(repo_root: Path, scan: RepoScan, output_dir: Path) -> list[str]:
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
    bucket_tiers = _bucket_tier_map(plan)
    chunks: list[ChunkRecord] = []
    target_files = files or discover_artifact_files(repo_root, scan, output_dir)
    for rel_path in target_files:
        path = repo_root / rel_path
        if not path.exists() or not path.is_file():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        artifact_type = _artifact_type_for(rel_path)
        source_kind = scan.source_kind_by_file.get(rel_path, classify_source_kind(rel_path))
        publication_tier = _related_publication_tier(related.get(rel_path, []), bucket_tiers, rel_path)
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


def _artifact_windows(lines: list[str], *, max_lines: int, overlap: int) -> list[tuple[int, int, str]]:
    if not lines:
        return []
    if len(lines) <= max_lines:
        return [(1, len(lines), _first_section_name(lines))]

    windows: list[tuple[int, int, str]] = []
    step = max(max_lines - overlap, 1)
    for offset in range(0, len(lines), step):
        start_line = offset + 1
        end_line = min(offset + max_lines, len(lines))
        section_name = _first_section_name(lines[offset:end_line]) or f"lines {start_line}-{end_line}"
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
    for file_path, file_chunks in by_file.items():
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
    bucket_tiers = _bucket_tier_map(plan)
    chunks: list[ChunkRecord] = []
    target_files = files or sorted(scan.parsed_files.keys())

    for rel_path in target_files:
        parsed = scan.parsed_files.get(rel_path)
        if not parsed:
            continue
        source_kind = scan.source_kind_by_file.get(rel_path, classify_source_kind(rel_path))
        framework = select_primary_framework(scan.file_frameworks.get(rel_path, []))
        publication_tier = _related_publication_tier(related.get(rel_path, []), bucket_tiers, rel_path)
        related_slugs = related.get(rel_path, [])

        # 1. Import graph chunk
        if parsed.imports:
            import_lines = []
            for imp in parsed.imports[:30]:  # cap at 30 to stay within embedding limits
                import_lines.append(f"  - {imp}")
            text = (
                f"File: {rel_path}\n"
                f"Language: {parsed.language}\n"
                f"Type: import_graph\n\n"
                f"{Path(rel_path).name} imports:\n"
                + "\n".join(import_lines)
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
                    title=f"{Path(rel_path).name} :: imports",
                )
            )

        # 2. Symbol index chunk
        if parsed.symbols:
            symbol_lines = []
            for sym in parsed.symbols:
                sig = f" — {sym.signature.strip()}" if sym.signature else ""
                lines_info = ""
                if sym.start_line > 0 and sym.end_line > 0:
                    lines_info = f" (lines {sym.start_line}-{sym.end_line})"
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
                text = text[:MAX_CHUNK_CHARS - 20] + "\n... [truncated]"
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
                    title=f"{Path(rel_path).name} :: symbol index",
                )
            )

    return chunks

