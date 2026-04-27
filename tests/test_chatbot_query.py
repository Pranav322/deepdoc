from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil
from unittest.mock import patch

import pytest

from deepdoc.chatbot.indexer import ChatbotIndexer
from deepdoc.chatbot.persistence import save_corpus, save_source_archive
from deepdoc.chatbot.service import ChatbotQueryService, create_fastapi_app
from deepdoc.chatbot.types import ChunkRecord, RetrievedChunk
from deepdoc.config import DEFAULT_CONFIG
from deepdoc.persistence_v2 import save_plan
from deepdoc.planner import scan_repo
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
            lines = [
                line
                for line in user.splitlines()
                if line.strip() and line.strip()[0].isdigit()
            ]
            return "\n".join("8" for _ in lines) if lines else "8"
        return "Grounded answer"


class _FailingEmbedClient:
    def embed(self, texts):
        raise RuntimeError("Embedding request failed: missing API key")


class _UnexpectedChatClient:
    def complete(self, system: str, user: str) -> str:
        raise AssertionError(
            "chat model should not be called without retrieved context"
        )


class _RecordingChatClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return "Grounded answer"


class _FastModeNoLlmRetrievalChatClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if "alternative search queries" in system:
            raise AssertionError("fast mode should not run query expansion")
        if "relevance scorer" in system.lower() or "Rate each chunk" in user:
            raise AssertionError("fast mode should not run reranking")
        return "Grounded answer"


class _ContinuationAnswerChatClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if len(self.calls) == 1:
            return (
                "## Overview\n"
                "Reshipping creates a follow-up order that references the original order.\n\n"
                "## Implementation details\n"
                "- `create_reshipping_order` validates the source order.\n"
                "- It copies customer and shipping details into a new order draft.\n"
                "- It writes a `ReshippingOrderLog` entry for traceability.\n\n"
                "## Dependencies & Connections\n"
                "- Imports: models are loaded from `models/Order.py`.\n"
                "- API Integration: `/api/v2/reshipping-order-creation` triggers creation.\n"
                "- Data Flow: original order -> new reship order -> log record.\n"
                "- Relationships:"
            )
        return (
            "- `ReshippingOrderLog` links the original order id and new order id.\n\n"
            "## Sources\n"
            "- `models/Order.py:1-120`\n"
            "- `api/orders.py:55-110`\n\n"
            "## Summary\n"
            "Reshipping is implemented as a new order creation flow with explicit linkage to the original order."
        )


def test_query_service_returns_code_and_artifact_citations(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )

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
                related_doc_paths=["auth.mdx"],
                related_doc_urls=["/auth"],
                related_doc_titles=["Auth"],
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
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client", return_value=_FakeChatClient()
        ),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.query("Where is auth handled?")

    assert result["answer"] == "Grounded answer"
    assert result["code_citations"][0]["file_path"] == "src/auth.py"
    assert result["artifact_citations"][0]["file_path"] == "package.json"
    assert result["doc_links"][0]["url"] == "/auth"


def test_query_service_abstains_out_of_scope_without_llm_or_citations(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )
    save_plan(make_plan([make_bucket("Auth", "auth", ["src/auth.py"])]), repo_root)
    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(
        index_dir,
        "code",
        [
            ChunkRecord(
                chunk_id="c1",
                kind="code",
                source_key="src/auth.py",
                text="def login(user): return user",
                chunk_hash="hashc1",
                file_path="src/auth.py",
                start_line=1,
                end_line=1,
            )
        ],
        [[0.0, 1.0]],
    )
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client",
            return_value=_UnexpectedChatClient(),
        ),
    ):
        service = ChatbotQueryService(repo_root, {"chatbot": {"enabled": True}})
        result = service.query("how can i go to moon and come back")

    assert result["confidence"] == "out_of_scope_confidence"
    assert result["used_chunks"] == 0
    assert result["code_citations"] == []
    assert result["artifact_citations"] == []
    assert result["doc_citations"] == []


def test_query_service_filters_low_score_citations_but_keeps_high_score(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )
    save_plan(make_plan([make_bucket("Auth", "auth", ["src/auth.py"])]), repo_root)
    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(index_dir, "code", [], [])
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client",
            return_value=_FakeChatClient(),
        ),
    ):
        service = ChatbotQueryService(repo_root, {"chatbot": {"enabled": True}})

    low = RetrievedChunk(
        record=ChunkRecord(
            chunk_id="low",
            kind="code",
            source_key="src/low.py",
            text="low",
            chunk_hash="low",
            file_path="src/low.py",
            start_line=1,
            end_line=1,
        ),
        score=0.39,
    )
    high = RetrievedChunk(
        record=ChunkRecord(
            chunk_id="high",
            kind="code",
            source_key="src/high.py",
            text="high",
            chunk_hash="high",
            file_path="src/high.py",
            start_line=1,
            end_line=1,
        ),
        score=0.41,
    )
    service.retrieve_context = lambda *args, **kwargs: {
        "code_hits": [low, high],
        "artifact_hits": [],
        "doc_hits": [],
        "relationship_hits": [],
        "max_raw_semantic_score": 0.9,
    }
    service._select_prompt_hits = lambda *args, **kwargs: {
        "code_hits": [low, high],
        "artifact_hits": [],
        "doc_hits": [],
        "relationship_hits": [],
    }

    result = service.query("Where is auth handled?")

    assert [item["file_path"] for item in result["code_citations"]] == ["src/high.py"]


def test_normal_query_prompt_bans_fabricated_example_code(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )
    save_corpus(repo_root / ".deepdoc" / "chatbot", "code", [], [])
    save_corpus(repo_root / ".deepdoc" / "chatbot", "artifact", [], [])
    save_corpus(repo_root / ".deepdoc" / "chatbot", "doc_summary", [], [])

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client",
            return_value=_RecordingChatClient(),
        ),
    ):
        service = ChatbotQueryService(repo_root, {"chatbot": {"enabled": True}})

    prompt = service._system_prompt()

    assert "Never generate illustrative example code" in prompt
    assert "stubs, or pseudocode" in prompt


def test_query_service_uses_explicit_chunk_doc_links_without_bucket_slugs(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )

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
                chunk_hash="hashc1",
                file_path="src/auth.py",
                start_line=1,
                end_line=5,
                symbol_names=["login"],
                related_doc_paths=["custom-auth.mdx"],
                related_doc_urls=["/auth"],
                related_doc_titles=["Auth"],
            )
        ],
        [[1.0, 0.0]],
    )
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])

    cfg = {"chatbot": {"enabled": True, "retrieval": {"query_expansion": False}}}

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client", return_value=_FakeChatClient()
        ),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.query("Where is auth handled?")

    assert result["doc_links"] == [
        {"title": "Auth", "url": "/auth", "doc_path": "custom-auth.mdx"}
    ]


