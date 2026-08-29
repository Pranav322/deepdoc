from __future__ import annotations

from pathlib import Path
import subprocess

import click
import pytest

from deepdoc.output_safety import (
    assert_safe_for_generation,
    clean_owned_outputs,
    inspect_output_root,
    record_output_ownership,
    resolve_output_paths,
)


def _init_git(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "initial"],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _cfg(output_dir: str = "deepdoc-docs", site_dir: str = "deepdoc-site") -> dict:
    return {"output_dir": output_dir, "site_dir": site_dir}


def test_paths_are_repository_relative_and_non_overlapping(tmp_path: Path) -> None:
    paths = resolve_output_paths(tmp_path, _cfg())
    assert paths.output_dir == tmp_path / "deepdoc-docs"
    assert paths.site_dir == tmp_path / "deepdoc-site"

    with pytest.raises(click.ClickException):
        resolve_output_paths(tmp_path, _cfg("../outside"))
    with pytest.raises(click.ClickException):
        resolve_output_paths(tmp_path, _cfg("/tmp/outside"))
    with pytest.raises(click.ClickException):
        resolve_output_paths(tmp_path, _cfg(".", "deepdoc-site"))
    with pytest.raises(click.ClickException):
        resolve_output_paths(tmp_path, _cfg("deepdoc-docs", "deepdoc-docs/site"))


def test_tracked_authored_docs_block_generation(tmp_path: Path) -> None:
    authored = tmp_path / "docs" / "en" / "docs" / "index.md"
    authored.parent.mkdir(parents=True)
    authored.write_text("# Authored docs\n")
    _init_git(tmp_path)

    with pytest.raises(click.ClickException, match="Refusing to write"):
        assert_safe_for_generation(tmp_path, _cfg("docs", "deepdoc-site"))
    assert authored.exists()


def test_tracked_site_blocks_generation(tmp_path: Path) -> None:
    authored = tmp_path / "site" / "index.html"
    authored.parent.mkdir(parents=True)
    authored.write_text("authored build output")
    _init_git(tmp_path)

    with pytest.raises(click.ClickException, match="Refusing to write"):
        assert_safe_for_generation(tmp_path, _cfg("deepdoc-docs", "site"))
    assert authored.exists()


def test_ownership_manifest_allows_exact_generated_files(tmp_path: Path) -> None:
    paths = resolve_output_paths(tmp_path, _cfg())
    paths.output_dir.mkdir()
    page = paths.output_dir / "index.md"
    page.write_text("---\ndeepdoc_generated_version: 1.0\n---\n# Generated\n")
    paths.site_dir.mkdir()
    config = paths.site_dir / "deepdoc.config.json"
    config.write_text("{}")

    record_output_ownership(
        tmp_path,
        paths,
        output_files={page},
        site_files={config},
    )

    output = inspect_output_root(tmp_path, paths.output_dir, kind="output")
    site = inspect_output_root(tmp_path, paths.site_dir, kind="site")
    assert output.state == "deepdoc_only"
    assert site.state == "deepdoc_only"
    assert_safe_for_generation(tmp_path, _cfg())


def test_clean_owned_outputs_preserves_authored_neighbors(tmp_path: Path) -> None:
    paths = resolve_output_paths(tmp_path, _cfg("docs", "deepdoc-site"))
    paths.output_dir.mkdir()
    generated = paths.output_dir / "generated.md"
    generated.write_text("---\ndeepdoc_generated_version: 1.0\n---\n# Generated\n")
    authored = paths.output_dir / "architecture.md"
    authored.write_text("# Authored\n")

    record_output_ownership(
        tmp_path,
        paths,
        output_files={generated},
        site_files=set(),
    )
    removed, preserved = clean_owned_outputs(tmp_path, _cfg("docs", "deepdoc-site"))

    assert generated in removed
    assert not generated.exists()
    assert authored.exists()
    assert authored in preserved


