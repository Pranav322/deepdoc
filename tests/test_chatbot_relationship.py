"""Tests for relationship chunk building and chain-retrieval."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from deepdoc.chatbot.chunker import build_relationship_chunks
from deepdoc.chatbot.persistence import save_corpus
from deepdoc.chatbot.service import ChatbotQueryService
from deepdoc.chatbot.types import ChunkRecord
from deepdoc.parser.base import ParsedFile, Symbol
from deepdoc.persistence_v2 import save_plan
from deepdoc.planner_v2 import RepoScan
from tests.conftest import make_bucket, make_plan


def _make_scan_with_parsed_files(
    parsed_files: dict[str, ParsedFile],
    file_contents: dict[str, str] | None = None,
) -> RepoScan:
    return RepoScan(
        file_tree={".": list(parsed_files.keys())},
        file_summaries={k: "" for k in parsed_files},
        api_endpoints=[],
        languages={"python": len(parsed_files)},
        has_openapi=False,
        openapi_paths=[],
        total_files=len(parsed_files),
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
        parsed_files=parsed_files,
        file_contents=file_contents or {k: "" for k in parsed_files},
        source_kind_by_file={k: "product" for k in parsed_files},
        file_frameworks={},
    )


def test_relationship_chunks_contain_import_graph() -> None:
    """Import graph chunks should list all imports for a file."""
    parsed = ParsedFile(
        path=Path("src/controller.py"),
        language="python",
        imports=[
            "from services.order_service import OrderService",
            "from serializers.order import OrderSerializer",
            "from django.http import JsonResponse",
        ],
        symbols=[],
    )
    scan = _make_scan_with_parsed_files({"src/controller.py": parsed})
    plan = make_plan([make_bucket("Orders", "orders", ["src/controller.py"])])

    chunks = build_relationship_chunks(scan, plan, {})

    import_chunks = [c for c in chunks if "import_graph" in c.text]
    assert len(import_chunks) == 1, f"Expected 1 import chunk, got {len(import_chunks)}"
    chunk = import_chunks[0]
    assert chunk.kind == "relationship"
    assert "OrderService" in chunk.text
    assert "OrderSerializer" in chunk.text
    assert "JsonResponse" in chunk.text
    assert chunk.file_path == "src/controller.py"
    assert len(chunk.imports_summary) == 3


def test_relationship_chunks_contain_symbol_index() -> None:
    """Symbol index chunks should list all symbols with signatures and line numbers."""
    parsed = ParsedFile(
        path=Path("src/controller.py"),
        language="python",
        imports=[],
        symbols=[
            Symbol(name="OrderController", kind="class", start_line=10, end_line=100, signature="class OrderController"),
            Symbol(name="on_get", kind="method", start_line=15, end_line=30, signature="def on_get(self, req, resp)"),
            Symbol(name="on_post", kind="method", start_line=32, end_line=60, signature="def on_post(self, req, resp)"),
            Symbol(name="_validate", kind="method", start_line=62, end_line=80, signature="def _validate(self, data)"),
        ],
    )
    scan = _make_scan_with_parsed_files({"src/controller.py": parsed})
    plan = make_plan([make_bucket("Orders", "orders", ["src/controller.py"])])

    chunks = build_relationship_chunks(scan, plan, {})

    symbol_chunks = [c for c in chunks if "symbol_index" in c.text]
    assert len(symbol_chunks) == 1
    chunk = symbol_chunks[0]
    assert chunk.kind == "relationship"
    assert "OrderController" in chunk.text
    assert "on_get" in chunk.text
    assert "on_post" in chunk.text
    assert "_validate" in chunk.text
    assert "lines 15-30" in chunk.text
    assert "4 symbols" in chunk.text
    assert len(chunk.symbol_names) == 4


def test_relationship_chunks_for_file_with_both_imports_and_symbols() -> None:
    """A file with both imports and symbols should produce 2 relationship chunks."""
    parsed = ParsedFile(
        path=Path("src/service.py"),
        language="python",
        imports=["from models import Order"],
        symbols=[Symbol(name="create_order", kind="function", start_line=5, end_line=20, signature="def create_order(data)")],
    )
    scan = _make_scan_with_parsed_files({"src/service.py": parsed})
    plan = make_plan([make_bucket("Orders", "orders", ["src/service.py"])])

    chunks = build_relationship_chunks(scan, plan, {})

    assert len(chunks) == 2
    kinds_in_text = {c.text.split("Type: ")[1].split("\n")[0] for c in chunks}
    assert kinds_in_text == {"import_graph", "symbol_index"}


def test_relationship_chunks_empty_for_unparsed_files() -> None:
    """Files without parsed data should produce no relationship chunks."""
    scan = _make_scan_with_parsed_files({})
    plan = make_plan([make_bucket("Empty", "empty", [])])

    chunks = build_relationship_chunks(scan, plan, {})
    assert chunks == []


def test_relationship_chunks_scoped_to_specific_files() -> None:
    """When files= is provided, only those files get relationship chunks."""
    parsed_a = ParsedFile(
        path=Path("src/a.py"), language="python",
        imports=["import os"], symbols=[],
    )
    parsed_b = ParsedFile(
        path=Path("src/b.py"), language="python",
        imports=["import sys"], symbols=[],
    )
    scan = _make_scan_with_parsed_files({"src/a.py": parsed_a, "src/b.py": parsed_b})
    plan = make_plan([make_bucket("AB", "ab", ["src/a.py", "src/b.py"])])

    chunks = build_relationship_chunks(scan, plan, {}, files=["src/a.py"])

    assert len(chunks) == 1
    assert chunks[0].file_path == "src/a.py"


class _FakeEmbedClient:
    def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


class _FakeChatClient:
    def complete(self, system: str, user: str) -> str:
        if "alternative search queries" in system:
            return "order controller\norder service"
        if "relevance scorer" in system.lower() or "Rate each chunk" in user:
            lines = [l for l in user.splitlines() if l.strip() and l.strip()[0].isdigit()]
            return "\n".join("8" for _ in lines) if lines else "8"
        return "Detailed grounded answer about OrderController"


def test_chain_retrieval_pulls_related_files(tmp_path: Path) -> None:
    """Chain-retrieval should pull code chunks from files mentioned in imports."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text("chatbot:\n  enabled: true\n", encoding="utf-8")

    plan = make_plan([
        make_bucket("Orders", "orders", ["src/controller.py", "src/service.py"]),
    ])
    save_plan(plan, repo_root)

    index_dir = repo_root / ".deepdoc" / "chatbot"

    # Code corpus: controller + service
    code_records = [
        ChunkRecord(
            chunk_id="ctrl1", kind="code", source_key="src/controller.py",
            text="class OrderController:\n    def on_get(self, req, resp): ...",
            chunk_hash="h1", file_path="src/controller.py",
            start_line=1, end_line=30, symbol_names=["OrderController", "on_get"],
            related_bucket_slugs=["orders"],
        ),
        ChunkRecord(
            chunk_id="svc1", kind="code", source_key="src/service.py",
            text="class OrderService:\n    def create_order(self, data): ...",
            chunk_hash="h2", file_path="src/service.py",
            start_line=1, end_line=20, symbol_names=["OrderService", "create_order"],
            related_bucket_slugs=["orders"],
        ),
    ]
    save_corpus(index_dir, "code", code_records, [[1.0, 0.0], [0.2, 0.8]])

    # Relationship corpus: controller imports service
    rel_records = [
        ChunkRecord(
            chunk_id="rel1", kind="relationship", source_key="src/controller.py",
            text="File: src/controller.py\nType: import_graph\n\ncontroller.py imports:\n  - from services.order_service import OrderService",
            chunk_hash="hr1", file_path="src/controller.py",
            imports_summary=["from services.order_service import OrderService"],
            related_bucket_slugs=["orders"],
            title="controller.py :: imports",
        ),
    ]
    save_corpus(index_dir, "relationship", rel_records, [[0.9, 0.1]])
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])

    cfg = {
        "chatbot": {
            "enabled": True,
            "retrieval": {"query_expansion": False, "rerank": False},
        }
    }

    with (
        patch("deepdoc.chatbot.service.build_embedding_client", return_value=_FakeEmbedClient()),
        patch("deepdoc.chatbot.service.build_chat_client", return_value=_FakeChatClient()),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        result = service.query("How does OrderController work?")

    assert result["answer"]
    assert result["used_chunks"] > 0


def test_relationship_prompt_section_included(tmp_path: Path) -> None:
    """The prompt sent to the LLM should include a 'File relationships' section."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".deepdoc.yaml").write_text("chatbot:\n  enabled: true\n", encoding="utf-8")

    plan = make_plan([make_bucket("Auth", "auth", ["src/auth.py"])])
    save_plan(plan, repo_root)

    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(
        index_dir, "code",
        [ChunkRecord(
            chunk_id="c1", kind="code", source_key="src/auth.py",
            text="def login(): ...", chunk_hash="h1",
            file_path="src/auth.py", start_line=1, end_line=5,
            symbol_names=["login"], related_bucket_slugs=["auth"],
        )],
        [[1.0, 0.0]],
    )
    save_corpus(
        index_dir, "relationship",
        [ChunkRecord(
            chunk_id="r1", kind="relationship", source_key="src/auth.py",
            text="File: src/auth.py\nType: symbol_index\n\nauth.py defines 1 symbol:\n  - function: login (lines 1-5)",
            chunk_hash="hr1", file_path="src/auth.py",
            symbol_names=["login"], related_bucket_slugs=["auth"],
            title="auth.py :: symbol index",
        )],
        [[1.0, 0.0]],
    )
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "doc_summary", [], [])

    prompts_seen: list[str] = []

    class _CapturingChatClient:
        def complete(self, system: str, user: str) -> str:
            if "alternative search queries" in system:
                return "auth login"
            if "relevance scorer" in system.lower() or "Rate each chunk" in user:
                return "8"
            prompts_seen.append(user)
            return "Answer"

    cfg = {"chatbot": {"enabled": True, "retrieval": {"query_expansion": False, "rerank": False}}}

    with (
        patch("deepdoc.chatbot.service.build_embedding_client", return_value=_FakeEmbedClient()),
        patch("deepdoc.chatbot.service.build_chat_client", return_value=_CapturingChatClient()),
    ):
        service = ChatbotQueryService(repo_root, cfg)
        service.query("How does login work?")

    assert len(prompts_seen) == 1
    assert "File relationships" in prompts_seen[0]
    assert "symbol_index" in prompts_seen[0]
