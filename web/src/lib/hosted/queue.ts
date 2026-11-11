// Dispatch and status for generation jobs.
//
// Dispatch = write the job's input to R2, then start one ECS Fargate task that
// reads it. There is no queue to run: the task starts immediately and exits when
// the job ends, so idle cost is zero. Status comes back through R2 the same way
// it always did, so this layer never talks to a running container.

import { runGenerationTask, type AwsEnv } from "./aws";

export interface CloudEnv extends AwsEnv {
  DB: D1Database;
  SITES: R2Bucket;
  GITHUB_CLIENT_ID: string;
  GITHUB_SECRET_ID: string;
}

// The user's GitHub token is in `payload`, so it goes to R2 (private bucket, read
// once and deleted by the task) and never into the RunTask call.
export async function enqueueJob(env: CloudEnv, payload: { job_id: string } & Record<string, unknown>): Promise<boolean> {
  const key = `jobs/${payload.job_id}/input.json`;
  await env.SITES.put(key, JSON.stringify(payload), { httpMetadata: { contentType: "application/json" } });
  const started = await runGenerationTask(env, payload.job_id);
  if (!started) {
    // Nothing will ever read it, so don't leave a token sitting in the bucket.
    await env.SITES.delete(key).catch(() => undefined);
  }
  return started;
}

// Read a job's current status from R2 (jobs/{id}/status.json), which the task
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
