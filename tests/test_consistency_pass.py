from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from deepdoc.generator.consistency import CrossBucketConsistencyPass
from deepdoc.generator.generation import GenerationResult
from tests.conftest import make_bucket


def _make_result(slug: str, title: str, content: str) -> GenerationResult:
    bucket = make_bucket(title, slug, [])
    return GenerationResult(bucket=bucket, content=content)


def _make_llm(response: str) -> MagicMock:
    llm = MagicMock()
    llm.complete.return_value = response
    return llm


def test_consistency_pass_injects_missing_link(tmp_path):
    """LLM returns a cross-link gap — callout is appended to the source page."""
    output_dir = tmp_path / "docs"
    output_dir.mkdir()

    orders_content = "# Order Fulfillment\n\n## Overview\n\nplace_order calls charge_card.\n"
    payments_content = "# Payments & Billing\n\n## Overview\n\nStripe integration.\n"

    (output_dir / "order-fulfillment.md").write_text(orders_content)
    (output_dir / "payments-billing.md").write_text(payments_content)

    results = [
        _make_result("order-fulfillment", "Order Fulfillment", orders_content),
        _make_result("payments-billing", "Payments & Billing", payments_content),
    ]

    llm_response = json.dumps({
        "cross_links": [
            {
                "from_slug": "order-fulfillment",
                "to_slug": "payments-billing",
                "reason": "mentions charge_card which is documented here",
            }
        ]
    })
    llm = _make_llm(llm_response)
    cfg = {}

    injected = CrossBucketConsistencyPass(llm, output_dir, cfg).run(results)

    assert injected == 1
    patched = (output_dir / "order-fulfillment.md").read_text()
    assert "/// note | See also" in patched
    assert "(payments-billing.md)" in patched
    assert "charge_card" in patched
    # Payments page untouched
    assert (output_dir / "payments-billing.md").read_text() == payments_content


def test_consistency_pass_skips_existing_link(tmp_path):
    """LLM suggests a link that already exists in the page — no change, returns 0."""
    output_dir = tmp_path / "docs"
    output_dir.mkdir()

    orders_content = (
        "# Order Fulfillment\n\n"
        "See [Payments & Billing](payments-billing.md) for charge details.\n"
    )
    (output_dir / "order-fulfillment.md").write_text(orders_content)
    (output_dir / "payments-billing.md").write_text("# Payments\n")

    results = [
        _make_result("order-fulfillment", "Order Fulfillment", orders_content),
        _make_result("payments-billing", "Payments & Billing", "# Payments\n"),
    ]

    llm_response = json.dumps({
        "cross_links": [
            {"from_slug": "order-fulfillment", "to_slug": "payments-billing", "reason": "related"}
        ]
    })
    llm = _make_llm(llm_response)

    injected = CrossBucketConsistencyPass(llm, output_dir, {}).run(results)

    assert injected == 0
    # Content unchanged
    assert (output_dir / "order-fulfillment.md").read_text() == orders_content


def test_consistency_pass_handles_llm_failure_gracefully(tmp_path):
    """LLM returns unparseable garbage — pass returns 0 without raising."""
    output_dir = tmp_path / "docs"
    output_dir.mkdir()

    (output_dir / "page-a.md").write_text("# Page A\n")
    (output_dir / "page-b.md").write_text("# Page B\n")

    results = [
        _make_result("page-a", "Page A", "# Page A\n"),
        _make_result("page-b", "Page B", "# Page B\n"),
    ]

    llm = _make_llm("not valid json at all !!!")

    injected = CrossBucketConsistencyPass(llm, output_dir, {}).run(results)

    assert injected == 0
    # Files untouched
    assert (output_dir / "page-a.md").read_text() == "# Page A\n"
