from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from deepdoc.chatbot.persistence import save_corpus
from deepdoc.chatbot.service import ChatbotQueryService, create_fastapi_app
from deepdoc.chatbot.types import ChunkRecord, RetrievedChunk
from deepdoc.persistence_v2 import save_plan
from tests.conftest import make_bucket, make_plan


class _FakeEmbedClient:
    def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


class _FakeChatClient:
    """Handles answer, expansion, and reranking prompts."""

    def complete(self, system: str, user: str) -> str:
        if "alternative search queries" in system:
            return "authentication login\nauth middleware handler"
        if "relevance scorer" in system.lower() or "Rate each chunk" in user:
            # Return one score per line — count the numbered items
            lines = [line for line in user.splitlines() if line.strip() and line.strip()[0].isdigit()]
            return "\n".join("8" for _ in lines) if lines else "8"
        return "Grounded answer"


class _FailingEmbedClient:
    def embed(self, texts):
        raise RuntimeError("Embedding request failed: missing API key")


class _UnexpectedChatClient:
    def complete(self, system: str, user: str) -> str:
        raise AssertionError("chat model should not be called without retrieved context")


def test_query_service_returns_code_and_artifact_citations(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text("chatbot:\n  enabled: true\n", encoding="utf-8")

    plan = make_plan([make_bucket("Auth", "auth", ["src/auth.py"])])
    save_plan(plan, repo_root)

    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(
        index_dir,
        "code",
        [
            ChunkRecord(
                chunk_id="c1",
                kind="code",
                source_key="src/auth.py",
                text="File: src/auth.py\nLines: 10-20\n\ndef login(user): ...",
                chunk_hash="hashc1",
                file_path="src/auth.py",
                start_line=10,
                end_line=20,
                symbol_names=["login"],
                related_bucket_slugs=["auth"],
            )
        ],
        [[1.0, 0.0]],
    )
    save_corpus(
        index_dir,
        "artifact",
        [
            ChunkRecord(
                chunk_id="a1",
                kind="artifact",
                source_key="package.json",
                text="Artifact: package.json\nType: json\n\nscripts: dev",
                chunk_hash="hasha1",
                file_path="package.json",
                artifact_type="json",
                start_line=1,
                end_line=5,
            )
        ],
        [[1.0, 0.0]],
    )
    save_corpus(index_dir, "doc_summary", [], [])

    cfg = {
        "chatbot": {
            "enabled": True,
            "backend": {"base_url": "http://127.0.0.1:8001"},
        }
    }

    with (
        patch("deepdoc.chatbot.service.build_embedding_client", return_value=_FakeEmbedClient()),
        patch("deepdoc.chatbot.service.build_chat_client", return_value=_FakeChatClient()),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.query("Where is auth handled?")

    assert result["answer"] == "Grounded answer"
    assert result["code_citations"][0]["file_path"] == "src/auth.py"
    assert result["artifact_citations"][0]["file_path"] == "package.json"
    assert result["doc_links"][0]["url"] == "/auth"


def test_fastapi_query_endpoint_accepts_json_body(tmp_path: Path) -> None:
    testclient = pytest.importorskip("fastapi.testclient")
    TestClient = testclient.TestClient

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text("chatbot:\n  enabled: true\n", encoding="utf-8")

    plan = make_plan([make_bucket("Auth", "auth", ["src/auth.py"])])
    save_plan(plan, repo_root)

    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(index_dir, "code", [], [])
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])

    cfg = {
        "chatbot": {
            "enabled": True,
            "backend": {"base_url": "http://127.0.0.1:8001"},
        }
    }

    with (
        patch("deepdoc.chatbot.service.build_embedding_client", return_value=_FakeEmbedClient()),
        patch("deepdoc.chatbot.service.build_chat_client", return_value=_FakeChatClient()),
    ):
        app = create_fastapi_app(repo_root, cfg)
        client = TestClient(app)
        response = client.post("/query", json={"question": "Where is auth handled?"})

    assert response.status_code == 200
    assert "couldn't find any indexed code" in response.json()["answer"]
    assert response.json()["used_chunks"] == 0


