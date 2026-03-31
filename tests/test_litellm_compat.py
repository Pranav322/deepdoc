from __future__ import annotations

from types import SimpleNamespace

from deepdoc.llm.litellm_compat import patch_litellm_logging


def test_patch_litellm_logging_handles_none_api_base() -> None:
    class FakeLogging:
        def _get_masked_api_base(self, api_base: str) -> str:
            if "key=" in api_base:
                return "masked"
            return str(api_base)

    fake_module = SimpleNamespace(Logging=FakeLogging)

    patch_litellm_logging(fake_module)

    logger = FakeLogging()
    assert logger._get_masked_api_base(None) == ""


def test_patch_litellm_logging_is_idempotent() -> None:
    calls: list[str] = []

    class FakeLogging:
        def _get_masked_api_base(self, api_base: str) -> str:
            calls.append(str(api_base))
            return str(api_base)

    fake_module = SimpleNamespace(Logging=FakeLogging)

    patch_litellm_logging(fake_module)
    patch_litellm_logging(fake_module)

    logger = FakeLogging()
    assert logger._get_masked_api_base("https://example.com") == "https://example.com"
    assert calls == ["https://example.com"]
