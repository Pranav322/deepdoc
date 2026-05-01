from __future__ import annotations

import json
from pathlib import Path

from deepdoc.generator import (
    _fix_mermaid_diagram,
    build_internal_doc_link_maps,
    escape_mdx_route_params,
    escape_mdx_text_hazards,
    normalize_code_fence_languages,
    normalize_explanatory_lines_outside_fences,
    normalize_html_code_blocks,
    normalize_mdx_steps,
    repair_mdx_component_blocks,
    repair_split_object_code_fences,
    repair_dangling_plain_fences,
    repair_internal_doc_links,
    repair_unbalanced_code_fences,
)
from deepdoc.pipeline_v2 import _endpoint_ref_slug, stage_openapi_assets
from deepdoc.prompts_v2 import (
    DEBUG_RUNBOOK_V2,
    DOMAIN_GLOSSARY_V2,
    ENDPOINT_BUCKET_V2,
    ENDPOINT_REF_V2,
    START_HERE_INDEX_V2,
    START_HERE_SETUP_V2,
    SYSTEM_V2,
)
from deepdoc.site.builder import _ensure_mdx_frontmatter, build_fumadocs_from_plan
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
        {
            "project_name": "Demo",
            "site": {
                "repo_url": "https://example.com/repo",
                "colors": {
                    "primary": "#EB3E25",
                    "light": "#EF624E",
                    "dark": "#C1331F",
                },
            },
        },
        plan,
        has_openapi=True,
    )

    assert (output_dir / "index.mdx").exists()
    assert (repo_root / "site" / "package.json").exists()
    assert (repo_root / "site" / "postcss.config.mjs").exists()
    assert (repo_root / "site" / "source.config.mjs").exists()
    assert (repo_root / "site" / "next.config.mjs").exists()
    assert (repo_root / "site" / "app" / "layout.tsx").exists()
    assert (repo_root / "site" / "app" / "search" / "route.ts").exists()
    assert (repo_root / "site" / "public" / "favicon.svg").exists()
    assert not (repo_root / "mint.json").exists()
    assert not (repo_root / "app").exists()
    assert not (repo_root / "package.json").exists()

    page_tree = (repo_root / "site" / "lib" / "page-tree.generated.ts").read_text(
        encoding="utf-8"
    )
    global_css = (repo_root / "site" / "app" / "global.css").read_text(encoding="utf-8")
    next_config = (repo_root / "site" / "next.config.mjs").read_text(encoding="utf-8")
    app_layout = (repo_root / "site" / "app" / "layout.tsx").read_text(encoding="utf-8")
    mdx_components = (repo_root / "site" / "mdx-components.tsx").read_text(
        encoding="utf-8"
    )
    docs_page = (repo_root / "site" / "app" / "[[...slug]]" / "page.tsx").read_text(
        encoding="utf-8"
    )
    api_page_component = (repo_root / "site" / "components" / "api-page.tsx").read_text(
        encoding="utf-8"
    )
    openapi_lib = (repo_root / "site" / "lib" / "openapi.ts").read_text(
        encoding="utf-8"
    )
    auth_doc = (output_dir / "auth.mdx").read_text(encoding="utf-8")
    assert '"url": "/"' in page_tree
    assert '"name": "Core"' in page_tree
    assert '"url": "/auth"' in page_tree
    assert '"name": "API Reference"' in page_tree
    assert '"url": "/api/get-order"' in page_tree
    assert "--deepdoc-brand-primary: #EB3E25;" in global_css
    assert ".deepdoc-chatbot-dock" not in global_css
    assert ".deepdoc-chatbot-shell--visible" not in global_css
    assert ".deepdoc-chatbot-shell--hidden" not in global_css
    assert (repo_root / "site" / "app" / "ask" / "page.tsx").exists() is False
    assert (repo_root / "site" / "components" / "chatbot-panel.tsx").exists() is False
    assert (repo_root / "site" / "components" / "chatbot-toggle.tsx").exists() is False
    assert (repo_root / "site" / "lib" / "chatbot-config.ts").exists() is False

    package_json = json.loads(
        (repo_root / "site" / "package.json").read_text(encoding="utf-8")
    )
    assert package_json["dependencies"]["fumadocs-openapi"] == "9.3.9"
    assert package_json["dependencies"]["fumadocs-ui"] == "15.7.11"
    assert package_json["dependencies"]["next"] == "15.3.0"
    assert package_json["dependencies"]["react"] == "19.1.0"
    assert package_json["dependencies"]["react-syntax-highlighter"] == "^15.6.1"
    assert (
        package_json["devDependencies"]["@types/react-syntax-highlighter"]
        == "^15.5.13"
    )
    assert "fumadocs-ui/provider';" in app_layout
    assert "NEXT_PUBLIC_DEEPDOC_SITE_BASE_PATH" in app_layout
    assert (
        "const searchApiPath = siteBasePath ? `${siteBasePath}/search` : '/search';"
        in app_layout
    )
    assert "api: searchApiPath" in app_layout
    assert 'title: "Demo"' in (output_dir / "index.mdx").read_text(encoding="utf-8")
    assert "icon: 'favicon.svg'" in app_layout
    assert "ChatbotToggle" not in app_layout
    assert "provider/next" not in app_layout
    assert "turbopack" not in next_config
    assert "DEEPDOC_SITE_BASE_PATH" in next_config
    assert "normalizedExplicitBasePath" in next_config
    assert (
        "siteBasePath = normalizedExplicitBasePath || githubPagesBasePath"
        in next_config
    )
    assert "trailingSlash: useTrailingSlash" in next_config
    assert "GITHUB_REPOSITORY" in next_config
    assert "basePath: siteBasePath || undefined" in next_config
    assert "assetPrefix: siteBasePath || undefined" in next_config
    assert "APIPage" in mdx_components
    assert "ComponentType" in docs_page
    assert "TOCItemType" in docs_page
    assert "page.data as { body:" in docs_page
    assert "import type { PageTree } from 'fumadocs-core/server';" in page_tree
    assert "satisfies PageTree.Root" in page_tree
    assert "APIPage as FumadocsAPIPage" in api_page_component
    assert "createAPIPage" not in api_page_component
    assert "createOpenAPI" in openapi_lib
    assert "generateAPIParams" in openapi_lib
    assert "getAPIPage" in openapi_lib
    assert "manifest.json" in openapi_lib
    assert "path.join(schemaDir, file)" in openapi_lib
    assert "!/^manifest\\.json$/i.test(file)" in openapi_lib
    assert "/^(openapi|swagger)(\\.|$)/i.test(file)" in openapi_lib
    assert "openapiSource" not in openapi_lib
    assert "openapiPlugin" not in openapi_lib
    assert auth_doc.startswith("---\n")
    assert 'title: "Auth"' in auth_doc

    build_fumadocs_from_plan(
        repo_root,
        output_dir,
        {
            "project_name": "Demo",
            "site": {
                "repo_url": "https://example.com/repo",
                "colors": {
                    "primary": "#EB3E25",
                    "light": "#EF624E",
                    "dark": "#C1331F",
                },
            },
        },
        plan,
        has_openapi=True,
    )

    assert (repo_root / "site" / "package.json").exists()


