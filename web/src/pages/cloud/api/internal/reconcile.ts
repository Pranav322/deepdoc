import type { APIRoute } from "astro";
import { fetchJobStatus } from "../../../../lib/hosted/queue";

/**
 * Sweeps `projects` rows stuck in a non-terminal status and refreshes them
 * from R2 (`jobs/{id}/status.json`), which is the real source of truth.
 *
 * Why this exists: `GET /api/projects` already does exactly this refresh —
 * but only for the calling user's own rows, and only when they happen to
 * load that page. A job that finishes while its owner never looks again
 * (or a project belonging to a user who signs in once and vanishes) stays
 * "generating"/"queued" in D1 forever, even though R2 says `done`. This was
 * found live: three projects sat stale for 9 minutes to 28 days — two had
 * actually finished successfully days/weeks earlier. Fixing it required a
 * manual `wrangler d1 execute UPDATE` each time, which does not scale and
 * was the whole point of this endpoint.
 *
 * Called on a schedule by an Azure Container Apps Job (`deepdoc-reconcile`,
 * `--trigger-type Schedule`) — see docs/PRODUCTION_INFRA.md. Cloudflare
 * Pages has no native Cron Triggers (verified against the Pages project
 * config API: no cron/trigger field exists), so the schedule lives on the
 * Azure side, which already runs the generation compute.
 */
const MAX_ROWS_PER_SWEEP = 100;

export const POST: APIRoute = async ({ request, locals }) => {
  const env = locals.runtime.env;
  const secret = request.headers.get("X-Reconcile-Secret");
  if (!secret || !env.RECONCILE_SECRET || secret !== env.RECONCILE_SECRET) {
    return new Response(JSON.stringify({ error: "unauthorized" }), { status: 401 });
  }

  const { results } = await env.DB.prepare(
    `SELECT user_login, owner, repo, job_id, status FROM projects
     WHERE status NOT IN ('done', 'failed')
     ORDER BY created_at ASC
     LIMIT ?`,
  )
    .bind(MAX_ROWS_PER_SWEEP)
    .all<{ user_login: string; owner: string; repo: string; job_id: string; status: string }>();

  const updated: Array<{ owner: string; repo: string; from: string; to: string }> = [];
  let stillPending = 0;

  for (const row of results) {
    const refreshed = await fetchJobStatus(env, row.job_id);
    // fetchJobStatus returns status: null both when jobs/{id}/status.json
    // doesn't exist yet (genuinely still queued) and on a parse failure —
    // either way, "no new information" means leave the row alone rather
    // than overwrite a real status with an unknown one.
    if (!refreshed.status || refreshed.status === row.status) {
      stillPending++;
      continue;
    }
    await env.DB.prepare("UPDATE projects SET status = ? WHERE job_id = ? AND user_login = ?")
      .bind(refreshed.status, row.job_id, row.user_login)
      .run();
    updated.push({ owner: row.owner, repo: row.repo, from: row.status, to: refreshed.status });
  }

  return new Response(
    JSON.stringify({ checked: results.length, updated, stillPending }),
    { headers: { "Content-Type": "application/json" } },
  );
};
