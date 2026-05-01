"""V2 Generation Engine — evidence-assembled, single-pass, validated page generation.

Phase 3 of the bucket-based doc pipeline:

  3.1 Evidence assembly: per-bucket, section-aware context gathering from scan data
  3.2 Single-pass generation: one LLM call per bucket with full evidence + mandatory outline
  3.3 Validation: check required sections, evidence citations, no hallucinated paths
  3.4 Graph-lite diagrams: static import/endpoint edges → Mermaid seed context
  3.5 Parallel generation: concurrent LLM calls for independent buckets
  3.6 Graceful degradation: fallbacks for sparse evidence, malformed output, LLM failures
"""

from __future__ import annotations

import html
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
)

from ..llm import LLMClient
from ..parser import parse_file, supported_extensions
from ..parser.base import ParsedFile, Symbol
from ..planner import DocBucket, DocPlan, RepoScan, tracked_bucket_files
from ..prompts_v2 import SYSTEM_V2, get_prompt_for_bucket
from ..scanner import _classify_file_role
from ..openapi import parse_openapi_spec, spec_to_context_string

console = Console()

# ═════════════════════════════════════════════════════════════════════════════
# 3.1  Evidence Assembly
# ═════════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════════
# 3.4  Mermaid Post-Processing
# ═════════════════════════════════════════════════════════════════════════════


def fix_mermaid_diagrams(content: str) -> str:
    """Find and fix common LLM Mermaid syntax errors in generated markdown."""

    def fix_block(match: re.Match) -> str:
        diagram = match.group(1)
        fixed = _fix_mermaid_diagram(diagram)
        return f"```mermaid\n{fixed}\n```"

    return re.sub(r"```mermaid\n(.*?)\n```", fix_block, content, flags=re.DOTALL)


