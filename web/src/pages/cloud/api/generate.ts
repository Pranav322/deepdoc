import type { APIRoute } from "astro";
import { requireSession, isUnlimited, countRecentStarts, parseGithubRepoUrl, MAX_SAVED_PROJECTS, MAX_STARTS_PER_DAY } from "../../../lib/hosted/session";
import { enqueueJob, fetchJobStatus } from "../../../lib/hosted/queue";

interface RepoMeta {
  description: string | null;
  language: string | null;
  stars: number | null;
  avatarUrl: string | null;
}

/**
 * Repo metadata straight from GitHub, for the card the project will become.
 *
 * This used to be whatever the browser happened to send in the POST body.
 * The repo-picker path sent real values (it had them from /api/repos), but
 * the paste-a-URL path sent none — so most projects were stored with a null
 * description, language and star count, and the public gallery rendered a
 * wall of bare name-only cards of uneven height. Asking GitHub here covers
 * every entry path at once, including regenerate.
 *
 * Returns `"missing"` only for an explicit 404, which is the one answer worth
 * refusing on: it means the repo does not exist or this token cannot see it,
 * and today that is discovered minutes later inside the container job. Any
 * other failure (rate limit, GitHub outage, network) returns null so a
 * transient problem degrades to a sparse card rather than blocking a build.
 */
async function fetchRepoMeta(
  owner: string,
  repo: string,
  token: string,
): Promise<RepoMeta | null | "missing"> {
  let res: Response;
  try {
    res = await fetch(`https://api.github.com/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`, {
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        // GitHub rejects API requests without one.
        "User-Agent": "deepdoc-hosted",
      },
    });
  } catch {
    return null;
  }
  if (res.status === 404) return "missing";
  if (!res.ok) return null;
  const json = (await res.json().catch(() => null)) as {
    description?: string | null;
    language?: string | null;
    stargazers_count?: number | null;
    owner?: { avatar_url?: string | null } | null;
  } | null;
  if (!json) return null;
  return {
    description: json.description ?? null,
    language: json.language ?? null,
    stars: json.stargazers_count ?? null,
    avatarUrl: json.owner?.avatar_url ?? null,
  };
}

// Ported from handleGenerate in web/hosted/src/index.ts.
export const POST: APIRoute = async ({ request, locals, cookies }) => {
  const env = locals.runtime.env;
  const user = await requireSession(env, cookies);
  if (!user) return new Response(JSON.stringify({ error: "not authenticated" }), { status: 401 });

  const body = (await request.json().catch(() => null)) as
    | {
        owner?: string;
        repo?: string;
        repo_url?: string;
        description?: string | null;
        language?: string | null;
        avatarUrl?: string | null;
        stars?: number | null;
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
    // `status === null` means jobs/{id}/status.json does not exist yet — the
    // window between enqueue and the container writing its first status. That
    // is in-flight, not absent. Treating null as falsy here let a second
    // request through during exactly that window, enqueuing a duplicate job:
    // two Container Apps executions for one repo, both writing the same R2
    // prefix, with D1 keeping only the second job_id so the first billed on
    // untracked. Same failure class as the openclaw/openclaw incident, and
    // the same null-is-in-flight lesson already learned in
    // [owner]/[repo]/[...path].ts.
    const inFlight = existing.status === null
      || (existing.status !== "done" && existing.status !== "failed");
    if (inFlight) {
      const existingProject = await env.DB.prepare(
        "SELECT created_at FROM projects WHERE user_login = ? AND LOWER(owner) = LOWER(?) AND LOWER(repo) = LOWER(?)",
      )
        .bind(user.login, owner, repo)
        .first<{ created_at: number }>();
      return new Response(
        JSON.stringify({
          job_id: existingJobRow.job_id,
          // Normalise the pre-cold-start null to the same "queued" the first
          // POST returns, so the client never has to reason about null.
          status: existing.status ?? "queued",
          owner,
          repo,
          createdAt: existingProject?.created_at ?? null,
        }),
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

  // Last gate before dispatch, so a repo we are going to refuse anyway
  // (owned by someone else, over quota) never costs a GitHub call, and
  // nothing has been written yet when we refuse here.
  const meta = await fetchRepoMeta(owner, repo, user.token);
  if (meta === "missing") {
    return new Response(
      JSON.stringify({ error: `${owner}/${repo} could not be found on GitHub, or your account can't see it` }),
      { status: 400, headers: { "Content-Type": "application/json" } },
    );
  }
  // GitHub wins where it answered; the body's values remain the fallback for
  // a transient failure, since the repo picker does send real ones.
  const description = meta?.description ?? body?.description ?? null;
  const language = meta?.language ?? body?.language ?? null;
  const avatarUrl = meta?.avatarUrl ?? body?.avatarUrl ?? null;
  const stars = meta?.stars ?? body?.stars ?? null;

  // Dispatch = enqueue. This endpoint mints the job_id; a KEDA-scaled
  // Container Apps Job picks the message up and processes it in its own
  // isolated container. github_token rides in the message (private queue;
  // deleted after processing).
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
      `INSERT INTO projects (user_login, owner, repo, job_id, status, created_at, description, language, avatar_url, visibility, stars)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(user_login, owner, repo) DO UPDATE SET
         job_id = excluded.job_id, status = excluded.status, created_at = excluded.created_at,
         description = excluded.description, language = excluded.language, avatar_url = excluded.avatar_url,
         visibility = excluded.visibility, stars = excluded.stars`,
    ).bind(
      user.login,
      owner,
      repo,
      job.job_id,
      job.status,
      now,
      description,
      language,
      avatarUrl,
      visibility,
      stars,
    ),
  ]);

  return new Response(JSON.stringify({ ...job, owner, repo, createdAt: now }), {
    status: 202,
    headers: { "Content-Type": "application/json" },
  });
};
