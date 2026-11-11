"""Shared generation pipeline: clone a repo, run deepdoc generate + deploy,
upload the built site to R2, and publish progress to R2 as status.json.

job.py (the ECS Fargate task entrypoint) is the only caller, so this is the one
source of truth for what a generation actually does.
"""
from __future__ import annotations

import json
import mimetypes
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

def build_deepdoc_yaml(name: str) -> str:
    """The .deepdoc.yaml written into every cloned repo.

    The model is chosen by environment (set on the ECS task definition), so
    swapping providers or models is a task-definition change, not a code change.
    Defaults target Amazon Bedrock through the task role, so there is no API key
    to store: LiteLLM's Bedrock provider signs with the task's IAM credentials.
    """
    model = os.environ.get("DEEPDOC_LLM_MODEL", "bedrock/converse/openai.gpt-oss-120b-1:0")
    provider = os.environ.get("DEEPDOC_LLM_PROVIDER") or model.split("/", 1)[0]
    api_key_env = os.environ.get("DEEPDOC_LLM_API_KEY_ENV", "")
    # Capability numbers must be explicit: LiteLLM has no metadata for many
    # Bedrock aliases, and an unknown model otherwise falls back (loudly) to a
    # generic 128K window.
    context = int(os.environ.get("DEEPDOC_LLM_CONTEXT_TOKENS", "128000"))
    reserve = int(os.environ.get("DEEPDOC_LLM_OUTPUT_RESERVE_TOKENS", "16000"))
    lines = [
        f"project_name: {name}",
        "output_dir: docs",
        "site_dir: site",
        "",
        "llm:",
        f"  provider: {provider}",
        f"  model: {model}",
        f"  api_key_env: '{api_key_env}'",
        "  max_tokens: null",
        "  temperature: 0.2",
        f"  context_window_tokens: {context}",
        f"  output_reserve_tokens: {reserve}",
    ]
    base_url = os.environ.get("DEEPDOC_LLM_BASE_URL")
    api_version = os.environ.get("DEEPDOC_LLM_API_VERSION")
    if base_url:
        lines.append(f"  base_url: {base_url}")
    if api_version:
        lines.append(f"  api_version: '{api_version}'")
    lines += ["", "chatbot:", "  enabled: false", ""]
    return "\n".join(lines)


WORK_ROOT = Path(tempfile.gettempdir()) / "deepdoc-hosted-jobs"
WORK_ROOT.mkdir(exist_ok=True)

# Local dev uses a `.venv` next to this file; the container installs deepdoc
# globally, so `deepdoc` is just on PATH there.
_local_venv_bin = Path(__file__).resolve().parent / ".venv" / "bin" / "deepdoc"
DEEPDOC_BIN = str(_local_venv_bin) if _local_venv_bin.is_file() else (shutil.which("deepdoc") or "deepdoc")

R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "8a2cef39862f19036324a81881b974a9")
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


def _current_execution_name() -> str | None:
    """ARN of the ECS task this process runs in, so the Cloudflare app can stop
    it when a project is deleted mid-run. Read from the task metadata endpoint
    that Fargate injects; None outside ECS (local dev)."""
    uri = os.environ.get("ECS_CONTAINER_METADATA_URI_V4")
    if not uri:
        return None
    try:
        with urllib.request.urlopen(f"{uri}/task", timeout=2) as resp:
            return json.loads(resp.read()).get("TaskARN")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
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


RECONCILE_URL = os.environ.get("RECONCILE_URL", "https://cloud.deepdoc.tech/api/internal/reconcile")


