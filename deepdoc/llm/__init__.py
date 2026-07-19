"""LLM client — thin wrapper around LiteLLM for multi-provider support."""

from .client import LLMClient, LLMOutputTruncatedError
from .retry import is_retryable_llm_error
from .token_budget import (
    ModelCapabilities,
    ModelCapabilityError,
    PromptBudget,
    PromptFitResult,
    build_prompt_budget,
    count_message_tokens,
    count_text_tokens,
    fit_prompt_sections,
    resolve_completion_capabilities,
)

__all__ = [
    "LLMClient",
    "LLMOutputTruncatedError",
    "ModelCapabilities",
    "ModelCapabilityError",
    "PromptBudget",
    "PromptFitResult",
    "build_prompt_budget",
    "count_message_tokens",
    "count_text_tokens",
    "fit_prompt_sections",
    "is_retryable_llm_error",
    "resolve_completion_capabilities",
]
