import type { APIRoute } from "astro";

// Ported from handleAuthStart in web/hosted/src/index.ts.
export const GET: APIRoute = async ({ url, locals }) => {
  const env = locals.runtime.env;
  const state = crypto.randomUUID();
  await env.DB.prepare("INSERT INTO oauth_states (state, created_at) VALUES (?, ?)")
    .bind(state, Date.now())
    .run();

  const redirectUri = `${url.origin}/api/auth/callback/github`;
  const authorizeUrl = new URL("https://github.com/login/oauth/authorize");
  authorizeUrl.searchParams.set("client_id", env.GITHUB_CLIENT_ID);
  authorizeUrl.searchParams.set("redirect_uri", redirectUri);
  // 'repo' (not just read:user) is required to list + clone private repos.
  authorizeUrl.searchParams.set("scope", "repo read:user");
  authorizeUrl.searchParams.set("state", state);
  return new Response(null, {
    status: 302,
    headers: { Location: authorizeUrl.toString() },
  });
};
