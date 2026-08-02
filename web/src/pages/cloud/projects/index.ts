import type { APIRoute } from "astro";
import { tryPageHtml, readTheme } from "../../../lib/hosted/page_html";

export const GET: APIRoute = ({ cookies }) => {
  return new Response(tryPageHtml(readTheme(cookies)), { headers: { "Content-Type": "text/html; charset=utf-8" } });
};
