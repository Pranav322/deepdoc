"""DeepResearch: Multi-turn agentic research over the codebase.

Decomposes a natural-language question into sub-questions, retrieves evidence
for each, then synthesises a comprehensive answer with source citations.

Everything runs locally — no new cloud dependencies beyond the LLM the user
has already configured in .deepdoc.yaml.

Usage:
    from deepdoc.chatbot.deep_research import DeepResearcher
    researcher = DeepResearcher(service=chatbot_service, llm=llm_client)
    result = researcher.research("How does order cancellation work end to end?")
    print(result.final_answer)
    for source in result.all_sources:
        print(" -", source)
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ResearchStep:
    """One sub-question and its retrieved answer."""

    question: str
    answer: str
    sources: list[str] = field(default_factory=list)
    chunks_used: int = 0


@dataclass
class ResearchResult:
    """Complete result of a deep research session."""

    original_question: str
    steps: list[ResearchStep]
    final_answer: str
    all_sources: list[str] = field(default_factory=list)
    confidence: str = "medium"  # "high" | "medium" | "low"


class DeepResearcher:
    """Multi-turn agentic researcher over the indexed codebase.

    Algorithm:
      1. Decompose the question into 2–4 focused sub-questions.
      2. For each sub-question, retrieve top-k chunks from the chatbot service.
      3. Answer each sub-question using the retrieved evidence.
      4. Synthesise all sub-answers into a final comprehensive answer with citations.
      5. Return the result with source file references.

    This compensates for gaps in static documentation by letting the developer
    ask arbitrary questions that cut across multiple files and services.
    """

    def __init__(self, service: Any, llm: Any, top_k: int = 8, max_rounds: int = 3):
        """
        Args:
            service: ChatbotQueryService instance (has .query(question, top_k) method).
            llm:     LLMClient instance (has .complete(system, user) method).
            top_k:   Number of chunks to retrieve per sub-question.
            max_rounds: Maximum number of sub-questions to explore.
        """
        self.service = service
        self.llm = llm
        self.top_k = top_k
        self.max_rounds = max_rounds

    def research(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
    ) -> ResearchResult:
        """Run a full deep research session for the given question."""
        logger.info(f"[deep_research] Starting research: {question[:80]}")
        history = (history or [])[-4:]

        # Step 1: Decompose
        sub_questions = self._decompose(question, history)
        logger.info(
            f"[deep_research] Decomposed into {len(sub_questions)} sub-questions"
        )

        # Step 2+3: Retrieve and answer each sub-question
        steps: list[ResearchStep] = []
        all_source_files: list[str] = []

        for sq in sub_questions[: self.max_rounds]:
            chunks = self._retrieve_for_question(sq, history, question)
            sources = list(
                dict.fromkeys(
                    getattr(c.record, "file_path", None)
                    or getattr(c.record, "doc_path", None)
                    for c in chunks
                    if getattr(c.record, "file_path", None)
                    or getattr(c.record, "doc_path", None)
                )
            )
            answer = self._answer_step(sq, chunks, history)
            steps.append(
                ResearchStep(
                    question=sq,
                    answer=answer,
                    sources=sources,
                    chunks_used=len(chunks),
                )
            )
            all_source_files.extend(s for s in sources if s not in all_source_files)

        # Step 4: Synthesise
        final_answer = self._synthesise(question, steps, history)
        confidence = self._estimate_confidence(steps)

        return ResearchResult(
            original_question=question,
            steps=steps,
            final_answer=final_answer,
            all_sources=all_source_files,
            confidence=confidence,
        )

    # ── Internal methods ───────────────────────────────────────────────────────

    def _retrieve_for_question(
        self,
        question: str,
        history: list[dict[str, str]],
        original_question: str,
    ) -> list[Any]:
        """Retrieve chunks for a single question using the service's retrieval."""
        try:
            retrieve_context = getattr(self.service, "retrieve_context", None)
            if not callable(retrieve_context):
                return []
            context = retrieve_context(
                question,
                history,
                original_question=original_question,
            )
            all_hits = (
                context.get("code_hits", [])
                + context.get("artifact_hits", [])
                + context.get("doc_hits", [])
                + context.get("relationship_hits", [])
            )
            best_hits: dict[str, Any] = {}
            for hit in all_hits:
                chunk_id = getattr(hit.record, "chunk_id", "")
                if chunk_id and (
                    chunk_id not in best_hits or hit.score > best_hits[chunk_id].score
                ):
                    best_hits[chunk_id] = hit
            fallback = getattr(self.service, "live_research_fallback", None)
            should_fallback = getattr(self.service, "should_use_live_fallback", None)
            if callable(fallback) and callable(should_fallback):
                ranked_hits = sorted(
                    best_hits.values(), key=lambda hit: hit.score, reverse=True
                )
                if should_fallback(question, ranked_hits[: self.top_k]):
                    fallback_hits = fallback(
                        question,
                        history,
                        original_question=original_question,
                        exclude_ids=set(best_hits.keys()),
                    )
                    for hit in fallback_hits:
                        chunk_id = getattr(hit.record, "chunk_id", "")
                        if chunk_id and (
                            chunk_id not in best_hits
                            or hit.score > best_hits[chunk_id].score
                        ):
                            best_hits[chunk_id] = hit
            return sorted(best_hits.values(), key=lambda hit: hit.score, reverse=True)[
                : self.top_k
            ]
        except Exception as e:
            logger.warning(f"[deep_research] Retrieval failed: {e}")
            return []

    def _decompose(self, question: str, history: list[dict[str, str]]) -> list[str]:
        """Ask the LLM to break a broad question into focused sub-questions."""
        system = (
            "You are a technical assistant helping to research a software codebase. "
            "Break the given question into 2–4 focused sub-questions that together "
            "fully answer the original. Each sub-question should target a specific "
            "aspect: data flow, entry point, error handling, configuration, etc. "
            'Return ONLY a JSON array of strings, e.g. ["sub-q1", "sub-q2"].'
        )
        try:
            history_context = _history_context(history)
            response = self.llm.complete(
                system,
                (
                    f"Recent conversation:\n{history_context}\n\nQuestion: {question}"
                    if history_context
                    else f"Question: {question}"
                ),
            )
            sub_qs = _extract_json_array(response.strip())
            if isinstance(sub_qs, list) and sub_qs:
                return [str(q) for q in sub_qs[:4]]
        except Exception as e:
            logger.warning(f"[deep_research] Decomposition failed: {e}")
        # Fallback: use original question as only sub-question
        return [question]

    def _answer_step(
        self,
        question: str,
        chunks: list[Any],
        history: list[dict[str, str]],
    ) -> str:
        """Answer a single sub-question using retrieved evidence chunks."""
        if not chunks:
            return "No relevant evidence found for this sub-question."

        evidence_parts = []
        chunk_chars = 1600
        chat_cfg = getattr(self.service, "chat_cfg", {})
        if isinstance(chat_cfg, dict):
            retrieval_cfg = chat_cfg.get("retrieval", {})
            if isinstance(retrieval_cfg, dict):
                chunk_chars = int(retrieval_cfg.get("deep_research_chunk_chars", 1600))
        for i, c in enumerate(chunks[: self.top_k], 1):
            record = getattr(c, "record", c)
            source = (
                getattr(record, "file_path", None)
                or getattr(record, "doc_path", None)
                or "unknown"
            )
            text = getattr(record, "text", "")[:chunk_chars]
            evidence_parts.append(f"[{i}] From `{source}`:\n{text}")
        evidence_text = "\n\n---\n\n".join(evidence_parts)

        system = (
            "You are a technical assistant answering questions about a software codebase. "
            "Answer ONLY based on the provided evidence. Be specific and cite file paths "
            "using backticks. If the evidence does not contain enough information, say so. "
            "Do not invent function names, file paths, or behaviour not in the evidence."
        )
        user_msg = (
            f"Recent conversation:\n{_history_context(history)}\n\nQuestion: {question}\n\n"
            f"Evidence:\n{evidence_text}\n\n"
            "Answer concisely (3–6 sentences). Cite source files."
        )
        try:
            return self.llm.complete(system, user_msg)
        except Exception as e:
            logger.warning(f"[deep_research] Step answer failed: {e}")
            return f"Could not generate answer: {e}"

    def _synthesise(
        self,
        original_question: str,
        steps: list[ResearchStep],
        history: list[dict[str, str]],
    ) -> str:
        """Synthesise sub-answers into one comprehensive answer."""
        if not steps:
            return "No research steps completed."

        sub_answers = "\n\n".join(
            f"**Sub-question {i + 1}:** {step.question}\n**Answer:** {step.answer}"
            for i, step in enumerate(steps)
        )
        all_sources = list(dict.fromkeys(s for step in steps for s in step.sources))
        sources_note = (
            f"\n\nSources consulted: {', '.join(f'`{s}`' for s in all_sources[:10])}"
            if all_sources
            else ""
        )

        system = (
            "You are a technical assistant synthesising research findings about a codebase. "
            "Write a comprehensive answer to the original question by combining the sub-answers. "
            "Be specific, cite file paths in backticks, and highlight any gaps where evidence "
            "was insufficient. Do not invent information."
        )
        user_msg = (
            f"Recent conversation:\n{_history_context(history)}\n\n"
            f"Original question: {original_question}\n\n"
            f"Research findings:\n{sub_answers}"
            f"{sources_note}\n\n"
            "Write a comprehensive answer (1–3 paragraphs) that directly answers the original question."
        )
        try:
            return self.llm.complete(system, user_msg)
        except Exception as e:
            logger.warning(f"[deep_research] Synthesis failed: {e}")
            # Fallback: concatenate step answers
            return " ".join(step.answer for step in steps)

    def _estimate_confidence(self, steps: list[ResearchStep]) -> str:
        """Estimate confidence based on how many chunks were found."""
        total_chunks = sum(s.chunks_used for s in steps)
        if total_chunks >= 12:
            return "high"
        elif total_chunks >= 5:
            return "medium"
        return "low"


def _history_context(history: list[dict[str, str]]) -> str:
    turns = [
        f"{item.get('role', 'user')}: {item.get('content', '').strip()}"
        for item in history[-4:]
        if item.get("content", "").strip()
    ]
    return "\n".join(turns)


def _extract_json_array(text: str) -> list[Any] | None:
    fenced_match = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", text)
    candidates = [fenced_match.group(1)] if fenced_match else []
    candidates.append(text)
    decoder = json.JSONDecoder()
    for candidate in candidates:
        for match in re.finditer(r"\[", candidate):
            try:
                parsed, _ = decoder.raw_decode(candidate[match.start() :])
            except Exception:
                continue
            if isinstance(parsed, list):
                return parsed
    return None