def test_fastapi_query_endpoint_accepts_json_body(tmp_path: Path) -> None:
    testclient = pytest.importorskip("fastapi.testclient")
    TestClient = testclient.TestClient

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )

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
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client", return_value=_FakeChatClient()
        ),
    ):
        app = create_fastapi_app(repo_root, cfg)
        client = TestClient(app)
        response = client.post("/query", json={"question": "Where is auth handled?"})

    assert response.status_code == 200
    assert "couldn't find any indexed code" in response.json()["answer"]
    assert response.json()["used_chunks"] == 0


def test_query_service_returns_no_context_response_when_retrieval_is_empty(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )

    plan = make_plan([make_bucket("Auth", "auth", ["src/auth.py"])])
    save_plan(plan, repo_root)

    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(index_dir, "code", [], [])
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])

    cfg = {"chatbot": {"enabled": True}}

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client",
            return_value=_UnexpectedChatClient(),
        ),
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
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )

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
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FailingEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client", return_value=_FakeChatClient()
        ),
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
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )

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

    cfg = {
        "chatbot": {
            "enabled": True,
            "retrieval": {"query_expansion": True, "iterative_retrieval": False},
        }
    }

    embed_client = _FakeEmbedClient()
    embed_calls: list[list[str]] = []
    original_embed = embed_client.embed

    def tracking_embed(texts):
        embed_calls.append(texts)
        return original_embed(texts)

    embed_client.embed = tracking_embed

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client", return_value=embed_client
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client", return_value=_FakeChatClient()
        ),
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
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )

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
        patch(
            "deepdoc.chatbot.service.build_embedding_client", return_value=embed_client
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client", return_value=_FakeChatClient()
        ),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        service.query("Where is auth handled?")

    assert len(embed_calls) == 1
    assert len(embed_calls[0]) == 1  # only original query


def test_fast_mode_skips_llm_retrieval_steps_and_uses_single_embedding_call(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )

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
                text="def login(user): return issue(user)",
                chunk_hash="h1",
                file_path="src/auth.py",
                start_line=1,
                end_line=1,
                symbol_names=["login"],
                related_bucket_slugs=["auth"],
            )
        ],
        [[1.0, 0.0]],
    )
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])

    class _TrackingEmbedClient:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def embed(self, texts):
            self.calls.append(list(texts))
            return [[1.0, 0.0] for _ in texts]

    embed_client = _TrackingEmbedClient()
    chat_client = _FastModeNoLlmRetrievalChatClient()
    cfg = {
        "chatbot": {
            "enabled": True,
            "retrieval": {
                "query_expansion": True,
                "rerank": True,
                "iterative_retrieval": True,
                "fast_mode_use_llm_retrieval_steps": False,
                "fast_mode_iterative_retrieval": False,
            },
        }
    }

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=embed_client,
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client",
            return_value=chat_client,
        ),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.query("Where is auth handled?", mode="fast")

    assert result["answer"] == "Grounded answer"
    assert result["response_mode"] == "fast"
    assert len(chat_client.calls) == 1
    assert len(embed_client.calls) == 1
    assert len(embed_client.calls[0]) == 1


def test_default_query_mode_keeps_query_expansion_and_rerank(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )

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
                text="def login(user): return issue(user)",
                chunk_hash="h1",
                file_path="src/auth.py",
                start_line=1,
                end_line=1,
                symbol_names=["login"],
                related_bucket_slugs=["auth"],
            )
        ],
        [[1.0, 0.0]],
    )
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])

    class _TrackingRetrievalStepChatClient:
        def __init__(self) -> None:
            self.saw_expansion = False
            self.saw_rerank = False

        def complete(self, system: str, user: str) -> str:
            if "alternative search queries" in system:
                self.saw_expansion = True
                return "auth login flow"
            if "relevance scorer" in system.lower() or "Rate each chunk" in user:
                self.saw_rerank = True
                lines = [
                    line
                    for line in user.splitlines()
                    if line.strip() and line.strip()[0].isdigit()
                ]
                return "\n".join("8" for _ in lines) if lines else "8"
            return "Grounded answer"

    chat_client = _TrackingRetrievalStepChatClient()
    cfg = {
        "chatbot": {
            "enabled": True,
            "retrieval": {
                "query_expansion": True,
                "rerank": True,
                "iterative_retrieval": False,
            },
        }
    }

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client",
            return_value=chat_client,
        ),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.query("Where is auth handled?")

    assert result["answer"] == "Grounded answer"
    assert result["response_mode"] == "default"
    assert chat_client.saw_expansion
    assert chat_client.saw_rerank


def test_query_continues_abrupt_answer_and_adds_missing_summary(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )

    plan = make_plan([make_bucket("Orders", "orders", ["src/orders.py"])])
    save_plan(plan, repo_root)

    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(
        index_dir,
        "code",
        [
            ChunkRecord(
                chunk_id="c1",
                kind="code",
                source_key="src/orders.py",
                text="def create_reshipping_order(payload): return payload",
                chunk_hash="h1",
                file_path="src/orders.py",
                start_line=1,
                end_line=1,
                symbol_names=["create_reshipping_order"],
            )
        ],
        [[1.0, 0.0]],
    )
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])

    chat_client = _ContinuationAnswerChatClient()
    cfg = {
        "chatbot": {
            "enabled": True,
            "retrieval": {
                "query_expansion": False,
                "rerank": False,
                "iterative_retrieval": False,
            },
        }
    }

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client",
            return_value=chat_client,
        ),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.query("Explain reshipping order flow", mode="fast")

    assert len(chat_client.calls) == 2
    assert "## Summary" in result["answer"]
    assert "ReshippingOrderLog" in result["answer"]