def test_start_here_prompts_include_generation_placeholders() -> None:
    prompts = [
        START_HERE_INDEX_V2,
        START_HERE_SETUP_V2,
        DOMAIN_GLOSSARY_V2,
        DEBUG_RUNBOOK_V2,
    ]

    for prompt in prompts:
        assert "{source_context}" in prompt
        assert "{required_sections}" in prompt
        assert "{required_diagrams}" in prompt
        assert "{sitemap_context}" in prompt
        assert "{dependency_links}" in prompt


def test_build_fumadocs_preserves_handwritten_index_without_frontmatter(
    tmp_path: Path,
) -> None:
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
    plan = make_plan([overview, auth])
    plan.nav_structure = {"Core": ["auth"]}

    custom_index = "# Custom landing\n\nThis page is handwritten.\n"
    (output_dir / "index.mdx").write_text(custom_index, encoding="utf-8")
    (output_dir / "auth.mdx").write_text("# Auth\n", encoding="utf-8")

    build_fumadocs_from_plan(
        repo_root,
        output_dir,
        {"project_name": "Demo"},
        plan,
        has_openapi=False,
    )

    index_text = (output_dir / "index.mdx").read_text(encoding="utf-8")
    auth_doc = (output_dir / "auth.mdx").read_text(encoding="utf-8")

    assert index_text.startswith("---\n")
    assert 'title: "Custom landing"' in index_text
    assert "_deepdoc_autogen_" not in index_text
    assert index_text.endswith(custom_index)
    assert auth_doc.startswith("---\n")


