"""Index build and incremental refresh for chatbot corpora."""

from __future__ import annotations

from contextlib import nullcontext
import json
from pathlib import Path
from typing import Any

from rich.console import Console

from ..v2_models import DocPlan, RepoScan
from ..telemetry import RunTelemetry
from .chunker import (
    build_artifact_chunks,
    build_call_graph_chunks,
    build_code_chunks,
    build_graph_relation_chunks,
    build_relationship_chunks,
    discover_artifact_files,
    is_artifact_file_path,
)
from .docs_summary import (
    build_doc_full_chunks,
    build_doc_summary_chunks,
    build_repo_doc_chunks,
    discover_repo_doc_files,
)
from .persistence import (
    corpus_paths,
    lexical_corpus_record_count,
    load_corpus,
    save_corpus,
    save_index_manifest,
)
from .providers import build_embedding_client
from .scaffold import scaffold_chatbot_backend
from .settings import chatbot_index_dir, get_chatbot_cfg, service_model_identity
from .source_archive import (
    build_source_archive,
    source_archive_needs_rebuild,
    source_path_is_archiveable,
    update_source_archive,
)
from .symbol_index import build_symbol_chunks
from .types import ChunkRecord

console = Console()
CHATBOT_CORPUS_SCHEMA_VERSION = 5
SOURCE_BACKED_CORPORA = (
    "code",
    "symbol",
    "artifact",
    "repo_doc",
    "relationship",
)


