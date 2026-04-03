from __future__ import annotations

from pathlib import Path

from deepdoc.chatbot.service import ChatbotQueryService
from deepdoc.chatbot.types import ChunkRecord, RetrievedChunk
from deepdoc.persistence_v2 import load_plan, load_scan_cache, save_plan, save_scan_cache
from deepdoc.planner_v2 import (
    DocBucket,
    DocPlan,
    RepoScan,
    _assign_publication_tiers,
    _auto_generate_endpoint_refs,
    _normalize_repo_profile,
    _shape_plan_nav,
)
from deepdoc.source_metadata import (
    classify_integration_party,
    classify_source_kind,
    endpoint_publication_decision,
)


def _scan(
    *,
    frameworks: list[str] | None = None,
    api_endpoints: list[dict] | None = None,
    source_kind_by_file: dict[str, str] | None = None,
    file_frameworks: dict[str, list[str]] | None = None,
) -> RepoScan:
    return RepoScan(
        file_tree={},
        file_summaries={},
        api_endpoints=api_endpoints or [],
        languages={"python": 1},
        has_openapi=False,
        openapi_paths=[],
        total_files=0,
        frameworks_detected=frameworks or [],
        entry_points=[],
        config_files=[],
        source_kind_by_file=source_kind_by_file or {},
        file_frameworks=file_frameworks or {},
    )


def test_source_kind_classifies_internal_supporting_material() -> None:
    assert classify_source_kind("tests/test_chatbot_query.py") == "test"
    assert classify_source_kind("tests/fixtures/frameworks/express_app/server.js") == "fixture"
    assert classify_source_kind("examples/demo/app.py") == "example"
    assert classify_source_kind("docs/architecture.md") == "docs"


def test_endpoint_publication_rejects_fixture_and_header_like_paths() -> None:
    publishable, _, reason = endpoint_publication_decision(
        "/api/v1/users",
        route_file="tests/fixtures/frameworks/express_app/server.js",
        handler_file="tests/fixtures/frameworks/express_app/server.js",
        framework="express",
        source_kind_by_file={"tests/fixtures/frameworks/express_app/server.js": "fixture"},
    )
    assert publishable is False
    assert reason == "non_product_source"

    publishable, _, reason = endpoint_publication_decision(
        "/Authorization",
        route_file="src/routes.ts",
        handler_file="src/routes.ts",
        framework="express",
        source_kind_by_file={"src/routes.ts": "product"},
    )
    assert publishable is False
    assert reason in {"header_like_segment", "unexpected_uppercase_segment"}


def test_normalize_repo_profile_promotes_falcon_backend() -> None:
    classification = {"repo_profile": {"primary_type": "other", "secondary_traits": []}}
    scan = _scan(
        frameworks=["falcon"],
        api_endpoints=[
            {
                "method": "GET",
                "path": "/api/v1/users",
                "handler": "Users",
                "file": "main.py",
                "publication_ready": True,
            }
        ],
    )

    normalized = _normalize_repo_profile(classification, scan)

    assert normalized["repo_profile"]["primary_type"] == "falcon_backend"
    assert "uses_falcon" in normalized["repo_profile"]["secondary_traits"]


def test_supporting_buckets_land_in_supporting_sections() -> None:
    plan = DocPlan(
        buckets=[
            DocBucket(
                bucket_type="architecture",
                title="Architecture Overview",
                slug="architecture-overview",
                section="Overview",
                description="Core architecture",
                owned_files=["app/main.py"],
                generation_hints={"is_introduction_page": True},
            ),
            DocBucket(
                bucket_type="testing",
                title="Testing Strategy",
                slug="testing-strategy",
                section="Architecture",
                description="Tests and coverage",
                owned_files=["tests/test_app.py"],
            ),
        ],
        nav_structure={},
        skipped_files=[],
        classification={"repo_profile": {"primary_type": "backend_service"}},
    )
    scan = _scan(source_kind_by_file={"app/main.py": "product", "tests/test_app.py": "test"})

    plan = _assign_publication_tiers(plan, scan, plan.classification)
    plan = _shape_plan_nav(plan, plan.classification)

    testing_bucket = next(bucket for bucket in plan.buckets if bucket.slug == "testing-strategy")
    assert testing_bucket.publication_tier == "supporting"
    assert "Testing" in plan.nav_structure


