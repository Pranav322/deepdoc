from __future__ import annotations

from pathlib import Path

from deepdoc.config import DEFAULT_CONFIG
from deepdoc.generator_v2 import AssembledEvidence, EvidenceAssembler, PageValidator
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


def test_source_context_thresholds_follow_config_cutoffs(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)

    lines = ["def giant_handler():"]
    lines.extend(f"    step_{idx} = {idx}" for idx in range(1, 550))
    content = "\n".join(lines) + "\n"
    rel_path = "src/giant_handler.py"
    (repo_root / rel_path).write_text(content, encoding="utf-8")

    parsed = ParsedFile(
        path=Path(rel_path),
        language="python",
        symbols=[
            Symbol(
                name="giant_handler",
                kind="function",
                signature="def giant_handler():",
                start_line=1,
                end_line=550,
            )
        ],
        imports=[],
    )
    scan = RepoScan(
        file_tree={"src": ["giant_handler.py"]},
        file_summaries={rel_path: "summary"},
        api_endpoints=[],
        languages={"python": 1},
        has_openapi=False,
        openapi_paths=[],
        total_files=1,
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
        file_line_counts={rel_path: 550},
        parsed_files={rel_path: parsed},
        file_contents={rel_path: content},
    )
    bucket = make_bucket("Core Flow", "core-flow", [rel_path])
    plan = make_plan([bucket])

    excerpt_cfg = dict(DEFAULT_CONFIG)
    excerpt_cfg["large_file_lines"] = 500
    excerpt_cfg["giant_file_lines"] = 2000
    full_cfg = dict(DEFAULT_CONFIG)
    full_cfg["large_file_lines"] = 600
    full_cfg["giant_file_lines"] = 2000

    excerpt_evidence = EvidenceAssembler(repo_root, scan, plan, excerpt_cfg).assemble(bucket)
    full_evidence = EvidenceAssembler(repo_root, scan, plan, full_cfg).assemble(bucket)

    assert "step_540 = 540" not in excerpt_evidence.source_context
    assert "step_540 = 540" in full_evidence.source_context


def test_tier3_owned_symbol_excerpts_keep_deeper_branch_logic(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)

    lines = ["def login(req):"]
    lines.extend(f"    prelude_{idx} = {idx}" for idx in range(1, 68))
    lines.append("    if is_block:")
    lines.append("        return {'blocked': True}")
    lines.extend(f"    mid_{idx} = {idx}" for idx in range(1, 15))
    lines.extend(f"    tail_{idx} = {idx}" for idx in range(1, 1980))
    content = "\n".join(lines) + "\n"
    rel_path = "src/routes.py"
    (repo_root / rel_path).write_text(content, encoding="utf-8")

    parsed = ParsedFile(
        path=Path(rel_path),
        language="python",
        symbols=[
            Symbol(
                name="login",
                kind="function",
                signature="def login(req):",
                start_line=1,
                end_line=len(lines),
            )
        ],
        imports=[],
    )
    scan = RepoScan(
        file_tree={"src": ["routes.py"]},
        file_summaries={rel_path: "summary"},
        api_endpoints=[],
        languages={"python": 1},
        has_openapi=False,
        openapi_paths=[],
        total_files=1,
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
        file_line_counts={rel_path: len(lines)},
        parsed_files={rel_path: parsed},
        file_contents={rel_path: content},
    )
    bucket = make_bucket(
        "Order Login Flow",
        "order-login-flow",
        [rel_path],
        bucket_type="endpoint",
        section="API Reference",
        generation_hints={"prompt_style": "endpoint", "include_endpoint_detail": True},
    )
    bucket.owned_symbols = ["login"]
    plan = make_plan([bucket])

    evidence = EvidenceAssembler(repo_root, scan, plan, dict(DEFAULT_CONFIG)).assemble(bucket)

    assert "if is_block:" in evidence.source_context
    assert "return {'blocked': True}" in evidence.source_context


