"""Shared classification of transient (retryable) LLM errors.

`LLMClient.complete` wraps the underlying provider failure in a
`RuntimeError(... ) from e`, so the original litellm/openai exception type is
preserved on the exception chain (`__cause__`/`__context__`) even though the
top-level type is generic. This helper classifies by exception *class name*
along that chain — robust against message wording — and falls back to
substring markers when only a message string is available.

HTTP 500 / generic "the server had an error" responses are treated as
transient: they are the most common provider blip and were previously
mis-classified as fatal, permanently stubbing pages on the first failure.
"""

from __future__ import annotations

# litellm/openai exception class names that represent transient failures.
# Matched by exact class name (not isinstance) so that 4xx subclasses of the
# broad ``APIError`` base do not get swept in as retryable.
_RETRYABLE_TYPE_NAMES = frozenset(
    {
        "APIError",
        "APIConnectionError",
        "InternalServerError",
        "ServiceUnavailableError",
        "Timeout",
        "APITimeoutError",
        "RateLimitError",
    }
)

# Definitively fatal types — never retry, even if they appear alongside a
# broad type on the chain.
_NON_RETRYABLE_TYPE_NAMES = frozenset(
    {
        "AuthenticationError",
        "PermissionDeniedError",
        "BadRequestError",
        "InvalidRequestError",
        "NotFoundError",
        "UnprocessableEntityError",
        "ContentPolicyViolationError",
    }
)

# Substring markers for the message-only fallback path. Includes HTTP 500 and
# the generic Azure/OpenAI 500 phrasing, which contain none of the prior
# 502/503/504 markers.
_TRANSIENT_MARKERS = (
    "rate",
    "429",
    "500",
    "overloaded",
    "timeout",
    "timed out",
    "502",
    "503",
    "504",
    "bad gateway",
    "service unavailable",
    "internal server error",
    "had an error",
    "please try again",
    "apierror",
    "apiconnectionerror",
    "connection",
    "temporary",
    "throttl",
    "capacity",
    "server_error",
    "internal_error",
)


def _matches_transient_marker(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in _TRANSIENT_MARKERS)


def is_retryable_llm_error(error: object) -> bool:
    """Return True if an LLM error is transient and worth retrying.

    Accepts either an exception instance or an error message string.
    """
    if isinstance(error, BaseException):
        seen: set[int] = set()
        exc: BaseException | None = error
        saw_retryable_type = False
        while exc is not None and id(exc) not in seen:
            seen.add(id(exc))
            name = type(exc).__name__
            if name in _NON_RETRYABLE_TYPE_NAMES:
                return False
            if name in _RETRYABLE_TYPE_NAMES:
                saw_retryable_type = True
            exc = exc.__cause__ or exc.__context__
        if saw_retryable_type:
            return True
        return _matches_transient_marker(str(error))
    return _matches_transient_marker(str(error))
