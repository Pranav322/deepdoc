from __future__ import annotations

from deepdoc.chatbot.embeddings import (
    _effective_fastembed_batch_size,
    _fastembed_cache_dir,
    _trim_fastembed_text,
    get_embeddings,
)


def test_fastembed_long_context_models_are_not_hard_trimmed() -> None:
    text = "x" * 5000

    assert _trim_fastembed_text(text, "nomic-ai/nomic-embed-text-v1.5") == text


def test_empty_embeddings_shape_tracks_backend_dimension() -> None:
    arr = get_embeddings(
        [], backend="fastembed", model="nomic-ai/nomic-embed-text-v1.5"
    )

    if hasattr(arr, "shape"):
        assert arr.shape == (0, 768)
    else:
        assert arr == []


def test_fastembed_batch_size_is_clamped_for_long_nomic_code_chunks() -> None:
    texts = ["x" * 3500, "y" * 1800, "z" * 1200]

    effective = _effective_fastembed_batch_size(
        texts,
        "nomic-ai/nomic-embed-text-v1.5",
        32,
    )

    assert effective == 4


def test_fastembed_batch_size_keeps_small_requested_values() -> None:
    texts = ["short chunk", "another short chunk"]

    effective = _effective_fastembed_batch_size(
        texts,
        "nomic-ai/nomic-embed-text-v1.5",
        2,
    )

    assert effective == 2


def test_fastembed_cache_dir_defaults_to_user_cache(monkeypatch) -> None:
    monkeypatch.delenv("FASTEMBED_CACHE_PATH", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    cache_dir = _fastembed_cache_dir()

    assert cache_dir.name == "fastembed"
    assert ".cache" in str(cache_dir)


def test_fastembed_cache_dir_respects_explicit_env(monkeypatch) -> None:
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", "/tmp/custom-fastembed-cache")

    cache_dir = _fastembed_cache_dir()

    assert str(cache_dir) == "/tmp/custom-fastembed-cache"
