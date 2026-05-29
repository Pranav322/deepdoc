"""Post-generation cross-bucket consistency pass.

After all pages are generated independently, makes a single LLM call to
identify cross-linking gaps — pages that discuss concepts documented
elsewhere but don't link to them — and injects a "See also" callout.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from rich.console import Console

from ..llm import LLMClient
from .generation import GenerationResult

console = Console()

CONSISTENCY_SYSTEM = (
    "You are a documentation reviewer. "
    "Your job is to identify cross-linking gaps between independently generated "
    "documentation pages. A gap exists when page A discusses concepts that are clearly "
    "documented on page B but contains no link to page B. "
    "Return only valid JSON — no prose, no markdown fences."
)

_H2_RE = re.compile(r"^## (.+)", re.MULTILINE)


class CrossBucketConsistencyPass:
    """Single post-generation LLM pass to detect and patch cross-link gaps."""

    def __init__(self, llm: LLMClient, output_dir: Path, cfg: dict[str, Any]) -> None:
        self.llm = llm
        self.output_dir = output_dir
        self.cfg = cfg

    def run(self, results: list[GenerationResult]) -> int:
        """Detect cross-link gaps and inject 'See also' callouts.

        Returns the number of pages patched (0 if nothing to do or LLM fails).
        """
        if not self.cfg.get("consistency_pass", True):
            return 0

        successful = [r for r in results if r.content and not r.error]
        if len(successful) < 2:
            return 0

        slug_to_title = {r.bucket.slug: r.bucket.title for r in successful}

        page_summaries = self._build_summaries(successful)
        user_prompt = self._build_prompt(page_summaries)

        try:
            response = self.llm.complete(CONSISTENCY_SYSTEM, user_prompt)
        except Exception as exc:
            console.print(f"[dim yellow]  consistency pass: LLM call failed ({exc})[/dim yellow]")
            return 0

        cross_links = self._parse_response(response)
        if cross_links is None:
            return 0

        patched = 0
        for item in cross_links:
            from_slug = item.get("from_slug", "")
            to_slug = item.get("to_slug", "")
            reason = item.get("reason", "")
            if not from_slug or not to_slug or from_slug == to_slug:
                continue
            if to_slug not in slug_to_title:
                continue
            page_path = self.output_dir / f"{from_slug}.md"
            if not page_path.exists():
                continue
            content = page_path.read_text(encoding="utf-8")
            if f"]({to_slug}.md" in content:
                continue
            to_title = slug_to_title[to_slug]
            callout = (
                f"\n/// note | See also\n- [{to_title}]({to_slug}.md) — {reason}\n///\n"
            )
            page_path.write_text(content.rstrip() + callout, encoding="utf-8")
            patched += 1

        return patched

    # ── helpers ──────────────────────────────────────────────────────────

    def _build_summaries(self, results: list[GenerationResult]) -> str:
        lines: list[str] = []
        for r in results:
            headings = _H2_RE.findall(r.content or "")[:6]
            heading_str = ", ".join(headings) if headings else "(no sections)"
            lines.append(
                f"- slug={r.bucket.slug} | title={r.bucket.title} "
                f"| type={r.bucket.bucket_type} | sections=[{heading_str}]"
            )
        return "\n".join(lines)

    def _build_prompt(self, page_summaries: str) -> str:
        return (
            f"You have the following documentation pages ({page_summaries.count(chr(10)) + 1} total).\n"
            "Identify pairs where page A discusses concepts clearly documented on page B "
            "but has no link to it.\n\n"
            f"Pages:\n{page_summaries}\n\n"
            'Return JSON: {"cross_links": [{"from_slug": "...", "to_slug": "...", "reason": "..."}]}\n\n'
            "Rules:\n"
            "- Only suggest links genuinely useful to a developer reading page A\n"
            "- Do not suggest obvious/redundant links (e.g. intro → everything)\n"
            "- Maximum 20 suggestions total"
        )

    def _parse_response(self, response: str) -> list[dict[str, str]] | None:
        text = response.strip()
        if text.startswith("```"):
            lines = [ln for ln in text.splitlines() if not ln.strip().startswith("```")]
            text = "\n".join(lines).strip()
        try:
            data = json.loads(text)
            return data.get("cross_links", [])
        except Exception:
            console.print("[dim yellow]  consistency pass: could not parse LLM response[/dim yellow]")
            return None
