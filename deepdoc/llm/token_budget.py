"""LiteLLM-first model capabilities and prompt token budgeting."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
from collections.abc import Callable
from typing import Any

from .litellm_compat import prepare_litellm


class ModelCapabilityError(ValueError):
    """DeepDoc cannot safely resolve a model's prompt capacity."""


@dataclass(frozen=True)
class ModelCapabilities:
    """Locally resolved completion-model capabilities."""

    model: str
    capability_model: str
    context_window_tokens: int
    max_output_tokens: int | None
    source: str


@dataclass(frozen=True)
class PromptBudget:
    """Token envelope available to one completion operation."""

    context_window_tokens: int
    output_reserve_tokens: int
    safety_tokens: int
    fixed_prompt_tokens: int
    variable_input_tokens: int


@dataclass(frozen=True)
class PromptFitResult:
    """A complete prompt fitted from required and optional whole records."""

    prompt: str
    sections: dict[str, str]
    input_tokens: int
    tokens_estimated: bool
    omitted_records: dict[str, int]


def _configured_token_value(value: Any, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {"", "auto", "none", "null"}:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ModelCapabilityError(
            f"{name} must be a positive integer or 'auto'."
        ) from exc
    if parsed <= 0:
        raise ModelCapabilityError(
            f"{name} must be a positive integer or 'auto'."
        )
    return parsed


@lru_cache(maxsize=128)
def _litellm_model_info(model: str) -> dict[str, Any] | None:
    """Read LiteLLM's bundled model metadata without making a provider request."""
    if not model:
        return None
    try:
        info = prepare_litellm().get_model_info(model)
    except Exception:
        return None
    return dict(info) if isinstance(info, dict) else None


def resolve_completion_capabilities(
    model: str,
    config: dict[str, Any] | None = None,
    *,
    config_prefix: str = "llm",
) -> ModelCapabilities:
    """Resolve completion capabilities from config, LiteLLM, or a base model."""
    config = config or {}
    model = str(model or "").strip()
    base_model = str(config.get("base_model") or "").strip()
    explicit_context = _configured_token_value(
        config.get("context_window_tokens"), "context_window_tokens"
    )
    explicit_output = _configured_token_value(
        config.get("max_output_tokens"), "max_output_tokens"
    )

    metadata_model = base_model or model
    info = _litellm_model_info(metadata_model)
    metadata_context = _configured_token_value(
        (info or {}).get("max_input_tokens"), "LiteLLM max_input_tokens"
    )
    metadata_output = _configured_token_value(
        (info or {}).get("max_output_tokens"), "LiteLLM max_output_tokens"
    )

    context_window = explicit_context or metadata_context
    if context_window is None:
        raise ModelCapabilityError(
            f"Could not resolve the context window for model {model!r}. "
            f"Set {config_prefix}.base_model to a LiteLLM-known model or set "
            f"{config_prefix}.context_window_tokens explicitly."
        )

    max_output = explicit_output or metadata_output
    if max_output is not None:
        max_output = min(max_output, context_window)
    if explicit_context and explicit_output:
        source = "explicit"
    elif explicit_context:
        source = "explicit_context"
    elif base_model:
        source = "litellm_base_model"
    else:
        source = "litellm"
    return ModelCapabilities(
        model=model,
        capability_model=metadata_model,
        context_window_tokens=context_window,
        max_output_tokens=max_output,
        source=source,
    )


def count_text_tokens(text: str, capabilities: ModelCapabilities) -> tuple[int, bool]:
    """Count model tokens locally, with a conservative no-network fallback."""
    if not text:
        return 0, False
    try:
        count = prepare_litellm().token_counter(
            model=capabilities.capability_model,
            text=text,
        )
        return max(1, int(count)), False
    except Exception:
        return max(1, math.ceil(len(text) / 3)), True


def count_message_tokens(
    system: str,
    user: str,
    capabilities: ModelCapabilities,
) -> tuple[int, bool]:
    """Count a two-message completion request using LiteLLM's local tokenizer."""
    messages = [
        {"role": "system", "content": system or ""},
        {"role": "user", "content": user or ""},
    ]
    try:
        count = prepare_litellm().token_counter(
            model=capabilities.capability_model,
            messages=messages,
        )
        return max(1, int(count)), False
    except Exception:
        text_tokens, _ = count_text_tokens(
            (system or "") + "\n" + (user or ""), capabilities
        )
        return text_tokens + 8, True


def build_prompt_budget(
    capabilities: ModelCapabilities,
    *,
    output_reserve_tokens: Any = None,
    fixed_prompt_tokens: int = 0,
    safety_fraction: float = 0.05,
) -> PromptBudget:
    """Build one operation budget from resolved model capability."""
    configured_reserve = _configured_token_value(
        output_reserve_tokens, "output_reserve_tokens"
    )
    if configured_reserve is not None:
        reserve = configured_reserve
    elif capabilities.max_output_tokens is not None:
        reserve = capabilities.max_output_tokens
    else:
        raise ModelCapabilityError(
            f"Could not resolve an output reserve for model {capabilities.model!r}. "
            "Set output_reserve_tokens explicitly."
        )
    reserve = min(reserve, capabilities.context_window_tokens // 2)
    safety = max(256, int(capabilities.context_window_tokens * safety_fraction))
    variable = capabilities.context_window_tokens - reserve - safety - max(
        0, int(fixed_prompt_tokens)
    )
    if variable <= 0:
        raise ModelCapabilityError(
            "The configured output reserve and fixed prompt leave no input-token budget."
        )
    return PromptBudget(
        context_window_tokens=capabilities.context_window_tokens,
        output_reserve_tokens=reserve,
        safety_tokens=safety,
        fixed_prompt_tokens=max(0, int(fixed_prompt_tokens)),
        variable_input_tokens=variable,
    )


def fit_prompt_sections(
    capabilities: ModelCapabilities,
    *,
    system: str,
    render_prompt: Callable[[dict[str, str]], str],
    required_sections: dict[str, str],
    optional_sections: list[tuple[str, list[str]]],
    output_reserve_tokens: Any = None,
    step_name: str,
) -> PromptFitResult:
    """Fit whole optional records while preserving every required prompt section."""
    budget = build_prompt_budget(
        capabilities,
        output_reserve_tokens=output_reserve_tokens,
    )
    maximum_input = (
        budget.context_window_tokens
        - budget.output_reserve_tokens
        - budget.safety_tokens
    )
    sections = dict(required_sections)
    prompt = render_prompt(sections)
    input_tokens, estimated = count_message_tokens(system, prompt, capabilities)
    if input_tokens > maximum_input:
        raise ModelCapabilityError(
            f"{step_name} required inventory exceeds the resolved model budget "
            f"({input_tokens:,} input tokens > {maximum_input:,} available). "
            "Increase llm.context_window_tokens, reduce llm.output_reserve_tokens, "
            "or choose a model with a larger context window."
        )

    omitted: dict[str, int] = {}
    for name, records in optional_sections:
        accepted: list[str] = []
        for record in records:
            candidate = dict(sections)
            candidate[name] = "\n".join([*accepted, record])
            candidate_prompt = render_prompt(candidate)
            candidate_tokens, candidate_estimated = count_message_tokens(
                system, candidate_prompt, capabilities
            )
            if candidate_tokens <= maximum_input:
                sections = candidate
                prompt = candidate_prompt
                input_tokens = candidate_tokens
                estimated = estimated or candidate_estimated
                accepted.append(record)
            else:
                omitted[name] = omitted.get(name, 0) + 1
        sections.setdefault(name, "")
    return PromptFitResult(
        prompt=prompt,
        sections=sections,
        input_tokens=input_tokens,
        tokens_estimated=estimated,
        omitted_records=omitted,
    )
