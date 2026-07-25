import type { APIRoute } from "astro";
import { requireSession } from "../../../../lib/hosted/session";
import { fetchJobStatus } from "../../../../lib/hosted/queue";

// Ported from handleStatus in web/hosted/src/index.ts.
export const GET: APIRoute = async ({ params, locals, cookies }) => {
  const env = locals.runtime.env;
  const user = await requireSession(env, cookies);
  if (!user) return new Response(JSON.stringify({ error: "not authenticated" }), { status: 401 });

  const jobId = params.id!;
  const result = await fetchJobStatus(env, jobId);

  if (result.status) {
    await env.DB.prepare("UPDATE projects SET status = ? WHERE job_id = ? AND user_login = ?")
      .bind(result.status, jobId, user.login)
      .run();
  }

  return new Response(result.text, { headers: { "Content-Type": "application/json" } });
};
