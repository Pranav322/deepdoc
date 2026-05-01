"""Persistence helpers for chatbot corpora."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from .types import ChunkRecord, RetrievedChunk, SourceCatalogEntry

CORPUS_FILES = {
    "code": ("code_chunks.jsonl", "code_vectors.npy", "code.faiss"),
    "symbol": ("symbol_chunks.jsonl", "symbol_vectors.npy", "symbol.faiss"),
    "artifact": ("artifact_chunks.jsonl", "artifact_vectors.npy", "artifacts.faiss"),
    "doc_summary": ("doc_chunks.jsonl", "doc_vectors.npy", "docs.faiss"),
    "doc_full": ("doc_full_chunks.jsonl", "doc_full_vectors.npy", "docs_full.faiss"),
    "repo_doc": ("repo_doc_chunks.jsonl", "repo_doc_vectors.npy", "repo_docs.faiss"),
    "relationship": (
        "relationship_chunks.jsonl",
        "relationship_vectors.npy",
        "relationship.faiss",
    ),
}
LEXICAL_DB_FILE = "lexical_index.sqlite3"
SOURCE_CATALOG_FILE = "source_catalog.json"
INDEX_MANIFEST_FILE = "index_manifest.json"


def ensure_index_dir(index_dir: Path) -> Path:
    index_dir.mkdir(parents=True, exist_ok=True)
    return index_dir


def lexical_index_path(index_dir: Path) -> Path:
    return ensure_index_dir(index_dir) / LEXICAL_DB_FILE


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
    paths["chunks"].write_text(
        "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
    )

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
    save_lexical_corpus(index_dir, corpus, records)


def save_lexical_corpus(
    index_dir: Path,
    corpus: str,
    records: list[ChunkRecord],
) -> None:
    db_path = lexical_index_path(index_dir)
    conn = sqlite3.connect(db_path)
    try:
        _ensure_lexical_schema(conn)
        conn.execute("DELETE FROM lexical_chunks WHERE corpus = ?", (corpus,))
        if records:
            conn.executemany(
                """
                INSERT INTO lexical_chunks (
                    corpus,
                    chunk_id,
                    file_path,
                    file_name,
                    title,
                    symbols,
                    metadata,
                    text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        corpus,
                        record.chunk_id,
                        record.file_path or record.doc_path,
                        Path(record.file_path or record.doc_path or "").name,
                        record.title,
                        " ".join(record.symbol_names or []),
                        _lexical_metadata_blob(record),
                        record.text,
                    )
                    for record in records
                ],
            )
        conn.commit()
    finally:
        conn.close()