def _fix_mermaid_diagram(diagram: str) -> str:
    """Fix the most common Mermaid mistakes LLMs make."""

    def sanitize_edge_label(label: str) -> str:
        cleaned = re.sub(r"<br\s*/?>", " ", label, flags=re.IGNORECASE)
        cleaned = cleaned.replace("(", " ").replace(")", " ")
        cleaned = cleaned.replace("/", " ")
        cleaned = re.sub(r"[^A-Za-z0-9 _:-]+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned or "link"

    lines = diagram.splitlines()
    fixed: list[str] = []
    diagram_type = ""

    for line in lines:
        stripped = line.strip().lower()

        if not diagram_type and stripped:
            for dtype in (
                "flowchart",
                "graph",
                "sequencediagram",
                "classdiagram",
                "erdiagram",
                "gantt",
                "pie",
                "statediagram",
            ):
                if stripped.startswith(dtype):
                    diagram_type = dtype
                    break

        # Fix: Unquoted labels with parentheses in flowchart
        if diagram_type in ("flowchart", "graph", ""):
            line = re.sub(
                r"\b(\w[\w-]*)\(([^()]*\([^()]*\)[^()]*)\)",
                lambda m: f'{m.group(1)}["{m.group(2)}"]',
                line,
            )
            line = re.sub(
                r'\b([A-Za-z][\w-]*)\[([^\]"]*(?:<br\s*/?>|\(|\))[^\]"]*)\]',
                lambda m: f'{m.group(1)}["{m.group(2)}"]',
                line,
            )
            line = re.sub(
                r'(-->|---|-.->|==>)\s*"([^"]+)"',
                lambda m: (
                    f"{m.group(1)} "
                    f'{re.sub(r"[^A-Za-z0-9]+", "", m.group(2)).strip() or "Node"}["{m.group(2)}"]'
                ),
                line,
            )
            line = re.sub(
                r'^(\s*)([A-Za-z][\w-]*)\s*--\s*"([^"]+)"\s*-->\s*([A-Za-z][\w-]*)\s*$',
                lambda m: f"{m.group(1)}{m.group(2)} -->|{m.group(3)}| {m.group(4)}",
                line,
            )
            line = re.sub(
                r"^(\s*)([A-Za-z][\w-]*)\s*<--\s*([A-Za-z][\w-]*)\s*$",
                lambda m: f"{m.group(1)}{m.group(3)} --> {m.group(2)}",
                line,
            )
            line = re.sub(
                r"^(\s*)([A-Za-z][\w-]*)\s*<-->\s*([A-Za-z][\w-]*)\s*$",
                lambda m: (
                    f"{m.group(1)}{m.group(2)} --> {m.group(3)}\n"
                    f"{m.group(1)}{m.group(3)} --> {m.group(2)}"
                ),
                line,
            )
            line = re.sub(
                r"\|([^|]+)\|",
                lambda m: f"|{sanitize_edge_label(m.group(1))}|",
                line,
            )

        # Fix: Node labels with colons not in quotes
        line = re.sub(
            r'\[([^\]"]*:[^\]"]*)\]',
            lambda m: (
                f'["{m.group(1)}"]'
                if ":" in m.group(1) and not m.group(1).startswith('"')
                else f"[{m.group(1)}]"
            ),
            line,
        )

        # Fix: classDiagram -> instead of --
        if diagram_type == "classdiagram":
            line = re.sub(r"\s+->\s+", " --> ", line)
            line = re.sub(
                r'(-->\s+)([A-Za-z][\w-]*)\["[^"]+"\]',
                r"\1\2",
                line,
            )
            line = re.sub(
                r'(-->\s+)"([A-Za-z][A-Za-z0-9_]*)"',
                r"\1\2",
                line,
            )
            line = re.sub(
                r'^(\s*)([A-Za-z][\w-]*)\["[^"]+"\]\s*$',
                r"\1class \2",
                line,
            )

        # Fix: sequenceDiagram participants accidentally emitted with flowchart syntax
        if diagram_type == "sequencediagram":
            line = re.sub(
                r'^(\s*participant\s+)([A-Za-z][\w-]*)\["([^"]+)"\]\s*$',
                lambda m: f"{m.group(1)}{m.group(2)} as {m.group(3)}",
                line,
            )

        if diagram_type in ("statediagram", "statediagram-v2"):
            line = re.sub(
                r'"([A-Za-z][A-Za-z0-9_]*)"',
                r"\1",
                line,
            )

        if diagram_type == "erdiagram":
            if stripped == "...":
                continue
            if re.match(r"^\s*\.\.\.\s*(\"[^\"]+\")?\s*$", line):
                continue
            if re.match(r"^\s*[A-Za-z][\w-]*\s+\.\.\.\s*(\"[^\"]+\")?\s*$", line):
                continue
            line = re.sub(r"^(\s*)--\s+", r"\1%% ", line)

        fixed.append(line)

    result = "\n".join(fixed)

    # Warn about duplicate node IDs
    if diagram_type in ("flowchart", "graph"):
        node_ids = re.findall(r"\b([A-Za-z][\w-]*)\s*[\[({\|]", result)
        seen: set[str] = set()
        dupes: list[str] = []
        for nid in node_ids:
            if nid in seen:
                dupes.append(nid)
            seen.add(nid)
        if dupes:
            result = (
                f"%% Note: possible duplicate node IDs: {', '.join(set(dupes))}\n"
                + result
            )

    return result


def fix_file_references(
    content: str, repo_root: Path, known_files: set[str], page_files: list[str]
) -> str:
    """Remove hallucinated file:line refs, fix out-of-range line numbers."""
    file_line_counts: dict[str, int] = {}

    def get_line_count(path: str) -> int:
        if path not in file_line_counts:
            try:
                text = (repo_root / path).read_text(encoding="utf-8", errors="replace")
                file_line_counts[path] = len(text.splitlines())
            except Exception:
                file_line_counts[path] = 0
        return file_line_counts[path]

    def fix_ref(match: re.Match) -> str:
        path = match.group(1)
        line_str = match.group(2)

        if path not in known_files and not (repo_root / path).exists():
            return f"`{path}`"

        if line_str:
            try:
                line_num = int(line_str)
                total = get_line_count(path)
                if total > 0 and line_num > total:
                    return f"`{path}`"
            except ValueError:
                pass

        return match.group(0)

    return re.sub(
        r"`([a-zA-Z][a-zA-Z0-9_./-]*\.[a-zA-Z]{1,8}):(\d+)`",
        fix_ref,
        content,
    )


def _normalize_internal_doc_url(target: str) -> str:
    normalized = (target or "").strip()
    if not normalized.startswith("/"):
        return normalized
    if normalized != "/" and normalized.endswith("/"):
        normalized = normalized.rstrip("/")
    return normalized or "/"


def _normalize_doc_title_key(value: str) -> str:
    cleaned = html.unescape(value or "")
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"[*_~{}[\]()]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned).strip()
    return cleaned


def build_internal_doc_link_maps(
    pages: list[tuple[str, str]],
) -> tuple[set[str], dict[str, str], dict[str, str]]:
    """Build valid-url, title-map, and alias-map helpers for doc-link repair."""

    valid_urls: set[str] = set()
    title_to_url: dict[str, str] = {}
    alias_map: dict[str, str] = {}

    for title, url in pages:
        normalized_url = _normalize_internal_doc_url(url)
        if not normalized_url:
            continue
        valid_urls.add(normalized_url)
        title_key = _normalize_doc_title_key(title)
        if title_key and title_key not in title_to_url:
            title_to_url[title_key] = normalized_url
        if normalized_url == "/":
            alias_map["/overview"] = "/"
            alias_map["/architecture"] = "/"
            alias_map["/introduction"] = "/"
            alias_map["/architecture-overview"] = "/"
            alias_map["/system-overview"] = "/"
            alias_map["/system-architecture"] = "/"
            alias_map["/start-here"] = "/"

    return valid_urls, title_to_url, alias_map


def repair_internal_doc_links(
    content: str,
    valid_urls: set[str],
    title_to_url: dict[str, str],
    alias_map: dict[str, str] | None = None,
) -> str:
    """Repair internal doc links so missing slugs do not break static export."""

    alias_map = alias_map or {}

    def resolve_target(
        target: str,
        *,
        label: str = "",
        title: str = "",
    ) -> str | None:
        normalized = _normalize_internal_doc_url(target)
        if (
            not normalized.startswith("/")
            or normalized.startswith("//")
            or normalized.startswith("/api/")
            or "." in normalized.rsplit("/", 1)[-1]
        ):
            return normalized

        if normalized in valid_urls:
            return normalized

        if normalized in alias_map and alias_map[normalized] in valid_urls:
            return alias_map[normalized]

        for candidate_text in (title, label):
            title_key = _normalize_doc_title_key(candidate_text)
            if title_key and title_key in title_to_url:
                return title_to_url[title_key]

        # Handle common model-generated aliases safely.
        if normalized in {"/database", "/database-src", "/database-source"}:
            for title_key, candidate_url in title_to_url.items():
                if "database" in title_key and any(
                    token in title_key for token in ("schema", "model", "persistence")
                ):
                    return candidate_url

        if (
            normalized in {"/architecture", "/overview", "/introduction"}
            and "/" in valid_urls
        ):
            return "/"

        return None

    def replace_markdown_link(match: re.Match[str]) -> str:
        label = match.group("label")
        target = match.group("target")
        resolved = resolve_target(target, label=label)
        if resolved is None:
            return label
        if resolved == target:
            return match.group(0)
        return f"[{label}]({resolved})"

    def replace_tag(match: re.Match[str]) -> str:
        tag = match.group("tag")
        attrs = match.group("attrs")
        href_match = re.search(r'\bhref="(?P<target>/[^"]+)"', attrs)
        if not href_match:
            return match.group(0)

        target = href_match.group("target")
        title_match = re.search(r'\btitle="(?P<title>[^"]+)"', attrs)
        resolved = resolve_target(
            target, title=(title_match.group("title") if title_match else "")
        )
        if resolved is None:
            resolved = "/" if "/" in valid_urls else target
        if resolved == target:
            return match.group(0)

        replaced_attrs = (
            attrs[: href_match.start("target")]
            + resolved
            + attrs[href_match.end("target") :]
        )
        return f"<{tag}{replaced_attrs}>"

    content = re.sub(
        r"\[(?P<label>[^\]]+)\]\((?P<target>/[^)\s]+)\)",
        replace_markdown_link,
        content,
    )
    content = re.sub(
        r"<(?P<tag>[A-Za-z][\w.]*)\b(?P<attrs>[^>]*)>",
        replace_tag,
        content,
    )
    return content


def escape_mdx_route_params(content: str) -> str:
    """Escape route params like `/users/{id}` in MDX text without touching code fences.

    MDX treats `{id}` as a JavaScript expression in normal text and JSX props, so
    endpoint paths must be escaped to render as literal braces.
    """

    def escape_segment(segment: str) -> str:
        return re.sub(
            r"(?<=/)\{([A-Za-z_][A-Za-z0-9_]*(?::[A-Za-z_][A-Za-z0-9_]*)?)\}",
            lambda match: f"&#123;{match.group(1)}&#125;",
            segment,
        )

    lines: list[str] = []
    in_fence = False
    for line in content.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            lines.append(line)
            continue

        if in_fence:
            lines.append(line)
            continue

        parts = re.split(r"(`[^`]*`)", line)
        escaped = "".join(
            part
            if part.startswith("`") and part.endswith("`")
            else escape_segment(part)
            for part in parts
        )
        if "|" in line:
            escaped = re.sub(
                r"`([A-Za-z_][A-Za-z0-9_]*)&lt;([^`]+)&gt;`",
                r"`\1<\2>`",
                escaped,
            )
            escaped = re.sub(
                r"`([A-Za-z_][A-Za-z0-9_]*)<([^`\n]+)>`",
                lambda match: f"`{match.group(1)}&lt;{match.group(2)}&gt;`",
                escaped,
            )
        lines.append(escaped)

    return "\n".join(lines)


def escape_mdx_text_hazards(content: str) -> str:
    """Escape plain-text MDX hazards like bare `<5s` outside fenced code.

    A raw `<` followed by a digit, placeholder syntax like `<model>`, or generic
    type syntax like `array<object>` is parsed as invalid JSX in MDX prose and
    markdown tables.
    Also repairs malformed inline HTML where the opening tag is real but the
    closing tag was escaped by the model, e.g. `<code>path&lt;/code&gt;`.
    """

    lines: list[str] = []
    in_fence = False
    safe_html_tags = {
        "a",
        "b",
        "body",
        "br",
        "code",
        "details",
        "div",
        "em",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "head",
        "header",
        "hr",
        "html",
        "i",
        "img",
        "kbd",
        "li",
        "main",
        "meta",
        "ol",
        "p",
        "pre",
        "section",
        "small",
        "span",
        "strong",
        "sub",
        "summary",
        "sup",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "title",
        "tr",
        "u",
        "ul",
    }

    for line in content.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            lines.append(line)
            continue

        if in_fence:
            lines.append(line)
            continue

        line = re.sub(
            r"<code>\{([^{}\n]+)\}</code>",
            lambda match: f"<code>&#123;{match.group(1)}&#125;</code>",
            line,
        )

        parts = re.split(r"(`[^`]*`)", line)

        def normalize_code_span(part: str) -> str:
            if "|" not in line:
                return part
            if not (part.startswith("`") and part.endswith("`")):
                return part

            code = part[1:-1]
            code = re.sub(
                r"<([^`\n<>]+)>",
                lambda match: f"&lt;{match.group(1)}&gt;",
                code,
            )
            if "{" in code or "}" in code:
                code = code.replace("{", "&#123;").replace("}", "&#125;")
            return f"`{code}`"

        def escape_segment(part: str) -> str:
            part = re.sub(
                r"<(?P<tag>code|strong|em|b|i)>(?P<body>.*?)&lt;/(?P=tag)&gt;",
                lambda match: (
                    f"<{match.group('tag')}>{match.group('body')}</{match.group('tag')}>"
                ),
                part,
            )
            part = re.sub(
                r"<(?P<tag>code|strong|em|b|i)>(?P<body>.*?)</(?P=tag)&gt;",
                lambda match: (
                    f"<{match.group('tag')}>{match.group('body')}</{match.group('tag')}>"
                ),
                part,
            )
            part = re.sub(
                r"<(?P<tag>code|strong|em|b|i)>(?P<body>.*?)&lt;/(?P=tag)>",
                lambda match: (
                    f"<{match.group('tag')}>{match.group('body')}</{match.group('tag')}>"
                ),
                part,
            )
            part = re.sub(r"<br\s*/?>", "<br />", part, flags=re.IGNORECASE)
            if "|" in line:
                part = re.sub(r"<br\s*/?>", " / ", part, flags=re.IGNORECASE)
            part = re.sub(r"<(?=[^A-Za-z/!])", "&lt;", part)
            part = re.sub(r"<(?=\d)", "&lt;", part)
            part = re.sub(
                r"\b([A-Za-z_][A-Za-z0-9_]*)<([A-Za-z_][A-Za-z0-9_, .|/&;<>[\]-]*)>",
                lambda match: f"{match.group(1)}&lt;{match.group(2)}&gt;",
                part,
            )
            part = re.sub(
                r"<([A-Za-z_][A-Za-z0-9_]*:[A-Za-z_][A-Za-z0-9_]*)>",
                lambda match: f"&lt;{match.group(1)}&gt;",
                part,
            )
            part = re.sub(
                r"<([a-z_][a-z0-9_-]*)>",
                lambda match: (
                    match.group(0)
                    if match.group(1) in safe_html_tags
                    else f"&lt;{match.group(1)}&gt;"
                ),
                part,
            )
            part = part.replace("<=", "&lt;=")
            if not line.lstrip().startswith("<"):
                part = re.sub(
                    r"\{([^`\n{}]*:[^`\n{}]*)\}",
                    lambda match: f"&#123;{match.group(1)}&#125;",
                    part,
                )
            if line.lstrip().startswith("|"):
                part = re.sub(
                    r"(?<!`)(\[\{[^`\n]*\}\])(?!`)",
                    r"`\1`",
                    part,
                )
                part = re.sub(
                    r"([,(]\s*)\{([A-Za-z_][A-Za-z0-9_, ]*)\}(?=\s*[),])",
                    lambda match: f"{match.group(1)}&#123;{match.group(2)}&#125;",
                    part,
                )
            part = part.replace("{...}", "&#123;...&#125;")
            return part

        escaped = "".join(
            normalize_code_span(part)
            if part.startswith("`") and part.endswith("`")
            else escape_segment(part)
            for part in parts
        )
        if not line.lstrip().startswith("<"):
            escaped = re.sub(
                r"\{([^{}\n]*:[^{}\n]*)\}",
                lambda match: f"&#123;{match.group(1)}&#125;",
                escaped,
            )
            escaped = escaped.replace("{", "&#123;").replace("}", "&#125;")
        lines.append(escaped)

    return "\n".join(lines)


def normalize_code_fence_languages(content: str) -> str:
    """Normalize unsupported or inconsistent fence labels to safe Shiki languages."""

    alias_map = {
        "env": "bash",
        "dotenv": "bash",
        "shell": "bash",
        "sh": "bash",
    }

    def replace(match: re.Match) -> str:
        indent = match.group(1) or ""
        lang = match.group(2)
        rest = match.group(3) or ""
        normalized = alias_map.get(lang.lower(), lang)
        return f"{indent}```{normalized}{rest}"

    return re.sub(
        r"^([ \t]*)```([A-Za-z0-9_+-]+)([^\n`]*)$", replace, content, flags=re.MULTILINE
    )


def repair_split_object_code_fences(content: str) -> str:
    """Repair code fences that were accidentally closed after an opening `{`."""

    pattern = re.compile(
        r"```(?P<lang>[A-Za-z0-9_+-]+)\n"
        r"(?P<head>(?:(?!```)[\s\S])*?)"
        r"\{\n```\n"
        r"(?P<body>[\s\S]*?)"
        r"\n\}\n```",
    )

    def replace(match: re.Match) -> str:
        lang = match.group("lang")
        head = match.group("head").rstrip("\n")
        body = match.group("body").strip("\n")
        prefix = f"{head}\n" if head else ""
        return f"```{lang}\n{prefix}{{\n{body}\n}}\n```"

    return pattern.sub(replace, content)


def repair_unbalanced_code_fences(content: str) -> str:
    """Drop one trailing unmatched fence marker when fence count is odd."""

    lines = content.splitlines()
    fence_indexes = [
        idx for idx, line in enumerate(lines) if line.lstrip().startswith("```")
    ]
    if len(fence_indexes) % 2 == 0:
        return content

    plain_fence_indexes = [
        idx for idx in fence_indexes if re.match(r"^\s*```\s*$", lines[idx])
    ]
    drop_idx = plain_fence_indexes[-1] if plain_fence_indexes else fence_indexes[-1]
    lines.pop(drop_idx)
    repaired = "\n".join(lines)
    if content.endswith("\n"):
        repaired += "\n"
    return repaired


def repair_dangling_plain_fences(content: str) -> str:
    """Remove standalone fence lines that dangle outside a real code block."""

    explanatory_prefixes = (
        "expected:",
        "output:",
        "result:",
        "returns:",
        "return:",
        "you should see:",
    )

    lines = content.splitlines()
    repaired: list[str] = []
    in_fence = False

    for idx, line in enumerate(lines):
        stripped = line.strip()
        plain_fence = re.match(r"^\s*```\s*$", line)
        labeled_fence = re.match(r"^\s*```[A-Za-z0-9_+-]+", line)

        if labeled_fence:
            repaired.append(line)
            in_fence = not in_fence
            continue

        if plain_fence:
            if in_fence:
                repaired.append(line)
                in_fence = False
                continue

            prev_nonblank = ""
            for prev in range(idx - 1, -1, -1):
                candidate = lines[prev].strip().lower()
                if candidate:
                    prev_nonblank = candidate
                    break

            next_nonblank = ""
            for nxt in range(idx + 1, len(lines)):
                candidate = lines[nxt].strip()
                if candidate:
                    next_nonblank = candidate
                    break

            if (
                any(prev_nonblank.startswith(prefix) for prefix in explanatory_prefixes)
                or next_nonblank.startswith("</")
            ):
                continue

            repaired.append(line)
            in_fence = True
            continue

        repaired.append(line)

    normalized = "\n".join(repaired)
    if content.endswith("\n"):
        normalized += "\n"
    return normalized


def normalize_explanatory_lines_outside_fences(content: str) -> str:
    """Move prose lines like `Expected:` out of fenced code blocks.

    LLM output sometimes leaves explanatory prose inside a shell/code fence,
    which then cascades into malformed JSX children inside components like
    <Tab>. Close the current fence before those prose lines and let the
    existing fence-repair pass clean up any leftover trailing fence.
    """

    explanatory_prefixes = (
        "expected:",
        "output:",
        "result:",
        "response:",
        "returns:",
        "return:",
        "you should see:",
    )

    lines = content.splitlines()
    normalized: list[str] = []
    in_fence = False
    fence_indent = ""

    idx = 0
    while idx < len(lines):
        line = lines[idx]
        fence_match = re.match(r"^(\s*)```", line)
        if fence_match:
            normalized.append(line)
            if in_fence:
                in_fence = False
                fence_indent = ""
            else:
                in_fence = True
                fence_indent = fence_match.group(1)
            idx += 1
            continue

        stripped = line.strip()
        lowered = stripped.lower()
        looks_like_object_field = bool(
            re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*:\s*[\[{]?$", stripped)
        )
        if (
            in_fence
            and not looks_like_object_field
            and any(lowered.startswith(prefix) for prefix in explanatory_prefixes)
        ):
            normalized.append(f"{fence_indent}```")
            in_fence = False
            fence_indent = ""
            next_idx = idx + 1
            if next_idx < len(lines) and re.match(r"^\s*```\s*$", lines[next_idx]):
                idx += 1

        normalized.append(line)
        idx += 1

    repaired = "\n".join(normalized)
    if content.endswith("\n"):
        repaired += "\n"
    return repaired


def normalize_html_code_blocks(content: str) -> str:
    """Convert raw HTML code blocks into fenced code blocks."""

    def replace_pre(match: re.Match) -> str:
        body = re.sub(
            r"<br(\s*/?)>",
            r"&lt;br\1&gt;",
            match.group("body"),
            flags=re.IGNORECASE,
        )
        normalized = body.strip("\n")
        return f"```bash\n{normalized}\n```"

    content = re.sub(
        r"<pre><code>(?P<body>.*?)</code></pre>",
        replace_pre,
        content,
        flags=re.DOTALL,
    )

    def replace_code(match: re.Match) -> str:
        escaped_body = re.sub(
            r"<br(\s*/?)>",
            r"&lt;br\1&gt;",
            match.group("body"),
            flags=re.IGNORECASE,
        )
        body = html.unescape(escaped_body)
        normalized = body.strip("\n")
        if "\n" not in normalized:
            return f"<code>{escaped_body}</code>"
        language = (
            "javascript"
            if any(
                token in normalized
                for token in ("await ", "const ", "=>", "$set", "updateOne(")
            )
            else "text"
        )
        return f"\n```{language}\n{normalized}\n```\n"

    content = re.sub(
        r"(?:<br\s*/?>\s*)?<code>(?P<body>.*?)</code>",
        replace_code,
        content,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return content


def normalize_mdx_steps(content: str) -> str:
    """Rewrite heading-like content inside <Step> blocks into safe markdown text.

    MDX can choke on ATX headings such as `### Title` when they appear directly
    inside JSX flow components like <Step>. Also, raw heading tags such as
    `<h3>Title</h3>` can end up nested inside `<p>` during hydration. Convert
    both forms into simple bold lines while leaving headings outside steps and
    fenced code alone.
    """

    def replace_step(match: re.Match) -> str:
        lead = match.group("lead")
        body = match.group("body")
        tail = match.group("tail")
        lines: list[str] = []
        in_fence = False

        for line in body.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("```"):
                in_fence = not in_fence
                lines.append(line)
                continue

            if not in_fence:
                heading = re.match(r"^(\s*)(#{1,6})\s+(.+?)\s*$", line)
                if heading:
                    indent, _hashes, title = heading.groups()
                    lines.append(f"{indent}**{title.strip()}**")
                    continue

                html_heading = re.match(r"^(\s*)<h[1-6]>(.+?)</h[1-6]>\s*$", line)
                if html_heading:
                    indent, title = html_heading.groups()
                    lines.append(f"{indent}**{title.strip()}**")
                    continue

            lines.append(line)

        normalized_body = "\n".join(lines)
        return f"{match.group('open')}{lead}{normalized_body}{tail}</Step>"

    return re.sub(
        r"(?P<open><Step(?:\s[^>]*)?>)(?P<lead>\s*)(?P<body>.*?)(?P<tail>\s*)</Step>",
        replace_step,
        content,
        flags=re.DOTALL,
    )


def repair_mdx_component_blocks(content: str) -> str:
    """Repair malformed block-level JSX components in generated MDX.

    LLM output sometimes emits inline-started components with fenced blocks, e.g.
    `<Callout>Text:\n```bash ...` where the closing tag appears after the fence.
    That structure breaks MDX parsing because the opening JSX tag is treated as an
    inline node inside a paragraph. Normalize those cases into multiline blocks.
    """

    multiline_components = (
        "Callout",
        "Card",
        "Tabs",
        "Tab",
        "Steps",
        "Step",
        "Accordions",
        "Accordion",
        "Frame",
    )

    for component in multiline_components:
        pattern = re.compile(
            rf"<({component})(\s[^>]*)?>([^\n<][^\n]*?):\s*\n(```[\s\S]*?```\s*</\1>)"
        )

        def _rewrite(match: re.Match) -> str:
            name = match.group(1)
            attrs = match.group(2) or ""
            lead = match.group(3).strip()
            tail = match.group(4)
            return f"<{name}{attrs}>\n{lead}:\n\n{tail}"

        content = pattern.sub(_rewrite, content)

    for component in multiline_components:
        open_count = len(re.findall(rf"<{component}(?:\s[^>]*)?>", content))
        close_count = len(re.findall(rf"</{component}>", content))
        if open_count <= close_count:
            continue
        deficit = open_count - close_count
        content = content.rstrip() + (f"\n</{component}>" * deficit) + "\n"

    return content
