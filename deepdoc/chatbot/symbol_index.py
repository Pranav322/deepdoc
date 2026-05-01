"""Symbol-focused chatbot chunks for exact code questions."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ..v2_models import DocPlan, RepoScan
from .chunker import EMPTY_LINK_INFO
from .linking import build_plan_link_maps
from .types import ChunkRecord


def build_symbol_chunks(
    scan: RepoScan,
    plan: DocPlan,
    cfg: dict[str, Any],
    *,
    files: list[str] | None = None,
) -> list[ChunkRecord]:
    """Build tight chunks for parsed functions/classes/methods."""
    selected = set(files or [])
    chunks: list[ChunkRecord] = []
    plan_links = build_plan_link_maps(plan) if plan else None
    for rel_path, parsed in sorted(scan.parsed_files.items()):
        if selected and rel_path not in selected:
            continue
        content = scan.file_contents.get(rel_path, "")
        if not parsed.symbols or not content:
            continue
        lines = content.splitlines()
        link_info = (
            plan_links.file_links.get(rel_path, EMPTY_LINK_INFO)
            if plan_links
            else EMPTY_LINK_INFO
        )
        for symbol in parsed.symbols:
            normalized = symbol.normalized_range()
            if not normalized:
                continue
            start = max(1, normalized[0] or 1)
            end = max(start, normalized[1] or start)
            snippet = "\n".join(lines[start - 1 : min(end, len(lines))])
            if not snippet.strip():
                continue
            signature = symbol.signature or symbol.name
            text = (
                f"File: {rel_path}\n"
                f"Symbol: {symbol.name}\n"
                f"Kind: {symbol.kind}\n"
                f"Lines: {start}-{end}\n"
                f"Signature: {signature}\n\n"
                f"{snippet}"
            )
            chunk_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            chunks.append(
                ChunkRecord(
                    chunk_id=f"{rel_path}:{symbol.name}:{start}-{end}:{chunk_hash[:8]}",
                    kind="code",
                    source_key=rel_path,
                    text=text,
                    chunk_hash=chunk_hash,
                    title=f"{Path(rel_path).name} :: {symbol.name}",
                    file_path=rel_path,
                    language=parsed.language,
                    start_line=start,
                    end_line=end,
                    symbol_names=[symbol.name],
                    related_bucket_slugs=[],
                    linked_file_paths=list(link_info.linked_file_paths),
                    related_doc_paths=list(link_info.related_doc_paths),
                    related_doc_urls=list(link_info.related_doc_urls),
                    related_doc_titles=list(link_info.related_doc_titles),
                    metadata={
                        "chunk_subtype": "symbol_definition",
                        "symbol_kind": symbol.kind,
                        "signature": signature,
                    },
                )
            )
    return chunks
