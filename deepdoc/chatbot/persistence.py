"""Persistence helpers for chatbot corpora."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .types import ChunkRecord, RetrievedChunk

CORPUS_FILES = {
    "code": ("code_chunks.jsonl", "code_vectors.npy", "code.faiss"),
    "artifact": ("artifact_chunks.jsonl", "artifact_vectors.npy", "artifacts.faiss"),
    "doc_summary": ("doc_chunks.jsonl", "doc_vectors.npy", "docs.faiss"),
}


def ensure_index_dir(index_dir: Path) -> Path:
    index_dir.mkdir(parents=True, exist_ok=True)
    return index_dir


def corpus_paths(index_dir: Path, corpus: str) -> dict[str, Path]:
    chunk_file, vector_file, index_file = CORPUS_FILES[corpus]
    return {
        "chunks": index_dir / chunk_file,
        "vectors": index_dir / vector_file,
        "index": index_dir / index_file,
        "meta": index_dir / f"{corpus}_meta.json",
    }


def load_corpus(index_dir: Path, corpus: str) -> tuple[list[ChunkRecord], Any]:
    paths = corpus_paths(index_dir, corpus)
    if not paths["chunks"].exists():
        return [], []

    records = [
        ChunkRecord.from_dict(json.loads(line))
        for line in paths["chunks"].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not paths["vectors"].exists():
        return records, []
    try:
        import numpy as np

        vectors = np.load(paths["vectors"], allow_pickle=False)
        if vectors.ndim == 1 and vectors.size == 0:
            return records, []
        return records, vectors
    except Exception:
        raw = paths["vectors"].read_text(encoding="utf-8").strip()
        return records, json.loads(raw) if raw else []


def load_vector_index(index_dir: Path, corpus: str) -> Any | None:
    paths = corpus_paths(index_dir, corpus)
    if not paths["index"].exists():
        return None
    try:
        import faiss  # type: ignore

        return faiss.read_index(str(paths["index"]))
    except Exception:
        return None


def save_corpus(
    index_dir: Path,
    corpus: str,
    records: list[ChunkRecord],
    vectors: Any,
    meta: dict[str, Any] | None = None,
) -> None:
    ensure_index_dir(index_dir)
    paths = corpus_paths(index_dir, corpus)
    lines = [json.dumps(record.to_dict(), sort_keys=True) for record in records]
    paths["chunks"].write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    try:
        import numpy as np

        arr = np.asarray(vectors, dtype="float32")
        if arr.size == 0:
            arr = np.zeros((0, 0), dtype="float32")
        np.save(paths["vectors"], arr, allow_pickle=False)
        write_vector_index(paths["index"], arr)
    except Exception:
        paths["vectors"].write_text(json.dumps(vectors), encoding="utf-8")
        write_vector_index(paths["index"], vectors)
    paths["meta"].write_text(json.dumps(meta or {}, indent=2), encoding="utf-8")


def write_vector_index(path: Path, vectors: Any) -> None:
    try:
        import numpy as np
        import faiss  # type: ignore

        arr = np.asarray(vectors, dtype="float32")
        if arr.size == 0 or arr.ndim != 2:
            path.write_text("empty\n", encoding="utf-8")
            return
        normalized = normalize_vectors(arr)
        index = faiss.IndexFlatIP(normalized.shape[1])
        index.add(normalized)
        faiss.write_index(index, str(path))
    except Exception:
        path.write_text("numpy-fallback\n", encoding="utf-8")


def normalize_vectors(vectors: Any) -> Any:
    try:
        import numpy as np

        arr = np.asarray(vectors, dtype="float32")
        if arr.size == 0:
            return arr
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return arr / norms
    except Exception:
        normalized: list[list[float]] = []
        for row in vectors:
            norm = sum(value * value for value in row) ** 0.5 or 1.0
            normalized.append([float(value) / norm for value in row])
        return normalized


def similarity_search(
    records: list[ChunkRecord],
    vectors: Any,
    query_vector: list[float],
    top_k: int,
    *,
    vector_index: Any | None = None,
) -> list[RetrievedChunk]:
    if not records:
        return []
    if vector_index is not None:
        try:
            query = normalize_vectors([query_vector])
            scores, order = vector_index.search(query, top_k)
            return [
                RetrievedChunk(record=records[idx], score=float(score))
                for score, idx in zip(scores[0], order[0])
                if idx >= 0 and idx < len(records)
            ]
        except Exception:
            pass

    arr = normalize_vectors(vectors)
    try:
        import numpy as np

        if getattr(arr, "size", 0) == 0:
            return []
        query = normalize_vectors(np.asarray([query_vector], dtype="float32"))[0]
        scores = arr @ query
        order = np.argsort(scores)[::-1][:top_k]
        return [
            RetrievedChunk(record=records[idx], score=float(scores[idx]))
            for idx in order
            if idx < len(records)
        ]
    except Exception:
        if not arr:
            return []
        query = normalize_vectors([query_vector])[0]
        scored = []
        for idx, row in enumerate(arr):
            score = sum(left * right for left, right in zip(row, query))
            scored.append((score, idx))
        scored.sort(reverse=True)
        return [
            RetrievedChunk(record=records[idx], score=float(score))
            for score, idx in scored[:top_k]
            if idx < len(records)
        ]
