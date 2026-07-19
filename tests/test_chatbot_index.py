from __future__ import annotations

from pathlib import Path

from deepdoc.chatbot.chunker import build_artifact_chunks, build_code_chunks
from deepdoc.chatbot.embedding_capabilities import (
    embedding_policy_fingerprint,
    resolve_embedding_capabilities,
)
from deepdoc.chatbot.docs_summary import (
    build_doc_full_chunks,
    build_doc_summary_chunks,
    build_repo_doc_chunks,
)
from deepdoc.chatbot.indexer import (
    CHATBOT_CORPUS_SCHEMA_VERSION,
    ChatbotIndexer,
    chatbot_index_needs_refresh,
)
from deepdoc.chatbot.persistence import (
    CORPUS_FILES,
    corpus_paths,
    load_corpus,
    load_index_manifest,
    query_lexical_index,
    save_corpus,
    save_index_manifest,
)
from deepdoc.chatbot.symbol_index import build_symbol_chunks
from deepdoc.chatbot.settings import service_model_identity
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


def _seed_healthy_corpora(indexer: ChatbotIndexer) -> None:
    meta = {
        "embedding_model": service_model_identity(indexer.chatbot_cfg["embeddings"]),
        "schema_version": CHATBOT_CORPUS_SCHEMA_VERSION,
        "embedding_policy_fingerprint": indexer.embedding_policy_fingerprint,
    }
    for corpus in CORPUS_FILES:
        save_corpus(indexer.index_dir, corpus, [], [], meta=meta)


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
    assert chunk.related_doc_paths == ["auth.md"]
    assert "def login(user):" in chunk.text


