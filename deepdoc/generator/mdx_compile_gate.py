"""MDX compile gate that runs after post-processing.

Responsible for three things, in order:

1. Validate the generated MDX compiles cleanly via ``@mdx-js/mdx``.
2. If it does not, re-prompt the same LLM with a focused fix instruction.
   Capped at ``max_retries`` retries (default 2 → 3 total compile attempts).
3. If retries are exhausted, strip JSX components to GFM-equivalent Markdown
   so the page ships in a degraded but renderable form. Better than a broken
   build.

The gate is intentionally independent from the content validator: content
validation cares about sections, citations, and grounding; this gate only
cares about whether MDX can parse and render the bytes we are about to write.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable

from ..llm import LLMClient
from ..planner import DocBucket
from ..prompts_v2 import SYSTEM_V2
from .post_processors import escape_mdx_route_params, escape_mdx_text_hazards
from .mdx_validator import (
    MdxCompileError,
    ValidationOutcome,
    validate_mdx,
)

logger = logging.getLogger(__name__)

_CALLOUT_TYPE_TO_GFM = {
    "info": "NOTE",
    "note": "NOTE",
    "tip": "TIP",
    "warn": "WARNING",
    "warning": "WARNING",
    "danger": "CAUTION",
    "error": "CAUTION",
    "caution": "CAUTION",
    "important": "IMPORTANT",
}


@dataclass
class GateOutcome:
    """Result of running the MDX compile gate on a single page."""

    content: str
    retries: int = 0
    fallback_applied: bool = False
    fallback_also_failed: bool = False
    last_error: MdxCompileError | None = None
    compile_failed: bool = False


def apply_mdx_compile_gate(
    content: str,
    llm: LLMClient | None,
    bucket: DocBucket,
    *,
    max_retries: int = 2,
    validate: Callable[[str], ValidationOutcome] = validate_mdx,
) -> GateOutcome:
    """Validate MDX and recover from compile failures.

    Parameters
    ----------
    content:
        The post-processed MDX content, including frontmatter.
    llm:
        The LLM client used for fix retries. May be ``None`` in tests; when
        absent, the gate skips retries and goes straight to the JSX-strip
        fallback if validation fails.
    bucket:
        The bucket being generated. Used only to give the LLM context in the
        fix prompt.
    max_retries:
        Maximum number of LLM fix retries. Default 2 (so up to 3 compile
        attempts total). Set to 0 to skip retries entirely.
    validate:
        Validator callable. Override in tests to avoid spawning Node.
    """
    outcome = validate(content)
    if outcome.ok:
        return GateOutcome(content=content)

    retries = 0
    last_error: MdxCompileError | None = outcome.error
    current = content

    while retries < max_retries and last_error is not None and llm is not None:
        retries += 1
        try:
            user_prompt = _build_fix_prompt(current, last_error, bucket)
            fixed = llm.complete(SYSTEM_V2, user_prompt)
        except Exception as exc:
            logger.warning(
                "MDX compile gate: LLM fix call failed on retry %d for %s: %s",
                retries,
                bucket.slug,
                exc,
            )
            break

        fixed = _strip_code_fence_wrapping(fixed)
        if not fixed.strip():
            logger.warning(
                "MDX compile gate: LLM returned empty content on retry %d for %s",
                retries,
                bucket.slug,
            )
            continue

        # Re-run hazard escaping so LLM fix attempts cannot reintroduce bare
        # {expr} or route params that weren't present before the fix call.
        fixed = escape_mdx_text_hazards(fixed)
        fixed = escape_mdx_route_params(fixed)
        current = fixed
        next_outcome = validate(current)
        if next_outcome.ok:
            return GateOutcome(content=current, retries=retries)
        last_error = next_outcome.error

    # Escape hazards one more time before JSX stripping — the retry loop may
    # have left bare {expr} in content that the strip pass won't handle.
    fallback = _strip_jsx_to_markdown(escape_mdx_text_hazards(escape_mdx_route_params(current)))
    fallback_outcome = validate(fallback)
    return GateOutcome(
        content=fallback,
        retries=retries,
        fallback_applied=True,
        fallback_also_failed=not fallback_outcome.ok,
        last_error=fallback_outcome.error if not fallback_outcome.ok else last_error,
        compile_failed=True,
    )


def _build_fix_prompt(
    content: str, error: MdxCompileError, bucket: DocBucket
) -> str:
    """Build a tightly scoped fix-instruction prompt for a single compile error."""
    location_hint = ""
    if error.line is not None:
        location_hint = f" at line {error.line}"
        if error.column is not None:
            location_hint += f", column {error.column}"

    return (
        f"The generated documentation page for `{bucket.title}` failed to compile as "
        f"MDX. The MDX compiler reported the following error{location_hint}:\n\n"
        f"    {error.message}\n\n"
        "Common causes:\n"
        "- Unescaped `<` followed by a digit or unknown tag in prose "
        "(e.g. `<5s`, `array<object>`).\n"
        "- Unclosed or mismatched JSX components like `<Callout>`, `<Tabs>`, "
        "`<Step>`, `<Accordion>`.\n"
        "- Curly braces in URLs or text that MDX parses as JS expressions "
        "(e.g. `/users/{id}`).\n"
        "- Headings inside flow JSX components like `<Step>`.\n\n"
        "Return the ENTIRE page below with ONLY the change required to fix that "
        "specific error. Do not add commentary, do not rewrite sections, do not "
        "remove existing content. Preserve frontmatter exactly. Return raw MDX "
        "only, no surrounding code fence.\n\n"
        "----- PAGE START -----\n"
        f"{content}\n"
        "----- PAGE END -----\n"
    )


def _strip_code_fence_wrapping(text: str) -> str:
    """If the LLM wraps its return in ``` fences, strip the outer wrapper."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text
    lines = stripped.splitlines()
    if len(lines) < 2:
        return text
    if not lines[-1].strip().startswith("```"):
        return text
    return "\n".join(lines[1:-1])


