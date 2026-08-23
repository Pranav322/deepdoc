from __future__ import annotations

from deepdoc.parser.routes.base import APIEndpoint
from deepdoc.parser.routes.common import dedupe_endpoints


def _endpoint(**overrides) -> APIEndpoint:
    base = dict(
        method="GET",
        path="/users",
        handler="handler",
        file="app.py",
        route_file="app.py",
        line=10,
        framework="",
    )
    base.update(overrides)
    return APIEndpoint(**base)


def test_conflicting_claims_on_same_route_keep_higher_priority_framework() -> None:
    endpoints = [
        _endpoint(path="/users", framework="nestjs"),
        _endpoint(path="/api/users", framework="django"),
    ]

    result = dedupe_endpoints(endpoints)

    assert len(result) == 1
    assert result[0].path == "/api/users"
    assert result[0].framework == "django"


def test_identical_claims_still_exact_deduped() -> None:
    endpoints = [
        _endpoint(path="/users", framework="fastapi"),
        _endpoint(path="/users", framework="fastapi"),
    ]

    result = dedupe_endpoints(endpoints)

    assert len(result) == 1


def test_distinct_routes_are_not_merged() -> None:
    endpoints = [
        _endpoint(path="/users", line=10, framework="django"),
        _endpoint(path="/orders", line=20, framework="django"),
    ]

    result = dedupe_endpoints(endpoints)

    assert {ep.path for ep in result} == {"/users", "/orders"}
