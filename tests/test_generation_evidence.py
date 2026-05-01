from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from deepdoc.call_graph import build_call_graph
from deepdoc.config import DEFAULT_CONFIG
from deepdoc.generator import (
    AssembledEvidence,
    BucketGenerationEngine,
    EvidenceAssembler,
    GenerationResult,
    PageValidator,
    ValidationResult,
    summarize_generation_results,
)
from deepdoc.parser.base import ParsedFile, Symbol
from deepdoc.planner import RepoScan
from deepdoc.prompts_v2 import OVERVIEW_V2, get_prompt_for_bucket
from deepdoc.scanner import RuntimeScan, RuntimeScheduler, RuntimeTask
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
        frameworks_detected=[],
        entry_points=["src/app.py"],
        config_files=["settings.py"],
        file_line_counts={
            path: len(content.splitlines()) for path, content in file_contents.items()
        },
        parsed_files=parsed_files,
        file_contents=file_contents,
        config_impacts=[
            {
                "key": "API_PREFIX",
                "kind": "setting",
                "file_path": "settings.py",
                "default_value": "'/api/v1'",
                "related_files": ["src/routes.py"],
                "related_endpoints": ["POST /api/v1/login"],
            }
        ],
        runtime_scan=RuntimeScan(
            tasks=[
                RuntimeTask(
                    name="send_login_audit",
                    file_path="src/services/auth_service.py",
                    runtime_kind="celery",
                    producer_files=["src/routes.py"],
                    linked_endpoints=["POST /api/v1/login"],
                )
            ],
            schedulers=[
                RuntimeScheduler(
                    name="nightly-auth-sync",
                    file_path="settings.py",
                    scheduler_type="beat",
                    cron="0 2 * * *",
                    invoked_targets=["send_login_audit"],
                )
            ],
        ),
    )


def test_evidence_assembler_compresses_overflow_files_instead_of_omitting(
    tmp_path: Path,
) -> None:
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

    evidence = EvidenceAssembler(repo_root, _make_scan(repo_root), plan, cfg).assemble(
        bucket
    )

    assert evidence.coverage_files_total == 4
    assert evidence.files_compressed >= 1
    assert "Source omitted" not in evidence.source_context
    assert (
        "Card: `settings.py`" in evidence.compressed_cards_context
        or "`settings.py`" in evidence.compressed_cards_context
    )
    assert "Compressed File Coverage" not in evidence.source_context


def test_evidence_cards_preserve_all_tracked_files_when_bucket_is_large(
    tmp_path: Path,
) -> None:
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
    (repo_root / "src" / "app.py").write_text(
        "def create_app():\n    return 'ok'\n", encoding="utf-8"
    )
    (repo_root / "settings.py").write_text("API_PREFIX='/api/v1'\n", encoding="utf-8")

    intro = make_bucket(
        "System Architecture & Component Overview",
        "architecture",
        ["src/app.py"],
        generation_hints={"is_introduction_page": True, "prompt_style": "system"},
    )
    auth = make_bucket(
        "Authentication",
        "authentication",
        ["src/services/auth.py"],
        section="Runtime & Frameworks",
    )
    plan = make_plan([intro, auth])
    plan.nav_structure = {
        "Overview": ["architecture"],
        "Runtime & Frameworks": ["authentication"],
    }

    scan = _make_scan(repo_root)
    scan.frameworks_detected = ["falcon"]
    scan.entry_points = ["src/app.py"]
    scan.config_files = ["settings.py"]

    evidence = EvidenceAssembler(repo_root, scan, plan, dict(DEFAULT_CONFIG)).assemble(
        intro
    )

    assert "Planned Documentation Map" in evidence.plan_summary_context
    assert "Authentication" in evidence.plan_summary_context
    assert "Primary entry points" in evidence.plan_summary_context


