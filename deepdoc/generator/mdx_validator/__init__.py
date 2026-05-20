"""MDX compile-check used as the final correctness gate in generation.

Shells out to a small Node script (``validate.mjs``) that runs
``@mdx-js/mdx``'s ``compile()`` on the page. The Python wrapper exposes a
synchronous ``validate_mdx`` that returns a typed outcome, plus helpers for
bootstrap and node-availability checks.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import click

_VALIDATOR_DIR = Path(__file__).resolve().parent
_VALIDATE_SCRIPT = _VALIDATOR_DIR / "validate.mjs"
_NODE_MODULES = _VALIDATOR_DIR / "node_modules"
_BOOTSTRAP_LOCK = Lock()
_BOOTSTRAP_DONE = False


@dataclass(frozen=True)
class MdxCompileError:
    """Structured information about an MDX compile failure."""

    message: str
    line: int | None = None
    column: int | None = None
    rule_id: str | None = None

    def short(self) -> str:
        location = ""
        if self.line is not None:
            location = f" at line {self.line}"
            if self.column is not None:
                location += f", column {self.column}"
        return f"{self.message}{location}".strip()


@dataclass(frozen=True)
class ValidationOutcome:
    """Result of running ``validate_mdx`` on a single page."""

    ok: bool
    error: MdxCompileError | None = None


def ensure_node_available() -> str:
    """Return the path to ``node`` or raise a clear ``ClickException``."""
    node = shutil.which("node")
    if not node:
        raise click.ClickException(
            "Node 18+ is required for MDX validation but `node` was not found "
            "on PATH. Install it from https://nodejs.org and retry. "
            "Node is already required to build/serve the Fumadocs site."
        )
    return node


def bootstrap_validator() -> None:
    """Install the validator's Node dependencies if not already present.

    Idempotent and process-safe via a module-level lock. Network installs run
    only on first use; subsequent calls return immediately.
    """
    global _BOOTSTRAP_DONE
    if _BOOTSTRAP_DONE:
        return
    with _BOOTSTRAP_LOCK:
        if _BOOTSTRAP_DONE:
            return
        ensure_node_available()
        if _NODE_MODULES.exists():
            _BOOTSTRAP_DONE = True
            return
        npm = shutil.which("npm")
        if not npm:
            raise click.ClickException(
                "`npm` was not found on PATH. Install Node 18+ (which ships "
                "with npm) from https://nodejs.org and retry."
            )
        try:
            subprocess.run(
                [npm, "install", "--no-audit", "--no-fund", "--loglevel=error"],
                cwd=str(_VALIDATOR_DIR),
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            stderr_tail = (e.stderr or "").strip().splitlines()[-5:]
            raise click.ClickException(
                "Failed to install the MDX validator's Node dependencies. "
                "Run `npm install` inside "
                f"{_VALIDATOR_DIR} manually to see the full error.\n"
                + "\n".join(stderr_tail)
            ) from e
        _BOOTSTRAP_DONE = True


def validate_mdx(content: str, *, timeout_seconds: float = 30.0) -> ValidationOutcome:
    """Run ``@mdx-js/mdx`` compile() on ``content``.

    Returns an ``ValidationOutcome`` with ``ok=True`` on clean compile, or
    ``ok=False`` with a populated ``MdxCompileError`` on failure.

    Raises ``click.ClickException`` if Node/npm is missing or the bootstrap
    install fails — these are environment problems, not page problems.
    """
    bootstrap_validator()
    node = ensure_node_available()
    try:
        completed = subprocess.run(
            [node, str(_VALIDATE_SCRIPT)],
            input=content,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return ValidationOutcome(
            ok=False,
            error=MdxCompileError(
                message=f"MDX compile timed out after {timeout_seconds:.0f}s",
                rule_id="validator-timeout",
            ),
        )
    except OSError as e:
        return ValidationOutcome(
            ok=False,
            error=MdxCompileError(
                message=f"Failed to launch MDX validator: {e}",
                rule_id="validator-launch-error",
            ),
        )

    if completed.returncode == 0:
        return ValidationOutcome(ok=True)

    stderr = (completed.stderr or "").strip()
    if not stderr:
        return ValidationOutcome(
            ok=False,
            error=MdxCompileError(
                message="MDX validator exited with no diagnostic output",
                rule_id="validator-empty-stderr",
            ),
        )
    try:
        payload = json.loads(stderr.splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return ValidationOutcome(
            ok=False,
            error=MdxCompileError(
                message=stderr[:500],
                rule_id="validator-unparseable",
            ),
        )

    return ValidationOutcome(
        ok=False,
        error=MdxCompileError(
            message=str(payload.get("message") or "unknown MDX compile error"),
            line=payload.get("line"),
            column=payload.get("column"),
            rule_id=payload.get("ruleId"),
        ),
    )


__all__ = [
    "MdxCompileError",
    "ValidationOutcome",
    "bootstrap_validator",
    "ensure_node_available",
    "validate_mdx",
]
