"""Runtime query service for the generated chatbot backend."""

from __future__ import annotations

from copy import deepcopy
import fnmatch
import hashlib
import json
from pathlib import Path
import queue
import re
import threading
from typing import Any, Callable

from pydantic import BaseModel, Field

from ..parser import supported_extensions
from ..persistence_v2 import load_plan
from ..source_metadata import classify_source_kind
from .persistence import (
    load_corpus,
    load_source_archive,
    load_source_catalog,
    load_vector_index,
    query_lexical_index,
    similarity_search,
)
from .providers import build_chat_client, build_embedding_client
from .settings import chatbot_allowed_origins, get_chatbot_cfg
from .types import (
    ChunkRecord,
    EvidenceItem,
    ReferenceItem,
    RetrievalDiagnostics,
    RetrievedChunk,
    SourceCatalogEntry,
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
CODE_WORKSPACE_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".php", ".java", ".rb",
    ".rs", ".vue", ".svelte", ".html", ".css", ".scss", ".sass",
}
CODE_WORKSPACE_CONFIG_NAMES = {
    ".env", ".env.example", "docker-compose.yml", "docker-compose.yaml",
    "package.json", "pyproject.toml", "requirements.txt", "composer.json",
    "go.mod", "cargo.toml", "gemfile",
}
CODE_WORKSPACE_CONFIG_SUFFIXES = {".json", ".toml", ".yaml", ".yml", ".ini", ".cfg"}


class QueryRequest(BaseModel):
    """Incoming chatbot query payload."""

    question: str
    history: list[dict[str, str]] = Field(default_factory=list)


class DeepResearchRequest(QueryRequest):
    """Incoming deep-research payload."""

    max_rounds: int = Field(default=3, ge=1, le=6)


class CodeDeepRequest(QueryRequest):
    """Incoming code-deep payload."""

    max_rounds: int = Field(default=4, ge=1, le=8)


