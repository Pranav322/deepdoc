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

from .retrieval_mixin import RetrievalMixin
from .answer_mixin import AnswerMixin
from .live_fallback_mixin import LiveFallbackMixin
from .routes import create_fastapi_app, QueryRequest, DeepResearchRequest, CodeDeepRequest

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


class ChatbotQueryService(RetrievalMixin, AnswerMixin, LiveFallbackMixin):
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
        # Bound here so monkeypatches on deepdoc.chatbot.service.similarity_search
        # (used in tests) are picked up at construction time and reach the mixin methods.
        self._similarity_search = similarity_search

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

    def _ood_gate_snapshot(self, question: str, *, mode: str = "default") -> dict[str, Any]:
        """Collect the lightweight OOD signals used before answer generation.

        This intentionally avoids LLM retrieval steps such as query expansion and
        reranking, but still uses the same semantic+lexical candidate search path
        and corpora mix as normal query execution.
        """
        if not (
            self.code_records
            or self.symbol_records
            or self.artifact_records
            or self.doc_summary_records
            or self.doc_full_records
            or self.repo_doc_records
            or self.relationship_records
        ):
            return {
                "max_raw_semantic_score": 1.0,
                "has_strong_context_hit": False,
            }

        retrieval_cfg = deepcopy(self._retrieval_profile(mode))
        retrieval_cfg["query_expansion"] = False
        retrieval_cfg["rerank"] = False

        code_hits, artifact_hits, doc_hits, relationship_hits, raw_score = (
            self._search_query_batch([question], question, retrieval_cfg)
        )
        context_hits = code_hits + artifact_hits + doc_hits + relationship_hits
        has_strong_context_hit = any(
            getattr(hit, "score", 0.0) >= self.CITATION_MIN_SCORE
            and self._hit_has_exact_query_overlap(question, hit)
            for hit in context_hits
        )
        return {
            "max_raw_semantic_score": float(raw_score),
            "has_strong_context_hit": has_strong_context_hit,
        }

    def query(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
        *,
        mode: str = "default",
        token_callback: "Callable[[str], None] | None" = None,
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
        answer = self._complete_with_continuation(self._system_prompt(), prompt, token_callback)
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
        *,
        token_callback: "Callable[[str], None] | None" = None,
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
            token_callback=token_callback,
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
        token_callback: "Callable[[str], None] | None" = None,
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
        researcher.synthesis_token_callback = token_callback
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