# ---------------------------------------------------------------------------
# JSX → Markdown fallback
# ---------------------------------------------------------------------------

_FALLBACK_BANNER = (
    "{/* deepdoc: auto-recovered from MDX compile failure */}\n"
)


def _strip_jsx_to_markdown(content: str) -> str:
    """Convert known JSX components to GFM-equivalent Markdown.

    This is the last-resort fallback. It is intentionally lossy: the goal is
    "renders something readable" rather than "preserves every visual nuance."
    The recovery banner makes the degradation visible in source.
    """
    body = content

    body = _convert_callouts(body)
    body = _convert_accordions(body)
    body = _convert_steps(body)
    body = _convert_cards(body)
    body = _convert_tabs(body)
    body = _strip_remaining_jsx(body)
    body = _escape_jsx_hazards_in_text(body)

    if _FALLBACK_BANNER not in body:
        body = _inject_banner(body)
    return body


def _inject_banner(content: str) -> str:
    """Place the recovery banner immediately after the frontmatter block."""
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            insert_at = end + len("\n---") + 1
            return content[:insert_at] + _FALLBACK_BANNER + content[insert_at:]
    return _FALLBACK_BANNER + content


def _convert_callouts(content: str) -> str:
    pattern = re.compile(
        r'<Callout(?P<attrs>[^>]*)>(?P<body>.*?)</Callout>',
        re.DOTALL,
    )

    def replace(match: re.Match) -> str:
        attrs = match.group("attrs") or ""
        type_match = re.search(r'type=["\']([^"\']+)["\']', attrs)
        kind = (type_match.group(1).lower() if type_match else "note")
        gfm_label = _CALLOUT_TYPE_TO_GFM.get(kind, "NOTE")
        inner = match.group("body").strip()
        lines = inner.splitlines() or [""]
        quoted = "\n".join(f"> {line}" if line else ">" for line in lines)
        return f"> [!{gfm_label}]\n{quoted}"

    return pattern.sub(replace, content)


def _convert_accordions(content: str) -> str:
    # Negative lookahead `(?!s)` prevents the regex from eating the wrapper
    # `<Accordions>` tag as an opening Accordion.
    accordion_pattern = re.compile(
        r'<Accordion(?!s)(?P<attrs>[^>]*)>(?P<body>.*?)</Accordion(?!s)>',
        re.DOTALL,
    )

    def replace_accordion(match: re.Match) -> str:
        attrs = match.group("attrs") or ""
        title_match = re.search(r'title=["\']([^"\']+)["\']', attrs)
        title = title_match.group(1) if title_match else "Details"
        inner = match.group("body").strip()
        return f"<details>\n<summary>{title}</summary>\n\n{inner}\n\n</details>"

    content = accordion_pattern.sub(replace_accordion, content)
    content = re.sub(r'</?Accordions[^>]*>', "", content)
    return content


