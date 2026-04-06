"""Shared link metadata helpers for chatbot corpora."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..v2_models import DocBucket, DocPlan, tracked_bucket_files


@dataclass(frozen=True)
class LinkInfo:
    """Direct links between repo files and generated documentation pages."""

    related_doc_paths: list[str] = field(default_factory=list)
    related_doc_urls: list[str] = field(default_factory=list)
    related_doc_titles: list[str] = field(default_factory=list)
    linked_file_paths: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PlanLinkMaps:
    """Lookup tables for file-level and page-level link metadata."""

    file_links: dict[str, LinkInfo] = field(default_factory=dict)
    slug_links: dict[str, LinkInfo] = field(default_factory=dict)


def build_plan_link_maps(plan: DocPlan, *, has_openapi: bool = False) -> PlanLinkMaps:
    file_doc_paths: dict[str, list[str]] = defaultdict(list)
    file_doc_urls: dict[str, list[str]] = defaultdict(list)
    file_doc_titles: dict[str, list[str]] = defaultdict(list)
    file_linked_paths: dict[str, set[str]] = defaultdict(set)
    slug_links: dict[str, LinkInfo] = {}

    for bucket in plan.buckets:
        doc_path = bucket_doc_path(bucket)
        doc_url = bucket_doc_url(bucket, has_openapi=has_openapi)
        linked_files = tracked_bucket_files(bucket)
        slug_links[bucket.slug] = LinkInfo(
            related_doc_paths=[doc_path],
            related_doc_urls=[doc_url],
            related_doc_titles=[bucket.title],
            linked_file_paths=list(linked_files),
        )
        for rel_path in linked_files:
            _append_unique(file_doc_paths[rel_path], doc_path)
            _append_unique(file_doc_urls[rel_path], doc_url)
            _append_unique(file_doc_titles[rel_path], bucket.title)
            file_linked_paths[rel_path].update(
                candidate for candidate in linked_files if candidate != rel_path
            )

    file_links = {
        rel_path: LinkInfo(
            related_doc_paths=file_doc_paths.get(rel_path, []),
            related_doc_urls=file_doc_urls.get(rel_path, []),
            related_doc_titles=file_doc_titles.get(rel_path, []),
            linked_file_paths=sorted(file_linked_paths.get(rel_path, set())),
        )
        for rel_path in set(file_doc_paths) | set(file_doc_urls) | set(file_doc_titles) | set(file_linked_paths)
    }
    return PlanLinkMaps(file_links=file_links, slug_links=slug_links)


def bucket_doc_path(bucket: DocBucket) -> str:
    hints = bucket.generation_hints or {}
    page_type = hints.get("prompt_style", bucket.bucket_type)
    if hints.get("is_introduction_page") or page_type == "overview":
        return "index.mdx"
    return f"{bucket.slug}.mdx"


def bucket_doc_url(bucket: DocBucket, *, has_openapi: bool = False) -> str:
    hints = bucket.generation_hints or {}
    page_type = hints.get("prompt_style", bucket.bucket_type)
    if hints.get("is_introduction_page") or page_type == "overview":
        return "/"
    if has_openapi and (hints.get("is_endpoint_ref") or page_type == "endpoint_ref"):
        return f"/api/{bucket.slug}"
    return f"/{bucket.slug}"


def _append_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)
