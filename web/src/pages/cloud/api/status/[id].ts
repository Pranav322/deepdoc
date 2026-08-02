import type { APIRoute } from "astro";
import { requireSession } from "../../../../lib/hosted/session";
import { fetchJobStatus } from "../../../../lib/hosted/queue";

// Ported from handleStatus in web/hosted/src/index.ts.
export const GET: APIRoute = async ({ params, locals, cookies }) => {
  const env = locals.runtime.env;
  const user = await requireSession(env, cookies);
  if (!user) return new Response(JSON.stringify({ error: "not authenticated" }), { status: 401 });

  const jobId = params.id!;

  // Scope the job to the caller before reading it. status.json carries
  // log_tail — the last 4000 chars of build output, which for a private repo
  // can include file paths and source excerpts — so without this any signed-in
  // user could read any other user's build log by job id. The site proxy
  // already gates on ownership this way; this endpoint did not.
  const owned = await env.DB.prepare(
    "SELECT 1 FROM projects WHERE job_id = ? AND user_login = ?",
  )
    .bind(jobId, user.login)
    .first();
  if (!owned) return new Response(JSON.stringify({ error: "not found" }), { status: 404 });

  const result = await fetchJobStatus(env, jobId);

  if (result.status) {
    await env.DB.prepare("UPDATE projects SET status = ? WHERE job_id = ? AND user_login = ?")
      .bind(result.status, jobId, user.login)
      .run();
  }

  return new Response(result.text, { headers: { "Content-Type": "application/json" } });
};
