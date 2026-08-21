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
  # Real deployment limits: 1,000,000 token context window, 128,000 token
  # max output. The old context_window_tokens: 128000 was wrong — it was
  # the *output* limit, not the context window — so the planner's classify
  # step was budgeting off a window ~8x smaller than the model actually
  # has, and a large repo (e.g. a 154K-token required classify prompt)
  # could hard-fail on a false token-budget error after already burning
  # hours in the scan phase.
  context_window_tokens: 1000000
  output_reserve_tokens: 128000
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


# Container Apps Jobs names each pod "{execution-name}-{replica-suffix}" and
# sets HOSTNAME to that pod name (standard k8s behavior this platform runs
# on) — confirmed against real logs ("Execution: 'deepdoc-gen-job-m4r9q',
# Replica: 'deepdoc-gen-job-m4r9q-xv67h'"). Stripping the last dash segment
# recovers the execution name, which the Worker needs to call the Azure
# stop-execution API on delete.
JOB_NAME = "deepdoc-gen-job"


def _current_execution_name() -> str | None:
    hostname = os.environ.get("HOSTNAME", "")
    if hostname.startswith(JOB_NAME + "-") and "-" in hostname[len(JOB_NAME) + 1 :]:
        return hostname.rsplit("-", 1)[0]
    return None


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
        "execution_name": _current_execution_name(),
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


def _iter_r2_keys(client, prefix: str):
    """Every key under prefix. Paginates — a large docs site easily exceeds the
    1000-key page limit, and missing the tail would leave stale files behind."""
    token = None
    while True:
        kwargs = {"Bucket": R2_BUCKET, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        page = client.list_objects_v2(**kwargs)
        for obj in page.get("Contents", []) or []:
            yield obj["Key"]
        if not page.get("IsTruncated"):
            return
        token = page.get("NextContinuationToken")
        if not token:
            return


def upload_site_to_r2(owner: str, repo: str, site_out: Path, log: list) -> None:
    client = _r2_client()
    if client is None:
        log.append("R2 credentials not configured — skipping upload")
        return
    prefix = f"{owner.lower()}/{repo.lower()}/"

    files = [p for p in site_out.rglob("*") if p.is_file()]

    # Upload assets before HTML.
    #
    # A regenerate writes into the same prefix a live site is being served
    # from, so ordering decides what a visitor mid-rebuild actually gets.
    # Uploading in rglob order meant new HTML could land while it still
    # referenced content-hashed chunks that hadn't been written yet — the
    # visitor got a missing-chunk error, or Next's "Unexpected token '<'"
    # when the 404 body came back as HTML. Writing every asset first means
    # old HTML keeps resolving against old chunks (still present) until the
    # moment new HTML appears, by which point its chunks are already there.
    def is_html(p: Path) -> bool:
        return p.suffix.lower() in (".html", ".htm")

    ordered = [p for p in files if not is_html(p)] + [p for p in files if is_html(p)]

    uploaded_keys = set()
    for file_path in ordered:
        rel = file_path.relative_to(site_out).as_posix()
        content_type = mimetypes.guess_type(rel)[0] or "application/octet-stream"
        key = prefix + rel
        client.put_object(
            Bucket=R2_BUCKET, Key=key, Body=file_path.read_bytes(), ContentType=content_type
        )
        uploaded_keys.add(key)
    log.append(f"uploaded {len(uploaded_keys)} files to R2 at {prefix}")

    # Sweep whatever the previous build left behind.
    #
    # Uploads used to be purely additive, so a page deleted or renamed between
    # builds stayed reachable forever, and superseded chunk files accumulated
    # in the prefix indefinitely. Done after the upload rather than before so
    # the site is never a 404 window; the objects removed here are by
    # definition ones the new build does not reference.
    try:
        stale = [k for k in _iter_r2_keys(client, prefix) if k not in uploaded_keys]
        for i in range(0, len(stale), 1000):  # delete_objects caps at 1000
            client.delete_objects(
                Bucket=R2_BUCKET,
                Delete={"Objects": [{"Key": k} for k in stale[i : i + 1000]], "Quiet": True},
            )
        if stale:
            log.append(f"removed {len(stale)} stale files left by the previous build")
    except Exception as exc:  # noqa: BLE001 — a failed sweep must not fail the build
        log.append(f"stale-file sweep failed (non-fatal): {exc}")


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
    print(f"$ {echoed}", flush=True)
    env = {**os.environ, **extra_env} if extra_env else None
    # No timeout — a legitimately slow generation/build shouldn't be killed;
    # only a real non-zero exit is a failure.
    #
    # Popen + line-by-line streaming, not subprocess.run(capture_output=True):
    # capture_output fully buffers the child's stdout/stderr in memory and
    # only hands it back once the process exits, so a multi-hour scan/plan
    # step produced literally nothing in Azure's logs until it was already
    # done or dead — no way to tell "still working" from "hung" from
    # outside. Printing each line as it arrives makes it our own process's
    # stdout in real time, which is what Azure's log stream actually reads.
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    output_lines: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="", flush=True)
        output_lines.append(line)
    proc.wait()
    combined = "".join(output_lines)
    log.append(combined)
    if proc.returncode != 0:
        # Surface the real reason (e.g. the quality gate's blocker list) instead
        # of a bare "deepdoc deploy failed" — this tail is what the UI shows.
        detail_tail = "\n".join(combined.strip().splitlines()[-12:])
        raise RuntimeError(f"command failed ({proc.returncode}): {echoed}\n{detail_tail}")


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
