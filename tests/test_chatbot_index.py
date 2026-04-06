from __future__ import annotations

from pathlib import Path

from deepdoc.chatbot.chunker import build_artifact_chunks, build_code_chunks
from deepdoc.chatbot.docs_summary import (
    build_doc_full_chunks,
    build_doc_summary_chunks,
    build_repo_doc_chunks,
)
from deepdoc.chatbot.indexer import CHATBOT_CORPUS_SCHEMA_VERSION, ChatbotIndexer
from deepdoc.chatbot.persistence import load_corpus, save_corpus
from deepdoc.chatbot.types import ChunkRecord
from deepdoc.parser.base import ParsedFile, Symbol
from deepdoc.planner import RepoScan
from deepdoc.scanner import GiantFileAnalysis, SymbolCluster
from tests.conftest import make_bucket, make_plan


def _scan_for(tmp_path: Path) -> RepoScan:
    return RepoScan(
        file_tree={},
        file_summaries={},
        api_endpoints=[],
        languages={"python": 1},
        has_openapi=False,
        openapi_paths=[],
        total_files=1,
        frameworks_detected=[],
        entry_points=[],
        config_files=["package.json"],
        file_line_counts={"src/auth.py": 4},
        parsed_files={
            "src/auth.py": ParsedFile(
                path=Path("src/auth.py"),
                language="python",
                symbols=[
                    Symbol(
                        name="login",
                        kind="function",
                        signature="def login(user):",
                        start_line=1,
                        end_line=4,
                    )
                ],
                imports=["from db import users"],
                raw_content="def login(user):\n    token = issue(user)\n    return token\n",
            )
        },
        file_contents={
            "src/auth.py": "def login(user):\n    token = issue(user)\n    return token\n",
        },
    )


def test_code_chunks_use_symbol_line_ranges(tmp_path: Path) -> None:
    scan = _scan_for(tmp_path)
    plan = make_plan([make_bucket("Auth", "auth", ["src/auth.py"])])

    chunks = build_code_chunks(scan, plan, {"chatbot": {"enabled": True}})

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.kind == "code"
    assert chunk.file_path == "src/auth.py"
    assert chunk.start_line == 1
    assert chunk.end_line == 4
    assert chunk.symbol_names == ["login"]
    assert chunk.related_doc_urls == ["/auth"]
    assert chunk.related_doc_paths == ["auth.mdx"]
    assert "def login(user):" in chunk.text


def test_code_chunks_fallback_to_single_line_when_symbol_end_missing(
    tmp_path: Path,
) -> None:
    scan = RepoScan(
        file_tree={},
        file_summaries={},
        api_endpoints=[],
        languages={"python": 1},
        has_openapi=False,
        openapi_paths=[],
        total_files=1,
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
        file_line_counts={"src/auth.py": 4},
        parsed_files={
            "src/auth.py": ParsedFile(
                path=Path("src/auth.py"),
                language="python",
                symbols=[
                    Symbol(
                        name="login",
                        kind="function",
                        signature="def login(user):",
                        start_line=1,
                        end_line=0,
                    )
                ],
                imports=[],
            )
        },
        file_contents={
            "src/auth.py": "def login(user):\n    token = issue(user)\n    return token\n",
        },
    )
    plan = make_plan([make_bucket("Auth", "auth", ["src/auth.py"])])

    chunks = build_code_chunks(scan, plan, {"chatbot": {"enabled": True}})

    assert len(chunks) == 1
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 1


