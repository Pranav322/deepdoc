"""Tests for the MDX compile gate orchestrator and JSX-strip fallback.

These tests avoid spawning Node by overriding the ``validate`` callable
passed into ``apply_mdx_compile_gate``. A separate test exercises the
"node missing" branch of the validator wrapper.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import click
import pytest

from deepdoc.generator.mdx_compile_gate import (
    GateOutcome,
    _strip_jsx_to_markdown,
    apply_mdx_compile_gate,
)
from deepdoc.generator.mdx_validator import (
    MdxCompileError,
    ValidationOutcome,
    validate_mdx,
)

from .conftest import make_bucket


@dataclass
class _FakeLLM:
    """LLM stub that returns a queue of canned responses."""

    responses: list[str]

    def complete(self, system: str, user: str) -> str:  # noqa: ARG002
        if not self.responses:
            raise AssertionError("fake LLM ran out of canned responses")
        return self.responses.pop(0)


def _make_validator(verdicts: list[ValidationOutcome]) -> Callable[[str], ValidationOutcome]:
    """Return a stub validator that yields the supplied verdicts in order."""

    calls = {"i": 0}

    def stub(content: str) -> ValidationOutcome:  # noqa: ARG001
        idx = calls["i"]
        calls["i"] += 1
        if idx >= len(verdicts):
            # Default to ok=True so we never deadlock if the caller validates
            # one more time than the test expects.
            return ValidationOutcome(ok=True)
        return verdicts[idx]

    return stub


_GOOD_MDX = "---\ntitle: Test\n---\n\n# Hello\n\nSome content.\n"


def test_gate_happy_path_returns_content_unchanged() -> None:
    bucket = make_bucket("Test", "test", owned_files=[])
    outcome = apply_mdx_compile_gate(
        _GOOD_MDX,
        llm=None,
        bucket=bucket,
        validate=_make_validator([ValidationOutcome(ok=True)]),
    )
    assert outcome.content == _GOOD_MDX
    assert outcome.retries == 0
    assert outcome.fallback_applied is False
    assert outcome.compile_failed is False
    assert outcome.last_error is None


def test_gate_recovers_after_one_llm_retry() -> None:
    bucket = make_bucket("Test", "test", owned_files=[])
    fixed_content = _GOOD_MDX.replace("Hello", "Hello (fixed)")
    fake_llm = _FakeLLM(responses=[fixed_content])
    error = MdxCompileError(message="Unexpected `<` in text", line=4, column=1)
    verdicts = [
        ValidationOutcome(ok=False, error=error),  # initial check on input
        ValidationOutcome(ok=True),                # check after LLM fix
    ]
    outcome = apply_mdx_compile_gate(
        "broken content",
        llm=fake_llm,
        bucket=bucket,
        validate=_make_validator(verdicts),
    )
    assert outcome.content == fixed_content
    assert outcome.retries == 1
    assert outcome.fallback_applied is False
    assert outcome.compile_failed is False


def test_gate_exhausted_retries_apply_jsx_strip_fallback() -> None:
    bucket = make_bucket("Test", "test", owned_files=[])
    broken = (
        "---\ntitle: Boom\n---\n\n"
        '<Callout type="warn">Danger</Callout>\n'
    )
    fake_llm = _FakeLLM(responses=["still broken 1", "still broken 2"])
    error = MdxCompileError(message="cannot parse JSX", line=5)
    verdicts = [
        ValidationOutcome(ok=False, error=error),  # initial
        ValidationOutcome(ok=False, error=error),  # after retry 1
        ValidationOutcome(ok=False, error=error),  # after retry 2
    ]
    outcome = apply_mdx_compile_gate(
        broken,
        llm=fake_llm,
        bucket=bucket,
        max_retries=2,
        validate=_make_validator(verdicts),
    )
    assert outcome.retries == 2
    assert outcome.fallback_applied is True
    assert outcome.compile_failed is True
    assert outcome.last_error == error
    # Fallback banner should be present in the recovered content.
    assert "deepdoc: auto-recovered" in outcome.content


def test_gate_no_llm_skips_retries_and_falls_back() -> None:
    bucket = make_bucket("Test", "test", owned_files=[])
    broken = "<Callout>oops</Callout>"
    error = MdxCompileError(message="unclosed JSX", line=1)
    outcome = apply_mdx_compile_gate(
        broken,
        llm=None,
        bucket=bucket,
        validate=_make_validator([ValidationOutcome(ok=False, error=error)]),
    )
    assert outcome.retries == 0
    assert outcome.fallback_applied is True
    assert outcome.compile_failed is True


def test_strip_callout_to_gfm_alert() -> None:
    src = '<Callout type="warn">Danger here</Callout>'
    out = _strip_jsx_to_markdown(src)
    assert "> [!WARNING]" in out
    assert "> Danger here" in out


def test_strip_callout_default_type_is_note() -> None:
    src = "<Callout>Just a note</Callout>"
    out = _strip_jsx_to_markdown(src)
    assert "> [!NOTE]" in out


def test_strip_accordions_to_details() -> None:
    src = (
        "<Accordions>"
        '<Accordion title="Q1">A1 body</Accordion>'
        '<Accordion title="Q2">A2 body</Accordion>'
        "</Accordions>"
    )
    out = _strip_jsx_to_markdown(src)
    assert "<details>" in out
    assert "<summary>Q1</summary>" in out
    assert "<summary>Q2</summary>" in out
    # Wrapping <Accordions> tags must be removed entirely.
    assert "<Accordions" not in out and "</Accordions>" not in out


def test_strip_steps_to_ordered_list() -> None:
    src = (
        "<Steps>"
        "<Step>### First step\nDo this</Step>"
        "<Step>### Second step\nThen this</Step>"
        "</Steps>"
    )
    out = _strip_jsx_to_markdown(src)
    assert "1." in out and "2." in out
    assert "<Step" not in out and "<Steps" not in out


def test_strip_cards_to_link_list() -> None:
    src = (
        "<Cards>"
        '<Card title="Setup" href="/setup">Get started</Card>'
        '<Card title="Architecture" href="/arch" />'
        "</Cards>"
    )
    out = _strip_jsx_to_markdown(src)
    assert "[Setup](/setup) — Get started" in out
    assert "[Architecture](/arch)" in out


def test_strip_tabs_to_headed_sections() -> None:
    src = (
        "<Tabs>"
        '<Tab value="Node">node body</Tab>'
        '<Tab value="Python">python body</Tab>'
        "</Tabs>"
    )
    out = _strip_jsx_to_markdown(src)
    assert "**Node**" in out and "node body" in out
    assert "**Python**" in out and "python body" in out


def test_strip_banner_inserted_after_frontmatter() -> None:
    src = "---\ntitle: X\n---\n\nbody"
    out = _strip_jsx_to_markdown(src)
    lines = out.splitlines()
    # Frontmatter remains first.
    assert lines[0] == "---"
    assert lines[1] == "title: X"
    assert lines[2] == "---"
    # Banner sits immediately after the closing ---.
    assert "{/* deepdoc: auto-recovered" in out
    banner_idx = next(i for i, ln in enumerate(lines) if "deepdoc: auto-recovered" in ln)
    assert banner_idx == 3


def test_gate_fallback_also_fails_sets_flag() -> None:
    """When the JSX-strip fallback also fails to compile, fallback_also_failed is True
    and last_error reflects the fallback's compile error, not the original."""
    bucket = make_bucket("Test", "test", owned_files=[])
    original_error = MdxCompileError(message="unknown JSX component <Fancy>", line=5)
    fallback_error = MdxCompileError(message="stray brace expression {x}", line=3)
    verdicts = [
        ValidationOutcome(ok=False, error=original_error),  # initial check
        ValidationOutcome(ok=False, error=fallback_error),   # fallback check
    ]
    outcome = apply_mdx_compile_gate(
        "broken {x} content",
        llm=None,
        bucket=bucket,
        max_retries=0,
        validate=_make_validator(verdicts),
    )
    assert outcome.fallback_applied is True
    assert outcome.fallback_also_failed is True
    assert outcome.compile_failed is True
    assert outcome.last_error == fallback_error


