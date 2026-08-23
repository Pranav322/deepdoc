from __future__ import annotations

from types import SimpleNamespace

import pytest

from deepdoc.llm.token_budget import (
    ModelCapabilityError,
    build_prompt_budget,
    count_message_tokens,
    fit_prompt_sections,
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


def test_unknown_model_falls_back_to_defaults(monkeypatch, recwarn) -> None:
    # An unknown model alias no longer hard-fails; it assumes conservative
    # defaults so non-expert users aren't blocked, and warns loudly instead.
    monkeypatch.setattr(
        "deepdoc.llm.token_budget.prepare_litellm",
        lambda: SimpleNamespace(get_model_info=lambda model: (_ for _ in ()).throw(Exception())),
    )

    from deepdoc.llm.token_budget import (
        DEFAULT_FALLBACK_CONTEXT_TOKENS,
        DEFAULT_FALLBACK_OUTPUT_RESERVE_TOKENS,
    )

    result = resolve_completion_capabilities("azure/private-deployment", {})
    assert result.source == "fallback_default"
    assert result.context_window_tokens == DEFAULT_FALLBACK_CONTEXT_TOKENS
    assert result.max_output_tokens == DEFAULT_FALLBACK_OUTPUT_RESERVE_TOKENS
    assert any("context window" in str(w.message) for w in recwarn.list)

    # Explicit config still wins and silences the fallback.
    explicit = resolve_completion_capabilities(
        "azure/private-deployment", {"context_window_tokens": 64000}
    )
    assert explicit.context_window_tokens == 64000
    assert explicit.source == "explicit_context"


def test_prompt_budget_uses_model_output_when_reserve_auto(monkeypatch) -> None:
    fake = SimpleNamespace(
        get_model_info=lambda model: {
            "max_input_tokens": 32000,
            "max_output_tokens": 4096,
        }
    )
    monkeypatch.setattr("deepdoc.llm.token_budget.prepare_litellm", lambda: fake)
    capabilities = resolve_completion_capabilities("fit-model", {})

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
    capabilities = resolve_completion_capabilities("fit-model", {})

    count, estimated = count_message_tokens("system", "user", capabilities)

    assert count == 42
    assert estimated is False


def test_prompt_fitter_preserves_required_sections_and_omits_whole_records(monkeypatch) -> None:
    fake = SimpleNamespace(
        get_model_info=lambda model: {
            "max_input_tokens": 400,
            "max_output_tokens": 20,
        },
        token_counter=lambda **kwargs: len(
            (
                kwargs.get("text")
                or " ".join(message["content"] for message in kwargs["messages"])
            ).split()
        ),
    )
    monkeypatch.setattr("deepdoc.llm.token_budget.prepare_litellm", lambda: fake)
    capabilities = resolve_completion_capabilities("prompt-fit-model", {})

    result = fit_prompt_sections(
        capabilities,
        system="system",
        render_prompt=lambda sections: (
            f"required={sections['required']}\noptional={sections.get('optional', '')}"
        ),
        required_sections={"required": "must keep"},
        optional_sections=[
            ("optional", ["one " * 100, "two " * 100, "three " * 100]),
        ],
        output_reserve_tokens=20,
        step_name="test",
    )

    assert "must keep" in result.prompt
    assert result.omitted_records["optional"] >= 1
    assert "one one" in result.prompt


def test_prompt_fitter_rejects_required_inventory_that_cannot_fit(monkeypatch) -> None:
    fake = SimpleNamespace(
        get_model_info=lambda model: {
            "max_input_tokens": 300,
            "max_output_tokens": 20,
        },
        token_counter=lambda **kwargs: len(
            (
                kwargs.get("text")
                or " ".join(message["content"] for message in kwargs["messages"])
            ).split()
        ),
    )
    monkeypatch.setattr("deepdoc.llm.token_budget.prepare_litellm", lambda: fake)
    capabilities = resolve_completion_capabilities("required-overflow-model", {})

    with pytest.raises(ModelCapabilityError, match="required inventory"):
        fit_prompt_sections(
            capabilities,
            system="system",
            render_prompt=lambda sections: sections["required"],
            required_sections={"required": "word " * 30},
            optional_sections=[],
            output_reserve_tokens=20,
            step_name="test",
        )


def test_prompt_fitter_guarantees_fit_when_tokenizer_is_non_additive(monkeypatch) -> None:
    """Real tokenizers add per-line/separator overhead that grows with the number of
    joined records — sum-of-record estimates can undercount this. The fitter must
    trim back down to the real budget after the exact recount, not just report it."""

    def token_counter(**kwargs):
        text = kwargs.get("text")
        if text is not None:
            return len(text.split())
        joined = " ".join(m["content"] for m in kwargs["messages"])
        # Non-additive overhead: grows with the number of newline-joined records,
        # which per-record standalone counts (count_text_tokens) cannot see.
        lines = joined.count("\n") + 1
        return len(joined.split()) + lines * 50

    fake = SimpleNamespace(
        get_model_info=lambda model: {
            "max_input_tokens": 500,
            "max_output_tokens": 20,
        },
        token_counter=token_counter,
    )
    monkeypatch.setattr("deepdoc.llm.token_budget.prepare_litellm", lambda: fake)
    capabilities = resolve_completion_capabilities("non-additive-model", {})

    result = fit_prompt_sections(
        capabilities,
        system="system",
        render_prompt=lambda sections: (
            f"required={sections['required']}\noptional={sections.get('optional', '')}"
        ),
        required_sections={"required": "must keep"},
        optional_sections=[
            ("optional", ["word " * 30 for _ in range(10)]),
        ],
        output_reserve_tokens=20,
        step_name="test",
    )

    budget = build_prompt_budget(capabilities, output_reserve_tokens=20)
    maximum_input = (
        budget.context_window_tokens - budget.output_reserve_tokens - budget.safety_tokens
    )
    assert result.input_tokens <= maximum_input
    assert result.omitted_records["optional"] >= 1
    assert "must keep" in result.prompt


def test_planner_endpoint_formatter_keeps_every_endpoint() -> None:
    from deepdoc.planner.utils import _format_endpoints

    endpoints = [
        {
            "method": "GET",
            "path": f"/resource/{index}",
            "handler": f"handler_{index}",
            "file": "routes.py",
            "line": index,
        }
        for index in range(60)
    ]

    rendered = _format_endpoints(endpoints)

    assert len(rendered.splitlines()) == 60
    assert "more endpoints" not in rendered
