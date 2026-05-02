"""Answer generation mixin for ChatbotQueryService."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Callable

from ..source_metadata import classify_source_kind
from .types import (
    EvidenceItem,
    ReferenceItem,
    RetrievalDiagnostics,
    RetrievedChunk,
)

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


class AnswerMixin:
    """Mixin providing answer generation and evidence contract methods."""

    def _complete_with_continuation(
        self,
        system: str,
        user: str,
        token_callback: "Callable[[str], None] | None" = None,
    ) -> str:
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

        if token_callback is not None:
            chunks: list[str] = []
            for token in self.chat_client.complete_stream(system, user):
                token_callback(token)
                chunks.append(token)
            answer = "".join(chunks)
        else:
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
        if AnswerMixin._is_reference_doc_path(normalized):
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