def query_lexical_index(
    index_dir: Path,
    corpus: str,
    match_query: str,
    limit: int,
) -> list[str]:
    if not match_query.strip():
        return []
    db_path = lexical_index_path(index_dir)
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        _ensure_lexical_schema(conn)
        rows = conn.execute(
            """
            SELECT chunk_id
            FROM lexical_chunks
            WHERE corpus = ? AND lexical_chunks MATCH ?
            ORDER BY bm25(lexical_chunks, 8.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0)
            LIMIT ?
            """,
            (corpus, match_query, max(int(limit), 1)),
        ).fetchall()
        return [str(row[0]) for row in rows if row and row[0]]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _ensure_lexical_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS lexical_chunks USING fts5(
            corpus UNINDEXED,
            chunk_id UNINDEXED,
            file_path,
            file_name,
            title,
            symbols,
            metadata,
            text,
            tokenize='unicode61'
        )
        """
    )


def _lexical_metadata_blob(record: ChunkRecord) -> str:
    metadata_bits: list[str] = [
        record.language,
        record.framework,
        record.artifact_type,
        record.section_name,
        record.source_kind,
        record.publication_tier,
        record.doc_path,
        record.doc_url,
        " ".join(record.imports_summary or []),
        " ".join(record.linked_file_paths or []),
        " ".join(record.related_doc_paths or []),
        " ".join(record.related_doc_urls or []),
        " ".join(record.related_doc_titles or []),
    ]
    if record.metadata:
        metadata_bits.append(json.dumps(record.metadata, sort_keys=True))
    return " ".join(bit for bit in metadata_bits if bit)


def save_source_archive(index_dir: Path, archive_data: dict[str, str]) -> None:
    ensure_index_dir(index_dir)
    archive_path = index_dir / "source_archive.json.gz"
    payload = json.dumps(archive_data, sort_keys=True).encode("utf-8")
    with archive_path.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            gz.write(payload)


def load_source_archive(index_dir: Path) -> dict[str, str]:
    archive_path = index_dir / "source_archive.json.gz"
    if not archive_path.exists():
        return {}
    try:
        with gzip.open(archive_path, "rt", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_source_catalog(
    index_dir: Path,
    entries: list[SourceCatalogEntry],
) -> None:
    ensure_index_dir(index_dir)
    (index_dir / SOURCE_CATALOG_FILE).write_text(
        json.dumps([entry.to_dict() for entry in entries], indent=2, sort_keys=True),
        encoding="utf-8",
    )


def load_source_catalog(index_dir: Path) -> list[SourceCatalogEntry]:
    catalog_path = index_dir / SOURCE_CATALOG_FILE
    if not catalog_path.exists():
        return []
    try:
        raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    entries: list[SourceCatalogEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            entries.append(SourceCatalogEntry.from_dict(item))
        except TypeError:
            continue
    return entries


def save_index_manifest(index_dir: Path) -> dict[str, Any]:
    manifest = build_index_manifest(index_dir)
    ensure_index_dir(index_dir)
    (index_dir / INDEX_MANIFEST_FILE).write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return manifest


def load_index_manifest(index_dir: Path) -> dict[str, Any]:
    path = index_dir / INDEX_MANIFEST_FILE
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def build_index_manifest(index_dir: Path) -> dict[str, Any]:
    artifacts: dict[str, Any] = {}
    for corpus in sorted(CORPUS_FILES):
        paths = corpus_paths(index_dir, corpus)
        chunk_text = _read_text(paths["chunks"])
        meta = _read_json_object(paths["meta"])
        artifacts[corpus] = {
            "kind": "semantic_chunks",
            "chunk_file": paths["chunks"].name,
            "vector_file": paths["vectors"].name,
            "faiss_file": paths["index"].name,
            "record_count": len([line for line in chunk_text.splitlines() if line.strip()]),
            "content_hash": _sha256_text(chunk_text),
            "schema_version": meta.get("schema_version"),
            "embedding_model": meta.get("embedding_model"),
        }

    catalog_entries = load_source_catalog(index_dir)
    artifacts["source_catalog"] = {
        "kind": "source_catalog",
        "file": SOURCE_CATALOG_FILE,
        "record_count": len(catalog_entries),
        "content_hash": _sha256_text(
            json.dumps([entry.to_dict() for entry in catalog_entries], sort_keys=True)
        ),
    }
    archive = load_source_archive(index_dir)
    artifacts["source_archive"] = {
        "kind": "source_archive",
        "file": "source_archive.json.gz",
        "record_count": len(archive),
        "content_hash": _sha256_text(json.dumps(archive, sort_keys=True)),
    }
    artifacts["lexical_index"] = {
        "kind": "lexical_index",
        "file": LEXICAL_DB_FILE,
        "record_count_by_corpus": _lexical_record_counts(index_dir),
    }
    call_graph_path = index_dir / "call_graph.json"
    artifacts["relationship_graph"] = {
        "kind": "relationship_graph",
        "file": call_graph_path.name,
        "content_hash": _sha256_text(_read_text(call_graph_path)),
        "exists": call_graph_path.exists(),
    }
    return {"version": 1, "artifacts": artifacts}


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _lexical_record_counts(index_dir: Path) -> dict[str, int]:
    db_path = lexical_index_path(index_dir)
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(db_path)
    try:
        _ensure_lexical_schema(conn)
        rows = conn.execute(
            "SELECT corpus, COUNT(*) FROM lexical_chunks GROUP BY corpus ORDER BY corpus"
        ).fetchall()
        return {str(corpus): int(count) for corpus, count in rows}
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def write_vector_index(path: Path, vectors: Any) -> None:
    try:
        import faiss  # type: ignore
        import numpy as np

        arr = np.asarray(vectors, dtype="float32")
        if arr.size == 0 or arr.ndim != 2:
            path.write_text("empty\n", encoding="utf-8")
            return
        normalized = normalize_vectors(arr)
        # FAISS IndexFlatIP performs inner product search on normalized vectors
        # The dimension is the second dimension of the array
        dim = normalized.shape[1] if normalized.ndim == 2 else 384
        index = faiss.IndexFlatIP(dim)
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
                for score, idx in zip(scores[0], order[0], strict=False)
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
            score = sum(left * right for left, right in zip(row, query, strict=False))
            scored.append((score, idx))
        scored.sort(reverse=True)
        return [
            RetrievedChunk(record=records[idx], score=float(score))
            for score, idx in scored[:top_k]
            if idx < len(records)
        ]
