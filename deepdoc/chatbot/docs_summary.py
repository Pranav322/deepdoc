"""Deterministic docs-summary extraction."""

from __future__ import annotations

import json
import hashlib
from pathlib import PurePosixPath
from pathlib import Path
import re
from typing import Any

from ..source_metadata import classify_source_kind
from ..v2_models import DocPlan, RepoScan, tracked_bucket_files
from .linking import build_plan_link_maps
from .settings import get_chatbot_cfg
from .types import ChunkRecord

REPO_DOC_SUFFIXES = {".md", ".mdx", ".txt", ".rst", ".adoc", ".ipynb"}
REPO_DOC_IGNORED_PARTS = {
    ".git",
    ".deepdoc",
    "site",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "out",
    "coverage",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
}


def build_doc_summary_chunks(
    output_dir: Path,
    plan: DocPlan,
    cfg: dict[str, Any],
    *,
    has_openapi: bool = False,
    slugs: list[str] | None = None,
) -> list[ChunkRecord]:
    chatbot_cfg = get_chatbot_cfg(cfg)
    plan_links = build_plan_link_maps(plan, has_openapi=has_openapi)
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
        title, snippets = _extract_summary(
            raw, page.title, max_chunks=max_chunks, max_chars=max_chars
        )
        url = _doc_url(page, has_openapi)
        link_info = plan_links.slug_links.get(page.slug)
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
                    publication_tier=getattr(page._b, "publication_tier", "core")
                    if hasattr(page, "_b")
                    else "core",
                    source_kind="docs",
                    framework="",
                    trust_score=0.9
                    if (
                        getattr(page._b, "publication_tier", "core")
                        if hasattr(page, "_b")
                        else "core"
                    )
                    == "core"
                    else 0.7,
                    related_bucket_slugs=[page.slug],
                    owned_files=list(getattr(page, "source_files", [])),
                    linked_file_paths=list(
                        link_info.linked_file_paths if link_info else []
                    ),
                    related_doc_paths=list(
                        link_info.related_doc_paths if link_info else []
                    ),
                    related_doc_urls=list(
                        link_info.related_doc_urls if link_info else [url]
                    ),
                    related_doc_titles=list(
                        link_info.related_doc_titles if link_info else [title]
                    ),
                )
            )
    return chunks


def build_doc_full_chunks(
    output_dir: Path,
    plan: DocPlan,
    cfg: dict[str, Any],
    *,
    has_openapi: bool = False,
    slugs: list[str] | None = None,
) -> list[ChunkRecord]:
    chatbot_cfg = get_chatbot_cfg(cfg)
    plan_links = build_plan_link_maps(plan, has_openapi=has_openapi)
    max_chars = max(chatbot_cfg["chunking"]["max_doc_summary_chars"], 5000)
    slug_filter = set(slugs or [])
    chunks: list[ChunkRecord] = []

    for page in plan.pages:
        if slug_filter and page.slug not in slug_filter:
            continue
        doc_path = _doc_path_for_page(output_dir, page)
        if not doc_path.exists():
            continue
        raw = doc_path.read_text(encoding="utf-8", errors="replace")
        title, sections = _extract_full_sections(raw, page.title, max_chars=max_chars)
        url = _doc_url(page, has_openapi)
        link_info = plan_links.slug_links.get(page.slug)
        for idx, section in enumerate(sections):
            heading = section.get("heading", title)
            body = section.get("body", "").strip()
            text = "\n".join(
                [
                    f"Document: {title}",
                    f"Section: {heading}",
                    f"Path: {doc_path.relative_to(output_dir).as_posix()}",
                    f"URL: {url}",
                    "",
                    body,
                ]
            ).strip()
            chunk_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            chunks.append(
                ChunkRecord(
                    chunk_id=f"{page.slug}:full:{idx}:{chunk_hash[:8]}",
                    kind="doc_full",
                    source_key=doc_path.relative_to(output_dir).as_posix(),
                    text=text,
                    chunk_hash=chunk_hash,
                    title=title,
                    doc_path=doc_path.relative_to(output_dir).as_posix(),
                    doc_url=url,
                    section_name=heading,
                    publication_tier=getattr(page._b, "publication_tier", "core")
                    if hasattr(page, "_b")
                    else "core",
                    source_kind="docs",
                    framework="",
                    trust_score=0.95
                    if (
                        getattr(page._b, "publication_tier", "core")
                        if hasattr(page, "_b")
                        else "core"
                    )
                    == "core"
                    else 0.75,
                    related_bucket_slugs=[page.slug],
                    owned_files=list(getattr(page, "source_files", [])),
                    linked_file_paths=list(
                        link_info.linked_file_paths if link_info else []
                    ),
                    related_doc_paths=list(
                        link_info.related_doc_paths if link_info else []
                    ),
                    related_doc_urls=list(
                        link_info.related_doc_urls if link_info else [url]
                    ),
                    related_doc_titles=list(
                        link_info.related_doc_titles if link_info else [title]
                    ),
                )
            )
    return chunks


