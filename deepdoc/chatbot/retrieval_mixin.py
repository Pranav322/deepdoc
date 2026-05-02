"""Retrieval mixin for ChatbotQueryService."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
from typing import Any

from .persistence import (
    query_lexical_index,
    similarity_search,
)
from .types import (
    RetrievedChunk,
)

STOPWORD_TOKENS = {
    "a",
    "an",
    "and",
    "any",
    "are",
    "can",
    "does",
    "first",
    "for",
    "from",
    "handle",
    "handled",
    "how",
    "in",
    "is",
    "it",
    "its",
    "of",
    "or",
    "repo",
    "repository",
    "show",
    "that",
    "the",
    "this",
    "to",
    "use",
    "what",
    "went",
    "where",
    "who",
    "which",
    "with",
    "work",
}
DOC_SUFFIXES = {".md", ".mdx", ".txt", ".rst", ".adoc", ".ipynb"}


class RetrievalMixin:
    """Mixin providing retrieval and search methods for ChatbotQueryService."""

    def retrieve_context(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
        *,
        original_question: str | None = None,
        mode: str = "default",
    ) -> dict[str, Any]:
        retrieval_cfg = self._retrieval_profile(mode)
        search_question = original_question or question

        queries = self._expand_query(question, retrieval_cfg)
        code_hits, artifact_hits, doc_hits, relationship_hits, max_raw_semantic_score = (
            self._search_query_batch(
                queries,
                search_question,
                retrieval_cfg,
            )
        )

        followup_queries = self._derive_followup_queries(
            question,
            code_hits,
            artifact_hits,
            doc_hits,
            relationship_hits,
            retrieval_cfg,
        )
        if followup_queries:
            followup_code, followup_artifact, followup_doc, followup_relationship, _ = (
                self._search_query_batch(
                    followup_queries,
                    search_question,
                    retrieval_cfg,
                )
            )
            code_hits = self._merge_hits(
                code_hits,
                followup_code,
                limit=self._candidate_top_k("code", retrieval_cfg),
            )
            artifact_hits = self._merge_hits(
                artifact_hits,
                followup_artifact,
                limit=self._candidate_top_k("artifact", retrieval_cfg),
            )
            doc_hits = self._merge_hits(
                doc_hits,
                followup_doc,
                limit=max(
                    self._candidate_top_k("docs", retrieval_cfg) * 2,
                    retrieval_cfg["top_k_docs"],
                ),
            )
            relationship_hits = self._merge_hits(
                relationship_hits,
                followup_relationship,
                limit=self._candidate_top_k("relationship", retrieval_cfg),
            )

        code_hits, artifact_hits, doc_hits, relationship_hits = (
            self._graph_neighbor_expand(
                code_hits,
                artifact_hits,
                doc_hits,
                relationship_hits,
                retrieval_cfg,
            )
        )
        code_hits = self._chain_retrieve(code_hits, relationship_hits, retrieval_cfg)
        code_hits, artifact_hits, doc_hits, relationship_hits = self._rerank(
            search_question,
            code_hits,
            artifact_hits,
            doc_hits,
            relationship_hits,
            retrieval_cfg,
        )
        code_hits = self._stitch_code_hits(search_question, code_hits, retrieval_cfg)
        return {
            "code_hits": code_hits[: retrieval_cfg["top_k_code"]],
            "artifact_hits": artifact_hits[: retrieval_cfg["top_k_artifact"]],
            "doc_hits": doc_hits[: retrieval_cfg["top_k_docs"]],
            "relationship_hits": relationship_hits[
                : retrieval_cfg.get("top_k_relationship", 6)
            ],
            # Raw cosine similarity from the initial semantic search, used for
            # OOD detection in query().  Graph-expansion hits excluded intentionally.
            "max_raw_semantic_score": max_raw_semantic_score,
        }

    def _multi_query_search(
        self,
        records: list,
        vectors: Any,
        query_vectors: list[list[float]],
        top_k: int,
        *,
        vector_index: Any | None = None,
        question: str = "",
    ) -> list[RetrievedChunk]:
        """Search with multiple query vectors and merge by max score per chunk."""
        if not records:
            return []

        best: dict[str, RetrievedChunk] = {}
        for qv in query_vectors:
            hits = self._similarity_search(
                records, vectors, qv, top_k, vector_index=vector_index
            )
            for hit in hits:
                cid = hit.record.chunk_id
                if cid not in best or hit.score > best[cid].score:
                    best[cid] = hit

        merged = sorted(best.values(), key=lambda h: h.score, reverse=True)
        merged.sort(
            key=lambda hit: (
                self._evidence_priority(
                    hit.record, self._question_support_profile(question)
                ),
                hit.score,
            ),
            reverse=True,
        )
        return merged[:top_k]

    def _lexical_search(
        self,
        corpus: str,
        records: list[Any],
        queries: list[str],
        question: str,
        top_k: int,
    ) -> list[RetrievedChunk]:
        retrieval_cfg = self.chat_cfg["retrieval"]
        if not retrieval_cfg.get("lexical_retrieval", True) or not records:
            return []

        candidate_limit = max(top_k, retrieval_cfg.get("lexical_candidate_limit", 24))
        query_signals = self._query_signals([question, *queries])
        if not query_signals["tokens"] and not query_signals["exact_terms"]:
            return []

        by_chunk_id = {record.chunk_id: record for record in records}
        match_query = self._sqlite_match_query(query_signals)
        if match_query:
            chunk_ids = query_lexical_index(
                self.index_dir,
                corpus,
                match_query,
                candidate_limit,
            )
            hits = [
                RetrievedChunk(
                    record=by_chunk_id[chunk_id],
                    score=max(1.0, self._lexical_score(by_chunk_id[chunk_id], query_signals)),
                )
                for chunk_id in chunk_ids
                if chunk_id in by_chunk_id
            ]
            if hits:
                profile = self._question_support_profile(question)
                hits.sort(
                    key=lambda hit: (self._evidence_priority(hit.record, profile), hit.score),
                    reverse=True,
                )
                return hits[:candidate_limit]

        hits: list[RetrievedChunk] = []
        for record in records:
            score = self._lexical_score(record, query_signals)
            if score <= 0:
                continue
            hits.append(RetrievedChunk(record=record, score=score))

        profile = self._question_support_profile(question)
        hits.sort(
            key=lambda hit: (self._evidence_priority(hit.record, profile), hit.score),
            reverse=True,
        )
        return hits[:candidate_limit]

    @staticmethod
    def _sqlite_match_query(query_signals: dict[str, Any]) -> str:
        terms = []
        for term in sorted(set(query_signals.get("exact_terms", set())) | set(query_signals.get("tokens", set()))):
            cleaned = re.sub(r"[^A-Za-z0-9_./-]+", " ", str(term)).strip()
            for part in cleaned.split():
                if len(part) >= 2:
                    terms.append(part.replace('"', ''))
        return " OR ".join(f'"{term}"' for term in terms[:8])

    def _query_signals(self, questions: list[str]) -> dict[str, Any]:
        token_set: set[str] = set()
        exact_terms: set[str] = set()
        raw_terms: set[str] = set()
        identifier_like = False

        for question in questions:
            if not question:
                continue
            lowered = question.lower()
            for match in re.findall(r"`([^`]+)`|\"([^\"]+)\"|'([^']+)'", question):
                for candidate in match:
                    normalized = candidate.strip().lower()
                    if normalized:
                        exact_terms.add(normalized)
            for raw in re.findall(r"[A-Za-z0-9_./:-]+", question):
                normalized = raw.strip().lower().strip("._:-/")
                if not normalized or len(normalized) < 2:
                    continue
                raw_terms.add(raw.lower())
                identifier_like = (
                    identifier_like
                    or any(ch in raw for ch in "._/-:")
                    or raw.upper() == raw
                    or any(ch.isdigit() for ch in raw)
                )
                if len(normalized) >= 3 and normalized not in STOPWORD_TOKENS:
                    token_set.add(normalized)
                if any(ch in raw for ch in "._/-:") or raw.upper() == raw:
                    exact_terms.add(raw.lower())
            if "/" in lowered:
                for route in re.findall(r"/[A-Za-z0-9{}_<>{}\-./:]+", lowered):
                    exact_terms.add(route.strip())

        return {
            "tokens": sorted(token_set),
            "exact_terms": sorted(exact_terms),
            "raw_terms": sorted(raw_terms),
            "identifier_like": identifier_like,
        }

    def _search_query_batch(
        self,
        queries: list[str],
        question: str,
        retrieval_cfg: dict[str, Any],
    ) -> tuple[
        list[RetrievedChunk],
        list[RetrievedChunk],
        list[RetrievedChunk],
        list[RetrievedChunk],
        float,  # max_pure_semantic_score — embedding similarity before lexical merge
    ]:
        query_vectors = self.embedding_client.embed(queries)
        candidate_top_k_code = self._candidate_top_k("code", retrieval_cfg)
        candidate_top_k_artifact = self._candidate_top_k("artifact", retrieval_cfg)
        candidate_top_k_docs = self._candidate_top_k("docs", retrieval_cfg)
        candidate_top_k_relationship = self._candidate_top_k(
            "relationship", retrieval_cfg
        )

        semantic_code_hits = self._multi_query_search(
            self.code_records,
            self.code_vectors,
            query_vectors,
            candidate_top_k_code,
            vector_index=self.code_index,
            question=question,
        )
        semantic_symbol_hits = self._multi_query_search(
            self.symbol_records,
            self.symbol_vectors,
            query_vectors,
            candidate_top_k_code,
            vector_index=self.symbol_index,
            question=question,
        )
        semantic_artifact_hits = self._multi_query_search(
            self.artifact_records,
            self.artifact_vectors,
            query_vectors,
            candidate_top_k_artifact,
            vector_index=self.artifact_index,
            question=question,
        )
        semantic_doc_summary_hits = self._multi_query_search(
            self.doc_summary_records,
            self.doc_summary_vectors,
            query_vectors,
            candidate_top_k_docs,
            vector_index=self.doc_summary_index,
            question=question,
        )
        semantic_doc_full_hits = self._multi_query_search(
            self.doc_full_records,
            self.doc_full_vectors,
            query_vectors,
            candidate_top_k_docs,
            vector_index=self.doc_full_index,
            question=question,
        )
        semantic_repo_doc_hits = self._multi_query_search(
            self.repo_doc_records,
            self.repo_doc_vectors,
            query_vectors,
            candidate_top_k_docs,
            vector_index=self.repo_doc_index,
            question=question,
        )
        lexical_code_hits = self._lexical_search(
            "code",
            self.code_records,
            queries,
            question,
            candidate_top_k_code,
        )
        lexical_symbol_hits = self._lexical_search(
            "symbol",
            self.symbol_records,
            queries,
            question,
            candidate_top_k_code,
        )
        lexical_artifact_hits = self._lexical_search(
            "artifact",
            self.artifact_records,
            queries,
            question,
            candidate_top_k_artifact,
        )
        lexical_doc_summary_hits = self._lexical_search(
            "doc_summary",
            self.doc_summary_records,
            queries,
            question,
            candidate_top_k_docs,
        )
        lexical_doc_full_hits = self._lexical_search(
            "doc_full",
            self.doc_full_records,
            queries,
            question,
            candidate_top_k_docs,
        )
        lexical_repo_doc_hits = self._lexical_search(
            "repo_doc",
            self.repo_doc_records,
            queries,
            question,
            candidate_top_k_docs,
        )
        lexical_relationship_hits = self._lexical_search(
            "relationship",
            self.relationship_records,
            queries,
            question,
            candidate_top_k_relationship,
        )
        code_hits = self._merge_hits(
            semantic_symbol_hits,
            semantic_code_hits,
            lexical_symbol_hits,
            lexical_code_hits,
            limit=candidate_top_k_code,
        )
        artifact_hits = self._merge_hits(
            semantic_artifact_hits,
            lexical_artifact_hits,
            limit=candidate_top_k_artifact,
        )
        doc_hits = self._merge_hits(
            semantic_doc_summary_hits,
            semantic_doc_full_hits,
            semantic_repo_doc_hits,
            lexical_doc_summary_hits,
            lexical_doc_full_hits,
            lexical_repo_doc_hits,
            limit=max(candidate_top_k_docs * 2, retrieval_cfg["top_k_docs"]),
        )
        semantic_relationship_hits = self._multi_query_search(
            self.relationship_records,
            self.relationship_vectors,
            query_vectors,
            candidate_top_k_relationship,
            vector_index=self.relationship_index,
            question=question,
        )
        relationship_hits = self._merge_hits(
            semantic_relationship_hits,
            lexical_relationship_hits,
            limit=candidate_top_k_relationship,
        )

        # Max pure-embedding similarity score, captured BEFORE lexical merge.
        # Lexical hits can have inflated scores from token overlap even for
        # out-of-scope questions, so only semantic scores are reliable for OOD.
        pure_semantic_hits = (
            semantic_code_hits
            + semantic_symbol_hits
            + semantic_doc_summary_hits
            + semantic_doc_full_hits
            + semantic_repo_doc_hits
        )
        max_pure_semantic_score: float = (
            max(float(h.score) for h in pure_semantic_hits)
            if pure_semantic_hits
            else 0.0
        )

        return code_hits, artifact_hits, doc_hits, relationship_hits, max_pure_semantic_score

    def _candidate_top_k(self, corpus: str, retrieval_cfg: dict[str, Any]) -> int:
        if corpus == "code":
            return retrieval_cfg.get(
                "candidate_top_k_code", retrieval_cfg["top_k_code"]
            )
        if corpus == "artifact":
            return retrieval_cfg.get(
                "candidate_top_k_artifact", retrieval_cfg["top_k_artifact"]
            )
        if corpus == "docs":
            return retrieval_cfg.get(
                "candidate_top_k_docs", retrieval_cfg["top_k_docs"]
            )
        return retrieval_cfg.get(
            "candidate_top_k_relationship",
            retrieval_cfg.get("top_k_relationship", 6),
        )

    def _sort_hits(
        self, hits: list[RetrievedChunk], profile: dict[str, Any]
    ) -> list[RetrievedChunk]:
        return sorted(
            hits,
            key=lambda hit: (self._evidence_priority(hit.record, profile), hit.score),
            reverse=True,
        )

    def _merge_hits(
        self,
        *hit_groups: list[RetrievedChunk],
        limit: int,
    ) -> list[RetrievedChunk]:
        best: dict[str, RetrievedChunk] = {}
        for hits in hit_groups:
            for hit in hits:
                chunk_id = hit.record.chunk_id
                if chunk_id not in best or hit.score > best[chunk_id].score:
                    best[chunk_id] = hit
        return sorted(best.values(), key=lambda hit: hit.score, reverse=True)[:limit]

    def _hit_has_exact_query_overlap(self, question: str, hit: RetrievedChunk) -> bool:
        record = hit.record
        if record.kind == "relationship":
            return True
        haystack = " ".join(
            [
                record.text or "",
                record.file_path or "",
                record.doc_path or "",
                " ".join(record.symbol_names or []),
            ]
        ).lower()
        tokens = [
            token
            for token in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", question)
            if (len(token) >= 4 or "_" in token)
            and token.lower() not in STOPWORD_TOKENS
        ]
        return any(token.lower() in haystack for token in tokens)

    @staticmethod
    def _is_graph_expanded_hit(hit: RetrievedChunk) -> bool:
        subtype = (hit.record.metadata or {}).get("chunk_subtype", "")
        return str(subtype).startswith("graph_") or str(subtype) == "live_repo_fallback"

    def _graph_neighbor_expand(
        self,
        code_hits: list[RetrievedChunk],
        artifact_hits: list[RetrievedChunk],
        doc_hits: list[RetrievedChunk],
        relationship_hits: list[RetrievedChunk],
        retrieval_cfg: dict[str, Any],
    ) -> tuple[
        list[RetrievedChunk],
        list[RetrievedChunk],
        list[RetrievedChunk],
        list[RetrievedChunk],
    ]:
        if not retrieval_cfg.get("graph_neighbor_expansion", False):
            return code_hits, artifact_hits, doc_hits, relationship_hits

        candidate_files: list[str] = []
        candidate_doc_paths: list[str] = []
        candidate_doc_urls: list[str] = []
        seen_files: set[str] = set()
        seen_doc_paths: set[str] = set()
        seen_doc_urls: set[str] = set()

        for hit in code_hits + artifact_hits + doc_hits + relationship_hits:
            record = hit.record
            for file_path in [
                record.file_path,
                *record.linked_file_paths,
                *record.owned_files,
            ]:
                normalized = file_path.strip()
                if normalized and normalized not in seen_files:
                    seen_files.add(normalized)
                    candidate_files.append(normalized)
            for doc_path in [record.doc_path, *record.related_doc_paths]:
                normalized = doc_path.strip()
                if normalized and normalized not in seen_doc_paths:
                    seen_doc_paths.add(normalized)
                    candidate_doc_paths.append(normalized)
            for doc_url in [record.doc_url, *record.related_doc_urls]:
                normalized = doc_url.strip()
                if normalized and normalized not in seen_doc_urls:
                    seen_doc_urls.add(normalized)
                    candidate_doc_urls.append(normalized)

        max_files = retrieval_cfg.get("graph_neighbor_max_files", 6)
        code_hits = self._merge_hits(
            code_hits,
            self._expand_hits_by_file(
                candidate_files[:max_files],
                self._code_by_file,
                self.code_records,
                retrieval_cfg.get("graph_neighbor_code_chunks_per_file", 2),
                score=0.72,
                exclude_ids={hit.record.chunk_id for hit in code_hits},
            ),
            limit=self._candidate_top_k("code", retrieval_cfg),
        )
        artifact_hits = self._merge_hits(
            artifact_hits,
            self._expand_hits_by_file(
                candidate_files[:max_files],
                self._artifact_by_file,
                self.artifact_records,
                retrieval_cfg.get("graph_neighbor_artifact_chunks_per_file", 1),
                score=0.66,
                exclude_ids={hit.record.chunk_id for hit in artifact_hits},
            ),
            limit=self._candidate_top_k("artifact", retrieval_cfg),
        )
        relationship_hits = self._merge_hits(
            relationship_hits,
            self._expand_hits_by_file(
                candidate_files[:max_files],
                self._relationship_by_file,
                self.relationship_records,
                retrieval_cfg.get("graph_neighbor_relationship_chunks_per_file", 2),
                score=0.7,
                exclude_ids={hit.record.chunk_id for hit in relationship_hits},
                preferred_subtypes={
                    "graph_neighbors",
                    "call_graph",
                    "framework_context",
                    "import_graph",
                    "symbol_index",
                },
            ),
            limit=self._candidate_top_k("relationship", retrieval_cfg),
        )
        doc_hits = self._merge_hits(
            doc_hits,
            self._expand_doc_hits(
                candidate_doc_paths,
                candidate_doc_urls,
                max_chunks=retrieval_cfg.get("graph_neighbor_max_docs", 4),
                exclude_ids={hit.record.chunk_id for hit in doc_hits},
            ),
            limit=max(
                self._candidate_top_k("docs", retrieval_cfg) * 2,
                retrieval_cfg["top_k_docs"],
            ),
        )
        return code_hits, artifact_hits, doc_hits, relationship_hits

    def _lexical_score(self, record: Any, query_signals: dict[str, Any]) -> float:
        haystacks = self._record_haystacks(record)
        text_blob = haystacks["text"]
        metadata_blob = haystacks["metadata"]
        score = 0.0

        for term in query_signals["exact_terms"]:
            if len(term) < 2:
                continue
            if term == haystacks["file_name"] or term == haystacks["file_path"]:
                score += 1.5
            elif term in haystacks["file_path"]:
                score += 1.25
            elif term in haystacks["symbols"]:
                score += 1.15
            elif term in haystacks["title"] or term in haystacks["section"]:
                score += 1.0
            elif term in metadata_blob:
                score += 0.9
            elif term in text_blob:
                score += 0.75

        token_matches = 0
        for token in query_signals["tokens"]:
            if token in STOPWORD_TOKENS or len(token) < 3:
                continue
            if token in haystacks["file_path"] or token in haystacks["symbols"]:
                token_matches += 2
            elif token in metadata_blob:
                token_matches += 1
            elif token in text_blob:
                token_matches += 1
        if token_matches:
            score += min(1.2, 0.12 * token_matches)

        if query_signals["identifier_like"] and score > 0:
            score += 0.2
        return score

    def _record_haystacks(self, record: Any) -> dict[str, str]:
        file_path = (
            getattr(record, "file_path", "") or getattr(record, "doc_path", "")
        ).lower()
        return {
            "text": getattr(record, "text", "").lower(),
            "metadata": " ".join(
                filter(
                    None,
                    [
                        getattr(record, "title", ""),
                        getattr(record, "section_name", ""),
                        getattr(record, "doc_path", ""),
                        getattr(record, "doc_url", ""),
                        getattr(record, "framework", ""),
                        " ".join(getattr(record, "symbol_names", []) or []),
                        " ".join(getattr(record, "imports_summary", []) or []),
                        " ".join(getattr(record, "linked_file_paths", []) or []),
                        " ".join(getattr(record, "related_doc_paths", []) or []),
                        " ".join(getattr(record, "related_doc_urls", []) or []),
                    ],
                )
            ).lower(),
            "symbols": " ".join(getattr(record, "symbol_names", []) or []).lower(),
            "file_path": file_path,
            "file_name": Path(file_path).name.lower() if file_path else "",
            "title": getattr(record, "title", "").lower(),
            "section": getattr(record, "section_name", "").lower(),
        }

    def _index_doc_record(self, corpus: str, idx: int, record: Any) -> None:
        if record.doc_path:
            self._docs_by_path.setdefault(record.doc_path, []).append((corpus, idx))
        if record.doc_url:
            self._docs_by_url.setdefault(record.doc_url, []).append((corpus, idx))

    def _question_support_profile(self, question: str) -> dict[str, Any]:
        lower = question.lower()
        supporting_requested = any(
            token in lower
            for token in (
                "test",
                "tests",
                "fixture",
                "fixtures",
                "example",
                "examples",
                "generated",
                "mock",
                "spec",
                "playwright",
                "cypress",
            )
        )
        framework_mentions = re.findall(
            r"\b(falcon|django|express|fastify|laravel|vue|go)\b",
            lower,
        )
        framework_focus = any(
            token in lower
            for token in (
                "route",
                "routes",
                "router",
                "middleware",
                "handler",
                "controller",
                "viewset",
                "store",
                "pinia",
                "props",
                "emit",
                "component",
            )
        )
        query_signals = self._query_signals([question])
        query_mode = "general"
        if query_signals["identifier_like"]:
            query_mode = "identifier"
        elif any(
            token in lower
            for token in ("config", "env", "environment", "setting", "variable")
        ):
            query_mode = "config"
        elif any(
            token in lower
            for token in (
                "runtime",
                "worker",
                "job",
                "queue",
                "scheduler",
                "cron",
                "signal",
                "listener",
            )
        ):
            query_mode = "runtime"
        elif any(
            token in lower
            for token in (
                "flow",
                "lifecycle",
                "request",
                "request flow",
                "end to end",
                "how does",
                "walk through",
                "step by step",
                "trace",
            )
        ):
            query_mode = "flow"
        elif any(
            token in lower
            for token in (
                "architecture",
                "overview",
                "system",
                "why",
                "design",
                "module",
                "explain",
            )
        ):
            query_mode = "architecture"
        return {
            "supporting_requested": supporting_requested,
            "framework_mentions": set(framework_mentions),
            "framework_focus": framework_focus,
            "query_mode": query_mode,
            "exact_terms": query_signals["exact_terms"],
            "identifier_like": query_signals["identifier_like"],
        }

    def _evidence_priority(self, record: Any, profile: dict[str, Any]) -> float:
        priority = 0.0
        supporting_requested = profile.get("supporting_requested")
        if record.publication_tier == "core":
            priority += 1.5 if supporting_requested else 3.0
        elif record.publication_tier == "supporting":
            priority += 2.5 if supporting_requested else 1.5
        else:
            priority += 0.5

        source_kind = record.source_kind or ""
        if source_kind == "product":
            priority += 0.8 if supporting_requested else 2.5
        elif source_kind in {"config", "docs", "ops", "tooling"}:
            priority += 1.2
        elif source_kind in {"test", "fixture", "example", "generated"}:
            priority += 4.5 if supporting_requested else -1.0

        framework = (record.framework or "").lower()
        if framework and framework in profile.get("framework_mentions", set()):
            priority += 1.0
        chunk_subtype = str((record.metadata or {}).get("chunk_subtype", "")).lower()
        if chunk_subtype == "framework_context" and (
            profile.get("framework_focus")
            or framework in profile.get("framework_mentions", set())
        ):
            priority += 2.0

        priority += float(getattr(record, "trust_score", 0.0))
        return priority

    def _chain_retrieve(
        self,
        code_hits: list[RetrievedChunk],
        relationship_hits: list[RetrievedChunk],
        retrieval_cfg: dict[str, Any],
    ) -> list[RetrievedChunk]:
        """Use relationship chunks to pull in code from related files.

        When a relationship chunk (import graph) mentions files that aren't
        already in the code hits, grab their top code chunks too. This lets
        the chatbot see the full picture — e.g., OrderController + the
        OrderService it imports.
        """
        already_seen_files = {hit.record.file_path for hit in code_hits}
        already_seen_ids = {hit.record.chunk_id for hit in code_hits}
        extra_hits: list[RetrievedChunk] = []

        for rel_hit in relationship_hits:
            # Look at files mentioned in the relationship chunk's imports
            for imp in rel_hit.record.imports_summary:
                # Try to extract file paths from import statements
                for file_path, indices in self._code_by_file.items():
                    if file_path in already_seen_files:
                        continue
                    # Match if the import mentions a module/file name that
                    # corresponds to this file path
                    file_stem = Path(file_path).stem
                    file_name = Path(file_path).name
                    if file_stem in imp or file_name in imp or file_path in imp:
                        # Grab the first 2 code chunks from this related file
                        for idx in indices[:2]:
                            record = self.code_records[idx]
                            if record.chunk_id not in already_seen_ids:
                                extra_hits.append(
                                    RetrievedChunk(
                                        record=record,
                                        score=rel_hit.score
                                        * 0.8,  # slightly discount chain-retrieved
                                    )
                                )
                                already_seen_ids.add(record.chunk_id)
                        already_seen_files.add(file_path)

        # Merge: original hits first, then chain-retrieved extras
        return code_hits + extra_hits

    def _rerank(
        self,
        question: str,
        code_hits: list[RetrievedChunk],
        artifact_hits: list[RetrievedChunk],
        doc_hits: list[RetrievedChunk],
        relationship_hits: list[RetrievedChunk],
        retrieval_cfg: dict[str, Any],
    ) -> tuple[
        list[RetrievedChunk],
        list[RetrievedChunk],
        list[RetrievedChunk],
        list[RetrievedChunk],
    ]:
        """LLM-based reranking of candidate chunks for better precision."""
        if not retrieval_cfg.get("rerank", False):
            profile = self._question_support_profile(question)
            return (
                self._sort_hits(code_hits, profile),
                self._sort_hits(artifact_hits, profile),
                self._sort_hits(doc_hits, profile),
                self._sort_hits(relationship_hits, profile),
            )

        candidate_limit = retrieval_cfg.get("rerank_candidate_limit", 32)
        per_kind_limit = retrieval_cfg.get(
            "rerank_candidate_limit_per_kind",
            max(1, candidate_limit // 4),
        )
        preview_chars = retrieval_cfg.get("rerank_preview_chars", 450)
        all_hits = code_hits + artifact_hits + doc_hits + relationship_hits
        if not all_hits:
            return code_hits, artifact_hits, doc_hits, relationship_hits

        candidates = self._balanced_rerank_candidates(
            candidate_limit,
            per_kind_limit,
            code_hits,
            artifact_hits,
            doc_hits,
            relationship_hits,
        )

        # Build numbered list of chunk previews for the LLM
        previews = []
        for i, hit in enumerate(candidates):
            metadata_bits = [
                hit.record.file_path or hit.record.doc_path,
                hit.record.title,
                hit.record.section_name,
                ", ".join(hit.record.symbol_names[:4]),
            ]
            preview = hit.record.text[:preview_chars].replace("\n", " ")
            header = " | ".join(bit for bit in metadata_bits if bit)
            previews.append(f"{i + 1}. [{hit.record.kind}] {header} :: {preview}")

        rerank_prompt = (
            f"Question: {question}\n\n"
            "Rate each chunk's relevance to the question on a scale of 0 to 10. "
            "Return ONLY the scores, one number per line, in the same order.\n\n"
            + "\n".join(previews)
        )

        try:
            raw = self.chat_client.complete(
                "You are a relevance scorer. Output only numbers, one per line.",
                rerank_prompt,
            )
            scores = []
            for line in raw.strip().splitlines():
                cleaned = line.strip().rstrip(".")
                # Strip leading number prefix like "1. " or "1: "
                for sep in (". ", ": ", "- "):
                    if sep in cleaned:
                        cleaned = cleaned.split(sep, 1)[-1].strip()
                try:
                    scores.append(float(cleaned))
                except ValueError:
                    scores.append(0.0)

            # Pad or truncate scores to match candidates
            while len(scores) < len(candidates):
                scores.append(0.0)
            scores = scores[: len(candidates)]

            # Re-sort candidates by LLM relevance score
            profile = self._question_support_profile(question)
            scored_hits = sorted(
                zip(scores, candidates, strict=False),
                key=lambda item: (
                    item[0] + self._evidence_priority(item[1].record, profile),
                    item[1].score,
                ),
                reverse=True,
            )

            # Split back into kind-based buckets
            reranked_code = [h for _, h in scored_hits if h.record.kind == "code"]
            reranked_artifact = [
                h for _, h in scored_hits if h.record.kind == "artifact"
            ]
            reranked_doc = [
                h
                for _, h in scored_hits
                if h.record.kind in {"doc_summary", "doc_full", "repo_doc"}
            ]
            reranked_relationship = [
                h for _, h in scored_hits if h.record.kind == "relationship"
            ]

            return (
                reranked_code,
                reranked_artifact,
                reranked_doc,
                reranked_relationship,
            )

        except Exception:
            # Fallback to original ordering if reranking fails
            profile = self._question_support_profile(question)
            return (
                self._sort_hits(code_hits, profile),
                self._sort_hits(artifact_hits, profile),
                self._sort_hits(doc_hits, profile),
                self._sort_hits(relationship_hits, profile),
            )

    def _balanced_rerank_candidates(
        self,
        candidate_limit: int,
        per_kind_limit: int,
        code_hits: list[RetrievedChunk],
        artifact_hits: list[RetrievedChunk],
        doc_hits: list[RetrievedChunk],
        relationship_hits: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        groups = [
            code_hits,
            artifact_hits,
            doc_hits,
            relationship_hits,
        ]
        candidates: list[RetrievedChunk] = []
        seen_ids: set[str] = set()

        def append_hit(hit: RetrievedChunk) -> None:
            if hit.record.chunk_id in seen_ids or len(candidates) >= candidate_limit:
                return
            candidates.append(hit)
            seen_ids.add(hit.record.chunk_id)

        for hits in groups:
            for hit in hits[:per_kind_limit]:
                append_hit(hit)

        if len(candidates) >= candidate_limit:
            return candidates[:candidate_limit]

        max_group_len = max((len(group) for group in groups), default=0)
        for offset in range(per_kind_limit, max_group_len):
            for hits in groups:
                if offset < len(hits):
                    append_hit(hits[offset])
                if len(candidates) >= candidate_limit:
                    return candidates[:candidate_limit]
        return candidates[:candidate_limit]

    def _select_prompt_hits(
        self,
        question: str,
        code_hits: list[RetrievedChunk],
        artifact_hits: list[RetrievedChunk],
        doc_hits: list[RetrievedChunk],
        relationship_hits: list[RetrievedChunk],
        retrieval_cfg: dict[str, Any],
    ) -> dict[str, list[RetrievedChunk]]:
        profile = self._question_support_profile(question)
        budgets = self._prompt_budgets(profile, retrieval_cfg)
        exact_terms = set(profile.get("exact_terms", []))

        return {
            "code_hits": self._reserve_and_fill_hits(
                code_hits,
                budgets["code"],
                exact_terms=exact_terms,
            ),
            "artifact_hits": self._reserve_and_fill_hits(
                artifact_hits,
                budgets["artifact"],
                exact_terms=exact_terms,
            ),
            "doc_hits": self._reserve_and_fill_hits(
                doc_hits,
                budgets["docs"],
                exact_terms=exact_terms,
            ),
            "relationship_hits": self._reserve_and_fill_hits(
                relationship_hits,
                budgets["relationship"],
                exact_terms=exact_terms,
            ),
        }

    def _reserve_and_fill_hits(
        self,
        hits: list[RetrievedChunk],
        limit: int,
        *,
        exact_terms: set[str],
    ) -> list[RetrievedChunk]:
        if limit <= 0 or not hits:
            return []

        selected: list[RetrievedChunk] = []
        selected_ids: set[str] = set()
        signals = {"exact_terms": exact_terms, "tokens": []}
        for hit in hits:
            if hit.record.chunk_id in selected_ids:
                continue
            if self._is_exact_match_hit(hit, signals):
                selected.append(hit)
                selected_ids.add(hit.record.chunk_id)
            if len(selected) >= min(2, limit):
                break

        for hit in hits:
            if len(selected) >= limit:
                break
            if hit.record.chunk_id in selected_ids:
                continue
            selected.append(hit)
            selected_ids.add(hit.record.chunk_id)
        return selected[:limit]

    def _prompt_budgets(
        self,
        profile: dict[str, Any],
        retrieval_cfg: dict[str, Any],
    ) -> dict[str, int]:
        budgets = {
            "code": retrieval_cfg["max_prompt_code_chunks"],
            "artifact": retrieval_cfg["max_prompt_artifact_chunks"],
            "docs": retrieval_cfg["max_prompt_doc_chunks"],
            "relationship": retrieval_cfg.get("max_prompt_relationship_chunks", 4),
        }
        mode = profile.get("query_mode", "general")
        if mode == "identifier":
            budgets["code"] = max(budgets["code"], 14)
            budgets["artifact"] = max(budgets["artifact"], 6)
            budgets["docs"] = max(4, budgets["docs"])
            budgets["relationship"] = max(budgets["relationship"], 7)
        elif mode == "runtime":
            budgets["code"] = max(budgets["code"], 14)
            budgets["relationship"] = max(budgets["relationship"], 8)
            budgets["artifact"] = max(budgets["artifact"], 6)
            budgets["docs"] = max(budgets["docs"], 6)
        elif mode == "architecture":
            budgets["docs"] = max(budgets["docs"], 8)
            budgets["relationship"] = max(budgets["relationship"], 8)
            budgets["code"] = max(10, budgets["code"] - 1)
        elif mode == "config":
            budgets["artifact"] = max(budgets["artifact"], 8)
            budgets["docs"] = max(budgets["docs"], 6)
            budgets["relationship"] = max(budgets["relationship"], 6)
        elif mode == "flow":
            budgets["code"] = max(budgets["code"], 16)
            budgets["artifact"] = max(budgets["artifact"], 6)
            budgets["docs"] = max(budgets["docs"], 6)
            budgets["relationship"] = max(budgets["relationship"], 8)
        return budgets

    def _expand_query(self, question: str, retrieval_cfg: dict[str, Any]) -> list[str]:
        """Generate alternative search queries via LLM for better recall."""
        if not retrieval_cfg.get("query_expansion", False):
            return [question]

        max_extra = retrieval_cfg.get("expansion_max_queries", 3)
        try:
            expansion_system = (
                "Generate alternative search queries for a codebase search. "
                "Return one query per line, no numbering or bullets. "
                f"Return at most {max_extra} queries. Keep each under 20 words. "
                "Focus on different terminology: function names, class names, "
                "file patterns, technical synonyms."
            )
            raw = self.chat_client.complete(expansion_system, question)
            variants = [
                line.strip() for line in raw.strip().splitlines() if line.strip()
            ]
            variants = variants[:max_extra]
        except Exception:
            variants = []

        return [question] + variants

    def _expand_hits_by_file(
        self,
        file_paths: list[str],
        index_by_file: dict[str, list[int]],
        records: list[Any],
        per_file_limit: int,
        *,
        score: float,
        exclude_ids: set[str],
        preferred_subtypes: set[str] | None = None,
    ) -> list[RetrievedChunk]:
        hits: list[RetrievedChunk] = []
        for file_path in file_paths:
            indices = index_by_file.get(file_path, [])
            if not indices:
                continue
            selected = []
            if preferred_subtypes:
                selected.extend(
                    idx
                    for idx in indices
                    if str(
                        (records[idx].metadata or {}).get("chunk_subtype", "")
                    ).lower()
                    in preferred_subtypes
                )
                selected.extend(idx for idx in indices if idx not in selected)
            else:
                selected = list(indices)
            count = 0
            for idx in selected:
                record = records[idx]
                if record.chunk_id in exclude_ids:
                    continue
                hits.append(RetrievedChunk(record=record, score=score))
                exclude_ids.add(record.chunk_id)
                count += 1
                if count >= per_file_limit:
                    break
        return hits

    def _expand_doc_hits(
        self,
        doc_paths: list[str],
        doc_urls: list[str],
        *,
        max_chunks: int,
        exclude_ids: set[str],
    ) -> list[RetrievedChunk]:
        hits: list[RetrievedChunk] = []
        seen_pairs: set[tuple[str, int]] = set()
        for corpus, mapping_keys, lookup in (
            ("doc_path", doc_paths, self._docs_by_path),
            ("doc_url", doc_urls, self._docs_by_url),
        ):
            del corpus
            for key in mapping_keys:
                for kind, idx in lookup.get(key, []):
                    pair = (kind, idx)
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    if kind == "doc_summary":
                        record = self.doc_summary_records[idx]
                        score = 0.63
                    elif kind == "doc_full":
                        record = self.doc_full_records[idx]
                        score = 0.69
                    else:
                        record = self.repo_doc_records[idx]
                        score = 0.67
                    if record.chunk_id in exclude_ids:
                        continue
                    hits.append(RetrievedChunk(record=record, score=score))
                    exclude_ids.add(record.chunk_id)
                    if len(hits) >= max_chunks:
                        return hits
        return hits

    def _derive_followup_queries(
        self,
        question: str,
        code_hits: list[RetrievedChunk],
        artifact_hits: list[RetrievedChunk],
        doc_hits: list[RetrievedChunk],
        relationship_hits: list[RetrievedChunk],
        retrieval_cfg: dict[str, Any],
    ) -> list[str]:
        if not retrieval_cfg.get("iterative_retrieval", False):
            return []

        max_queries = max(0, retrieval_cfg.get("iterative_max_followup_queries", 2))
        if max_queries == 0:
            return []

        hints: list[str] = []
        seen: set[str] = set()
        for hit in (code_hits + artifact_hits + doc_hits + relationship_hits)[:10]:
            record = hit.record
            candidates = [
                record.file_path,
                Path(record.file_path).name if record.file_path else "",
                *record.owned_files[:3],
                *record.linked_file_paths[:4],
            ]
            candidates.extend(record.symbol_names[:3])
            candidates.extend(
                [
                    record.title,
                    record.section_name,
                    record.doc_path,
                    *record.related_doc_paths[:2],
                    *record.related_doc_urls[:2],
                ]
            )
            candidates.extend(record.related_bucket_slugs[:2])
            for candidate in candidates:
                normalized = candidate.strip()
                if not normalized:
                    continue
                lowered = normalized.lower()
                if lowered in seen or len(normalized) < 3:
                    continue
                seen.add(lowered)
                hints.append(normalized)

        queries: list[str] = []
        for hint in hints:
            queries.append(f"{question}\nRelated focus: {hint}")
            if len(queries) >= max_queries:
                break
        return queries

    def _stitch_code_hits(
        self,
        question: str,
        code_hits: list[RetrievedChunk],
        retrieval_cfg: dict[str, Any],
    ) -> list[RetrievedChunk]:
        if not retrieval_cfg.get("stitch_adjacent_code_chunks", True) or not code_hits:
            return code_hits

        query_signals = self._query_signals([question])
        per_hit = max(0, retrieval_cfg.get("stitch_max_adjacent_chunks", 2))
        if per_hit == 0:
            return code_hits

        selected_ids = {hit.record.chunk_id for hit in code_hits}
        stitched: list[RetrievedChunk] = []
        for position, hit in enumerate(code_hits[: min(4, len(code_hits))]):
            if position > 0 and not self._is_exact_match_hit(hit, query_signals):
                continue
            stitched.extend(
                self._adjacent_code_hits(hit, per_hit=per_hit, exclude_ids=selected_ids)
            )
        return self._merge_hits(
            code_hits,
            stitched,
            limit=self._candidate_top_k("code", retrieval_cfg),
        )

    def _adjacent_code_hits(
        self,
        hit: RetrievedChunk,
        *,
        per_hit: int,
        exclude_ids: set[str],
    ) -> list[RetrievedChunk]:
        file_path = hit.record.file_path
        if not file_path:
            return []
        indices = self._code_by_file_sorted.get(file_path, [])
        if not indices:
            return []

        current_index = None
        for offset, idx in enumerate(indices):
            if self.code_records[idx].chunk_id == hit.record.chunk_id:
                current_index = offset
                break
        if current_index is None:
            return []

        extras: list[RetrievedChunk] = []
        neighbor_offsets: list[int] = []
        for step in range(1, per_hit + 1):
            neighbor_offsets.extend([current_index - step, current_index + step])
        for neighbor_offset in neighbor_offsets:
            if neighbor_offset < 0 or neighbor_offset >= len(indices):
                continue
            record = self.code_records[indices[neighbor_offset]]
            if record.chunk_id in exclude_ids:
                continue
            extras.append(
                RetrievedChunk(record=record, score=max(0.1, hit.score - 0.05))
            )
            exclude_ids.add(record.chunk_id)
        return extras

    def _is_exact_match_hit(
        self,
        hit: RetrievedChunk,
        query_signals: dict[str, Any],
    ) -> bool:
        exact_terms = set(query_signals.get("exact_terms", []))
        if not exact_terms:
            return False
        haystacks = self._record_haystacks(hit.record)
        searchable = {
            haystacks["file_path"],
            haystacks["file_name"],
            haystacks["title"],
            haystacks["section"],
        }
        searchable.update(term for term in haystacks["symbols"].split() if term)
        text_blob = haystacks["text"]
        metadata_blob = haystacks["metadata"]
        return any(
            term in searchable or term in text_blob or term in metadata_blob
            for term in exact_terms
            if term
        )