class ChatbotQueryService:
    """Query all chatbot corpora and answer with grounded citations."""

    def __init__(self, repo_root: Path, cfg: dict[str, Any], llm: Any = None) -> None:
        self.repo_root = repo_root
        self.cfg = cfg
        self.chat_cfg = get_chatbot_cfg(cfg)
        self.project_name = cfg.get("project_name") or repo_root.name
        self._supported_source_extensions = supported_extensions()
        self.embedding_client = build_embedding_client(cfg)
        self.chat_client = build_chat_client(cfg)
        self._llm = llm or self.chat_client
        self.plan = load_plan(repo_root)
        from .settings import chatbot_index_dir

        self.index_dir = chatbot_index_dir(repo_root, cfg)
        self.code_records, self.code_vectors = load_corpus(self.index_dir, "code")
        self.symbol_records, self.symbol_vectors = load_corpus(self.index_dir, "symbol")
        self.artifact_records, self.artifact_vectors = load_corpus(
            self.index_dir, "artifact"
        )
        self.doc_summary_records, self.doc_summary_vectors = load_corpus(
            self.index_dir, "doc_summary"
        )
        self.doc_full_records, self.doc_full_vectors = load_corpus(
            self.index_dir, "doc_full"
        )
        self.repo_doc_records, self.repo_doc_vectors = load_corpus(
            self.index_dir, "repo_doc"
        )
        self.relationship_records, self.relationship_vectors = load_corpus(
            self.index_dir, "relationship"
        )
        self.code_index = load_vector_index(self.index_dir, "code")
        self.symbol_index = (
            load_vector_index(self.index_dir, "symbol") if self.symbol_records else None
        )
        self.artifact_index = load_vector_index(self.index_dir, "artifact")
        self.doc_summary_index = load_vector_index(self.index_dir, "doc_summary")
        self.doc_full_index = load_vector_index(self.index_dir, "doc_full")
        self.repo_doc_index = load_vector_index(self.index_dir, "repo_doc")
        self.relationship_index = load_vector_index(self.index_dir, "relationship")

        self.source_archive = load_source_archive(self.index_dir)
        self.source_catalog = load_source_catalog(self.index_dir)
        self._source_catalog_by_path: dict[str, SourceCatalogEntry] = {
            entry.file_path: entry for entry in self.source_catalog
        }

        # Build corpus lookups for chain and graph-neighbor expansion.
        self._code_by_file: dict[str, list[int]] = {}
        for idx, record in enumerate(self.code_records):
            self._code_by_file.setdefault(record.file_path, []).append(idx)
        self._code_by_file_sorted: dict[str, list[int]] = {
            file_path: sorted(
                indices,
                key=lambda idx: (
                    self.code_records[idx].start_line,
                    self.code_records[idx].end_line,
                    self.code_records[idx].chunk_id,
                ),
            )
            for file_path, indices in self._code_by_file.items()
        }
        self._artifact_by_file: dict[str, list[int]] = {}
        for idx, record in enumerate(self.artifact_records):
            self._artifact_by_file.setdefault(record.file_path, []).append(idx)
        self._symbol_by_file: dict[str, list[int]] = {}
        for idx, record in enumerate(self.symbol_records):
            self._symbol_by_file.setdefault(record.file_path, []).append(idx)
        self._relationship_by_file: dict[str, list[int]] = {}
        for idx, record in enumerate(self.relationship_records):
            self._relationship_by_file.setdefault(record.file_path, []).append(idx)
        self._docs_by_path: dict[str, list[tuple[str, int]]] = {}
        self._docs_by_url: dict[str, list[tuple[str, int]]] = {}
        for idx, record in enumerate(self.doc_summary_records):
            self._index_doc_record("doc_summary", idx, record)
        for idx, record in enumerate(self.doc_full_records):
            self._index_doc_record("doc_full", idx, record)
        for idx, record in enumerate(self.repo_doc_records):
            self._index_doc_record("repo_doc", idx, record)

    # Minimum score for a hit to appear as a citation. The OOD gate handles
    # out-of-scope answers; this filter prevents weak lexical/coincidental hits
    # from appearing as supporting evidence.
    CITATION_MIN_SCORE: float = 0.40

    # Raw semantic score threshold for out-of-domain detection in query().
    # Aligned with DeepResearcher.OOD_THRESHOLD.
    OOD_THRESHOLD: float = 0.35

    def _get_raw_semantic_max_score(self, question: str) -> float:
        """Return the highest raw cosine similarity score for *question* against
        the code and doc-summary corpora, without graph expansion or reranking.

        Used by DeepResearcher and query() for out-of-domain detection.

        Returns 1.0 in two cases so we never falsely block a valid question:
        - The corpora are empty (no index built yet → let no-context path handle it)
        - Any error during embedding or search
        """
        # If both primary corpora are empty there's nothing to score against —
        # this is a "no index" situation, not an "out of domain" situation.
        if not self.code_records and not self.doc_summary_records:
            return 1.0
        try:
            query_vectors = self.embedding_client.embed([question])
            top_k = 5
            code_hits = self._multi_query_search(
                self.code_records,
                self.code_vectors,
                query_vectors,
                top_k,
                vector_index=self.code_index,
                question=question,
            )
            doc_hits = self._multi_query_search(
                self.doc_summary_records,
                self.doc_summary_vectors,
                query_vectors,
                top_k,
                vector_index=self.doc_summary_index,
                question=question,
            )
            all_hits = code_hits + doc_hits
            if not all_hits:
                return 0.0
            return max(float(h.score) for h in all_hits)
        except Exception:
            return 1.0  # fail open — don't falsely block on errors

    def _ood_result(self, question: str) -> dict[str, Any]:
        """Clean abstention response for out-of-domain questions.
        No LLM call, no citations, no misleading chunk counts.
        """
        project_name = self.project_name
        answer = (
            f"This question doesn't appear to be related to the **{project_name}** codebase.\n\n"
            "No relevant code, documentation, or configuration was found for this query. "
            "Try asking about a specific file, function, API endpoint, data model, or "
            "feature that exists in the project."
        )
        return {
            "answer": answer,
            "code_citations": [],
            "artifact_citations": [],
            "doc_citations": [],
            "repo_doc_citations": [],
            "relationship_citations": [],
            "live_fallback_citations": [],
            "doc_links": [],
            "used_chunks": 0,
            "confidence": "out_of_scope_confidence",
            **self._workspace_defaults(),
        }

    @staticmethod
    def _workspace_defaults() -> dict[str, Any]:
        return {
            "scan_activity": [],
            "primary_files": [],
            "supporting_files": [],
            "tabs": [],
            "snippet_targets": [],
            "code_workspace_citations": [],
            "evidence": [],
            "references": [],
            "diagnostics": {},
        }

    def query(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
        *,
        mode: str = "default",
    ) -> dict[str, Any]:
        retrieval_cfg = self._retrieval_profile(mode)
        context = self.retrieve_context(question, history, mode=mode)

        # Out-of-domain gate: the raw semantic score is captured inside
        # retrieve_context (before graph expansion) at no extra embed cost.
        # If the question has no meaningful overlap with the indexed codebase,
        # return a clean abstention — no LLM call, no misleading citations.
        raw_score = float(context.get("max_raw_semantic_score", 1.0))
        context_hits = (
            list(context.get("code_hits", []))
            + list(context.get("artifact_hits", []))
            + list(context.get("doc_hits", []))
            + list(context.get("relationship_hits", []))
        )
        has_strong_context_hit = any(
            getattr(hit, "score", 0.0) >= self.CITATION_MIN_SCORE
            and self._hit_has_exact_query_overlap(question, hit)
            for hit in context_hits
        )
        if raw_score < self.OOD_THRESHOLD and (
            self.code_records or self.doc_summary_records
        ) and not has_strong_context_hit:
            result = self._ood_result(question)
            result["response_mode"] = mode
            return self._apply_evidence_contract(result, mode=mode)

        code_hits = context["code_hits"]
        artifact_hits = context["artifact_hits"]
        doc_hits = context["doc_hits"]
        relationship_hits = context["relationship_hits"]
        selected = self._select_prompt_hits(
            question,
            code_hits,
            artifact_hits,
            doc_hits,
            relationship_hits,
            retrieval_cfg,
        )
        selected_code = selected["code_hits"]
        selected_artifacts = selected["artifact_hits"]
        selected_docs = selected["doc_hits"]
        selected_relationships = selected["relationship_hits"]

        if not (
            selected_code
            or selected_artifacts
            or selected_docs
            or selected_relationships
        ):
            result = self._no_context_result(question)
            result["response_mode"] = mode
            return self._apply_evidence_contract(result, mode=mode)

        # Step 6: Build prompt and generate answer
        prompt = self._build_prompt(
            question,
            history or [],
            selected_code,
            selected_artifacts,
            selected_docs,
            selected_relationships,
            retrieval_cfg,
        )
        answer = self._complete_with_continuation(self._system_prompt(), prompt)
        all_selected_hits = (
            selected_code + selected_artifacts + selected_docs + selected_relationships
        )

        # Citation filtering: only surface hits that have meaningful semantic similarity.
        # Graph-expansion hits (scores 0.63–0.72) are kept; truly irrelevant hits removed.
        min_score = self.CITATION_MIN_SCORE

        response = {
            "answer": answer,
            "code_citations": [
                self._citation_payload(hit)
                for hit in selected_code
                if hit.score >= min_score
                or self._is_graph_expanded_hit(hit)
                or self._hit_has_exact_query_overlap(question, hit)
            ],
            "artifact_citations": [
                self._citation_payload(hit)
                for hit in selected_artifacts
                if hit.score >= min_score
                or self._is_graph_expanded_hit(hit)
                or self._hit_has_exact_query_overlap(question, hit)
            ],
            "doc_citations": [
                self._citation_payload(hit)
                for hit in selected_docs
                if hit.record.kind in {"doc_summary", "doc_full"}
                and (
                    hit.score >= min_score
                    or self._is_graph_expanded_hit(hit)
                    or self._hit_has_exact_query_overlap(question, hit)
                )
            ],
            "repo_doc_citations": [
                self._citation_payload(hit)
                for hit in selected_docs
                if hit.record.kind == "repo_doc"
                and (
                    hit.score >= min_score
                    or self._is_graph_expanded_hit(hit)
                    or self._hit_has_exact_query_overlap(question, hit)
                )
            ],
            "relationship_citations": [
                self._citation_payload(hit)
                for hit in selected_relationships
                if hit.score >= min_score
                or self._is_graph_expanded_hit(hit)
                or self._hit_has_exact_query_overlap(question, hit)
            ],
            "live_fallback_citations": [
                self._citation_payload(hit)
                for hit in all_selected_hits
                if (hit.record.metadata or {}).get("chunk_subtype")
                == "live_repo_fallback"
            ],
            "doc_links": self._doc_links(
                selected_docs, selected_code + selected_artifacts
            ),
            "used_chunks": len(selected_code)
            + len(selected_artifacts)
            + len(selected_docs)
            + len(selected_relationships),
            "response_mode": mode,
        }
        response = self._finalize_answer_response(
            question,
            response,
            mode=mode,
            system_prompt=self._system_prompt(),
            original_prompt=prompt,
        )
        if self._answer_is_abstention(answer):
            stripped = self._ood_result(question)
            stripped["answer"] = answer
            stripped["response_mode"] = mode
            return self._apply_evidence_contract(stripped, mode=mode)
        return response

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

    def _no_context_result(self, question: str) -> dict[str, Any]:
        answer = (
            f"I couldn't find any indexed code, config, or documentation evidence for `{question}` in this repository.\n\n"
            "This usually means the chatbot index is empty, stale, or the question terms did not match anything retrievable.\n\n"
            "Try re-indexing the repo and asking again with a concrete filename, route, symbol, or module name."
        )
        return {
            "answer": answer,
            "code_citations": [],
            "artifact_citations": [],
            "doc_citations": [],
            "repo_doc_citations": [],
            "relationship_citations": [],
            "live_fallback_citations": [],
            "doc_links": [],
            "used_chunks": 0,
            **self._workspace_defaults(),
        }

    def deep_research(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
        max_rounds: int = 3,
    ) -> dict[str, Any]:
        """Run a DeepResearch session: decompose → retrieve → synthesise.

        Returns a ResearchResult with a comprehensive answer and source citations.
        Requires an LLM client to be configured (llm= at construction time or via settings).

        Args:
            question: The research question to answer.
            max_rounds: Maximum number of sub-questions to explore.

        Returns:
            ResearchResult with fields: original_question, steps, final_answer, all_sources, confidence.
        """
        retrieval_cfg = self.chat_cfg["retrieval"]
        _, response = self._run_research_mode(
            question,
            history,
            mode="deep",
            max_rounds=max_rounds,
            top_k=max(8, retrieval_cfg.get("deep_research_top_k", 10)),
        )
        return response

    def code_deep(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
        max_rounds: int = 4,
        *,
        trace_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        retrieval_cfg = self._retrieval_profile("code_deep")
        trace: list[dict[str, Any]] = []

        def emit(event: dict[str, Any]) -> None:
            payload = dict(event)
            payload["index"] = len(trace) + 1
            trace.append(payload)
            callback = trace_callback
            if callable(callback):
                callback(payload)

        result, response = self._run_research_mode(
            question,
            history,
            mode="code_deep",
            max_rounds=max_rounds,
            top_k=max(
                10,
                int(retrieval_cfg.get("code_deep_top_k", retrieval_cfg["top_k_code"])),
            ),
            trace_callback=emit,
        )
        response["trace"] = trace
        response["file_inventory"] = self._collect_file_inventory(
            question,
            response,
            result.all_sources,
            retrieval_cfg,
            trace,
        )
        response["response_mode"] = "code_deep"
        response["research_mode"] = "code_deep"
        response = self._finalize_answer_response(question, response, mode="code_deep")
        response["trace"] = trace
        response["file_inventory"] = self._collect_file_inventory(
            question,
            response,
            result.all_sources,
            retrieval_cfg,
            trace,
        )
        return response

    def _run_research_mode(
        self,
        question: str,
        history: list[dict[str, str]] | None,
        *,
        mode: str,
        max_rounds: int,
        top_k: int,
        trace_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        from .deep_research import DeepResearcher

        researcher = DeepResearcher(
            service=self,
            llm=self._llm,
            top_k=top_k,
            max_rounds=max_rounds,
            mode=mode,
            trace_callback=trace_callback,
        )
        result = researcher.research(question, history=history or [])
        query_mode = "deep" if mode == "deep" else "code_deep"
        response = self.query(question, history, mode=query_mode)
        response.update(
            {
                "answer": result.final_answer,
                "used_chunks": max(
                    response.get("used_chunks", 0),
                    sum(step.chunks_used for step in result.steps),
                ),
                "confidence": result.confidence,
                "research_mode": mode,
                "research_sources": result.all_sources,
                "response_mode": mode,
            }
        )
        response = self._finalize_answer_response(question, response, mode=mode)
        return result, response

    def _collect_file_inventory(
        self,
        question: str,
        response: dict[str, Any],
        research_sources: list[str],
        retrieval_cfg: dict[str, Any],
        trace: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        limit = max(8, int(retrieval_cfg.get("code_deep_file_inventory_limit", 18)))
        inventory: dict[str, dict[str, Any]] = {}

        def add_entry(
            path: str,
            reason: str,
            *,
            score: float = 0.0,
            source_kind: str = "",
            publication_tier: str = "",
            symbol_names: list[str] | None = None,
            start_line: int = 0,
            end_line: int = 0,
        ) -> None:
            normalized = str(path or "").strip()
            if not normalized:
                return
            item = inventory.setdefault(
                normalized,
                {
                    "file_path": normalized,
                    "score": 0.0,
                    "reasons": set(),
                    "source_kind": source_kind,
                    "publication_tier": publication_tier,
                    "symbol_names": set(),
                    "line_ranges": set(),
                },
            )
            item["score"] = max(float(item.get("score", 0.0)), float(score))
            item["reasons"].add(reason)
            if source_kind and not item.get("source_kind"):
                item["source_kind"] = source_kind
            if publication_tier and not item.get("publication_tier"):
                item["publication_tier"] = publication_tier
            for symbol in symbol_names or []:
                if symbol:
                    item["symbol_names"].add(symbol)
            if start_line and end_line and end_line >= start_line:
                item["line_ranges"].add(f"{start_line}-{end_line}")

        citation_map = {
            "code_citations": "retrieved_code",
            "artifact_citations": "retrieved_artifact",
            "relationship_citations": "retrieved_relationship",
            "live_fallback_citations": "live_fallback",
            "repo_doc_citations": "retrieved_repo_doc",
            "doc_citations": "retrieved_doc",
        }
        for key, reason in citation_map.items():
            for citation in response.get(key, []):
                path = citation.get("file_path") or citation.get("doc_path")
                add_entry(
                    path,
                    reason,
                    score=float(citation.get("score", 0.0) or 0.0),
                    source_kind=str(citation.get("source_kind", "") or ""),
                    publication_tier=str(citation.get("publication_tier", "") or ""),
                    symbol_names=list(citation.get("symbol_names", []) or []),
                    start_line=int(citation.get("start_line", 0) or 0),
                    end_line=int(citation.get("end_line", 0) or 0),
                )

        for path in research_sources:
            add_entry(path, "research_step", score=1.1)

        for event in trace:
            if str(event.get("phase", "")) == "tool_call":
                path = str(event.get("path", "") or "")
                action = str(event.get("action", "") or "")
                if path:
                    add_entry(path, f"tool_{action or 'call'}", score=1.05)

        query_signals = self._query_signals([question])
        archive_candidates: list[tuple[float, str]] = []
        for rel_path in self.source_archive:
            score = self._path_match_score(rel_path, query_signals)
            if score > 0.9:
                archive_candidates.append((score, rel_path))
        archive_candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        for score, rel_path in archive_candidates[:limit]:
            add_entry(rel_path, "path_match", score=score)

        rows: list[dict[str, Any]] = []
        for item in inventory.values():
            rows.append(
                {
                    "file_path": item["file_path"],
                    "score": round(float(item.get("score", 0.0)), 3),
                    "reasons": sorted(item.get("reasons", set())),
                    "source_kind": item.get("source_kind", ""),
                    "publication_tier": item.get("publication_tier", ""),
                    "symbol_names": sorted(item.get("symbol_names", set()))[:8],
                    "line_ranges": sorted(item.get("line_ranges", set()))[:6],
                }
            )
        rows.sort(
            key=lambda item: (float(item.get("score", 0.0)), item["file_path"]),
            reverse=True,
        )
        return rows[:limit]

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

    def _citation_payload(self, hit: RetrievedChunk) -> dict[str, Any]:
        record = hit.record
        return {
            "kind": record.kind,
            "file_path": record.file_path,
            "doc_path": record.doc_path,
            "doc_url": record.doc_url,
            "title": record.title,
            "section_name": record.section_name,
            "start_line": record.start_line,
            "end_line": record.end_line,
            "symbol_names": record.symbol_names,
            "artifact_type": record.artifact_type,
            "text": record.text,
            "language": record.language,
            "source_kind": record.source_kind,
            "publication_tier": record.publication_tier,
            "framework": record.framework,
            "metadata": record.metadata,
            "score": hit.score,
        }

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
    def _answer_is_abstention(answer: str) -> bool:
        lower = answer.lower()
        markers = (
            "not answerable from",
            "doesn't appear to be related",
            "does not appear to be related",
            "no relevant code",
            "no relevant sources",
            "context does not contain",
            "retrieved context does not contain",
            "codebase does not contain information",
        )
        return any(marker in lower for marker in markers)

    @staticmethod
    def _is_graph_expanded_hit(hit: RetrievedChunk) -> bool:
        subtype = (hit.record.metadata or {}).get("chunk_subtype", "")
        return str(subtype).startswith("graph_") or str(subtype) == "live_repo_fallback"

    def _index_doc_record(self, corpus: str, idx: int, record: Any) -> None:
        if record.doc_path:
            self._docs_by_path.setdefault(record.doc_path, []).append((corpus, idx))
        if record.doc_url:
            self._docs_by_url.setdefault(record.doc_url, []).append((corpus, idx))

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
            hits = similarity_search(
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

    def _retrieval_profile(self, mode: str) -> dict[str, Any]:
        base = deepcopy(self.chat_cfg["retrieval"])
        mode_name = mode.strip().lower() if isinstance(mode, str) else "default"
        if mode_name == "default":
            return base
        if mode_name == "deep":
            deep_prompt_chars = base.get("deep_mode_max_prompt_chars")
            if isinstance(deep_prompt_chars, int) and deep_prompt_chars > 0:
                base["max_prompt_chars"] = deep_prompt_chars
            return base

        if mode_name == "code_deep":
            code_prompt_chars = base.get("code_deep_mode_max_prompt_chars")
            if isinstance(code_prompt_chars, int) and code_prompt_chars > 0:
                base["max_prompt_chars"] = code_prompt_chars

            code_top_k = base.get("code_deep_top_k")
            if isinstance(code_top_k, int) and code_top_k > 0:
                base["top_k_code"] = max(base.get("top_k_code", code_top_k), code_top_k)
                base["candidate_top_k_code"] = max(
                    base.get("candidate_top_k_code", code_top_k * 2),
                    code_top_k * 2,
                )

            relationship_top_k = base.get("code_deep_top_k_relationship")
            if isinstance(relationship_top_k, int) and relationship_top_k > 0:
                base["top_k_relationship"] = max(
                    base.get("top_k_relationship", relationship_top_k),
                    relationship_top_k,
                )
                base["candidate_top_k_relationship"] = max(
                    base.get("candidate_top_k_relationship", relationship_top_k * 2),
                    relationship_top_k * 2,
                )

            docs_cap = base.get("code_deep_top_k_docs")
            if isinstance(docs_cap, int) and docs_cap > 0:
                base["top_k_docs"] = min(base.get("top_k_docs", docs_cap), docs_cap)

            base["query_expansion"] = True
            base["iterative_retrieval"] = True
            base["graph_neighbor_expansion"] = True
            base["rerank"] = True
            return base

        fast_prompt_chars = base.get("fast_mode_max_prompt_chars")
        if isinstance(fast_prompt_chars, int) and fast_prompt_chars > 0:
            base["max_prompt_chars"] = fast_prompt_chars
        if base.get("fast_mode_use_llm_retrieval_steps", False) is False:
            base["query_expansion"] = False
            base["rerank"] = False
        if base.get("fast_mode_iterative_retrieval", False) is False:
            base["iterative_retrieval"] = False
        return base

    def _complete_with_continuation(self, system: str, user: str) -> str:
        answer_cfg = self.chat_cfg.get("answer", {})
        max_retries = 0
        try:
            max_retries = max(0, int(answer_cfg.get("continuation_retries", 2)))
        except (TypeError, ValueError):
            max_retries = 2
        try:
            context_chars = max(
                400,
                int(answer_cfg.get("continuation_context_chars", 12000)),
            )
        except (TypeError, ValueError):
            context_chars = 12000

        answer = self.chat_client.complete(system, user)
        if not answer:
            return answer

        current = answer
        retries = 0
        while retries < max_retries and self._answer_looks_incomplete(current):
            continuation_prompt = (
                "The previous answer appears incomplete and ended abruptly. "
                "Continue from the exact point where it stopped. "
                "Do not repeat earlier sections. Complete any unfinished bullets, "
                "headings, or sentences, and end with `## Summary`.\n\n"
                "Previous answer tail:\n"
                f"{current[-context_chars:]}"
            )
            continuation = self.chat_client.complete(system, continuation_prompt)
            if not continuation or not continuation.strip():
                break
            merged = self._merge_continuation(current, continuation)
            if merged == current:
                break
            current = merged
            retries += 1
        return current

    def _answer_looks_incomplete(self, answer: str) -> bool:
        if not answer:
            return False
        stripped = answer.strip()
        if len(stripped) < 260:
            return False

        lower = stripped.lower()
        score = 0
        if stripped.count("```") % 2 == 1:
            score += 2
        if re.search(r"(relationships?|dependencies?)\s*:\s*$", lower):
            score += 2
        if stripped.endswith((":", "-", "*", ",", "/", "(")):
            score += 1
        if not re.search(r"[.!?`\)\]]\s*$", stripped) and not stripped.endswith("```"):
            score += 1

        has_structured_sections = any(
            token in lower
            for token in (
                "## overview",
                "## implementation",
                "dependencies & connections",
                "## sources",
            )
        )
        if has_structured_sections and "## summary" not in lower:
            score += 1

        tail_word_match = re.search(r"([a-z0-9_]+)\W*$", lower)
        if tail_word_match and tail_word_match.group(1) in {
            "and",
            "or",
            "with",
            "to",
            "for",
            "of",
            "in",
            "when",
            "if",
            "because",
            "relationships",
            "relationship",
        }:
            score += 1
        return score >= 2

    def _merge_continuation(self, existing: str, continuation: str) -> str:
        left = existing.rstrip()
        right = continuation.strip()
        if not right:
            return left
        if right in left:
            return left

        left_lower = left.lower()
        right_lower = right.lower()
        overlap = 0
        max_overlap = min(len(left_lower), len(right_lower), 800)
        for size in range(max_overlap, 39, -1):
            if left_lower.endswith(right_lower[:size]):
                overlap = size
                break

        if overlap:
            right = right[overlap:].lstrip()
            if not right:
                return left
        return f"{left}\n\n{right}"

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

    def _build_prompt(
        self,
        question: str,
        history: list[dict[str, str]],
        code_hits: list[RetrievedChunk],
        artifact_hits: list[RetrievedChunk],
        doc_hits: list[RetrievedChunk],
        relationship_hits: list[RetrievedChunk] | None = None,
        retrieval_cfg: dict[str, Any] | None = None,
    ) -> str:
        retrieval_settings = retrieval_cfg or self.chat_cfg["retrieval"]
        max_chars = retrieval_settings.get("max_prompt_chars", 120000)
        profile = self._question_support_profile(question)

        history_lines = []
        for item in history[-4:]:
            role = item.get("role", "user")
            content = item.get("content", "")
            if content:
                history_lines.append(f"{role.title()}: {content}")

        sections = [f"Question: {question}"]
        if history_lines:
            sections.append("Conversation:\n" + "\n".join(history_lines))

        used = sum(len(s) for s in sections)
        evidence, _ = self._evidence_from_workspace_rows(
            self._code_workspace_citations(
                {
                    "code_citations": [self._citation_payload(hit) for hit in code_hits],
                    "artifact_citations": [
                        self._citation_payload(hit) for hit in artifact_hits
                    ],
                    "live_fallback_citations": [
                        self._citation_payload(hit)
                        for hit in code_hits
                        if (hit.record.metadata or {}).get("chunk_subtype")
                        == "live_repo_fallback"
                    ],
                }
            ),
            mode="fast",
        )
        if evidence:
            evidence_blocks = [
                "\n".join(
                    [
                        f"[{item.id}] {item.file_path}:{item.start_line}-{item.end_line}",
                        f"kind={item.kind} role={item.role}",
                        item.snippet,
                    ]
                )
                for item in evidence[:12]
            ]
            evidence_text = (
                "Source/config evidence blocks. Use these IDs for implementation claims; "
                "do not cite docs as source proof:\n"
                + "\n\n".join(evidence_blocks)
            )
            sections.append(evidence_text)
            used += len(evidence_text)

        sections_by_mode = {
            "identifier": [
                ("Code context", code_hits),
                ("Artifact context", artifact_hits),
                ("File relationships (imports & symbols)", relationship_hits or []),
                ("Docs context", doc_hits),
            ],
            "config": [
                ("Artifact context", artifact_hits),
                ("Code context", code_hits),
                ("Docs context", doc_hits),
                ("File relationships (imports & symbols)", relationship_hits or []),
            ],
            "architecture": [
                ("Docs context", doc_hits),
                ("File relationships (imports & symbols)", relationship_hits or []),
                ("Code context", code_hits),
                ("Artifact context", artifact_hits),
            ],
            "runtime": [
                ("Code context", code_hits),
                ("File relationships (imports & symbols)", relationship_hits or []),
                ("Artifact context", artifact_hits),
                ("Docs context", doc_hits),
            ],
        }
        for label, hits in sections_by_mode.get(
            profile.get("query_mode", "general"),
            [
                ("File relationships (imports & symbols)", relationship_hits or []),
                ("Code context", code_hits),
                ("Artifact context", artifact_hits),
                ("Docs context", doc_hits),
            ],
        ):
            if not hits:
                continue
            parts = [f"{label}:"]
            for hit in hits:
                chunk_text = hit.record.text
                if used + len(chunk_text) + 10 > max_chars:
                    break
                parts.append(chunk_text)
                used += len(chunk_text) + 2  # account for join separator
            if len(parts) > 1:
                sections.append("\n\n".join(parts))

        return "\n\n".join(sections)

    def _doc_links(
        self,
        doc_hits: list[RetrievedChunk],
        supporting_hits: list[RetrievedChunk],
    ) -> list[dict[str, str]]:
        links: dict[str, dict[str, str]] = {}
        for hit in doc_hits:
            if hit.record.doc_url:
                links[hit.record.doc_url] = {
                    "title": hit.record.title or hit.record.doc_url,
                    "url": hit.record.doc_url,
                    "doc_path": hit.record.doc_path,
                }
            for idx, url in enumerate(hit.record.related_doc_urls):
                title = (
                    hit.record.related_doc_titles[idx]
                    if idx < len(hit.record.related_doc_titles)
                    else hit.record.title or url
                )
                doc_path = (
                    hit.record.related_doc_paths[idx]
                    if idx < len(hit.record.related_doc_paths)
                    else hit.record.doc_path
                )
                links.setdefault(
                    url,
                    {"title": title or url, "url": url, "doc_path": doc_path},
                )
        if self.plan:
            slug_map = {page.slug: page for page in self.plan.pages}
            for hit in supporting_hits:
                for idx, url in enumerate(hit.record.related_doc_urls):
                    title = (
                        hit.record.related_doc_titles[idx]
                        if idx < len(hit.record.related_doc_titles)
                        else url
                    )
                    doc_path = (
                        hit.record.related_doc_paths[idx]
                        if idx < len(hit.record.related_doc_paths)
                        else ""
                    )
                    links.setdefault(
                        url,
                        {"title": title or url, "url": url, "doc_path": doc_path},
                    )
                for slug in hit.record.related_bucket_slugs:
                    page = slug_map.get(slug)
                    if not page:
                        continue
                    url = "/" if page.page_type == "overview" else f"/{page.slug}"
                    links.setdefault(
                        url,
                        {
                            "title": page.title,
                            "url": url,
                            "doc_path": f"{page.slug}.mdx",
                        },
                    )
        return list(links.values())[:5]

    def _finalize_answer_response(
        self,
        question: str,
        response: dict[str, Any],
        *,
        mode: str,
        system_prompt: str | None = None,
        original_prompt: str | None = None,
    ) -> dict[str, Any]:
        response.update(self._workspace_payload(question, response, mode=mode))
        response = self._apply_evidence_contract(response, mode=mode)
        response["answer"] = self._attach_evidence_sources(
            str(response.get("answer", "") or ""),
            response,
        )
        errors, warnings = self._validate_answer_grounding(response)
        self._merge_validation_diagnostics(response, errors=errors, warnings=warnings)
        if (
            errors
            and system_prompt
            and original_prompt
            and not self._answer_is_abstention(str(response.get("answer", "") or ""))
        ):
            correction_prompt = self._build_evidence_correction_prompt(
                question,
                original_prompt,
                response,
                errors,
            )
            corrected = self.chat_client.complete(system_prompt, correction_prompt)
            if corrected and corrected.strip():
                response["answer"] = corrected.strip()
                response.update(self._workspace_payload(question, response, mode=mode))
                response = self._apply_evidence_contract(response, mode=mode)
                retry_errors, retry_warnings = self._validate_answer_grounding(response)
                diagnostics = dict(response.get("diagnostics", {}) or {})
                diagnostics["validation_retried"] = True
                diagnostics["validation_errors"] = retry_errors
                diagnostics["warnings"] = sorted(
                    set(list(diagnostics.get("warnings", []) or []) + retry_warnings)
                )
                if retry_errors:
                    diagnostics["validation_failed_closed"] = True
                    response["answer"] = self._conservative_grounded_answer(
                        question,
                        response,
                        retry_errors,
                    )
                response["diagnostics"] = diagnostics
        else:
            diagnostics = dict(response.get("diagnostics", {}) or {})
            remaining_errors = list(diagnostics.get("validation_errors", []) or [])
            if (
                remaining_errors
                and not self._answer_is_abstention(str(response.get("answer", "") or ""))
            ):
                diagnostics["validation_failed_closed"] = True
                response["answer"] = self._conservative_grounded_answer(
                    question,
                    response,
                    remaining_errors,
                )
                response["diagnostics"] = diagnostics
        return response

    def _attach_evidence_sources(
        self,
        answer: str,
        response: dict[str, Any],
    ) -> str:
        """Add a compact evidence list when a research answer omitted IDs."""
        if self._answer_evidence_ids(answer):
            return answer
        evidence = list(response.get("evidence", []) or [])
        if not evidence:
            return answer
        referenced_paths = {
            path.replace("\\", "/")
            for path in self._answer_file_references(answer)
            if self._is_code_workspace_path(path.replace("\\", "/"), allow_config=True)
        }
        if not referenced_paths:
            return answer
        relevant = [
            item
            for item in evidence
            if str(item.get("file_path", "") or "").replace("\\", "/")
            in referenced_paths
        ]
        if not relevant:
            return answer
        source_lines = [
            f"- `{item.get('file_path')}:{item.get('start_line')}-{item.get('end_line')}` [{item.get('id')}]"
            for item in relevant[:8]
            if item.get("id") and item.get("file_path")
        ]
        if not source_lines:
            return answer
        return answer.rstrip() + "\n\n## Sources\n" + "\n".join(source_lines)

    def _workspace_payload(
        self,
        question: str,
        response: dict[str, Any],
        *,
        mode: str,
    ) -> dict[str, Any]:
        del question
        payload = self._workspace_defaults()
        workspace_rows = self._code_workspace_citations(response)
        payload["code_workspace_citations"] = workspace_rows
        payload["snippet_targets"] = [
            {
                "kind": row.get("kind", "code_workspace"),
                "file_path": row.get("file_path", ""),
                "title": row.get("title", ""),
                "start_line": int(row.get("start_line", 0) or 0),
                "end_line": int(row.get("end_line", 0) or 0),
                "score": float(row.get("score", 0.0) or 0.0),
                "symbol_names": list(row.get("symbol_names", []) or []),
            }
            for row in workspace_rows[:6]
        ]
        file_inventory: dict[str, dict[str, Any]] = {}
        for row in workspace_rows:
            path = str(row.get("file_path", "") or "")
            if not path:
                continue
            item = file_inventory.setdefault(
                path,
                {
                    "file_path": path,
                    "title": Path(path).name or path,
                    "score": 0.0,
                    "reasons": set(),
                    "source_kind": str(row.get("source_kind", "") or ""),
                    "publication_tier": "",
                    "symbol_names": set(),
                    "start_line": int(row.get("start_line", 0) or 0),
                    "end_line": int(row.get("end_line", 0) or 0),
                    "has_text": bool(row.get("text")),
                },
            )
            item["score"] = max(float(item["score"]), float(row.get("score", 0.0) or 0.0))
            item["reasons"].add(str(row.get("reason", "") or "evidence"))
            for symbol in row.get("symbol_names", []) or []:
                item["symbol_names"].add(str(symbol))
        files = []
        for item in file_inventory.values():
            files.append(
                {
                    **item,
                    "reasons": sorted(item["reasons"]),
                    "symbol_names": sorted(item["symbol_names"])[:8],
                }
            )
        files.sort(key=lambda item: (float(item["score"]), item["file_path"]), reverse=True)
        payload["primary_files"] = files[:4]
        payload["supporting_files"] = files[4:10]
        payload["tabs"] = [
            {
                "file_path": item["file_path"],
                "title": item["title"],
                "initial_start_line": item.get("start_line", 0),
                "initial_end_line": item.get("end_line", 0),
                "reason": item["reasons"][0] if item.get("reasons") else "evidence",
            }
            for item in files[:4]
        ]
        payload["scan_activity"] = self._workspace_scan_activity(response, mode=mode)
        return payload

    def _workspace_scan_activity(
        self,
        response: dict[str, Any],
        *,
        mode: str,
    ) -> list[dict[str, Any]]:
        rows = []
        for kind, count, label in (
            ("code", len(response.get("code_citations", [])), "Retrieved code evidence"),
            ("artifact", len(response.get("artifact_citations", [])), "Matched config evidence"),
            ("docs", len(response.get("doc_links", [])), "Linked related docs"),
            ("relationship", len(response.get("relationship_citations", [])), "Expanded relationships"),
        ):
            if count:
                rows.append({"kind": kind, "label": label, "count": count})
        return rows or [{"kind": mode, "label": "Prepared a grounded answer workspace", "count": 0}]

    def _code_workspace_citations(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, int, int, str]] = set()

        def add(citation: dict[str, Any], *, reason: str) -> None:
            if not self._citation_is_code_workspace(citation):
                return
            path = str(citation.get("file_path", "") or "").strip()
            start = int(citation.get("start_line", 0) or 0)
            end = int(citation.get("end_line", 0) or 0)
            text = str(citation.get("text", "") or "")
            if not text or start <= 0 or end < start:
                text, start, end = self._snippet_for_workspace_path(
                    path,
                    start_line=start,
                    end_line=end,
                )
            if not text or start <= 0 or end < start:
                return
            key = (path, start, end, reason)
            if key in seen:
                return
            seen.add(key)
            rows.append(
                {
                    "kind": "code_workspace",
                    "file_path": path,
                    "title": citation.get("title") or Path(path).name or path,
                    "start_line": start,
                    "end_line": end,
                    "text": text,
                    "language": citation.get("language", ""),
                    "symbol_names": list(citation.get("symbol_names", []) or []),
                    "reason": reason,
                    "source_kind": citation.get("source_kind", "") or classify_source_kind(path),
                    "metadata": citation.get("metadata", {}) or {},
                    "score": float(citation.get("score", 0.0) or 0.0),
                    "artifact_type": citation.get("artifact_type", ""),
                }
            )

        for key, reason in (
            ("code_citations", "retrieved_code"),
            ("artifact_citations", "retrieved_artifact"),
            ("live_fallback_citations", "live_fallback"),
        ):
            for citation in response.get(key, []) or []:
                add(citation, reason=reason)

        for reference in self._mentioned_workspace_references(str(response.get("answer", "") or "")):
            add(
                {
                    "kind": "code",
                    "file_path": reference["file_path"],
                    "start_line": reference.get("start_line", 0),
                    "end_line": reference.get("end_line", 0),
                    "source_kind": classify_source_kind(reference["file_path"]),
                },
                reason="mentioned_source",
            )

        by_path: dict[str, dict[str, Any]] = {}
        for row in rows:
            path = row["file_path"]
            existing = by_path.get(path)
            if not existing or float(row.get("score", 0.0)) > float(existing.get("score", 0.0)):
                by_path[path] = row
        return list(by_path.values())[:8]

    def _apply_evidence_contract(
        self,
        response: dict[str, Any],
        *,
        mode: str,
    ) -> dict[str, Any]:
        evidence, diagnostics = self._evidence_from_workspace_rows(
            list(response.get("code_workspace_citations", []) or []),
            mode=mode,
        )
        references = self._reference_items(response)
        diagnostics.evidence_count = len(evidence)
        diagnostics.reference_count = len(references)
        response["evidence"] = [item.to_dict() for item in evidence]
        response["references"] = [item.to_dict() for item in references]
        response["diagnostics"] = diagnostics.to_dict()
        response["code_workspace_citations"] = [
            self._legacy_workspace_citation(item) for item in evidence
        ]
        if not response.get("doc_links") and references:
            response["doc_links"] = [
                {"title": item.title, "url": item.url, "doc_path": item.path}
                for item in references
            ]
        return response

    def _evidence_from_workspace_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        mode: str,
    ) -> tuple[list[EvidenceItem], RetrievalDiagnostics]:
        diagnostics = RetrievalDiagnostics()
        evidence: list[EvidenceItem] = []
        seen: set[tuple[str, int, int]] = set()
        source_catalog = list(getattr(self, "source_catalog", []) or [])
        source_catalog_by_path = dict(getattr(self, "_source_catalog_by_path", {}) or {})
        source_archive = dict(getattr(self, "source_archive", {}) or {})
        for row in rows:
            path = str(row.get("file_path", "") or "").strip()
            if not path or not self._citation_is_code_workspace(row):
                if path:
                    diagnostics.rejected_paths.append(path)
                continue
            start = int(row.get("start_line", 0) or 0)
            end = int(row.get("end_line", 0) or 0)
            snippet = str(row.get("text", "") or "")
            catalog_entry = source_catalog_by_path.get(path)
            if source_catalog and catalog_entry is None:
                diagnostics.rejected_paths.append(path)
                continue
            if catalog_entry is not None and (
                start <= 0 or end < start or end > catalog_entry.total_lines
            ):
                diagnostics.missing_evidence.append(path)
                continue
            if source_archive:
                archive_text = source_archive.get(path, "")
                archive_lines = archive_text.splitlines()
                if (
                    not archive_text
                    or start <= 0
                    or end < start
                    or start > len(archive_lines)
                    or end > len(archive_lines)
                ):
                    diagnostics.missing_evidence.append(path)
                    continue
                snippet = "\n".join(archive_lines[start - 1 : end])
            if not snippet or start <= 0 or end < start:
                diagnostics.missing_evidence.append(path)
                continue
            key = (path, start, end)
            if key in seen:
                continue
            seen.add(key)
            source_kind = str(row.get("source_kind", "") or "") or classify_source_kind(path)
            role = self._evidence_role(row, source_kind=source_kind, mode=mode)
            evidence.append(
                EvidenceItem(
                    id=f"E{len(evidence) + 1}",
                    kind="config" if role == "config" or source_kind == "config" else "source",
                    file_path=path,
                    start_line=start,
                    end_line=end,
                    snippet=snippet,
                    role=role,
                    confidence=round(float(row.get("score", 0.0) or 0.0), 3),
                    title=str(row.get("title", "") or Path(path).name or path),
                    language=str(row.get("language", "") or self._language_for_path(path)),
                    symbol_names=list(row.get("symbol_names", []) or []),
                    source_kind=source_kind,
                    reason=str(row.get("reason", "") or ""),
                )
            )
        if mode == "code_deep" and not evidence:
            diagnostics.warnings.append("No source/config evidence was available for Code Deep.")
        return evidence, diagnostics

    def _evidence_role(self, row: dict[str, Any], *, source_kind: str, mode: str) -> str:
        reason = str(row.get("reason", "") or "")
        if source_kind == "config" or row.get("artifact_type"):
            return "config"
        if reason in {"investigation_step", "research_step"} or mode == "code_deep":
            return "implementation"
        if reason == "mentioned_source":
            return "supporting"
        return "entrypoint"

    @staticmethod
    def _legacy_workspace_citation(item: EvidenceItem) -> dict[str, Any]:
        return {
            "kind": "code_workspace",
            "file_path": item.file_path,
            "title": item.title or Path(item.file_path).name,
            "start_line": item.start_line,
            "end_line": item.end_line,
            "text": item.snippet,
            "language": item.language,
            "symbol_names": item.symbol_names,
            "reason": item.reason or item.role,
            "source_kind": item.source_kind,
            "score": item.confidence,
            "evidence_id": item.id,
        }

    def _reference_items(self, response: dict[str, Any]) -> list[ReferenceItem]:
        references: list[ReferenceItem] = []
        seen: set[tuple[str, str]] = set()

        def add(kind: str, path: str, title: str = "", url: str = "") -> None:
            normalized = str(path or "").strip()
            if not normalized:
                return
            reference_kind = "generated_doc" if kind == "generated_doc" or normalized.startswith("docs/") else "repo_doc"
            key = (reference_kind, normalized)
            if key in seen:
                return
            seen.add(key)
            references.append(
                ReferenceItem(
                    kind=reference_kind,
                    path=normalized,
                    title=title or Path(normalized).name or normalized,
                    url=url,
                )
            )

        for link in response.get("doc_links", []) or []:
            add("generated_doc", str(link.get("doc_path", "") or ""), str(link.get("title", "") or ""), str(link.get("url", "") or ""))
        for citation in response.get("doc_citations", []) or []:
            add("generated_doc", str(citation.get("doc_path", "") or citation.get("file_path", "") or ""), str(citation.get("title", "") or ""), str(citation.get("doc_url", "") or citation.get("url", "") or ""))
        for citation in response.get("repo_doc_citations", []) or []:
            add("repo_doc", str(citation.get("doc_path", "") or citation.get("file_path", "") or ""), str(citation.get("title", "") or ""), str(citation.get("doc_url", "") or citation.get("url", "") or ""))
        return references

    def _snippet_for_workspace_path(
        self,
        file_path: str,
        *,
        start_line: int = 0,
        end_line: int = 0,
    ) -> tuple[str, int, int]:
        content = self.source_archive.get(file_path, "")
        if content:
            lines = content.splitlines()
            start = max(1, int(start_line or 1))
            if start > len(lines):
                return "", start_line, end_line
            end = int(end_line or 0)
            if end < start:
                end = min(len(lines), start + 79)
            end = min(end, len(lines))
            return "\n".join(lines[start - 1 : end]), start, end
        for record in self.code_records + self.symbol_records + self.artifact_records:
            if record.file_path != file_path:
                continue
            if not record.text:
                continue
            return (
                record.text,
                int(start_line or record.start_line or 1),
                int(end_line or record.end_line or record.start_line or 1),
            )
        return "", start_line, end_line

    def _mentioned_workspace_references(self, *texts: str) -> list[dict[str, Any]]:
        references: list[dict[str, Any]] = []
        seen: set[tuple[str, int, int]] = set()
        pattern = re.compile(
            r"(?<![\w/.-])([A-Za-z0-9_./-]+\.(?:py|js|jsx|ts|tsx|go|php|java|rb|rs|vue|svelte|html|css|scss|sass|json|toml|ya?ml|ini|cfg|md|mdx|txt|csv))(?:(?:[:#L](\d+)(?:[-:](\d+))?)|(?![:#L]\d))(?![\w/-])",
            re.IGNORECASE,
        )
        for text in texts:
            for raw_path, raw_start, raw_end in pattern.findall(str(text or "")):
                path = raw_path.strip("`'\".,:;()[]{}")
                if self._is_reference_doc_path(path):
                    continue
                if not self._is_code_workspace_path(path, allow_config=True):
                    continue
                start = int(raw_start or 0)
                end = int(raw_end or start or 0)
                key = (path, start, end)
                if key in seen:
                    continue
                seen.add(key)
                references.append({"file_path": path, "start_line": start, "end_line": end})
        return references

    @staticmethod
    def _is_reference_doc_path(path: str) -> bool:
        normalized = str(path or "").replace("\\", "/").strip().lower()
        return (
            normalized.startswith("docs/")
            or normalized.startswith("site/")
            or normalized.startswith(".deepdoc")
            or Path(normalized).name.startswith(".deepdoc")
            or Path(normalized).suffix in {".md", ".mdx", ".rst", ".adoc", ".ipynb"}
        )

    @staticmethod
    def _is_code_workspace_path(path: str, *, kind: str = "", allow_config: bool = False) -> bool:
        normalized = str(path or "").replace("\\", "/").strip()
        if not normalized:
            return False
        if ChatbotQueryService._is_reference_doc_path(normalized):
            return False
        if str(kind or "").startswith(("doc_", "repo_doc")):
            return False
        if classify_source_kind(normalized) == "generated":
            return False
        suffix = Path(normalized).suffix.lower()
        if suffix in CODE_WORKSPACE_SUFFIXES:
            return True
        if not allow_config:
            return False
        name = Path(normalized).name.lower()
        return name in CODE_WORKSPACE_CONFIG_NAMES or suffix in CODE_WORKSPACE_CONFIG_SUFFIXES

    def _citation_is_code_workspace(self, citation: dict[str, Any]) -> bool:
        path = str(citation.get("file_path", "") or "").strip()
        if not path:
            return False
        kind = str(citation.get("kind", "") or "")
        if kind in {"doc_summary", "doc_full", "repo_doc", "relationship"}:
            return False
        source_kind = str(citation.get("source_kind", "") or "") or classify_source_kind(path)
        return self._is_code_workspace_path(
            path,
            kind=kind,
            allow_config=kind in {"artifact", "code", "code_workspace"} or bool(citation.get("artifact_type")) or source_kind == "config",
        )

    @staticmethod
    def _language_for_path(path: str) -> str:
        suffix = Path(path).suffix.lower()
        return {
            ".py": "python", ".js": "javascript", ".jsx": "javascript",
            ".ts": "typescript", ".tsx": "typescript", ".go": "go",
            ".php": "php", ".java": "java", ".rb": "ruby", ".rs": "rust",
            ".vue": "vue", ".svelte": "svelte", ".html": "html",
            ".css": "css", ".scss": "scss", ".sass": "sass",
            ".json": "json", ".toml": "toml", ".yaml": "yaml", ".yml": "yaml",
        }.get(suffix, suffix.lstrip("."))

    def _merge_validation_diagnostics(
        self,
        response: dict[str, Any],
        *,
        errors: list[str],
        warnings: list[str],
    ) -> None:
        diagnostics = dict(response.get("diagnostics", {}) or {})
        diagnostics["validation_errors"] = errors
        diagnostics["warnings"] = sorted(set(list(diagnostics.get("warnings", []) or []) + warnings))
        response["diagnostics"] = diagnostics

    def _validate_answer_grounding(self, response: dict[str, Any]) -> tuple[list[str], list[str]]:
        answer = str(response.get("answer", "") or "")
        evidence = list(response.get("evidence", []) or [])
        references = list(response.get("references", []) or [])
        evidence_ids = {str(item.get("id", "")) for item in evidence if item.get("id")}
        evidence_paths = {str(item.get("file_path", "") or "").replace("\\", "/") for item in evidence if item.get("file_path")}
        reference_paths = {str(item.get("path", "") or "").replace("\\", "/") for item in references if item.get("path")}
        errors: list[str] = []
        warnings: list[str] = []
        if re.search(r"\bline\s+unknown\b", answer, re.IGNORECASE):
            errors.append("answer_contains_line_unknown")
        cited_ids = self._answer_evidence_ids(answer)
        unknown_ids = sorted(cited_ids - evidence_ids)
        if unknown_ids:
            errors.append("answer_cites_unknown_evidence:" + ",".join(unknown_ids))
        source_refs: set[str] = set()
        doc_refs: set[str] = set()
        for path in self._answer_file_references(answer):
            normalized = path.replace("\\", "/")
            if self._is_reference_doc_path(normalized):
                doc_refs.add(normalized)
            elif self._is_code_workspace_path(normalized, allow_config=True):
                source_refs.add(normalized)
        missing_paths = sorted(
            path
            for path in source_refs
            if path not in evidence_paths
            and not any(item.endswith(f"/{path}") or path.endswith(f"/{item}") for item in evidence_paths)
        )
        if missing_paths:
            errors.append("answer_mentions_unbacked_source_path:" + ",".join(missing_paths[:8]))
        docs_as_proof = sorted(
            path
            for path in doc_refs
            if cited_ids and not (
                path in reference_paths
                or any(item.endswith(f"/{path}") or path.endswith(f"/{item}") for item in reference_paths)
            )
        )
        if docs_as_proof:
            errors.append("answer_uses_docs_as_evidence:" + ",".join(docs_as_proof[:8]))
        if source_refs and evidence_ids and not cited_ids:
            errors.append("answer_mentions_source_paths_without_evidence_ids")
        return errors, warnings

    @staticmethod
    def _answer_evidence_ids(answer: str) -> set[str]:
        ids: set[str] = set()
        for bracketed, bare in re.findall(r"\[(E\d+)\]|\b(E\d+)\b", answer, re.IGNORECASE):
            value = bracketed or bare
            if value:
                ids.add(value.upper())
        return ids

    @staticmethod
    def _answer_file_references(answer: str) -> set[str]:
        pattern = re.compile(
            r"(?<![\w/.-])([A-Za-z0-9_./-]+\.(?:py|js|jsx|ts|tsx|go|php|java|rb|rs|vue|svelte|html|css|scss|sass|json|toml|ya?ml|ini|cfg|md|mdx|txt|csv))(?::\d+(?:-\d+)?)?(?![\w/-])",
            re.IGNORECASE,
        )
        return {match.strip("`'\".,:;()[]{}") for match in pattern.findall(answer)}

    def _build_evidence_correction_prompt(
        self,
        question: str,
        original_prompt: str,
        response: dict[str, Any],
        errors: list[str],
    ) -> str:
        evidence_blocks = []
        for item in response.get("evidence", []) or []:
            evidence_blocks.append(
                "\n".join(
                    [
                        f"[{item.get('id')}] {item.get('file_path')}:{item.get('start_line')}-{item.get('end_line')}",
                        f"kind={item.get('kind')} role={item.get('role')}",
                        str(item.get("snippet", "") or ""),
                    ]
                )
            )
        references = [
            f"- {item.get('kind')}: {item.get('path')} ({item.get('title') or item.get('url') or ''})"
            for item in response.get("references", []) or []
        ]
        return (
            "Your previous answer failed evidence validation.\n\n"
            f"Question: {question}\n\n"
            "Validation errors:\n"
            + "\n".join(f"- {error}" for error in errors)
            + "\n\nRules:\n"
            "- Use only evidence blocks for source/config claims.\n"
            "- Cite implementation claims with IDs like [E1].\n"
            "- Do not mention source files missing from evidence.\n"
            "- Docs are references only, never proof.\n"
            "- Never write line unknown.\n\n"
            "Evidence blocks:\n"
            + ("\n\n".join(evidence_blocks) if evidence_blocks else "(none)")
            + "\n\nReference-only docs:\n"
            + ("\n".join(references) if references else "(none)")
            + "\n\nOriginal retrieval prompt:\n"
            + original_prompt
            + "\n\nReturn only the corrected answer."
        )

    def _conservative_grounded_answer(
        self,
        question: str,
        response: dict[str, Any],
        errors: list[str],
    ) -> str:
        evidence = list(response.get("evidence", []) or [])
        if not evidence:
            return (
                f"I could not produce a validated answer for `{question}` because no source/config evidence "
                "was available after validation."
            )
        lines = [
            f"I could not safely keep the generated answer for `{question}` because it failed evidence validation.",
            "",
            "Validated source evidence available:",
        ]
        for item in evidence[:8]:
            lines.append(f"- [{item.get('id')}] `{item.get('file_path')}:{item.get('start_line')}-{item.get('end_line')}`")
        lines.extend(["", "Validation gaps:", *[f"- {error.split(':', 1)[0]}" for error in errors]])
        return "\n".join(lines)

    def _system_prompt(self) -> str:
        return (
            f"You are a **deep codebase knowledge assistant** for the **{self.project_name}** project. "
            "You answer developer questions using ONLY the retrieved context provided in each query. "
            "Never fabricate file paths, function names, class names, or code that does not appear in the context. "
            "Never generate illustrative example code, stubs, or pseudocode unless that exact code appears in the retrieved context.\n\n"
            "## YOUR PRIMARY DIRECTIVE: BE EXHAUSTIVE\n"
            "Developers are asking you because they want DEEP understanding, not shallow summaries. "
            "Your answers should be as detailed as a senior engineer explaining the code during a code review.\n\n"
            "- **Show the actual code** — always prefer showing full method/function implementations over paraphrasing.\n"
            "- **Explain the logic** — walk through what the code does step-by-step, explaining non-obvious decisions.\n"
            "- **Cover all methods** — if asked about a class/controller/service, explain EVERY method, not just the main ones.\n"
            "- **Follow the chain** — when a method calls another service/function, explain that too with its code.\n"
            "- **Include imports and dependencies** — show what the file imports and how it connects to other files.\n"
            "- **Show data flow** — explain inputs → processing → outputs for each operation.\n"
            "- **Never say 'and more'** — list everything explicitly. Developers need complete information.\n\n"
            "## Evidence hierarchy\n"
            "1. **Source/config evidence blocks with IDs like [E1] are the only implementation proof.** Cite these IDs for code claims.\n"
            "2. **Relationship chunks** show import graphs and symbol indexes — use these to explain how files connect, but ground claims in source/config IDs.\n"
            "3. **Artifact chunks** are source/config proof only when they appear as evidence blocks.\n"
            "4. **Generated docs and repo docs** are reference context only. They can help orientation, but never use them as proof of code behavior.\n"
            "5. If no exact source/config evidence supports a claim, say the source proof was not found.\n\n"
            "## Formatting rules\n"
            "- When referencing code, include the file path and line range plus the evidence ID: `path/to/file.py:10-20` [E1].\n"
            "- Show code in fenced blocks with the correct language tag (```python, ```typescript, etc.).\n"
            "- **Show FULL implementations**, not truncated snippets. If a method is 50 lines, show all 50 lines.\n"
            "- Use headers (##) to organize complex answers by topic/method/component.\n"
            "- Use bullet points for listing attributes, parameters, or quick facts.\n\n"
            "## Grounding rules\n"
            "- If the retrieved context does not contain enough information to fully answer, say exactly what is missing "
            "and suggest a more specific question the user could ask.\n"
            "- Never write `line unknown`, and never invent a file path or evidence ID.\n"
            "- When a related documentation page exists in the doc summaries, mention it naturally "
            '(e.g. "See the Authentication docs for the full auth flow").\n\n'
            "## Answer structure\n"
            "1. **Overview** — one paragraph explaining what this component is and its role in the system.\n"
            "2. **Implementation details** — full code with explanations, organized by method/function.\n"
            "3. **Dependencies & connections** — what this file imports, what calls it, data flow.\n"
            "4. **Sources** — list all files referenced, formatted as `- path/to/file.py:start-end [E1]`.\n"
            "5. **Summary** — always end with a short closing section titled `## Summary` that wraps up the main takeaway in 1-3 sentences."
        )


def create_fastapi_app(repo_root: Path, cfg: dict[str, Any]):
    from fastapi import Body, FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, StreamingResponse

    service = ChatbotQueryService(repo_root, cfg)
    app = FastAPI(title="DeepDoc Chatbot")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=chatbot_allowed_origins(cfg),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/query")
    def query(request: QueryRequest = Body(...)) -> dict[str, Any]:
        try:
            return service.query(request.question, request.history, mode="fast")
        except Exception as exc:
            return JSONResponse(
                status_code=500,
                content={
                    "error": "chatbot_query_failed",
                    "detail": str(exc),
                },
            )

    @app.post("/deep-research")
    def deep_research(request: DeepResearchRequest = Body(...)) -> dict[str, Any]:
        try:
            return service.deep_research(
                request.question,
                request.history,
                max_rounds=request.max_rounds,
            )
        except Exception as exc:
            return JSONResponse(
                status_code=500,
                content={
                    "error": "chatbot_deep_research_failed",
                    "detail": str(exc),
                },
            )

    @app.post("/code-deep")
    def code_deep(request: CodeDeepRequest = Body(...)) -> dict[str, Any]:
        try:
            return service.code_deep(
                request.question,
                request.history,
                max_rounds=request.max_rounds,
            )
        except Exception as exc:
            return JSONResponse(
                status_code=500,
                content={
                    "error": "chatbot_code_deep_failed",
                    "detail": str(exc),
                },
            )

    @app.post("/code-deep/stream")
    def code_deep_stream(request: CodeDeepRequest = Body(...)):
        events: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue()

        def emit(event: dict[str, Any]) -> None:
            events.put(("trace", event))

        def run() -> None:
            try:
                result = service.code_deep(
                    request.question,
                    request.history,
                    max_rounds=request.max_rounds,
                    trace_callback=emit,
                )
                events.put(("result", result))
            except Exception as exc:
                events.put(
                    (
                        "error",
                        {
                            "error": "chatbot_code_deep_failed",
                            "detail": str(exc),
                        },
                    )
                )
            finally:
                events.put(("done", {"status": "done"}))
                events.put(None)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

        def event_stream():
            while True:
                item = events.get()
                if item is None:
                    break
                event_name, payload = item
                yield f"event: {event_name}\n"
                yield f"data: {json.dumps(payload)}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/query-context")
    def query_context(request: QueryRequest = Body(...)) -> dict[str, Any]:
        try:
            context = service.retrieve_context(
                request.question,
                request.history,
                mode="fast",
            )
            selected = service._select_prompt_hits(
                request.question,
                context.get("code_hits", []),
                context.get("artifact_hits", []),
                context.get("doc_hits", []),
                context.get("relationship_hits", []),
                service._retrieval_profile("fast"),
            )
            selected_hits = (
                selected.get("code_hits", [])
                + selected.get("artifact_hits", [])
                + selected.get("doc_hits", [])
                + selected.get("relationship_hits", [])
            )
            payload = {
                "question": request.question,
                "response_mode": "fast",
                "selected_chunks": len(selected_hits),
                "code_citations": [
                    service._citation_payload(hit)
                    for hit in selected.get("code_hits", [])
                ],
                "artifact_citations": [
                    service._citation_payload(hit)
                    for hit in selected.get("artifact_hits", [])
                ],
                "doc_citations": [
                    service._citation_payload(hit)
                    for hit in selected.get("doc_hits", [])
                    if hit.record.kind in {"doc_summary", "doc_full"}
                ],
                "repo_doc_citations": [
                    service._citation_payload(hit)
                    for hit in selected.get("doc_hits", [])
                    if hit.record.kind == "repo_doc"
                ],
                "relationship_citations": [
                    service._citation_payload(hit)
                    for hit in selected.get("relationship_hits", [])
                ],
            }
            payload["doc_links"] = service._doc_links(
                selected.get("doc_hits", []),
                selected.get("code_hits", []) + selected.get("artifact_hits", []),
            )
            payload.update(service._workspace_payload(request.question, payload, mode="fast"))
            payload = service._apply_evidence_contract(payload, mode="fast")
            payload.pop("answer", None)
            return payload
        except Exception as exc:
            return JSONResponse(
                status_code=500,
                content={
                    "error": "chatbot_query_context_failed",
                    "detail": str(exc),
                },
            )

    return app
