from __future__ import annotations

from pathlib import Path

from deepdoc.chatbot.chunker import build_artifact_chunks, build_code_chunks
from deepdoc.chatbot.docs_summary import build_doc_summary_chunks
from deepdoc.parser.base import ParsedFile, Symbol
from deepdoc.planner_v2 import RepoScan
from tests.conftest import make_bucket, make_plan


def _scan_for(tmp_path: Path) -> RepoScan:
    return RepoScan(
        file_tree={},
        file_summaries={},
        api_endpoints=[],
        languages={"python": 1},
        has_openapi=False,
        openapi_paths=[],
        total_files=1,
        frameworks_detected=[],
        entry_points=[],
        config_files=["package.json"],
        file_line_counts={"src/auth.py": 4},
        parsed_files={
            "src/auth.py": ParsedFile(
                path=Path("src/auth.py"),
                language="python",
                symbols=[
                    Symbol(
                        name="login",
                        kind="function",
                        signature="def login(user):",
                        start_line=1,
                        end_line=4,
                    )
                ],
                imports=["from db import users"],
                raw_content="def login(user):\n    token = issue(user)\n    return token\n",
            )
        },
        file_contents={
            "src/auth.py": "def login(user):\n    token = issue(user)\n    return token\n",
        },
    )


def test_code_chunks_use_symbol_line_ranges(tmp_path: Path) -> None:
    scan = _scan_for(tmp_path)
    plan = make_plan([make_bucket("Auth", "auth", ["src/auth.py"])])

    chunks = build_code_chunks(scan, plan, {"chatbot": {"enabled": True}})

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.kind == "code"
    assert chunk.file_path == "src/auth.py"
    assert chunk.start_line == 1
    assert chunk.end_line == 4
    assert chunk.symbol_names == ["login"]
    assert "def login(user):" in chunk.text


def test_artifact_chunks_cover_config_files(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "package.json").write_text('{"name":"demo","scripts":{"dev":"next dev"}}', encoding="utf-8")
    scan = _scan_for(tmp_path)
    plan = make_plan([make_bucket("Setup", "setup", ["src/auth.py"])])

    chunks = build_artifact_chunks(
        repo_root,
        scan,
        plan,
        repo_root / "docs",
        {"chatbot": {"enabled": True}},
        files=["package.json"],
    )

    assert len(chunks) == 1
    assert chunks[0].kind == "artifact"
    assert chunks[0].artifact_type == "json"
    assert "scripts" in chunks[0].text


def test_doc_summary_chunks_are_deterministic(tmp_path: Path) -> None:
    output_dir = tmp_path / "docs"
    output_dir.mkdir()
    (output_dir / "index.mdx").write_text(
        "---\ntitle: Demo\n---\n\n# Demo\n\nWelcome aboard.\n\n## Architecture\n\nAuth flows through middleware.\n",
        encoding="utf-8",
    )
    overview = make_bucket(
        "Overview",
        "overview",
        ["README.md"],
        generation_hints={"is_introduction_page": True},
    )
    plan = make_plan([overview])

    chunks = build_doc_summary_chunks(output_dir, plan, {"chatbot": {"enabled": True}})

    assert len(chunks) >= 1
    assert chunks[0].kind == "doc_summary"
    assert chunks[0].doc_url == "/"
    assert any("Architecture" in chunk.text for chunk in chunks)
