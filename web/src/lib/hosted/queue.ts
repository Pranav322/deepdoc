// Ported verbatim from web/hosted/src/index.ts — the Azure Storage Queue
// dispatch contract is unchanged by the Astro migration; only the caller
// (Astro endpoints instead of a raw Worker fetch handler) is different.

export interface CloudEnv {
  DB: D1Database;
  SITES: R2Bucket;
  GITHUB_CLIENT_ID: string;
  GITHUB_SECRET_ID: string;
  QUEUE_MESSAGES_URL: string;
}

// Enqueue a generation request onto the Azure Storage Queue. The message text
// is base64(JSON) — matches job.py's TextBase64DecodePolicy — wrapped in the
// Storage Queue REST XML envelope. KEDA scales the Job on queue length, so this
// enqueue is the entire dispatch: no runner to call, no replica to hit.
export async function enqueueJob(env: CloudEnv, payload: unknown): Promise<boolean> {
  const b64 = btoa(JSON.stringify(payload));
  const body = `<QueueMessage><MessageText>${b64}</MessageText></QueueMessage>`;
  const res = await fetch(env.QUEUE_MESSAGES_URL, {
    method: "POST",
    headers: { "Content-Type": "application/xml" },
    body,
  });
  return res.ok;
}

// Read a job's current status from R2 (jobs/{id}/status.json), which the Job
// writes as it progresses. Durable and independent of any container.
export async function fetchJobStatus(
  env: CloudEnv,
  jobId: string,
): Promise<{ status: string | null; error: string | null; text: string; executionName: string | null }> {
  const obj = await env.SITES.get(`jobs/${jobId}/status.json`);
  if (!obj)
    return { status: null, error: null, text: JSON.stringify({ status: "queued" }), executionName: null };
  const text = await obj.text();
  try {
    const d = JSON.parse(text) as { status: string; error: string | null; execution_name?: string | null };
    return { status: d.status, error: d.error ?? null, text, executionName: d.execution_name ?? null };
  } catch {
    return { status: null, error: null, text, executionName: null };
  }
}