def test_helper_context_only_follows_directly_imported_local_helpers(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "src" / "helpers").mkdir(parents=True)

    controller_path = "src/controller.py"
    helpers_path = "src/helpers/auth.py"
    unrelated_path = "src/other_helpers.py"

    controller_content = (
        "from src.helpers.auth import create_token, sync_cart\n\n"
        "def login(req):\n"
        "    token = create_token(req)\n"
        "    sync_cart(req)\n"
        "    return token\n"
    )
    helpers_content = (
        "def create_token(req):\n"
        "    return {'token': req}\n\n"
        "def sync_cart(req):\n"
        "    return {'cart': req}\n\n"
        "def unused_helper(req):\n"
        "    return {'unused': req}\n"
    )
    unrelated_content = (
        "def create_token(req):\n"
        "    return {'wrong': req}\n"
    )

    for rel_path, content in {
        controller_path: controller_content,
        helpers_path: helpers_content,
        unrelated_path: unrelated_content,
    }.items():
        path = repo_root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    parsed_files = {
        controller_path: ParsedFile(
            path=Path(controller_path),
            language="python",
            symbols=[
                Symbol(
                    name="login",
                    kind="function",
                    signature="def login(req):",
                    start_line=3,
                    end_line=6,
                )
            ],
            imports=["src.helpers.auth"],
        ),
        helpers_path: ParsedFile(
            path=Path(helpers_path),
            language="python",
            symbols=[
                Symbol(
                    name="create_token",
                    kind="function",
                    signature="def create_token(req):",
                    start_line=1,
                    end_line=2,
                ),
                Symbol(
                    name="sync_cart",
                    kind="function",
                    signature="def sync_cart(req):",
                    start_line=4,
                    end_line=5,
                ),
                Symbol(
                    name="unused_helper",
                    kind="function",
                    signature="def unused_helper(req):",
                    start_line=7,
                    end_line=8,
                ),
            ],
            imports=[],
        ),
        unrelated_path: ParsedFile(
            path=Path(unrelated_path),
            language="python",
            symbols=[
                Symbol(
                    name="create_token",
                    kind="function",
                    signature="def create_token(req):",
                    start_line=1,
                    end_line=2,
                )
            ],
            imports=[],
        ),
    }
    scan = RepoScan(
        file_tree={"src": ["controller.py", "other_helpers.py"], "src/helpers": ["auth.py"]},
        file_summaries={path: "summary" for path in parsed_files},
        api_endpoints=[],
        languages={"python": len(parsed_files)},
        has_openapi=False,
        openapi_paths=[],
        total_files=len(parsed_files),
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
        file_line_counts={
            controller_path: len(controller_content.splitlines()),
            helpers_path: len(helpers_content.splitlines()),
            unrelated_path: len(unrelated_content.splitlines()),
        },
        parsed_files=parsed_files,
        file_contents={
            controller_path: controller_content,
            helpers_path: helpers_content,
            unrelated_path: unrelated_content,
        },
    )
    bucket = make_bucket(
        "Login Endpoint",
        "login-endpoint",
        [controller_path],
        bucket_type="endpoint",
        section="API Reference",
        generation_hints={"prompt_style": "endpoint", "include_endpoint_detail": True},
    )
    bucket.owned_symbols = ["login"]
    plan = make_plan([bucket])

    evidence = EvidenceAssembler(repo_root, scan, plan, dict(DEFAULT_CONFIG)).assemble(bucket)

    assert "Resolved Helper Functions" in evidence.helper_context
    assert "`create_token()` (`src/helpers/auth.py:1`)" in evidence.helper_context
    assert "`sync_cart()` (`src/helpers/auth.py:4`)" in evidence.helper_context
    assert "unused_helper" not in evidence.helper_context
    assert "src/other_helpers.py" not in evidence.helper_context


def test_helper_context_handles_module_imports_without_pulling_unused_symbols(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "src" / "helpers").mkdir(parents=True)

    controller_path = "src/controller.py"
    helpers_path = "src/helpers/auth.py"
    settings_path = "src/settings.py"

    controller_content = (
        "import src.helpers.auth as auth\n"
        "import json\n\n"
        "def login(req):\n"
        "    payload = auth.create_token(req)\n"
        "    return json.dumps(payload)\n"
    )
    helpers_content = (
        "def create_token(req):\n"
        "    return {'token': req}\n\n"
        "def sync_cart(req):\n"
        "    return {'cart': req}\n"
    )
    settings_content = "VALUE = 'x'\n"

    for rel_path, content in {
        controller_path: controller_content,
        helpers_path: helpers_content,
        settings_path: settings_content,
    }.items():
        path = repo_root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    parsed_files = {
        controller_path: ParsedFile(
            path=Path(controller_path),
            language="python",
            symbols=[
                Symbol(
                    name="login",
                    kind="function",
                    signature="def login(req):",
                    start_line=4,
                    end_line=6,
                )
            ],
            imports=["src.helpers.auth", "json"],
        ),
        helpers_path: ParsedFile(
            path=Path(helpers_path),
            language="python",
            symbols=[
                Symbol(
                    name="create_token",
                    kind="function",
                    signature="def create_token(req):",
                    start_line=1,
                    end_line=2,
                ),
                Symbol(
                    name="sync_cart",
                    kind="function",
                    signature="def sync_cart(req):",
                    start_line=4,
                    end_line=5,
                ),
            ],
            imports=[],
        ),
        settings_path: ParsedFile(
            path=Path(settings_path),
            language="python",
            symbols=[],
            imports=[],
        ),
    }
    scan = RepoScan(
        file_tree={"src": ["controller.py", "settings.py"], "src/helpers": ["auth.py"]},
        file_summaries={path: "summary" for path in parsed_files},
        api_endpoints=[],
        languages={"python": len(parsed_files)},
        has_openapi=False,
        openapi_paths=[],
        total_files=len(parsed_files),
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
        file_line_counts={
            controller_path: len(controller_content.splitlines()),
            helpers_path: len(helpers_content.splitlines()),
            settings_path: len(settings_content.splitlines()),
        },
        parsed_files=parsed_files,
        file_contents={
            controller_path: controller_content,
            helpers_path: helpers_content,
            settings_path: settings_content,
        },
    )
    bucket = make_bucket(
        "Login Endpoint",
        "login-endpoint",
        [controller_path],
        bucket_type="endpoint",
        section="API Reference",
        generation_hints={"prompt_style": "endpoint", "include_endpoint_detail": True},
    )
    bucket.owned_symbols = ["login"]
    plan = make_plan([bucket])

    evidence = EvidenceAssembler(repo_root, scan, plan, dict(DEFAULT_CONFIG)).assemble(bucket)

    assert "`create_token()` (`src/helpers/auth.py:1`)" in evidence.helper_context
    assert "sync_cart" not in evidence.helper_context
    assert "json" not in evidence.helper_context


