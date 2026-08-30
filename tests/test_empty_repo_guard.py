from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import click
import pytest

from deepdoc.pipeline_v2 import PipelineV2
from deepdoc.planner import scan_repo


def _pipeline(repo_root: Path) -> PipelineV2:
    with patch("deepdoc.pipeline_v2.LLMClient", return_value=MagicMock()):
        return PipelineV2(
            repo_root,
            {"output_dir": "docs", "llm": {"provider": "anthropic", "model": "test"}},
        )


def test_empty_directory_raises_clear_error(tmp_path: Path) -> None:
    scan = scan_repo(tmp_path, {})
    pipeline = _pipeline(tmp_path)

    with pytest.raises(click.ClickException, match="No source files found"):
        pipeline._guard_supported_source_files(scan)


def test_unsupported_only_repo_raises_clear_error(tmp_path: Path) -> None:
    (tmp_path / "Main.rb").write_text("class Main\nend", encoding="utf-8")
    scan = scan_repo(tmp_path, {})
    pipeline = _pipeline(tmp_path)

    with pytest.raises(click.ClickException, match="No parseable source files"):
        pipeline._guard_supported_source_files(scan)


def test_supported_repo_does_not_raise(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def f():\n    pass\n", encoding="utf-8")
    scan = scan_repo(tmp_path, {})
    pipeline = _pipeline(tmp_path)

    pipeline._guard_supported_source_files(scan)