def test_symbol_chunks_create_precise_symbol_definition_records(tmp_path: Path) -> None:
    scan = _scan_for(tmp_path)
    plan = make_plan([make_bucket("Auth", "auth", ["src/auth.py"])])

    chunks = build_symbol_chunks(scan, plan, {"chatbot": {"enabled": True}})

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.kind == "code"
    assert chunk.file_path == "src/auth.py"
    assert chunk.start_line == 1
    assert chunk.end_line == 4
    assert chunk.symbol_names == ["login"]
    assert chunk.metadata["chunk_subtype"] == "symbol_definition"
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
    (repo_root / "src").mkdir()
    (repo_root / "src" / "auth.py").write_text(
        "def login(user):\n    token = issue(user)\n    return token\n",
        encoding="utf-8",
    )
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
    (output_dir / "index.md").write_text(
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
    (output_dir / "auth.md").write_text(
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
    (output_dir / "index.md").write_text(
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
        "docs/index.md": "Generated docs summary",
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
    (output_dir / "index.md").write_text(
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


def test_incremental_sync_writes_symbol_corpus_and_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "src").mkdir()
    (repo_root / "src" / "auth.py").write_text(
        "def login(user):\n    token = issue(user)\n    return token\n",
        encoding="utf-8",
    )
    output_dir = repo_root / "docs"
    output_dir.mkdir()
    plan = make_plan([make_bucket("Auth", "auth", ["src/auth.py"])])
    scan = _scan_for(tmp_path)

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
        changed_files=["src/auth.py"],
    )

    index_dir = repo_root / ".deepdoc" / "chatbot"
    symbol_records, symbol_vectors = load_corpus(index_dir, "symbol")
    manifest = load_index_manifest(index_dir)
    assert stats["symbol_chunks"] == 1
    assert "symbol" in stats["corpora_refreshed"]
    assert symbol_records[0].file_path == "src/auth.py"
    assert len(symbol_vectors) == 1
    assert manifest["artifacts"]["symbol"]["record_count"] == 1
    assert manifest["artifacts"]["source_archive"]["record_count"] == 1
    assert manifest["artifacts"]["source_archive"]["file"] == "source_archive.sqlite3"


def test_incremental_sync_skips_healthy_untouched_corpora(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    output_dir = repo_root / "docs"
    output_dir.mkdir()

    class _FakeEmbedClient:
        def embed(self, texts):
            return [[float(len(text))] for text in texts]

    monkeypatch.setattr(
        "deepdoc.chatbot.indexer.build_embedding_client", lambda cfg: _FakeEmbedClient()
    )
    indexer = ChatbotIndexer(repo_root, {"chatbot": {"enabled": True}})
    _seed_healthy_corpora(indexer)
    before = {
        corpus: corpus_paths(indexer.index_dir, corpus)["chunks"].read_bytes()
        for corpus in CORPUS_FILES
    }
    load_calls: list[str] = []
    original_load = load_corpus

    def tracked_load(index_dir, corpus):
        load_calls.append(corpus)
        return original_load(index_dir, corpus)

    monkeypatch.setattr("deepdoc.chatbot.indexer.load_corpus", tracked_load)

    stats = indexer.sync_incremental(
        plan=make_plan([]),
        scan=_scan_for(tmp_path),
        output_dir=output_dir,
    )

    assert stats["corpora_refreshed"] == []
    assert sorted(load_calls) == sorted(CORPUS_FILES)
    assert all(load_calls.count(corpus) == 1 for corpus in CORPUS_FILES)
    assert before == {
        corpus: corpus_paths(indexer.index_dir, corpus)["chunks"].read_bytes()
        for corpus in CORPUS_FILES
    }


def test_incremental_code_change_skips_unrelated_corpora(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "src").mkdir()
    (repo_root / "src" / "auth.py").write_text(
        "def login(user):\n    return issue(user)\n", encoding="utf-8"
    )
    output_dir = repo_root / "docs"
    output_dir.mkdir()

    class _FakeEmbedClient:
        def embed(self, texts):
            return [[float(len(text))] for text in texts]

    monkeypatch.setattr(
        "deepdoc.chatbot.indexer.build_embedding_client", lambda cfg: _FakeEmbedClient()
    )
    indexer = ChatbotIndexer(repo_root, {"chatbot": {"enabled": True}})
    _seed_healthy_corpora(indexer)
    scan = _scan_for(tmp_path)
    plan = make_plan([make_bucket("Auth", "auth", ["src/auth.py"])])

    stats = indexer.sync_incremental(
        plan=plan,
        scan=scan,
        output_dir=output_dir,
        changed_files=["src/auth.py"],
    )

    assert stats["corpora_refreshed"] == ["code", "symbol", "relationship"]


def test_corpus_health_requires_vector_and_lexical_indexes(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    class _FakeEmbedClient:
        def embed(self, texts):
            return []

    monkeypatch.setattr(
        "deepdoc.chatbot.indexer.build_embedding_client", lambda cfg: _FakeEmbedClient()
    )
    indexer = ChatbotIndexer(repo_root, {"chatbot": {"enabled": True}})
    _seed_healthy_corpora(indexer)

    corpus_paths(indexer.index_dir, "code")["index"].unlink()
    assert indexer._corpus_needs_rebuild("code") is True

    _seed_healthy_corpora(indexer)
    import sqlite3

    conn = sqlite3.connect(indexer.index_dir / "lexical_index.sqlite3")
    try:
        conn.execute("INSERT INTO lexical_chunks (corpus, chunk_id) VALUES (?, ?)", ("code", "orphan"))
        conn.commit()
    finally:
        conn.close()
    assert indexer._corpus_needs_rebuild("code") is True


def test_save_corpus_updates_sqlite_lexical_index(tmp_path: Path) -> None:
    index_dir = tmp_path / "repo" / ".deepdoc" / "chatbot"
    save_corpus(
        index_dir,
        "code",
        [
            ChunkRecord(
                chunk_id="c1",
                kind="code",
                source_key="src/payments.py",
                text='PAYMENTS_HOST = os.getenv("PAYMENTS_HOST")',
                chunk_hash="h1",
                file_path="src/payments.py",
                start_line=1,
                end_line=1,
            )
        ],
        [[1.0]],
    )

    hits = query_lexical_index(index_dir, "code", "PAYMENTS_HOST", limit=5)

    assert hits == ["c1"]


def test_index_manifest_describes_artifacts_without_timestamps(tmp_path: Path) -> None:
    index_dir = tmp_path / "repo" / ".deepdoc" / "chatbot"
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
            )
        ],
        [[1.0]],
    )

    first = save_index_manifest(index_dir)
    second = save_index_manifest(index_dir)

    assert first == second
    assert "generated_at" not in first
    assert first["version"] == 2
    assert first["artifacts"]["code"]["record_count"] == 1
    assert first["artifacts"]["lexical_index"]["record_count_by_corpus"]["code"] == 1


def test_chatbot_index_needs_refresh_checks_source_archive(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    class _FakeEmbedClient:
        def embed(self, texts):
            return []

    monkeypatch.setattr(
        "deepdoc.chatbot.indexer.build_embedding_client", lambda cfg: _FakeEmbedClient()
    )
    monkeypatch.setattr(
        ChatbotIndexer,
        "_corpus_needs_rebuild",
        lambda self, corpus: False,
    )

    assert chatbot_index_needs_refresh(repo_root, {"chatbot": {"enabled": True}})


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
        source_key="old-page.md",
        text="# Old Page",
        chunk_hash="oldhash",
        doc_path="old-page.md",
        doc_url="/old-page",
    )
    doc_full_record = ChunkRecord(
        chunk_id="doc-full-old",
        kind="doc_full",
        source_key="old-page.md",
        text="# Old Page\n\nMore details",
        chunk_hash="oldfullhash",
        doc_path="old-page.md",
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
        deleted_files=["old-page.md"],
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
    (repo_root / "src").mkdir()
    (repo_root / "src" / "auth.py").write_text("demo code\n", encoding="utf-8")
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
            "embedding_model": "fastembed||nomic-ai/nomic-embed-text-v1.5||",
            "schema_version": CHATBOT_CORPUS_SCHEMA_VERSION,
            "embedding_policy_fingerprint": embedding_policy_fingerprint(
                resolve_embedding_capabilities(
                    {"backend": "fastembed", "fastembed_model": "nomic-ai/nomic-embed-text-v1.5"}
                )
            ),
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


def test_corpus_needs_rebuild_when_existing_source_is_now_excluded(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "src").mkdir()
    (repo_root / "src" / "secret.py").write_text("TOKEN = 'abc'\n", encoding="utf-8")
    index_dir = repo_root / ".deepdoc" / "chatbot"
    save_corpus(
        index_dir,
        "code",
        [
            ChunkRecord(
                chunk_id="c1",
                kind="code",
                source_key="src/secret.py",
                text="TOKEN = 'abc'",
                chunk_hash="hashc1",
                file_path="src/secret.py",
            )
        ],
        [[1.0]],
        meta={
            "embedding_model": "fastembed||nomic-ai/nomic-embed-text-v1.5||",
            "schema_version": CHATBOT_CORPUS_SCHEMA_VERSION,
            "embedding_policy_fingerprint": embedding_policy_fingerprint(
                resolve_embedding_capabilities(
                    {"backend": "fastembed", "fastembed_model": "nomic-ai/nomic-embed-text-v1.5"}
                )
            ),
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
                "indexing": {"exclude_globs": ["src/secret.py"]},
            }
        },
    )

    assert indexer._corpus_needs_rebuild("code") is True


def test_oversized_source_does_not_force_permanent_corpus_rebuild(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "large.py").write_text("x = 1\n" * 20, encoding="utf-8")

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
                "indexing": {"max_file_bytes": 10},
            }
        },
    )
    save_corpus(
        indexer.index_dir,
        "code",
        [
            ChunkRecord(
                chunk_id="large",
                kind="code",
                source_key="large.py",
                text="x = 1",
                chunk_hash="large",
                file_path="large.py",
            )
        ],
        [[1.0]],
        meta={
            "embedding_model": service_model_identity(
                indexer.chatbot_cfg["embeddings"]
            ),
            "schema_version": CHATBOT_CORPUS_SCHEMA_VERSION,
            "embedding_policy_fingerprint": indexer.embedding_policy_fingerprint,
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
        existing_records=existing_records,
        existing_vectors=[[1.0], [0.5]],
    )

    merged_records, _ = load_corpus(index_dir, "relationship")
    call_graph_records = [
        record
        for record in merged_records
        if (record.metadata or {}).get("chunk_subtype") == "call_graph"
    ]
    assert [record.chunk_id for record in call_graph_records] == ["cg_new"]
    assert any(record.chunk_id == "rel_old" for record in merged_records)
