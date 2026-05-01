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
from time import time
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class ResearchStep:
    """One sub-question and its retrieved answer."""

    question: str
    answer: str
    sources: list[str] = field(default_factory=list)
    chunks_used: int = 0
    max_similarity_score: float = 0.0  # highest raw semantic score among retrieved chunks
    mean_similarity_score: float = 0.0  # average raw score among retrieved chunks


@dataclass
class ResearchResult:
    """Complete result of a deep research session."""

    original_question: str
    steps: list[ResearchStep]
    final_answer: str
    all_sources: list[str] = field(default_factory=list)
    confidence: str = "medium"  # "high" | "medium" | "low" | "out_of_scope_confidence"
    max_semantic_score: float = 0.0  # max raw semantic score seen across all steps
    mean_semantic_score: float = 0.0  # mean raw semantic score across research steps


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

    def __init__(
        self,
        service: Any,
        llm: Any,
        top_k: int = 10,
        max_rounds: int = 3,
        *,
        mode: str = "deep",
        trace_callback: Callable[[dict[str, Any]], None] | None = None,
    ):
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
        self.mode = mode
        self.trace_callback = trace_callback
        self.synthesis_token_callback: "Callable[[str], None] | None" = None

    def _emit_trace(self, phase: str, message: str, **data: Any) -> None:
        callback = self.trace_callback
        if not callable(callback):
            return
        payload: dict[str, Any] = {
            "phase": phase,
            "message": message,
            "mode": self.mode,
            "timestamp": int(time() * 1000),
        }
        for key, value in data.items():
            if value is not None:
                payload[key] = value
        try:
            callback(payload)
        except Exception:
            logger.debug("[deep_research] Trace callback failed", exc_info=True)

    # ── Out-of-domain detection ────────────────────────────────────────────────

    # Minimum raw cosine similarity for a question to be considered in-scope.
    # Below this threshold → return a clean abstention without calling the LLM.
    OOD_THRESHOLD: float = 0.35

    def _check_out_of_domain(self, question: str) -> tuple[bool, float]:
        """Return (is_ood, max_score).  Calls service for a lightweight raw-semantic
        check (no graph expansion, no reranking) to assess domain relevance."""
        get_snapshot = getattr(self.service, "_ood_gate_snapshot", None)
        if callable(get_snapshot):
            try:
                snapshot = get_snapshot(question, mode=self.mode)
                score = float(snapshot.get("max_raw_semantic_score", 1.0))
                has_strong_context_hit = bool(
                    snapshot.get("has_strong_context_hit", False)
                )
                return (
                    score < self.OOD_THRESHOLD and not has_strong_context_hit,
                    score,
                )
            except Exception as e:
                logger.debug(f"[deep_research] OOD snapshot failed: {e}")
        get_score = getattr(self.service, "_get_raw_semantic_max_score", None)
        if not callable(get_score):
            return False, 1.0  # service doesn't support the check — assume in-scope
        try:
            score = float(get_score(question))
            return score < self.OOD_THRESHOLD, score
        except Exception as e:
            logger.debug(f"[deep_research] OOD check failed: {e}")
            return False, 1.0  # fail open

    def _ood_result(self, question: str, max_score: float) -> ResearchResult:
        """Build a clean abstention result for out-of-domain questions."""
        project_name = getattr(self.service, "project_name", "this codebase")
        answer = (
            f"This question doesn't appear to be related to the **{project_name}** codebase.\n\n"
            "No relevant code, documentation, or configuration was found. "
            "Try asking about a specific file, function, API endpoint, "
            "data model, or feature that exists in the project."
        )
        return ResearchResult(
            original_question=question,
            steps=[],
            final_answer=answer,
            all_sources=[],
            confidence="out_of_scope_confidence",
            max_semantic_score=max_score,
        )

    def research(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
    ) -> ResearchResult:
        """Run a full deep research session for the given question."""
        logger.info(f"[deep_research] Starting research: {question[:80]}")
        history = (history or [])[-4:]
        self._emit_trace(
            "start",
            "Starting research session",
            question=question,
            max_rounds=self.max_rounds,
            top_k=self.top_k,
        )

        # Step 0: Out-of-domain gate — short-circuit before any LLM call
        is_ood, raw_score = self._check_out_of_domain(question)
        if is_ood:
            logger.info(
                f"[deep_research] OOD detected (max_score={raw_score:.3f} < "
                f"{self.OOD_THRESHOLD}), returning abstention."
            )
            self._emit_trace(
                "ood_abstention",
                "Question is out of domain — returning abstention without LLM call",
                max_semantic_score=raw_score,
                threshold=self.OOD_THRESHOLD,
            )
            return self._ood_result(question, raw_score)

        # Step 1: Decompose
        sub_questions = self._decompose(question, history)
        logger.info(
            f"[deep_research] Decomposed into {len(sub_questions)} sub-questions"
        )
        self._emit_trace(
            "decompose",
            "Generated focused sub-questions",
            sub_questions=sub_questions,
            sub_question_count=len(sub_questions),
        )

        # Step 2+3: Retrieve and answer each sub-question
        steps: list[ResearchStep] = []
        all_source_files: list[str] = []

        for step_index, sq in enumerate(sub_questions[: self.max_rounds], start=1):
            self._emit_trace(
                "step_start",
                "Researching sub-question",
                step=step_index,
                question=sq,
            )
            step_result = self._agent_loop(
                sq,
                history,
                question,
                step=step_index,
            )
            steps.append(step_result)
            all_source_files.extend(
                s for s in step_result.sources if s not in all_source_files
            )
            self._emit_trace(
                "step_done",
                "Completed sub-question",
                step=step_index,
                question=sq,
                chunks_used=step_result.chunks_used,
                sources=step_result.sources,
            )

        # Step 4: Synthesise
        self._emit_trace(
            "synthesise_start",
            "Synthesising final answer",
            step_count=len(steps),
        )
        final_answer = self._synthesise(question, steps, history)
        max_score = max((s.max_similarity_score for s in steps), default=0.0)
        mean_score = _mean_score(
            s.mean_similarity_score for s in steps if s.mean_similarity_score > 0.0
        )
        confidence = self._estimate_confidence(steps, max_score, mean_score)
        self._emit_trace(
            "done",
            "Finished research session",
            confidence=confidence,
            source_count=len(all_source_files),
            step_count=len(steps),
            max_semantic_score=max_score,
            mean_semantic_score=mean_score,
        )

        return ResearchResult(
            original_question=question,
            steps=steps,
            final_answer=final_answer,
            all_sources=all_source_files,
            confidence=confidence,
            max_semantic_score=max_score,
            mean_semantic_score=mean_score,
        )

    # ── Internal methods ───────────────────────────────────────────────────────

    def _retrieve_for_question(
        self,
        question: str,
        history: list[dict[str, str]],
        original_question: str,
        *,
        step: int,
    ) -> list[Any]:
        """Retrieve chunks for a single question using the service's retrieval."""
        try:
            retrieve_context = getattr(self.service, "retrieve_context", None)
            if not callable(retrieve_context):
                return []
            try:
                context = retrieve_context(
                    question,
                    history,
                    original_question=original_question,
                    mode=self.mode,
                )
            except TypeError:
                context = retrieve_context(
                    question,
                    history,
                    original_question=original_question,
                )

            all_hits = _context_hits(context)
            if question.strip() != original_question.strip():
                try:
                    try:
                        root_context = retrieve_context(
                            original_question,
                            history,
                            original_question=original_question,
                            mode=self.mode,
                        )
                    except TypeError:
                        root_context = retrieve_context(
                            original_question,
                            history,
                            original_question=original_question,
                        )
                    all_hits.extend(_context_hits(root_context))
                except Exception as e:
                    logger.warning(
                        f"[deep_research] Original-question retrieval failed: {e}"
                    )

            best_hits: dict[str, Any] = {}
            for hit in all_hits:
                chunk_id = getattr(hit.record, "chunk_id", "")
                if chunk_id and (
                    chunk_id not in best_hits or hit.score > best_hits[chunk_id].score
                ):
                    best_hits[chunk_id] = hit

            self._emit_trace(
                "retrieve",
                "Retrieved indexed evidence",
                step=step,
                question=question,
                retrieved=len(best_hits),
            )

            fallback = getattr(self.service, "live_research_fallback", None)
            should_fallback = getattr(self.service, "should_use_live_fallback", None)
            if callable(fallback) and callable(should_fallback):
                ranked_hits = sorted(
                    best_hits.values(), key=lambda hit: hit.score, reverse=True
                )
                if should_fallback(question, ranked_hits[: self.top_k]):
                    self._emit_trace(
                        "fallback_start",
                        "Indexed evidence was weak, checking archived source",
                        step=step,
                        question=question,
                    )
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
                    self._emit_trace(
                        "fallback_done",
                        "Added archived-source fallback evidence",
                        step=step,
                        question=question,
                        fallback_hits=len(fallback_hits),
                    )
            return sorted(best_hits.values(), key=lambda hit: hit.score, reverse=True)[
                : self.top_k
            ]
        except Exception as e:
            logger.warning(f"[deep_research] Retrieval failed: {e}")
            self._emit_trace(
                "retrieve_error",
                "Failed to retrieve evidence",
                step=step,
                question=question,
                error=str(e),
            )
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
                ordered = [question] + [
                    str(q).strip() for q in sub_qs if str(q).strip()
                ]
                deduped: list[str] = []
                seen: set[str] = set()
                for item in ordered:
                    key = item.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    deduped.append(item)
                return deduped[:4]
        except Exception as e:
            logger.warning(f"[deep_research] Decomposition failed: {e}")
        # Fallback: use original question as only sub-question
        return [question]

    def _agent_loop(
        self,
        question: str,
        history: list[dict[str, str]],
        original_question: str,
        *,
        step: int,
    ) -> ResearchStep:
        """Run a Tool-Using ReAct loop for a single sub-question."""
        max_iterations = 3
        chunks = self._retrieve_for_question(
            question,
            history,
            original_question,
            step=step,
        )
        sources_used = list(
            dict.fromkeys(
                getattr(c.record, "file_path", None)
                or getattr(c.record, "doc_path", None)
                for c in chunks
                if getattr(c.record, "file_path", None)
                or getattr(c.record, "doc_path", None)
            )
        )
        max_chunk_score = max((getattr(c, "score", 0.0) for c in chunks), default=0.0)
        mean_chunk_score = _mean_score(getattr(c, "score", 0.0) for c in chunks)

        chunk_chars = 3200
        chat_cfg = getattr(self.service, "chat_cfg", {})
        if isinstance(chat_cfg, dict):
            retrieval_cfg = chat_cfg.get("retrieval", {})
            if isinstance(retrieval_cfg, dict):
                chunk_chars = int(retrieval_cfg.get("deep_research_chunk_chars", 3200))

        evidence_parts = []
        for i, c in enumerate(chunks[: self.top_k], 1):
            record = getattr(c, "record", c)
            source = (
                getattr(record, "file_path", None)
                or getattr(record, "doc_path", None)
                or "unknown"
            )
            text = getattr(record, "text", "")[:chunk_chars]
            evidence_parts.append(f"[{i}] From `{source}`:\n{text}")

        system = (
            "You are a software engineering agent answering a specific sub-question. "
            "You have access to the following initial evidence chunks from the codebase.\n\n"
            "If the evidence is sufficient, provide your final answer in plain text.\n"
            "If you need to explore the codebase further, you can use the following tools by outputting a JSON object and NOTHING else:\n"
            '1. read_file: `{"action": "read_file", "path": "file/path.py", "start": 10, "end": 50}`\n'
            '2. grep: `{"action": "grep", "pattern": "def main"}`\n\n'
            "Answer ONLY based on evidence. Prefer a detailed, implementation-level walkthrough.\n\n"
            "## STRICT GROUNDING RULES\n"
            "- Do NOT invent, fabricate, or hallucinate any code, function names, class names, "
            "file paths, or variable names that do not appear verbatim in the evidence chunks above.\n"
            "- Do NOT write example code, stubs, or pseudocode to illustrate an answer — only show "
            "code that literally exists in the retrieved evidence.\n"
            "- If the evidence chunks do not contain a relevant answer to the sub-question, "
            "explicitly state: 'The retrieved evidence does not contain information about this.' "
            "Do not attempt to fill the gap with plausible-sounding but fabricated content."
        )

        history_context = _history_context(history)
        user_msg = (
            f"Recent conversation:\n{history_context}\n\n"
            f"Original Goal: {original_question}\n"
            f"Current Sub-question: {question}\n\n"
            f"Initial Evidence:\n{chr(10).join(evidence_parts)}\n\n"
            "What is your answer or next action?"
        )

        turn_history: list[dict[str, str]] = [{"role": "user", "content": user_msg}]

        for iteration in range(max_iterations):
            try:
                # Provide the full turn history to the LLM
                prompt = "\n\n".join(
                    [f"{msg['role'].upper()}: {msg['content']}" for msg in turn_history]
                )
                response = self._complete_sub_question(system, prompt).strip()
            except Exception as e:
                logger.warning(f"[deep_research] Agent iteration failed: {e}")
                return ResearchStep(
                    question=question,
                    answer=f"Error generating answer: {e}",
                    sources=sources_used,
                    chunks_used=len(chunks),
                    max_similarity_score=max_chunk_score,
                    mean_similarity_score=mean_chunk_score,
                )

            tool_call = _extract_json_object(response)
            if tool_call and isinstance(tool_call, dict) and "action" in tool_call:
                turn_history.append({"role": "assistant", "content": response})
                self._emit_trace(
                    "tool_call",
                    "Running archive inspection tool",
                    step=step,
                    question=question,
                    iteration=iteration + 1,
                    action=str(tool_call.get("action", "")),
                    path=str(tool_call.get("path", "")) or None,
                    pattern=str(tool_call.get("pattern", "")) or None,
                )
                try:
                    output = self._execute_tool(tool_call, sources_used)
                except Exception as e:
                    logger.warning(f"[deep_research] Tool execution failed: {e}")
                    output = f"Error: Tool execution failed - {e}"
                turn_history.append({"role": "tool", "content": output})
                self._emit_trace(
                    "tool_result",
                    "Tool output received",
                    step=step,
                    question=question,
                    iteration=iteration + 1,
                    output_preview=output[:240],
                )
            else:
                self._emit_trace(
                    "step_answer",
                    "Produced sub-question answer",
                    step=step,
                    question=question,
                    chunks_used=len(chunks) + iteration,
                )
                return ResearchStep(
                    question=question,
                    answer=response,
                    sources=sources_used,
                    chunks_used=len(chunks) + iteration,
                    max_similarity_score=max_chunk_score,
                    mean_similarity_score=mean_chunk_score,
                )

        # Fallback if iterations exhaust
        try:
            prompt = "\n\n".join(
                [f"{msg['role'].upper()}: {msg['content']}" for msg in turn_history]
            )
            prompt += (
                "\n\nSYSTEM: Max iterations reached. Please summarize your findings "
                "into a final answer now."
            )
            final_ans = self._complete_sub_question(system, prompt).strip()
        except Exception:
            final_ans = "Exhausted agent iterations. Partial results only."

        return ResearchStep(
            question=question,
            answer=final_ans,
            sources=sources_used,
            chunks_used=len(chunks) + max_iterations,
            max_similarity_score=max_chunk_score,
            mean_similarity_score=mean_chunk_score,
        )

    def _execute_tool(self, tool_call: dict[str, Any], sources_used: list[str]) -> str:
        action = str(tool_call.get("action", "")).strip()
        archive = getattr(self.service, "source_archive", {})

        if action == "read_file":
            path = str(tool_call.get("path", ""))
            if not path:
                return "Error: read_file requires a non-empty 'path'."
            start = _parse_tool_int(tool_call.get("start"), default=1)
            end = _parse_tool_int(tool_call.get("end"), default=100)
            if start is None or end is None:
                return "Error: read_file 'start' and 'end' must be integers."
            if start < 1:
                start = 1
            if end < start:
                return "Error: read_file 'end' must be >= 'start'."
            content = archive.get(path)
            if not content:
                return f"Error: File '{path}' not found in source archive."
            if path not in sources_used:
                sources_used.append(path)
            lines = content.splitlines()
            snippet = "\n".join(lines[max(0, start - 1) : end])
            return f"--- {path} (lines {start}-{end}) ---\n{snippet}"

        elif action == "grep":
            pattern = str(tool_call.get("pattern", ""))
            if not pattern or len(pattern) < 3:
                return "Error: Grep pattern must be at least 3 characters."

            try:
                rx = re.compile(pattern, re.IGNORECASE)
            except Exception as e:
                return f"Error: Invalid regex '{pattern}' - {e}"

            results = []
            for path, content in archive.items():
                lines = content.splitlines()
                matched_in_file = False
                for i, line in enumerate(lines, 1):
                    if rx.search(line):
                        matched_in_file = True
                        results.append(f"{path}:{i}: {line.strip()}")
                        if len(results) >= 30:
                            break
                if matched_in_file and path not in sources_used:
                    sources_used.append(path)
                if len(results) >= 30:
                    break

            if not results:
                return f"No matches found in archive for '{pattern}'."
            if len(results) >= 30:
                results.append("... [truncated due to length]")
            return "\n".join(results)

        return f"Error: Unknown action '{action}'"

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
            "was insufficient. Do not invent information. Prefer complete, end-to-end "
            "explanations over brief summaries.\n\n"
            "## STRICT GROUNDING RULES — NON-NEGOTIABLE\n"
            "- NEVER fabricate code examples, function names, class names, variable names, "
            "or file paths that do not appear verbatim in the research findings below.\n"
            "- Only include code in your answer if it was explicitly quoted in a research finding. "
            "Reproducing code from memory or writing illustrative pseudocode is FORBIDDEN.\n"
            "- If the research findings do not contain enough information to answer the question, "
            "explicitly state what is missing. Do NOT fill gaps with plausible-sounding content.\n"
            "- If the question is entirely outside the scope of the codebase, say so clearly "
            "without attempting to relate it to the codebase."
        )
        user_msg = (
            f"Recent conversation:\n{_history_context(history)}\n\n"
            f"Original question: {original_question}\n\n"
            f"Research findings:\n{sub_answers}"
            f"{sources_note}\n\n"
            "Write a highly detailed, comprehensive answer that directly addresses the "
            "original question. Ground every claim in the research findings above — only "
            "quote code that appears verbatim in those findings. Cover the main implementation "
            "path, important related files, configuration, and any notable gaps in evidence."
        )
        try:
            return self._complete_sub_question(system, user_msg, token_callback=self.synthesis_token_callback)
        except Exception as e:
            logger.warning(f"[deep_research] Synthesis failed: {e}")
            # Fallback: concatenate step answers
            return " ".join(step.answer for step in steps)

    def _complete_sub_question(
        self,
        system: str,
        prompt: str,
        token_callback: "Callable[[str], None] | None" = None,
    ) -> str:
        complete_with_continuation = getattr(
            self.service,
            "_complete_with_continuation",
            None,
        )
        if callable(complete_with_continuation):
            return complete_with_continuation(system, prompt, token_callback)
        return self.llm.complete(system, prompt)

    def _estimate_confidence(
        self,
        steps: list[ResearchStep],
        max_score: float = 0.0,
        mean_score: float = 0.0,
    ) -> str:
        """Estimate confidence based on semantic similarity scores, not chunk count.

        Chunk count was a misleading proxy — FAISS always returns results regardless
        of relevance, so high chunk counts don't indicate quality.  Similarity scores
        are the ground truth signal: high scores mean retrieved chunks are genuinely
        relevant to the question.
        """
        if not steps:
            return "low"

        # Use the max semantic score passed in from research(), which was computed
        # from the actual chunk scores stored on each ResearchStep.
        if max_score <= 0.0:
            # Fallback: compute from step scores if caller didn't pass it in
            max_score = max((s.max_similarity_score for s in steps), default=0.0)
        if mean_score <= 0.0:
            mean_score = _mean_score(
                s.mean_similarity_score for s in steps if s.mean_similarity_score > 0.0
            )

        # Score bands: calibrated against cosine similarity from nomic-embed-text.
        # >0.70 → the top retrieved chunk is highly relevant (high confidence)
        # 0.50–0.70 → relevant but may have gaps (medium)
        # 0.35–0.50 → weakly relevant — answer may miss detail (low)
        # <0.35 → out of domain — should have been caught by OOD gate (out_of_scope)
        if max_score >= 0.70 and mean_score >= 0.50:
            return "high"
        elif max_score >= 0.50 and mean_score >= 0.35:
            return "medium"
        elif max_score >= 0.35:
            return "low"
        return "out_of_scope_confidence"


