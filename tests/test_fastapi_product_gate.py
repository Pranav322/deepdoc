"""End-to-end product regression for the FastAPI failure pattern.

This fixture mirrors the conditions that made the original FastAPI run unsafe:
tracked MkDocs authored docs, an old generated site root, an AI-derived export,
and a legacy ``docs``/``site`` configuration. It uses a deterministic pipeline
double so the product contract is tested without LLM credentials.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from deepdoc import cli
from deepdoc.config import load_config
from deepdoc.docs_system import DocRole, detect_docs_system
from deepdoc.generator.claims import Claim, ClaimValidator
from deepdoc.generator.post_processors import inject_source_citations
from deepdoc.planner import scan_repo
from deepdoc.repo_model import build_repo_model_from_scan
from deepdoc.site.builder.next_builder import _build_nav
from deepdoc.v2_models import DocBucket, DocPlan


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _create_fastapi_shaped_repo(root: Path) -> None:
    (root / "fastapi").mkdir()
    (root / "fastapi" / "app.py").write_text(
        "from fastapi import FastAPI\n\napp = FastAPI()\n\n"
        "@app.get('/health')\ndef health():\n    return {'ok': True}\n"
    )
    (root / "docs").mkdir()
    (root / "docs" / "index.md").write_text("# FastAPI Authored Guide\n")
    (root / "docs" / "translation-de.md").write_text("# Deutsche Anleitung\n")
    (root / "docs" / "deepwiki-export.md").write_text(
        "Source: https://deepwiki.com/tiangolo/fastapi\n\n# Stale AI Export\n"
    )
    (root / "mkdocs.yml").write_text("site_name: FastAPI\nnav:\n  - Home: index.md\n")
    (root / "site").mkdir()
    (root / "site" / "index.html").write_text("<html>old authored build</html>\n")
    (root / ".deepdoc.yaml").write_text(
        "project_name: FastAPI-shaped\n"
        "output_dir: docs\n"
        "site_dir: site\n"
        "llm:\n  provider: anthropic\n  model: claude-test\n"
    )
    _git(root, "init")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "initial")


def _bucket(slug: str, title: str, parent_slug: str | None = None) -> DocBucket:
    return DocBucket(
        bucket_type="feature",
        title=title,
        slug=slug,
        section="Architecture",
        description="",
        parent_slug=parent_slug,
    )


def test_fastapi_product_gate(monkeypatch, tmp_path: Path) -> None:
    _create_fastapi_shaped_repo(tmp_path)
    authored_before = (tmp_path / "docs" / "index.md").read_bytes()
    translation_before = (tmp_path / "docs" / "translation-de.md").read_bytes()
    mkdocs_before = (tmp_path / "mkdocs.yml").read_bytes()
    site_before = (tmp_path / "site" / "index.html").read_bytes()
    captured: dict[str, object] = {}

    class FakePipeline:
        def __init__(self, repo_root: Path, cfg: dict):
            captured["repo_root"] = repo_root
            captured["cfg"] = cfg

        def run(self, force: bool, reconcile: bool) -> dict:
            captured["force"] = force
            captured["reconcile"] = reconcile
            return {"pages_failed": 0, "pages_invalid": 0, "pages_degraded": 0}

    import deepdoc.pipeline_v2 as pipeline_v2

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pipeline_v2, "PipelineV2", FakePipeline)

    result = CliRunner().invoke(cli.main, ["generate", "--clean", "--yes"])

    assert result.exit_code == 0, result.output
    assert captured["cfg"]["output_dir"] == "deepdoc-docs"
    assert captured["cfg"]["site_dir"] == "deepdoc-site"
    assert captured["force"] is True
    assert captured["reconcile"] is False

    # Authored FastAPI assets survive the full clean/migration workflow.
    assert (tmp_path / "docs" / "index.md").read_bytes() == authored_before
    assert (tmp_path / "docs" / "translation-de.md").read_bytes() == translation_before
    assert (tmp_path / "mkdocs.yml").read_bytes() == mkdocs_before
    assert (tmp_path / "site" / "index.html").read_bytes() == site_before

    persisted = load_config(tmp_path / ".deepdoc.yaml")
    assert persisted["output_dir"] == "deepdoc-docs"
    assert persisted["site_dir"] == "deepdoc-site"

    scan = scan_repo(tmp_path, persisted)
    assert scan.doc_role_by_file["docs/index.md"] == DocRole.AUTHORED
    assert scan.doc_role_by_file["docs/deepwiki-export.md"] == DocRole.AI_DERIVED
    assert "docs/index.md" in scan.doc_contexts
    assert "docs/deepwiki-export.md" not in scan.doc_contexts

    docs_system = detect_docs_system(
        tmp_path,
        scan.file_tree,
        scan.file_contents,
        scan.source_kind_by_file,
        scan.doc_role_by_file,
        scan.config_files,
    )
    assert docs_system.detected
    assert docs_system.source_roots == ["docs"]

    # Both parent and child must be emitted to recursive nav data.
    parent = _bucket("security", "Security")
    child = _bucket("security-oauth", "OAuth", parent_slug="security")
    plan = DocPlan(
        buckets=[parent, child],
        nav_structure={
            "Architecture": [{
                "parent_slug": "security",
                "display_title": "Security",
                "children": ["security-oauth"],
            }]
        },
        skipped_files=[],
    )
    nav = _build_nav(plan, has_openapi=False)
    group = next(entry for entry in nav if entry.get("title") == "Architecture")["items"][0]
    assert [item["slug"] for item in group["items"]] == ["security", "security-oauth"]

    # Invalid claims are authoritative and citations remain safe in frontmatter/code.
    model = build_repo_model_from_scan(scan, str(tmp_path))
    claims = [Claim("route", "GET /missing")] * 5
    claim_result = ClaimValidator(scan, model).validate(claims)
    assert not claim_result.is_valid
    cited = inject_source_citations(
        "---\ndescription: `fastapi/app.py:1`\n---\n"
        "See `fastapi/app.py:1`.\n```python\n`fastapi/app.py:1`\n```\n",
        {"fastapi/app.py"},
        git_remote="git@github.com:tiangolo/fastapi.git",
        commit_sha="abc1234",
    )
    assert "description: `fastapi/app.py:1`" in cited
    assert cited.count("github.com/tiangolo/fastapi/blob/abc1234/fastapi/app.py#L1") == 1
    assert "```python\n`fastapi/app.py:1`\n```" in cited

    # The migration itself is idempotent: no authored files changed in Git.
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert " docs/" not in status
    assert "mkdocs.yml" not in status
    assert " site/" not in status
