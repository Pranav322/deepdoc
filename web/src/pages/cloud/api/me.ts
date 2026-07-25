import type { APIRoute } from "astro";
import { requireSession } from "../../../lib/hosted/session";

// Ported from handleMe in web/hosted/src/index.ts.
export const GET: APIRoute = async ({ locals, cookies }) => {
  const user = await requireSession(locals.runtime.env, cookies);
  if (!user) return new Response(JSON.stringify({ authenticated: false }), { status: 200 });
  return new Response(
    JSON.stringify({ authenticated: true, login: user.login, avatarUrl: user.avatarUrl }),
    { status: 200 },
  );
};
