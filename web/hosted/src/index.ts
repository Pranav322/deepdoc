import { tryPageHtml, stalePageHtml, privateSitePage } from "./try_page";

export interface Env {
  GITHUB_CLIENT_ID: string;
  GITHUB_SECRET_ID: string;
  DB: D1Database;
  SITES: R2Bucket;
  // Azure Storage Queue the generation Jobs consume. QUEUE_MESSAGES_URL is the
  // full queue "/messages" endpoint including a SAS token with 'add' permission
  // (stored as a secret). Enqueuing here is what triggers a KEDA-scaled Job.
  QUEUE_MESSAGES_URL: string;
}

const CONTENT_TYPES: Record<string, string> = {
  html: "text/html; charset=utf-8",
  css: "text/css; charset=utf-8",
  js: "application/javascript; charset=utf-8",
  json: "application/json; charset=utf-8",
  svg: "image/svg+xml",
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  ico: "image/x-icon",
  txt: "text/plain; charset=utf-8",
  xml: "application/xml; charset=utf-8",
  webmanifest: "application/manifest+json",
};

function guessContentType(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  return CONTENT_TYPES[ext] ?? "application/octet-stream";
}

interface Session {
  login: string;
  id: number;
  avatarUrl: string;
  token: string;
}

interface Project {
  owner: string;
  repo: string;
  jobId: string;
  status: string;
  createdAt: number;
  description?: string | null;
  language?: string | null;
  avatarUrl?: string | null;
  visibility?: string;
}

const MAX_SAVED_PROJECTS = 2;
const MAX_STARTS_PER_DAY = 2;
const DAY_MS = 24 * 60 * 60 * 1000;
const SESSION_TTL_MS = 30 * DAY_MS;
const OAUTH_STATE_TTL_MS = 10 * 60 * 1000;

// Logins (lowercased) exempt from all quota limits — the product owner(s).
const UNLIMITED_LOGINS = new Set(["pranav322"]);
function isUnlimited(login: string): boolean {
  return UNLIMITED_LOGINS.has(login.toLowerCase());
}

function cookie(name: string, req: Request): string | null {
  const header = req.headers.get("Cookie") || "";
  const match = header.match(new RegExp(`(?:^|;\\s*)${name}=([^;]+)`));
  return match ? decodeURIComponent(match[1]) : null;
}

function setCookie(
  name: string,
  value: string,
  // Max-Age makes this a PERSISTENT cookie that survives a browser close,
  // matching the 30-day server-side session TTL. Without it the browser drops
  // the cookie on quit and the user has to log in again every launch.
  opts = `Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${Math.floor(SESSION_TTL_MS / 1000)}`,
): string {
  return `${name}=${encodeURIComponent(value)}; ${opts}`;
}

// Enqueue a generation request onto the Azure Storage Queue. The message text
// is base64(JSON) — matches job.py's TextBase64DecodePolicy — wrapped in the
// Storage Queue REST XML envelope. KEDA scales the Job on queue length, so this
// enqueue is the entire dispatch: no runner to call, no replica to hit.
async function enqueueJob(env: Env, payload: unknown): Promise<boolean> {
  const b64 = btoa(JSON.stringify(payload));
  const body = `<QueueMessage><MessageText>${b64}</MessageText></QueueMessage>`;
  const res = await fetch(env.QUEUE_MESSAGES_URL, {
    method: "POST",
    headers: { "Content-Type": "application/xml" },
    body,
  });
  return res.ok;
}

// Read a job's current status from R2 (jobs/{id}/status.json), which the Job
// writes as it progresses. Replaces the old "ask the runner over HTTP" call —
// durable and independent of any container.
async function fetchJobStatus(
  env: Env,
  jobId: string,
): Promise<{ status: string | null; error: string | null; text: string }> {
  const obj = await env.SITES.get(`jobs/${jobId}/status.json`);
  if (!obj) return { status: null, error: null, text: JSON.stringify({ status: "queued" }) };
  const text = await obj.text();
  try {
    const d = JSON.parse(text) as { status: string; error: string | null };
    return { status: d.status, error: d.error ?? null, text };
  } catch {
    return { status: null, error: null, text };
  }
}

async function handleAuthStart(req: Request, env: Env): Promise<Response> {
  const state = crypto.randomUUID();
  await env.DB.prepare("INSERT INTO oauth_states (state, created_at) VALUES (?, ?)")
    .bind(state, Date.now())
    .run();

  const url = new URL(req.url);
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
}