def test_fastapi_query_context_endpoint_returns_selected_citations(
    tmp_path: Path,
) -> None:
    testclient = pytest.importorskip("fastapi.testclient")
    TestClient = testclient.TestClient

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )

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
                text="def login(user): return issue(user)",
                chunk_hash="h1",
                file_path="src/auth.py",
                start_line=1,
                end_line=1,
                symbol_names=["login"],
            )
        ],
        [[1.0, 0.0]],
    )
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client",
            return_value=_UnexpectedChatClient(),
        ),
    ):
        app = create_fastapi_app(repo_root, {"chatbot": {"enabled": True}})
        client = TestClient(app)
        response = client.post(
            "/query-context", json={"question": "Where is login handled?"}
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["response_mode"] == "fast"
    assert payload["selected_chunks"] > 0
    assert payload["code_citations"][0]["file_path"] == "src/auth.py"
    assert "answer" not in payload


def test_query_service_uses_lexical_retrieval_when_vector_search_misses(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )

    plan = make_plan([make_bucket("Payments", "payments", ["src/payments.py"])])
    save_plan(plan, repo_root)

    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(
        index_dir,
        "code",
        [
            ChunkRecord(
                chunk_id="c1",
                kind="code",
                source_key="src/payments.py",
                text=(
                    "File: src/payments.py\nLines: 1-3\n\n"
                    'PAYMENTS_HOST = os.getenv("PAYMENTS_HOST")\n'
                ),
                chunk_hash="hc1",
                file_path="src/payments.py",
                start_line=1,
                end_line=3,
                symbol_names=["PAYMENTS_HOST"],
                related_bucket_slugs=["payments"],
            )
        ],
        [[0.0, 0.0]],
    )
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])

    monkeypatch.setattr(
        "deepdoc.chatbot.service.similarity_search",
        lambda records, vectors, query_vector, top_k, *, vector_index=None: [],
    )

    cfg = {
        "chatbot": {
            "enabled": True,
            "retrieval": {
                "query_expansion": False,
                "iterative_retrieval": False,
                "rerank": False,
                "lexical_retrieval": True,
            },
        }
    }

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client", return_value=_FakeChatClient()
        ),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.query("Where is `PAYMENTS_HOST` configured?")

    assert result["answer"] == "Grounded answer"
    assert result["code_citations"][0]["file_path"] == "src/payments.py"


def test_deep_research_uses_live_repo_fallback_when_index_is_empty(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )
    (repo_root / "src").mkdir()
    (repo_root / "src" / "payments.py").write_text(
        'PAYMENTS_HOST = os.getenv("PAYMENTS_HOST")\n',
        encoding="utf-8",
    )
    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_source_archive(
        index_dir, {"src/payments.py": 'PAYMENTS_HOST = os.getenv("PAYMENTS_HOST")\n'}
    )

    class _DeepFallbackChatClient:
        def complete(self, system: str, user: str) -> str:
            if "alternative search queries" in system:
                return ""
            if "Break the given question into 2–4 focused sub-questions" in system:
                return '["Where is PAYMENTS_HOST used?"]'
            if "agent answering a specific sub-question" in system:
                assert "src/payments.py" in user
                return "PAYMENTS_HOST is used in `src/payments.py`."
            if "synthesising research findings" in system:
                assert "src/payments.py" in user
                return "Deep answer grounded in `src/payments.py`."
            return "Grounded answer"

    cfg = {
        "chatbot": {
            "enabled": True,
            "retrieval": {
                "query_expansion": False,
                "iterative_retrieval": False,
                "rerank": False,
                "deep_research_live_fallback": True,
            },
        }
    }

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client",
            return_value=_DeepFallbackChatClient(),
        ),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.deep_research("How does `PAYMENTS_HOST` work?", max_rounds=1)

    assert result["answer"] == "Deep answer grounded in `src/payments.py`."
    assert result["research_mode"] == "deep"
    assert "src/payments.py" in result["research_sources"]
    assert result["used_chunks"] > 0


def test_deep_research_handles_invalid_read_file_arguments(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )
    plan = make_plan([make_bucket("Payments", "payments", ["src/payments.py"])])
    save_plan(plan, repo_root)

    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(
        index_dir,
        "code",
        [
            ChunkRecord(
                chunk_id="c1",
                kind="code",
                source_key="src/payments.py",
                text='PAYMENTS_HOST = os.getenv("PAYMENTS_HOST")\n',
                chunk_hash="h1",
                file_path="src/payments.py",
                start_line=1,
                end_line=1,
            )
        ],
        [[1.0, 0.0]],
    )
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])
    save_corpus(index_dir, "doc_full", [], [])
    save_corpus(index_dir, "repo_doc", [], [])
    save_corpus(index_dir, "relationship", [], [])
    save_source_archive(
        index_dir,
        {"src/payments.py": 'PAYMENTS_HOST = os.getenv("PAYMENTS_HOST")\n'},
    )

    class _DeepResearchToolChatClient:
        def __init__(self) -> None:
            self.sub_question_calls = 0
            self.sub_question_prompts: list[str] = []

        def complete(self, system: str, user: str) -> str:
            if "alternative search queries" in system:
                return ""
            if "Break the given question into 2–4 focused sub-questions" in system:
                return '["Where is PAYMENTS_HOST used?"]'
            if "agent answering a specific sub-question" in system:
                self.sub_question_calls += 1
                self.sub_question_prompts.append(user)
                if self.sub_question_calls == 1:
                    return (
                        '{"action": "read_file", "path": "src/payments.py", '
                        '"start": "ten", "end": 20}'
                    )
                assert "Error: read_file 'start' and 'end' must be integers." in user
                return "PAYMENTS_HOST is used in `src/payments.py`."
            if "synthesising research findings" in system:
                return "Deep answer grounded in `src/payments.py`."
            return "Grounded answer"

    cfg = {
        "chatbot": {
            "enabled": True,
            "retrieval": {
                "query_expansion": False,
                "iterative_retrieval": False,
                "rerank": False,
            },
        }
    }
    chat_client = _DeepResearchToolChatClient()

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client",
            return_value=chat_client,
        ),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.deep_research("Explain PAYMENTS_HOST", max_rounds=1)

    assert result["answer"] == "Deep answer grounded in `src/payments.py`."
    assert "src/payments.py" in result["research_sources"]
    assert chat_client.sub_question_calls >= 2
    assert all("\\n\\n" not in prompt for prompt in chat_client.sub_question_prompts)


def test_deep_research_does_not_cite_missing_read_file_target(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )
    plan = make_plan([make_bucket("Schemas", "schemas", ["src/schema.py"])])
    save_plan(plan, repo_root)

    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(index_dir, "code", [], [])
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])
    save_corpus(index_dir, "doc_full", [], [])
    save_corpus(index_dir, "repo_doc", [], [])
    save_corpus(index_dir, "relationship", [], [])

    class _DeepResearchMissingFileChatClient:
        def __init__(self) -> None:
            self.sub_question_calls = 0

        def complete(self, system: str, user: str) -> str:
            if "alternative search queries" in system:
                return ""
            if "Break the given question into 2–4 focused sub-questions" in system:
                return '["List every schema"]'
            if "agent answering a specific sub-question" in system:
                self.sub_question_calls += 1
                if self.sub_question_calls == 1:
                    return (
                        '{"action": "read_file", "path": "src/missing_schema.py", '
                        '"start": 1, "end": 30}'
                    )
                return "No evidence found in retrieved context."
            if "synthesising research findings" in system:
                return "Could not find schema definitions from current evidence."
            return "Grounded answer"

    cfg = {
        "chatbot": {
            "enabled": True,
            "retrieval": {
                "query_expansion": False,
                "iterative_retrieval": False,
                "rerank": False,
            },
        }
    }

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client",
            return_value=_DeepResearchMissingFileChatClient(),
        ),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.deep_research("Tell me all schemas", max_rounds=1)

    assert (
        result["answer"] == "Could not find schema definitions from current evidence."
    )
    assert "src/missing_schema.py" not in result["research_sources"]