def test_intro_evidence_includes_repo_docs_context(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "src" / "app.py").write_text("def create_app():\n    return 'ok'\n", encoding="utf-8")

    intro = make_bucket(
        "System Architecture & Component Overview",
        "architecture",
        ["src/app.py"],
        generation_hints={"is_introduction_page": True, "prompt_style": "system"},
    )
    plan = make_plan([intro])
    scan = _make_scan(repo_root)
    scan.research_contexts = [
        {
            "title": "Architecture Notes",
            "file_path": "docs/ARCHITECTURE.md",
            "summary": "Explains request flow and background jobs.",
        }
    ]
    scan.doc_contexts = {
        "README.md": "Covers local setup and major integrations.",
    }

    evidence = EvidenceAssembler(repo_root, scan, plan, dict(DEFAULT_CONFIG)).assemble(intro)

    assert "Internal Docs Context" in evidence.repo_docs_context
    assert "docs/ARCHITECTURE.md" in evidence.repo_docs_context
    assert "README.md" in evidence.repo_docs_context
    assert "docs/ARCHITECTURE.md" in evidence.evidence_file_paths
    assert "README.md" in evidence.evidence_file_paths


def test_page_validator_flags_unmatched_routes_and_out_of_evidence_refs(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    for rel_path in ["src/routes.py", "src/other.py"]:
        path = repo_root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pass\n", encoding="utf-8")

    scan = RepoScan(
        file_tree={"src": ["routes.py", "other.py"]},
        file_summaries={"src/routes.py": "summary", "src/other.py": "summary"},
        api_endpoints=[
            {
                "method": "POST",
                "path": "/api/v1/login",
                "file": "src/routes.py",
                "publication_ready": True,
            }
        ],
        languages={"python": 2},
        has_openapi=False,
        openapi_paths=[],
        total_files=2,
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
        file_line_counts={"src/routes.py": 1, "src/other.py": 1},
        parsed_files={},
        file_contents={},
    )
    validator = PageValidator(repo_root, scan)
    bucket = make_bucket(
        "Operations & Deployment",
        "operations",
        ["src/routes.py"],
        bucket_type="feature",
        section="API Reference",
        generation_hints={"prompt_style": "feature", "include_endpoint_detail": True},
    )
    evidence = AssembledEvidence(
        bucket=bucket,
        source_context="",
        endpoints_detail="",
        integration_context="",
        cluster_context="",
        artifact_context="",
        graph_context="",
        cross_ref_context="",
        evidence_file_paths={"src/routes.py"},
        total_evidence_chars=0,
    )
    content = """
# Operations & Deployment

The service exposes `POST /api/v1/login` through `src/routes.py`.
For health checks, call `/api/v2/health` from `src/other.py`.

This page documents deployment behavior for the internal service and explains how runtime
operations interact with request handling, environment validation, rollout checks, alerting,
and post-deploy verification so the generated page is long enough for validator coverage.
""".strip()

    result = validator.validate(content, bucket, evidence)

    assert "/api/v2/health" in result.unmatched_routes
    assert "src/other.py" in result.out_of_evidence_refs
    assert "/api/v1/login" not in result.unmatched_routes