async function handleAuthCallback(req: Request, env: Env): Promise<Response> {
  const url = new URL(req.url);
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

  return new Response(null, {
    status: 302,
    headers: {
      Location: "/try",
      "Set-Cookie": setCookie("dd_session", sessionId),
    },
  });
}

async function handleLogout(req: Request, env: Env): Promise<Response> {
  const sid = cookie("dd_session", req);
  if (sid) {
    await env.DB.prepare("DELETE FROM sessions WHERE id = ?").bind(sid).run();
  }
  return new Response(JSON.stringify({ ok: true }), {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      // Expire the cookie immediately so the browser drops it.
      "Set-Cookie": "dd_session=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0",
    },
  });
}

async function requireSession(req: Request, env: Env): Promise<Session | null> {
  const sid = cookie("dd_session", req);
  if (!sid) return null;
  const row = await env.DB.prepare("SELECT * FROM sessions WHERE id = ? AND expires_at > ?")
    .bind(sid, Date.now())
    .first<{ login: string; github_id: number; avatar_url: string; token: string }>();
  if (!row) return null;
  return { login: row.login, id: row.github_id, avatarUrl: row.avatar_url, token: row.token };
}

async function handleMe(req: Request, env: Env): Promise<Response> {
  const user = await requireSession(req, env);
  if (!user) return new Response(JSON.stringify({ authenticated: false }), { status: 200 });
  return new Response(
    JSON.stringify({ authenticated: true, login: user.login, avatarUrl: user.avatarUrl }),
    { status: 200 },
  );
}

async function handleRepos(req: Request, env: Env): Promise<Response> {
  const user = await requireSession(req, env);
  if (!user) return new Response(JSON.stringify({ error: "not authenticated" }), { status: 401 });

  const reposRes = await fetch(
    "https://api.github.com/user/repos?affiliation=owner&sort=updated&per_page=100",
    { headers: { Authorization: `Bearer ${user.token}`, "User-Agent": "deepdoc-hosted" } },
  );
  if (!reposRes.ok) {
    return new Response(JSON.stringify({ error: "failed to list repos", detail: await reposRes.text() }), {
      status: 502,
    });
  }
  const repos = (await reposRes.json()) as Array<{
    full_name: string;
    name: string;
    owner: { login: string; avatar_url: string };
    private: boolean;
    updated_at: string;
    description: string | null;
    language: string | null;
  }>;
  const simplified = repos.map((r) => ({
    fullName: r.full_name,
    owner: r.owner.login,
    repo: r.name,
    private: r.private,
    updatedAt: r.updated_at,
    description: r.description,
    language: r.language,
    avatarUrl: r.owner.avatar_url,
  }));
  return new Response(JSON.stringify(simplified), { headers: { "Content-Type": "application/json" } });
}

