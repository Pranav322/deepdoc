/**
 * Cloudflare Pages Function — catches /:owner/:repo and /:owner/:repo/*
 * Proxies to the DO backend (Express server).
 *
 * Set BACKEND_URL in Cloudflare Pages → Settings → Environment Variables.
 * Example: BACKEND_URL=http://143.110.247.23
 */

// Top-level paths owned by the Astro marketing site — never proxy these.
const RESERVED = new Set([
  'docs', 'changelog', 'blog', 'pricing', 'about',
  'favicon.ico', 'robots.txt', 'sitemap.xml',
  '_astro', '_headers', '_redirects',
]);

export async function onRequest(context) {
  const { env, request, params } = context;
  const { owner, repo } = params;

  // Don't intercept marketing pages
  if (RESERVED.has(owner)) {
    return context.next();
  }

  // Validate characters — same rule as the server
  if (!/^[a-zA-Z0-9_.-]+$/.test(owner) || !/^[a-zA-Z0-9_.-]+$/.test(repo)) {
    return new Response('Invalid owner or repo name.', { status: 400 });
  }

  const backendUrl = env.BACKEND_URL;
  if (!backendUrl) {
    return new Response('BACKEND_URL not configured.', { status: 503 });
  }

  // Build backend URL — params.path is an array of segments (or undefined)
  const pathSuffix =
    Array.isArray(params.path) && params.path.length > 0
      ? '/' + params.path.join('/')
      : '';

  const url = new URL(request.url);
  const target = `${backendUrl}/${owner}/${repo}${pathSuffix}${url.search}`;

  const backendReq = new Request(target, {
    method: request.method,
    headers: request.headers,
    body: ['GET', 'HEAD'].includes(request.method) ? undefined : request.body,
  });

  const response = await fetch(backendReq);

  // Pass through as-is — body is a ReadableStream so SSE streams correctly.
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
  });
}