def test_modified_owned_file_becomes_unmanaged_and_is_preserved(tmp_path: Path) -> None:
    paths = resolve_output_paths(tmp_path, _cfg())
    paths.site_dir.mkdir()
    layout = paths.site_dir / "app" / "layout.tsx"
    layout.parent.mkdir()
    layout.write_text("generated layout")
    record_output_ownership(
        tmp_path,
        paths,
        output_files=set(),
        site_files={layout},
    )

    layout.write_text("custom layout")
    inspection = inspect_output_root(tmp_path, paths.site_dir, kind="site")
    assert layout in inspection.unmanaged_files

    removed, preserved = clean_owned_outputs(tmp_path, _cfg())
    assert layout not in removed
    assert layout in preserved
    assert layout.read_text() == "custom layout"


def test_legacy_site_preserves_modified_template_file(tmp_path: Path) -> None:
    paths = resolve_output_paths(tmp_path, _cfg())
    layout = paths.site_dir / "app" / "layout.tsx"
    layout.parent.mkdir(parents=True)
    layout.write_text("// custom legacy layout")
    (paths.site_dir / "deepdoc.config.json").write_text("{}")

    inspection = inspect_output_root(tmp_path, paths.site_dir, kind="site")
    assert layout in inspection.unmanaged_files

    removed, preserved = clean_owned_outputs(tmp_path, _cfg())
    assert layout not in removed
    assert layout in preserved
    assert layout.exists()


def test_legacy_generated_markdown_can_be_cleaned_without_ownership_file(tmp_path: Path) -> None:
    paths = resolve_output_paths(tmp_path, _cfg("docs", "deepdoc-site"))
    paths.output_dir.mkdir()
    generated = paths.output_dir / "legacy.md"
    generated.write_text("---\ndeepdoc_generated_at: 2026-01-01\n---\n# Generated\n")

    removed, _ = clean_owned_outputs(tmp_path, _cfg("docs", "deepdoc-site"))

    assert generated in removed
    assert not generated.exists()


def test_openapi_assets_use_configured_site_directory(tmp_path: Path) -> None:
    from deepdoc.pipeline_v2 import stage_openapi_assets

    spec = tmp_path / "openapi.json"
    spec.write_text(
        '{"openapi":"3.0.0","info":{"title":"Test","version":"1"},'
        '"paths":{"/health":{"get":{"responses":{"200":{"description":"ok"}}}}}}'
    )
    custom_site = tmp_path / "deepdoc-site"

    staged = stage_openapi_assets(
        tmp_path,
        openapi_paths=["openapi.json"],
        site_dir=custom_site,
    )

    assert staged
    assert (custom_site / "openapi" / "manifest.json").is_file()
    assert not (tmp_path / "site").exists()


def test_pipeline_records_generated_output_ownership(tmp_path: Path) -> None:
    from deepdoc.pipeline_v2 import PipelineV2
    from deepdoc.v2_models import DocPlan

    output_dir = tmp_path / "deepdoc-docs"
    output_dir.mkdir()
    page = output_dir / "index.md"
    page.write_text("---\ndeepdoc_generated_version: 1.0\n---\n# Generated\n")
    whats_changed = output_dir / "whats-changed.md"
    whats_changed.write_text("# What's Changed\n")
    cfg = {
        "output_dir": "deepdoc-docs",
        "site_dir": "deepdoc-site",
        "llm": {"provider": "anthropic", "model": "test"},
    }
    pipeline = PipelineV2(tmp_path, cfg)
    plan = DocPlan(buckets=[], nav_structure={}, skipped_files=[])

    pipeline._build_site(plan, has_openapi=False)

    ownership = (tmp_path / ".deepdoc" / "output_ownership.json").read_text()
    assert "deepdoc-docs/index.md" in ownership
    assert "deepdoc-docs/whats-changed.md" in ownership
    assert "deepdoc-site/deepdoc.config.json" in ownership
