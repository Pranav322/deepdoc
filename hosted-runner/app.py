"""Legacy HTTP runner (pre-queue). Kept working during the cutover to the
event-driven Container Apps Job; the real generation logic now lives in
pipeline.py, shared with job.py. Retire this once the Job path is verified.
"""
from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

from pydantic import BaseModel  # noqa: E402

from pipeline import run_generation  # noqa: E402

RUNNER_SHARED_SECRET = os.environ.get("RUNNER_SHARED_SECRET")


async def verify_shared_secret(authorization: str = Header(default="")) -> None:
    if not RUNNER_SHARED_SECRET or authorization != f"Bearer {RUNNER_SHARED_SECRET}":
        raise HTTPException(status_code=401, detail="unauthorized")


jobs: dict[str, dict] = {}

app = FastAPI(title="deepdoc-hosted-runner", dependencies=[Depends(verify_shared_secret)])


class GenerateRequest(BaseModel):
    owner: str
    repo: str
    repo_url: str
    github_token: str | None = None


def _run_job(job_id: str, owner: str, repo: str, github_token: str | None) -> None:
    job = jobs[job_id]

    def on_status(status: str, error: str | None, log: list) -> None:
        job["status"] = status
        job["log"] = log
        if error:
            job["error"] = error

    result = run_generation(job_id, owner, repo, github_token, on_status)
    if result.get("site_path"):
        job["site_path"] = result["site_path"]


@app.post("/jobs")
def create_job(req: GenerateRequest):
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {
        "status": "pending",
        "owner": req.owner,
        "repo": req.repo,
        "log": [],
        "error": None,
        "site_path": None,
    }
    thread = threading.Thread(target=_run_job, args=(job_id, req.owner, req.repo, req.github_token), daemon=True)
    thread.start()
    return {"job_id": job_id, "status": "pending"}


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="unknown job")
    return {
        "job_id": job_id,
        "status": job["status"],
        "error": job["error"],
        "log_tail": "\n".join(job["log"])[-4000:],
        "site_ready": job["status"] == "done",
    }


@app.get("/jobs/{job_id}/site/{path:path}")
def serve_site(job_id: str, path: str = "index.html"):
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        raise HTTPException(status_code=404, detail="site not ready")
    site_root = Path(job["site_path"]).resolve()
    target = (site_root / (path or "index.html")).resolve()
    if site_root not in target.parents and target != site_root:
        raise HTTPException(status_code=403, detail="path escapes site root")
    if target.is_dir():
        target = target / "index.html"
    if not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(target)


@app.on_event("shutdown")
def _cleanup_note() -> None:
    # ponytail: job workdirs under WORK_ROOT are left on disk for post-mortem
    # debugging during local validation; add TTL cleanup before real deploy.
    pass
