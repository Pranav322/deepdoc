from typing import Any

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str
    history: list[dict[str, str]] = Field(default_factory=list)


class QueryResponse(BaseModel):
    answer: str
    code_citations: list[dict[str, Any]]
    artifact_citations: list[dict[str, Any]]
    doc_links: list[dict[str, Any]]
    used_chunks: int
