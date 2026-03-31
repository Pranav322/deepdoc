"""Compatibility helpers for LiteLLM integration."""

from __future__ import annotations

from typing import Any

_PATCH_ATTR = "_codewiki_none_safe_api_base_patch"


def patch_litellm_logging(litellm_logging: Any) -> None:
    """Make LiteLLM logging tolerant of api_base=None."""
    logging_cls = getattr(litellm_logging, "Logging", None)
    if logging_cls is None or getattr(logging_cls, _PATCH_ATTR, False):
        return

    original = logging_cls._get_masked_api_base

    def _get_masked_api_base(self, api_base: Any) -> str:
        return original(self, api_base or "")

    logging_cls._get_masked_api_base = _get_masked_api_base
    setattr(logging_cls, _PATCH_ATTR, True)


def prepare_litellm():
    """Import LiteLLM and apply local compatibility guards."""
    import litellm
    from litellm.litellm_core_utils import litellm_logging

    litellm.suppress_debug_info = True
    patch_litellm_logging(litellm_logging)
    return litellm