def discover_repo_doc_files(
    repo_root: Path,
    scan: RepoScan,
    cfg: dict[str, Any],
    *,
    output_dir: Path | None = None,
) -> list[str]:
    chatbot_cfg = get_chatbot_cfg(cfg)
    indexing_cfg = chatbot_cfg.get("indexing", {})
    if not indexing_cfg.get("include_repo_docs", True):
        return []

    include_tests = bool(indexing_cfg.get("include_tests", False))
    repo_doc_globs = list(indexing_cfg.get("repo_doc_globs", []))
    exclude_globs = list(indexing_cfg.get("exclude_globs", []))
    max_file_bytes = int(indexing_cfg.get("max_file_bytes", 250000))

    candidates = {
        path
        for path in scan.doc_contexts.keys()
        if isinstance(path, str) and path.strip()
    }
    candidates.update(
        context.get("file_path", "")
        for context in scan.research_contexts
        if isinstance(context, dict) and context.get("file_path")
    )

    if repo_doc_globs:
        for path in repo_root.rglob("*"):
            if not path.is_file():
                continue
            rel_path = path.relative_to(repo_root).as_posix()
            if _matches_any_glob(rel_path, repo_doc_globs):
                candidates.add(rel_path)

    discovered: list[str] = []
    for rel_path in sorted(candidates):
        path = repo_root / rel_path
        if not path.is_file():
            continue
        if _repo_doc_should_skip(
            rel_path,
            output_dir=output_dir,
            repo_root=repo_root,
            include_tests=include_tests,
            exclude_globs=exclude_globs,
        ):
            continue
        try:
            if path.stat().st_size > max_file_bytes or _looks_binary(path):
                continue
        except OSError:
            continue
        discovered.append(rel_path)
    return discovered


