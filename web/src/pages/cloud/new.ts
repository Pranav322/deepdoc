import type { APIRoute } from "astro";

// Stale bookmark to the old "new site" page — redirect rather than 404.
export const GET: APIRoute = () => new Response(null, { status: 302, headers: { Location: "/" } });
