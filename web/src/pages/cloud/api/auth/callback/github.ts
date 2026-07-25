import type { APIRoute } from "astro";
import { SESSION_TTL_MS, OAUTH_STATE_TTL_MS, setSessionCookie } from "../../../../../lib/hosted/session";

// Ported from handleAuthCallback in web/hosted/src/index.ts.
export const GET: APIRoute = async ({ url, locals, cookies }) => {
  const env = locals.runtime.env;
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  if (!code || !state) return new Response("Invalid OAuth state", { status: 400 });

  await env.DB.prepare("DELETE FROM oauth_states WHERE created_at < ?")
    .bind(Date.now() - OAUTH_STATE_TTL_MS)
    .run();

  const stateRow = await env.DB.prepare("SELECT state FROM oauth_states WHERE state = ?").bind(state).first();
  if (!stateRow) return new Response("Invalid OAuth state", { status: 400 });
  await env.DB.prepare("DELETE FROM oauth_states WHERE state = ?").bind(state).run();

  const tokenRes = await fetch("https://github.com/login/oauth/access_token", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      client_id: env.GITHUB_CLIENT_ID,
      client_secret: env.GITHUB_SECRET_ID,
      code,
    }),
  });
  const tokenData = (await tokenRes.json()) as { access_token?: string; error?: string };
  if (!tokenData.access_token) {
    return new Response(`GitHub token exchange failed: ${tokenData.error ?? "unknown"}`, { status: 400 });
  }

  const userRes = await fetch("https://api.github.com/user", {
    headers: {
      Authorization: `Bearer ${tokenData.access_token}`,
      "User-Agent": "deepdoc-hosted",
    },
  });
  const user = (await userRes.json()) as { login: string; id: number; avatar_url: string };

  const sessionId = crypto.randomUUID();
  const now = Date.now();
  await env.DB.prepare(
    "INSERT INTO sessions (id, login, github_id, avatar_url, token, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
  )
    .bind(sessionId, user.login, user.id, user.avatar_url, tokenData.access_token, now, now + SESSION_TTL_MS)
    .run();

  setSessionCookie(cookies, sessionId);

  // "/" — the client decides the default view (projects if you have any,
  // otherwise generate). Keeping one canonical entry point instead of
  // hardcoding a page here.
  return new Response(null, { status: 302, headers: { Location: "/" } });
};