def build_repo_doc_chunks(
    repo_root: Path,
    scan: RepoScan,
    plan: DocPlan,
    cfg: dict[str, Any],
    *,
    output_dir: Path,
    files: list[str] | None = None,
) -> list[ChunkRecord]:
    chatbot_cfg = get_chatbot_cfg(cfg)
    indexing_cfg = chatbot_cfg.get("indexing", {})
    if not indexing_cfg.get("include_repo_docs", True):
        return []

    max_chars = int(indexing_cfg.get("max_repo_doc_chars", 12000))
    target_files = files or discover_repo_doc_files(
        repo_root,
        scan,
        cfg,
        output_dir=output_dir,
    )
    plan_links = build_plan_link_maps(plan)
    file_to_slugs: dict[str, list[str]] = {}
    for bucket in plan.buckets:
        for rel_path in tracked_bucket_files(bucket):
            file_to_slugs.setdefault(rel_path, []).append(bucket.slug)
    research_contexts = {
        context.get("file_path", ""): context
        for context in scan.research_contexts
        if isinstance(context, dict) and context.get("file_path")
    }

    chunks: list[ChunkRecord] = []
    for rel_path in target_files:
        path = repo_root / rel_path
        if not path.exists() or not path.is_file():
            continue
        raw = _read_repo_doc_text(path)
        if not raw.strip():
            continue

        fallback_title = Path(rel_path).stem.replace("_", " ").replace("-", " ").title()
        title, sections = _extract_full_sections(
            raw, fallback_title, max_chars=max_chars
        )
        link_info = plan_links.file_links.get(rel_path)
        source_kind = scan.source_kind_by_file.get(
            rel_path, classify_source_kind(rel_path)
        )
        publication_tier = (
            "supporting"
            if source_kind in {"test", "fixture", "example", "generated"}
            else "core"
        )
        trust_score = 0.82 if source_kind == "docs" else 0.72
        context = research_contexts.get(rel_path, {})
        summary = scan.doc_contexts.get(rel_path, "")

        for idx, section in enumerate(sections):
            heading = section.get("heading", title)
            body = section.get("body", "").strip()
            if not body:
                continue
            context_lines = []
            if summary:
                context_lines.append(f"Summary: {summary}")
            if context.get("kind"):
                context_lines.append(f"Doc type: {context['kind']}")
            if context.get("headings"):
                context_lines.append(
                    "Known headings: " + ", ".join(context.get("headings", [])[:6])
                )

            text_parts = [
                f"Repository Document: {title}",
                f"Path: {rel_path}",
                f"Section: {heading}",
            ]
            if context_lines:
                text_parts.extend(["", *context_lines])
            text_parts.extend(["", body])
            text = "\n".join(text_parts).strip()
            chunk_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            chunks.append(
                ChunkRecord(
                    chunk_id=f"repo-doc:{rel_path}:{idx}:{chunk_hash[:8]}",
                    kind="repo_doc",
                    source_key=rel_path,
                    text=text,
                    chunk_hash=chunk_hash,
                    title=title,
                    file_path=rel_path,
                    doc_path=rel_path,
                    section_name=heading,
                    source_kind=source_kind,
                    publication_tier=publication_tier,
                    trust_score=trust_score,
                    related_bucket_slugs=list(file_to_slugs.get(rel_path, [])),
                    linked_file_paths=list(
                        link_info.linked_file_paths if link_info else []
                    ),
                    related_doc_paths=list(
                        link_info.related_doc_paths if link_info else []
                    ),
                    related_doc_urls=list(
                        link_info.related_doc_urls if link_info else []
                    ),
                    related_doc_titles=list(
                        link_info.related_doc_titles if link_info else []
                    ),
                    metadata={
                        "chunk_subtype": "repo_doc",
                        "doc_origin": "repo",
                        "repo_doc_kind": context.get("kind", ""),
                    },
                )
            )
    return chunks


def _extract_summary(
    content: str, fallback_title: str, *, max_chunks: int, max_chars: int
) -> tuple[str, list[str]]:
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
    sections = [
        chunk.strip() for chunk in re.split(r"\n(?=## )", text) if chunk.strip()
    ]
    if not sections:
        sections = [text.strip()] if text.strip() else []
    snippets: list[str] = []
    for section in sections[:max_chunks]:
        snippet = section[:max_chars].strip()
        if snippet:
            snippets.append(snippet)
    return title, snippets or [fallback_title]


def _extract_full_sections(
    content: str,
    fallback_title: str,
    *,
    max_chars: int,
) -> tuple[str, list[dict[str, str]]]:
    content = _strip_frontmatter(content)
    lines = [line.rstrip() for line in content.splitlines()]
    title = fallback_title
    sections: list[dict[str, str]] = []
    current_heading = fallback_title
    current_lines: list[str] = []

    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip() or fallback_title
            current_heading = title
            continue
        if line.startswith("## "):
            _push_full_section(sections, current_heading, current_lines, max_chars)
            current_heading = line[3:].strip() or fallback_title
            current_lines = []
            continue
        current_lines.append(line)

    _push_full_section(sections, current_heading, current_lines, max_chars)
    if not sections:
        sections.append({"heading": title, "body": fallback_title})
    return title, sections


