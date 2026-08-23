from __future__ import annotations

from pathlib import Path

from deepdoc.parser.routes.base import RouteResolverContext
from deepdoc.parser.routes.fastapi import detect_fastapi


def test_mock_patch_in_a_fastapi_file_does_not_emit_a_phantom_endpoint() -> None:
    content = (
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n\n"
        "@app.post(\"/orders\")\n"
        "def create_order():\n"
        "    pass\n\n"
        "@mock.patch(\"myapp.services.billing.charge\")\n"
        "def test_charge(mock_charge):\n"
        "    pass\n"
    )
    ctx = RouteResolverContext(path=Path("app.py"), content=content, language="python")

    endpoints = detect_fastapi(ctx)

    assert len(endpoints) == 1
    assert endpoints[0].method == "POST"
    assert endpoints[0].path == "/orders"
