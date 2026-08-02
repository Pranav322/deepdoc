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

/** Deterministic hue per owner — the same one the old iframe fallback used. */
export function fallbackHue(owner: string): number {
  let hash = 0;
  for (let i = 0; i < owner.length; i++) hash = (hash * 31 + owner.charCodeAt(i)) | 0;
  return Math.abs(hash) % 360;
}

/**
 * Shown while a real screenshot doesn't exist yet (or can't be made). Content
 * rather than a broken image, so a half-warm gallery reads as intentional.
 * Short max-age so cards upgrade to the real thing on a later visit.
 */
export function fallbackSvg(owner: string, repo: string): Response {
  const hue = fallbackHue(owner);
  const initial = (owner[0] || "?").toUpperCase()
    .replace(/[<>&"']/g, "");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${THUMB_W}" height="${THUMB_H}" viewBox="0 0 ${THUMB_W} ${THUMB_H}" role="img" aria-label="${owner}/${repo}">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="hsl(${hue} 42% 26%)"/>
      <stop offset="100%" stop-color="hsl(${(hue + 40) % 360} 38% 15%)"/>
    </linearGradient>
  </defs>
  <rect width="${THUMB_W}" height="${THUMB_H}" fill="url(#g)"/>
  <text x="50%" y="50%" text-anchor="middle" dominant-baseline="central"
        font-family="DM Sans, ui-sans-serif, system-ui, sans-serif"
        font-size="220" font-weight="700" fill="rgba(255,255,255,0.86)">${initial}</text>
</svg>`;
  return new Response(svg, {
    headers: {
      "Content-Type": "image/svg+xml; charset=utf-8",
      // Short, so a cold card picks up its real screenshot soon after one gets
      // made, and so retries naturally stagger instead of stampeding.
      "Cache-Control": "public, max-age=120",
    },
  });
}

export function thumbKey(owner: string, repo: string, createdAt: number): string {
  // Version in the key: a regenerate writes a new object, the old one is
  // simply orphaned, and the served URL can be immutable with no invalidation.
  return `thumbs/${owner.toLowerCase()}/${repo.toLowerCase()}/${createdAt}.jpg`;
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
async function tryClaimLock(env: ThumbEnv, owner: string, repo: string): Promise<boolean> {
  const key = `thumbs/_locks/${owner.toLowerCase()}/${repo.toLowerCase()}`;
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

async function releaseLock(env: ThumbEnv, owner: string, repo: string): Promise<void> {
  try {
    await env.SITES.delete(`thumbs/_locks/${owner.toLowerCase()}/${repo.toLowerCase()}`);
  } catch {
    /* best effort — the 120s staleness window covers a leaked lock */
  }
}

/** Captures the public site. Returns null on any failure; callers fall back. */
export async function captureScreenshot(
  env: ThumbEnv,
  siteUrl: string,
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
