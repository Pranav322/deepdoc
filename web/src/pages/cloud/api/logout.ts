import type { APIRoute } from "astro";
import { SESSION_COOKIE } from "../../../lib/hosted/session";

// Ported from handleLogout in web/hosted/src/index.ts.
export const POST: APIRoute = async ({ locals, cookies }) => {
  const sid = cookies.get(SESSION_COOKIE)?.value;
  if (sid) {
    await locals.runtime.env.DB.prepare("DELETE FROM sessions WHERE id = ?").bind(sid).run();
  }
  cookies.delete(SESSION_COOKIE, { path: "/" });
  return new Response(JSON.stringify({ ok: true }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
};
