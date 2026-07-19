from __future__ import annotations

from types import SimpleNamespace

import pytest

from deepdoc.llm import ModelCapabilityError
from deepdoc.chatbot.embedding_capabilities import EmbeddingCapabilityError
from deepdoc.chatbot.providers import LiteLLMChatClient, LiteLLMEmbeddingClient


class _FakeContextWindowError(Exception):
    pass


def test_chat_client_clamps_output_and_rejects_oversized_prompt(monkeypatch) -> None:
    completion_calls = []

    class _FakeLiteLLM:
        def get_model_info(self, model):
            return {"max_input_tokens": 4096, "max_output_tokens": 1024}

        def token_counter(self, **kwargs):
            text = " ".join(message["content"] for message in kwargs["messages"])
            return len(text.split())

        def completion(self, **kwargs):
            completion_calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
            )

    monkeypatch.setattr(
        "deepdoc.chatbot.providers.prepare_litellm", lambda: _FakeLiteLLM()
    )
    monkeypatch.setattr(
        "deepdoc.llm.token_budget.prepare_litellm", lambda: _FakeLiteLLM()
    )
    client = LiteLLMChatClient(
        {
            "provider": "openai",
            "model": "chat-test",
            "context_window_tokens": 4096,
            "output_reserve_tokens": 1024,
            "max_tokens": 5000,
        }
    )

    assert client.max_tokens == 1024
    with pytest.raises(ModelCapabilityError, match="resolved answer-model context window"):
        client.complete("system", "word " * 4000)

    assert completion_calls == []


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

    client = LiteLLMEmbeddingClient({"provider": "azure", "model": "azure/text-embedding-3-small", "batch_size": 24, "max_input_tokens": 8191})
    vectors = client.embed(["alpha", "beta", "gamma"])

    assert vectors == [[5.0], [4.0], [5.0]]
    assert calls[0] == ["alpha", "beta", "gamma"]
    assert calls[1:] == [["alpha"], ["beta", "gamma"], ["beta"], ["gamma"]]


def test_embedding_client_rejects_fitted_singleton_context_error(monkeypatch) -> None:
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

    client = LiteLLMEmbeddingClient({"provider": "azure", "model": "azure/text-embedding-3-small", "batch_size": 1, "max_input_tokens": 8191})
    with pytest.raises(EmbeddingCapabilityError, match="token-fitted"):
        client.embed(["x" * 5000])

    assert calls == ["x" * 5000]


def test_embedding_client_handles_azure_maximum_input_length_error(monkeypatch) -> None:
    calls: list[list[str]] = []

    class _FakeLiteLLM:
        def embedding(self, **kwargs):
            batch = kwargs["input"]
            calls.append(list(batch))
            if len(batch) > 1:
                raise _FakeContextWindowError(
                    "AzureException BadRequestError - {"
                    "\"error\": {\"message\": \"Invalid 'input[11]': "
                    "maximum input length is 8192 tokens.\"}}"
                )
            return SimpleNamespace(data=[{"embedding": [float(len(batch[0]))]}])

    monkeypatch.setattr("deepdoc.chatbot.providers.prepare_litellm", lambda: _FakeLiteLLM())

    client = LiteLLMEmbeddingClient(
        {"provider": "azure", "model": "azure/text-embedding-3-small", "batch_size": 24, "max_input_tokens": 8191}
    )
    vectors = client.embed(["alpha", "beta", "gamma"])

    assert vectors == [[5.0], [4.0], [5.0]]
    assert calls[0] == ["alpha", "beta", "gamma"]
    assert calls[1:] == [["alpha"], ["beta", "gamma"], ["beta"], ["gamma"]]


def test_embedding_client_defaults_to_single_item_batches_for_azure() -> None:
    client = LiteLLMEmbeddingClient({"provider": "azure", "model": "azure/text-embedding-3-small"})

    assert client.batch_size == 1


def test_embedding_client_defaults_to_single_item_batches_for_azure_model() -> None:
    client = LiteLLMEmbeddingClient({"model": "azure/text-embedding-3-small"})

    assert client.batch_size == 1


def test_embedding_client_defaults_to_single_item_batches_for_azure_with_profile() -> None:
    client = LiteLLMEmbeddingClient({"provider": "azure", "model": "azure/text-embedding-3-small", "max_input_tokens": 8191})

    assert client.batch_size == 1
