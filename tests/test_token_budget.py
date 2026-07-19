from __future__ import annotations

from types import SimpleNamespace

import pytest

from deepdoc.llm.token_budget import (
    ModelCapabilityError,
    build_prompt_budget,
    count_message_tokens,
    resolve_completion_capabilities,
)


def test_known_model_uses_litellm_metadata(monkeypatch) -> None:
    fake = SimpleNamespace(
        get_model_info=lambda model: {
            "max_input_tokens": 128000,
            "max_output_tokens": 16384,
        }
    )
    monkeypatch.setattr("deepdoc.llm.token_budget.prepare_litellm", lambda: fake)

    result = resolve_completion_capabilities("gpt-known", {})

    assert result.context_window_tokens == 128000
    assert result.max_output_tokens == 16384
    assert result.source == "litellm"


def test_explicit_context_overrides_unknown_model(monkeypatch) -> None:
    monkeypatch.setattr(
        "deepdoc.llm.token_budget.prepare_litellm",
        lambda: SimpleNamespace(get_model_info=lambda model: (_ for _ in ()).throw(Exception())),
    )

    result = resolve_completion_capabilities(
        "azure/private-deployment",
        {"context_window_tokens": 64000, "output_reserve_tokens": 8000},
    )

    assert result.context_window_tokens == 64000
    assert result.source == "explicit_context"


def test_base_model_resolves_unknown_deployment(monkeypatch) -> None:
    fake = SimpleNamespace(
        get_model_info=lambda model: {
            "max_input_tokens": 32000,
            "max_output_tokens": 4096,
        }
        if model == "known-base"
        else (_ for _ in ()).throw(Exception())
    )
    monkeypatch.setattr("deepdoc.llm.token_budget.prepare_litellm", lambda: fake)

    result = resolve_completion_capabilities(
        "azure/private-deployment", {"base_model": "known-base"}
    )

    assert result.capability_model == "known-base"
    assert result.source == "litellm_base_model"


def test_unknown_model_without_override_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "deepdoc.llm.token_budget.prepare_litellm",
        lambda: SimpleNamespace(get_model_info=lambda model: (_ for _ in ()).throw(Exception())),
    )

    with pytest.raises(ModelCapabilityError, match="base_model"):
        resolve_completion_capabilities("azure/private-deployment", {})


def test_prompt_budget_uses_model_output_when_reserve_auto(monkeypatch) -> None:
    fake = SimpleNamespace(
        get_model_info=lambda model: {
            "max_input_tokens": 32000,
            "max_output_tokens": 4096,
        }
    )
    monkeypatch.setattr("deepdoc.llm.token_budget.prepare_litellm", lambda: fake)
    capabilities = resolve_completion_capabilities("known", {})

    budget = build_prompt_budget(capabilities, output_reserve_tokens="auto")

    assert budget.output_reserve_tokens == 4096
    assert budget.variable_input_tokens < 32000 - 4096


def test_token_count_uses_litellm_messages(monkeypatch) -> None:
    fake = SimpleNamespace(
        token_counter=lambda **kwargs: 42,
        get_model_info=lambda model: {
            "max_input_tokens": 32000,
            "max_output_tokens": 4096,
        },
    )
    monkeypatch.setattr("deepdoc.llm.token_budget.prepare_litellm", lambda: fake)
    capabilities = resolve_completion_capabilities("known", {})

    count, estimated = count_message_tokens("system", "user", capabilities)

    assert count == 42
    assert estimated is False
