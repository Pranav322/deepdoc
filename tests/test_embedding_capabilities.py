from __future__ import annotations

import pytest

from deepdoc.chatbot.embedding_capabilities import (
    EmbeddingCapabilityError,
    embedding_policy_fingerprint,
    fit_embedding_text,
    resolve_embedding_capabilities,
)


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
