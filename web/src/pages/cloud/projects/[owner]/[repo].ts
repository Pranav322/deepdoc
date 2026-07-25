import type { APIRoute } from "astro";
import { tryPageHtml } from "../../../../lib/hosted/page_html";

export const GET: APIRoute = () => {
  return new Response(tryPageHtml(), { headers: { "Content-Type": "text/html; charset=utf-8" } });
};
