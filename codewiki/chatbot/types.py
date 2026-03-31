"""Shared chatbot datatypes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ChunkKind = Literal["code", "artifact", "doc_summary"]


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
    artifact_type: str = ""
    section_name: str = ""
    start_line: int = 0
    end_line: int = 0
    symbol_names: list[str] = field(default_factory=list)
    imports_summary: list[str] = field(default_factory=list)
    related_bucket_slugs: list[str] = field(default_factory=list)
    owned_files: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChunkRecord":
        return cls(**data)


@dataclass
class RetrievedChunk:
    """A chunk returned by similarity search."""

    record: ChunkRecord
    score: float