def test_query_service_returns_no_context_response_when_retrieval_is_empty(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text("chatbot:\n  enabled: true\n", encoding="utf-8")

    plan = make_plan([make_bucket("Auth", "auth", ["src/auth.py"])])
    save_plan(plan, repo_root)

    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(index_dir, "code", [], [])
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])

    cfg = {"chatbot": {"enabled": True}}

    with (
        patch("deepdoc.chatbot.service.build_embedding_client", return_value=_FakeEmbedClient()),
        patch("deepdoc.chatbot.service.build_chat_client", return_value=_UnexpectedChatClient()),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.query("how many background syncs are there?")

    assert "couldn't find any indexed code" in result["answer"]
    assert result["used_chunks"] == 0
    assert result["code_citations"] == []
    assert result["artifact_citations"] == []


def test_fastapi_query_endpoint_returns_json_error_payload(tmp_path: Path) -> None:
    testclient = pytest.importorskip("fastapi.testclient")
    TestClient = testclient.TestClient

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text("chatbot:\n  enabled: true\n", encoding="utf-8")

    plan = make_plan([make_bucket("Auth", "auth", ["src/auth.py"])])
    save_plan(plan, repo_root)

    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(index_dir, "code", [], [])
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])

    cfg = {
        "chatbot": {
            "enabled": True,
            "backend": {"base_url": "http://127.0.0.1:8001"},
        }
    }

    with (
        patch("deepdoc.chatbot.service.build_embedding_client", return_value=_FailingEmbedClient()),
        patch("deepdoc.chatbot.service.build_chat_client", return_value=_FakeChatClient()),
    ):
        app = create_fastapi_app(repo_root, cfg)
        client = TestClient(app)
        response = client.post("/query", json={"question": "Where is auth handled?"})

    assert response.status_code == 500
    assert response.json()["error"] == "chatbot_query_failed"
    assert "missing API key" in response.json()["detail"]


