"""One-shot entrypoint for an ECS Fargate generation task.

The Cloudflare Pages app starts this task with ``ecs:RunTask`` and passes only a
``JOB_ID`` environment override. The job's real inputs, including the user's
GitHub token, are written by the Pages app to R2 at ``jobs/{id}/input.json``. They
are deliberately not put in the RunTask call, because that call lands in CloudTrail
and in the task description, both of which would then hold a user's GitHub token.

The task reads and deletes that object, runs the shared pipeline, writes status
and the built site to R2, pings Cloudflare to reconcile, and exits. Compute is
only billed while the task runs, so idle cost is zero.

input.json contract (written by web/src/lib/hosted/queue.ts):
  {"job_id","owner","repo","github_token","visibility"}
"""
from __future__ import annotations

import json
import os
import sys

from pipeline import (
    R2_BUCKET,
    _r2_client,
    notify_completion,
    run_generation,
    write_status,
)


def _load_input(job_id: str) -> dict | None:
    client = _r2_client()
    if client is None:
        print("R2 credentials are not configured", file=sys.stderr)
        return None
    key = f"jobs/{job_id}/input.json"
    try:
        body = client.get_object(Bucket=R2_BUCKET, Key=key)["Body"].read()
    except Exception as exc:  # noqa: BLE001
        print(f"could not read {key}: {exc}", file=sys.stderr)
        return None
    # Delete before doing any work so the token never outlives its read, even if
    # the task is killed mid-run.
    try:
        client.delete_object(Bucket=R2_BUCKET, Key=key)
    except Exception as exc:  # noqa: BLE001
        print(f"warning: could not delete {key}: {exc}", file=sys.stderr)
    try:
        return json.loads(body)
    except ValueError:
        return None


def main() -> int:
    job_id = os.environ.get("JOB_ID", "").strip()
    if not job_id:
        print("JOB_ID is not set", file=sys.stderr)
        return 2

    payload = _load_input(job_id)
    if not payload or not (payload.get("owner") and payload.get("repo")):
        write_status(job_id, "failed", "The generation request could not be read. Please start it again.", [])
        notify_completion()
        return 1

    owner, repo = payload["owner"], payload["repo"]
    print(f"processing job {job_id} for {owner}/{repo}", flush=True)
    write_status(job_id, "queued", None, ["task started"])

    result = run_generation(
        job_id, owner, repo, payload.get("github_token"),
        lambda s, e, log: write_status(job_id, s, e, log),
    )

    # Always after a terminal status exists in R2, so projects.status in D1 is
    # corrected now instead of whenever the owner next loads their dashboard.
    notify_completion()
    print(f"job {job_id} finished: {result['status']}", flush=True)
    return 0 if result["status"] == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
