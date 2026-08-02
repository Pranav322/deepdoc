import type { APIRoute } from "astro";
import {
  type ThumbEnv,
  captureScreenshot,
  fallbackSvg,
  releaseLock,
  parseTheme,
  thumbKey,
  tryClaimBudget,
  tryClaimLock,
} from "../../../../../lib/hosted/thumb";

// GET /api/thumb/{owner}/{repo}  ->  gallery screenshot (jpeg), or an SVG
// placeholder while one doesn't exist.
//
// Public and unauthenticated on purpose: it only ever serves images of sites
// that are already public. Never screenshots a private site (the browser would
// just capture the 403 page) and never one mid-generation (you'd cache a
// picture of the progress screen under a long-lived URL).

// At most this many real captures started per minute across the whole account.
// Browser Rendering REST allows 6/min on the free plan; leave headroom.
const MAX_CAPTURES_PER_MINUTE = 4;

export const GET: APIRoute = async ({ params, locals, request, url }) => {
  const env = locals.runtime.env as unknown as ThumbEnv;
  // Theme lives in the URL rather than being read from the cookie, so each
  // variant keeps its own immutable, independently cacheable address — a
  // cookie-varying image URL would defeat both the CDN and the immutable
  // Cache-Control below.
  const theme = parseTheme(url.searchParams.get("t"));
  const owner = params.owner ?? "";
  const repo = (params.repo ?? "").replace(/\.jpg$/i, "");
  if (!owner || !repo) return fallbackSvg(owner || "?", repo || "?", theme);

  // Public + finished, from the same authority the gallery itself uses:
  // visibility is canonical on owner_repo_jobs, status on the owner's row.
  const row = await env.DB.prepare(
    `SELECT p.created_at AS createdAt, p.status AS status
       FROM owner_repo_jobs o
       JOIN projects p
         ON LOWER(p.owner) = LOWER(o.owner) AND LOWER(p.repo) = LOWER(o.repo)
        AND p.user_login = o.owner_login
      WHERE LOWER(o.owner) = LOWER(?) AND LOWER(o.repo) = LOWER(?)
        AND o.visibility = 'public'`,
  )
    .bind(owner, repo)
    .first<{ createdAt: number; status: string }>();

  if (!row || row.status !== "done") return fallbackSvg(owner, repo, theme);

  const key = thumbKey(owner, repo, row.createdAt, theme);

  // 1. Cached screenshot.
  const cached = await env.SITES.get(key);
  if (cached) {
    const etag = cached.httpEtag;
    // The key contains the generation timestamp, so a hit is immutable.
    if (etag && request.headers.get("If-None-Match") === etag) {
      return new Response(null, { status: 304, headers: { ETag: etag } });
    }
    const headers = new Headers({
      "Content-Type": "image/jpeg",
      "Cache-Control": "public, max-age=31536000, immutable",
    });
    if (etag) headers.set("ETag", etag);
    return new Response(cached.body as unknown as BodyInit, { headers });
  }

  // 2. Cold. Only one request per repo should attempt a capture, and only a
  //    few per minute overall — everyone else gets the placeholder.
  if (!(await tryClaimLock(env, owner, repo, theme))) return fallbackSvg(owner, repo, theme);
  try {
    if (!(await tryClaimBudget(env, MAX_CAPTURES_PER_MINUTE))) {
      return fallbackSvg(owner, repo, theme);
    }

    const siteUrl = `https://cloud.deepdoc.tech/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/`;
    const shot = await captureScreenshot(env, siteUrl, theme);
    if (!shot) return fallbackSvg(owner, repo, theme);

    // Re-check state right before storing: a job that flipped away from 'done'
    // mid-request must not get a stale image pinned under an immutable URL.
    const still = await env.DB.prepare(
      `SELECT status FROM projects
        WHERE LOWER(owner) = LOWER(?) AND LOWER(repo) = LOWER(?) AND created_at = ?`,
    )
      .bind(owner, repo, row.createdAt)
      .first<{ status: string }>();
    if (!still || still.status !== "done") return fallbackSvg(owner, repo, theme);

    await env.SITES.put(key, shot, { httpMetadata: { contentType: "image/jpeg" } });
    return new Response(shot, {
      headers: {
        "Content-Type": "image/jpeg",
        "Cache-Control": "public, max-age=31536000, immutable",
      },
    });
  } finally {
    await releaseLock(env, owner, repo, theme);
  }
};
