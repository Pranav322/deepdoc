from __future__ import annotations

from types import SimpleNamespace

from deepdoc.chatbot.providers import LiteLLMEmbeddingClient


class _FakeContextWindowError(Exception):
    pass


def test_embedding_client_splits_batches_on_context_window_error(monkeypatch) -> None:
    calls: list[list[str]] = []

    class _FakeLiteLLM:
        def embedding(self, **kwargs):
            batch = kwargs["input"]
            calls.append(list(batch))
            if len(batch) > 1:
                raise _FakeContextWindowError(
                    "AzureException ContextWindowExceededError - maximum context length exceeded"
                )
            return SimpleNamespace(data=[{"embedding": [float(len(batch[0]))]}])

    monkeypatch.setattr("deepdoc.chatbot.providers.prepare_litellm", lambda: _FakeLiteLLM())

    client = LiteLLMEmbeddingClient({"provider": "azure", "model": "azure/text-embedding-3-small", "batch_size": 24})
    vectors = client.embed(["alpha", "beta", "gamma"])

    assert vectors == [[5.0], [4.0], [5.0]]
    assert calls[0] == ["alpha", "beta", "gamma"]
    assert calls[1:] == [["alpha"], ["beta", "gamma"], ["beta"], ["gamma"]]


def test_embedding_client_trims_single_oversized_text_on_retry(monkeypatch) -> None:
    calls: list[str] = []

    class _FakeLiteLLM:
        def embedding(self, **kwargs):
            text = kwargs["input"][0]
            calls.append(text)
            if len(text) > 3000:
                raise _FakeContextWindowError(
                    "AzureException ContextWindowExceededError - maximum context length exceeded"
                )
            return SimpleNamespace(data=[{"embedding": [1.0, 2.0]}])

    monkeypatch.setattr("deepdoc.chatbot.providers.prepare_litellm", lambda: _FakeLiteLLM())

    client = LiteLLMEmbeddingClient({"provider": "azure", "model": "azure/text-embedding-3-small", "batch_size": 1})
    vectors = client.embed(["x" * 5000])

    assert vectors == [[1.0, 2.0]]
    assert len(calls) >= 2
    assert len(calls[-1]) < len(calls[0])
    assert calls[-1].endswith("... [truncated for embedding]")
