from __future__ import annotations

import json
from pathlib import Path

from codewiki.generator_v2 import (
    _fix_mermaid_diagram,
    escape_mdx_route_params,
    escape_mdx_text_hazards,
    normalize_code_fence_languages,
)
from codewiki.pipeline_v2 import stage_openapi_assets
from codewiki.prompts_v2 import ENDPOINT_BUCKET_V2, ENDPOINT_REF_V2, SYSTEM_V2
from codewiki.site.fumadocs_builder_v2 import build_fumadocs_from_plan
from tests.conftest import make_bucket, make_plan


def test_build_fumadocs_from_plan_creates_site_scaffold(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    output_dir = repo_root / "docs"
    output_dir.mkdir()

    overview = make_bucket(
        "Overview",
        "overview",
        ["README.md"],
        generation_hints={"is_introduction_page": True},
    )
    auth = make_bucket("Auth", "auth", ["auth.py"], section="Core")
    endpoint_ref = make_bucket(
        "Get Order",
        "get-order",
        ["routes.py"],
        bucket_type="endpoint_ref",
        section="API Endpoints",
        generation_hints={"is_endpoint_ref": True, "prompt_style": "endpoint_ref"},
    )

    plan = make_plan([overview, auth, endpoint_ref])
    plan.nav_structure = {
        "Core": ["auth"],
        "API Endpoints > Orders": ["get-order"],
    }

    (output_dir / "auth.mdx").write_text("# Auth\n", encoding="utf-8")

    build_fumadocs_from_plan(
        repo_root,
        output_dir,
        {"project_name": "Demo", "site": {"repo_url": "https://example.com/repo"}},
        plan,
        has_openapi=True,
    )

    assert (output_dir / "index.mdx").exists()
    assert (repo_root / "site" / "package.json").exists()
    assert (repo_root / "site" / "postcss.config.mjs").exists()
    assert (repo_root / "site" / "source.config.mjs").exists()
    assert (repo_root / "site" / "app" / "search" / "route.ts").exists()
    assert (repo_root / "site" / "public" / "favicon.svg").exists()
    assert not (repo_root / "mint.json").exists()
    assert not (repo_root / "app").exists()
    assert not (repo_root / "package.json").exists()

    page_tree = (repo_root / "site" / "lib" / "page-tree.generated.ts").read_text(
        encoding="utf-8"
    )
    assert '"url": "/"' in page_tree
    assert '"name": "Core"' in page_tree
    assert '"url": "/auth"' in page_tree
    assert '"name": "API Reference"' in page_tree
    assert '"url": "/api/get-order"' in page_tree

    build_fumadocs_from_plan(
        repo_root,
        output_dir,
        {"project_name": "Demo", "site": {"repo_url": "https://example.com/repo"}},
        plan,
        has_openapi=True,
    )

    assert (repo_root / "site" / "package.json").exists()


def test_fumadocs_prompts_drop_mintlify_only_components() -> None:
    assert "Mintlify" not in SYSTEM_V2
    assert "<Callout" in SYSTEM_V2
    assert "<Cards>" in SYSTEM_V2
    assert "<Tabs items={" in SYSTEM_V2
    assert "<Accordions type=\"single\">" in SYSTEM_V2
    assert "<CardGroup" not in SYSTEM_V2
    assert "<AccordionGroup" not in SYSTEM_V2

    for prompt in (ENDPOINT_BUCKET_V2, ENDPOINT_REF_V2):
        assert "ParamField" not in prompt
        assert "ResponseField" not in prompt
        assert "RequestExample" not in prompt
        assert "ResponseExample" not in prompt
        assert "Expandable" not in prompt


def test_stage_openapi_assets_uses_endpoint_ref_slug_shape(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    spec_path = repo_root / "openapi.json"
    spec_path.write_text(
        json.dumps(
            {
                "openapi": "3.1.0",
                "info": {"title": "Demo API", "version": "1.0.0"},
                "paths": {
                    "/orders/{id}": {
                        "get": {
                            "summary": "Get an order",
                            "operationId": "GetOrderById",
                            "responses": {"200": {"description": "ok"}},
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    assert stage_openapi_assets(repo_root, ["openapi.json"]) is True

    manifest = json.loads(
        (repo_root / "site" / "openapi" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest == [
        {
            "slug": "get-orders-id",
            "title": "Get an order",
            "method": "GET",
            "path": "/orders/{id}",
        }
    ]


def test_escape_mdx_route_params_avoids_runtime_expressions() -> None:
    content = """# GET /reports/{slug}

<Card title="GET /api/users/{id}" href="/get-api-users-id">
  Open the user endpoint.
</Card>

Inline code: `GET /reports/{slug}`

```mermaid
flowchart TD
    A["GET /reports/{slug}"]
```
"""

    escaped = escape_mdx_route_params(content)

    assert "/reports/&#123;slug&#125;" in escaped
    assert 'title="GET /api/users/&#123;id&#125;"' in escaped
    assert "`GET /reports/{slug}`" in escaped
    assert 'A["GET /reports/{slug}"]' in escaped


def test_escape_mdx_text_hazards_escapes_bare_lt_in_prose_only() -> None:
    content = """- **Timeouts**: Webhook handlers must respond quickly (<5s typical).

Inline code: `<5s`

```md
<5s
```
"""

    escaped = escape_mdx_text_hazards(content)

    assert "(&lt;5s typical)." in escaped
    assert "Inline code: `<5s`" in escaped
    assert "```md\n<5s\n```" in escaped


def test_escape_mdx_text_hazards_escapes_django_route_converters() -> None:
    content = """# ANY /get-prod-variants/<str:prod_slug>

Description: API reference for ANY /get-prod-variants/<str:prod_slug>

Inline code: `ANY /get-prod-variants/<str:prod_slug>`
"""

    escaped = escape_mdx_text_hazards(content)

    assert "/get-prod-variants/&lt;str:prod_slug&gt;" in escaped
    assert "`ANY /get-prod-variants/<str:prod_slug>`" in escaped


def test_normalize_code_fence_languages_rewrites_env_aliases() -> None:
    content = """```env
SECRET_KEY=test
```

```dotenv
DEBUG=False
```
"""

    normalized = normalize_code_fence_languages(content)

    assert "```bash\nSECRET_KEY=test" in normalized
    assert "```bash\nDEBUG=False" in normalized


def test_fix_mermaid_diagram_rewrites_quoted_edge_targets() -> None:
    diagram = """flowchart TD
SiteBuilder --> "Fumadocs Site"
"""

    fixed = _fix_mermaid_diagram(diagram)

    assert 'SiteBuilder --> FumadocsSite["Fumadocs Site"]' in fixed


def test_fix_mermaid_diagram_strips_flowchart_labels_from_class_diagram_edges() -> None:
    diagram = """classDiagram
SiteBuilder --> FumadocsSite["Fumadocs Site"]
"""

    fixed = _fix_mermaid_diagram(diagram)

    assert "SiteBuilder --> FumadocsSite" in fixed
    assert 'FumadocsSite["Fumadocs Site"]' not in fixed
