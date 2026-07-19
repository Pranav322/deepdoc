from __future__ import annotations

import pytest

from deepdoc.chatbot.embedding_capabilities import (
    EmbeddingCapabilityError,
    embedding_policy_fingerprint,
    fit_embedding_text,
    fit_embedding_records,
    resolve_embedding_capabilities,
)
from deepdoc.chatbot.types import ChunkRecord


def test_default_fastembed_profile_resolves_without_litellm(monkeypatch) -> None:
    monkeypatch.setattr(
        "deepdoc.chatbot.embedding_capabilities.prepare_litellm",
        lambda: (_ for _ in ()).throw(AssertionError("should not resolve hosted metadata")),
    )

    capabilities = resolve_embedding_capabilities(
        {
            "backend": "fastembed",
            "fastembed_model": "nomic-ai/nomic-embed-text-v1.5",
        }
    )

    assert capabilities.max_input_tokens == 8192
    assert capabilities.source == "fastembed_registry"


def test_embedding_profile_fits_line_aligned_text_with_marker(monkeypatch) -> None:
    monkeypatch.setattr(
        "deepdoc.chatbot.embedding_capabilities.prepare_litellm",
        lambda: (_ for _ in ()).throw(Exception()),
    )
    capabilities = resolve_embedding_capabilities(
        {"backend": "fastembed", "fastembed_model": "unknown", "max_input_tokens": 60}
    )
    text = "header\n" + "line\n" * 100

    fitted = fit_embedding_text(text, capabilities)

    assert fitted.startswith("header")
    assert fitted.endswith("[truncated for embedding]")
    assert "line\nline" in fitted


def test_embedding_profile_fits_oversized_first_line(monkeypatch) -> None:
    monkeypatch.setattr(
        "deepdoc.chatbot.embedding_capabilities.prepare_litellm",
        lambda: (_ for _ in ()).throw(Exception()),
    )
    capabilities = resolve_embedding_capabilities(
        {"backend": "fastembed", "fastembed_model": "unknown", "max_input_tokens": 30}
    )

    fitted = fit_embedding_text("x" * 1000, capabilities)

    assert fitted.endswith("[truncated for embedding]")
    assert fitted.startswith("x")


def test_unknown_embedding_model_requires_explicit_capacity() -> None:
    with pytest.raises(EmbeddingCapabilityError, match="max_input_tokens"):
        resolve_embedding_capabilities(
            {"backend": "fastembed", "fastembed_model": "unknown-model"}
        )


def test_embedding_policy_fingerprint_changes_with_capacity() -> None:
    first = resolve_embedding_capabilities(
        {"backend": "fastembed", "fastembed_model": "unknown", "max_input_tokens": 512}
    )
    second = resolve_embedding_capabilities(
        {"backend": "fastembed", "fastembed_model": "unknown", "max_input_tokens": 1024}
    )

    assert embedding_policy_fingerprint(first) != embedding_policy_fingerprint(second)


def test_fitted_embedding_record_updates_chunk_id_hash_fragment(monkeypatch) -> None:
    monkeypatch.setattr(
        "deepdoc.chatbot.embedding_capabilities.prepare_litellm",
        lambda: (_ for _ in ()).throw(Exception()),
    )
    capabilities = resolve_embedding_capabilities(
        {"backend": "fastembed", "fastembed_model": "unknown", "max_input_tokens": 30}
    )
    record = ChunkRecord(
        chunk_id="src/app.py:1:10:deadbeef",
        kind="code",
        source_key="src/app.py",
        text="header\n" + "line\n" * 100,
        chunk_hash="deadbeefcafebabe",
        file_path="src/app.py",
    )

    fitted = fit_embedding_records([record], capabilities)[0]

    assert fitted.chunk_hash != record.chunk_hash
    assert fitted.chunk_hash[:8] in fitted.chunk_id
    assert record.chunk_hash[:8] not in fitted.chunk_id
