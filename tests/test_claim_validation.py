"""Tests for claim extraction, validation, and source trust scoring — Slice 7."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from deepdoc.generator.claims import (
    Claim, ClaimValidation,
    ClaimExtractor, ClaimValidator,
    compute_source_trust, has_generated_marker,
)


# ---------------------------------------------------------------------------
# Claim extraction
# ---------------------------------------------------------------------------


class TestClaimExtraction:
    def test_extracts_route_claims(self):
        md = "The API has `GET /api/users` and `POST /api/orders` endpoints."
        claims = ClaimExtractor().extract(md)
        routes = [c for c in claims if c.claim_type == "route"]
        assert len(routes) == 2

    def test_extracts_call_claims(self):
        md = "Calls `UserService.findAll` and delegates to `PaymentProcessor.charge`."
        claims = ClaimExtractor().extract(md)
        calls = [c for c in claims if c.claim_type == "call_edge"]
        assert len(calls) == 2

    def test_extracts_file_refs(self):
        md = "Defined in `src/main.py:42` and used in `lib/utils.ts:15`."
        claims = ClaimExtractor().extract(md)
        refs = [c for c in claims if c.claim_type == "file_ref"]
        assert len(refs) == 2

    def test_ignores_code_fences(self):
        md = """Here is some text.
```python
GET /api/users
```
Real route: `GET /api/health`."""
        claims = ClaimExtractor().extract(md)
        routes = [c for c in claims if c.claim_type == "route"]
        assert len(routes) == 1
        assert "health" in routes[0].claim_text

    def test_empty_markdown(self):
        claims = ClaimExtractor().extract("")
        assert claims == []

    def test_no_claims_in_plain_text(self):
        claims = ClaimExtractor().extract("This is just a paragraph about architecture.")
        assert len(claims) == 0


# ---------------------------------------------------------------------------
# Claim validation
# ---------------------------------------------------------------------------


class TestClaimValidation:
    def _make_scan(self, routes=None, symbols=None, frameworks=None, files=None):
        scan = MagicMock()
        scan.file_summaries = {f: "" for f in (files or [])}
        scan.file_contents = {f: "" for f in (files or [])}
        scan.published_api_endpoints = [
            {"path": r} for r in (routes or [])
        ]
        scan.parsed_files = {}
        if symbols:
            syms = MagicMock()
            syms.symbols = [MagicMock() for _ in range(len(symbols))]
            for i, s in enumerate(symbols):
                syms.symbols[i].name = s
            scan.parsed_files = {"fake.py": syms}
        scan.frameworks_detected = frameworks or []
        return scan

    def test_grounded_route_passes(self):
        scan = self._make_scan(routes=["/api/users"])
        validator = ClaimValidator(scan)
        claims = [Claim(claim_type="route", claim_text="GET /api/users")]
        result = validator.validate(claims)
        assert result.is_valid
        assert result.ungrounded_route_claims == 0

    def test_ungrounded_route_fails(self):
        scan = self._make_scan(routes=["/api/users"])
        validator = ClaimValidator(scan)
        claims = [Claim(claim_type="route", claim_text="GET /api/inbox")] * 5
        result = validator.validate(claims)
        assert not result.is_valid
        assert result.ungrounded_route_claims == 5

    def test_few_ungrounded_routes_passes(self):
        scan = self._make_scan(routes=["/api/users"])
        validator = ClaimValidator(scan)
        claims = [Claim(claim_type="route", claim_text="GET /api/inbox")]
        result = validator.validate(claims)
        assert result.is_valid  # < 5 ungrounded → still valid

    def test_grounded_call_passes(self):
        scan = self._make_scan(symbols=["findAll"])
        validator = ClaimValidator(scan)
        claims = [Claim(claim_type="call_edge", claim_text="calls `findAll`")]
        result = validator.validate(claims)
        assert result.is_valid

    def test_ungrounded_call_fails(self):
        scan = self._make_scan(symbols=["findAll"])
        validator = ClaimValidator(scan)
        claims = [Claim(claim_type="call_edge", claim_text="calls `fabricatedMethod`")] * 5
        result = validator.validate(claims)
        assert not result.is_valid

    def test_hallucinated_file_fails(self):
        scan = self._make_scan(files=["src/main.py"])
        validator = ClaimValidator(scan)
        claims = [Claim(claim_type="file_ref", claim_text="src/fake.py:99")]
        result = validator.validate(claims)
        assert not result.is_valid
        assert "src/fake.py" in result.hallucinated_files

    def test_real_file_passes(self):
        scan = self._make_scan(files=["src/main.py"])
        validator = ClaimValidator(scan)
        claims = [Claim(claim_type="file_ref", claim_text="src/main.py:42")]
        result = validator.validate(claims)
        assert result.is_valid

    def test_fabricated_framework_fails(self):
        scan = self._make_scan(frameworks=["express"])
        validator = ClaimValidator(scan)
        claims = [Claim(claim_type="framework", claim_text="built with Spring Boot")]
        result = validator.validate(claims)
        assert not result.is_valid
        assert result.fabricated_frameworks

    def test_correct_framework_passes(self):
        scan = self._make_scan(frameworks=["express"])
        validator = ClaimValidator(scan)
        claims = [Claim(claim_type="framework", claim_text="built with Express")]
        result = validator.validate(claims)
        assert result.is_valid

    def test_mixed_grounded_ungrounded(self):
        scan = self._make_scan(
            routes=["/api/users"], symbols=["findAll"], files=["src/main.py"]
        )
        validator = ClaimValidator(scan)
        claims = [
            Claim(claim_type="route", claim_text="GET /api/users"),
            Claim(claim_type="call_edge", claim_text="calls `fabricatedMethod`"),
        ]
        result = validator.validate(claims)
        assert result.grounded_claims == 1
        assert result.ungrounded_call_claims == 1


# ---------------------------------------------------------------------------
# Source trust scoring
# ---------------------------------------------------------------------------


class TestSourceTrust:
    def test_product_trust(self):
        assert compute_source_trust("product") == 1.0

    def test_test_trust(self):
        assert compute_source_trust("test") == 0.1

    def test_fixture_trust(self):
        assert compute_source_trust("fixture") == 0.1

    def test_generated_trust(self):
        assert compute_source_trust("generated") == 0.0

    def test_config_trust(self):
        assert compute_source_trust("config") == 0.8

    def test_generated_marker_in_content(self):
        assert compute_source_trust("product", "// @generated") == 0.0

    def test_auto_generated_marker(self):
        assert compute_source_trust("product", "/** auto-generated file */") == 0.0

    def test_do_not_edit_marker(self):
        assert compute_source_trust("product", "// DO NOT EDIT") == 0.0

    def test_marker_only_in_first_50_lines(self):
        long = "line\n" * 60 + "// @generated"
        assert compute_source_trust("product", long) == 1.0  # marker past line 50, ignored


class TestGeneratedMarker:
    def test_at_generated(self):
        assert has_generated_marker("// @generated")

    def test_auto_generated(self):
        assert has_generated_marker("/* auto-generated */")

    def test_do_not_edit(self):
        assert has_generated_marker("# DO NOT EDIT")

    def test_this_file_is_auto(self):
        assert has_generated_marker("// THIS FILE IS AUTO GENERATED")

    def test_no_marker(self):
        assert not has_generated_marker("def hello(): pass")

    def test_marker_in_comment(self):
        assert has_generated_marker("# @generated by protoc")