function parseGithubRepoUrl(value: string): { owner: string; repo: string } | null {
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

async function countRecentStarts(env: Env, login: string): Promise<number> {
  const cutoff = Date.now() - DAY_MS;
  await env.DB.prepare("DELETE FROM rate_limit_starts WHERE user_login = ? AND started_at <= ?")
    .bind(login, cutoff)
    .run();
  const row = await env.DB.prepare("SELECT COUNT(*) AS n FROM rate_limit_starts WHERE user_login = ?")
    .bind(login)
    .first<{ n: number }>();
  return row?.n ?? 0;
}

async function handleGenerate(req: Request, env: Env): Promise<Response> {
  const user = await requireSession(req, env);
  if (!user) return new Response(JSON.stringify({ error: "not authenticated" }), { status: 401 });

  const body = (await req.json().catch(() => null)) as
    | {
        owner?: string;
        repo?: string;
        repo_url?: string;
        description?: string | null;
        language?: string | null;
        avatarUrl?: string | null;
        visibility?: string;
      }
    | null;

  const visibility = body?.visibility === "public" ? "public" : "private";

  let owner: string;
  let repo: string;
  if (body?.owner && body?.repo) {
    owner = body.owner;
    repo = body.repo;
  } else if (body?.repo_url) {
    const parsed = parseGithubRepoUrl(body.repo_url);
    if (!parsed) {
      return new Response(
        JSON.stringify({ error: "repo_url must be a https://github.com/<owner>/<repo> URL" }),
        { status: 400 },
      );
    }
    owner = parsed.owner;
    repo = parsed.repo;
  } else {
    return new Response(JSON.stringify({ error: "provide either {owner, repo} or {repo_url}" }), {
      status: 400,
    });
  }

  // One canonical site per repo: if this repo already has a site owned by a
  // different DeepDoc user, refuse — a second user must not clobber it.
  const existingJobRow = await env.DB.prepare(
    "SELECT job_id, owner_login FROM owner_repo_jobs WHERE LOWER(owner) = LOWER(?) AND LOWER(repo) = LOWER(?)",
  )
    .bind(owner, repo)
    .first<{ job_id: string; owner_login: string | null }>();
  if (existingJobRow) {
    const ownedByOther =
      existingJobRow.owner_login &&
      existingJobRow.owner_login.toLowerCase() !== user.login.toLowerCase();
    if (ownedByOther) {
      return new Response(
        JSON.stringify({
          error: "Someone else already generated docs for this repo. One site per repo.",
        }),
        { status: 409, headers: { "Content-Type": "application/json" } },
      );
    }
    // Owner clicking again while a job is already running — hand back the
    // in-flight job instead of enqueuing a duplicate.
    const existing = await fetchJobStatus(env, existingJobRow.job_id);
    if (existing.status && existing.status !== "done" && existing.status !== "failed") {
      return new Response(
        JSON.stringify({ job_id: existingJobRow.job_id, status: existing.status, owner, repo }),
        { status: 202, headers: { "Content-Type": "application/json" } },
      );
    }
  }

  if (!isUnlimited(user.login)) {
    const savedCountRow = await env.DB.prepare("SELECT COUNT(*) AS n FROM projects WHERE user_login = ?")
      .bind(user.login)
      .first<{ n: number }>();
    if ((savedCountRow?.n ?? 0) >= MAX_SAVED_PROJECTS) {
      return new Response(
        JSON.stringify({ error: `you already have ${MAX_SAVED_PROJECTS} saved projects — delete one first` }),
        { status: 400 },
      );
    }
    const recentStarts = await countRecentStarts(env, user.login);
    if (recentStarts >= MAX_STARTS_PER_DAY) {
      return new Response(
        JSON.stringify({ error: `generation limit reached (${MAX_STARTS_PER_DAY} per 24h) — try again later` }),
        { status: 429 },
      );
    }
  }

  // Dispatch = enqueue. The Worker mints the job_id; a KEDA-scaled Container
  // Apps Job picks the message up and processes it in its own isolated
  // container. github_token rides in the message (private queue; deleted after
  // processing; same trust level as the prior HTTPS POST to the runner).
  const jobId = crypto.randomUUID().replace(/-/g, "").slice(0, 12);
  const enqueued = await enqueueJob(env, {
    job_id: jobId,
    owner,
    repo,
    github_token: user.token,
    visibility,
  });
  if (!enqueued) {
    return new Response(JSON.stringify({ error: "could not queue the generation job" }), { status: 502 });
  }
  const job = { job_id: jobId, status: "queued" };
  const now = Date.now();

  await env.DB.batch([
    env.DB.prepare("INSERT INTO rate_limit_starts (user_login, started_at) VALUES (?, ?)").bind(user.login, now),
    env.DB.prepare(
      // owner_login is set once (first generation wins) — never overwritten,
      // so ownership can't be stolen by a later ON CONFLICT update. visibility
      // does follow the owner's latest choice on their own re-generation.
      `INSERT INTO owner_repo_jobs (owner, repo, job_id, visibility, owner_login)
       VALUES (?, ?, ?, ?, ?)
       ON CONFLICT(owner, repo) DO UPDATE SET
         job_id = excluded.job_id, visibility = excluded.visibility`,
    ).bind(owner, repo, job.job_id, visibility, user.login),
    env.DB.prepare(
      `INSERT INTO projects (user_login, owner, repo, job_id, status, created_at, description, language, avatar_url, visibility)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(user_login, owner, repo) DO UPDATE SET
         job_id = excluded.job_id, status = excluded.status, created_at = excluded.created_at,
         description = excluded.description, language = excluded.language, avatar_url = excluded.avatar_url,
         visibility = excluded.visibility`,
    ).bind(
      user.login,
      owner,
      repo,
      job.job_id,
      job.status,
      now,
      body?.description ?? null,
      body?.language ?? null,
      body?.avatarUrl ?? null,
      visibility,
    ),
  ]);

  return new Response(JSON.stringify({ ...job, owner, repo }), {
    status: 202,
    headers: { "Content-Type": "application/json" },
  });
}

async function handleStatus(req: Request, env: Env, jobId: string): Promise<Response> {
  const user = await requireSession(req, env);
  if (!user) return new Response(JSON.stringify({ error: "not authenticated" }), { status: 401 });

  const result = await fetchJobStatus(env, jobId);

  if (result.status) {
    await env.DB.prepare("UPDATE projects SET status = ? WHERE job_id = ? AND user_login = ?")
      .bind(result.status, jobId, user.login)
      .run();
  }

  return new Response(result.text, { headers: { "Content-Type": "application/json" } });
}

async function handleProjects(req: Request, env: Env): Promise<Response> {
  const user = await requireSession(req, env);
  if (!user) return new Response(JSON.stringify({ error: "not authenticated" }), { status: 401 });

  const { results } = await env.DB.prepare(
    "SELECT owner, repo, job_id, status, created_at, description, language, avatar_url, visibility FROM projects WHERE user_login = ? ORDER BY created_at DESC",
  )
    .bind(user.login)
    .all<{
      owner: string;
      repo: string;
      job_id: string;
      status: string;
      created_at: number;
      description: string | null;
      language: string | null;
      avatar_url: string | null;
      visibility: string;
    }>();

  const projects: Project[] = [];
  for (const row of results) {
    let status = row.status;
    if (status !== "done" && status !== "failed") {
      const refreshed = await fetchJobStatus(env, row.job_id);
      if (refreshed.status) {
        status = refreshed.status;
        await env.DB.prepare("UPDATE projects SET status = ? WHERE job_id = ? AND user_login = ?")
          .bind(status, row.job_id, user.login)
          .run();
      }
    }
    projects.push({
      owner: row.owner,
      repo: row.repo,
      jobId: row.job_id,
      status,
      createdAt: row.created_at,
      description: row.description,
      language: row.language,
      avatarUrl: row.avatar_url,
      visibility: row.visibility,
    });
  }

  const unlimited = isUnlimited(user.login);
  return new Response(
    JSON.stringify({
      projects,
      quota: {
        unlimited,
        savedProjects: projects.length,
        maxSavedProjects: unlimited ? null : MAX_SAVED_PROJECTS,
        startsInWindow: await countRecentStarts(env, user.login),
        maxStartsPerDay: unlimited ? null : MAX_STARTS_PER_DAY,
      },
    }),
    { headers: { "Content-Type": "application/json" } },
  );
}

async function handleDeleteProject(req: Request, env: Env, owner: string, repo: string): Promise<Response> {
  const user = await requireSession(req, env);
  if (!user) return new Response(JSON.stringify({ error: "not authenticated" }), { status: 401 });

  const result = await env.DB.prepare(
    "DELETE FROM projects WHERE user_login = ? AND LOWER(owner) = LOWER(?) AND LOWER(repo) = LOWER(?)",
  )
    .bind(user.login, owner, repo)
    .run();
  return new Response(JSON.stringify({ deleted: (result.meta.changes ?? 0) > 0 }), {
    headers: { "Content-Type": "application/json" },
  });
}

async function handleSetVisibility(req: Request, env: Env, owner: string, repo: string): Promise<Response> {
  const user = await requireSession(req, env);
  if (!user) return new Response(JSON.stringify({ error: "not authenticated" }), { status: 401 });

  const body = (await req.json().catch(() => null)) as { visibility?: string } | null;
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
}

async function handleOwnerRepoSite(req: Request, env: Env, owner: string, repo: string, path: string): Promise<Response> {
  // Ownership/visibility gate FIRST — before serving any bytes. owner_repo_jobs
  // is the single serving authority per repo. If the site is private, only its
  // owner (matching session login) may read ANY of it, including /_next/*
  // assets, so a private site is fully sealed, not just its landing HTML.
  // R2 is not publicly exposed (only reachable via this Worker's binding), so
  // this check is the real trust boundary.
  const jobRow = await env.DB.prepare(
    "SELECT job_id, visibility, owner_login FROM owner_repo_jobs WHERE LOWER(owner) = LOWER(?) AND LOWER(repo) = LOWER(?)",
  )
    .bind(owner, repo)
    .first<{ job_id: string; visibility: string | null; owner_login: string | null }>();

  if (jobRow && jobRow.visibility === "private") {
    const viewer = await requireSession(req, env);
    const isOwner =
      viewer && jobRow.owner_login && viewer.login.toLowerCase() === jobRow.owner_login.toLowerCase();
    if (!isOwner) {
      return new Response(privateSitePage(owner, repo, !!viewer), {
        status: 403,
        headers: { "Content-Type": "text/html; charset=utf-8" },
      });
    }
  }

  // R2 is the durable source of truth for finished sites — check it first,
  // no runner round-trip needed. This is what makes a runner restart a
  // non-event for anything already generated.
  //
  // `path` comes straight from url.pathname, which stays percent-encoded
  // for characters like `[`/`]`/`(`/`)` — Next.js's own App Router uses
  // literal folder names like `(main)` and `[[...slug]]`, and its webpack
  // runtime requests those chunk URLs percent-encoded (e.g. `%5B%5B`). The
  // R2 keys uploaded by the runner use the real filesystem path (actual
  // brackets, not percent-encoded), so this must be decoded before use or
  // every such chunk silently 404s and the browser gets an HTML fallback
  // page where it expected JavaScript ("Unexpected token '<'").
  const decodedPath = decodeURIComponent(path);
  const prefix = `${owner.toLowerCase()}/${repo.toLowerCase()}/`;

  // next.config.mjs sets trailingSlash: true, so every generated page's real
  // file on disk is `{slug}/index.html`, not `{slug}/` — a raw key lookup on
  // the URL path alone always misses for page routes (only real static
  // assets like /_next/... have an actual file extension and need no
  // rewrite). Next's own client-side router resolves this internally, which
  // is why sidebar navigation worked while a reload or a plain in-content
  // <a> link — a real server request — did not.
  const candidates = [decodedPath];
  if (decodedPath === "" || decodedPath.endsWith("/")) {
    candidates.push(`${decodedPath}index.html`);
  } else if (!decodedPath.split("/").pop()?.includes(".")) {
    candidates.push(`${decodedPath}/index.html`);
  }

  for (const candidate of candidates) {
    const object = await env.SITES.get(prefix + candidate);
    if (object) {
      const headers = new Headers();
      headers.set("Content-Type", object.httpMetadata?.contentType || guessContentType(candidate));
      return new Response(object.body, { headers });
    }
  }

  // Reuse the ownership-gate lookup from the top — no need to hit D1 again.
  if (!jobRow) return new Response("Not found", { status: 404 });

  const result = await fetchJobStatus(env, jobRow.job_id);

  if (result.status && result.status !== "done" && result.status !== "failed") {
    // Still queued/running (or the browser hit this URL directly mid-generation)
    // — serve the app shell so its client-side JS resumes the progress view.
    return new Response(tryPageHtml(), { headers: { "Content-Type": "text/html; charset=utf-8" } });
  }

  // Status says done/failed but nothing's in R2 under this path — the built
  // files are gone (or never uploaded). Say so plainly instead of silently
  // falling back to the dashboard.
  return new Response(stalePageHtml(owner, repo), {
    status: 200,
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);

    // App-shell routes — the SPA reads location.pathname to pick a view.
    if (url.pathname === "/try" || url.pathname === "/" || url.pathname === "/account") {
      return new Response(tryPageHtml(), { headers: { "Content-Type": "text/html; charset=utf-8" } });
    }
    if (url.pathname === "/auth/github") return handleAuthStart(req, env);
    if (url.pathname === "/api/auth/callback/github") return handleAuthCallback(req, env);
    if (url.pathname === "/api/logout" && req.method === "POST") return handleLogout(req, env);
    if (url.pathname === "/api/me") return handleMe(req, env);
    if (url.pathname === "/api/repos") return handleRepos(req, env);
    if (url.pathname === "/api/generate" && req.method === "POST") return handleGenerate(req, env);
    if (url.pathname === "/api/projects" && req.method === "GET") return handleProjects(req, env);

    const statusMatch = url.pathname.match(/^\/api\/status\/([\w-]+)$/);
    if (statusMatch) return handleStatus(req, env, statusMatch[1]);

    // Visibility toggle — must be matched before the 2-segment DELETE route.
    const visMatch = url.pathname.match(/^\/api\/projects\/([\w.-]+)\/([\w.-]+)\/visibility$/);
    if (visMatch && req.method === "POST") return handleSetVisibility(req, env, visMatch[1], visMatch[2]);

    const deleteMatch = url.pathname.match(/^\/api\/projects\/([\w.-]+)\/([\w.-]+)$/);
    if (deleteMatch && req.method === "DELETE") return handleDeleteProject(req, env, deleteMatch[1], deleteMatch[2]);

    // Vanity serving route — must stay last so it never shadows /try, /api/*, /auth/*.
    const ownerRepoMatch = url.pathname.match(/^\/([\w.-]+)\/([\w.-]+)\/?(.*)$/);
    if (ownerRepoMatch) {
      return handleOwnerRepoSite(req, env, ownerRepoMatch[1], ownerRepoMatch[2], ownerRepoMatch[3] || "index.html");
    }

    return new Response("Not found", { status: 404 });
  },
};