def test_gate_fallback_passes_validation_not_flagged() -> None:
    """When the fallback compiles cleanly, fallback_also_failed is False."""
    bucket = make_bucket("Test", "test", owned_files=[])
    error = MdxCompileError(message="unclosed JSX", line=1)
    verdicts = [
        ValidationOutcome(ok=False, error=error),  # initial
        ValidationOutcome(ok=True),                # fallback check passes
    ]
    outcome = apply_mdx_compile_gate(
        "<Callout>broken</Callout>",
        llm=None,
        bucket=bucket,
        max_retries=0,
        validate=_make_validator(verdicts),
    )
    assert outcome.fallback_applied is True
    assert outcome.fallback_also_failed is False
    assert outcome.compile_failed is True


def test_ensure_node_available_raises_when_missing(monkeypatch) -> None:
    import shutil as _shutil
    from deepdoc.generator import mdx_validator

    monkeypatch.setattr(mdx_validator, "shutil", _shutil)
    monkeypatch.setattr(_shutil, "which", lambda _cmd: None)

    with pytest.raises(click.ClickException) as excinfo:
        mdx_validator.ensure_node_available()
    assert "Node 18+" in str(excinfo.value.message)


def test_validate_mdx_environment_failure_propagates_as_click(monkeypatch) -> None:
    """When Node is unavailable, validate_mdx should raise ClickException
    (an environment problem), not silently return ok=False."""
    import shutil as _shutil
    from deepdoc.generator import mdx_validator as v

    monkeypatch.setattr(v, "_BOOTSTRAP_DONE", False, raising=False)
    monkeypatch.setattr(v, "_NODE_MODULES", v._VALIDATOR_DIR / "_does_not_exist", raising=False)
    monkeypatch.setattr(_shutil, "which", lambda _cmd: None)

    with pytest.raises(click.ClickException):
        validate_mdx("anything")
