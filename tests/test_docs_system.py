"""Tests for doc role classification and documentation-system detection."""

from __future__ import annotations

import tempfile
from pathlib import Path

from deepdoc.docs_system import (
    DocRole,
    DocumentationSystem,
    classify_doc_role,
    detect_docs_system,
    _is_ai_derived,
    _is_deepdoc_owned,
)


class TestDocRoleClassification:
    def test_authored_doc_in_docs_path(self):
        role = classify_doc_role("docs/en/docs/index.md", "# Architecture\nContent")
        assert role == DocRole.AUTHORED

    def test_root_readme(self):
        role = classify_doc_role("README.md", "# Project\nDescription")
        assert role == DocRole.AUTHORED

    def test_contributing_md(self):
        role = classify_doc_role("CONTRIBUTING.md", "# Contributing\nGuidelines")
        assert role == DocRole.AUTHORED

    def test_mkdocs_yml_is_docs_config(self):
        role = classify_doc_role("docs/en/mkdocs.yml", "site_name: Test\nsite_url: https://test.com")
        assert role == DocRole.DOCS_CONFIG

    def test_mkdocs_yaml_is_docs_config(self):
        role = classify_doc_role("docs/mkdocs.yaml", "site_name: Test\n")
        assert role == DocRole.DOCS_CONFIG

    def test_deepdoc_generated_is_ai_derived(self):
        role = classify_doc_role(
            "docs/routing.md",
            "---\ndeepdoc_generated_version: 1.0\n---\n# Routing\n",
        )
        assert role == DocRole.AI_DERIVED

    def test_deepdoc_generated_at_is_ai_derived(self):
        role = classify_doc_role(
            "docs/index.md",
            "---\ndeepdoc_generated_at: 2026-01-01\n---\n# Overview\n",
        )
        assert role == DocRole.AI_DERIVED

    def test_deepwiki_export_is_ai_derived(self):
        role = classify_doc_role(
            "docs/export.md",
            "Source: https://deepwiki.com/fastapi/fastapi\n\n# Content\n",
        )
        assert role == DocRole.AI_DERIVED

    def test_normal_markdown_is_not_ai_derived(self):
        role = classify_doc_role(
            "docs/architecture.md",
            "# Architecture\nOur design uses FastAPI and Starlette.\n",
        )
        assert role == DocRole.AUTHORED

    def test_site_dir_is_built_site(self):
        role = classify_doc_role("site/index.html", source_kind="product", site_dir="site")
        assert role == DocRole.BUILT_SITE

    def test_built_site_with_configured_dir(self):
        role = classify_doc_role("deepdoc-site/index.html", site_dir="deepdoc-site")
        assert role == DocRole.BUILT_SITE

    def test_product_source_is_not_a_doc(self):
        role = classify_doc_role("src/main.py", "def f(): pass\n")
        assert role == ""

    def test_config_file_is_not_a_doc(self):
        role = classify_doc_role("pyproject.toml", source_kind="config")
        assert role == ""

    def test_docusaurus_config(self):
        role = classify_doc_role("website/docusaurus.config.js", source_kind="product")
        assert role == DocRole.DOCS_CONFIG


class TestAIDerivedDetection:
    def test_deepdoc_generated_version_detected(self):
        assert _is_ai_derived("---\ndeepdoc_generated_version: 0.5.0\n---\n")
        assert _is_ai_derived("deepdoc_generated_at: 2026-01-01T00:00:00Z\n")
        assert _is_ai_derived("\n\ndeepdoc_generated_version: 1.0\n")

    def test_deepwiki_url_detected(self):
        assert _is_ai_derived("Source: https://deepwiki.com/fastapi/fastapi\n")
        assert _is_ai_derived("link: https://deepwiki.com/foo/bar")

    def test_normal_content_not_flagged(self):
        assert not _is_ai_derived("## Architecture\nWe use FastAPI.\n")
        assert not _is_ai_derived("# My Documentation\n\nContent here.\n")

    def test_deepdoc_owned(self):
        assert _is_deepdoc_owned("---\ndeepdoc_generated_version: 1.0\n---\n")
        assert not _is_deepdoc_owned("# Normal docs\nContent here.\n")


