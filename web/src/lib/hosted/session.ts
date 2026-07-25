// Ported from web/hosted/src/index.ts — session/quota logic is unchanged;
// only cookie handling now goes through Astro's `cookies` API instead of
// manual Cookie/Set-Cookie header parsing.
import type { AstroCookies } from "astro";
import type { CloudEnv } from "./queue";

export interface Session {
  login: string;
  id: number;
  avatarUrl: string;
  token: string;
}

export const MAX_SAVED_PROJECTS = 2;
export const MAX_STARTS_PER_DAY = 2;
export const DAY_MS = 24 * 60 * 60 * 1000;
export const SESSION_TTL_MS = 30 * DAY_MS;
export const OAUTH_STATE_TTL_MS = 10 * 60 * 1000;
export const SESSION_COOKIE = "dd_session";

// Logins (lowercased) exempt from all quota limits — the product owner(s).
const UNLIMITED_LOGINS = new Set(["pranav322"]);
export function isUnlimited(login: string): boolean {
  return UNLIMITED_LOGINS.has(login.toLowerCase());
}

export function setSessionCookie(cookies: AstroCookies, sessionId: string): void {
  // Max-Age (via `maxAge`) makes this a PERSISTENT cookie that survives a
  // browser close, matching the 30-day server-side session TTL.
  cookies.set(SESSION_COOKIE, sessionId, {
    path: "/",
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    maxAge: Math.floor(SESSION_TTL_MS / 1000),
  });
}

export async function requireSession(env: CloudEnv, cookies: AstroCookies): Promise<Session | null> {
  const sid = cookies.get(SESSION_COOKIE)?.value;
  if (!sid) return null;
  const row = await env.DB.prepare("SELECT * FROM sessions WHERE id = ? AND expires_at > ?")
    .bind(sid, Date.now())
    .first<{ login: string; github_id: number; avatar_url: string; token: string }>();
  if (!row) return null;
  return { login: row.login, id: row.github_id, avatarUrl: row.avatar_url, token: row.token };
}

export async function countRecentStarts(env: CloudEnv, login: string): Promise<number> {
  const cutoff = Date.now() - DAY_MS;
  await env.DB.prepare("DELETE FROM rate_limit_starts WHERE user_login = ? AND started_at <= ?")
    .bind(login, cutoff)
    .run();
  const row = await env.DB.prepare("SELECT COUNT(*) AS n FROM rate_limit_starts WHERE user_login = ?")
    .bind(login)
    .first<{ n: number }>();
  return row?.n ?? 0;
}

export function parseGithubRepoUrl(value: string): { owner: string; repo: string } | null {
  try {
    const u = new URL(value);
    if (u.hostname !== "github.com") return null;
    const parts = u.pathname.split("/").filter(Boolean);
    if (parts.length !== 2) return null;
    return { owner: parts[0], repo: parts[1].replace(/\.git$/, "") };
  } catch {
    return null;
  }
}