def test_auto_generate_endpoint_refs_uses_only_publishable_endpoints() -> None:
    api_family = DocBucket(
        bucket_type="endpoint-family",
        title="Users API",
        slug="users-api",
        section="API Reference",
        description="Users endpoints",
        generation_hints={"is_endpoint_family": True, "prompt_style": "endpoint"},
    )
    plan = DocPlan(
        buckets=[api_family],
        nav_structure={"API Reference": ["users-api"]},
        skipped_files=[],
        classification={"repo_profile": {"primary_type": "backend_service"}},
    )
    scan = _scan(
        api_endpoints=[
            {
                "method": "GET",
                "path": "/api/users",
                "handler": "list_users",
                "file": "routes.py",
                "route_file": "routes.py",
                "handler_file": "handlers.py",
                "publication_ready": True,
            },
            {
                "method": "GET",
                "path": "/Authorization",
                "handler": "fake",
                "file": "routes.py",
                "route_file": "routes.py",
                "handler_file": "handlers.py",
                "publication_ready": False,
            },
        ]
    )

    expanded = _auto_generate_endpoint_refs(plan, scan)
    slugs = {bucket.slug for bucket in expanded.buckets}

    assert "get-api-users" in slugs
    assert "get-authorization" not in slugs


def test_plan_persistence_preserves_publication_metadata(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    plan = DocPlan(
        buckets=[
            DocBucket(
                bucket_type="architecture",
                title="Falcon Runtime",
                slug="falcon-runtime",
                section="Runtime & Frameworks",
                description="Falcon runtime details",
                owned_files=["app/main.py"],
                publication_tier="core",
                source_kind_summary={"product": 2, "config": 1},
            )
        ],
        nav_structure={},
        skipped_files=[],
        classification={"repo_profile": {"primary_type": "falcon_backend"}},
    )

    save_plan(plan, repo_root)
    loaded = load_plan(repo_root)

    assert loaded is not None
    assert loaded.buckets[0].publication_tier == "core"
    assert loaded.buckets[0].source_kind_summary == {"product": 2, "config": 1}


def test_scan_cache_preserves_source_kinds_and_frameworks(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    scan = _scan(
        frameworks=["falcon"],
        source_kind_by_file={"app/main.py": "product", "tests/test_main.py": "test"},
        file_frameworks={"app/main.py": ["falcon"]},
    )

    save_scan_cache(scan, repo_root)
    cached = load_scan_cache(repo_root)

    assert cached is not None
    assert cached["source_kind_by_file"]["app/main.py"] == "product"
    assert cached["source_kind_by_file"]["tests/test_main.py"] == "test"
    assert cached["file_frameworks"]["app/main.py"] == ["falcon"]


def test_chatbot_prefers_core_but_can_prioritize_tests_when_explicit() -> None:
    service = ChatbotQueryService.__new__(ChatbotQueryService)
    core_hit = RetrievedChunk(
        record=ChunkRecord(
            chunk_id="core",
            kind="code",
            source_key="app/main.py",
            text="core",
            chunk_hash="1",
            file_path="app/main.py",
            source_kind="product",
            publication_tier="core",
            trust_score=1.0,
            framework="falcon",
        ),
        score=0.6,
    )
    test_hit = RetrievedChunk(
        record=ChunkRecord(
            chunk_id="test",
            kind="code",
            source_key="tests/test_main.py",
            text="test",
            chunk_hash="2",
            file_path="tests/test_main.py",
            source_kind="test",
            publication_tier="supporting",
            trust_score=0.5,
            framework="falcon",
        ),
        score=0.9,
    )

    normal = service._sort_hits([test_hit, core_hit], service._question_support_profile("where is auth handled"))
    explicit = service._sort_hits([test_hit, core_hit], service._question_support_profile("which test covers auth"))

    assert normal[0].record.file_path == "app/main.py"
    assert explicit[0].record.file_path == "tests/test_main.py"


def test_integration_party_uses_repo_name_tokens() -> None:
    assert classify_integration_party("deepdoc", Path("/tmp/deepdoc")) == "first_party"
    assert classify_integration_party("workos", Path("/tmp/deepdoc")) == "third_party"
