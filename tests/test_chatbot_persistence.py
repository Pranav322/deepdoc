from __future__ import annotations

from deepdoc.chatbot.persistence import similarity_search
from deepdoc.chatbot.types import ChunkRecord


class _FakeFaissIndex:
    def search(self, query, top_k):
        del query, top_k
        return [[0.95, 0.75]], [[1, 0]]


def test_similarity_search_uses_loaded_index_when_available() -> None:
    records = [
        ChunkRecord(
            chunk_id="c1",
            kind="code",
            source_key="src/first.py",
            text="def first(): ...",
            chunk_hash="h1",
            file_path="src/first.py",
        ),
        ChunkRecord(
            chunk_id="c2",
            kind="code",
            source_key="src/second.py",
            text="def second(): ...",
            chunk_hash="h2",
            file_path="src/second.py",
        ),
    ]

    hits = similarity_search(
        records,
        [[1.0, 0.0], [0.0, 1.0]],
        [1.0, 0.0],
        2,
        vector_index=_FakeFaissIndex(),
    )

    assert [hit.record.file_path for hit in hits] == ["src/second.py", "src/first.py"]
    assert [hit.score for hit in hits] == [0.95, 0.75]