def notify_completion() -> None:
    """Tell Cloudflare a job just reached a terminal state, so `projects.status`
    in D1 gets corrected immediately instead of staying stale until the owning
    user happens to reload /api/projects.

    Deliberately a plain "go check R2" ping, not "job {id} is {status}": the
    reconcile endpoint already knows how to read jobs/{id}/status.json (which
    write_status() just wrote) and it sweeps every stale row in one pass, so
    there's no new payload contract to keep in sync between this container and
    the Cloudflare side — one shared idea of "the truth is in R2" instead of
    two.

    Best-effort like write_status(): RECONCILE_SECRET may be unset (local dev
    has no reason to configure it), the network call may fail, and none of
    that should affect whether the job itself succeeded. A 15-minute-stale
    row is a UI inconvenience; retrying a whole generation because a
    notification ping failed would not be a fair trade.
    """
    secret = os.environ.get("RECONCILE_SECRET")
    if not secret:
        return
    req = urllib.request.Request(
        RECONCILE_URL,
        data=b"{}",
        method="POST",
        headers={"X-Reconcile-Secret": secret, "Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except (urllib.error.URLError, TimeoutError, OSError):
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
    # step produced literally nothing in CloudWatch until it was already
    # done or dead — no way to tell "still working" from "hung" from
    # outside. Printing each line as it arrives makes it our own process's
    # stdout in real time, which is what the awslogs driver actually reads.
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


# ── Cost guard ───────────────────────────────────────────────────────────────
# Two layers keep one generation under MAX_USD:
#   1. preflight_estimate(): refuse a repo whose estimated cost is clearly over.
#   2. budget/sitecustomize.py: a hard stop inside every `deepdoc` subprocess that
#      counts real tokens from each LiteLLM response and exits when spend passes
#      the cap. The estimate is a heuristic (multipliers below are NOT yet
#      calibrated against real runs), so layer 2 is the one that actually bounds
#      the bill.
MAX_USD = float(os.environ.get("DEEPDOC_MAX_USD", "1.00"))
PRICE_IN_PER_M = float(os.environ.get("DEEPDOC_PRICE_IN_PER_M", "0.15"))    # gpt-oss-120b on Bedrock
PRICE_OUT_PER_M = float(os.environ.get("DEEPDOC_PRICE_OUT_PER_M", "0.60"))
EST_INPUT_MULT = float(os.environ.get("DEEPDOC_EST_INPUT_MULT", "2.5"))     # prompt tokens per source token
EST_OUTPUT_MULT = float(os.environ.get("DEEPDOC_EST_OUTPUT_MULT", "0.15"))  # completion tokens per source token

_SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build", "static", "media", ".venv", "venv", "target", "out"}
_SOURCE_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".php", ".vue", ".java", ".rs"}


def estimate_source_tokens(repo_dir: Path) -> int:
    total_bytes = 0
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and "venv" not in d]
        for name in files:
            if Path(name).suffix.lower() in _SOURCE_EXTS and ".min." not in name:
                try:
                    total_bytes += min((Path(root) / name).stat().st_size, 1_000_000)
                except OSError:
                    pass
    return total_bytes // 4


def preflight_estimate(repo_dir: Path) -> tuple[float, int]:
    tokens = estimate_source_tokens(repo_dir)
    cost = (tokens * EST_INPUT_MULT * PRICE_IN_PER_M + tokens * EST_OUTPUT_MULT * PRICE_OUT_PER_M) / 1_000_000
    return cost, tokens


def budget_env(job_dir: Path) -> dict[str, str]:
    """Env that arms the in-process spend cap for deepdoc subprocesses."""
    budget_dir = str(Path(__file__).resolve().parent / "budget")
    existing = os.environ.get("PYTHONPATH", "")
    return {
        "PYTHONPATH": budget_dir + (os.pathsep + existing if existing else ""),
        "DEEPDOC_BUDGET_FILE": str(job_dir / "spend.json"),
        "DEEPDOC_MAX_USD": str(MAX_USD),
        "DEEPDOC_PRICE_IN_PER_M": str(PRICE_IN_PER_M),
        "DEEPDOC_PRICE_OUT_PER_M": str(PRICE_OUT_PER_M),
    }


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

        (repo_dir / ".deepdoc.yaml").write_text(build_deepdoc_yaml(repo))

        est_cost, est_tokens = preflight_estimate(repo_dir)
        log.append(f"preflight: ~{est_tokens:,} source tokens, estimated cost ~${est_cost:.2f} (cap ${MAX_USD:.2f})")
        if est_cost > MAX_USD:
            raise RuntimeError(
                f"{owner}/{repo} is too large for the hosted tier: about {est_tokens:,} source tokens "
                f"would cost roughly ${est_cost:.2f}, over the ${MAX_USD:.2f} per-generation limit."
            )

        stage("generating")
        _run([DEEPDOC_BIN, "generate", "--clean", "--yes"], cwd=repo_dir, log=log, extra_env=budget_env(job_dir))

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