def test_query_expansion_generates_multiple_queries(tmp_path: Path) -> None:
    """When query_expansion is enabled, the service embeds multiple queries."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text("chatbot:\n  enabled: true\n", encoding="utf-8")

    plan = make_plan([make_bucket("Auth", "auth", ["src/auth.py"])])
    save_plan(plan, repo_root)

    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(
        index_dir, "code",
        [ChunkRecord(chunk_id="c1", kind="code", source_key="src/auth.py",
                     text="def login(user): ...", chunk_hash="h1",
                     file_path="src/auth.py", start_line=1, end_line=5,
                     symbol_names=["login"], related_bucket_slugs=["auth"])],
        [[1.0, 0.0]],
    )
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])

    cfg = {"chatbot": {"enabled": True, "retrieval": {"query_expansion": True}}}

    embed_client = _FakeEmbedClient()
    embed_calls: list[list[str]] = []
    original_embed = embed_client.embed

    def tracking_embed(texts):
        embed_calls.append(texts)
        return original_embed(texts)

    embed_client.embed = tracking_embed

    with (
        patch("deepdoc.chatbot.service.build_embedding_client", return_value=embed_client),
        patch("deepdoc.chatbot.service.build_chat_client", return_value=_FakeChatClient()),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.query("Where is auth handled?")

    assert result["answer"] == "Grounded answer"
    # Expansion should have embedded more than just the original query
    assert len(embed_calls) == 1  # single batch call
    assert len(embed_calls[0]) > 1  # original + expanded queries


def test_query_expansion_disabled_uses_single_query(tmp_path: Path) -> None:
    """When query_expansion is False, only the original query is embedded."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text("chatbot:\n  enabled: true\n", encoding="utf-8")

    plan = make_plan([make_bucket("Auth", "auth", ["src/auth.py"])])
    save_plan(plan, repo_root)

    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(index_dir, "code", [], [])
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])

    cfg = {"chatbot": {"enabled": True, "retrieval": {"query_expansion": False}}}

    embed_client = _FakeEmbedClient()
    embed_calls: list[list[str]] = []
    original_embed = embed_client.embed

    def tracking_embed(texts):
        embed_calls.append(texts)
        return original_embed(texts)

    embed_client.embed = tracking_embed

    with (
        patch("deepdoc.chatbot.service.build_embedding_client", return_value=embed_client),
        patch("deepdoc.chatbot.service.build_chat_client", return_value=_FakeChatClient()),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        service.query("Where is auth handled?")

    assert len(embed_calls) == 1
    assert len(embed_calls[0]) == 1  # only original query


def test_rerank_reorders_chunks_by_llm_score(tmp_path: Path) -> None:
    """Reranking should reorder chunks based on LLM relevance scores."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text("chatbot:\n  enabled: true\n", encoding="utf-8")

    plan = make_plan([make_bucket("Auth", "auth", ["src/auth.py"])])
    save_plan(plan, repo_root)

    index_dir = repo_root / ".deepdoc" / "chatbot"
    records = [
        ChunkRecord(chunk_id=f"c{i}", kind="code", source_key=f"src/f{i}.py",
                     text=f"def func{i}(): ...", chunk_hash=f"h{i}",
                     file_path=f"src/f{i}.py", start_line=1, end_line=5,
                     symbol_names=[f"func{i}"], related_bucket_slugs=["auth"])
        for i in range(3)
    ]
    save_corpus(index_dir, "code", records, [[1.0, 0.0]] * 3)
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])

    # Reranker returns descending scores so order reverses
    class _RerankingChatClient:
        def complete(self, system: str, user: str) -> str:
            if "alternative search queries" in system:
                return "func0 implementation"
            if "relevance scorer" in system.lower() or "Rate each chunk" in user:
                return "3\n9\n6"  # middle chunk scores highest
            return "Grounded answer"

    cfg = {"chatbot": {"enabled": True, "retrieval": {"rerank": True, "query_expansion": False}}}

    with (
        patch("deepdoc.chatbot.service.build_embedding_client", return_value=_FakeEmbedClient()),
        patch("deepdoc.chatbot.service.build_chat_client", return_value=_RerankingChatClient()),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.query("Which function?")

    # After reranking, c1 (score 9) should be first
    assert result["code_citations"][0]["file_path"] == "src/f1.py"


def test_system_prompt_contains_project_name(tmp_path: Path) -> None:
    """System prompt should include the project name."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text("chatbot:\n  enabled: true\n", encoding="utf-8")

    plan = make_plan([make_bucket("Auth", "auth", ["src/auth.py"])])
    save_plan(plan, repo_root)

    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(index_dir, "code", [], [])
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])

    cfg = {"project_name": "MyProject", "chatbot": {"enabled": True}}

    with (
        patch("deepdoc.chatbot.service.build_embedding_client", return_value=_FakeEmbedClient()),
        patch("deepdoc.chatbot.service.build_chat_client", return_value=_FakeChatClient()),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        prompt = service._system_prompt()

    assert "MyProject" in prompt
    assert "file path and line range" in prompt
    assert "Sources" in prompt
    assert "## Summary" in prompt


def test_query_service_passes_loaded_indexes_into_similarity_search(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text("chatbot:\n  enabled: true\n", encoding="utf-8")

    plan = make_plan([make_bucket("Auth", "auth", ["src/auth.py"])])
    save_plan(plan, repo_root)

    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(
        index_dir,
        "code",
        [
            ChunkRecord(
                chunk_id="c1",
                kind="code",
                source_key="src/auth.py",
                text="def login(user): ...",
                chunk_hash="h1",
                file_path="src/auth.py",
                start_line=1,
                end_line=5,
                symbol_names=["login"],
                related_bucket_slugs=["auth"],
            )
        ],
        [[1.0, 0.0]],
    )
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])

    loaded_indexes = {
        "code": object(),
        "artifact": object(),
        "doc_summary": object(),
        "relationship": object(),
    }
    seen_indexes: list[object | None] = []

    def fake_load_vector_index(index_dir, corpus):
        del index_dir
        return loaded_indexes[corpus]

    def fake_similarity_search(records, vectors, query_vector, top_k, *, vector_index=None):
        del vectors, query_vector, top_k
        seen_indexes.append(vector_index)
        return [RetrievedChunk(record=records[0], score=1.0)] if records else []

    cfg = {
        "chatbot": {
            "enabled": True,
            "retrieval": {"query_expansion": False, "rerank": False},
        }
    }

    monkeypatch.setattr("deepdoc.chatbot.service.load_vector_index", fake_load_vector_index)
    monkeypatch.setattr("deepdoc.chatbot.service.similarity_search", fake_similarity_search)

    with (
        patch("deepdoc.chatbot.service.build_embedding_client", return_value=_FakeEmbedClient()),
        patch("deepdoc.chatbot.service.build_chat_client", return_value=_FakeChatClient()),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.query("Where is auth handled?")

    assert result["answer"] == "Grounded answer"
    # code corpus has records, so its index is used; others have no records so
    # similarity_search is short-circuited. Relationship corpus is also empty.
    assert loaded_indexes["code"] in seen_indexes