def _push_full_section(
    sections: list[dict[str, str]],
    heading: str,
    lines: list[str],
    max_chars: int,
) -> None:
    body = "\n".join(lines).strip()
    if not body:
        return
    if len(body) <= max_chars:
        sections.append({"heading": heading, "body": body})
        return

    start = 0
    part = 1
    while start < len(body):
        end = min(start + max_chars, len(body))
        if end < len(body):
            split_at = body.rfind("\n\n", start, end)
            if split_at <= start:
                split_at = body.rfind("\n", start, end)
            if split_at > start:
                end = split_at
        chunk = body[start:end].strip()
        if chunk:
            chunk_heading = heading if part == 1 else f"{heading} (Part {part})"
            sections.append({"heading": chunk_heading, "body": chunk})
            part += 1
        start = end
        while start < len(body) and body[start] == "\n":
            start += 1


def _strip_frontmatter(content: str) -> str:
    if not content.startswith("---"):
        return content
    try:
        _, _, rest = content.split("---", 2)
        return rest.lstrip("\n")
    except ValueError:
        return content


def _read_repo_doc_text(path: Path) -> str:
    if path.suffix.lower() != ".ipynb":
        return path.read_text(encoding="utf-8", errors="replace")
    try:
        notebook = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return ""

    markdown_cells: list[str] = []
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") != "markdown":
            continue
        source = cell.get("source", [])
        if isinstance(source, list):
            markdown_cells.append("".join(source))
        elif isinstance(source, str):
            markdown_cells.append(source)
    return "\n\n".join(markdown_cells)


def _repo_doc_should_skip(
    rel_path: str,
    *,
    output_dir: Path | None,
    repo_root: Path,
    include_tests: bool,
    exclude_globs: list[str],
) -> bool:
    normalized = rel_path.strip().replace("\\", "/")
    if not normalized:
        return True
    path = PurePosixPath(normalized)
    if path.suffix.lower() not in REPO_DOC_SUFFIXES:
        return True
    if any(part in REPO_DOC_IGNORED_PARTS for part in path.parts):
        return True
    if exclude_globs and _matches_any_glob(normalized, exclude_globs):
        return True
    if output_dir is not None and _is_under_output_dir(
        repo_root / normalized, output_dir
    ):
        return True
    source_kind = classify_source_kind(normalized)
    if not include_tests and source_kind in {"test", "fixture", "example", "generated"}:
        return True
    return False


def _is_under_output_dir(candidate: Path, output_dir: Path) -> bool:
    try:
        candidate.resolve().relative_to(output_dir.resolve())
    except ValueError:
        return False
    return True


def _matches_any_glob(rel_path: str, patterns: list[str]) -> bool:
    rel = PurePosixPath(rel_path)
    name = PurePosixPath(rel.name)
    return any(rel.match(pattern) or name.match(pattern) for pattern in patterns)


def _looks_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            sample = handle.read(2048)
    except OSError:
        return True
    return b"\x00" in sample


def _doc_path_for_page(output_dir: Path, page: Any) -> Path:
    hints = (page._b.generation_hints or {}) if hasattr(page, "_b") else {}
    if hints.get("is_introduction_page") or page.page_type == "overview":
        return output_dir / "index.mdx"
    return output_dir / f"{page.slug}.mdx"


def _doc_url(page: Any, has_openapi: bool) -> str:
    hints = (page._b.generation_hints or {}) if hasattr(page, "_b") else {}
    if hints.get("is_introduction_page") or page.page_type == "overview":
        return "/"
    if has_openapi and (
        hints.get("is_endpoint_ref") or page.page_type == "endpoint_ref"
    ):
        return f"/api/{page.slug}"
    return f"/{page.slug}"
