import type { APIRoute } from "astro";
import { requireSession } from "../../../../../lib/hosted/session";

// Ported from handleDeleteProject in web/hosted/src/index.ts.
export const DELETE: APIRoute = async ({ params, locals, cookies }) => {
  const env = locals.runtime.env;
  const user = await requireSession(env, cookies);
  if (!user) return new Response(JSON.stringify({ error: "not authenticated" }), { status: 401 });

  const { owner, repo } = params;
  const result = await env.DB.prepare(
    "DELETE FROM projects WHERE user_login = ? AND LOWER(owner) = LOWER(?) AND LOWER(repo) = LOWER(?)",
  )
    .bind(user.login, owner, repo)
    .run();
  return new Response(JSON.stringify({ deleted: (result.meta.changes ?? 0) > 0 }), {
    headers: { "Content-Type": "application/json" },
  });
};