def test_deep_research_grep_adds_matched_files_to_sources(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )
    plan = make_plan([make_bucket("Payments", "payments", ["src/payments.py"])])
    save_plan(plan, repo_root)

    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(index_dir, "code", [], [])
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])
    save_corpus(index_dir, "doc_full", [], [])
    save_corpus(index_dir, "repo_doc", [], [])
    save_corpus(index_dir, "relationship", [], [])
    save_source_archive(
        index_dir,
        {"src/payments.py": 'PAYMENTS_HOST = os.getenv("PAYMENTS_HOST")\n'},
    )

    class _DeepResearchGrepSourcesChatClient:
        def __init__(self) -> None:
            self.sub_question_calls = 0

        def complete(self, system: str, user: str) -> str:
            if "alternative search queries" in system:
                return ""
            if "Break the given question into 2–4 focused sub-questions" in system:
                return '["Where is PAYMENTS_HOST defined?"]'
            if "agent answering a specific sub-question" in system:
                self.sub_question_calls += 1
                if self.sub_question_calls == 1:
                    return '{"action": "grep", "pattern": "PAYMENTS_HOST"}'
                assert "src/payments.py:1:" in user
                return "PAYMENTS_HOST is defined in `src/payments.py`."
            if "synthesising research findings" in system:
                return "Deep answer grounded in `src/payments.py`."
            return "Grounded answer"

    cfg = {
        "chatbot": {
            "enabled": True,
            "retrieval": {
                "query_expansion": False,
                "iterative_retrieval": False,
                "rerank": False,
                "deep_research_live_fallback": False,
            },
        }
    }

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client",
            return_value=_DeepResearchGrepSourcesChatClient(),
        ),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.deep_research("Where is PAYMENTS_HOST defined?", max_rounds=1)

    assert result["answer"] == "Deep answer grounded in `src/payments.py`."
    assert "src/payments.py" in result["research_sources"]


def test_query_service_stitches_adjacent_code_chunks_for_exact_match(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )

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
                text="File: src/auth.py\nLines: 1-20\n\ndef login(user):\n    token = issue(user)\n",
                chunk_hash="hc1",
                file_path="src/auth.py",
                start_line=1,
                end_line=20,
                symbol_names=["login"],
            ),
            ChunkRecord(
                chunk_id="c2",
                kind="code",
                source_key="src/auth.py",
                text="File: src/auth.py\nLines: 21-40\n\n    audit(token)\n    return token\n",
                chunk_hash="hc2",
                file_path="src/auth.py",
                start_line=21,
                end_line=40,
                symbol_names=["login"],
            ),
        ],
        [[1.0, 0.0], [0.9, 0.0]],
    )
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])
    save_corpus(index_dir, "doc_full", [], [])
    save_corpus(index_dir, "repo_doc", [], [])
    save_corpus(index_dir, "relationship", [], [])

    def _first_only(records, vectors, query_vector, top_k, *, vector_index=None):
        del vectors, query_vector, top_k, vector_index
        return [RetrievedChunk(record=records[0], score=1.0)] if records else []

    monkeypatch.setattr("deepdoc.chatbot.service.similarity_search", _first_only)

    cfg = {
        "chatbot": {
            "enabled": True,
            "retrieval": {
                "query_expansion": False,
                "iterative_retrieval": False,
                "rerank": False,
                "graph_neighbor_expansion": False,
                "stitch_adjacent_code_chunks": True,
                "stitch_max_adjacent_chunks": 1,
            },
        }
    }

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client", return_value=_FakeChatClient()
        ),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.query("Show the full `login` implementation")

    line_ranges = {
        (item["start_line"], item["end_line"]) for item in result["code_citations"]
    }
    assert (1, 20) in line_ranges
    assert (21, 40) in line_ranges


def test_query_service_returns_repo_doc_and_relationship_citations(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )
    plan = make_plan([make_bucket("Architecture", "architecture", ["README.md"])])
    save_plan(plan, repo_root)

    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(index_dir, "code", [], [])
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])
    save_corpus(index_dir, "doc_full", [], [])
    save_corpus(
        index_dir,
        "repo_doc",
        [
            ChunkRecord(
                chunk_id="rd1",
                kind="repo_doc",
                source_key="README.md",
                text="Repository Document: Architecture\n\nThe system uses an auth worker.",
                chunk_hash="rdhash",
                doc_path="README.md",
                title="Architecture",
                section_name="Overview",
                related_doc_urls=["/architecture"],
                related_doc_paths=["architecture.mdx"],
                related_doc_titles=["Architecture"],
            )
        ],
        [[1.0, 0.0]],
    )
    save_corpus(
        index_dir,
        "relationship",
        [
            ChunkRecord(
                chunk_id="rel1",
                kind="relationship",
                source_key="src/auth.py",
                text="Relationship graph: src/auth.py imports src/workers/auth_worker.py",
                chunk_hash="relhash",
                file_path="src/auth.py",
                linked_file_paths=["src/workers/auth_worker.py"],
                metadata={"chunk_subtype": "graph_neighbors"},
            )
        ],
        [[1.0, 0.0]],
    )

    cfg = {
        "chatbot": {
            "enabled": True,
            "retrieval": {
                "query_expansion": False,
                "iterative_retrieval": False,
                "rerank": False,
                "graph_neighbor_expansion": False,
            },
        }
    }

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client", return_value=_FakeChatClient()
        ),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.query("Explain the architecture of the auth worker")

    assert result["repo_doc_citations"][0]["doc_path"] == "README.md"
    assert result["relationship_citations"][0]["file_path"] == "src/auth.py"


