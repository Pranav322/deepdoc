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

def normalize_code_fence_languages(content: str) -> str:
    """Normalize unsupported or inconsistent fence labels to safe Shiki languages."""

    alias_map = {
        "env": "bash",
        "dotenv": "bash",
        "shell": "bash",
        "sh": "bash",
        "redis": "bash",
        "curl": "bash",
        "conf": "ini",
        "config": "ini",
        "text": "plaintext",
        "txt": "plaintext",
        "plain": "plaintext",
        "requirements": "plaintext",
        "output": "plaintext",
    }

    # Languages included in Shiki's default bundle (fumadocs uses bundled-all).
    # Anything outside this set falls back to plaintext to avoid build failures.
    _SHIKI_BUNDLED = {
        "abap", "actionscript-3", "ada", "angular-html", "angular-ts",
        "apache", "apex", "apl", "applescript", "ara", "asciidoc", "asm",
        "astro", "awk", "ballerina", "bat", "batch", "beancount", "berry",
        "be", "bibtex", "bicep", "blade", "c", "cadence", "cdc", "clarity",
        "clojure", "clj", "cmake", "cobol", "codeowners", "coffescript",
        "common-lisp", "lisp", "coq", "cpp", "crystal", "csharp", "cs",
        "css", "csv", "cue", "cypher", "d", "dart", "dax", "desktop",
        "diff", "docker", "dockerfile", "dotenv", "dream-maker", "edge",
        "elixir", "elm", "emacs-lisp", "erb", "erlang", "fennel", "fish",
        "fluent", "fortran-fixed-form", "fortran-free-form", "fsharp",
        "gdresource", "gdscript", "gdshader", "genie", "gherkin", "git-commit",
        "git-rebase", "gleam", "glimmer-js", "glimmer-ts", "glsl", "gnuplot",
        "go", "graphql", "gql", "groovy", "hack", "haml", "handlebars", "hbs",
        "haskell", "hcl", "hjson", "hlsl", "html", "html-derivative", "http",
        "hxml", "hy", "imba", "ini", "toml", "java", "javascript", "js",
        "jinja", "jinja-html", "jison", "json", "json5", "jsonc", "jsonl",
        "jsonnet", "jssm", "jsx", "julia", "kotlin", "kusto", "kql", "latex",
        "lean", "less", "liquid", "log", "logo", "lua", "luau", "make",
        "makefile", "markdown", "md", "marko", "matlab", "mdc", "mdx",
        "mermaid", "mipsasm", "mojo", "move", "narrat", "nextflow", "nf",
        "nginx", "nim", "nix", "nushell", "nu", "objective-c", "objc",
        "objective-cpp", "ocaml", "pascal", "perl", "php", "plsql",
        "postcss", "powerquery", "powershell", "ps", "ps1", "prisma",
        "prolog", "proto", "protobuf", "puppet", "purescript", "python",
        "py", "r", "raku", "perl6", "razor", "reg", "regexp", "regex",
        "rel", "riscv", "rst", "ruby", "rb", "rust", "rs", "sas", "sass",
        "scala", "scheme", "scss", "shaderlab", "shader", "shellscript",
        "bash", "sh", "shell", "zsh", "smalltalk", "solidity", "soy",
        "sparql", "splunk", "spl", "sql", "ssh-config", "stata", "stylus",
        "styl", "svelte", "swift", "system-verilog", "systemd", "tasl",
        "tcl", "templ", "terraform", "tex", "toml", "ts", "tsv", "tsx",
        "turtle", "twig", "typescript", "typespec", "typst", "v", "vb",
        "cmd", "verilog", "vhdl", "viml", "vim", "vimscript", "vue",
        "vue-html", "vyper", "wasm", "wenyan", "wgsl", "wikitext",
        "mediawiki", "wolfram", "xml", "xsl", "yaml", "yml", "zenscript",
        "zig", "plaintext",
    }

    def replace(match: re.Match) -> str:
        indent = match.group(1) or ""
        lang = match.group(2)
        rest = match.group(3) or ""
        normalized = alias_map.get(lang.lower(), lang)
        # Fall back to plaintext for langs not in Shiki's bundle to prevent build failures
        if normalized.lower() not in _SHIKI_BUNDLED:
            normalized = "plaintext"
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


# Patterns that break the MDX parser when .md files are processed with format:'mdx'.
# - `<=` and bare `<` before space/digit → MDX tries to open a JSX tag
# - `{...}` containing `:` or starting with digit/quote → MDX tries to eval as JS expression
_MDX_ANGLE_HAZARDS = re.compile(r"<=|<(?=\s|\d)")
_MDX_BRACE_HAZARDS = re.compile(r"\{([^}]*[:][^}]*|[0-9\"][^}]*)\}")


def escape_mdx_angle_hazards(content: str) -> str:
    """Escape MDX parse hazards outside code blocks and YAML frontmatter.

    Handles:
    - `<=` / bare `<` before space or digit (would be parsed as JSX tag open)
    - `{...}` with dict-like content (would be parsed as JS expression)
    """
    # Split off YAML frontmatter so we never touch it — frontmatter uses raw
    # JSON objects as field values and must not be HTML-entity escaped.
    frontmatter = ""
    body = content
    fm_match = re.match(r"^(---\n[\s\S]*?\n---\n)", content)
    if fm_match:
        frontmatter = fm_match.group(1)
        body = content[len(frontmatter):]

    parts = re.split(r"(```[\s\S]*?```)", body)
    result = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            result.append(part)
        else:
            part = _MDX_ANGLE_HAZARDS.sub(lambda m: "&lt;" + m.group(0)[1:], part)
            part = _MDX_BRACE_HAZARDS.sub(lambda m: "&#123;" + m.group(1) + "&#125;", part)
            result.append(part)
    return frontmatter + "".join(result)


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
            replacement = f"[{m.group(0)}](/domain-glossary#{slug})"
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
