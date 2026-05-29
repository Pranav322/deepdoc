"""Regression tests for transient-LLM-error classification.

Guards the bug where an Azure HTTP 500 (``litellm.APIError`` with the message
"The server had an error while processing your request") was mis-classified as
fatal and permanently stubbed a page on the first failure (retries: 0).
"""

from __future__ import annotations

from deepdoc.llm import is_retryable_llm_error


class APIError(Exception):
    """Stand-in for ``litellm.APIError`` — matched by class name."""


class AuthenticationError(Exception):
    """Stand-in for ``litellm.AuthenticationError``."""


class RateLimitError(Exception):
    """Stand-in for ``litellm.RateLimitError``."""


def _wrap(exc: Exception) -> RuntimeError:
    """Mirror LLMClient.complete, which raises ``RuntimeError(...) from e``."""
    try:
        raise exc
    except Exception as inner:  # noqa: BLE001
        return RuntimeError(f"LLM request failed: {inner}")  # __context__ set


def _wrap_from(exc: Exception) -> RuntimeError:
    try:
        raise exc
    except Exception as inner:  # noqa: BLE001
        new = RuntimeError(f"LLM request failed: {inner}")
        new.__cause__ = inner
        return new


# ── The exact observed failure ───────────────────────────────────────────────

AZURE_500_MSG = (
    "LLM request failed: litellm.APIError: AzureException APIError - "
    "The server had an error while processing your request. Sorry about that!"
)


def test_azure_500_message_is_retryable():
    assert is_retryable_llm_error(AZURE_500_MSG) is True


def test_azure_500_wrapped_apierror_is_retryable():
    # Type-name classification along the exception chain.
    assert is_retryable_llm_error(_wrap_from(APIError("server had an error"))) is True
    assert is_retryable_llm_error(_wrap(APIError("server had an error"))) is True


def test_bare_apierror_type_is_retryable():
    assert is_retryable_llm_error(APIError("anything")) is True


# ── Other transient cases still retry ────────────────────────────────────────


def test_rate_limit_type_and_message_retry():
    assert is_retryable_llm_error(RateLimitError("slow down")) is True
    assert is_retryable_llm_error("429 Too Many Requests") is True


def test_classic_5xx_messages_retry():
    for msg in ("503 Service Unavailable", "502 Bad Gateway", "request timed out"):
        assert is_retryable_llm_error(msg) is True


# ── Fatal errors must NOT retry ──────────────────────────────────────────────


def test_auth_error_type_not_retryable():
    assert is_retryable_llm_error(AuthenticationError("invalid api key")) is False


def test_auth_error_wins_over_chain():
    # Even wrapped, an authentication failure must stay fatal.
    assert is_retryable_llm_error(_wrap_from(AuthenticationError("bad key"))) is False


def test_invalid_model_message_not_retryable():
    assert is_retryable_llm_error("model_not_found: no such model gpt-99") is False
