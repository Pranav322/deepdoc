"""Index build and incremental refresh for chatbot corpora."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from ..planner_v2 import DocPlan, RepoScan
from .chunker import (
    build_artifact_chunks,
    build_code_chunks,
    discover_artifact_files,
    is_artifact_file_path,
)
from .docs_summary import build_doc_summary_chunks
from .persistence import load_corpus, save_corpus
from .providers import build_embedding_client
from .scaffold import scaffold_chatbot_backend
from .settings import chatbot_index_dir, get_chatbot_cfg, service_model_identity
from .types import ChunkRecord


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
        code_records = build_code_chunks(scan, plan, self.cfg)
        artifact_records = build_artifact_chunks(self.repo_root, scan, plan, output_dir, self.cfg)
        doc_records = build_doc_summary_chunks(output_dir, plan, self.cfg, has_openapi=has_openapi)

        self._save_records("code", code_records)
        self._save_records("artifact", artifact_records)
        self._save_records("doc_summary", doc_records)
        scaffold_chatbot_backend(self.repo_root, self.cfg)
        return {
            "code_chunks": len(code_records),
            "artifact_chunks": len(artifact_records),
            "doc_chunks": len(doc_records),
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
            if is_artifact_file_path(path) or path in discover_artifact_files(self.repo_root, scan, output_dir)
        ]

        code_records = build_code_chunks(scan, plan, self.cfg, files=code_targets) if code_targets else []
        artifact_records = (
            build_artifact_chunks(self.repo_root, scan, plan, output_dir, self.cfg, files=artifact_targets)
            if artifact_targets
            else []
        )
        doc_records = (
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

        self._merge_records("code", code_records, changed_keys=code_targets, deleted_keys=deleted_files)
        self._merge_records("artifact", artifact_records, changed_keys=artifact_targets, deleted_keys=deleted_files)
        deleted_doc_paths = [f"{slug}.mdx" for slug in deleted_files if slug.endswith(".mdx")]
        self._merge_records(
            "doc_summary",
            doc_records,
            changed_keys=[f"{slug}.mdx" for slug in changed_doc_slugs],
            deleted_keys=deleted_doc_paths,
        )
        scaffold_chatbot_backend(self.repo_root, self.cfg)
        return {
            "code_chunks": len(code_records),
            "artifact_chunks": len(artifact_records),
            "doc_chunks": len(doc_records),
        }

    def _save_records(self, corpus: str, records: list[ChunkRecord]) -> None:
        vectors = self.embedding_client.embed([record.text for record in records]) if records else []
        meta = {"embedding_model": service_model_identity(self.chatbot_cfg["embeddings"])}
        save_corpus(self.index_dir, corpus, records, vectors, meta=meta)

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

        kept_records: list[ChunkRecord] = []
        kept_vectors: list[Any] = []
        for idx, record in enumerate(existing_records):
            if record.source_key in changed or record.source_key in deleted:
                continue
            kept_records.append(record)
            if len(existing_vectors) > idx:
                kept_vectors.append(existing_vectors[idx])

        new_vectors = self.embedding_client.embed([record.text for record in fresh_records]) if fresh_records else []
        merged_records = kept_records + fresh_records
        merged_vectors = kept_vectors + new_vectors
        meta = {"embedding_model": service_model_identity(self.chatbot_cfg["embeddings"])}
        save_corpus(self.index_dir, corpus, merged_records, merged_vectors, meta=meta)
