#!/usr/bin/env python3
"""Optional manual smoke check against a shallow checkout of real FastAPI.

This command does not call an LLM or generate documentation. It verifies that
legacy docs/site configuration auto-migrates to dedicated DeepDoc paths while
the tracked FastAPI docs tree remains unchanged.

Examples:
  python scripts/verify_fastapi_product_gate.py --repo /path/to/fastapi
  python scripts/verify_fastapi_product_gate.py --clone /tmp/fastapi-smoke
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deepdoc.output_safety import assert_safe_for_generation


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--repo", type=Path)
    group.add_argument("--clone", type=Path, help="Destination for a shallow FastAPI clone")
    args = parser.parse_args()

    if args.clone:
        if args.clone.exists():
            print(f"Refusing to overwrite existing path: {args.clone}", file=sys.stderr)
            return 2
        subprocess.run(
            ["git", "clone", "--depth", "1", "https://github.com/fastapi/fastapi.git", str(args.clone)],
            check=True,
        )
        repo = args.clone
    else:
        repo = args.repo.resolve()

    if not (repo / ".git").exists() or not (repo / "docs").exists():
        print("Expected a FastAPI checkout with .git and docs/", file=sys.stderr)
        return 2

    before = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout
    cfg = {"output_dir": "docs", "site_dir": "site"}
    paths = assert_safe_for_generation(repo, cfg)
    after = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout

    assert paths.output_dir == repo / "deepdoc-docs"
    assert paths.site_dir == repo / "deepdoc-site"
    assert before == after
    print("PASS: FastAPI authored docs preserved; DeepDoc selected dedicated output roots.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
