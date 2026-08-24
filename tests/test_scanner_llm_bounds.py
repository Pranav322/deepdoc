"""Phase-2 scanner LLM calls must fit the model's real token budget.

`cluster_giant_file` and `_normalize_integrations_llm` used to build an
unbounded (or fixed-`[:80]`-capped) prompt and hand it straight to
`llm.complete`. These tests prove both now use `fit_prompt_sections` so the
actual rendered prompt sent to the model never exceeds its budget, that
small inputs are unaffected, and that omitted-record counts are surfaced.
"""

from __future__ import annotations

import json

from deepdoc.llm.token_budget import ModelCapabilities, count_message_tokens
from deepdoc.parser.base import ParsedFile, Symbol
from deepdoc.scanner.clustering import cluster_giant_file
from deepdoc.scanner.common import IntegrationCandidate
from pathlib import Path

from deepdoc.scanner.integrations import _normalize_integrations_llm


class _RecordingLLM:
    """Fake LLMClient: records every (system, prompt) pair and asserts each
    one fits the real token budget before returning a canned response."""

    def __init__(self, context_window_tokens: int, output_reserve_tokens: int, response: str):
        self.capabilities = ModelCapabilities(
            model="test",
            capability_model="gpt-4o-mini",
            context_window_tokens=context_window_tokens,
            max_output_tokens=min(output_reserve_tokens, 4096),
            source="test",
        )
        self.output_reserve_tokens = output_reserve_tokens
        self._response = response
        self.calls: list[tuple[str, str, int]] = []

    def complete(self, system: str, prompt: str) -> str:
        tokens, _ = count_message_tokens(system, prompt, self.capabilities)
        self.calls.append((system, prompt, tokens))
        return self._response

    def max_input_tokens(self) -> int:
        from deepdoc.llm.token_budget import build_prompt_budget

        budget = build_prompt_budget(self.capabilities, output_reserve_tokens=self.output_reserve_tokens)
        return budget.context_window_tokens - budget.output_reserve_tokens - budget.safety_tokens


def _symbol(name: str, i: int) -> Symbol:
    return Symbol(
        name=name,
        kind="function",
        signature=f"def {name}(request, context_{i}, payload_{i}):",
        docstring=f"Handles {name} for workflow number {i} with extended documentation text.",
        body_preview=f"    validate(payload_{i})\n    return process_{name}(context_{i})",
        start_line=i * 10 + 1,
        end_line=i * 10 + 8,
    )


def test_cluster_giant_file_small_input_includes_every_symbol_unbounded_budget() -> None:
    symbols = [_symbol(f"handle_case_{i}", i) for i in range(5)]
    parsed = ParsedFile(path="big.py", language="python", symbols=symbols, imports=["os", "json"])
    response = json.dumps({"clusters": [{"cluster_name": "core", "symbols": [s.name for s in symbols]}]})
    llm = _RecordingLLM(context_window_tokens=128000, output_reserve_tokens=16000, response=response)

    analysis = cluster_giant_file("big.py", parsed, "\n" * 200, llm)

    assert len(llm.calls) == 1
    _, prompt, tokens = llm.calls[0]
    assert tokens <= llm.max_input_tokens()
    for s in symbols:
        assert s.name in prompt
    assert analysis.total_symbols == 5
    assert sum(len(c.symbols) for c in analysis.clusters) == 5


def test_cluster_giant_file_bounds_prompt_under_tiny_budget_and_reports_omissions(capsys) -> None:
    # Enough symbols, each with signature/docstring/preview, that the full
    # inventory would blow a small budget if sent unbounded.
    symbols = [_symbol(f"handle_case_{i:03d}", i) for i in range(400)]
    parsed = ParsedFile(path="big.py", language="python", symbols=symbols, imports=[f"pkg_{i}" for i in range(30)])
    response = json.dumps({"clusters": [{"cluster_name": "core", "symbols": ["handle_case_000"]}]})
    llm = _RecordingLLM(context_window_tokens=2500, output_reserve_tokens=200, response=response)

    analysis = cluster_giant_file("big.py", parsed, "\n" * 5000, llm)

    assert len(llm.calls) == 1, "must not fall back to heuristic just because it's large — it should fit and send once"
    _, prompt, tokens = llm.calls[0]
    assert tokens <= llm.max_input_tokens()
    # Proves real bounding happened, not "got lucky": not every symbol fits.
    assert not all(s.name in prompt for s in symbols)
    assert analysis.total_symbols == 400
    captured = capsys.readouterr()
    assert "omitted" in captured.out


