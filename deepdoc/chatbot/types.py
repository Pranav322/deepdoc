"""Shared chatbot datatypes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ChunkKind = Literal[
    "code",
    "artifact",
    "doc_summary",
    "doc_full",
    "repo_doc",
    "relationship",
]


@dataclass
class ChunkRecord:
    """One retrievable chunk in the chatbot knowledge base."""

    chunk_id: str
    kind: ChunkKind
    source_key: str
    text: str
    chunk_hash: str
    title: str = ""
    file_path: str = ""
    doc_path: str = ""
    doc_url: str = ""
    language: str = ""
    framework: str = ""
    artifact_type: str = ""
    section_name: str = ""
    source_kind: str = ""
    publication_tier: str = ""
    trust_score: float = 0.0
    start_line: int = 0
    end_line: int = 0
    symbol_names: list[str] = field(default_factory=list)
    imports_summary: list[str] = field(default_factory=list)
    related_bucket_slugs: list[str] = field(default_factory=list)
    owned_files: list[str] = field(default_factory=list)
    linked_file_paths: list[str] = field(default_factory=list)
    related_doc_paths: list[str] = field(default_factory=list)
    related_doc_urls: list[str] = field(default_factory=list)
    related_doc_titles: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChunkRecord:
        return cls(**data)


@dataclass
class RetrievedChunk:
    """A chunk returned by similarity search."""

    record: ChunkRecord
    score: float


EvidenceKind = Literal["source", "config"]
EvidenceRole = Literal["entrypoint", "implementation", "supporting", "config"]
ReferenceKind = Literal["generated_doc", "repo_doc"]


@dataclass
class EvidenceItem:
    """Canonical source-backed proof shared by answers and the code pane."""

    id: str
    kind: EvidenceKind
    file_path: str
    start_line: int
    end_line: int
    snippet: str
    role: EvidenceRole = "supporting"
    confidence: float = 0.0
    title: str = ""
    language: str = ""
    symbol_names: list[str] = field(default_factory=list)
    source_kind: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReferenceItem:
    """Reference-only docs context that must not be used as source proof."""

    kind: ReferenceKind
    path: str
    title: str = ""
    url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RetrievalDiagnostics:
    """Diagnostics describing evidence assembly and answer validation."""

    evidence_count: int = 0
    reference_count: int = 0
    rejected_paths: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    validation_retried: bool = False
    validation_failed_closed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SourceCatalogEntry:
    """One source/config file available for evidence hydration."""

    file_path: str
    content_hash: str
    source_kind: str
    language: str
    total_lines: int
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceCatalogEntry:
        return cls(**data)