class ChatbotIndexer:
    """Builds and refreshes chatbot corpora."""

    def __init__(
        self,
        repo_root: Path,
        cfg: dict[str, Any],
        telemetry: RunTelemetry | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.cfg = cfg
        self.chatbot_cfg = get_chatbot_cfg(cfg)
        self.index_dir = chatbot_index_dir(repo_root, cfg)
        self.embedding_client = build_embedding_client(cfg)
        self.telemetry = telemetry

    def _span(self, name: str):
        return self.telemetry.span(name) if self.telemetry is not None else nullcontext()

    def sync_full(
        self,
        *,
        plan: DocPlan,
        scan: RepoScan,
        output_dir: Path,
        has_openapi: bool = False,
    ) -> dict[str, Any]:
        console.print(
            "[dim]Chatbot sync: building code/symbol/artifact/doc/repo-doc/relationship corpora...[/dim]"
        )
        with self._span("chatbot.chunk.code"):
            code_records = build_code_chunks(scan, plan, self.cfg)
        with self._span("chatbot.chunk.symbol"):
            symbol_records = build_symbol_chunks(scan, plan, self.cfg)
        with self._span("chatbot.chunk.artifact"):
            artifact_records = build_artifact_chunks(
                self.repo_root, scan, plan, output_dir, self.cfg
            )
        with self._span("chatbot.chunk.doc_summary"):
            doc_summary_records = build_doc_summary_chunks(
                output_dir, plan, self.cfg, has_openapi=has_openapi
            )
        with self._span("chatbot.chunk.doc_full"):
            doc_full_records = build_doc_full_chunks(
                output_dir, plan, self.cfg, has_openapi=has_openapi
            )
        with self._span("chatbot.chunk.repo_doc"):
            repo_doc_records = build_repo_doc_chunks(
                self.repo_root,
                scan,
                plan,
                self.cfg,
                output_dir=output_dir,
            )
        with self._span("chatbot.chunk.relationship"):
            relationship_records = build_relationship_chunks(scan, plan, self.cfg)

        # Call graph chunks — index execution chains for deep chatbot retrieval
        cg_chunks = []
        graph_chunks = []
        if hasattr(scan, "call_graph") and scan.call_graph is not None:
            with self._span("chatbot.chunk.call_graph"):
                cg_chunks = build_call_graph_chunks(
                    scan.call_graph, scan.parsed_files, plan=plan
                )
                graph_chunks = build_graph_relation_chunks(scan.call_graph, plan=plan)
            relationship_records.extend(cg_chunks)
            relationship_records.extend(graph_chunks)

        console.print(
            "[dim]Chatbot sync: embedding and saving corpora "
            f"({len(code_records)} code, {len(symbol_records)} symbol, {len(artifact_records)} artifact, "
            f"{len(doc_summary_records)} doc summary, {len(doc_full_records)} doc full, "
            f"{len(repo_doc_records)} repo doc, "
            f"{len(relationship_records)} relationship)...[/dim]"
        )
        self._save_records("code", code_records)
        self._save_records("symbol", symbol_records)
        self._save_records("artifact", artifact_records)
        self._save_records("doc_summary", doc_summary_records)
        self._save_records("doc_full", doc_full_records)
        self._save_records("repo_doc", repo_doc_records)
        self._save_records("relationship", relationship_records)
        console.print("[dim]Chatbot sync: packing full source text archive...[/dim]")
        with self._span("chatbot.source_archive"):
            build_source_archive(self.repo_root, self.index_dir, self.cfg)
        with self._span("chatbot.index_manifest"):
            manifest = save_index_manifest(self.index_dir)
        console.print("[dim]Chatbot sync: scaffolding backend...[/dim]")
        with self._span("chatbot.backend_scaffold"):
            scaffold_chatbot_backend(self.repo_root, self.cfg)
        return {
            "code_chunks": len(code_records),
            "symbol_chunks": len(symbol_records),
            "artifact_chunks": len(artifact_records),
            "doc_chunks": len(doc_summary_records),
            "doc_full_chunks": len(doc_full_records),
            "repo_doc_chunks": len(repo_doc_records),
            "relationship_chunks": len(relationship_records),
            "call_graph_chunks": len(cg_chunks),
            "graph_relation_chunks": len(graph_chunks),
            "corpora_refreshed": [
                "code",
                "symbol",
                "artifact",
                "doc_summary",
                "doc_full",
                "repo_doc",
                "relationship",
            ],
            "artifact_manifest": manifest,
        }

    def sync_incremental(
        self,
        *,
        plan: DocPlan,
        scan: RepoScan,
        output_dir: Path,
        changed_files: list[str] | None = None,
        deleted_files: list[str] | None = None,
        changed_doc_slugs: list[str] | None = None,
        has_openapi: bool = False,
    ) -> dict[str, Any]:
        changed_files = sorted(set(changed_files or []))
        deleted_files = sorted(set(deleted_files or []))
        changed_doc_slugs = sorted(set(changed_doc_slugs or []))

        code_targets = [path for path in changed_files if path in scan.file_contents]
        artifact_targets = [
            path
            for path in changed_files
            if is_artifact_file_path(path)
            or path in discover_artifact_files(self.repo_root, scan, output_dir)
        ]
        repo_doc_targets = [
            path
            for path in changed_files
            if path
            in discover_repo_doc_files(
                self.repo_root,
                scan,
                self.cfg,
                output_dir=output_dir,
            )
        ]

        code_records = (
            build_code_chunks(scan, plan, self.cfg, files=code_targets)
            if code_targets
            else []
        )
        symbol_records = (
            build_symbol_chunks(scan, plan, self.cfg, files=code_targets)
            if code_targets
            else []
        )
        artifact_records = (
            build_artifact_chunks(
                self.repo_root, scan, plan, output_dir, self.cfg, files=artifact_targets
            )
            if artifact_targets
            else []
        )
        doc_summary_records = (
            build_doc_summary_chunks(
                output_dir,
                plan,
                self.cfg,
                has_openapi=has_openapi,
                slugs=changed_doc_slugs,
            )
            if changed_doc_slugs
            else []
        )
        doc_full_records = (
            build_doc_full_chunks(
                output_dir,
                plan,
                self.cfg,
                has_openapi=has_openapi,
                slugs=changed_doc_slugs,
            )
            if changed_doc_slugs
            else []
        )
        repo_doc_records = (
            build_repo_doc_chunks(
                self.repo_root,
                scan,
                plan,
                self.cfg,
                output_dir=output_dir,
                files=repo_doc_targets,
            )
            if repo_doc_targets
            else []
        )

        # Inspect each corpus once. Healthy, mutation-free corpora remain byte-for-byte
        # untouched; unhealthy corpora still receive a complete recovery rebuild.
        corpus_states = {
            corpus: self._load_corpus_state(corpus)
            for corpus in (
                "code",
                "symbol",
                "artifact",
                "doc_summary",
                "doc_full",
                "repo_doc",
                "relationship",
            )
        }
        rebuild_code = corpus_states["code"][0]
        rebuild_symbol = corpus_states["symbol"][0]
        rebuild_artifact = corpus_states["artifact"][0]
        rebuild_doc_summary = corpus_states["doc_summary"][0]
        rebuild_doc_full = corpus_states["doc_full"][0]
        rebuild_repo_doc = corpus_states["repo_doc"][0]
        rebuild_relationship = corpus_states["relationship"][0]

        if rebuild_code:
            code_records = build_code_chunks(scan, plan, self.cfg)
        if rebuild_symbol:
            symbol_records = build_symbol_chunks(scan, plan, self.cfg)
        if rebuild_artifact:
            artifact_records = build_artifact_chunks(
                self.repo_root, scan, plan, output_dir, self.cfg
            )
        if rebuild_doc_summary:
            doc_summary_records = build_doc_summary_chunks(
                output_dir,
                plan,
                self.cfg,
                has_openapi=has_openapi,
            )
        if rebuild_doc_full:
            doc_full_records = build_doc_full_chunks(
                output_dir,
                plan,
                self.cfg,
                has_openapi=has_openapi,
            )
        if rebuild_repo_doc:
            repo_doc_records = build_repo_doc_chunks(
                self.repo_root,
                scan,
                plan,
                self.cfg,
                output_dir=output_dir,
            )

        # Relationship chunks — rebuild for any changed code files, or full rebuild if missing
        relationship_targets = [
            path for path in (changed_files or []) if path in scan.parsed_files
        ]
        relationship_records = (
            build_relationship_chunks(scan, plan, self.cfg, files=relationship_targets)
            if relationship_targets
            else []
        )
        if rebuild_relationship:
            relationship_records = build_relationship_chunks(scan, plan, self.cfg)

        # Call graph chunks — rebuild if call graph changed or missing
        cg_chunks = []
        graph_chunks = []
        if hasattr(scan, "call_graph") and scan.call_graph is not None:
            if relationship_targets or rebuild_relationship:
                cg_chunks = build_call_graph_chunks(
                    scan.call_graph, scan.parsed_files, plan=plan
                )
                graph_chunks = build_graph_relation_chunks(
                    scan.call_graph,
                    plan=plan,
                    files=relationship_targets if not rebuild_relationship else None,
                )
                relationship_records.extend(cg_chunks)
                relationship_records.extend(graph_chunks)

        refreshed: dict[str, bool] = {}
        refreshed["code"] = self._sync_incremental_corpus(
            "code",
            code_records,
            changed_keys=code_targets,
            deleted_keys=deleted_files,
            state=corpus_states["code"],
        )
        refreshed["symbol"] = self._sync_incremental_corpus(
            "symbol",
            symbol_records,
            changed_keys=code_targets,
            deleted_keys=deleted_files,
            state=corpus_states["symbol"],
        )
        refreshed["artifact"] = self._sync_incremental_corpus(
            "artifact",
            artifact_records,
            changed_keys=artifact_targets,
            deleted_keys=deleted_files,
            state=corpus_states["artifact"],
        )
        deleted_doc_paths = [path for path in deleted_files if path.endswith((".md", ".mdx"))]
        changed_doc_paths = [f"{slug}.md" for slug in changed_doc_slugs]
        refreshed["doc_summary"] = self._sync_incremental_corpus(
            "doc_summary",
            doc_summary_records,
            changed_keys=changed_doc_paths,
            deleted_keys=deleted_doc_paths,
            state=corpus_states["doc_summary"],
        )
        refreshed["doc_full"] = self._sync_incremental_corpus(
            "doc_full",
            doc_full_records,
            changed_keys=changed_doc_paths,
            deleted_keys=deleted_doc_paths,
            state=corpus_states["doc_full"],
        )
        refreshed["repo_doc"] = self._sync_incremental_corpus(
            "repo_doc",
            repo_doc_records,
            changed_keys=repo_doc_targets,
            deleted_keys=deleted_files,
            state=corpus_states["repo_doc"],
        )
        refreshed["relationship"] = self._sync_incremental_corpus(
            "relationship",
            relationship_records,
            changed_keys=relationship_targets,
            deleted_keys=deleted_files,
            state=corpus_states["relationship"],
        )
            
        update_source_archive(
            self.repo_root,
            self.index_dir,
            self.cfg,
            changed_files=changed_files,
            deleted_files=deleted_files,
        )
        manifest = save_index_manifest(self.index_dir)
            
        scaffold_chatbot_backend(self.repo_root, self.cfg)
        refreshed_corpora = [
            corpus for corpus, was_refreshed in refreshed.items() if was_refreshed
        ]
        return {
            "code_chunks": len(code_records),
            "symbol_chunks": len(symbol_records),
            "artifact_chunks": len(artifact_records),
            "doc_chunks": len(doc_summary_records),
            "doc_full_chunks": len(doc_full_records),
            "repo_doc_chunks": len(repo_doc_records),
            "relationship_chunks": len(relationship_records),
            "graph_relation_chunks": len(graph_chunks),
            "corpora_refreshed": refreshed_corpora,
            "artifact_manifest": manifest,
        }

    def _save_records(self, corpus: str, records: list[ChunkRecord]) -> None:
        console.print(
            f"[dim]Chatbot sync: embedding {corpus} corpus ({len(records)} records)...[/dim]"
        )
        with self._span(f"chatbot.embed.{corpus}"):
            vectors = (
                self.embedding_client.embed([record.text for record in records])
                if records
                else []
            )
        meta = {
            "embedding_model": service_model_identity(self.chatbot_cfg["embeddings"]),
            "schema_version": CHATBOT_CORPUS_SCHEMA_VERSION,
        }
        with self._span(f"chatbot.write.{corpus}"):
            save_corpus(self.index_dir, corpus, records, vectors, meta=meta)
        if self.telemetry is not None:
            self.telemetry.counter(f"chatbot.records.{corpus}", len(records))
        console.print(
            f"[dim]Chatbot sync: saved {corpus} corpus ({len(records)} records).[/dim]"
        )

    def _merge_records(
        self,
        corpus: str,
        fresh_records: list[ChunkRecord],
        *,
        changed_keys: list[str],
        deleted_keys: list[str],
        existing_records: list[ChunkRecord],
        existing_vectors: Any,
    ) -> None:
        deleted = set(deleted_keys)
        changed = set(changed_keys)
        call_graph_sources = {
            record.source_key
            for record in fresh_records
            if (record.metadata or {}).get("chunk_subtype") == "call_graph"
        }

        kept_records: list[ChunkRecord] = []
        kept_vectors: list[Any] = []
        for idx, record in enumerate(existing_records):
            if record.source_key in changed or record.source_key in deleted:
                continue
            if (
                corpus == "relationship"
                and (record.metadata or {}).get("chunk_subtype") == "call_graph"
                and record.source_key in call_graph_sources
            ):
                continue
            kept_records.append(record)
            if len(existing_vectors) > idx:
                kept_vectors.append(existing_vectors[idx])

        with self._span(f"chatbot.embed.{corpus}"):
            new_vectors = (
                self.embedding_client.embed([record.text for record in fresh_records])
                if fresh_records
                else []
            )
        merged_records = kept_records + fresh_records
        merged_vectors = kept_vectors + new_vectors
        meta = {
            "embedding_model": service_model_identity(self.chatbot_cfg["embeddings"]),
            "schema_version": CHATBOT_CORPUS_SCHEMA_VERSION,
        }
        with self._span(f"chatbot.write.{corpus}"):
            save_corpus(
                self.index_dir, corpus, merged_records, merged_vectors, meta=meta
            )
        if self.telemetry is not None:
            self.telemetry.counter(f"chatbot.records.{corpus}", len(fresh_records))

    def _sync_incremental_corpus(
        self,
        corpus: str,
        fresh_records: list[ChunkRecord],
        *,
        changed_keys: list[str],
        deleted_keys: list[str],
        state: tuple[bool, list[ChunkRecord], Any],
    ) -> bool:
        rebuild, existing_records, existing_vectors = state
        if rebuild:
            self._save_records(corpus, fresh_records)
            return True

        deleted = set(deleted_keys)
        has_effective_deletion = any(
            record.source_key in deleted for record in existing_records
        )
        if not changed_keys and not fresh_records and not has_effective_deletion:
            return False

        self._merge_records(
            corpus,
            fresh_records,
            changed_keys=changed_keys,
            deleted_keys=deleted_keys,
            existing_records=existing_records,
            existing_vectors=existing_vectors,
        )
        return True

    def _corpus_needs_rebuild(self, corpus: str) -> bool:
        return self._load_corpus_state(corpus)[0]

    def source_backed_corpora_needing_rebuild(self) -> list[str]:
        """Return corpora that require a complete source scan to recover safely."""
        return [
            corpus
            for corpus in SOURCE_BACKED_CORPORA
            if self._corpus_needs_rebuild(corpus)
        ]

    def _load_corpus_state(
        self, corpus: str
    ) -> tuple[bool, list[ChunkRecord], Any]:
        paths = corpus_paths(self.index_dir, corpus)
        if (
            not paths["chunks"].exists()
            or not paths["vectors"].exists()
            or not paths["index"].exists()
            or not paths["meta"].exists()
        ):
            return True, [], []
        try:
            meta = json.loads(paths["meta"].read_text(encoding="utf-8"))
        except Exception:
            return True, [], []
        if meta.get("schema_version") != CHATBOT_CORPUS_SCHEMA_VERSION:
            return True, [], []
        if meta.get("embedding_model") != service_model_identity(
            self.chatbot_cfg["embeddings"]
        ):
            return True, [], []

        try:
            with self._span(f"chatbot.load.{corpus}"):
                records, vectors = load_corpus(self.index_dir, corpus)
            vector_count = int(getattr(vectors, "shape", [len(vectors)])[0])
        except Exception:
            return True, [], []
        if vector_count != len(records):
            return True, records, vectors
        if lexical_corpus_record_count(self.index_dir, corpus) != len(records):
            return True, records, vectors
        if self._corpus_has_unindexable_source_records(corpus, records):
            return True, records, vectors
        return False, records, vectors

    def _corpus_has_unindexable_source_records(
        self,
        corpus: str,
        records: list[ChunkRecord],
    ) -> bool:
        if corpus not in SOURCE_BACKED_CORPORA:
            return False

        max_file_bytes = int(
            self.chatbot_cfg.get("indexing", {}).get("max_file_bytes", 250000)
        )
        for record in records:
            rel_path = record.source_key or record.file_path
            if not rel_path:
                continue
            source_path = self.repo_root / rel_path
            try:
                if source_path.is_file() and source_path.stat().st_size > max_file_bytes:
                    continue
            except OSError:
                return True
            if not source_path_is_archiveable(self.repo_root, rel_path, self.cfg):
                return True
        return False


def chatbot_index_needs_refresh(repo_root: Path, cfg: dict[str, Any]) -> bool:
    """Return whether any chatbot corpus is missing or inconsistent."""
    indexer = ChatbotIndexer(repo_root, cfg)
    if source_archive_needs_rebuild(repo_root, indexer.index_dir, cfg):
        return True
    return any(
        indexer._corpus_needs_rebuild(corpus)
        for corpus in (
            "code",
            "symbol",
            "artifact",
            "doc_summary",
            "doc_full",
            "repo_doc",
            "relationship",
        )
    )
