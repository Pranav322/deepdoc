from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil
from unittest.mock import patch

import pytest

from deepdoc.chatbot.indexer import ChatbotIndexer
from deepdoc.chatbot.persistence import save_corpus
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

    class _DeepFallbackChatClient:
        def complete(self, system: str, user: str) -> str:
            if "alternative search queries" in system:
                return ""
            if "Break the given question into 2–4 focused sub-questions" in system:
                return '["Where is PAYMENTS_HOST used?"]'
            if "answering questions about a software codebase" in system:
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
            if "answering questions about a software codebase" in system:
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
            if "answering questions about a software codebase" in system:
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
