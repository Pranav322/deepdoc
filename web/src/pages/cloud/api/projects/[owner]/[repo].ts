import type { APIRoute } from "astro";
import { requireSession } from "../../../../../lib/hosted/session";
import { fetchJobStatus } from "../../../../../lib/hosted/queue";
import { stopJobExecution } from "../../../../../lib/hosted/azure";

// Ported from handleDeleteProject in web/hosted/src/index.ts. Deleting a
// project used to only remove the D1 row — the Azure Container Apps Job
// execution kept running (and billing) for as long as it took to finish or
// crash on its own, sometimes 12+ hours (see openclaw/openclaw). Now: if the
// project's job hasn't reached a terminal state, ask Azure to stop that
// execution before removing the row. Best-effort — a stop failure (job
// already finished, execution_name not yet written) must never block the
// delete itself.
export const DELETE: APIRoute = async ({ params, locals, cookies }) => {
  const env = locals.runtime.env;
  const user = await requireSession(env, cookies);
  if (!user) return new Response(JSON.stringify({ error: "not authenticated" }), { status: 401 });

  const { owner, repo } = params;
  const row = await env.DB.prepare(
    "SELECT job_id FROM projects WHERE user_login = ? AND LOWER(owner) = LOWER(?) AND LOWER(repo) = LOWER(?)",
  )
    .bind(user.login, owner, repo)
    .first<{ job_id: string }>();

  if (row?.job_id) {
    const jobStatus = await fetchJobStatus(env, row.job_id);
    if (jobStatus.status !== "done" && jobStatus.status !== "failed" && jobStatus.executionName) {
      await stopJobExecution(env, jobStatus.executionName);
    }
  }

  const result = await env.DB.prepare(
    "DELETE FROM projects WHERE user_login = ? AND LOWER(owner) = LOWER(?) AND LOWER(repo) = LOWER(?)",
  )
    .bind(user.login, owner, repo)
    .run();
  return new Response(JSON.stringify({ deleted: (result.meta.changes ?? 0) > 0 }), {
    headers: { "Content-Type": "application/json" },
  });
};
