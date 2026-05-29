from __future__ import annotations

import json
from pathlib import Path

from deepdoc.generator import (
    _fix_mermaid_diagram,
    build_internal_doc_link_maps,
    normalize_code_fence_languages,
    normalize_explanatory_lines_outside_fences,
    normalize_html_code_blocks,
    repair_split_object_code_fences,
    repair_dangling_plain_fences,
    repair_internal_doc_links,
    repair_unbalanced_code_fences,
)
from deepdoc.pipeline_v2 import _endpoint_ref_slug, stage_openapi_assets
from deepdoc.prompts import (
    DEBUG_RUNBOOK_V2,
    DOMAIN_GLOSSARY_V2,
    ENDPOINT_BUCKET_V2,
    ENDPOINT_REF_V2,
    START_HERE_INDEX_V2,
    START_HERE_SETUP_V2,
    SYSTEM_V2,
)
from deepdoc.site.builder import _ensure_md_frontmatter, build_mkdocs_from_plan
from tests.conftest import make_bucket, make_plan


def test_build_mkdocs_from_plan_creates_site_scaffold(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    output_dir = repo_root / "docs"
    output_dir.mkdir()

    # Stage an OpenAPI spec so the Swagger UI page is generated.
    (repo_root / "site" / "openapi").mkdir(parents=True)
    (repo_root / "site" / "openapi" / "spec.json").write_text(
        json.dumps(
            {"openapi": "3.0.0", "info": {"title": "T", "version": "1"}, "paths": {}}
        ),
        encoding="utf-8",
    )
    # Leftover Fumadocs artifacts that the builder must clean up.
    (repo_root / "site" / "next.config.mjs").write_text("// old", encoding="utf-8")
    (repo_root / "site" / "app").mkdir()
    (repo_root / "site" / "app" / "layout.tsx").write_text("x", encoding="utf-8")

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

    (output_dir / "auth.md").write_text("# Auth\n", encoding="utf-8")

    build_mkdocs_from_plan(
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

    mkdocs_yml = (repo_root / "site" / "mkdocs.yml").read_text(encoding="utf-8")
    extra_css = (repo_root / "site" / "docs" / "stylesheets" / "extra.css").read_text(
        encoding="utf-8"
    )

    # Core scaffold files exist.
    assert (output_dir / "index.md").exists()
    assert (repo_root / "site" / "mkdocs.yml").exists()

    # mkdocs.yml has the expected Material + pymdownx configuration.
    assert 'site_name: "Demo"' in mkdocs_yml
    assert "name: material" in mkdocs_yml
    assert "pymdownx.blocks.admonition" in mkdocs_yml
    assert "pymdownx.blocks.details" in mkdocs_yml
    assert "pymdownx.blocks.tab" in mkdocs_yml
    assert "format: !!python/name:pymdownx.superfences.fence_code_format" in mkdocs_yml
    assert "site_dir: out" in mkdocs_yml

    # Nav reflects the plan; endpoint_ref is consolidated into the API page.
    assert "Auth: auth.md" in mkdocs_yml
    assert "API Reference: api.md" in mkdocs_yml
    assert "get-order.md" not in mkdocs_yml

    # OpenAPI page + plugin wired in.
    assert "swagger-ui-tag" in mkdocs_yml
    assert (output_dir / "api.md").exists()
    assert "<swagger-ui src=" in (output_dir / "api.md").read_text(encoding="utf-8")
    assert (output_dir / "openapi" / "spec.json").exists()

    # Brand colors mapped onto Material's CSS variables.
    assert "--md-primary-fg-color: #EB3E25;" in extra_css

    # Chatbot disabled → no chatbot page.
    assert not (output_dir / "ask").exists()

    # Fumadocs/Next.js artifacts removed; no stray root files.
    assert not (repo_root / "site" / "next.config.mjs").exists()
    assert not (repo_root / "site" / "app").exists()
    assert not (repo_root / "site" / "package.json").exists()
    assert not (repo_root / "mint.json").exists()

    auth_doc = (output_dir / "auth.md").read_text(encoding="utf-8")
    assert auth_doc.startswith("---\n")
    assert 'title: "Auth"' in auth_doc
    assert 'title: "Demo"' in (output_dir / "index.md").read_text(encoding="utf-8")



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


def test_build_mkdocs_preserves_handwritten_index_without_frontmatter(
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
    (output_dir / "index.md").write_text(custom_index, encoding="utf-8")
    (output_dir / "auth.md").write_text("# Auth\n", encoding="utf-8")

    build_mkdocs_from_plan(
        repo_root,
        output_dir,
        {"project_name": "Demo"},
        plan,
        has_openapi=False,
    )

    index_text = (output_dir / "index.md").read_text(encoding="utf-8")
    auth_doc = (output_dir / "auth.md").read_text(encoding="utf-8")

    assert index_text.startswith("---\n")
    assert 'title: "Custom landing"' in index_text
    assert "_deepdoc_autogen_" not in index_text
    assert index_text.endswith(custom_index)
    assert auth_doc.startswith("---\n")


def test_build_mkdocs_repairs_malformed_index_frontmatter(tmp_path: Path) -> None:
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
    (output_dir / "index.md").write_text(malformed_index, encoding="utf-8")
    (output_dir / "auth.md").write_text("# Auth\n", encoding="utf-8")

    build_mkdocs_from_plan(
        repo_root,
        output_dir,
        {"project_name": "Demo"},
        plan,
        has_openapi=False,
    )

    index_text = (output_dir / "index.md").read_text(encoding="utf-8")

    assert index_text.startswith("---\n")
    assert 'title: "System Architecture & Overview"' in index_text
    assert "_deepdoc_autogen_" not in index_text
    assert "# System Architecture & Overview" in index_text
    assert "A real-time POS backend." in index_text
    assert "## What This Does" in index_text


def test_build_mkdocs_without_openapi_omits_api_page(
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

    (output_dir / "auth.md").write_text("# Auth\n", encoding="utf-8")

    build_mkdocs_from_plan(
        repo_root,
        output_dir,
        {"project_name": "Demo"},
        plan,
        has_openapi=False,
    )

    mkdocs_yml = (repo_root / "site" / "mkdocs.yml").read_text(encoding="utf-8")
    assert not (output_dir / "api.md").exists()
    assert not (output_dir / "openapi").exists()
    assert "swagger-ui-tag" not in mkdocs_yml
    assert "API Reference: api.md" not in mkdocs_yml


def test_build_mkdocs_renders_swagger_page_from_staged_spec(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    output_dir = repo_root / "docs"
    output_dir.mkdir()
    (repo_root / "site" / "openapi").mkdir(parents=True)
    # manifest.json is excluded; the real spec drives the Swagger page.
    (repo_root / "site" / "openapi" / "manifest.json").write_text("[]", encoding="utf-8")
    (repo_root / "site" / "openapi" / "deepdoc-openapi-0-health.json").write_text(
        json.dumps(
            {"openapi": "3.0.0", "info": {"title": "Health", "version": "1"}, "paths": {}}
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

    (output_dir / "index.md").write_text("# Overview\n", encoding="utf-8")
    (output_dir / "operations-health.md").write_text("# Health\n", encoding="utf-8")

    build_mkdocs_from_plan(
        repo_root,
        output_dir,
        {"project_name": "Demo"},
        plan,
        has_openapi=True,
    )

    mkdocs_yml = (repo_root / "site" / "mkdocs.yml").read_text(encoding="utf-8")
    api_md = (output_dir / "api.md").read_text(encoding="utf-8")
    assert "swagger-ui-tag" in mkdocs_yml
    assert "API Reference: api.md" in mkdocs_yml
    assert '<swagger-ui src="openapi/deepdoc-openapi-0-health.json"/>' in api_md
    assert (output_dir / "openapi" / "deepdoc-openapi-0-health.json").exists()
    # The manifest itself must not be copied or rendered as a spec.
    assert not (output_dir / "openapi" / "manifest.json").exists()


def test_prompts_use_mkdocs_blocks_syntax() -> None:
    # MkDocs Material pymdownx Blocks syntax is taught.
    assert "/// note" in SYSTEM_V2
    assert "/// tab |" in SYSTEM_V2
    assert "/// details |" in SYSTEM_V2
    assert "grid cards" in SYSTEM_V2

    # Fumadocs remark-directives are not used as worked examples. They may only
    # appear inside the explicit "NEVER write ..." prohibition line, so check for
    # the directive at the start of a content line (how an example would appear).
    for directive in ("\n:::cards", "\n:::steps", "\n:::accordions", "\n::step", "\n::card"):
        assert directive not in SYSTEM_V2, f"unexpected directive example {directive!r}"

    # Mintlify JSX components never appear at all.
    assert "<CardGroup" not in SYSTEM_V2
    assert "<AccordionGroup" not in SYSTEM_V2
    assert "Mintlify" not in SYSTEM_V2

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
            "source_spec": manifest[0]["source_spec"],
            "source_path": "openapi.json",
        }
    ]
    assert manifest[0]["source_spec"].startswith("deepdoc-openapi-")


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
            "source_spec": manifest[0]["source_spec"],
            "source_path": "openapi.yaml",
        }
    ]


def test_stage_openapi_assets_stages_multiple_specs(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "orders.openapi.json").write_text(
        json.dumps(
            {
                "openapi": "3.1.0",
                "info": {"title": "Orders", "version": "1.0.0"},
                "paths": {"/orders": {"get": {"summary": "List orders", "responses": {"200": {"description": "ok"}}}}},
            }
        ),
        encoding="utf-8",
    )
    (repo_root / "billing.openapi.json").write_text(
        json.dumps(
            {
                "openapi": "3.1.0",
                "info": {"title": "Billing", "version": "1.0.0"},
                "paths": {"/invoices": {"post": {"summary": "Create invoice", "responses": {"200": {"description": "ok"}}}}},
            }
        ),
        encoding="utf-8",
    )

    assert stage_openapi_assets(
        repo_root, ["orders.openapi.json", "billing.openapi.json"]
    ) is True

    manifest = json.loads(
        (repo_root / "site" / "openapi" / "manifest.json").read_text(encoding="utf-8")
    )
    assert {entry["slug"] for entry in manifest} == {"get-orders", "post-invoices"}
    assert {entry["source_path"] for entry in manifest} == {
        "orders.openapi.json",
        "billing.openapi.json",
    }
    staged_specs = sorted((repo_root / "site" / "openapi").glob("deepdoc-openapi-*"))
    assert len(staged_specs) == 2


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

    assert "[Database & Schema](database-schema.md)" in repaired
    assert "[System Architecture & Overview](index.md)" in repaired
    assert 'title="Database & Schema" href="database-schema.md"' in repaired


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
    mdx_path = docs_dir / "start-here.md"
    mdx_path.write_text(
        """---
title: Start Here
description: Orientation for new developers: what this service does, who uses it.
---

# Start Here
""",
        encoding="utf-8",
    )

    _ensure_md_frontmatter(docs_dir)

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
    mdx_path = docs_dir / "auth.md"
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

    _ensure_md_frontmatter(docs_dir)

    updated = mdx_path.read_text(encoding="utf-8")
    assert 'deepdoc_generated_commit: "abc1234"' in updated
    assert 'deepdoc_status: "valid"' in updated
    assert '  - "src/auth.py"' in updated


def test_ensure_mdx_frontmatter_moves_leaked_body_out_of_yaml_frontmatter(
    tmp_path: Path,
) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    mdx_path = docs_dir / "background-jobs.md"
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

    _ensure_md_frontmatter(docs_dir)

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
