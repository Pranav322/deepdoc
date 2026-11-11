"""FastAPI router prefixes must survive a ``src/`` layout.

In ``src/app/main.py``, ``from app.api import notes`` refers to
``src/app/api/notes.py``: ``src/`` is on ``sys.path``, not the repo root. The
import index only tried repo-root paths, so the mount's ``prefix="/notes"`` was
attached to ``main.py`` instead of ``notes.py`` and every notes route was recorded
as ``/`` or ``/{id}``. The generated docs then cited the real ``/notes/...``
routes, the claim validator found them "ungrounded", and the page was marked
invalid, which blocks ``deepdoc deploy``.
"""
from __future__ import annotations

import io
from contextlib import redirect_stdout
from copy import deepcopy
from pathlib import Path

from deepdoc.config import DEFAULT_CONFIG
from deepdoc.parser.routes.repo_resolver import _resolve_python_module_path
from deepdoc.planner import scan_repo

MAIN = """\
from fastapi import FastAPI

from app.api import notes, ping

app = FastAPI()

app.include_router(ping.router)
app.include_router(notes.router, prefix="/notes", tags=["notes"])
"""

NOTES = """\
from fastapi import APIRouter

router = APIRouter()


@router.post("/", status_code=201)
async def create_note():
    return {}


@router.get("/{id}/")
async def read_note(id: int):
    return {}
"""

PING = """\
from fastapi import APIRouter

router = APIRouter()


@router.get("/ping")
async def pong():
    return {"ping": "pong!"}
"""


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_src_layout_router_prefix_is_applied(tmp_path: Path) -> None:
    _write(tmp_path, "src/app/__init__.py", "")
    _write(tmp_path, "src/app/api/__init__.py", "")
    _write(tmp_path, "src/app/main.py", MAIN)
    _write(tmp_path, "src/app/api/notes.py", NOTES)
    _write(tmp_path, "src/app/api/ping.py", PING)

    with redirect_stdout(io.StringIO()):
        scan = scan_repo(tmp_path, deepcopy(DEFAULT_CONFIG))

    routes = {(ep["method"], ep["path"]) for ep in scan.published_api_endpoints}
    assert ("POST", "/notes") in routes or ("POST", "/notes/") in routes
    assert any(m == "GET" and p.startswith("/notes/{id}") for m, p in routes)
    assert ("GET", "/ping") in routes
    assert not any(p in ("/", "/{id}", "/{id}/") for _, p in routes)


def test_absolute_import_resolves_from_an_ancestor_source_root() -> None:
    known = {"src/app/main.py", "src/app/api/notes.py", "src/app/api/__init__.py"}
    assert (
        _resolve_python_module_path("src/app/main.py", "app.api", known, "notes")
        == "src/app/api/notes.py"
    )


def test_repo_root_match_still_wins() -> None:
    known = {"app/api/notes.py", "src/app/api/notes.py", "src/app/main.py"}
    assert (
        _resolve_python_module_path("src/app/main.py", "app.api", known, "notes")
        == "app/api/notes.py"
    )


def test_deepdoc_config_file_is_not_scanned(tmp_path: Path) -> None:
    """DeepDoc's own .deepdoc.yaml is tool config, not the user's project."""
    _write(tmp_path, "src/app/main.py", MAIN)
    _write(tmp_path, ".deepdoc.yaml", "project_name: app\nllm:\n  provider: azure\n")

    with redirect_stdout(io.StringIO()):
        scan = scan_repo(tmp_path, deepcopy(DEFAULT_CONFIG))

    scanned = set(scan.file_summaries) | set(scan.file_contents)
    assert ".deepdoc.yaml" not in scanned
    assert "src/app/main.py" in scanned


def test_deepdoc_legacy_state_files_are_not_scanned(tmp_path: Path) -> None:
    """persistence_v2 writes .deepdoc_plan.json/.deepdoc_file_map.json to the repo
    root; the next run must not treat them as project files."""
    _write(tmp_path, "src/app/main.py", MAIN)
    _write(tmp_path, ".deepdoc_plan.json", "{}")
    _write(tmp_path, ".deepdoc_file_map.json", "{}")

    with redirect_stdout(io.StringIO()):
        scan = scan_repo(tmp_path, deepcopy(DEFAULT_CONFIG))

    scanned = set(scan.file_summaries) | set(scan.file_contents)
    assert not {".deepdoc_plan.json", ".deepdoc_file_map.json"} & scanned


def test_ambiguous_ancestor_match_stays_unresolved() -> None:
    """With src/api.py and src/app/api.py both present, `import api` from
    src/app/main.py depends on which directory is on sys.path; don't guess."""
    known = {"src/app/main.py", "src/api.py", "src/app/api.py"}
    assert _resolve_python_module_path("src/app/main.py", "api", known, None) == ""