@pytest.mark.skip()
def test_endpoint_evidence_surfaces_middleware_runtime_and_config_context(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "src" / "services").mkdir(parents=True)
    (repo_root / "src" / "routes.py").write_text(
        "def login(req, res):\n    return {'ok': True}\n",
        encoding="utf-8",
    )
    (repo_root / "src" / "services" / "auth_service.py").write_text(
        "def authenticate(user):\n    return {'user': user}\n",
        encoding="utf-8",
    )
    (repo_root / "settings.py").write_text("API_PREFIX='/api/v1'\n", encoding="utf-8")

    scan = _make_scan(repo_root)
    scan.api_endpoints[0]["middleware"] = ["auth_required", "audit_login"]
    scan.api_endpoints[0]["request_body"] = "LoginRequest"
    scan.api_endpoints[0]["response_type"] = "LoginResponse"

    bucket = make_bucket(
        "POST /api/v1/login",
        "post-api-v1-login",
        ["src/routes.py", "src/services/auth_service.py"],
        artifact_refs=["settings.py"],
        generation_hints={
            "is_endpoint_ref": True,
            "include_endpoint_detail": True,
            "include_runtime_context": True,
        },
    )
    bucket.owned_symbols = ["login"]
    plan = make_plan([bucket])

    evidence = EvidenceAssembler(repo_root, scan, plan, dict(DEFAULT_CONFIG)).assemble(
        bucket
    )

    assert "Middleware/auth" in evidence.endpoints_detail
    assert "auth_required" in evidence.endpoints_detail
    assert "send_login_audit" in evidence.runtime_context
    assert "POST /api/v1/login" in evidence.runtime_context
    assert "API_PREFIX" in evidence.config_env_context


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

    excerpt_evidence = EvidenceAssembler(repo_root, scan, plan, excerpt_cfg).assemble(
        bucket
    )
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

    evidence = EvidenceAssembler(repo_root, scan, plan, dict(DEFAULT_CONFIG)).assemble(
        bucket
    )

    assert "if is_block:" in evidence.source_context
    assert "return {'blocked': True}" in evidence.source_context


def test_helper_context_only_follows_directly_imported_local_helpers(
    tmp_path: Path,
) -> None:
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
    unrelated_content = "def create_token(req):\n    return {'wrong': req}\n"

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
        file_tree={
            "src": ["controller.py", "other_helpers.py"],
            "src/helpers": ["auth.py"],
        },
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

    evidence = EvidenceAssembler(repo_root, scan, plan, dict(DEFAULT_CONFIG)).assemble(
        bucket
    )

    assert "Resolved Helper Functions" in evidence.helper_context
    assert "`create_token()` (`src/helpers/auth.py:1`)" in evidence.helper_context
    assert "`sync_cart()` (`src/helpers/auth.py:4`)" in evidence.helper_context
    assert "unused_helper" not in evidence.helper_context
    assert "src/other_helpers.py" not in evidence.helper_context


def test_helper_context_handles_module_imports_without_pulling_unused_symbols(
    tmp_path: Path,
) -> None:
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

    evidence = EvidenceAssembler(repo_root, scan, plan, dict(DEFAULT_CONFIG)).assemble(
        bucket
    )

    assert "`create_token()` (`src/helpers/auth.py:1`)" in evidence.helper_context
    assert "sync_cart" not in evidence.helper_context
    assert "json" not in evidence.helper_context


def test_intro_evidence_includes_repo_docs_context(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "src" / "app.py").write_text(
        "def create_app():\n    return 'ok'\n", encoding="utf-8"
    )

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

    evidence = EvidenceAssembler(repo_root, scan, plan, dict(DEFAULT_CONFIG)).assemble(
        intro
    )

    assert "Internal Docs Context" in evidence.repo_docs_context
    assert "docs/ARCHITECTURE.md" in evidence.repo_docs_context
    assert "README.md" in evidence.repo_docs_context
    assert "docs/ARCHITECTURE.md" in evidence.evidence_file_paths
    assert "README.md" in evidence.evidence_file_paths


def test_page_validator_flags_unmatched_routes_and_out_of_evidence_refs(
    tmp_path: Path,
) -> None:
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


