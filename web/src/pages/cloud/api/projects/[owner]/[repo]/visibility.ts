import type { APIRoute } from "astro";
import { requireSession } from "../../../../../../lib/hosted/session";

// Ported from handleSetVisibility in web/hosted/src/index.ts.
export const POST: APIRoute = async ({ params, request, locals, cookies }) => {
  const env = locals.runtime.env;
  const user = await requireSession(env, cookies);
  if (!user) return new Response(JSON.stringify({ error: "not authenticated" }), { status: 401 });

  const { owner, repo } = params;
  const body = (await request.json().catch(() => null)) as { visibility?: string } | null;
  const visibility = body?.visibility === "public" ? "public" : body?.visibility === "private" ? "private" : null;
  if (!visibility) {
    return new Response(JSON.stringify({ error: "visibility must be 'public' or 'private'" }), { status: 400 });
  }

  // Update the caller's own project row, and the canonical serving row only if
  // the caller owns it (WHERE owner_login = them) — a no-op for anyone else.
  await env.DB.batch([
    env.DB.prepare(
      "UPDATE projects SET visibility = ? WHERE user_login = ? AND LOWER(owner) = LOWER(?) AND LOWER(repo) = LOWER(?)",
    ).bind(visibility, user.login, owner, repo),
    env.DB.prepare(
      "UPDATE owner_repo_jobs SET visibility = ? WHERE LOWER(owner) = LOWER(?) AND LOWER(repo) = LOWER(?) AND LOWER(owner_login) = LOWER(?)",
    ).bind(visibility, owner, repo, user.login),
  ]);

  return new Response(JSON.stringify({ ok: true, visibility }), {
    headers: { "Content-Type": "application/json" },
  });
};