def test_deep_research_uses_extended_chunk_evidence(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )
    plan = make_plan([make_bucket("Payments", "payments", ["src/payments.py"])])
    save_plan(plan, repo_root)

    long_text = "A" * 2200 + " IMPORTANT_MARKER_AFTER_2200 " + "B" * 200
    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(
        index_dir,
        "code",
        [
            ChunkRecord(
                chunk_id="c1",
                kind="code",
                source_key="src/payments.py",
                text=long_text,
                chunk_hash="longhash",
                file_path="src/payments.py",
                start_line=1,
                end_line=80,
            )
        ],
        [[1.0, 0.0]],
    )
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])
    save_corpus(index_dir, "doc_full", [], [])
    save_corpus(index_dir, "repo_doc", [], [])
    save_corpus(index_dir, "relationship", [], [])

    class _DeepResearchChatClient:
        def complete(self, system: str, user: str) -> str:
            if "alternative search queries" in system:
                return ""
            if "Break the given question into 2–4 focused sub-questions" in system:
                return '["How does the payment flow work?"]'
            if "agent answering a specific sub-question" in system:
                assert "IMPORTANT_MARKER_AFTER_2200" in user
                return "Step answer"
            if "synthesising research findings" in system:
                return "Final answer"
            return "Grounded answer"

    cfg = {
        "chatbot": {
            "enabled": True,
            "retrieval": {
                "query_expansion": False,
                "iterative_retrieval": False,
                "rerank": False,
                "graph_neighbor_expansion": False,
            },
        }
    }

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client",
            return_value=_DeepResearchChatClient(),
        ),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.deep_research("How does payments work?", max_rounds=1)

    assert result["answer"] == "Final answer"


def test_deep_research_schema_question_uses_original_question_retrieval(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )
    plan = make_plan([make_bucket("Database", "database", ["src/models.py"])])
    save_plan(plan, repo_root)

    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(
        index_dir,
        "code",
        [
            ChunkRecord(
                chunk_id="schema1",
                kind="code",
                source_key="src/models.py",
                text=(
                    "from django.db import models\n\n"
                    "class User(models.Model):\n"
                    "    email = models.EmailField(unique=True)\n"
                ),
                chunk_hash="schemahash1",
                file_path="src/models.py",
                start_line=1,
                end_line=4,
                symbol_names=["User"],
            )
        ],
        [[1.0, 0.0]],
    )
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])
    save_corpus(index_dir, "doc_full", [], [])
    save_corpus(index_dir, "repo_doc", [], [])
    save_corpus(index_dir, "relationship", [], [])

    class _SchemaDeepResearchChatClient:
        def complete(self, system: str, user: str) -> str:
            if "alternative search queries" in system:
                return ""
            if "Break the given question into 2–4 focused sub-questions" in system:
                return '["What schema files are used?"]'
            if "agent answering a specific sub-question" in system:
                assert "src/models.py" in user
                return "Schemas include `src/models.py` with a `User` model."
            if "synthesising research findings" in system:
                return "Schema is defined in `src/models.py`."
            return "Grounded answer"

    cfg = {
        "chatbot": {
            "enabled": True,
            "retrieval": {
                "query_expansion": False,
                "iterative_retrieval": False,
                "rerank": False,
            },
        }
    }

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client",
            return_value=_SchemaDeepResearchChatClient(),
        ),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.deep_research("tell me all the schemabeing used", max_rounds=1)

    assert result["answer"] == "Schema is defined in `src/models.py`."
    assert "src/models.py" in result["research_sources"]


def test_scan_index_query_end_to_end_on_falcon_fixture(tmp_path: Path) -> None:
    fixture_root = Path(__file__).parent / "fixtures" / "frameworks" / "falcon_app"
    repo_root = tmp_path / "falcon-app"
    shutil.copytree(fixture_root, repo_root)
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )
    output_dir = repo_root / "docs"
    output_dir.mkdir()

    cfg = deepcopy(DEFAULT_CONFIG)
    cfg["chatbot"]["enabled"] = True
    cfg["chatbot"]["retrieval"].update(
        {
            "query_expansion": False,
            "iterative_retrieval": False,
            "rerank": False,
            "graph_neighbor_expansion": False,
        }
    )
    scan = scan_repo(repo_root, cfg)
    plan = make_plan(
        [make_bucket("Falcon Auth", "falcon-auth", sorted(scan.file_summaries.keys()))]
    )
    save_plan(plan, repo_root)

    with (
        patch(
            "deepdoc.chatbot.indexer.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client", return_value=_FakeChatClient()
        ),
    ):
        ChatbotIndexer(repo_root, cfg).sync_full(
            plan=plan,
            scan=scan,
            output_dir=output_dir,
            has_openapi=False,
        )
        service = ChatbotQueryService(repo_root, cfg)
        result = service.query("Which falcon login route is handled here?")

    cited_files = {citation["file_path"] for citation in result["code_citations"]}
    assert "falcon" in scan.frameworks_detected
    assert "main.py" in cited_files or "controllers/auth.py" in cited_files


def test_rerank_reorders_chunks_by_llm_score(tmp_path: Path) -> None:
    """Reranking should reorder chunks based on LLM relevance scores."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )

    plan = make_plan([make_bucket("Auth", "auth", ["src/auth.py"])])
    save_plan(plan, repo_root)

    index_dir = repo_root / ".deepdoc" / "chatbot"
    records = [
        ChunkRecord(
            chunk_id=f"c{i}",
            kind="code",
            source_key=f"src/f{i}.py",
            text=f"def func{i}(): ...",
            chunk_hash=f"h{i}",
            file_path=f"src/f{i}.py",
            start_line=1,
            end_line=5,
            symbol_names=[f"func{i}"],
            related_bucket_slugs=["auth"],
        )
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

    cfg = {
        "chatbot": {
            "enabled": True,
            "retrieval": {"rerank": True, "query_expansion": False},
        }
    }

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client",
            return_value=_RerankingChatClient(),
        ),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        reranked_code, _, _, _ = service._rerank(
            "Which function?",
            [RetrievedChunk(record=record, score=1.0) for record in records],
            [],
            [],
            [],
            service.chat_cfg["retrieval"],
        )

    # After reranking, c1 (score 9) should be first
    assert reranked_code[0].record.file_path == "src/f1.py"


def test_rerank_balances_code_doc_and_relationship_candidates(tmp_path: Path) -> None:
    """Reranking should keep non-code evidence in play even when code dominates."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )

    plan = make_plan([make_bucket("Auth", "auth", ["src/auth.py", "auth.mdx"])])
    save_plan(plan, repo_root)

    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(index_dir, "code", [], [])
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])

    class _BalancedRerankChatClient:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        def complete(self, system: str, user: str) -> str:
            if "alternative search queries" in system:
                return ""
            if "relevance scorer" in system.lower() or "Rate each chunk" in user:
                self.prompts.append(user)
                return "4\n8\n9"
            return "Grounded answer"

    cfg = {
        "chatbot": {
            "enabled": True,
            "retrieval": {
                "rerank": True,
                "query_expansion": False,
                "rerank_candidate_limit": 3,
                "rerank_candidate_limit_per_kind": 1,
            },
        }
    }
    chat_client = _BalancedRerankChatClient()

    code_hits = [
        RetrievedChunk(
            record=ChunkRecord(
                chunk_id=f"c{i}",
                kind="code",
                source_key=f"src/file{i}.py",
                text=f"def code_{i}(): ...",
                chunk_hash=f"hc{i}",
                file_path=f"src/file{i}.py",
                start_line=1,
                end_line=5,
                symbol_names=[f"code_{i}"],
            ),
            score=1.0 - (i * 0.01),
        )
        for i in range(4)
    ]
    doc_hits = [
        RetrievedChunk(
            record=ChunkRecord(
                chunk_id="d1",
                kind="doc_full",
                source_key="auth.mdx",
                text="Auth architecture explains the login flow and its dependencies.",
                chunk_hash="hd1",
                doc_path="auth.mdx",
                doc_url="/auth",
                title="Auth",
            ),
            score=0.75,
        )
    ]
    relationship_hits = [
        RetrievedChunk(
            record=ChunkRecord(
                chunk_id="r1",
                kind="relationship",
                source_key="src/auth.py",
                text="# Call graph for `login`\n- `authenticate`\n- `audit_login`",
                chunk_hash="hr1",
                file_path="src/auth.py",
                metadata={"chunk_subtype": "call_graph"},
            ),
            score=0.72,
        )
    ]

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client",
            return_value=chat_client,
        ),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        reranked_code, _, reranked_doc, reranked_relationship = service._rerank(
            "Explain auth in detail",
            code_hits,
            [],
            doc_hits,
            relationship_hits,
            service.chat_cfg["retrieval"],
        )

    assert reranked_code
    assert reranked_doc[0].record.doc_path == "auth.mdx"
    assert reranked_relationship[0].record.file_path == "src/auth.py"
    assert chat_client.prompts
    rerank_prompt = chat_client.prompts[-1]
    assert "[doc_full]" in rerank_prompt
    assert "[relationship]" in rerank_prompt