def _convert_steps(content: str) -> str:
    steps_pattern = re.compile(
        r'<Steps(?P<attrs>[^>]*)>(?P<body>.*?)</Steps>',
        re.DOTALL,
    )

    def replace_steps(match: re.Match) -> str:
        inner = match.group("body")
        step_items = re.findall(
            r'<Step(?P<attrs>[^>]*)>(?P<body>.*?)</Step>',
            inner,
            flags=re.DOTALL,
        )
        if not step_items:
            return inner.strip()
        rendered = []
        for idx, (_, item_body) in enumerate(step_items, 1):
            cleaned = item_body.strip()
            cleaned = re.sub(r"^#{1,6}\s+(.+)$", r"**\1**", cleaned, count=1, flags=re.MULTILINE)
            indented = "\n".join(
                ("    " + line) if line else "" for line in cleaned.splitlines()
            )
            rendered.append(f"{idx}.\n{indented}")
        return "\n\n".join(rendered)

    return steps_pattern.sub(replace_steps, content)


def _convert_cards(content: str) -> str:
    cards_pattern = re.compile(
        r'<Cards(?P<attrs>[^>]*)>(?P<body>.*?)</Cards>',
        re.DOTALL,
    )

    def replace_cards(match: re.Match) -> str:
        inner = match.group("body")
        items: list[str] = []
        for card in re.finditer(
            # Non-greedy attrs that stop only at the actual tag terminator so
            # that quoted attrs containing `/` (e.g. `href="/setup"`) parse.
            r'<Card(?P<attrs>[^>]*?)(?:/>|>(?P<body>.*?)</Card>)',
            inner,
            flags=re.DOTALL,
        ):
            attrs = card.group("attrs") or ""
            title_match = re.search(r'title=["\']([^"\']+)["\']', attrs)
            href_match = re.search(r'href=["\']([^"\']+)["\']', attrs)
            title = title_match.group(1) if title_match else "Untitled"
            href = href_match.group(1) if href_match else "#"
            description = (card.group("body") or "").strip()
            if description:
                items.append(f"- [{title}]({href}) — {description}")
            else:
                items.append(f"- [{title}]({href})")
        return "\n".join(items) if items else ""

    return cards_pattern.sub(replace_cards, content)


def _convert_tabs(content: str) -> str:
    tabs_pattern = re.compile(
        r'<Tabs(?P<attrs>[^>]*)>(?P<body>.*?)</Tabs>',
        re.DOTALL,
    )

    def replace_tabs(match: re.Match) -> str:
        inner = match.group("body")
        rendered: list[str] = []
        for tab in re.finditer(
            r'<Tab(?P<attrs>[^>]*)>(?P<body>.*?)</Tab>',
            inner,
            flags=re.DOTALL,
        ):
            attrs = tab.group("attrs") or ""
            value_match = re.search(r'value=["\']([^"\']+)["\']', attrs)
            heading = value_match.group(1) if value_match else "Option"
            rendered.append(f"**{heading}**\n\n{tab.group('body').strip()}")
        return "\n\n".join(rendered) if rendered else inner.strip()

    return tabs_pattern.sub(replace_tabs, content)


def _strip_remaining_jsx(content: str) -> str:
    """Remove any leftover unknown JSX tags by escaping them as text.

    We do not try to translate unknown components — we just neutralise the
    angle brackets so the page parses.
    """
    return re.sub(r'<(/?)([A-Z][A-Za-z0-9]*)([^>]*)>', r'&lt;\1\2\3&gt;', content)


# Conservative: only escape `<` immediately followed by whitespace or a digit
# (e.g. `< 5`, `<5s`). This deliberately leaves `</...>` closing tags, valid
# HTML/JSX openings, and the recovery banner alone.
_JSX_HAZARD_TEXT_RE = re.compile(r'<(?=[\s\d])')


def _escape_jsx_hazards_in_text(content: str) -> str:
    """Escape stray `<` characters likely to break MDX in remaining prose.

    Conservative — leaves valid HTML tags (`<details>`, `<summary>`, etc.) and
    the recovery banner comment alone.
    """
    lines = content.splitlines()
    in_fence = False
    out: list[str] = []
    for line in lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        out.append(_JSX_HAZARD_TEXT_RE.sub("&lt;", line))
    trailing_newline = "\n" if content.endswith("\n") else ""
    return "\n".join(out) + trailing_newline


__all__ = [
    "GateOutcome",
    "apply_mdx_compile_gate",
]