class TestMkDocsDetection:
    def test_mkdocs_system_detected(self):
        file_tree = {"docs/en": ["mkdocs.yml", "docs/index.md"], "src": ["app.py"]}
        file_contents = {
            "docs/en/mkdocs.yml": "site_name: Test\nsite_url: https://test.com\n",
            "docs/en/docs/index.md": "# Test Docs\nContent\n",
            "src/app.py": "def f(): pass\n",
        }
        source_kinds = {
            "docs/en/mkdocs.yml": "config",
            "docs/en/docs/index.md": "docs",
            "src/app.py": "product",
        }
        doc_roles = {
            "docs/en/mkdocs.yml": DocRole.DOCS_CONFIG,
            "docs/en/docs/index.md": DocRole.AUTHORED,
        }
        system = detect_docs_system(
            Path("."),
            file_tree,
            file_contents,
            source_kinds,
            doc_roles,
            config_files=["docs/en/mkdocs.yml"],
        )
        assert system.detected
        assert system.kind == "mkdocs_zensical"
        assert "docs/en/mkdocs.yml" in system.config_files

    def test_no_mkdocs_when_no_config(self):
        file_tree = {"src": ["app.py"]}
        file_contents = {"src/app.py": "def f(): pass\n"}
        system = detect_docs_system(
            Path("."),
            file_tree,
            file_contents,
            {"src/app.py": "product"},
            {},
            config_files=[],
        )
        assert not system.detected
        assert system.kind == "none"

    def test_mkdocs_with_translations(self):
        file_tree = {
            "docs/en": ["mkdocs.yml", "docs/index.md"],
            "docs/de": ["mkdocs.yml", "docs/index.md"],
            "docs/fr": ["mkdocs.yml", "docs/index.md"],
        }
        file_contents = {
            "docs/en/mkdocs.yml": "site_name: Test\n",
            "docs/en/docs/index.md": "# English\n",
            "docs/de/mkdocs.yml": "INHERIT: ../en/mkdocs.yml\n",
            "docs/de/docs/index.md": "# German\n",
            "docs/fr/mkdocs.yml": "INHERIT: ../en/mkdocs.yml\n",
            "docs/fr/docs/index.md": "# French\n",
        }
        source_kinds = {
            "docs/en/mkdocs.yml": "config",
            "docs/en/docs/index.md": "docs",
            "docs/de/mkdocs.yml": "config",
            "docs/de/docs/index.md": "docs",
            "docs/fr/mkdocs.yml": "config",
            "docs/fr/docs/index.md": "docs",
        }
        doc_roles = {
            "docs/en/mkdocs.yml": DocRole.DOCS_CONFIG,
            "docs/en/docs/index.md": DocRole.AUTHORED,
            "docs/de/mkdocs.yml": DocRole.DOCS_CONFIG,
            "docs/de/docs/index.md": DocRole.AUTHORED,
            "docs/fr/mkdocs.yml": DocRole.DOCS_CONFIG,
            "docs/fr/docs/index.md": DocRole.AUTHORED,
        }
        system = detect_docs_system(
            Path("."),
            file_tree,
            file_contents,
            source_kinds,
            doc_roles,
            config_files=["docs/en/mkdocs.yml", "docs/de/mkdocs.yml", "docs/fr/mkdocs.yml"],
        )
        assert system.detected
        assert system.kind == "mkdocs_zensical"
        assert len(system.translation_roots) >= 2


class TestDocusaurusDetection:
    def test_docusaurus_system_detected(self):
        file_contents = {
            "website/docusaurus.config.js": "module.exports = { title: 'Test' };\n",
            "website/docs/intro.md": "# Intro\n",
        }
        source_kinds = {
            "website/docusaurus.config.js": "config",
            "website/docs/intro.md": "docs",
        }
        doc_roles = {
            "website/docusaurus.config.js": DocRole.DOCS_CONFIG,
            "website/docs/intro.md": DocRole.AUTHORED,
        }
        system = detect_docs_system(
            Path("."),
            {"website": ["docusaurus.config.js", "docs/intro.md"]},
            file_contents,
            source_kinds,
            doc_roles,
            config_files=["website/docusaurus.config.js"],
        )
        assert system.detected
        assert system.kind == "docusaurus"
        assert "website/docusaurus.config.js" in system.config_files