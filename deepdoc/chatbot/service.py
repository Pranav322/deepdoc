"""Runtime query service for the generated chatbot backend."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..persistence_v2 import load_plan
from .persistence import load_corpus, load_vector_index, similarity_search
from .providers import build_chat_client, build_embedding_client
from .settings import chatbot_allowed_origins, get_chatbot_cfg
from .types import RetrievedChunk


class QueryRequest(BaseModel):
    """Incoming chatbot query payload."""

    question: str
    history: list[dict[str, str]] = Field(default_factory=list)


class ChatbotQueryService:
    """Query all chatbot corpora and answer with grounded citations."""

    def __init__(self, repo_root: Path, cfg: dict[str, Any]) -> None:
        self.repo_root = repo_root
        self.cfg = cfg
        self.chat_cfg = get_chatbot_cfg(cfg)
        self.project_name = cfg.get("project_name") or repo_root.name
        self.embedding_client = build_embedding_client(cfg)
        self.chat_client = build_chat_client(cfg)
        self.plan = load_plan(repo_root)
        from .settings import chatbot_index_dir

        self.index_dir = chatbot_index_dir(repo_root, cfg)
        self.code_records, self.code_vectors = load_corpus(self.index_dir, "code")
        self.artifact_records, self.artifact_vectors = load_corpus(self.index_dir, "artifact")
        self.doc_records, self.doc_vectors = load_corpus(self.index_dir, "doc_summary")
        self.relationship_records, self.relationship_vectors = load_corpus(self.index_dir, "relationship")
        self.code_index = load_vector_index(self.index_dir, "code")
        self.artifact_index = load_vector_index(self.index_dir, "artifact")
        self.doc_index = load_vector_index(self.index_dir, "doc_summary")
        self.relationship_index = load_vector_index(self.index_dir, "relationship")

        # Build code record lookup for chain-retrieval
        self._code_by_file: dict[str, list[int]] = {}
        for idx, record in enumerate(self.code_records):
            self._code_by_file.setdefault(record.file_path, []).append(idx)

    def query(self, question: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        retrieval_cfg = self.chat_cfg["retrieval"]

        # Step 1: Query expansion — generate alternative search queries
        queries = self._expand_query(question, retrieval_cfg)

        # Step 2: Embed all query variants in one batch
        query_vectors = self.embedding_client.embed(queries)

        # Step 3: Similarity search per corpus, merge results across variants
        code_hits = self._multi_query_search(
            self.code_records,
            self.code_vectors,
            query_vectors,
            retrieval_cfg["top_k_code"],
            vector_index=self.code_index,
        )
        artifact_hits = self._multi_query_search(
            self.artifact_records,
            self.artifact_vectors,
            query_vectors,
            retrieval_cfg["top_k_artifact"],
            vector_index=self.artifact_index,
        )
        doc_hits = self._multi_query_search(
            self.doc_records,
            self.doc_vectors,
            query_vectors,
            retrieval_cfg["top_k_docs"],
            vector_index=self.doc_index,
        )
        relationship_hits = self._multi_query_search(
            self.relationship_records,
            self.relationship_vectors,
            query_vectors,
            retrieval_cfg.get("top_k_relationship", 6),
            vector_index=self.relationship_index,
        )

        # Step 3.5: Chain-retrieval — use relationship hits to pull in related code
        code_hits = self._chain_retrieve(code_hits, relationship_hits, retrieval_cfg)

        # Step 4: Rerank with LLM for better precision
        code_hits, artifact_hits, doc_hits = self._rerank(
            question, code_hits, artifact_hits, doc_hits, retrieval_cfg,
        )

        # Step 5: Apply final prompt limits
        selected_code = code_hits[: retrieval_cfg["max_prompt_code_chunks"]]
        selected_artifacts = artifact_hits[: retrieval_cfg["max_prompt_artifact_chunks"]]
        selected_docs = doc_hits[: retrieval_cfg["max_prompt_doc_chunks"]]
        selected_relationships = relationship_hits[:4]  # lightweight, always include a few

        if not (selected_code or selected_artifacts or selected_docs):
            return self._no_context_result(question)

        # Step 6: Build prompt and generate answer
        prompt = self._build_prompt(
            question, history or [], selected_code, selected_artifacts,
            selected_docs, selected_relationships,
        )
        answer = self.chat_client.complete(self._system_prompt(), prompt)

        return {
            "answer": answer,
            "code_citations": [
                {
                    "file_path": hit.record.file_path,
                    "start_line": hit.record.start_line,
                    "end_line": hit.record.end_line,
                    "symbol_names": hit.record.symbol_names,
                    "text": hit.record.text,
                    "language": hit.record.language,
                    "source_kind": hit.record.source_kind,
                    "publication_tier": hit.record.publication_tier,
                    "framework": hit.record.framework,
                }
                for hit in selected_code
            ],
            "artifact_citations": [
                {
                    "file_path": hit.record.file_path,
                    "start_line": hit.record.start_line,
                    "end_line": hit.record.end_line,
                    "artifact_type": hit.record.artifact_type,
                    "text": hit.record.text,
                    "language": hit.record.language,
                    "source_kind": hit.record.source_kind,
                    "publication_tier": hit.record.publication_tier,
                    "framework": hit.record.framework,
                }
                for hit in selected_artifacts
            ],
            "doc_links": self._doc_links(selected_docs, selected_code + selected_artifacts),
            "used_chunks": len(selected_code) + len(selected_artifacts) + len(selected_docs) + len(selected_relationships),
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
            "doc_links": [],
            "used_chunks": 0,
        }

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
            variants = [line.strip() for line in raw.strip().splitlines() if line.strip()]
            variants = variants[:max_extra]
        except Exception:
            variants = []

        return [question] + variants

    def _multi_query_search(
        self,
        records: list,
        vectors: Any,
        query_vectors: list[list[float]],
        top_k: int,
        *,
        vector_index: Any | None = None,
    ) -> list[RetrievedChunk]:
        """Search with multiple query vectors and merge by max score per chunk."""
        if not records:
            return []

        best: dict[str, RetrievedChunk] = {}
        for qv in query_vectors:
            hits = similarity_search(records, vectors, qv, top_k, vector_index=vector_index)
            for hit in hits:
                cid = hit.record.chunk_id
                if cid not in best or hit.score > best[cid].score:
                    best[cid] = hit

        merged = sorted(best.values(), key=lambda h: h.score, reverse=True)
        merged.sort(
            key=lambda hit: (
                self._evidence_priority(hit.record, self._question_support_profile("")),
                hit.score,
            ),
            reverse=True,
        )
        return merged[:top_k]

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
                                extra_hits.append(RetrievedChunk(
                                    record=record,
                                    score=rel_hit.score * 0.8,  # slightly discount chain-retrieved
                                ))
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
        retrieval_cfg: dict[str, Any],
    ) -> tuple[list[RetrievedChunk], list[RetrievedChunk], list[RetrievedChunk]]:
        """LLM-based reranking of candidate chunks for better precision."""
        if not retrieval_cfg.get("rerank", False):
            profile = self._question_support_profile(question)
            return (
                self._sort_hits(code_hits, profile),
                self._sort_hits(artifact_hits, profile),
                self._sort_hits(doc_hits, profile),
            )

        candidate_limit = retrieval_cfg.get("rerank_candidate_limit", 20)
        all_hits = code_hits + artifact_hits + doc_hits
        if not all_hits:
            return code_hits, artifact_hits, doc_hits

        candidates = all_hits[:candidate_limit]

        # Build numbered list of chunk previews for the LLM
        previews = []
        for i, hit in enumerate(candidates):
            preview = hit.record.text[:200].replace("\n", " ")
            previews.append(f"{i + 1}. [{hit.record.kind}] {preview}")

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
                zip(scores, candidates),
                key=lambda item: (item[0] + self._evidence_priority(item[1].record, profile), item[1].score),
                reverse=True,
            )

            # Split back into kind-based buckets
            reranked_code = [h for _, h in scored_hits if h.record.kind == "code"]
            reranked_artifact = [h for _, h in scored_hits if h.record.kind == "artifact"]
            reranked_doc = [h for _, h in scored_hits if h.record.kind == "doc_summary"]

            return reranked_code, reranked_artifact, reranked_doc

        except Exception:
            # Fallback to original ordering if reranking fails
            profile = self._question_support_profile(question)
            return (
                self._sort_hits(code_hits, profile),
                self._sort_hits(artifact_hits, profile),
                self._sort_hits(doc_hits, profile),
            )

    def _sort_hits(self, hits: list[RetrievedChunk], profile: dict[str, Any]) -> list[RetrievedChunk]:
        return sorted(
            hits,
            key=lambda hit: (self._evidence_priority(hit.record, profile), hit.score),
            reverse=True,
        )

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
            r"\b(falcon|django|fastapi|flask|express|fastify|laravel|vue|go|nestjs)\b",
            lower,
        )
        return {
            "supporting_requested": supporting_requested,
            "framework_mentions": set(framework_mentions),
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
    ) -> str:
        max_chars = self.chat_cfg["retrieval"].get("max_prompt_chars", 200000)

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

        for label, hits in [
            ("File relationships (imports & symbols)", relationship_hits or []),
            ("Code context", code_hits),
            ("Artifact context", artifact_hits),
            ("Docs summaries", doc_hits),
        ]:
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
        if self.plan:
            slug_map = {page.slug: page for page in self.plan.pages}
            for hit in supporting_hits:
                for slug in hit.record.related_bucket_slugs:
                    page = slug_map.get(slug)
                    if not page:
                        continue
                    url = "/" if page.page_type == "overview" else f"/{page.slug}"
                    links.setdefault(
                        url,
                        {"title": page.title, "url": url, "doc_path": f"{page.slug}.mdx"},
                    )
        return list(links.values())[:5]

    def _system_prompt(self) -> str:
        return (
            f"You are a **deep codebase knowledge assistant** for the **{self.project_name}** project. "
            "You answer developer questions using ONLY the retrieved context provided in each query. "
            "Never fabricate file paths, function names, class names, or code that does not appear in the context.\n\n"
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
            "1. **Code chunks** are primary evidence — show the actual implementation, not summaries.\n"
            "2. **Relationship chunks** show import graphs and symbol indexes — use these to explain how files connect.\n"
            "3. **Artifact chunks** (config files, Dockerfiles, migrations, OpenAPI specs) are supporting evidence.\n"
            "4. **Doc summaries** provide high-level context from generated documentation pages.\n"
            "5. **Supporting material** (tests, examples, fixtures) is valid evidence when explicitly requested.\n\n"
            "## Formatting rules\n"
            "- When referencing code, always include the file path and line range: `path/to/file.py:10-20`.\n"
            "- Show code in fenced blocks with the correct language tag (```python, ```typescript, etc.).\n"
            "- **Show FULL implementations**, not truncated snippets. If a method is 50 lines, show all 50 lines.\n"
            "- Use headers (##) to organize complex answers by topic/method/component.\n"
            "- Use bullet points for listing attributes, parameters, or quick facts.\n\n"
            "## Grounding rules\n"
            "- If the retrieved context does not contain enough information to fully answer, say exactly what is missing "
            "and suggest a more specific question the user could ask.\n"
            "- When a related documentation page exists in the doc summaries, mention it naturally "
            '(e.g. "See the Authentication docs for the full auth flow").\n\n'
            "## Answer structure\n"
            "1. **Overview** — one paragraph explaining what this component is and its role in the system.\n"
            "2. **Implementation details** — full code with explanations, organized by method/function.\n"
            "3. **Dependencies & connections** — what this file imports, what calls it, data flow.\n"
            "4. **Sources** — list all files referenced, formatted as `- path/to/file.py:start-end`."
        )


def create_fastapi_app(repo_root: Path, cfg: dict[str, Any]):
    from fastapi import Body, FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse

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
            return service.query(request.question, request.history)
        except Exception as exc:
            return JSONResponse(
                status_code=500,
                content={
                    "error": "chatbot_query_failed",
                    "detail": str(exc),
                },
            )

    return app