def test_build_fumadocs_repairs_malformed_index_frontmatter(tmp_path: Path) -> None:
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
    plan = make_plan([overview, auth])
    plan.nav_structure = {"Core": ["auth"]}

    malformed_index = """---
# System Architecture & Overview

A real-time POS backend.
---

## What This Does

It runs the admin platform.
"""
    (output_dir / "index.mdx").write_text(malformed_index, encoding="utf-8")
    (output_dir / "auth.mdx").write_text("# Auth\n", encoding="utf-8")

    build_fumadocs_from_plan(
        repo_root,
        output_dir,
        {"project_name": "Demo"},
        plan,
        has_openapi=False,
    )

    index_text = (output_dir / "index.mdx").read_text(encoding="utf-8")

    assert index_text.startswith("---\n")
    assert 'title: "System Architecture & Overview"' in index_text
    assert "_deepdoc_autogen_" not in index_text
    assert "# System Architecture & Overview" in index_text
    assert "A real-time POS backend." in index_text
    assert "## What This Does" in index_text


def test_build_fumadocs_without_openapi_omits_api_route_scaffold(
    tmp_path: Path,
) -> None:
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
    plan = make_plan([overview, auth])
    plan.nav_structure = {"Core": ["auth"]}

    (output_dir / "auth.mdx").write_text("# Auth\n", encoding="utf-8")

    build_fumadocs_from_plan(
        repo_root,
        output_dir,
        {"project_name": "Demo"},
        plan,
        has_openapi=False,
    )

    mdx_components = (repo_root / "site" / "mdx-components.tsx").read_text(
        encoding="utf-8"
    )
    assert not (
        repo_root / "site" / "app" / "api" / "[[...slug]]" / "page.tsx"
    ).exists()
    assert not (
        repo_root / "site" / "app" / "api" / "[[...slug]]" / "layout.tsx"
    ).exists()
    assert not (repo_root / "site" / "components" / "api-page.tsx").exists()
    assert not (repo_root / "site" / "lib" / "openapi.ts").exists()
    assert "@/components/api-page" not in mdx_components
    assert "APIPage," not in mdx_components