def test_system_prompt_contains_project_name(tmp_path: Path) -> None:
    """System prompt should include the project name."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )

    plan = make_plan([make_bucket("Auth", "auth", ["src/auth.py"])])
    save_plan(plan, repo_root)

    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(index_dir, "code", [], [])
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])

    cfg = {"project_name": "MyProject", "chatbot": {"enabled": True}}

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client", return_value=_FakeChatClient()
        ),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        prompt = service._system_prompt()

    assert "MyProject" in prompt
    assert "file path and line range" in prompt
    assert "Sources" in prompt
    assert "## Summary" in prompt


def test_query_service_passes_loaded_indexes_into_similarity_search(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )

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
        "doc_full": object(),
        "repo_doc": object(),
        "relationship": object(),
    }
    seen_indexes: list[object | None] = []

    def fake_load_vector_index(index_dir, corpus):
        del index_dir
        return loaded_indexes[corpus]

    def fake_similarity_search(
        records, vectors, query_vector, top_k, *, vector_index=None
    ):
        del vectors, query_vector, top_k
        seen_indexes.append(vector_index)
        return [RetrievedChunk(record=records[0], score=1.0)] if records else []

    cfg = {
        "chatbot": {
            "enabled": True,
            "retrieval": {"query_expansion": False, "rerank": False},
        }
    }

    monkeypatch.setattr(
        "deepdoc.chatbot.service.load_vector_index", fake_load_vector_index
    )
    monkeypatch.setattr(
        "deepdoc.chatbot.service.similarity_search", fake_similarity_search
    )

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client", return_value=_FakeChatClient()
        ),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.query("Where is auth handled?")

    assert result["answer"] == "Grounded answer"
    # code corpus has records, so its index is used; others have no records so
    # similarity_search is short-circuited. Relationship corpus is also empty.
    assert loaded_indexes["code"] in seen_indexes


def test_query_service_uses_candidate_retrieval_limits(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )

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
    save_corpus(
        index_dir,
        "artifact",
        [
            ChunkRecord(
                chunk_id="a1",
                kind="artifact",
                source_key="settings.py",
                text="AUTH_MODE=oauth",
                chunk_hash="ha1",
                file_path="settings.py",
                artifact_type="env",
                start_line=1,
                end_line=1,
            )
        ],
        [[0.8, 0.2]],
    )
    save_corpus(
        index_dir,
        "doc_summary",
        [
            ChunkRecord(
                chunk_id="d1",
                kind="doc_summary",
                source_key="auth.mdx",
                text="Authentication docs summary",
                chunk_hash="hd1",
                doc_path="auth.mdx",
                doc_url="/auth",
                title="Auth",
            )
        ],
        [[0.7, 0.3]],
    )
    save_corpus(
        index_dir,
        "doc_full",
        [
            ChunkRecord(
                chunk_id="df1",
                kind="doc_full",
                source_key="auth.mdx",
                text="## Login Flow\nDetailed authentication docs body.",
                chunk_hash="hdf1",
                doc_path="auth.mdx",
                doc_url="/auth",
                title="Auth",
            )
        ],
        [[0.6, 0.4]],
    )
    save_corpus(
        index_dir,
        "relationship",
        [
            ChunkRecord(
                chunk_id="r1",
                kind="relationship",
                source_key="src/auth.py",
                text="# Imports for `src/auth.py`\n- oauth_client",
                chunk_hash="hr1",
                file_path="src/auth.py",
                metadata={"chunk_subtype": "imports"},
            )
        ],
        [[0.9, 0.1]],
    )

    seen_limits: dict[str, list[int]] = {}

    def fake_similarity_search(
        records, vectors, query_vector, top_k, *, vector_index=None
    ):
        del vectors, query_vector, vector_index
        if records:
            seen_limits.setdefault(records[0].kind, []).append(top_k)
            return [RetrievedChunk(record=records[0], score=1.0)]
        return []

    cfg = {
        "chatbot": {
            "enabled": True,
            "retrieval": {
                "query_expansion": False,
                "rerank": False,
                "iterative_retrieval": False,
                "top_k_code": 2,
                "top_k_artifact": 1,
                "top_k_docs": 1,
                "top_k_relationship": 1,
                "candidate_top_k_code": 9,
                "candidate_top_k_artifact": 7,
                "candidate_top_k_docs": 5,
                "candidate_top_k_relationship": 4,
            },
        }
    }

    monkeypatch.setattr(
        "deepdoc.chatbot.service.similarity_search", fake_similarity_search
    )

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client", return_value=_FakeChatClient()
        ),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.query("Where is auth handled?")

    assert result["answer"] == "Grounded answer"
    assert seen_limits["code"] == [9]
    assert seen_limits["artifact"] == [7]
    assert seen_limits["doc_summary"] == [5]
    assert seen_limits["doc_full"] == [5]
    assert seen_limits["relationship"] == [4]


def test_query_service_iterative_retrieval_adds_followup_code_context(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )

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
                chunk_hash="hc1",
                file_path="src/auth.py",
                start_line=1,
                end_line=1,
                symbol_names=["login"],
                related_bucket_slugs=["auth"],
            )
        ],
        [[1.0, 0.0]],
    )
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])
    save_corpus(
        index_dir,
        "doc_full",
        [
            ChunkRecord(
                chunk_id="df1",
                kind="doc_full",
                source_key="auth.mdx",
                text="## Auth Overview\nAuthentication is handled in src/auth.py.",
                chunk_hash="hdf1",
                doc_path="auth.mdx",
                doc_url="/auth",
                title="Auth",
                owned_files=["src/auth.py"],
            )
        ],
        [[0.0, 1.0]],
    )
    save_corpus(index_dir, "relationship", [], [])

    class _FollowupEmbedClient:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def embed(self, texts):
            self.calls.append(list(texts))
            vectors = []
            for text in texts:
                if "src/auth.py" in text:
                    vectors.append([1.0, 0.0])
                else:
                    vectors.append([0.0, 1.0])
            return vectors

    def fake_similarity_search(
        records, vectors, query_vector, top_k, *, vector_index=None
    ):
        del vectors, top_k, vector_index
        if not records:
            return []
        kind = records[0].kind
        if kind == "doc_full" and query_vector == [0.0, 1.0]:
            return [RetrievedChunk(record=records[0], score=0.95)]
        if kind == "code" and query_vector == [1.0, 0.0]:
            return [RetrievedChunk(record=records[0], score=0.9)]
        return []

    cfg = {
        "chatbot": {
            "enabled": True,
            "retrieval": {
                "query_expansion": False,
                "rerank": False,
                "iterative_retrieval": True,
                "iterative_max_followup_queries": 1,
            },
        }
    }
    embed_client = _FollowupEmbedClient()

    monkeypatch.setattr(
        "deepdoc.chatbot.service.similarity_search", fake_similarity_search
    )

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client", return_value=embed_client
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client", return_value=_FakeChatClient()
        ),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.query("Where is auth handled?")

    assert result["answer"] == "Grounded answer"
    assert result["code_citations"][0]["file_path"] == "src/auth.py"
    assert len(embed_client.calls) == 2
    assert any("src/auth.py" in text for text in embed_client.calls[1])


def test_query_service_graph_neighbor_expansion_pulls_linked_code_context(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )

    plan = make_plan(
        [make_bucket("Orders", "orders", ["src/routes.py", "src/service.py"])]
    )
    save_plan(plan, repo_root)

    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(
        index_dir,
        "code",
        [
            ChunkRecord(
                chunk_id="c1",
                kind="code",
                source_key="src/routes.py",
                text="def route_handler(): ...",
                chunk_hash="hc1",
                file_path="src/routes.py",
                start_line=1,
                end_line=1,
                symbol_names=["route_handler"],
            ),
            ChunkRecord(
                chunk_id="c2",
                kind="code",
                source_key="src/service.py",
                text="def create_order(): return persist_order()",
                chunk_hash="hc2",
                file_path="src/service.py",
                start_line=1,
                end_line=1,
                symbol_names=["create_order"],
            ),
        ],
        [[1.0, 0.0], [0.0, 1.0]],
    )
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])
    save_corpus(index_dir, "doc_full", [], [])
    save_corpus(
        index_dir,
        "relationship",
        [
            ChunkRecord(
                chunk_id="r1",
                kind="relationship",
                source_key="src/routes.py",
                text="File graph neighbors for `src/routes.py`\n\n## References\n- `create_order`",
                chunk_hash="hr1",
                file_path="src/routes.py",
                linked_file_paths=["src/service.py"],
                metadata={"chunk_subtype": "graph_neighbors"},
            )
        ],
        [[0.8, 0.2]],
    )

    def fake_similarity_search(
        records, vectors, query_vector, top_k, *, vector_index=None
    ):
        del vectors, query_vector, top_k, vector_index
        if records and records[0].kind == "relationship":
            return [RetrievedChunk(record=records[0], score=1.0)]
        return []

    cfg = {
        "chatbot": {
            "enabled": True,
            "retrieval": {
                "query_expansion": False,
                "rerank": False,
                "iterative_retrieval": False,
                "graph_neighbor_expansion": True,
            },
        }
    }

    monkeypatch.setattr(
        "deepdoc.chatbot.service.similarity_search", fake_similarity_search
    )

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client", return_value=_FakeChatClient()
        ),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.query("How does order creation work?")

    assert result["answer"] == "Grounded answer"
    assert any(
        citation["file_path"] == "src/service.py"
        for citation in result["code_citations"]
    )


def test_fastapi_deep_research_endpoint_uses_shared_history(tmp_path: Path) -> None:
    testclient = pytest.importorskip("fastapi.testclient")
    TestClient = testclient.TestClient

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )

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
                text="def login(user):\n    return authenticate(user)\n",
                chunk_hash="h1",
                file_path="src/auth.py",
                start_line=1,
                end_line=2,
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
                source_key="settings.py",
                text="AUTH_MODE=oauth\n",
                chunk_hash="ha1",
                file_path="settings.py",
                artifact_type="env",
                start_line=1,
                end_line=1,
            )
        ],
        [[0.8, 0.2]],
    )
    save_corpus(
        index_dir,
        "doc_summary",
        [
            ChunkRecord(
                chunk_id="d1",
                kind="doc_summary",
                source_key="auth.mdx",
                text="Authentication docs summary",
                chunk_hash="hd1",
                doc_path="auth.mdx",
                doc_url="/auth",
                title="Auth",
            )
        ],
        [[0.7, 0.3]],
    )
    save_corpus(
        index_dir,
        "relationship",
        [
            ChunkRecord(
                chunk_id="r1",
                kind="relationship",
                source_key="src/auth.py",
                text="# Call graph for `login` in `src/auth.py`\n\n## Local calls:\n- `authenticate` (in `src/auth.py`)",
                chunk_hash="hr1",
                file_path="src/auth.py",
                metadata={"chunk_subtype": "call_graph"},
            )
        ],
        [[0.9, 0.1]],
    )

    class _DeepResearchChatClient:
        def __init__(self) -> None:
            self.messages: list[tuple[str, str]] = []

        def complete(self, system: str, user: str) -> str:
            self.messages.append((system, user))
            if "alternative search queries" in system:
                return ""
            if "relevance scorer" in system.lower() or "Rate each chunk" in user:
                lines = [
                    line
                    for line in user.splitlines()
                    if line.strip() and line.strip()[0].isdigit()
                ]
                return "\n".join("8" for _ in lines) if lines else "8"
            if "Break the given question into 2–4 focused sub-questions" in system:
                return '["Where is auth handled?", "Which config affects auth?"]'
            if "agent answering a specific sub-question" in system:
                return "Auth is handled in `src/auth.py`."
            if "synthesising research findings" in system:
                return "Deep answer grounded in `src/auth.py` and `auth.mdx`."
            return "Grounded answer"

    cfg = {
        "chatbot": {
            "enabled": True,
            "retrieval": {"query_expansion": False, "rerank": False},
        }
    }
    chat_client = _DeepResearchChatClient()

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch("deepdoc.chatbot.service.build_chat_client", return_value=chat_client),
    ):
        app = create_fastapi_app(repo_root, cfg)
        client = TestClient(app)
        response = client.post(
            "/deep-research",
            json={
                "question": "How does auth work?",
                "history": [
                    {"role": "user", "content": "We were looking at login earlier."},
                    {
                        "role": "assistant",
                        "content": "The login flow starts in the auth module.",
                    },
                ],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "Deep answer grounded in `src/auth.py` and `auth.mdx`."
    assert payload["research_mode"] == "deep"
    assert payload["confidence"] in {"high", "medium", "low"}
    assert any(
        "We were looking at login earlier." in user for _, user in chat_client.messages
    )


class _CodeDeepChatClient:
    def complete(self, system: str, user: str) -> str:
        if "alternative search queries" in system:
            return "auth middleware\nauth flow"
        if "relevance scorer" in system.lower() or "Rate each chunk" in user:
            lines = [line for line in user.splitlines() if line.strip()[:1].isdigit()]
            return "\n".join("8" for _ in lines) if lines else "8"
        if "Break the given question into 2–4 focused sub-questions" in system:
            return '["Where is auth defined?", "Which middleware applies?"]'
        if "agent answering a specific sub-question" in system:
            return "Auth flows through `src/auth.py` and `src/auth_middleware.py`."
        if "synthesising research findings" in system:
            return "Final code-aware answer from `src/auth.py` and `src/auth_middleware.py`."
        return "Grounded answer"


def test_code_deep_returns_trace_and_file_inventory(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )
    plan = make_plan(
        [make_bucket("Auth", "auth", ["src/auth.py", "src/auth_middleware.py"])]
    )
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
                text="def authenticate(user):\n    return issue_token(user)\n",
                chunk_hash="hc1",
                file_path="src/auth.py",
                start_line=1,
                end_line=2,
                symbol_names=["authenticate"],
            ),
            ChunkRecord(
                chunk_id="c2",
                kind="code",
                source_key="src/auth_middleware.py",
                text="def auth_middleware(request):\n    return check_auth(request)\n",
                chunk_hash="hc2",
                file_path="src/auth_middleware.py",
                start_line=1,
                end_line=2,
                symbol_names=["auth_middleware"],
            ),
        ],
        [[1.0, 0.0], [0.95, 0.0]],
    )
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])
    save_source_archive(
        index_dir,
        {
            "src/auth.py": "def authenticate(user):\n    return issue_token(user)\n",
            "src/auth_middleware.py": "def auth_middleware(request):\n    return check_auth(request)\n",
        },
    )

    cfg = {
        "chatbot": {
            "enabled": True,
            "retrieval": {
                "query_expansion": False,
                "iterative_retrieval": False,
                "rerank": False,
            },
        }
    }

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client",
            return_value=_CodeDeepChatClient(),
        ),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.code_deep(
            "Where is auth defined and which middleware runs?",
            max_rounds=2,
        )

    assert result["research_mode"] == "code_deep"
    assert result["response_mode"] == "code_deep"
    phases = {entry["phase"] for entry in result["trace"]}
    assert {"start", "decompose", "step_start", "step_done", "done"}.issubset(phases)
    inventory_paths = {entry["file_path"] for entry in result["file_inventory"]}
    assert "src/auth.py" in inventory_paths
    assert "src/auth_middleware.py" in inventory_paths


def test_fastapi_code_deep_endpoint_returns_trace_and_inventory(tmp_path: Path) -> None:
    testclient = pytest.importorskip("fastapi.testclient")
    TestClient = testclient.TestClient

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )
    plan = make_plan(
        [make_bucket("Auth", "auth", ["src/auth.py", "src/auth_middleware.py"])]
    )
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
                text="def authenticate(user):\n    return issue_token(user)\n",
                chunk_hash="hc1",
                file_path="src/auth.py",
                start_line=1,
                end_line=2,
                symbol_names=["authenticate"],
            ),
            ChunkRecord(
                chunk_id="c2",
                kind="code",
                source_key="src/auth_middleware.py",
                text="def auth_middleware(request):\n    return check_auth(request)\n",
                chunk_hash="hc2",
                file_path="src/auth_middleware.py",
                start_line=1,
                end_line=2,
                symbol_names=["auth_middleware"],
            ),
        ],
        [[1.0, 0.0], [0.95, 0.0]],
    )
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])
    save_source_archive(
        index_dir,
        {
            "src/auth.py": "def authenticate(user):\n    return issue_token(user)\n",
            "src/auth_middleware.py": "def auth_middleware(request):\n    return check_auth(request)\n",
        },
    )

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client",
            return_value=_CodeDeepChatClient(),
        ),
    ):
        app = create_fastapi_app(repo_root, {"chatbot": {"enabled": True}})
        client = TestClient(app)
        response = client.post(
            "/code-deep",
            json={"question": "Where is auth defined?", "history": []},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["research_mode"] == "code_deep"
    assert payload["trace"]
    assert payload["file_inventory"]


def test_fastapi_code_deep_stream_emits_trace_result_and_done(tmp_path: Path) -> None:
    testclient = pytest.importorskip("fastapi.testclient")
    TestClient = testclient.TestClient

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text(
        "chatbot:\n  enabled: true\n", encoding="utf-8"
    )
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
                text="def authenticate(user):\n    return issue_token(user)\n",
                chunk_hash="hc1",
                file_path="src/auth.py",
                start_line=1,
                end_line=2,
                symbol_names=["authenticate"],
            )
        ],
        [[1.0, 0.0]],
    )
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])
    save_source_archive(
        index_dir,
        {"src/auth.py": "def authenticate(user):\n    return issue_token(user)\n"},
    )

    with (
        patch(
            "deepdoc.chatbot.service.build_embedding_client",
            return_value=_FakeEmbedClient(),
        ),
        patch(
            "deepdoc.chatbot.service.build_chat_client",
            return_value=_CodeDeepChatClient(),
        ),
    ):
        app = create_fastapi_app(repo_root, {"chatbot": {"enabled": True}})
        client = TestClient(app)
        with client.stream(
            "POST",
            "/code-deep/stream",
            json={"question": "Where is auth defined?", "history": []},
        ) as response:
            body = "".join(chunk for chunk in response.iter_text())

    assert response.status_code == 200
    assert "event: trace" in body
    assert "event: result" in body
    assert "event: done" in body
    assert '"research_mode": "code_deep"' in body
