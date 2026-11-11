import type { APIRoute } from "astro";
import { requireSession } from "../../../lib/hosted/session";

// Ported from handleMe in web/hosted/src/index.ts.
export const GET: APIRoute = async ({ locals, cookies }) => {
  const env = locals.runtime.env;
  // Tells the client to show the "generation is paused" notice on every screen,
  // including to logged-out visitors on the public gallery.
  const generationPaused = env.GENERATION_PAUSED === "1";
  const user = await requireSession(env, cookies);
  if (!user) return new Response(JSON.stringify({ authenticated: false, generationPaused }), { status: 200 });
  return new Response(
    JSON.stringify({ authenticated: true, login: user.login, avatarUrl: user.avatarUrl, generationPaused }),
    { status: 200 },
  );
};
