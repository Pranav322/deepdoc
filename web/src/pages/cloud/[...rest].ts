import type { APIRoute } from "astro";
import { genericNotFoundPage, readTheme } from "../../lib/hosted/page_html";

// Catch-all for cloud.deepdoc.tech paths that match no other route. Astro ranks
// this below every literal and named route, so it only ever sees true misses
// (a mistyped URL, an old bookmark) and serves a styled page instead of Astro's
// bare default 404.
export const GET: APIRoute = ({ cookies }) =>
  new Response(genericNotFoundPage(readTheme(cookies)), {
    status: 404,
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
