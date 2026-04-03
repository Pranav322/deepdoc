from __future__ import annotations

from pathlib import Path

from deepdoc.config import DEFAULT_CONFIG
from deepdoc.generator_v2 import EvidenceAssembler
from deepdoc.parser.base import ParsedFile, Symbol
from deepdoc.planner_v2 import RepoScan
from deepdoc.prompts_v2 import OVERVIEW_V2, get_prompt_for_bucket

from tests.conftest import make_bucket, make_plan


def _make_scan(repo_root: Path) -> RepoScan:
    parsed_files = {
        "src/app.py": ParsedFile(
            path=Path("src/app.py"),
            language="python",
            symbols=[
                Symbol(
                    name="create_app",
                    kind="function",
                    signature="def create_app():",
                    start_line=1,
                    end_line=5,
                )
            ],
            imports=["services.auth_service"],
        ),
        "src/routes.py": ParsedFile(
            path=Path("src/routes.py"),
            language="python",
            symbols=[
                Symbol(
                    name="login",
                    kind="function",
                    signature="def login(req, res):",
                    start_line=1,
                    end_line=4,
                )
            ],
            imports=["services.auth_service"],
        ),
        "src/services/auth_service.py": ParsedFile(
            path=Path("src/services/auth_service.py"),
            language="python",
            symbols=[
                Symbol(
                    name="authenticate",
                    kind="function",
                    signature="def authenticate(user):",
                    start_line=1,
                    end_line=4,
                )
            ],
            imports=["settings"],
        ),
        "settings.py": ParsedFile(
            path=Path("settings.py"),
            language="python",
            symbols=[
                Symbol(
                    name="API_PREFIX",
                    kind="constant",
                    signature="API_PREFIX = '/api/v1'",
                    start_line=1,
                    end_line=1,
                )
            ],
            imports=[],
        ),
    }

    file_contents = {
        "src/app.py": "def create_app():\n    return 'ok'\n",
        "src/routes.py": "def login(req, res):\n    return {'ok': True}\n",
        "src/services/auth_service.py": (
            "def authenticate(user):\n    return {'user': user}\n"
        ),
        "settings.py": "API_PREFIX = '/api/v1'\n",
    }

    return RepoScan(
        file_tree={"src": ["app.py", "routes.py"], ".": ["settings.py"]},
        file_summaries={path: "summary" for path in file_contents},
        api_endpoints=[
            {
                "method": "POST",
                "path": "/api/v1/login",
                "handler": "login",
                "file": "src/routes.py",
                "route_file": "src/routes.py",
                "handler_file": "src/routes.py",
                "line": 1,
            }
        ],
        languages={"python": 4},
        has_openapi=False,
        openapi_paths=[],
        total_files=4,
        frameworks_detected=["flask"],
        entry_points=["src/app.py"],
        config_files=["settings.py"],
        file_line_counts={path: len(content.splitlines()) for path, content in file_contents.items()},
        parsed_files=parsed_files,
        file_contents=file_contents,
    )


def test_evidence_assembler_compresses_overflow_files_instead_of_omitting(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "src" / "services").mkdir(parents=True)

    files = {
        "src/app.py": "def create_app():\n    return 'ok'\n",
        "src/routes.py": "def login(req, res):\n    return {'ok': True}\n",
        "src/services/auth_service.py": (
            "def authenticate(user):\n    return {'user': user}\n"
        ),
        "settings.py": "API_PREFIX = '/api/v1'\n",
    }
    for rel, content in files.items():
        path = repo_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    bucket = make_bucket(
        "System Architecture & Overview",
        "system-overview",
        ["src/app.py", "src/routes.py", "src/services/auth_service.py"],
        artifact_refs=["settings.py"],
    )
    plan = make_plan([bucket])
    cfg = dict(DEFAULT_CONFIG)
    cfg["source_context_budget"] = 260

    evidence = EvidenceAssembler(repo_root, _make_scan(repo_root), plan, cfg).assemble(bucket)

    assert evidence.coverage_files_total == 4
    assert evidence.files_compressed >= 1
    assert "Source omitted" not in evidence.source_context
    assert "Card: `settings.py`" in evidence.compressed_cards_context or "`settings.py`" in evidence.compressed_cards_context
    assert "Compressed File Coverage" not in evidence.source_context


def test_evidence_cards_preserve_all_tracked_files_when_bucket_is_large(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    bucket_files: list[str] = []
    parsed_files: dict[str, ParsedFile] = {}
    file_contents: dict[str, str] = {}

    for idx in range(8):
        rel = f"src/module_{idx}.py"
        content = f"def handler_{idx}():\n    return {idx}\n"
        path = repo_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        bucket_files.append(rel)
        file_contents[rel] = content
        parsed_files[rel] = ParsedFile(
            path=Path(rel),
            language="python",
            symbols=[
                Symbol(
                    name=f"handler_{idx}",
                    kind="function",
                    signature=f"def handler_{idx}():",
                    start_line=1,
                    end_line=2,
                )
            ],
            imports=[],
        )

    scan = RepoScan(
        file_tree={"src": [Path(f).name for f in bucket_files]},
        file_summaries={path: "summary" for path in bucket_files},
        api_endpoints=[],
        languages={"python": len(bucket_files)},
        has_openapi=False,
        openapi_paths=[],
        total_files=len(bucket_files),
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
        file_line_counts={path: 2 for path in bucket_files},
        parsed_files=parsed_files,
        file_contents=file_contents,
    )
    bucket = make_bucket("Core", "core", bucket_files)
    plan = make_plan([bucket])
    cfg = dict(DEFAULT_CONFIG)
    cfg["source_context_budget"] = 180

    evidence = EvidenceAssembler(repo_root, scan, plan, cfg).assemble(bucket)

    represented = evidence.files_included_raw + evidence.files_compressed
    assert represented == evidence.coverage_files_total == len(bucket_files)
    assert evidence.files_compressed > 0
    for rel in bucket_files:
        if rel not in evidence.source_context:
            assert rel in evidence.compressed_cards_context


def test_intro_bucket_uses_overview_prompt_even_if_prompt_style_is_system() -> None:
    bucket = make_bucket(
        "System Architecture & Component Overview",
        "architecture",
        ["main.py"],
        generation_hints={"is_introduction_page": True, "prompt_style": "system"},
    )

    assert get_prompt_for_bucket(bucket) == OVERVIEW_V2


def test_intro_evidence_includes_repo_map_context(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "src" / "services").mkdir(parents=True)
    (repo_root / "src" / "app.py").write_text("def create_app():\n    return 'ok'\n", encoding="utf-8")
    (repo_root / "settings.py").write_text("API_PREFIX='/api/v1'\n", encoding="utf-8")

    intro = make_bucket(
        "System Architecture & Component Overview",
        "architecture",
        ["src/app.py"],
        generation_hints={"is_introduction_page": True, "prompt_style": "system"},
    )
    auth = make_bucket("Authentication", "authentication", ["src/services/auth.py"], section="Runtime & Frameworks")
    plan = make_plan([intro, auth])
    plan.nav_structure = {"Overview": ["architecture"], "Runtime & Frameworks": ["authentication"]}

    scan = _make_scan(repo_root)
    scan.frameworks_detected = ["falcon"]
    scan.entry_points = ["src/app.py"]
    scan.config_files = ["settings.py"]

    evidence = EvidenceAssembler(repo_root, scan, plan, dict(DEFAULT_CONFIG)).assemble(intro)

    assert "Planned Documentation Map" in evidence.plan_summary_context
    assert "Authentication" in evidence.plan_summary_context
    assert "Primary entry points" in evidence.plan_summary_context
