"""Deterministic docs-summary extraction."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from ..planner_v2 import DocPlan
from .settings import get_chatbot_cfg
from .types import ChunkRecord


def build_doc_summary_chunks(
    output_dir: Path,
    plan: DocPlan,
    cfg: dict[str, Any],
    *,
    has_openapi: bool = False,
    slugs: list[str] | None = None,
) -> list[ChunkRecord]:
    chatbot_cfg = get_chatbot_cfg(cfg)
    max_chunks = chatbot_cfg["chunking"]["max_doc_summary_chunks_per_page"]
    max_chars = chatbot_cfg["chunking"]["max_doc_summary_chars"]
    slug_filter = set(slugs or [])
    chunks: list[ChunkRecord] = []

    for page in plan.pages:
        if slug_filter and page.slug not in slug_filter:
            continue
        doc_path = _doc_path_for_page(output_dir, page)
        if not doc_path.exists():
            continue
        raw = doc_path.read_text(encoding="utf-8", errors="replace")
        title, snippets = _extract_summary(raw, page.title, max_chunks=max_chunks, max_chars=max_chars)
        url = _doc_url(page, has_openapi)
        for idx, snippet in enumerate(snippets):
            text = "\n".join(
                [
                    f"Document: {title}",
                    f"Path: {doc_path.relative_to(output_dir).as_posix()}",
                    f"URL: {url}",
                    "",
                    snippet,
                ]
            ).strip()
            chunk_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            chunks.append(
                ChunkRecord(
                    chunk_id=f"{page.slug}:summary:{idx}:{chunk_hash[:8]}",
                    kind="doc_summary",
                    source_key=doc_path.relative_to(output_dir).as_posix(),
                    text=text,
                    chunk_hash=chunk_hash,
                    title=title,
                    doc_path=doc_path.relative_to(output_dir).as_posix(),
                    doc_url=url,
                    related_bucket_slugs=[page.slug],
                    owned_files=list(getattr(page, "source_files", [])),
                )
            )
    return chunks


def _extract_summary(content: str, fallback_title: str, *, max_chunks: int, max_chars: int) -> tuple[str, list[str]]:
    content = _strip_frontmatter(content)
    content = re.sub(r"```.*?```", "", content, flags=re.DOTALL)
    content = re.sub(r"<[^>\n]+>", "", content)
    lines = [line.rstrip() for line in content.splitlines()]
    title = fallback_title
    cleaned: list[str] = []
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip() or fallback_title
            continue
        if line.strip():
            cleaned.append(line.strip())
    text = "\n".join(cleaned)
    sections = [chunk.strip() for chunk in re.split(r"\n(?=## )", text) if chunk.strip()]
    if not sections:
        sections = [text.strip()] if text.strip() else []
    snippets: list[str] = []
    for section in sections[:max_chunks]:
        snippet = section[:max_chars].strip()
        if snippet:
            snippets.append(snippet)
    return title, snippets or [fallback_title]


def _strip_frontmatter(content: str) -> str:
    if not content.startswith("---"):
        return content
    try:
        _, _, rest = content.split("---", 2)
        return rest.lstrip("\n")
    except ValueError:
        return content


def _doc_path_for_page(output_dir: Path, page: Any) -> Path:
    hints = (page._b.generation_hints or {}) if hasattr(page, "_b") else {}
    if hints.get("is_introduction_page") or page.page_type == "overview":
        return output_dir / "index.mdx"
    return output_dir / f"{page.slug}.mdx"


def _doc_url(page: Any, has_openapi: bool) -> str:
    hints = (page._b.generation_hints or {}) if hasattr(page, "_b") else {}
    if hints.get("is_introduction_page") or page.page_type == "overview":
        return "/"
    if has_openapi and (hints.get("is_endpoint_ref") or page.page_type == "endpoint_ref"):
        return f"/api/{page.slug}"
    return f"/{page.slug}"
