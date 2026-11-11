"""Specs with empty YAML values (``info:`` with nothing under it) parse to None.

``dict.get(key, default)`` returns that None, so a sloppy-but-loadable spec used
to crash ``spec_to_context_string`` and abort the whole generation run.
"""
from __future__ import annotations

from deepdoc.openapi import (
    extract_endpoints_from_spec,
    parse_openapi_spec,
    spec_to_context_string,
)

SLOPPY_YAML = """\
openapi: 3.0.0
info:
servers:
paths:
  /things:
    get:
      summary:
      tags:
      parameters:
      requestBody:
      responses:
        "200":
          description:
          content:
    post:
  /empty:
"""


def test_null_valued_spec_renders_context(tmp_path):
    path = tmp_path / "openapi.yaml"
    path.write_text(SLOPPY_YAML, encoding="utf-8")
    spec = parse_openapi_spec(path)
    assert spec is not None

    text = spec_to_context_string(spec)

    assert "API: Unknown v?" in text
    assert "GET /things" in text
    assert "POST /things" in text


def test_null_valued_spec_extracts_endpoints(tmp_path):
    path = tmp_path / "openapi.yaml"
    path.write_text(SLOPPY_YAML, encoding="utf-8")
    endpoints = extract_endpoints_from_spec(parse_openapi_spec(path))

    assert {(e["method"], e["path"]) for e in endpoints} == {
        ("GET", "/things"),
        ("POST", "/things"),
    }
    assert all(isinstance(e["tags"], list) for e in endpoints)


def test_non_mapping_spec_is_rejected(tmp_path):
    path = tmp_path / "openapi.yaml"
    path.write_text("- just\n- a list\n", encoding="utf-8")
    assert parse_openapi_spec(path) is None