def _history_context(history: list[dict[str, str]]) -> str:
    turns = [
        f"{item.get('role', 'user')}: {item.get('content', '').strip()}"
        for item in history[-4:]
        if item.get("content", "").strip()
    ]
    return "\n".join(turns)


def _mean_score(values: Any) -> float:
    scores = [float(value) for value in values if float(value) > 0.0]
    return sum(scores) / len(scores) if scores else 0.0


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


def _context_hits(context: dict[str, list[Any]] | None) -> list[Any]:
    if not isinstance(context, dict):
        return []
    return (
        list(context.get("code_hits", []))
        + list(context.get("artifact_hits", []))
        + list(context.get("doc_hits", []))
        + list(context.get("relationship_hits", []))
    )


def _extract_json_object(text: str) -> dict[str, Any] | None:
    fenced_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    candidates = [fenced_match.group(1)] if fenced_match else []
    candidates.append(text)
    decoder = json.JSONDecoder()
    for candidate in candidates:
        for match in re.finditer(r"\{", candidate):
            try:
                parsed, _ = decoder.raw_decode(candidate[match.start() :])
            except Exception:
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


def _parse_tool_int(value: Any, *, default: int) -> int | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return default
        if re.fullmatch(r"-?\d+", stripped):
            return int(stripped)
    return None