def test_giant_file_chunks_normalize_missing_cluster_end_lines(tmp_path: Path) -> None:
    scan = RepoScan(
        file_tree={},
        file_summaries={},
        api_endpoints=[],
        languages={"python": 1},
        has_openapi=False,
        openapi_paths=[],
        total_files=1,
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
        file_line_counts={"src/giant.py": 3000},
        parsed_files={
            "src/giant.py": ParsedFile(
                path=Path("src/giant.py"),
                language="python",
                symbols=[
                    Symbol(
                        name="LOGIN_HANDLER",
                        kind="constant",
                        signature="LOGIN_HANDLER = build_handler()",
                        start_line=120,
                        end_line=0,
                    )
                ],
                imports=[],
            )
        },
        file_contents={
            "src/giant.py": "\n" * 119
            + "LOGIN_HANDLER = build_handler()\n"
            + "\n" * 20,
        },
        giant_file_clusters={
            "src/giant.py": GiantFileAnalysis(
                file_path="src/giant.py",
                line_count=3000,
                total_symbols=1,
                clusters=[
                    SymbolCluster(
                        cluster_name="handlers",
                        description="Handler constants",
                        symbols=["LOGIN_HANDLER"],
                        line_ranges=[(120, 0)],
                    )
                ],
            )
        },
    )
    plan = make_plan([make_bucket("Auth", "auth", ["src/giant.py"])])

    chunks = build_code_chunks(scan, plan, {"chatbot": {"enabled": True}})

    assert len(chunks) == 1
    assert chunks[0].start_line == 120
    assert chunks[0].end_line == 120
    assert chunks[0].symbol_names == ["LOGIN_HANDLER"]


def test_artifact_chunks_cover_config_files(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "package.json").write_text(
        '{"name":"demo","scripts":{"dev":"next dev"}}', encoding="utf-8"
    )
    scan = _scan_for(tmp_path)
    plan = make_plan(
        [make_bucket("Setup", "setup", ["src/auth.py"], artifact_refs=["package.json"])]
    )

    chunks = build_artifact_chunks(
        repo_root,
        scan,
        plan,
        repo_root / "docs",
        {"chatbot": {"enabled": True}},
        files=["package.json"],
    )

    assert len(chunks) == 1
    assert chunks[0].kind == "artifact"
    assert chunks[0].artifact_type == "json"
    assert chunks[0].related_doc_urls == ["/setup"]
    assert "src/auth.py" in chunks[0].linked_file_paths
    assert "scripts" in chunks[0].text


def test_doc_summary_chunks_are_deterministic(tmp_path: Path) -> None:
    output_dir = tmp_path / "docs"
    output_dir.mkdir()
    (output_dir / "index.mdx").write_text(
        "---\ntitle: Demo\n---\n\n# Demo\n\nWelcome aboard.\n\n## Architecture\n\nAuth flows through middleware.\n",
        encoding="utf-8",
    )
    overview = make_bucket(
        "Overview",
        "overview",
        ["README.md"],
        generation_hints={"is_introduction_page": True},
    )
    plan = make_plan([overview])

    chunks = build_doc_summary_chunks(output_dir, plan, {"chatbot": {"enabled": True}})

    assert len(chunks) >= 1
    assert chunks[0].kind == "doc_summary"
    assert chunks[0].doc_url == "/"
    assert chunks[0].related_doc_urls == ["/"]
    assert chunks[0].linked_file_paths == ["README.md"]
    assert any("Architecture" in chunk.text for chunk in chunks)


def test_doc_full_chunks_preserve_section_content(tmp_path: Path) -> None:
    output_dir = tmp_path / "docs"
    output_dir.mkdir()
    (output_dir / "auth.mdx").write_text(
        (
            "---\ntitle: Auth\n---\n\n# Auth\n\nIntro.\n\n"
            "## Login Flow\n\nThe login flow validates credentials.\n\n"
            "```python\n"
            "def login(user):\n"
            "    return issue(user)\n"
            "```\n\n"
            "## Session Handling\n\nSessions are persisted in Redis.\n"
        ),
        encoding="utf-8",
    )
    auth = make_bucket("Auth", "auth", ["src/auth.py"])
    plan = make_plan([auth])

    chunks = build_doc_full_chunks(output_dir, plan, {"chatbot": {"enabled": True}})

    assert len(chunks) >= 2
    assert all(chunk.kind == "doc_full" for chunk in chunks)
    assert any(chunk.section_name == "Login Flow" for chunk in chunks)
    assert all(chunk.related_doc_urls == ["/auth"] for chunk in chunks)
    assert all("src/auth.py" in chunk.linked_file_paths for chunk in chunks)
    assert any("def login(user):" in chunk.text for chunk in chunks)