def test_build_fumadocs_surfaces_staged_openapi_operations_when_plan_has_no_endpoint_pages(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    output_dir = repo_root / "docs"
    output_dir.mkdir()
    (repo_root / "site" / "openapi").mkdir(parents=True)
    (repo_root / "site" / "openapi" / "manifest.json").write_text(
        json.dumps(
            [
                {
                    "slug": "get-http-localhost-3000-health",
                    "title": "Deep health check",
                    "method": "GET",
                    "path": "http://localhost:3000/health",
                }
            ]
        ),
        encoding="utf-8",
    )

    overview = make_bucket(
        "Overview",
        "overview",
        ["README.md"],
        generation_hints={"is_introduction_page": True},
    )
    health = make_bucket(
        "Health & Readiness Endpoints",
        "operations-health",
        ["health.js"],
        section="API Reference",
    )
    plan = make_plan([overview, health])
    plan.nav_structure = {"API Reference": ["operations-health"]}

    (output_dir / "index.mdx").write_text("# Overview\n", encoding="utf-8")
    (output_dir / "operations-health.mdx").write_text("# Health\n", encoding="utf-8")

    build_fumadocs_from_plan(
        repo_root,
        output_dir,
        {"project_name": "Demo"},
        plan,
        has_openapi=True,
    )

    page_tree = (repo_root / "site" / "lib" / "page-tree.generated.ts").read_text(
        encoding="utf-8"
    )
    assert '"name": "OpenAPI Operations"' in page_tree
    assert '"url": "/api/get-http-localhost-3000-health"' in page_tree
    assert '"name": "GET /health"' in page_tree


def test_fumadocs_prompts_drop_mintlify_only_components() -> None:
    assert "Mintlify" not in SYSTEM_V2
    assert "<Callout" in SYSTEM_V2
    assert "<Cards>" in SYSTEM_V2
    assert "<Tabs items={" in SYSTEM_V2
    assert '<Accordions type="single">' in SYSTEM_V2
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


def test_stage_openapi_assets_strips_server_origin_from_manifest_paths(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    spec_path = repo_root / "openapi.yaml"
    spec_path.write_text(
        """
openapi: 3.0.3
info:
  title: Demo API
  version: 1.0.0
servers:
  - url: http://localhost:3000
paths:
  /health:
    get:
      summary: Health
      responses:
        '200':
          description: ok
""".strip()
        + "\n",
        encoding="utf-8",
    )

    assert stage_openapi_assets(repo_root, ["openapi.yaml"]) is True

    manifest = json.loads(
        (repo_root / "site" / "openapi" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest == [
        {
            "slug": "get-health",
            "title": "Health",
            "method": "GET",
            "path": "/health",
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


def test_escape_mdx_route_params_escapes_typed_route_params() -> None:
    content = (
        "See [GET /artists/{slug:int}/{page:int}](/get-artists-slug-int-page-int)."
    )

    escaped = escape_mdx_route_params(content)

    assert "&#123;slug:int&#125;" in escaped
    assert "&#123;page:int&#125;" in escaped


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


def test_escape_mdx_text_hazards_escapes_lte_operator_in_jsx_text() -> None:
    content = '<Callout type="warn">If `final_points` is missing or <=0, return 400.</Callout>'

    escaped = escape_mdx_text_hazards(content)

    assert "&lt;=0" in escaped


def test_escape_mdx_text_hazards_escapes_django_route_converters() -> None:
    content = """# ANY /get-prod-variants/<str:prod_slug>

Description: API reference for ANY /get-prod-variants/<str:prod_slug>

Inline code: `ANY /get-prod-variants/<str:prod_slug>`
"""

    escaped = escape_mdx_text_hazards(content)

    assert "/get-prod-variants/&lt;str:prod_slug&gt;" in escaped
    assert "`ANY /get-prod-variants/<str:prod_slug>`" in escaped


def test_escape_mdx_text_hazards_escapes_plain_placeholder_tags() -> None:
    content = """| Location | Name |
|----------|------|
| path     | <model>/ |

Inline code: `<model>/`
"""

    escaped = escape_mdx_text_hazards(content)

    assert "| path     | &lt;model&gt;/ |" in escaped
    assert "Inline code: `<model>/`" in escaped


def test_escape_mdx_text_hazards_escapes_hyphenated_placeholder_tags() -> None:
    content = "[ANY /get-prod-variants-<str-prod_slug>](/any-get-prod-variants-<str-prod_slug>)"

    escaped = escape_mdx_text_hazards(content)

    assert "&lt;str-prod_slug&gt;" in escaped


def test_escape_mdx_text_hazards_escapes_non_tag_less_than_sequences() -> None:
    content = '- **detailed**: \' .\\\'\\`^",:;Il!i><~+_-?][}{1)(|/tfjrxn\''

    escaped = escape_mdx_text_hazards(content)

    assert ">&lt;~" in escaped
    assert "][&#125;&#123;1)" in escaped


def test_escape_mdx_text_hazards_escapes_generic_types_in_tables_only() -> None:
    content = """| Field | Type | Description |
|-------|------|-------------|
| products | array<object> | Product list |

Inline code: `array<object>`

```md
| products | array<object> | Product list |
```
"""

    escaped = escape_mdx_text_hazards(content)

    assert "| products | array&lt;object&gt; | Product list |" in escaped
    assert "Inline code: `array<object>`" in escaped
    assert "```md\n| products | array<object> | Product list |\n```" in escaped


def test_escape_mdx_text_hazards_escapes_union_generic_types() -> None:
    content = "- `productIds` (Array<string|number>): List of product IDs to sync."

    escaped = escape_mdx_text_hazards(content)

    assert "Array&lt;string|number&gt;" in escaped


def test_escape_mdx_text_hazards_escapes_generic_types_with_array_members() -> None:
    content = (
        "| `fetchIncompleteOrders` | `report/index.ts` | "
        "() => Promise<OrderData[]> | Fetches incomplete orders |"
    )

    escaped = escape_mdx_text_hazards(content)

    assert "() => Promise&lt;OrderData[]&gt;" in escaped


def test_escape_mdx_text_hazards_escapes_nested_generic_types() -> None:
    content = "- **writerQuery(sql, params):** Promise<Array&lt;Row&gt;>"

    escaped = escape_mdx_text_hazards(content)

    assert "Promise&lt;Array&lt;Row&gt;&gt;" in escaped


def test_escape_mdx_text_hazards_escapes_literal_brace_ellipsis() -> None:
    content = "| responseData | Error | {...} |"

    escaped = escape_mdx_text_hazards(content)

    assert "&#123;...&#125;" in escaped


def test_escape_mdx_text_hazards_escapes_destructured_args_in_table_cells() -> None:
    content = """| Symbol | Signature |
|---|---|
| updateHasProductReturnDetails | (details, {connection}) |

Inline code: `(details, {connection})`
"""

    escaped = escape_mdx_text_hazards(content)

    assert "(details, &#123;connection&#125;)" in escaped
    assert "Inline code: `(details, &#123;connection&#125;)`" in escaped


def test_escape_mdx_text_hazards_wraps_json_like_table_cells() -> None:
    content = '| product_details | has_products | [{"prod_id":101}] |'

    escaped = escape_mdx_text_hazards(content)

    assert '[&#123;"prod_id":101&#125;]' in escaped


def test_escape_mdx_text_hazards_escapes_generic_code_spans_in_tables() -> None:
    content = (
        "| `getKey` | `redisUtils.ts` | `<T>(key): Promise<T | null>` | "
        "Get and deserialize key |"
    )

    escaped = escape_mdx_text_hazards(content)

    assert "`&lt;T&gt;(key): Promise&lt;T | null&gt;`" in escaped


def test_escape_mdx_text_hazards_rewrites_br_tags_inside_table_cells() -> None:
    content = "| logger | methods | .error(),<br>.warn(),<br />.info() |"

    escaped = escape_mdx_text_hazards(content)

    assert "<br" not in escaped.lower()
    assert ".error(), / .warn(), / .info()" in escaped


def test_escape_mdx_text_hazards_normalizes_br_tags_to_self_closing() -> None:
    content = """<Accordion title=\"Health Endpoint Failure\">
**Symptom**: `/health` returns non-200.<br>
**Root Cause**: Application misconfiguration.<br/>
**Fix**: Check logs.
</Accordion>"""

    escaped = escape_mdx_text_hazards(content)

    assert "**Symptom**: `/health` returns non-200.<br />" in escaped
    assert "**Root Cause**: Application misconfiguration.<br />" in escaped
    assert "<br>" not in escaped
    assert "<br/>" not in escaped


def test_escape_mdx_text_hazards_escapes_generic_types_inside_inline_code_table_cells() -> (
    None
):
    content = "| fn | returns |\n|---|---|\n| `save()` | `Promise<object|boolean>` |"

    escaped = escape_mdx_text_hazards(content)

    assert "`Promise&lt;object|boolean&gt;`" in escaped


def test_escape_mdx_text_hazards_repairs_escaped_inline_html_closers() -> None:
    content = """<Callout>Handler: <strong>statsHandler&lt;/strong&gt; in <code>server.js&lt;/code&gt;</Callout>

Inline code: `<code>server.js&lt;/code&gt;`
"""

    escaped = escape_mdx_text_hazards(content)

    assert (
        "<Callout>Handler: <strong>statsHandler</strong> in <code>server.js</code></Callout>"
        in escaped
    )
    assert "Inline code: `<code>server.js&lt;/code&gt;`" in escaped


def test_escape_mdx_text_hazards_escapes_json_literals_inside_inline_code_tags() -> (
    None
):
    content = '<Callout type="info">You should see <code>{"status": "ok"}</code> or similar.</Callout>'

    escaped = escape_mdx_text_hazards(content)

    assert '<code>&#123;"status": "ok"&#125;</code>' in escaped


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


def test_normalize_code_fence_languages_rewrites_indented_env_aliases() -> None:
    content = """  ```env
  CLIMES_URL=https://api.climes.io/
  ```
"""

    normalized = normalize_code_fence_languages(content)

    assert "  ```bash" in normalized


def test_normalize_html_code_blocks_converts_pre_code_to_fences() -> None:
    content = """<pre><code>git clone &lt;repo-url&gt;
cd app
</code></pre>"""

    normalized = normalize_html_code_blocks(content)

    assert normalized == "```bash\ngit clone &lt;repo-url&gt;\ncd app\n```"


def test_normalize_html_code_blocks_converts_multiline_code_tags_to_fences() -> None:
    content = """<Step>
  <br/>
  <code>
  await Product.updateOne(
    { id: 12345 },
    { $set: productData },
    { upsert: true }
  );
  </code>
</Step>"""

    normalized = normalize_html_code_blocks(content)

    assert "```javascript" in normalized
    assert "await Product.updateOne(" in normalized
    assert "<code>" not in normalized


def test_normalize_html_code_blocks_escapes_br_tags_before_mdx_parse() -> None:
    content = "<code>git clone &lt;repo-url&gt;<br>cd app</code>"

    normalized = normalize_html_code_blocks(content)

    assert normalized == "<code>git clone &lt;repo-url&gt;&lt;br&gt;cd app</code>"


def test_normalize_html_code_blocks_does_not_escape_br_outside_code_tags() -> None:
    content = "Before<br><Callout>Keep break<br /></Callout>"

    normalized = normalize_html_code_blocks(content)

    assert normalized == content


def test_normalize_mdx_steps_converts_markdown_headings_inside_step_blocks() -> None:
    content = """<Steps>
  <Step>
    ### 1. Clone the repository

    ```bash
    git clone https://example.com/repo.git
    ```
  </Step>
</Steps>
"""

    normalized = normalize_mdx_steps(content)

    assert "**1. Clone the repository**" in normalized
    assert "### 1. Clone the repository" not in normalized
    assert "```bash" in normalized


def test_normalize_mdx_steps_leaves_code_fence_contents_and_external_headings_unchanged() -> (
    None
):
    content = """## Setup

<Steps>
  <Step>
    ```md
    ### not-a-real-heading
    ```
  </Step>
</Steps>
"""

    normalized = normalize_mdx_steps(content)

    assert normalized.startswith("## Setup")
    assert "### not-a-real-heading" in normalized
    assert "**not-a-real-heading**" not in normalized


def test_normalize_mdx_steps_converts_html_headings_inside_step_blocks() -> None:
    content = """<Steps>
  <Step>
    <h3>Install dependencies</h3>
    Run `npm install`.
  </Step>
</Steps>
"""

    normalized = normalize_mdx_steps(content)

    assert "<h3>Install dependencies</h3>" not in normalized
    assert "**Install dependencies**" in normalized


def test_repair_mdx_component_blocks_converts_inline_callout_before_fence() -> None:
    content = """<Callout type=\"info\">If using ASGI, start Daphne with:
```bash
daphne <django_project>.asgi:application
```
</Callout>
"""

    repaired = repair_mdx_component_blocks(content)

    assert repaired.startswith('<Callout type="info">\n')
    assert "If using ASGI, start Daphne with:\n\n```bash" in repaired
    assert repaired.rstrip().endswith("</Callout>")


def test_repair_unbalanced_code_fences_drops_last_unmatched_fence() -> None:
    content = """<Tabs items={['curl', 'Browser']}>
  <Tab value="curl">
    ```bash
    curl http://localhost:8000/
    ```
    ```
  </Tab>
</Tabs>
"""

    repaired = repair_unbalanced_code_fences(content)

    assert repaired.count("```") == 2
    assert "\n    ```\n    ```" not in repaired


def test_normalize_explanatory_lines_outside_fences_closes_fence_before_prose() -> None:
    content = """<Tabs items={['curl']}>
  <Tab value="curl">
    ```bash
    curl http://127.0.0.1:8000/admin/
    Expected: HTML login page.
    ```
  </Tab>
</Tabs>
"""

    normalized = normalize_explanatory_lines_outside_fences(content)

    assert "curl http://127.0.0.1:8000/admin/\n    ```\n    Expected: HTML login page." in normalized
    assert "Expected: HTML login page.\n    ```\n  </Tab>" not in normalized


def test_normalize_explanatory_lines_outside_fences_keeps_object_fields_inside_code() -> None:
    content = """```typescript
{
  response: {
    order: []
  }
}
```
"""

    normalized = normalize_explanatory_lines_outside_fences(content)

    assert normalized == content


def test_repair_dangling_plain_fences_drops_fence_before_closing_tab() -> None:
    content = """<Tabs items={['curl']}>
  <Tab value="curl">
    ```bash
    curl http://127.0.0.1:8000/admin/
    ```
    Expected: HTML login page.
    ```
  </Tab>
</Tabs>
"""

    repaired = repair_dangling_plain_fences(content)

    assert repaired.count("```") == 2
    assert "Expected: HTML login page.\n    ```\n  </Tab>" not in repaired


def test_repair_split_object_code_fences_stitches_body_back_into_fence() -> None:
    content = """```typescript
// ReturnDetailsPayload
{
```
  response: {
    order: []
  }
}
```
"""

    repaired = repair_split_object_code_fences(content)

    assert "```typescript\n// ReturnDetailsPayload\n{\n  response: {\n    order: []\n  }\n}\n```" in repaired


def test_escape_mdx_text_hazards_repairs_mis_escaped_inline_closing_tags() -> None:
    content = "<code>python -m venv venv&lt;br>source venv/bin/activate</code&gt;"

    escaped = escape_mdx_text_hazards(content)

    assert escaped == "<code>python -m venv venv&lt;br>source venv/bin/activate</code>"


def test_escape_mdx_text_hazards_escapes_json_like_table_cells() -> None:
    content = (
        '| `WishlistFactory.instantiate` | `middleware/WishlistMiddleware.py` | '
        '(None, {"user_id": ...}, context, sync=True) | Instantiates wishlist object. |'
    )

    escaped = escape_mdx_text_hazards(content)

    assert '&#123;"user_id": ...&#125;' in escaped


def test_escape_mdx_text_hazards_escapes_raw_object_literals_in_prose() -> None:
    content = "- **Returns:** { status: 'healthy' | 'degraded' | 'unhealthy', details: object }"

    escaped = escape_mdx_text_hazards(content)

    assert "&#123; status: 'healthy' | 'degraded' | 'unhealthy', details: object &#125;" in escaped


def test_escape_mdx_text_hazards_escapes_object_literals_split_by_inline_code() -> None:
    table_row = (
        '| `ValidationError` | Global handler | 400 | '
        '{ status: "error", `statusCode`: 400, message: ... } |'
    )
    prose_line = "- **Returns:** { status: `healthy`, details: object }"

    escaped_table = escape_mdx_text_hazards(table_row)
    escaped_prose = escape_mdx_text_hazards(prose_line)

    assert (
        "&#123; status: \"error\", `statusCode`: 400, message: ... &#125;"
        in escaped_table
    )
    assert "&#123; status: `healthy`, details: object &#125;" in escaped_prose


def test_escape_mdx_text_hazards_escapes_braces_inside_table_code_spans() -> None:
    content = (
        '| `/health` | Example | '
        '`{ status: "healthy", checks: { ... } }` |'
    )

    escaped = escape_mdx_text_hazards(content)

    assert "`&#123; status: \"healthy\", checks: &#123; ... &#125; &#125;`" in escaped


def test_repair_internal_doc_links_rewrites_aliases_using_page_titles() -> None:
    valid_urls, title_to_url, alias_map = build_internal_doc_link_maps(
        [
            ("System Architecture & Overview", "/"),
            ("Database & Schema", "/database-schema"),
            ("Setup & Configuration", "/setup"),
        ]
    )
    content = """
See [Database & Schema](/database-src) for details.
See [System Architecture & Overview](/architecture) first.
<Card title="Database & Schema" href="/database-src">
  Database docs
</Card>
"""

    repaired = repair_internal_doc_links(content, valid_urls, title_to_url, alias_map)

    assert "[Database & Schema](/database-schema)" in repaired
    assert "[System Architecture & Overview](/)" in repaired
    assert 'title="Database & Schema" href="/database-schema"' in repaired


def test_repair_internal_doc_links_strips_unresolvable_markdown_links() -> None:
    valid_urls, title_to_url, alias_map = build_internal_doc_link_maps(
        [("Overview", "/"), ("Setup", "/setup")]
    )
    content = "Read [Unknown Page](/missing-page) before setup."

    repaired = repair_internal_doc_links(content, valid_urls, title_to_url, alias_map)

    assert repaired == "Read Unknown Page before setup."


def test_repair_internal_doc_links_preserves_api_routes() -> None:
    valid_urls, title_to_url, alias_map = build_internal_doc_link_maps(
        [("Overview", "/"), ("Users API", "/api/get-users")]
    )
    content = "Use [GET /users](/api/get-users) for details."

    repaired = repair_internal_doc_links(content, valid_urls, title_to_url, alias_map)

    assert repaired == content


def test_ensure_mdx_frontmatter_normalizes_existing_yaml_scalars(
    tmp_path: Path,
) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    mdx_path = docs_dir / "start-here.mdx"
    mdx_path.write_text(
        """---
title: Start Here
description: Orientation for new developers: what this service does, who uses it.
---

# Start Here
""",
        encoding="utf-8",
    )

    _ensure_mdx_frontmatter(docs_dir)

    updated = mdx_path.read_text(encoding="utf-8")
    assert 'title: "Start Here"' in updated
    assert (
        'description: "Orientation for new developers: what this service does, who uses it."'
        in updated
    )


def test_ensure_mdx_frontmatter_preserves_deepdoc_provenance_fields(
    tmp_path: Path,
) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    mdx_path = docs_dir / "auth.mdx"
    mdx_path.write_text(
        """---
title: Auth
deepdoc_generated_commit: "abc1234"
deepdoc_status: "valid"
deepdoc_evidence_files:
  - "src/auth.py"
---

# Auth
""",
        encoding="utf-8",
    )

    _ensure_mdx_frontmatter(docs_dir)

    updated = mdx_path.read_text(encoding="utf-8")
    assert 'deepdoc_generated_commit: "abc1234"' in updated
    assert 'deepdoc_status: "valid"' in updated
    assert '  - "src/auth.py"' in updated


def test_ensure_mdx_frontmatter_moves_leaked_body_out_of_yaml_frontmatter(
    tmp_path: Path,
) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    mdx_path = docs_dir / "background-jobs.mdx"
    mdx_path.write_text(
        """---
title: "Background Jobs"
description: "Auto-generated developer documentation"
# Background Jobs & Runtime

This page documents the asynchronous runtime surfaces.

<Callout>
If you are looking for Django management commands, see [Django Commands & Signals](/background-jobs-django).
</Callout>
---

## Overview
""",
        encoding="utf-8",
    )

    _ensure_mdx_frontmatter(docs_dir)

    updated = mdx_path.read_text(encoding="utf-8")
    frontmatter, body = updated.split("\n---\n\n", 1)
    assert '# Background Jobs & Runtime' not in frontmatter
    assert 'title: "Background Jobs"' in frontmatter
    assert 'description: "Auto-generated developer documentation"' in frontmatter
    assert body.startswith("# Background Jobs & Runtime")
    assert "<Callout>" in body
    assert "## Overview" in body


def test_endpoint_ref_slug_strips_angle_bracket_path_converters() -> None:
    assert (
        _endpoint_ref_slug("GET", "/get-prod-variants/<str:prod_slug>")
        == "get-get-prod-variants-str-prod_slug"
    )


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


def test_fix_mermaid_diagram_quotes_flowchart_labels_with_html_breaks_and_parentheses() -> (
    None
):
    diagram = """flowchart LR
    A[Application Code<br>(SyncWeightOfOrder.py,<br>fast_queue.py)]
    B[requests Library]
    A --> B
"""

    fixed = _fix_mermaid_diagram(diagram)

    assert 'A["Application Code<br>(SyncWeightOfOrder.py,<br>fast_queue.py)"]' in fixed
    assert "A --> B" in fixed


def test_fix_mermaid_diagram_rewrites_reverse_flowchart_edges() -> None:
    diagram = """flowchart TD
    D <-- H
"""

    fixed = _fix_mermaid_diagram(diagram)

    assert "H --> D" in fixed
    assert "D <-- H" not in fixed


def test_fix_mermaid_diagram_rewrites_quoted_flowchart_edge_labels() -> None:
    diagram = """flowchart TD
    A -- "forks" --> B
"""

    fixed = _fix_mermaid_diagram(diagram)

    assert "A -->|forks| B" in fixed
    assert '-- "forks" -->' not in fixed


def test_fix_mermaid_diagram_rewrites_bidirectional_flowchart_edges() -> None:
    diagram = """flowchart TD
    App <--> DB
"""

    fixed = _fix_mermaid_diagram(diagram)

    assert "App --> DB" in fixed
    assert "DB --> App" in fixed
    assert "<-->" not in fixed


def test_fix_mermaid_diagram_strips_quotes_from_class_diagram_targets() -> None:
    diagram = """classDiagram
    MySQLCart --> "CartSerializer"
"""

    fixed = _fix_mermaid_diagram(diagram)

    assert "MySQLCart --> CartSerializer" in fixed
    assert '"CartSerializer"' not in fixed


def test_fix_mermaid_diagram_strips_quotes_from_simple_state_ids() -> None:
    diagram = """stateDiagram-v2
    Open --> "InProgress": updateOneDirectComplaint
    "InProgress" --> Closed: closeOneDirectTicket
"""

    fixed = _fix_mermaid_diagram(diagram)

    assert "Open --> InProgress: updateOneDirectComplaint" in fixed
    assert "InProgress --> Closed: closeOneDirectTicket" in fixed


def test_fix_mermaid_diagram_strips_erdiagram_placeholders_and_rewrites_comments() -> (
    None
):
    diagram = """erDiagram
  ORDERS {
    bigint id PK
    datetime created_at
    ...
  }
  -- MongoDB (denormalized, flexible)
  PRODUCTSV2 {
    int id PK
    ... "Flexible fields"
    Any    ... "Flexible fields (non-strict schema)"
  }
"""

    fixed = _fix_mermaid_diagram(diagram)

    assert "\n    ...\n" not in fixed
    assert '... "Flexible fields"' not in fixed
    assert 'Any    ... "Flexible fields (non-strict schema)"' not in fixed
    assert "%% MongoDB (denormalized, flexible)" in fixed


def test_fix_mermaid_diagram_sanitizes_flowchart_edge_labels_with_punctuation() -> None:
    diagram = """flowchart TD
    Client -->|HTTP (REST/Webhook)| API
    Inventory -->|DB/Cache| DB
"""

    fixed = _fix_mermaid_diagram(diagram)

    assert "Client -->|HTTP REST Webhook| API" in fixed
    assert "Inventory -->|DB Cache| DB" in fixed
