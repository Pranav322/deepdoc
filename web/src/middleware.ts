import { defineMiddleware } from "astro:middleware";

// The hosted app (cloud.deepdoc.tech) and the marketing site (deepdoc.tech)
// are one Astro deployment. The hosted app's pages/endpoints physically live
// under src/pages/cloud/ so they can't collide with marketing routes, but
// the external URL a browser or GitHub's OAuth callback sees stays
// unprefixed (/, /generate, /projects, /api/auth/callback/github, ...) —
// this rewrite is what makes that transparent.
//
// Local dev: the pages under src/pages/cloud/ use root-relative fetch()/nav
// calls (e.g. fetch('/api/me')), matching the clean external URL — so they
// only resolve correctly when reached through this same hostname rewrite,
// not by visiting /cloud/... directly (that would make a page's own
// relative '/api/me' hit the marketing namespace instead of its /cloud
// sibling). To test locally, add `127.0.0.1 cloud.localhost` to /etc/hosts
// and visit http://cloud.localhost:4321 — same rewrite path as production.
const CLOUD_HOSTS = new Set(["cloud.deepdoc.tech", "cloud.localhost"]);

export const onRequest = defineMiddleware(async (context, next) => {
  const { url } = context;
  if (CLOUD_HOSTS.has(url.hostname) && !url.pathname.startsWith("/cloud")) {
    return context.rewrite(new URL("/cloud" + url.pathname + url.search, url));
  }
  return next();
});
