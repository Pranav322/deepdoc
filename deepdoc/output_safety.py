"""Ownership-aware output directory safety.

DeepDoc must never treat a parent directory as disposable merely because it
was configured as an output root. This module validates configured paths,
records generated paths, and classifies roots before writes or cleanup.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

import click


OWNERSHIP_FILE = "output_ownership.json"
_DEEPDOC_MARKERS = (
    "deepdoc_generated_at:",
    "deepdoc_generated_version:",
)


@dataclass(frozen=True)
class OutputPaths:
    output_dir: Path
    site_dir: Path


@dataclass
class RootInspection:
    root: Path
    owned_files: set[Path] = field(default_factory=set)
    unmanaged_files: set[Path] = field(default_factory=set)
    tracked_files: set[Path] = field(default_factory=set)

    @property
    def state(self) -> str:
        if not self.root.exists():
            return "missing"
        if not any(self.root.iterdir()):
            return "empty"
        if self.tracked_files:
            return "tracked_authored"
        if self.unmanaged_files:
            return "mixed" if self.owned_files else "unmanaged"
        return "deepdoc_only"

    @property
    def safe_for_generation(self) -> bool:
        return self.state in {"missing", "empty", "deepdoc_only"}


def resolve_output_paths(repo_root: Path, cfg: dict[str, Any]) -> OutputPaths:
    """Return validated repository-contained output and site paths."""
    output_dir = _resolve_repo_relative(
        repo_root, str(cfg.get("output_dir") or "deepdoc-docs"), "output_dir"
    )
    site_dir = _resolve_repo_relative(
        repo_root, str(cfg.get("site_dir") or "deepdoc-site"), "site_dir"
    )
    if _overlaps(output_dir, site_dir):
        raise click.ClickException(
            "output_dir and site_dir must be separate, non-overlapping "
            "repository-relative directories."
        )
    return OutputPaths(output_dir=output_dir, site_dir=site_dir)


def inspect_output_root(
    repo_root: Path,
    root: Path,
    *,
    kind: str,
) -> RootInspection:
    """Classify files below one generated-output root.

    Ownership is exact-path based. Legacy generated Markdown is adopted only
    when it has DeepDoc provenance frontmatter; unknown files stay preserved.
    """
    inspection = RootInspection(root=root)
    if not root.exists() or not root.is_dir():
        return inspection

    ownership = _load_ownership(repo_root)
    expected_root = ownership.get(f"{kind}_dir")
    owned_rel = (
        set(ownership.get(f"{kind}_files", []))
        if expected_root == _repo_relative(repo_root, root)
        else set()
    )
    owned_hashes = ownership.get(f"{kind}_hashes", {}) if owned_rel else {}
    legacy_owned = (
        _legacy_owned_output_paths(repo_root, root) if kind == "output" else set()
    )
    all_files = [path for path in root.rglob("*") if path.is_file()]

    for path in all_files:
        rel = _repo_relative(repo_root, path)
        expected_hash = owned_hashes.get(rel)
        owned = rel in owned_rel and (
            not expected_hash or expected_hash == _file_hash(path)
        )
        if path in legacy_owned:
            owned = True
        if not owned and kind == "output" and _is_legacy_deepdoc_markdown(path):
            owned = True
        if not owned and kind == "output" and path.name == ".deepdoc_manifest.json":
            owned = True
        if not owned and kind == "site" and path.name == "deepdoc.config.json":
            owned = True
        if not owned and kind == "site" and _is_legacy_deepdoc_site_file(root, path):
            owned = True
        if owned:
            inspection.owned_files.add(path)
        else:
            inspection.unmanaged_files.add(path)

    tracked = _git_tracked_paths(repo_root, root)
    inspection.tracked_files = {
        path for path in tracked if path not in inspection.owned_files
    }
    return inspection


def assert_safe_for_generation(repo_root: Path, cfg: dict[str, Any]) -> OutputPaths:
    """Refuse to write into roots containing unowned or tracked content."""
    paths = resolve_output_paths(repo_root, cfg)
    inspections = (
        inspect_output_root(repo_root, paths.output_dir, kind="output"),
        inspect_output_root(repo_root, paths.site_dir, kind="site"),
    )
    unsafe = [inspection for inspection in inspections if not inspection.safe_for_generation]
    if not unsafe:
        return paths

    details: list[str] = []
    for inspection in unsafe:
        examples = sorted(
            {_repo_relative(repo_root, p) for p in inspection.tracked_files | inspection.unmanaged_files}
        )[:5]
        detail = f"{_repo_relative(repo_root, inspection.root)}/ ({inspection.state})"
        if examples:
            detail += "\n  " + "\n  ".join(f"- {path}" for path in examples)
        details.append(detail)

    raise click.ClickException(
        "Refusing to write DeepDoc output into existing repository content.\n\n"
        + "\n\n".join(details)
        + "\n\nUse dedicated paths, for example:\n"
        + "  deepdoc config set output_dir deepdoc-docs\n"
        + "  deepdoc config set site_dir deepdoc-site"
    )


def clean_owned_outputs(
    repo_root: Path,
    cfg: dict[str, Any],
) -> tuple[list[Path], list[Path]]:
    """Delete exact owned generated files and return (removed, preserved)."""
    paths = resolve_output_paths(repo_root, cfg)
    removed: list[Path] = []
    preserved: list[Path] = []
    for root, kind in ((paths.output_dir, "output"), (paths.site_dir, "site")):
        inspection = inspect_output_root(repo_root, root, kind=kind)
        preserved.extend(sorted(inspection.unmanaged_files | inspection.tracked_files))
        for path in sorted(inspection.owned_files, reverse=True):
            try:
                path.unlink()
                removed.append(path)
            except OSError:
                continue
        _remove_empty_directories(root)
    return removed, preserved


def record_output_ownership(
    repo_root: Path,
    paths: OutputPaths,
    *,
    output_files: set[Path],
    site_files: set[Path],
) -> None:
    """Persist exact generated paths for future safe cleanup."""
    state_dir = repo_root / ".deepdoc"
    state_dir.mkdir(parents=True, exist_ok=True)
    previous = _load_ownership(repo_root)
    output_files = _retained_owned_files(
        repo_root, previous, "output", paths.output_dir, output_files
    )
    site_files = _retained_owned_files(
        repo_root, previous, "site", paths.site_dir, site_files
    )
    output_existing = {
        path for path in output_files if path.exists() and path.is_file()
    }
    site_existing = {
        path for path in site_files if path.exists() and path.is_file()
    }
    payload = {
        "schema_version": 1,
        "output_dir": _repo_relative(repo_root, paths.output_dir),
        "site_dir": _repo_relative(repo_root, paths.site_dir),
        "output_files": sorted(_repo_relative(repo_root, path) for path in output_existing),
        "site_files": sorted(_repo_relative(repo_root, path) for path in site_existing),
        "output_hashes": {
            _repo_relative(repo_root, path): _file_hash(path)
            for path in output_existing
        },
        "site_hashes": {
            _repo_relative(repo_root, path): _file_hash(path)
            for path in site_existing
        },
    }
    _ownership_path(repo_root).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _load_ownership(repo_root: Path) -> dict[str, Any]:
    try:
        return json.loads(_ownership_path(repo_root).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def _ownership_path(repo_root: Path) -> Path:
    return repo_root / ".deepdoc" / OWNERSHIP_FILE


def _retained_owned_files(
    repo_root: Path,
    ownership: dict[str, Any],
    kind: str,
    root: Path,
    newly_written: set[Path],
) -> set[Path]:
    """Keep prior generated files only while their recorded hashes still match."""
    retained = {path for path in newly_written if path.exists() and path.is_file()}
    if ownership.get(f"{kind}_dir") != _repo_relative(repo_root, root):
        return retained
    hashes = ownership.get(f"{kind}_hashes", {})
    for rel in ownership.get(f"{kind}_files", []):
        expected = hashes.get(rel)
        if not expected:
            continue
        path = repo_root / rel
        if path.is_file() and _file_hash(path) == expected:
            retained.add(path)
    return retained


def _resolve_repo_relative(repo_root: Path, value: str, field: str) -> Path:
    raw = Path(value.strip())
    if not value.strip() or raw.is_absolute() or ".." in raw.parts:
        raise click.ClickException(
            f"{field} must be a non-empty repository-relative directory without '..'."
        )
    root = repo_root.resolve()
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise click.ClickException(f"{field} must remain inside the repository.") from exc
    if candidate == root or candidate.name in {".git", ".deepdoc", "chatbot_backend"}:
        raise click.ClickException(f"{field} cannot target {candidate.name or 'the repository root'}.")
    return candidate


def _overlaps(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _repo_relative(repo_root: Path, path: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _is_legacy_deepdoc_markdown(path: Path) -> bool:
    if path.suffix.lower() not in {".md", ".mdx"}:
        return False
    try:
        header = path.read_text(encoding="utf-8", errors="replace")[:20_000]
    except OSError:
        return False
    return any(marker in header for marker in _DEEPDOC_MARKERS)


def _legacy_owned_output_paths(repo_root: Path, output_root: Path) -> set[Path]:
    """Read legacy ledger doc_path entries without trusting paths outside output."""
    try:
        ledger = json.loads((repo_root / ".deepdoc" / "ledger.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return set()
    owned: set[Path] = set()
    for record in ledger.values() if isinstance(ledger, dict) else []:
        if not isinstance(record, dict):
            continue
        doc_paths = record.get("doc_paths") or [record.get("doc_path", "")]
        for value in doc_paths:
            if not value:
                continue
            candidate = (output_root / str(value)).resolve()
            try:
                candidate.relative_to(output_root.resolve())
            except ValueError:
                continue
            if candidate.is_file():
                owned.add(candidate)
    return owned


def _is_legacy_deepdoc_site_file(root: Path, path: Path) -> bool:
    """Adopt known scaffold files from pre-ownership-manifest sites.

    Only shipped template paths and specifically named DeepDoc assets are
    adopted; arbitrary custom files below a legacy scaffold remain unowned.
    """
    if not (root / "deepdoc.config.json").is_file():
        return False
    rel = path.relative_to(root).as_posix()
    if rel == "deepdoc.config.json":
        return True
    if rel == ".env.local":
        try:
            return path.read_text(encoding="utf-8", errors="replace").startswith(
                "DEEPDOC_DOCS_DIR="
            )
        except OSError:
            return False
    if rel == "app/globals.css":
        try:
            return "Brand colors — overwritten by `deepdoc generate`" in path.read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            return False
    if rel.startswith("openapi/deepdoc-openapi-") or rel == "openapi/manifest.json":
        return True
    try:
        from .site.builder.next_builder import _TEMPLATE_DIR

        template_paths = {
            candidate.relative_to(_TEMPLATE_DIR).as_posix()
            for candidate in _TEMPLATE_DIR.rglob("*")
            if candidate.is_file()
        }
    except Exception:
        return False
    if rel not in template_paths:
        return False
    try:
        return path.read_bytes() == (_TEMPLATE_DIR / rel).read_bytes()
    except OSError:
        return False


def _git_tracked_paths(repo_root: Path, root: Path) -> set[Path]:
    try:
        rel = _repo_relative(repo_root, root)
        result = subprocess.run(
            ["git", "ls-files", "-z", "--", rel],
            cwd=repo_root,
            capture_output=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    return {
        repo_root / item.decode("utf-8", errors="replace")
        for item in result.stdout.split(b"\0")
        if item
    }


def _remove_empty_directories(root: Path) -> None:
    if not root.exists():
        return
    for directory in sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        try:
            directory.rmdir()
        except OSError:
            continue
    try:
        root.rmdir()
    except OSError:
        pass


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "OutputInspection",
    "OutputPaths",
    "assert_safe_for_generation",
    "clean_owned_outputs",
    "inspect_output_root",
    "record_output_ownership",
    "resolve_output_paths",
]
