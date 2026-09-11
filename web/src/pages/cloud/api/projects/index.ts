import type { APIRoute } from "astro";
import { requireSession, isUnlimited, countRecentStarts, MAX_SAVED_PROJECTS, MAX_STARTS_PER_DAY } from "../../../../lib/hosted/session";
import { fetchJobStatus } from "../../../../lib/hosted/queue";

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
  stars?: number | null;
}

// Ported from handleProjects in web/hosted/src/index.ts.
export const GET: APIRoute = async ({ locals, cookies }) => {
  const env = locals.runtime.env;
  const user = await requireSession(env, cookies);
  if (!user) return new Response(JSON.stringify({ error: "not authenticated" }), { status: 401 });

  // owner_repo_jobs.visibility is canonical (it's what the public gallery and
  // the page-serving gate actually check); projects.visibility is a copy that
  // can drift out of sync if it's ever written without the paired update
  // (e.g. a direct DB edit). Read the canonical value here so "your projects"
  // never shows a visibility that doesn't match what's actually being served.
  const { results } = await env.DB.prepare(
    `SELECT p.owner, p.repo, p.job_id, p.status, p.created_at, p.description, p.language,
            p.avatar_url, COALESCE(o.visibility, p.visibility) AS visibility, p.stars
     FROM projects p
     LEFT JOIN owner_repo_jobs o
       ON LOWER(o.owner) = LOWER(p.owner) AND LOWER(o.repo) = LOWER(p.repo) AND o.owner_login = p.user_login
     WHERE p.user_login = ? ORDER BY p.created_at DESC`,
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
      stars: number | null;
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
      stars: row.stars,
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
};