def test_page_validator_ignores_markup_noise_in_route_claim_detection(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    scan = RepoScan(
        file_tree={"src": ["routes.py"]},
        file_summaries={"src/routes.py": "summary"},
        api_endpoints=[
            {
                "method": "GET",
                "path": "/api/v1/health",
                "file": "src/routes.py",
                "publication_ready": True,
            }
        ],
        languages={"python": 1},
        has_openapi=False,
        openapi_paths=[],
        total_files=1,
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
        file_line_counts={"src/routes.py": 1},
        parsed_files={},
        file_contents={},
    )
    validator = PageValidator(repo_root, scan)
    bucket = make_bucket(
        "API Health",
        "api-health",
        ["src/routes.py"],
        bucket_type="endpoint",
        section="API Reference",
        generation_hints={"include_endpoint_detail": True, "is_endpoint_ref": True},
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
# API Health

Use `<Callout>` blocks for docs emphasis and `<Card>` components for layout.
The route to call is `GET /api/v1/health`.
""".strip()

    result = validator.validate(content, bucket, evidence)

    assert "/Callout>" not in result.unmatched_routes
    assert "/Card>" not in result.unmatched_routes
    assert "/api/v1/health" not in result.unmatched_routes


def test_page_validator_normalizes_scheme_less_urls_in_route_claim_detection(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    scan = RepoScan(
        file_tree={"src": ["routes.py"]},
        file_summaries={"src/routes.py": "summary"},
        api_endpoints=[
            {
                "method": "POST",
                "path": "/api/v1/sync",
                "file": "src/routes.py",
                "publication_ready": True,
            }
        ],
        languages={"python": 1},
        has_openapi=False,
        openapi_paths=[],
        total_files=1,
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
        file_line_counts={"src/routes.py": 1},
        parsed_files={},
        file_contents={},
    )
    validator = PageValidator(repo_root, scan)
    bucket = make_bucket(
        "Sync API",
        "sync-api",
        ["src/routes.py"],
        bucket_type="endpoint",
        section="API Reference",
        generation_hints={"include_endpoint_detail": True, "is_endpoint_family": True},
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
# Sync API

Primary endpoint: `POST //api.example.com/api/v1/sync`.
""".strip()

    result = validator.validate(content, bucket, evidence)

    assert "/api/v1/sync" not in result.unmatched_routes


def test_page_validator_limits_integration_grounding_to_relevant_identity(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    scan = RepoScan(
        file_tree={},
        file_summaries={"integrations/vinculum.py": "summary"},
        api_endpoints=[],
        languages={"python": 1},
        has_openapi=False,
        openapi_paths=[],
        total_files=1,
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
        file_line_counts={"integrations/vinculum.py": 1},
        parsed_files={},
        file_contents={},
        integration_identities=[
            SimpleNamespace(
                name="vinculum",
                display_name="Vinculum",
                files=["integrations/vinculum.py"],
            ),
            SimpleNamespace(
                name="freshdesk",
                display_name="Freshdesk",
                files=["integrations/freshdesk.py"],
            ),
        ],
    )
    validator = PageValidator(repo_root, scan)
    bucket = make_bucket(
        "Vinculum Integration",
        "integration-vinculum",
        ["integrations/vinculum.py"],
        bucket_type="integration",
        generation_hints={
            "include_integration_detail": True,
            "prompt_style": "integration",
        },
    )
    evidence = AssembledEvidence(
        bucket=bucket,
        source_context="",
        endpoints_detail="",
        integration_context="**Integration: Vinculum**\n",
        cluster_context="",
        artifact_context="",
        graph_context="",
        cross_ref_context="",
        evidence_file_paths={"integrations/vinculum.py"},
        total_evidence_chars=0,
    )
    content = """
# Vinculum Integration

This page documents how Vinculum requests are validated, transformed, and retried.
""".strip()

    result = validator.validate(content, bucket, evidence)

    assert "Freshdesk" not in result.missing_integrations
    assert "Vinculum" not in result.missing_integrations


def test_page_validator_flags_missing_runtime_and_config_grounding(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "jobs").mkdir(parents=True)
    (repo_root / "settings.py").write_text(
        "PAYMENTS_HOST='https://pay.example'\n", encoding="utf-8"
    )
    (repo_root / "jobs" / "tasks.py").write_text(
        "def sync_orders():\n    pass\n", encoding="utf-8"
    )

    scan = RepoScan(
        file_tree={"jobs": ["tasks.py"], ".": ["settings.py"]},
        file_summaries={"jobs/tasks.py": "summary", "settings.py": "summary"},
        api_endpoints=[],
        languages={"python": 2},
        has_openapi=False,
        openapi_paths=[],
        total_files=2,
        frameworks_detected=[],
        entry_points=[],
        config_files=["settings.py"],
        file_line_counts={"jobs/tasks.py": 2, "settings.py": 1},
        parsed_files={},
        file_contents={},
        config_impacts=[
            {
                "key": "PAYMENTS_HOST",
                "file_path": "settings.py",
                "related_files": ["jobs/tasks.py"],
            }
        ],
        runtime_scan=RuntimeScan(
            tasks=[
                RuntimeTask(
                    name="sync_orders",
                    file_path="jobs/tasks.py",
                    runtime_kind="celery",
                )
            ]
        ),
    )
    validator = PageValidator(repo_root, scan)
    bucket = make_bucket(
        "Setup & Configuration",
        "setup",
        ["jobs/tasks.py"],
        artifact_refs=["settings.py"],
        bucket_type="runtime-group",
        section="Getting Started",
        generation_hints={
            "prompt_style": "runtime",
            "include_runtime_context": True,
            "runtime_group_kind": "celery",
        },
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
        runtime_context="### Tasks\n- `sync_orders` (`jobs/tasks.py`)\n",
        config_env_context="| Variable | Found In |\n|---|---|\n| `PAYMENTS_HOST` | `settings.py` |",
        evidence_file_paths={"jobs/tasks.py", "settings.py"},
        total_evidence_chars=0,
    )
    content = """
# Setup & Configuration

This page explains boot flow, service ownership, operational boundaries, deployment checks,
runtime expectations, and rollout safety for the order sync subsystem. It intentionally omits
the concrete runtime worker name and environment key so the validator can detect the gap while
the page remains long enough to avoid the short-page failure path.
""".strip()

    result = validator.validate(content, bucket, evidence)

    assert "sync_orders" in result.missing_runtime_entities
    assert "PAYMENTS_HOST" in result.missing_config_keys
    assert result.is_valid is False


def test_page_validator_flags_missing_integration_grounding_for_integration_page(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    scan = RepoScan(
        file_tree={},
        file_summaries={"integrations/vinculum.py": "summary"},
        api_endpoints=[],
        languages={"python": 1},
        has_openapi=False,
        openapi_paths=[],
        total_files=1,
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
        file_line_counts={"integrations/vinculum.py": 1},
        parsed_files={},
        file_contents={},
        integration_identities=[
            SimpleNamespace(
                name="vinculum",
                display_name="Vinculum",
                files=["integrations/vinculum.py"],
            )
        ],
    )
    validator = PageValidator(repo_root, scan)
    bucket = make_bucket(
        "Vinculum Integration",
        "integration-vinculum",
        ["integrations/vinculum.py"],
        bucket_type="integration",
        generation_hints={
            "include_integration_detail": True,
            "prompt_style": "integration",
        },
    )
    evidence = AssembledEvidence(
        bucket=bucket,
        source_context="",
        endpoints_detail="",
        integration_context="**Integration: Vinculum**\n",
        cluster_context="",
        artifact_context="",
        graph_context="",
        cross_ref_context="",
        evidence_file_paths={"integrations/vinculum.py"},
        total_evidence_chars=0,
    )
    content = """
# Warehouse Integration

This page covers the integration surface, request flow, operational safeguards, retry patterns,
configuration boundaries, and the handoff between internal order processing and third-party sync.
It intentionally avoids naming the specific partner so validation can detect the missing grounding.
""".strip()

    result = validator.validate(content, bucket, evidence)

    assert "Vinculum" in result.missing_integrations
    assert result.is_valid is False


def test_generation_summary_marks_invalid_and_degraded_pages_partial() -> None:
    bucket = make_bucket("Auth", "auth", ["src/auth.py"])
    summary = summarize_generation_results(
        [
            GenerationResult(
                bucket=bucket,
                content="# Auth",
                validation=ValidationResult(
                    is_valid=False,
                    warnings=["Missing runtime grounding"],
                ),
                degraded=True,
            )
        ]
    )

    assert summary.status == "partial"
    assert summary.invalid == 1
    assert summary.degraded == 1
    assert summary.invalid_slugs == ["auth"]
    assert summary.degraded_slugs == ["auth"]


def test_validator_invalidates_strict_pages_with_hallucinated_paths(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    scan = _make_scan(repo_root)
    bucket = make_bucket(
        "Auth Feature",
        "auth-feature",
        ["src/app.py", "src/routes.py", "src/services/auth_service.py"],
        bucket_type="feature",
    )
    content = (
        "# Auth Feature\n\n"
        "`src/app.py`, `src/routes.py`, and `src/services/auth_service.py` are covered. "
        "`orders/fake_one.py` and `orders/fake_two.py` do not exist. "
        + "This grounded sentence repeats enough words to avoid short-page validation. "
        * 12
    )

    result = PageValidator(repo_root, scan).validate(content, bucket)

    assert result.is_valid is False
    assert result.hallucinated_paths == ["orders/fake_one.py", "orders/fake_two.py"]


def test_validator_flags_hallucinated_symbols_but_allows_known_symbols(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    scan = _make_scan(repo_root)
    bucket = make_bucket(
        "Auth Feature",
        "auth-feature",
        ["src/routes.py", "src/services/auth_service.py"],
        bucket_type="feature",
    )
    content = (
        "# Auth Feature\n\n"
        "`src/routes.py` calls `login()` and `src/services/auth_service.py` defines "
        "`authenticate()`. The page must not invent `process_order()`, "
        "`SubmitOrder`, or `fakeAuthFlow`. "
        + "The rest of this paragraph is grounded filler for the validator. " * 14
    )

    result = PageValidator(repo_root, scan).validate(content, bucket)

    assert result.is_valid is False
    assert result.hallucinated_symbols == [
        "SubmitOrder",
        "fakeAuthFlow",
        "process_order",
    ]


def test_validator_allows_known_bucket_symbols(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    scan = _make_scan(repo_root)
    bucket = make_bucket(
        "Auth Feature",
        "auth-feature",
        ["src/routes.py", "src/services/auth_service.py"],
        bucket_type="feature",
    )
    content = (
        "# Auth Feature\n\n"
        "`src/routes.py` exposes `login()` and `src/services/auth_service.py` "
        "uses `authenticate()`. "
        + "This paragraph repeats grounded implementation context for validation. " * 18
    )

    result = PageValidator(repo_root, scan).validate(content, bucket)

    assert result.hallucinated_symbols == []


def test_validator_file_coverage_threshold_fails_feature_pages(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    files = [f"src/module_{idx}.py" for idx in range(10)]
    scan = RepoScan(
        file_tree={"src": [Path(path).name for path in files]},
        file_summaries={path: "summary" for path in files},
        api_endpoints=[],
        languages={"python": len(files)},
        has_openapi=False,
        openapi_paths=[],
        total_files=len(files),
        frameworks_detected=[],
        entry_points=[],
        config_files=[],
        parsed_files={},
        file_contents={},
    )
    bucket = make_bucket("Large Feature", "large-feature", files, bucket_type="feature")
    content = (
        "# Large Feature\n\n"
        "`src/module_0.py`, `src/module_1.py`, `src/module_2.py`, and "
        "`src/module_3.py` are referenced. "
        + "Detailed grounded prose repeats enough words for validation. " * 18
    )

    result = PageValidator(repo_root, scan).validate(content, bucket)

    assert result.is_valid is False
    assert result.missing_file_refs[:3] == [
        "src/module_4.py",
        "src/module_5.py",
        "src/module_6.py",
    ]


def test_generation_quality_feedback_is_actionable(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    bucket = make_bucket("Auth", "auth", ["src/auth.py"])
    engine = BucketGenerationEngine(
        repo_root,
        dict(DEFAULT_CONFIG),
        SimpleNamespace(),
        _make_scan(repo_root),
        make_plan([bucket]),
        repo_root / "docs",
    )
    validation = ValidationResult(
        is_valid=False,
        hallucinated_paths=["fake/path.py"],
        hallucinated_symbols=["process_order"],
        out_of_evidence_refs=["src/other.py"],
        warnings=["Low file coverage"],
    )

    feedback = engine._quality_feedback_to_instructions(validation)

    assert "Remove every reference to these non-existent paths" in feedback
    assert "`fake/path.py`" in feedback
    assert "Remove or correct these symbol names" in feedback
    assert "`process_order`" in feedback


def test_generated_pages_receive_provenance_frontmatter(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    bucket = make_bucket("Auth", "auth", ["src/auth.py"])
    engine = BucketGenerationEngine(
        repo_root,
        dict(DEFAULT_CONFIG),
        SimpleNamespace(),
        _make_scan(repo_root),
        make_plan([bucket]),
        repo_root / "docs",
    )
    content = "# Auth\n\nBody"

    updated = engine._add_provenance_frontmatter(
        content,
        bucket,
        ValidationResult(is_valid=True),
        None,
    )

    assert "deepdoc_generated_at:" in updated
    assert 'deepdoc_generated_version: "1.6.0"' in updated
    assert 'deepdoc_status: "valid"' in updated
    assert "deepdoc_evidence_files:" in updated


def test_generation_coverage_report_counts_files_endpoints_and_symbols(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    scan = _make_scan(repo_root)
    bucket = make_bucket("Auth", "auth", ["src/routes.py", "src/services/auth_service.py"])
    engine = BucketGenerationEngine(
        repo_root,
        dict(DEFAULT_CONFIG),
        SimpleNamespace(),
        scan,
        make_plan([bucket]),
        repo_root / "docs",
    )
    result = GenerationResult(
        bucket=bucket,
        content=(
            "`src/routes.py` handles `POST /api/v1/login` via `login()` and "
            "`src/services/auth_service.py` uses `authenticate()`."
        ),
    )

    report = engine._build_coverage_report([result])

    assert report["api_endpoints"]["documented"] == 1
    assert report["source_files"]["documented"] == 2
    assert report["public_symbols"]["documented"] >= 2


def test_specialized_database_and_runtime_pages_feed_deeper_evidence_and_links(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    for rel_path, content in {
        "orders/models.py": (
            "from django.db import models\n\n"
            "class Order(models.Model):\n"
            "    status = models.CharField(max_length=32)\n"
        ),
        "catalog/models.py": (
            "from django.db import models\n\n"
            "class CatalogItem(models.Model):\n"
            "    sku = models.CharField(max_length=32)\n"
        ),
        "db/orders.js": (
            "exports.up = async function(knex) {\n"
            "  await knex.schema.createTable('orders', function(table) {\n"
            "    table.uuid('id');\n"
            "    table.string('status');\n"
            "  });\n"
            "};\n"
        ),
        "jobs/tasks.py": (
            "from celery import shared_task\n\n"
            "@shared_task(queue='critical', autoretry_for=(Exception,), retry_backoff=True)\n"
            "def sync_orders(order_id):\n"
            "    return order_id\n"
        ),
        "jobs/scheduler.py": (
            "from celery.schedules import crontab\n"
            "app.conf.beat_schedule = {\n"
            "    'nightly-sync': {\n"
            "        'task': 'jobs.tasks.sync_orders',\n"
            "        'schedule': crontab(minute='0', hour='2'),\n"
            "    }\n"
            "}\n"
        ),
        "features/orders.py": (
            "from orders.models import Order\n"
            "from jobs.tasks import sync_orders\n\n"
            "def process_order(order_id):\n"
            "    sync_orders.delay(order_id)\n"
            "    return Order\n"
        ),
    }.items():
        path = repo_root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    parsed_files = {
        "orders/models.py": ParsedFile(
            path=Path("orders/models.py"),
            language="python",
            symbols=[
                Symbol(
                    name="Order", kind="class", signature="class Order(models.Model):"
                )
            ],
            imports=["catalog.models"],
        ),
        "catalog/models.py": ParsedFile(
            path=Path("catalog/models.py"),
            language="python",
            symbols=[
                Symbol(
                    name="CatalogItem",
                    kind="class",
                    signature="class CatalogItem(models.Model):",
                )
            ],
            imports=[],
        ),
        "jobs/tasks.py": ParsedFile(
            path=Path("jobs/tasks.py"),
            language="python",
            symbols=[
                Symbol(
                    name="sync_orders",
                    kind="function",
                    signature="def sync_orders(order_id):",
                )
            ],
            imports=[],
        ),
        "jobs/scheduler.py": ParsedFile(
            path=Path("jobs/scheduler.py"),
            language="python",
            symbols=[],
            imports=["jobs.tasks"],
        ),
        "features/orders.py": ParsedFile(
            path=Path("features/orders.py"),
            language="python",
            symbols=[
                Symbol(
                    name="process_order",
                    kind="function",
                    signature="def process_order(order_id):",
                )
            ],
            imports=["orders.models", "jobs.tasks"],
        ),
        "db/orders.js": ParsedFile(
            path=Path("db/orders.js"),
            language="javascript",
            symbols=[],
            imports=[],
        ),
    }
    file_contents = {
        rel_path: (repo_root / rel_path).read_text(encoding="utf-8")
        for rel_path in parsed_files
    }
    scan = RepoScan(
        file_tree={},
        file_summaries={path: "summary" for path in file_contents},
        api_endpoints=[],
        languages={"python": 5, "javascript": 1},
        has_openapi=False,
        openapi_paths=[],
        total_files=len(file_contents),
        frameworks_detected=["django", "celery"],
        entry_points=[],
        config_files=[],
        file_line_counts={
            path: len(content.splitlines()) for path, content in file_contents.items()
        },
        parsed_files=parsed_files,
        file_contents=file_contents,
    )
    scan.artifact_scan = type(
        "ArtifactScan",
        (),
        {
            "database_scan": type(
                "DatabaseScan",
                (),
                {
                    "model_files": [
                        type(
                            "ModelFileInfo",
                            (),
                            {
                                "file_path": "orders/models.py",
                                "model_names": ["Order"],
                                "orm_framework": "django",
                                "is_migration": False,
                            },
                        )(),
                        type(
                            "ModelFileInfo",
                            (),
                            {
                                "file_path": "catalog/models.py",
                                "model_names": ["CatalogItem"],
                                "orm_framework": "django",
                                "is_migration": False,
                            },
                        )(),
                    ],
                    "schema_files": [],
                    "migration_files": ["orders/migrations/0001_initial.py"],
                    "orm_framework": "django",
                    "orm_frameworks": ["django", "knex"],
                    "total_models": 13,
                    "groups": [
                        type(
                            "DatabaseGroup",
                            (),
                            {
                                "key": "orders",
                                "label": "Orders",
                                "file_paths": ["orders/models.py", "db/orders.js"],
                                "model_names": ["Order"],
                                "orm_frameworks": ["django", "knex"],
                                "external_refs": ["catalog"],
                            },
                        )(),
                        type(
                            "DatabaseGroup",
                            (),
                            {
                                "key": "catalog",
                                "label": "Catalog",
                                "file_paths": ["catalog/models.py"],
                                "model_names": ["CatalogItem"],
                                "orm_frameworks": ["django"],
                                "external_refs": ["orders"],
                            },
                        )(),
                    ],
                    "knex_artifacts": [
                        type(
                            "KnexArtifact",
                            (),
                            {
                                "file_path": "db/orders.js",
                                "artifact_type": "schema",
                                "table_name": "orders",
                                "columns": ["id", "status"],
                                "foreign_keys": [],
                                "query_patterns": [],
                            },
                        )()
                    ],
                    "graphql_interfaces": [],
                },
            )()
        },
    )()
    scan.runtime_scan = type(
        "RuntimeScan",
        (),
        {
            "tasks": [
                type(
                    "RuntimeTask",
                    (),
                    {
                        "name": "sync_orders",
                        "file_path": "jobs/tasks.py",
                        "runtime_kind": "celery",
                        "queue": "critical",
                        "retry_policy": "autoretry_for, retry_backoff",
                        "schedule_sources": ["crontab(minute='0', hour='2')"],
                        "triggers": [],
                    },
                )()
            ],
            "schedulers": [
                type(
                    "RuntimeScheduler",
                    (),
                    {
                        "name": "nightly-sync",
                        "file_path": "jobs/scheduler.py",
                        "scheduler_type": "beat",
                        "cron": "crontab(minute='0', hour='2')",
                        "invoked_targets": ["jobs.tasks.sync_orders"],
                    },
                )()
            ],
            "realtime_consumers": [],
        },
    )()

    database_overview = make_bucket(
        "Database & Schema",
        "database-schema",
        ["orders/models.py", "catalog/models.py", "db/orders.js"],
        bucket_type="database",
        section="Database > Database & Schema",
        generation_hints={
            "include_database_context": True,
            "prompt_style": "database_overview",
            "is_database_overview": True,
            "preserve_section": True,
        },
    )
    database_group = make_bucket(
        "Orders Data Model",
        "database-orders",
        ["orders/models.py", "db/orders.js"],
        bucket_type="database-group",
        section="Database > Database & Schema",
        generation_hints={
            "include_database_context": True,
            "prompt_style": "database_group",
            "is_database_group": True,
            "database_group_key": "orders",
            "preserve_section": True,
        },
    )
    runtime_overview = make_bucket(
        "Background Jobs & Runtime",
        "background-jobs",
        ["jobs/tasks.py", "jobs/scheduler.py"],
        bucket_type="runtime",
        section="Background Jobs > Background Jobs & Runtime",
        generation_hints={
            "prompt_style": "runtime_overview",
            "include_runtime_context": True,
            "is_runtime_overview": True,
            "preserve_section": True,
        },
    )
    runtime_tasks = make_bucket(
        "Celery Tasks & Producers",
        "background-jobs-celery",
        ["jobs/tasks.py", "jobs/scheduler.py"],
        bucket_type="runtime-group",
        section="Background Jobs > Background Jobs & Runtime",
        generation_hints={
            "prompt_style": "runtime",
            "include_runtime_context": True,
            "runtime_group_kind": "celery",
            "preserve_section": True,
        },
    )
    feature_bucket = make_bucket(
        "Order Processing",
        "order-processing",
        ["features/orders.py", "orders/models.py", "jobs/tasks.py"],
        bucket_type="feature",
        section="Core Flows",
        generation_hints={"prompt_style": "feature"},
    )
    plan = make_plan(
        [
            database_overview,
            database_group,
            runtime_overview,
            runtime_tasks,
            feature_bucket,
        ]
    )

    cfg = dict(DEFAULT_CONFIG)
    assembler = EvidenceAssembler(repo_root, scan, plan, cfg)
    overview_evidence = assembler.assemble(database_overview)
    group_evidence = assembler.assemble(database_group)
    runtime_evidence = assembler.assemble(runtime_tasks)

    assert "Database Groups" in overview_evidence.database_context
    assert "Orders Data Model" in overview_evidence.database_context
    assert "Knex Artifacts" in overview_evidence.database_context
    assert (
        "GraphQL Interfaces Touching The Data Layer"
        not in overview_evidence.database_context
    )

    assert "`orders/models.py` (django): Order" in group_evidence.database_context
    assert "`catalog/models.py`" not in group_evidence.database_context
    assert "Cross-Group References" in group_evidence.database_context
    assert "db/orders.js" in group_evidence.database_context

    assert "### Tasks" in runtime_evidence.runtime_context
    assert "sync_orders" in runtime_evidence.runtime_context
    assert "queue=critical" in runtime_evidence.runtime_context
    assert "nightly-sync" in runtime_evidence.runtime_context

    engine = BucketGenerationEngine(
        repo_root=repo_root,
        cfg=cfg,
        llm=object(),
        scan=scan,
        plan=plan,
        output_dir=repo_root / "docs",
    )
    dependency_links = engine._build_dependency_links_for(feature_bucket)

    assert "/database-schema" in dependency_links
    assert "/database-orders" in dependency_links
    assert "/background-jobs" in dependency_links
    assert "/background-jobs-celery" in dependency_links


@pytest.mark.skip()
def test_start_here_evidence_uses_integration_identities(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "integrations").mkdir(parents=True)
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "src" / "app.py").write_text(
        "def create_app():\n    return 'ok'\n", encoding="utf-8"
    )
    (repo_root / "integrations" / "vinculum.py").write_text(
        "class VinculumClient:\n    pass\n",
        encoding="utf-8",
    )

    scan = _make_scan(repo_root)
    scan.file_summaries["integrations/vinculum.py"] = "integration client"
    scan.file_contents["integrations/vinculum.py"] = "class VinculumClient:\n    pass\n"
    scan.file_line_counts["integrations/vinculum.py"] = 2
    scan.parsed_files["integrations/vinculum.py"] = ParsedFile(
        path=Path("integrations/vinculum.py"),
        language="python",
        symbols=[
            Symbol(
                name="VinculumClient",
                kind="class",
                signature="class VinculumClient:",
                start_line=1,
                end_line=2,
            )
        ],
        imports=[],
    )
    scan.integration_identities = [
        SimpleNamespace(display_name="Vinculum", files=["integrations/vinculum.py"])
    ]

    bucket = make_bucket(
        "Start Here",
        "start-here",
        ["src/app.py"],
        bucket_type="start_here_index",
        generation_hints={"prompt_style": "start_here_index"},
    )
    plan = make_plan([bucket])

    evidence = EvidenceAssembler(repo_root, scan, plan, dict(DEFAULT_CONFIG)).assemble(
        bucket
    )

    assert (
        "integrations/vinculum.py" in evidence.source_context
        or "integrations/vinculum.py" in evidence.compressed_cards_context
    )


@pytest.mark.skip()
def test_call_graph_context_prefers_exact_method_symbol_and_counts_extra_context(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "config").mkdir(parents=True)
    route_content = (
        "class AuthController:\n"
        "    def on_post(self, req, resp):\n"
        "        return authenticate(req)\n"
    )
    service_content = "def authenticate(req):\n    return req\n"
    env_content = "API_KEY = os.environ.get('API_KEY')\n"
    (repo_root / "src" / "routes.py").write_text(route_content, encoding="utf-8")
    (repo_root / "src" / "service.py").write_text(service_content, encoding="utf-8")
    (repo_root / "config" / "settings.py").write_text(env_content, encoding="utf-8")

    parsed_files = {
        "src/routes.py": ParsedFile(
            path=Path("src/routes.py"),
            language="python",
            symbols=[
                Symbol(
                    name="AuthController",
                    kind="class",
                    signature="class AuthController:",
                    start_line=1,
                    end_line=3,
                ),
                Symbol(
                    name="AuthController.on_post",
                    kind="method",
                    signature="def on_post(self, req, resp):",
                    start_line=2,
                    end_line=3,
                ),
            ],
            imports=["src.service"],
        ),
        "src/service.py": ParsedFile(
            path=Path("src/service.py"),
            language="python",
            symbols=[
                Symbol(
                    name="authenticate",
                    kind="function",
                    signature="def authenticate(req):",
                    start_line=1,
                    end_line=2,
                ),
            ],
            imports=[],
        ),
        "config/settings.py": ParsedFile(
            path=Path("config/settings.py"),
            language="python",
            symbols=[],
            imports=[],
        ),
    }
    file_contents = {
        "src/routes.py": route_content,
        "src/service.py": service_content,
        "config/settings.py": env_content,
    }
    scan = RepoScan(
        file_tree={},
        file_summaries={path: "summary" for path in file_contents},
        api_endpoints=[
            {
                "path": "/auth/login",
                "handler": "AuthController.on_post",
                "file": "src/routes.py",
                "route_file": "src/routes.py",
                "handler_file": "src/routes.py",
            }
        ],
        languages={"python": 3},
        has_openapi=False,
        openapi_paths=[],
        total_files=3,
        frameworks_detected=["falcon"],
        entry_points=[],
        config_files=["config/settings.py"],
        file_line_counts={
            path: len(content.splitlines()) for path, content in file_contents.items()
        },
        parsed_files=parsed_files,
        file_contents=file_contents,
    )
    scan.call_graph = build_call_graph(parsed_files, file_contents)

    bucket = make_bucket(
        "Auth API",
        "auth-api",
        ["src/routes.py", "src/service.py", "config/settings.py"],
        bucket_type="endpoint-family",
        generation_hints={"prompt_style": "endpoint"},
    )
    bucket.owned_symbols = ["AuthController.on_post"]
    plan = make_plan([bucket])

    evidence = EvidenceAssembler(repo_root, scan, plan, dict(DEFAULT_CONFIG)).assemble(
        bucket
    )

    assert "Execution chain: `AuthController.on_post`" in evidence.call_graph_context
    assert "`authenticate`" in evidence.call_graph_context
    assert evidence.total_evidence_chars >= (
        len(evidence.call_graph_context) + len(evidence.config_env_context)
    )
