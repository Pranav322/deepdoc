// Gallery thumbnails.
//
// The public gallery used to preview each site with a live <iframe> scaled
// 400% -> 25%. Up to 60 of them on one page: slow, janky, blurry, and it read
// as a debug view rather than a product. These are real screenshots instead,
// captured once via Cloudflare's Browser Rendering REST API and cached in R2
// forever.
//
// Capture happens in the Worker rather than in the Python generation pipeline
// because hosted-runner/ has uncommitted work by another developer — see
// AGENTS.md. If that lands and you'd rather capture at generation time, this
// endpoint can become a pure R2 read.

// Bindings this feature needs. Declared here rather than folded into CloudEnv
// (src/env.d.ts and lib/hosted/queue.ts both declare it, and both have
// uncommitted work on another branch). Merge them once that lands.
export interface ThumbEnv {
  DB: D1Database;
  SITES: R2Bucket;
  CF_ACCOUNT_ID?: string;
  CF_BROWSER_TOKEN?: string;
}

export const THUMB_W = 1280;
export const THUMB_H = 800;

export type ThumbTheme = "dark" | "light";

export function parseTheme(v: string | null): ThumbTheme {
  return v === "light" ? "light" : "dark";
}

function escapeXml(v: string): string {
  return String(v ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

/**
 * Shown while a real screenshot doesn't exist yet (or can't be made): a quiet
 * outline of a docs page titled with the repo's name, in the gallery's own
 * neutrals. It matches the wireframe the gallery card draws under its image
 * while loading, so a cold card reads as a page still arriving rather than a
 * different kind of tile. (It used to be a saturated per-owner gradient with
 * a giant initial, which was the loudest thing in a half-warm gallery.)
 * Short max-age so cards upgrade to the real thing on a later visit.
 *
 * owner/repo come straight from the request URL, and this response is an SVG
 * *document* on the app's own origin — opened directly, it renders and runs
 * like a page. Both values are escaped, and the CSP below forbids script
 * outright, so a crafted /api/thumb/... link can't execute anything.
 */
export function fallbackSvg(owner: string, repo: string, theme: ThumbTheme = "dark"): Response {
  const light = theme === "light";
  const bg = light ? "#FBFAF7" : "#121211";
  const ink = light ? "#111110" : "#F0EFEA";
  const name = escapeXml(`${owner}/${repo}`);
  // Long names would run off the content column; the title is decoration.
  const title = escapeXml(repo.length > 28 ? `${repo.slice(0, 27)}…` : repo);
  const bar = (x: number, y: number, w: number, h: number, o: number) =>
    `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${h / 2}" fill="${ink}" opacity="${o}"/>`;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${THUMB_W}" height="${THUMB_H}" viewBox="0 0 ${THUMB_W} ${THUMB_H}" role="img" aria-label="${name}">
  <rect width="${THUMB_W}" height="${THUMB_H}" fill="${bg}"/>
  <rect width="${THUMB_W}" height="64" fill="${ink}" opacity="0.035"/>
  <rect y="64" width="${THUMB_W}" height="1" fill="${ink}" opacity="0.07"/>
  ${bar(40, 24, 104, 16, 0.14)}
  ${bar(920, 20, 300, 24, 0.07)}
  <rect y="65" width="256" height="${THUMB_H - 65}" fill="${ink}" opacity="0.02"/>
  <rect x="256" y="65" width="1" height="${THUMB_H - 65}" fill="${ink}" opacity="0.07"/>
  ${bar(40, 108, 136, 12, 0.13)}${bar(40, 140, 168, 12, 0.07)}${bar(40, 172, 120, 12, 0.07)}${bar(40, 204, 152, 12, 0.07)}
  ${bar(40, 264, 112, 12, 0.13)}${bar(40, 296, 160, 12, 0.07)}${bar(40, 328, 132, 12, 0.07)}
  <text x="336" y="160" font-family="DM Sans, ui-sans-serif, system-ui, -apple-system, sans-serif" font-size="46"
        font-weight="600" letter-spacing="-1.4" fill="${ink}" opacity="0.62">${title}</text>
  ${bar(336, 204, 600, 14, 0.08)}${bar(336, 234, 552, 14, 0.08)}${bar(336, 264, 384, 14, 0.08)}
  <rect x="336" y="312" width="600" height="160" rx="14" fill="${ink}" opacity="0.045"/>
  ${bar(368, 348, 280, 12, 0.1)}${bar(368, 380, 392, 12, 0.1)}${bar(368, 412, 216, 12, 0.1)}
  ${bar(336, 516, 584, 14, 0.08)}${bar(336, 546, 480, 14, 0.08)}
  ${bar(1024, 120, 160, 12, 0.1)}${bar(1024, 152, 128, 10, 0.06)}${bar(1024, 180, 144, 10, 0.06)}${bar(1024, 208, 112, 10, 0.06)}
</svg>`;
  return new Response(svg, {
    headers: {
      "Content-Type": "image/svg+xml; charset=utf-8",
      "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
      "X-Content-Type-Options": "nosniff",
      // Short, so a cold card picks up its real screenshot soon after one gets
      // made, and so retries naturally stagger instead of stampeding.
      "Cache-Control": "public, max-age=120",
    },
  });
}

export function thumbKey(owner: string, repo: string, createdAt: number, theme: ThumbTheme): string {
  // Version in the key: a regenerate writes a new object, the old one is
  // simply orphaned, and the served URL can be immutable with no invalidation.
  // Theme is in the key too, so light and dark are independent objects that
  // each warm on demand rather than one overwriting the other.
  return `thumbs/${owner.toLowerCase()}/${repo.toLowerCase()}/${createdAt}-${theme}.jpg`;
}

/**
 * Browser Rendering REST is rate limited (6 req/min on the free plan, 600 on
 * paid). A cold gallery would blow straight through that, so cap how many real
 * captures we start per minute and let everything else take the fallback.
 * Stored in R2 because there's no KV binding here. Not transactional — a lost
 * update just means one extra attempt, which at worst earns a 429 we already
 * handle.
 */
async function tryClaimBudget(env: ThumbEnv, maxPerMinute: number): Promise<boolean> {
  const key = "thumbs/_budget.json";
  const minute = Math.floor(Date.now() / 60000);
  let count = 0;
  try {
    const obj = await env.SITES.get(key);
    if (obj) {
      const cur = (await obj.json()) as { minute?: number; count?: number };
      if (cur?.minute === minute) count = cur.count ?? 0;
    }
  } catch {
    // Unreadable budget: fail closed, take the fallback.
    return false;
  }
  if (count >= maxPerMinute) return false;
  try {
    await env.SITES.put(key, JSON.stringify({ minute, count: count + 1 }), {
      httpMetadata: { contentType: "application/json" },
    });
  } catch {
    return false;
  }
  return true;
}

/**
 * Stops several concurrent requests for the same cold card all triggering
 * their own screenshot. Benign race: worst case two captures of one page.
 */
async function tryClaimLock(env: ThumbEnv, owner: string, repo: string, theme: ThumbTheme): Promise<boolean> {
  const key = `thumbs/_locks/${owner.toLowerCase()}/${repo.toLowerCase()}-${theme}`;
  try {
    const existing = await env.SITES.get(key);
    if (existing) {
      const ts = Number(await existing.text());
      if (Number.isFinite(ts) && Date.now() - ts < 120_000) return false;
    }
    await env.SITES.put(key, String(Date.now()));
    return true;
  } catch {
    return false;
  }
}

async function releaseLock(env: ThumbEnv, owner: string, repo: string, theme: ThumbTheme): Promise<void> {
  try {
    await env.SITES.delete(`thumbs/_locks/${owner.toLowerCase()}/${repo.toLowerCase()}-${theme}`);
  } catch {
    /* best effort — the 120s staleness window covers a leaked lock */
  }
}

// Generated docs sites use next-themes: it reads localStorage, falls back to
// prefers-color-scheme, and applies the result as a class on <html>. A headless
// browser reports no preference, so every capture came out light — which looked
// wrong sitting in a dark gallery.
//
// Browser Rendering has no colour-scheme emulation, but it does support
// addScriptTag. Setting the class directly is enough, because the site's dark
// styling is plain CSS keyed off that class; next-themes has already mounted by
// then and won't overwrite it. localStorage is set too for any component that
// re-reads it. Verified against a real site: mean luma 236 -> 27.
const FORCE_DARK_JS =
  'try{localStorage.setItem("theme","dark")}catch(e){};' +
  'document.documentElement.classList.remove("light");' +
  'document.documentElement.classList.add("dark");' +
  'document.documentElement.style.colorScheme="dark";';

/** Captures the public site. Returns null on any failure; callers fall back. */
export async function captureScreenshot(
  env: ThumbEnv,
  siteUrl: string,
  theme: ThumbTheme = "dark",
): Promise<ArrayBuffer | null> {
  if (!env.CF_ACCOUNT_ID || !env.CF_BROWSER_TOKEN) return null;
  try {
    const res = await fetch(
      `https://api.cloudflare.com/client/v4/accounts/${env.CF_ACCOUNT_ID}/browser-rendering/screenshot`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.CF_BROWSER_TOKEN}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          url: siteUrl,
          viewport: { width: THUMB_W, height: THUMB_H },
          // Above the fold only — a full-page shot of a docs site is mostly
          // whitespace at card size.
          screenshotOptions: { fullPage: false, type: "jpeg", quality: 72 },
          gotoOptions: { waitUntil: "networkidle0", timeout: 20000 },
          // Light needs no forcing: it's what a headless browser renders by
          // default, and injecting nothing keeps that path identical to before.
          ...(theme === "dark" ? { addScriptTag: [{ content: FORCE_DARK_JS }] } : {}),
        }),
      },
    );
    // Includes 429 (rate limited). Fall back rather than retry inline; a
    // Worker can't cheaply wait out a Retry-After.
    if (!res.ok) return null;
    const buf = await res.arrayBuffer();
    return buf.byteLength > 0 ? buf : null;
  } catch {
    return null;
  }
}

export { tryClaimBudget, tryClaimLock, releaseLock };
