import type { APIRoute } from "astro";
import { requireSession } from "../../../../lib/hosted/session";
import { fetchJobStatus } from "../../../../lib/hosted/queue";
import { tryPageHtml, privateSitePage, stalePageHtml, readTheme } from "../../../../lib/hosted/page_html";

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

// Ported from handleOwnerRepoSite in web/hosted/src/index.ts. In the old
// Worker this had to be routed last via manual regex ordering so it never
// shadowed /generate, /projects, /api/*, /auth/*; here it's simply a
// separate file under a distinct directory tree, so Astro's own static>dynamic
// route priority handles that automatically — no ordering to get wrong.
export const GET: APIRoute = async ({ params, locals, cookies }) => {
  const env = locals.runtime.env;
  const owner = params.owner!;
  const repo = params.repo!;
  const path = params.path ?? "index.html";

  // Ownership/visibility gate FIRST — before serving any bytes. owner_repo_jobs
  // is the single serving authority per repo. If the site is private, only its
  // owner (matching session login) may read ANY of it, including /_next/*
  // assets, so a private site is fully sealed, not just its landing HTML.
  // R2 is not publicly exposed (only reachable via this binding), so this
  // check is the real trust boundary.
  const jobRow = await env.DB.prepare(
    "SELECT job_id, visibility, owner_login FROM owner_repo_jobs WHERE LOWER(owner) = LOWER(?) AND LOWER(repo) = LOWER(?)",
  )
    .bind(owner, repo)
    .first<{ job_id: string; visibility: string | null; owner_login: string | null }>();

  if (jobRow && jobRow.visibility === "private") {
    const viewer = await requireSession(env, cookies);
    const isOwner =
      viewer && jobRow.owner_login && viewer.login.toLowerCase() === jobRow.owner_login.toLowerCase();
    if (!isOwner) {
      return new Response(privateSitePage(owner, repo, !!viewer, readTheme(cookies)), {
        status: 403,
        headers: { "Content-Type": "text/html; charset=utf-8" },
      });
    }
  }

  // R2 is the durable source of truth for finished sites — check it first,
  // no runner round-trip needed. This is what makes a runner restart a
  // non-event for anything already generated.
  //
  // `path` comes from the rest param, which stays percent-encoded for
  // characters like `[`/`]`/`(`/`)` — Next.js's own App Router uses literal
  // folder names like `(main)` and `[[...slug]]`, and its webpack runtime
  // requests those chunk URLs percent-encoded (e.g. `%5B%5B`). The R2 keys
  // uploaded by the runner use the real filesystem path (actual brackets,
  // not percent-encoded), so this must be decoded before use or every such
  // chunk silently 404s and the browser gets an HTML fallback page where it
  // expected JavaScript ("Unexpected token '<'").
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
      // Without these every asset on every page of a generated site
      // round-tripped R2 through the Worker on each navigation, which is most
      // of why the docs sites feel sluggish. Fingerprinted build assets are
      // safe to pin hard; HTML must stay revalidated so a regenerate is
      // visible immediately. The ETag lets even HTML come back as a 304.
      // Candidates are prefix-relative ("_next/static/..."), so the leading
      // slash must be optional or the Next.js chunk case never matches.
      const isFingerprinted = /(^|\/)(_next\/static|assets)\//.test(candidate)
        || /\.[0-9a-f]{8,}\.(js|css|woff2?|png|jpg|svg)$/i.test(candidate);
      headers.set(
        "Cache-Control",
        isFingerprinted ? "public, max-age=31536000, immutable" : "public, max-age=0, must-revalidate",
      );
      if (object.httpEtag) headers.set("ETag", object.httpEtag);
      return new Response(object.body as unknown as BodyInit, { headers });
    }
  }

  // Reuse the ownership-gate lookup from the top — no need to hit D1 again.
  if (!jobRow) return new Response("Not found", { status: 404 });

  const result = await fetchJobStatus(env, jobRow.job_id);

  // result.status is `null` (not "queued") whenever the job's status.json
  // doesn't exist in R2 yet — true for every job in the real window between
  // "enqueued" and "the runner container actually started and wrote its
  // first status". Treating that as falsy here used to fall through to
  // stalePageHtml (the "regenerate" error screen) for a job that was
  // legitimately just starting, not done/failed with nothing to show.
  if (result.status !== "done" && result.status !== "failed") {
    // Still queued/running (or the browser hit this URL directly mid-generation)
    // — serve the app shell so its client-side JS resumes the progress view.
    return new Response(tryPageHtml(readTheme(cookies)), { headers: { "Content-Type": "text/html; charset=utf-8" } });
  }

  // Status says done/failed but nothing's in R2 under this path — the built
  // files are gone (or never uploaded). Say so plainly instead of silently
  // falling back to the dashboard.
  return new Response(stalePageHtml(owner, repo, readTheme(cookies)), {
    status: 200,
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
};
