"""Live fallback mixin for ChatbotQueryService."""

from __future__ import annotations

import fnmatch
import hashlib
from pathlib import Path
from typing import Any

from ..source_metadata import classify_source_kind
from .types import (
    ChunkRecord,
    RetrievedChunk,
)

DOC_SUFFIXES = {".md", ".mdx", ".txt", ".rst", ".adoc", ".ipynb"}


class LiveFallbackMixin:
    """Mixin providing live-repo fallback search methods."""

    def should_use_live_fallback(
        self,
        question: str,
        hits: list[RetrievedChunk],
    ) -> bool:
        retrieval_cfg = self.chat_cfg["retrieval"]
        if not retrieval_cfg.get("deep_research_live_fallback", True):
            return False
        if not hits:
            return True
        query_signals = self._query_signals([question])
        if len(hits) < 2:
            return True
        if query_signals["identifier_like"] and not any(
            self._lexical_score(hit.record, query_signals) >= 1.0 for hit in hits[:4]
        ):
            return True
        return False

    def live_research_fallback(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
        *,
        original_question: str | None = None,
        exclude_ids: set[str] | None = None,
    ) -> list[RetrievedChunk]:
        del history
        retrieval_cfg = self.chat_cfg["retrieval"]
        indexing_cfg = self.chat_cfg.get("indexing", {})
        query_signals = self._query_signals([original_question or question, question])
        if not query_signals["tokens"] and not query_signals["exact_terms"]:
            return []

        max_files = max(1, retrieval_cfg.get("live_fallback_max_files", 6))
        per_file = max(1, retrieval_cfg.get("live_fallback_max_per_file", 2))
        context_lines = max(2, retrieval_cfg.get("live_fallback_context_lines", 12))
        max_file_bytes = int(indexing_cfg.get("max_file_bytes", 250000))
        exclude_patterns = list(self.cfg.get("exclude", [])) + list(
            indexing_cfg.get("exclude_globs", [])
        )

        candidates: list[tuple[float, str, str]] = []
        for rel_path, content in self.source_archive.items():
            path_score = self._path_match_score(rel_path, query_signals)
            content_score = self._content_match_score(content, query_signals)
            score = path_score + content_score
            if score <= 0:
                continue
            candidates.append((score, rel_path, content))

        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        hits: list[RetrievedChunk] = []
        seen_ids = set(exclude_ids or set())
        for score, rel_path, content in candidates[:max_files]:
            chunks = self._build_live_fallback_chunks(
                rel_path,
                content,
                query_signals,
                base_score=score,
                per_file=per_file,
                context_lines=context_lines,
            )
            for hit in chunks:
                if hit.record.chunk_id in seen_ids:
                    continue
                hits.append(hit)
                seen_ids.add(hit.record.chunk_id)
        return hits

    def _matches_any_exclude(self, path: str, patterns: list[str]) -> bool:
        normalized = path.replace("\\", "/")
        for pattern in patterns:
            if (
                fnmatch.fnmatch(normalized, pattern)
                or fnmatch.fnmatch(Path(normalized).name, pattern)
                or pattern in normalized.split("/")
            ):
                return True
        return False

    def _path_match_score(self, rel_path: str, query_signals: dict[str, Any]) -> float:
        lowered = rel_path.lower()
        score = 0.0
        for term in query_signals["exact_terms"]:
            if term == lowered:
                score += 1.8
            elif term in lowered:
                score += 1.1
        for token in query_signals["tokens"]:
            if token in lowered:
                score += 0.2
        return score

    def _content_match_score(
        self, content: str, query_signals: dict[str, Any]
    ) -> float:
        lowered = content.lower()
        score = 0.0
        for term in query_signals["exact_terms"]:
            if term and term in lowered:
                score += 0.9
        token_matches = 0
        for token in query_signals["tokens"]:
            if token in lowered:
                token_matches += 1
        score += min(0.8, token_matches * 0.08)
        return score

    def _build_live_fallback_chunks(
        self,
        rel_path: str,
        content: str,
        query_signals: dict[str, Any],
        *,
        base_score: float,
        per_file: int,
        context_lines: int,
    ) -> list[RetrievedChunk]:
        lines = content.splitlines()
        if not lines:
            return []

        line_numbers = self._matching_line_numbers(lines, query_signals)
        if not line_numbers:
            line_numbers = [1]
        kind = self._live_chunk_kind(rel_path)
        source_kind = classify_source_kind(rel_path)
        publication_tier = (
            "supporting"
            if source_kind in {"test", "fixture", "example", "generated"}
            else "core"
        )
        trust_score = 0.78 if kind == "code" else 0.68
        hits: list[RetrievedChunk] = []
        for line_number in line_numbers[:per_file]:
            start = max(1, line_number - context_lines // 2)
            end = min(len(lines), start + context_lines - 1)
            snippet = "\n".join(lines[start - 1 : end]).strip()
            heading = (
                f"Live repo fallback: {rel_path}\n"
                f"Lines: {start}-{end}\n"
                f"Reason: exact-match fallback during deep research\n\n"
            )
            text = heading + snippet
            chunk_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            record = ChunkRecord(
                chunk_id=f"live:{rel_path}:{start}:{chunk_hash[:8]}",
                kind=kind,
                source_key=rel_path,
                text=text,
                chunk_hash=chunk_hash,
                title=Path(rel_path).name,
                file_path="" if kind == "repo_doc" else rel_path,
                doc_path=rel_path if kind == "repo_doc" else "",
                source_kind=source_kind,
                publication_tier=publication_tier,
                trust_score=trust_score,
                start_line=start,
                end_line=end,
                metadata={
                    "chunk_subtype": "live_repo_fallback",
                    "doc_origin": "repo" if kind == "repo_doc" else "",
                },
            )
            hits.append(
                RetrievedChunk(record=record, score=min(2.5, base_score + 0.15))
            )
        return hits

    def _matching_line_numbers(
        self,
        lines: list[str],
        query_signals: dict[str, Any],
    ) -> list[int]:
        matches: list[int] = []
        terms = [*query_signals["exact_terms"], *query_signals["tokens"]]
        for idx, line in enumerate(lines, start=1):
            lowered = line.lower()
            if any(term in lowered for term in terms if term):
                matches.append(idx)
        return matches

    def _live_chunk_kind(self, rel_path: str) -> str:
        suffix = Path(rel_path).suffix.lower()
        if suffix in self._supported_source_extensions:
            return "code"
        if suffix in DOC_SUFFIXES or classify_source_kind(rel_path) == "docs":
            return "repo_doc"
        return "artifact"