def test_repo_doc_chunks_index_repo_authored_docs_without_generated_output(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    output_dir = repo_root / "docs"
    output_dir.mkdir()
    (repo_root / "README.md").write_text(
        "# Demo\n\n## Architecture\n\nAuth flows through middleware.\n",
        encoding="utf-8",
    )
    (output_dir / "index.mdx").write_text(
        "# Generated Docs\n\nThis should stay in the generated-doc corpus only.\n",
        encoding="utf-8",
    )
    overview = make_bucket(
        "Overview",
        "overview",
        ["README.md"],
        generation_hints={"is_introduction_page": True},
    )
    plan = make_plan([overview])
    scan = _scan_for(tmp_path)
    scan.doc_contexts = {
        "README.md": "Headings: Demo, Architecture | Summary: Auth flows through middleware.",
        "docs/index.mdx": "Generated docs summary",
    }

    chunks = build_repo_doc_chunks(
        repo_root,
        scan,
        plan,
        {"chatbot": {"enabled": True}},
        output_dir=output_dir,
    )

    assert len(chunks) >= 1
    assert all(chunk.kind == "repo_doc" for chunk in chunks)
    assert all(chunk.file_path == "README.md" for chunk in chunks)
    assert all(chunk.doc_path == "README.md" for chunk in chunks)
    assert all(chunk.doc_url == "" for chunk in chunks)
    assert all(chunk.related_doc_urls == ["/"] for chunk in chunks)
    assert any("Architecture" in chunk.text for chunk in chunks)


def test_incremental_sync_recovers_missing_doc_corpus(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    output_dir = repo_root / "docs"
    output_dir.mkdir()
    (repo_root / "README.md").write_text(
        "# Demo\n\n## Architecture\n\nAuth flows through middleware.\n",
        encoding="utf-8",
    )
    (output_dir / "index.mdx").write_text(
        "# Demo\n\nWelcome aboard.\n\n## Architecture\n\nAuth flows through middleware.\n",
        encoding="utf-8",
    )

    overview = make_bucket(
        "Overview",
        "overview",
        ["README.md"],
        generation_hints={"is_introduction_page": True},
    )
    plan = make_plan([overview])
    scan = _scan_for(tmp_path)
    scan.doc_contexts = {
        "README.md": "Headings: Demo, Architecture | Summary: Auth flows through middleware.",
    }

    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(
        index_dir,
        "code",
        [
            ChunkRecord(
                chunk_id="c1",
                kind="code",
                source_key="src/auth.py",
                text="demo code",
                chunk_hash="hashc1",
                file_path="src/auth.py",
            )
        ],
        [[1.0]],
    )

    class _FakeEmbedClient:
        def embed(self, texts):
            return [[float(len(text))] for text in texts]

    monkeypatch.setattr(
        "deepdoc.chatbot.indexer.build_embedding_client", lambda cfg: _FakeEmbedClient()
    )

    indexer = ChatbotIndexer(repo_root, {"chatbot": {"enabled": True}})
    stats = indexer.sync_incremental(plan=plan, scan=scan, output_dir=output_dir)

    assert stats["doc_chunks"] >= 1
    assert stats["doc_full_chunks"] >= 1
    assert stats["repo_doc_chunks"] >= 1
    doc_records, doc_vectors = load_corpus(index_dir, "doc_summary")
    assert len(doc_records) == stats["doc_chunks"]
    assert len(doc_vectors) == len(doc_records)
    doc_full_records, doc_full_vectors = load_corpus(index_dir, "doc_full")
    assert len(doc_full_records) == stats["doc_full_chunks"]
    assert len(doc_full_vectors) == len(doc_full_records)
    repo_doc_records, repo_doc_vectors = load_corpus(index_dir, "repo_doc")
    assert len(repo_doc_records) == stats["repo_doc_chunks"]
    assert len(repo_doc_vectors) == len(repo_doc_records)


def test_incremental_sync_removes_deleted_generated_doc_chunks(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    output_dir = repo_root / "docs"
    output_dir.mkdir()

    plan = make_plan([make_bucket("Overview", "overview", ["README.md"])])
    scan = _scan_for(tmp_path)
    index_dir = repo_root / ".deepdoc" / "chatbot"
    doc_record = ChunkRecord(
        chunk_id="doc-old",
        kind="doc_summary",
        source_key="old-page.mdx",
        text="# Old Page",
        chunk_hash="oldhash",
        doc_path="old-page.mdx",
        doc_url="/old-page",
    )
    doc_full_record = ChunkRecord(
        chunk_id="doc-full-old",
        kind="doc_full",
        source_key="old-page.mdx",
        text="# Old Page\n\nMore details",
        chunk_hash="oldfullhash",
        doc_path="old-page.mdx",
        doc_url="/old-page",
    )
    save_corpus(index_dir, "doc_summary", [doc_record], [[1.0]])
    save_corpus(index_dir, "doc_full", [doc_full_record], [[1.0]])
    save_corpus(index_dir, "code", [], [])
    save_corpus(index_dir, "artifact", [], [])
    save_corpus(index_dir, "repo_doc", [], [])
    save_corpus(index_dir, "relationship", [], [])

    class _FakeEmbedClient:
        def embed(self, texts):
            return [[float(len(text))] for text in texts]

    monkeypatch.setattr(
        "deepdoc.chatbot.indexer.build_embedding_client", lambda cfg: _FakeEmbedClient()
    )

    indexer = ChatbotIndexer(repo_root, {"chatbot": {"enabled": True}})
    stats = indexer.sync_incremental(
        plan=plan,
        scan=scan,
        output_dir=output_dir,
        deleted_files=["old-page.mdx"],
    )

    doc_records, _ = load_corpus(index_dir, "doc_summary")
    doc_full_records, _ = load_corpus(index_dir, "doc_full")
    assert doc_records == []
    assert doc_full_records == []
    assert "doc_summary" in stats["corpora_refreshed"]
    assert "doc_full" in stats["corpora_refreshed"]


def test_corpus_needs_rebuild_when_embedding_identity_changes(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(
        index_dir,
        "code",
        [
            ChunkRecord(
                chunk_id="c1",
                kind="code",
                source_key="src/auth.py",
                text="demo code",
                chunk_hash="hashc1",
                file_path="src/auth.py",
            )
        ],
        [[1.0]],
        meta={"embedding_model": "litellm|azure|old-model||"},
    )

    class _FakeEmbedClient:
        def embed(self, texts):
            return [[1.0] for _ in texts]

    monkeypatch.setattr(
        "deepdoc.chatbot.indexer.build_embedding_client", lambda cfg: _FakeEmbedClient()
    )

    indexer = ChatbotIndexer(
        repo_root,
        {
            "chatbot": {
                "enabled": True,
                "embeddings": {
                    "backend": "fastembed",
                    "fastembed_model": "nomic-ai/nomic-embed-text-v1.5",
                },
            }
        },
    )

    assert indexer._corpus_needs_rebuild("code") is True


def test_corpus_needs_rebuild_when_schema_version_missing(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(
        index_dir,
        "code",
        [
            ChunkRecord(
                chunk_id="c1",
                kind="code",
                source_key="src/auth.py",
                text="demo code",
                chunk_hash="hashc1",
                file_path="src/auth.py",
            )
        ],
        [[1.0]],
        meta={"embedding_model": "fastembed|azure|nomic-ai/nomic-embed-text-v1.5||"},
    )

    class _FakeEmbedClient:
        def embed(self, texts):
            return [[1.0] for _ in texts]

    monkeypatch.setattr(
        "deepdoc.chatbot.indexer.build_embedding_client", lambda cfg: _FakeEmbedClient()
    )
    indexer = ChatbotIndexer(
        repo_root,
        {
            "chatbot": {
                "enabled": True,
                "embeddings": {
                    "backend": "fastembed",
                    "fastembed_model": "nomic-ai/nomic-embed-text-v1.5",
                },
            }
        },
    )

    assert indexer._corpus_needs_rebuild("code") is True


def test_corpus_does_not_rebuild_when_schema_version_matches(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(
        index_dir,
        "code",
        [
            ChunkRecord(
                chunk_id="c1",
                kind="code",
                source_key="src/auth.py",
                text="demo code",
                chunk_hash="hashc1",
                file_path="src/auth.py",
            )
        ],
        [[1.0]],
        meta={
            "embedding_model": "fastembed|azure|nomic-ai/nomic-embed-text-v1.5||",
            "schema_version": CHATBOT_CORPUS_SCHEMA_VERSION,
        },
    )

    class _FakeEmbedClient:
        def embed(self, texts):
            return [[1.0] for _ in texts]

    monkeypatch.setattr(
        "deepdoc.chatbot.indexer.build_embedding_client", lambda cfg: _FakeEmbedClient()
    )
    indexer = ChatbotIndexer(
        repo_root,
        {
            "chatbot": {
                "enabled": True,
                "embeddings": {
                    "backend": "fastembed",
                    "fastembed_model": "nomic-ai/nomic-embed-text-v1.5",
                },
            }
        },
    )

    assert indexer._corpus_needs_rebuild("code") is False


def test_relationship_merge_replaces_existing_call_graph_chunks(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    index_dir = repo_root / ".deepdoc" / "chatbot"
    existing_records = [
        ChunkRecord(
            chunk_id="cg_old",
            kind="relationship",
            source_key="src/controller.py",
            text="old call graph",
            chunk_hash="old",
            file_path="src/controller.py",
            metadata={"chunk_subtype": "call_graph"},
        ),
        ChunkRecord(
            chunk_id="rel_old",
            kind="relationship",
            source_key="src/controller.py",
            text="import graph",
            chunk_hash="rel",
            file_path="src/controller.py",
            metadata={"chunk_subtype": "import_graph"},
        ),
    ]
    save_corpus(
        index_dir,
        "relationship",
        existing_records,
        [[1.0], [0.5]],
        meta={"embedding_model": "litellm|azure|text-embedding-3-small||"},
    )

    class _FakeEmbedClient:
        def embed(self, texts):
            return [[float(idx + 1)] for idx, _ in enumerate(texts)]

    monkeypatch.setattr(
        "deepdoc.chatbot.indexer.build_embedding_client", lambda cfg: _FakeEmbedClient()
    )
    indexer = ChatbotIndexer(repo_root, {"chatbot": {"enabled": True}})
    fresh_records = [
        ChunkRecord(
            chunk_id="cg_new",
            kind="relationship",
            source_key="src/controller.py",
            text="new call graph",
            chunk_hash="new",
            file_path="src/controller.py",
            metadata={"chunk_subtype": "call_graph"},
        )
    ]

    indexer._merge_records(
        "relationship",
        fresh_records,
        changed_keys=[],
        deleted_keys=[],
    )

    merged_records, _ = load_corpus(index_dir, "relationship")
    call_graph_records = [
        record
        for record in merged_records
        if (record.metadata or {}).get("chunk_subtype") == "call_graph"
    ]
    assert [record.chunk_id for record in call_graph_records] == ["cg_new"]
    assert any(record.chunk_id == "rel_old" for record in merged_records)
