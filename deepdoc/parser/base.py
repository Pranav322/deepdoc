"""Shared data structures for all parsers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

SymbolKind = Literal[
    "function",
    "class",
    "method",
    "interface",
    "type",
    "route",
    "constant",
    "enum",
    "component",
    "hook",
]


@dataclass
class Symbol:
    """A named code symbol extracted from a file."""

    name: str
    kind: SymbolKind
    signature: str  # first line / declaration
    docstring: str = ""  # inline doc / comment above
    body_preview: str = ""  # first few lines of body
    start_line: int = 0
    end_line: int = 0
    decorators: list[str] = field(default_factory=list)  # @decorator / #[Attribute]
    visibility: str = ""  # "public", "private", "protected", "exported", "internal"
    fields: list[str] = field(default_factory=list)  # struct/class fields summary
    props: list[str] = field(default_factory=list)  # React component props
    is_exported: bool = False

    def __post_init__(self) -> None:
        self.start_line = max(int(self.start_line or 0), 0)
        self.end_line = max(int(self.end_line or 0), 0)
        if self.start_line <= 0:
            self.end_line = 0
        elif self.end_line > 0 and self.end_line < self.start_line:
            self.end_line = self.start_line

    def has_known_range(self) -> bool:
        return self.start_line > 0 and self.end_line >= self.start_line > 0

    def normalized_range(self) -> tuple[int, int] | None:
        """Return a safe line range for downstream consumers.

        Some fallback parsers only know where a symbol starts. Preserve that raw
        distinction in ``end_line == 0`` for callers that care, but provide a
        single-line fallback range everywhere else so chunking and clustering can
        proceed safely.
        """
        if self.start_line <= 0:
            return None
        end_line = (
            self.end_line if self.end_line >= self.start_line else self.start_line
        )
        return self.start_line, end_line


@dataclass
class ParsedFile:
    """Structured representation of a source file."""

    path: Path
    language: str
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    raw_content: str = ""

    @property
    def relative_path(self) -> str:
        return str(self.path)

    def summary_text(self) -> str:
        """Return a compact text representation for LLM context."""
        lines = [f"# File: {self.path}", f"Language: {self.language}", ""]
        if self.imports:
            lines.append("## Imports")
            lines.extend(f"- {i}" for i in self.imports[:20])
            lines.append("")
        if self.symbols:
            lines.append("## Symbols")
            for s in self.symbols:
                export_tag = " (exported)" if s.is_exported else ""
                vis_tag = f" [{s.visibility}]" if s.visibility else ""
                lines.append(f"### {s.kind}: {s.name}{export_tag}{vis_tag}")
                if s.decorators:
                    lines.append("Decorators: " + ", ".join(s.decorators))
                lines.append(f"```\n{s.signature}\n```")
                if s.docstring:
                    lines.append(f"> {s.docstring}")
                if s.fields:
                    lines.append("Fields: " + ", ".join(s.fields[:15]))
                if s.props:
                    lines.append("Props: " + ", ".join(s.props[:15]))
                if s.body_preview:
                    lines.append(f"```\n{s.body_preview}\n```")
                lines.append("")
        return "\n".join(lines)
