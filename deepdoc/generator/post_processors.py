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
from ..prompts import SYSTEM_V2, get_prompt_for_bucket
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
            # Insert comment AFTER the diagram type declaration line, not before it
            # (Mermaid requires diagram type as the very first line)
            first_nl = result.index("\n") if "\n" in result else len(result)
            result = (
                result[: first_nl + 1]
                + f"%% Note: possible duplicate node IDs: {', '.join(set(dupes))}\n"
                + result[first_nl + 1 :]
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


def _to_mkdocs_relative(url: str) -> str:
    """Identity function — kept for compatibility. Next.js uses root-absolute /slug paths natively."""
    return url


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
        relative = _to_mkdocs_relative(resolved)
        if relative == target:
            return match.group(0)
        return f"[{label}]({relative})"

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
        relative = _to_mkdocs_relative(resolved)
        if relative == target:
            return match.group(0)

        replaced_attrs = (
            attrs[: href_match.start("target")]
            + relative
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


_PROVENANCE_KEYS = frozenset({
    "deepdoc_generated_at",
    "deepdoc_generated_commit",
    "deepdoc_generated_version",
    "deepdoc_status",
    "deepdoc_evidence_files",
    "deepdoc_evidence_records",
    "deepdoc_prereqs",
    "deepdoc_generated_by",
    "stub",
})


def strip_leaked_provenance_fields(content: str) -> str:
    """Remove any deepdoc_* YAML-like fields that leaked into the document body."""
    if not content:
        return content
    lines = content.splitlines()
    in_frontmatter = False
    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if i == 0 and stripped == "---":
            in_frontmatter = True
            result.append(line)
            i += 1
            continue
        if in_frontmatter and stripped == "---":
            in_frontmatter = False
            result.append(line)
            i += 1
            continue
        if not in_frontmatter:
            key = stripped.split(":", 1)[0].strip()
            if key in _PROVENANCE_KEYS:
                i += 1
                while i < len(lines) and re.match(r"^\s{2,}-\s", lines[i]):
                    i += 1
                continue
        result.append(line)
        i += 1
    return "\n".join(result)


def inject_source_files_disclosure(content: str, evidence_files: list[str]) -> str:
    """Inject a collapsible source-file list after the first H1 heading."""
    if not content or not evidence_files:
        return content
    sorted_files = sorted(evidence_files)[:40]
    files_md = "\n".join(f"- [{f}]({f})" for f in sorted_files)
    disclosure = (
        "\n<details>\n<summary>Relevant source files</summary>\n\n"
        "The following files were used as context for generating this page:\n\n"
        f"{files_md}\n\n</details>\n"
    )
    patched, count = re.subn(
        r"(^#\s+[^\n]+\n)",
        r"\1" + disclosure,
        content,
        count=1,
        flags=re.MULTILINE,
    )
    return patched if count else content


def fix_frontmatter_description(content: str) -> str:
    """Strip directive artefacts (trailing ::, :::) from frontmatter description field.

    The LLM sometimes writes description values that end with :: or ::: which
    the remark-directive plugin then partially parses, corrupting the nav sidebar.
    """
    def clean_description(m: re.Match) -> str:
        prefix = m.group(1)   # "description: "
        value = m.group(2)    # the value only
        value = re.sub(r'\s*:{2,3}\s*$', '', value.rstrip())
        return f'{prefix}{value}'

    return re.sub(
        r'^(description:\s*)(["\']?.*?["\']?)\s*$',
        clean_description,
        content,
        flags=re.MULTILINE,
    )


def fix_bare_mermaid_fences(content: str) -> str:
    """Repair mermaid diagrams where the LLM omitted the opening code fence.

    The LLM sometimes writes just the word 'mermaid' on its own line followed
    by diagram content and a closing ``` — instead of the correct ```mermaid
    opening fence.  This produces a bare 'mermaid' paragraph in MDX and leaves
    the diagram body (including {node} labels) unescaped, causing acorn parse
    errors.

    Pattern matched:
        <text ending in : or .\n>
        mermaid\n
        <diagram type line, e.g. sequenceDiagram>\n
        ...diagram body...
        ```
    """
    return re.sub(
        r'(?m)^mermaid\n(?=(sequenceDiagram|flowchart|graph|classDiagram|stateDiagram|erDiagram|gantt|pie|gitGraph|mindmap|timeline|journey|quadrantChart|xychart|block|packet|kanban|architecture))',
        '```mermaid\n',
        content,
    )


def fix_bare_language_markers(content: str) -> str:
    """Repair lines where the LLM wrote a bare language name instead of opening a fence.

    Two variants the LLM produces:

    1. Suffix variant — language appended after a colon:
           Some description text:typescript
           interface Foo { ... }
           ```

    2. Standalone variant — language on its own line:
           #### Example Usage
           typescript
           <Component ... />
           ```

    Both leave the code content in free MDX body causing acorn parse errors.
    """
    _LANGS = (
        r"typescript|javascript|python|bash|json|yaml|tsx|jsx"
        r"|go|rust|java|css|html|sql|sh|text|plaintext|ruby|php|c|cpp|swift"
    )
    # Variant 1: text ending in :language
    content = re.sub(
        rf"^(.*\S):({_LANGS})\s*$",
        lambda m: f"{m.group(1)}\n```{m.group(2)}",
        content,
        flags=re.MULTILINE,
    )
    # Variant 2: language word alone on its own line (must be preceded by non-code line)
    content = re.sub(
        rf"^({_LANGS})\n",
        lambda m: f"```{m.group(1)}\n",
        content,
        flags=re.MULTILINE,
    )
    return content


def unwrap_markdown_trapped_in_code_fences(content: str) -> str:
    """Detect code fences that contain markdown content and unwrap them.

    The LLM sometimes forgets to close a code fence, leaving section headers
    (## ...), callout blocks (/// ...), and horizontal rules (---) trapped
    inside a code block. These render as literal text instead of rich content.
    """
    # Pattern: a fenced block that contains markdown indicators
    MD_INDICATORS = re.compile(
        r"^(?:#{1,6}\s|///\s|\-\-\-\s*$|^\*\*\*\s*$)",
        re.MULTILINE,
    )

    def maybe_unwrap(m: re.Match) -> str:
        lang = m.group(1)  # may be empty for plain ```
        body = m.group(2)
        # If body contains markdown indicators, unwrap it
        if MD_INDICATORS.search(body):
            return body
        return m.group(0)  # leave intact

    return re.sub(
        r"```([A-Za-z0-9_+-]*)\n([\s\S]*?)\n```",
        maybe_unwrap,
        content,
    )


def extract_glossary_terms(glossary_content: str) -> list[tuple[str, str]]:
    """Parse `### TermName` (h3) headings from glossary MDX → [(term, anchor-slug)].

    Anchor slug matches GitHub auto-anchor: lowercase, non-alphanumeric → hyphen,
    consecutive hyphens collapsed, leading/trailing hyphens trimmed.
    """
    terms: list[tuple[str, str]] = []
    for line in glossary_content.splitlines():
        m = re.match(r"^###\s+([^\n#].*?)\s*$", line)
        if not m:
            continue
        term = m.group(1).strip()
        if not term or term.startswith("#"):
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-")
        slug = re.sub(r"-+", "-", slug)
        if slug:
            terms.append((term, slug))
    return terms


def _is_term_linkable(term: str) -> bool:
    """Filter out generic terms that would create noisy links."""
    stripped = term.strip()
    if len(stripped) < 4:
        return False
    if " " in stripped or "-" in stripped or "_" in stripped:
        return True
    # Single word: require PascalCase / camelCase / has digit / longer than 6 chars
    if any(c.isupper() for c in stripped[1:]):
        return True
    if any(c.isdigit() for c in stripped):
        return True
    return len(stripped) >= 7


def link_glossary_terms(content: str, terms: list[tuple[str, str]]) -> str:
    """Auto-link first occurrence of each glossary term to /domain-glossary#<slug>.

    Skips: fenced code blocks (``` ... ```), inline code (`...`), existing
    markdown links ([..](..)), headings (#... lines), and frontmatter (--- ... ---).
    First occurrence per page only.
    """
    if not terms or not content:
        return content

    linkable = [(t, s) for (t, s) in terms if _is_term_linkable(t)]
    if not linkable:
        return content

    # Order longest-first so multi-word terms win over substrings.
    linkable.sort(key=lambda ts: len(ts[0]), reverse=True)

    lines = content.split("\n")
    in_fence = False
    in_frontmatter = lines and lines[0].strip() == "---"
    fm_close_idx = -1
    if in_frontmatter:
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                fm_close_idx = i
                break

    linked: set[str] = set()

    def _rewrite_segment(segment: str) -> str:
        if not segment.strip():
            return segment
        for term, slug in linkable:
            if term in linked:
                continue
            pattern = re.compile(
                r"(?<![\w/#-])" + re.escape(term) + r"(?![\w/-])",
                re.IGNORECASE,
            )
            m = pattern.search(segment)
            if not m:
                continue
            start, end = m.span()
            replacement = f"[{m.group(0)}](domain-glossary.md#{slug})"
            segment = segment[:start] + replacement + segment[end:]
            linked.add(term)
        return segment

    def _rewrite_line(line: str) -> str:
        # Split out inline code spans and existing links — only rewrite the rest.
        parts = re.split(r"(`[^`\n]*`|\[[^\]]*\]\([^)]*\))", line)
        for i, part in enumerate(parts):
            if not part or part.startswith("`") or part.startswith("["):
                continue
            parts[i] = _rewrite_segment(part)
        return "".join(parts)

    out: list[str] = []
    for idx, line in enumerate(lines):
        if in_frontmatter and idx <= fm_close_idx:
            out.append(line)
            continue
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        if stripped.startswith("#"):
            out.append(line)
            continue
        out.append(_rewrite_line(line))
    return "\n".join(out)
