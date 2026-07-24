"""Shared generation pipeline: clone a repo, run deepdoc generate + deploy,
upload the built site to R2, and publish progress to R2 as status.json.

Both entrypoints reuse this — the legacy HTTP server (app.py) and the
event-driven job consumer (job.py) — so there is exactly one source of truth
for what a generation actually does.
"""
from __future__ import annotations

import json
import mimetypes
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

DEEPDOC_YAML = """\
project_name: {name}
output_dir: docs
site_dir: site

llm:
  provider: azure
  model: azure/DeepSeek-V4-Flash
  api_key_env: AZURE_API_KEY
  base_url: https://deepdoc-foundry.services.ai.azure.com/
  max_tokens: null
  temperature: 0.2
  context_window_tokens: 128000
  output_reserve_tokens: 16000
  api_version: '2024-02-01'

chatbot:
  enabled: false
"""

WORK_ROOT = Path(tempfile.gettempdir()) / "deepdoc-hosted-jobs"
WORK_ROOT.mkdir(exist_ok=True)

# Local dev uses a `.venv` next to this file; the container installs deepdoc
# globally, so `deepdoc` is just on PATH there.
_local_venv_bin = Path(__file__).resolve().parent / ".venv" / "bin" / "deepdoc"
DEEPDOC_BIN = str(_local_venv_bin) if _local_venv_bin.is_file() else (shutil.which("deepdoc") or "deepdoc")

R2_ACCOUNT_ID = "8a2cef39862f19036324a81881b974a9"
R2_BUCKET = "deepdoc-hosted-sites"
R2_ENDPOINT = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")

# Progress callback: (status, error_or_None, log_lines) — app.py updates its
# in-memory dict, job.py writes it to R2. Terminal statuses: done | failed.
StatusCb = Callable[[str, "str | None", list], None]


def _r2_client():
    if not R2_ACCESS_KEY_ID or not R2_SECRET_ACCESS_KEY:
        return None
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def write_status(job_id: str, status: str, error: str | None = None, log: list | None = None) -> None:
    """Best-effort publish of jobs/{job_id}/status.json to R2 — this is what the
    Worker reads to report progress, now that there's no long-lived runner to
    ask. A failure here must never crash the job."""
    client = _r2_client()
    if client is None:
        return
    body = {
        "job_id": job_id,
        "status": status,
        "error": error,
        "log_tail": ("\n".join(log)[-4000:] if log else None),
        "updated_at": int(time.time()),
    }
    try:
        client.put_object(
            Bucket=R2_BUCKET,
            Key=f"jobs/{job_id}/status.json",
            Body=json.dumps(body).encode("utf-8"),
            ContentType="application/json",
        )
    except Exception:  # noqa: BLE001 — status publishing is best-effort
        pass


def upload_site_to_r2(owner: str, repo: str, site_out: Path, log: list) -> None:
    client = _r2_client()
    if client is None:
        log.append("R2 credentials not configured — skipping upload")
        return
    prefix = f"{owner.lower()}/{repo.lower()}/"
    count = 0
    for file_path in site_out.rglob("*"):
        if not file_path.is_file():
            continue
        rel = file_path.relative_to(site_out).as_posix()
        content_type = mimetypes.guess_type(rel)[0] or "application/octet-stream"
        client.put_object(
            Bucket=R2_BUCKET, Key=prefix + rel, Body=file_path.read_bytes(), ContentType=content_type
        )
        count += 1
    log.append(f"uploaded {count} files to R2 at {prefix}")


def _run(
    cmd: list[str],
    cwd: Path,
    log: list,
    extra_env: dict[str, str] | None = None,
    redact: str | None = None,
) -> None:
    echoed = " ".join(cmd)
    if redact:
        echoed = echoed.replace(redact, "***")
    log.append(f"$ {echoed}")
    env = {**os.environ, **extra_env} if extra_env else None
    # No timeout — a legitimately slow generation/build shouldn't be killed;
    # only a real non-zero exit is a failure.
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    log.append(result.stdout)
    if result.stderr:
        log.append(result.stderr)
    if result.returncode != 0:
        # Surface the real reason (e.g. the quality gate's blocker list) instead
        # of a bare "deepdoc deploy failed" — this tail is what the UI shows.
        detail = (result.stderr or result.stdout or "").strip()
        detail_tail = "\n".join(detail.splitlines()[-12:])
        raise RuntimeError(f"command failed ({result.returncode}): {echoed}\n{detail_tail}")


def run_generation(
    job_id: str,
    owner: str,
    repo: str,
    github_token: str | None,
    on_status: StatusCb,
) -> dict:
    """Clone → generate → deploy → upload. Calls on_status at each stage.
    Returns {status, site_path?/error?, log}. Never raises — failures come back
    as {status: 'failed', error}."""
    log: list = []
    job_dir = WORK_ROOT / job_id
    repo_dir = job_dir / "repo"

    def stage(s: str, err: str | None = None) -> None:
        on_status(s, err, log)

    try:
        stage("cloning")
        job_dir.mkdir(parents=True, exist_ok=True)
        clone_url = (
            f"https://x-access-token:{github_token}@github.com/{owner}/{repo}.git"
            if github_token
            else f"https://github.com/{owner}/{repo}.git"
        )
        _run(["git", "clone", "--depth", "1", clone_url, str(repo_dir)], cwd=job_dir, log=log, redact=github_token)

        (repo_dir / ".deepdoc.yaml").write_text(DEEPDOC_YAML.format(name=repo))

        stage("generating")
        _run([DEEPDOC_BIN, "generate", "--clean", "--yes"], cwd=repo_dir, log=log)

        stage("building")
        # basePath baked at build time to match the /{owner}/{repo}/ serving path.
        _run(
            [DEEPDOC_BIN, "deploy"],
            cwd=repo_dir,
            log=log,
            extra_env={"NEXT_PUBLIC_BASE_PATH": f"/{owner}/{repo}"},
        )

        site_out = repo_dir / "site" / "out"
        if not site_out.is_dir():
            raise RuntimeError("deploy finished but site/out/ was not produced")

        upload_site_to_r2(owner, repo, site_out, log)

        stage("done")
        return {"status": "done", "site_path": str(site_out), "log": log}
    except Exception as exc:  # noqa: BLE001 — surface any failure to status
        stage("failed", str(exc))
        return {"status": "failed", "error": str(exc), "log": log}
