from __future__ import annotations

import json

from deepdoc.llm.json_utils import _repair_json_candidate, parse_llm_json
from deepdoc.planner import _llm_step
from deepdoc.scanner import _parse_json


class _StubLLM:
    def __init__(self, response: str):
        self._response = response

    def complete(self, system: str, prompt: str) -> str:
        return self._response


def test_parse_llm_json_extracts_json_from_wrapped_response() -> None:
    response = """Here is the result:

```json
{
  "buckets": [{"slug": "overview"}]
}
```

Thanks!
"""

    parsed = parse_llm_json(response)

    assert parsed["buckets"][0]["slug"] == "overview"


def test_parse_llm_json_repairs_missing_commas_between_objects() -> None:
    response = """{
  "buckets": [
    {"slug": "overview"}
    {"slug": "training"}
  ]
}"""

    parsed = parse_llm_json(response)

    assert [item["slug"] for item in parsed["buckets"]] == ["overview", "training"]


def test_parse_llm_json_repairs_missing_commas_between_fields() -> None:
    response = """{
  "title": "Overview"
  "slug": "overview"
}"""

    parsed = parse_llm_json(response)

    assert parsed["slug"] == "overview"


def test_parse_llm_json_repairs_missing_comma_after_array_field() -> None:
    response = """{
  "owned_files": ["app.py", "utils.py"]
  "owned_symbols": ["build_plan"]
}"""

    parsed = parse_llm_json(response)

    assert parsed["owned_files"] == ["app.py", "utils.py"]
    assert parsed["owned_symbols"] == ["build_plan"]


def test_scanner_parse_json_uses_resilient_parser() -> None:
    response = """```json
{
  "clusters": [
    {"cluster_name": "users", "symbols": ["get_user"]}
    {"cluster_name": "auth", "symbols": ["login"]}
  ]
}
```"""

    parsed = _parse_json(response)

    assert [cluster["cluster_name"] for cluster in parsed["clusters"]] == [
        "users",
        "auth",
    ]


def test_parse_llm_json_repairs_truncated_json_after_last_valid_cluster() -> None:
    response = """```json
{
  "clusters": [
    {"cluster_name": "checkout", "symbols": ["process_checkout", "validate_cart"]}
  ]
}
```
Continue with more clusters..."""

    parsed = parse_llm_json(response)

    assert parsed["clusters"][0]["cluster_name"] == "checkout"
    assert "process_checkout" in parsed["clusters"][0]["symbols"]


def test_repair_json_candidate_recovers_from_unclosed_string_causing_expect_value() -> (
    None
):
    truncated = '{"clusters": [{"cluster_name": "checkout", "description": "Order'
    mock_exc = json.JSONDecodeError("Expecting value", truncated, 40)
    repaired = _repair_json_candidate(truncated, mock_exc)
    assert repaired is not None
    llm = _StubLLM(
        """{
  "buckets": [
    {
      "slug": "overview",
      "owned_files": ["app.py"]
    }
    {
      "slug": "training",
      "owned_files": ["train.py"]
    }
  ]
}"""
    )

    result = _llm_step(llm, "system", "prompt", "assign")

    assert result is not None
    assert [bucket["slug"] for bucket in result["buckets"]] == ["overview", "training"]