def test_normalize_integrations_small_input_unbounded_budget() -> None:
    candidates = [
        IntegrationCandidate(signal_type="sdk_import", name_hint="vinculum", file_path=f"f{i}.py", evidence=f"import vinculum_{i}")
        for i in range(5)
    ]
    response = json.dumps(
        {
            "integrations": [
                {
                    "name": "vinculum",
                    "display_name": "Vinculum",
                    "description": "d",
                    "is_substantial": True,
                    "candidate_indices": list(range(5)),
                }
            ]
        }
    )
    llm = _RecordingLLM(context_window_tokens=128000, output_reserve_tokens=16000, response=response)

    identities = _normalize_integrations_llm(candidates, llm, repo_root=Path('.'))

    assert len(llm.calls) == 1
    _, prompt, tokens = llm.calls[0]
    assert tokens <= llm.max_input_tokens()
    for c in candidates:
        assert c.file_path in prompt
    assert identities[0].files == [f"f{i}.py" for i in range(5)]


def test_normalize_integrations_bounds_prompt_under_tiny_budget_and_index_mapping_stays_correct(capsys) -> None:
    candidates = [
        IntegrationCandidate(
            signal_type="env_var",
            name_hint=f"service_{i}",
            file_path=f"services/service_{i:03d}/client.py",
            evidence=f"SERVICE_{i}_API_KEY = os.environ['SERVICE_{i}_API_KEY']",
        )
        for i in range(300)
    ]
    # The LLM only ever sees whatever prefix fit — index 0 unambiguously maps
    # to candidates[0] regardless of how many later ones were omitted.
    response = json.dumps(
        {
            "integrations": [
                {
                    "name": "service_0",
                    "display_name": "Service 0",
                    "description": "d",
                    "is_substantial": True,
                    "candidate_indices": [0],
                }
            ]
        }
    )
    llm = _RecordingLLM(context_window_tokens=2000, output_reserve_tokens=150, response=response)

    identities = _normalize_integrations_llm(candidates, llm, repo_root=Path('.'))

    assert len(llm.calls) == 1
    _, prompt, tokens = llm.calls[0]
    assert tokens <= llm.max_input_tokens()
    assert not all(c.file_path in prompt for c in candidates)
    assert identities[0].files == ["services/service_000/client.py"]
    captured = capsys.readouterr()
    assert "omitted" in captured.out


def test_normalize_integrations_preserves_original_indices_when_earlier_record_is_omitted() -> None:
    candidates = [
        IntegrationCandidate(
            signal_type="sdk_import",
            name_hint="oversized_first",
            file_path="services/oversized/client.py",
            evidence=" ".join(f"huge_evidence_token_{i}" for i in range(2500)),
        ),
        IntegrationCandidate(
            signal_type="sdk_import",
            name_hint="small_second",
            file_path="services/small/client.py",
            evidence="import small_second",
        ),
    ]
    response = json.dumps(
        {
            "integrations": [
                {
                    "name": "small_second",
                    "display_name": "Small Second",
                    "description": "d",
                    "is_substantial": False,
                    "candidate_indices": [1],
                }
            ]
        }
    )
    llm = _RecordingLLM(
        context_window_tokens=1800,
        output_reserve_tokens=150,
        response=response,
    )

    identities = _normalize_integrations_llm(candidates, llm, repo_root=Path("."))

    assert "candidate_index=1" in llm.calls[0][1]
    assert "candidate_index=0" not in llm.calls[0][1]
    assert identities[0].files == ["services/small/client.py"]
