"""Index build and incremental refresh for chatbot corpora."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console

from ..v2_models import DocPlan, RepoScan
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
from .persistence import corpus_paths, load_corpus, save_corpus
from .providers import build_embedding_client
from .scaffold import scaffold_chatbot_backend
from .settings import chatbot_index_dir, get_chatbot_cfg, service_model_identity
from .source_archive import build_source_archive, update_source_archive
from .types import ChunkRecord

console = Console()
CHATBOT_CORPUS_SCHEMA_VERSION = 5


class ChatbotIndexer:
    """Builds and refreshes chatbot corpora."""

    def __init__(self, repo_root: Path, cfg: dict[str, Any]) -> None:
        self.repo_root = repo_root
        self.cfg = cfg
        self.chatbot_cfg = get_chatbot_cfg(cfg)
        self.index_dir = chatbot_index_dir(repo_root, cfg)
        self.embedding_client = build_embedding_client(cfg)

    def sync_full(
        self,
        *,
        plan: DocPlan,
        scan: RepoScan,
        output_dir: Path,
        has_openapi: bool = False,
    ) -> dict[str, Any]:
        console.print(
            "[dim]Chatbot sync: building code/artifact/doc/repo-doc/relationship corpora...[/dim]"
        )
        code_records = build_code_chunks(scan, plan, self.cfg)
        artifact_records = build_artifact_chunks(
            self.repo_root, scan, plan, output_dir, self.cfg
        )
        doc_summary_records = build_doc_summary_chunks(
            output_dir, plan, self.cfg, has_openapi=has_openapi
        )
        doc_full_records = build_doc_full_chunks(
            output_dir, plan, self.cfg, has_openapi=has_openapi
        )
        repo_doc_records = build_repo_doc_chunks(
            self.repo_root,
            scan,
            plan,
            self.cfg,
            output_dir=output_dir,
        )
        relationship_records = build_relationship_chunks(scan, plan, self.cfg)

        # Call graph chunks — index execution chains for deep chatbot retrieval
        cg_chunks = []
        graph_chunks = []
        if hasattr(scan, "call_graph") and scan.call_graph is not None:
            cg_chunks = build_call_graph_chunks(
                scan.call_graph, scan.parsed_files, plan=plan
            )
            graph_chunks = build_graph_relation_chunks(scan.call_graph, plan=plan)
            relationship_records.extend(cg_chunks)
            relationship_records.extend(graph_chunks)

        console.print(
            "[dim]Chatbot sync: embedding and saving corpora "
            f"({len(code_records)} code, {len(artifact_records)} artifact, "
            f"{len(doc_summary_records)} doc summary, {len(doc_full_records)} doc full, "
            f"{len(repo_doc_records)} repo doc, "
            f"{len(relationship_records)} relationship)...[/dim]"
        )
        self._save_records("code", code_records)
        self._save_records("artifact", artifact_records)
        self._save_records("doc_summary", doc_summary_records)
        self._save_records("doc_full", doc_full_records)
        self._save_records("repo_doc", repo_doc_records)
        self._save_records("relationship", relationship_records)
        console.print("[dim]Chatbot sync: packing full source text archive...[/dim]")
        build_source_archive(self.repo_root, self.index_dir, self.cfg)
        console.print("[dim]Chatbot sync: scaffolding backend...[/dim]")
        scaffold_chatbot_backend(self.repo_root, self.cfg)
        return {
            "code_chunks": len(code_records),
            "artifact_chunks": len(artifact_records),
            "doc_chunks": len(doc_summary_records),
            "doc_full_chunks": len(doc_full_records),
            "repo_doc_chunks": len(repo_doc_records),
            "relationship_chunks": len(relationship_records),
            "call_graph_chunks": len(cg_chunks),
            "graph_relation_chunks": len(graph_chunks),
            "corpora_refreshed": [
                "code",
                "artifact",
                "doc_summary",
                "doc_full",
                "repo_doc",
                "relationship",
            ],
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

        # If a previous full sync failed midway, recover any corpus that is
        # still missing even when there are no changed files for it.
        rebuild_code = self._corpus_needs_rebuild("code")
        rebuild_artifact = self._corpus_needs_rebuild("artifact")
        rebuild_doc_summary = self._corpus_needs_rebuild("doc_summary")
        rebuild_doc_full = self._corpus_needs_rebuild("doc_full")
        rebuild_repo_doc = self._corpus_needs_rebuild("repo_doc")
        rebuild_relationship = self._corpus_needs_rebuild("relationship")

        if rebuild_code:
            code_records = build_code_chunks(scan, plan, self.cfg)
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

        if rebuild_code:
            self._save_records("code", code_records)
        else:
            self._merge_records(
                "code",
                code_records,
                changed_keys=code_targets,
                deleted_keys=deleted_files,
            )
        if rebuild_artifact:
            self._save_records("artifact", artifact_records)
        else:
            self._merge_records(
                "artifact",
                artifact_records,
                changed_keys=artifact_targets,
                deleted_keys=deleted_files,
            )
        deleted_doc_paths = [path for path in deleted_files if path.endswith(".mdx")]
        if rebuild_doc_summary:
            self._save_records("doc_summary", doc_summary_records)
        else:
            self._merge_records(
                "doc_summary",
                doc_summary_records,
                changed_keys=[f"{slug}.mdx" for slug in changed_doc_slugs],
                deleted_keys=deleted_doc_paths,
            )
        if rebuild_doc_full:
            self._save_records("doc_full", doc_full_records)
        else:
            self._merge_records(
                "doc_full",
                doc_full_records,
                changed_keys=[f"{slug}.mdx" for slug in changed_doc_slugs],
                deleted_keys=deleted_doc_paths,
            )
        if rebuild_repo_doc:
            self._save_records("repo_doc", repo_doc_records)
        else:
            self._merge_records(
                "repo_doc",
                repo_doc_records,
                changed_keys=repo_doc_targets,
                deleted_keys=deleted_files,
            )
        if rebuild_relationship:
            self._save_records("relationship", relationship_records)
        else:
            self._merge_records(
                "relationship",
                relationship_records,
                changed_keys=relationship_targets,
                deleted_keys=deleted_files,
            )
            
        update_source_archive(
            self.repo_root,
            self.index_dir,
            self.cfg,
            changed_files=changed_files,
            deleted_files=deleted_files,
        )
            
        scaffold_chatbot_backend(self.repo_root, self.cfg)
        refreshed_corpora = [
            corpus
            for corpus, refreshed in (
                ("code", rebuild_code or bool(code_targets)),
                ("artifact", rebuild_artifact or bool(artifact_targets)),
                ("doc_summary", rebuild_doc_summary or bool(changed_doc_slugs)),
                ("doc_full", rebuild_doc_full or bool(changed_doc_slugs)),
                ("repo_doc", rebuild_repo_doc or bool(repo_doc_targets)),
                (
                    "relationship",
                    rebuild_relationship
                    or bool(relationship_targets)
                    or bool(graph_chunks),
                ),
            )
            if refreshed
        ]
        return {
            "code_chunks": len(code_records),
            "artifact_chunks": len(artifact_records),
            "doc_chunks": len(doc_summary_records),
            "doc_full_chunks": len(doc_full_records),
            "repo_doc_chunks": len(repo_doc_records),
            "relationship_chunks": len(relationship_records),
            "graph_relation_chunks": len(graph_chunks),
            "corpora_refreshed": refreshed_corpora,
        }

    def _save_records(self, corpus: str, records: list[ChunkRecord]) -> None:
        console.print(
            f"[dim]Chatbot sync: embedding {corpus} corpus ({len(records)} records)...[/dim]"
        )
        vectors = (
            self.embedding_client.embed([record.text for record in records])
            if records
            else []
        )
        meta = {
            "embedding_model": service_model_identity(self.chatbot_cfg["embeddings"]),
            "schema_version": CHATBOT_CORPUS_SCHEMA_VERSION,
        }
        save_corpus(self.index_dir, corpus, records, vectors, meta=meta)
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
    ) -> None:
        existing_records, existing_vectors = load_corpus(self.index_dir, corpus)
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
        save_corpus(self.index_dir, corpus, merged_records, merged_vectors, meta=meta)

    def _corpus_needs_rebuild(self, corpus: str) -> bool:
        paths = corpus_paths(self.index_dir, corpus)
        if (
            not paths["chunks"].exists()
            or not paths["vectors"].exists()
            or not paths["meta"].exists()
        ):
            return True
        try:
            meta = json.loads(paths["meta"].read_text(encoding="utf-8"))
        except Exception:
            return True
        if meta.get("schema_version") != CHATBOT_CORPUS_SCHEMA_VERSION:
            return True
        if meta.get("embedding_model") != service_model_identity(
            self.chatbot_cfg["embeddings"]
        ):
            return True

        records, vectors = load_corpus(self.index_dir, corpus)
        try:
            vector_count = int(getattr(vectors, "shape", [len(vectors)])[0])
        except Exception:
            vector_count = len(vectors)
        if not records:
            return vector_count != 0
        return vector_count != len(records)


def chatbot_index_needs_refresh(repo_root: Path, cfg: dict[str, Any]) -> bool:
    """Return whether any chatbot corpus is missing or inconsistent."""
    indexer = ChatbotIndexer(repo_root, cfg)
    return any(
        indexer._corpus_needs_rebuild(corpus)
        for corpus in (
            "code",
            "artifact",
            "doc_summary",
            "doc_full",
            "repo_doc",
            "relationship",
        )
    )
