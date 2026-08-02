import type { APIRoute } from "astro";
import { tryPageHtml, readTheme } from "../../lib/hosted/page_html";

// The client-side script in tryPageHtml() decides what to actually render
// (sign-in prompt vs. the smart /projects-or-/generate default) based on
// /api/me — this endpoint just always serves the same app shell.
export const GET: APIRoute = ({ cookies }) => {
  return new Response(tryPageHtml(readTheme(cookies)), { headers: { "Content-Type": "text/html; charset=utf-8" } });
};
