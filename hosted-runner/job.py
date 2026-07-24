"""Event-driven job entrypoint for Azure Container Apps Jobs.

KEDA scales this job on the length of the `deepdoc-jobs` Azure Storage Queue;
each execution runs this script, which pulls exactly one message, processes it,
and exits. The container is ephemeral and isolated per execution — no shared
memory, no long-lived server.

Message contract (produced by the Cloudflare Worker's handleGenerate): the
queue MessageText is base64 of a JSON object
  {"job_id","owner","repo","github_token","visibility"}
We configure TextBase64DecodePolicy so `msg.content` is the decoded JSON string
— this must match how the Worker encodes it.
"""
from __future__ import annotations

import json
import os
import sys

from dotenv import load_dotenv

# Load a local .env when present (dev); in the container, env comes from
# Container App secrets and this is a harmless no-op.
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from azure.storage.queue import QueueClient, TextBase64DecodePolicy  # noqa: E402

from pipeline import run_generation, write_status  # noqa: E402


def main() -> int:
    conn = os.environ["QUEUE_CONN"]
    queue_name = os.environ.get("QUEUE_NAME", "deepdoc-jobs")
    qc = QueueClient.from_connection_string(
        conn, queue_name, message_decode_policy=TextBase64DecodePolicy()
    )

    # Long visibility timeout: the message stays invisible for the whole
    # generation so it isn't redelivered mid-run, and KEDA won't count it as
    # still-pending and spin up a duplicate execution for the same job.
    msgs = qc.receive_messages(max_messages=1, visibility_timeout=3600)
    msg = next(iter(msgs), None)
    if msg is None:
        print("no message to process; exiting")
        return 0

    try:
        payload = json.loads(msg.content)
    except Exception as exc:  # noqa: BLE001
        print(f"unparseable message, discarding: {exc}")
        qc.delete_message(msg)
        return 0

    job_id = payload.get("job_id")
    owner = payload.get("owner")
    repo = payload.get("repo")
    token = payload.get("github_token")
    if not (job_id and owner and repo):
        print(f"message missing required fields, discarding: {payload.keys()}")
        qc.delete_message(msg)
        return 0

    print(f"processing job {job_id} for {owner}/{repo}")
    write_status(job_id, "queued", None, ["picked up by worker execution"])

    result = run_generation(job_id, owner, repo, token, lambda s, e, log: write_status(job_id, s, e, log))

    # Delete on ANY terminal state (done OR failed) so a message is never
    # retried forever. A hard crash before this line leaves the message to
    # reappear after the visibility timeout; --replica-retry-limit bounds that.
    qc.delete_message(msg)
    print(f"job {job_id} finished: {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
