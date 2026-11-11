// Ported verbatim from web/hosted/src/try_page.ts as part of the Astro
// unification — server-rendered HTML+vanilla-JS strings, called from thin
// Astro pages under src/pages/cloud/. All internal fetch()/nav() calls use
// root-relative paths (/api/me, /generate, ...) matching the clean external
// URL that src/middleware.ts's hostname rewrite preserves — nothing here
// needed to change to work through that rewrite.
//
// Visual identity is shared with deepdoc.tech and /docs: the palette is
// src/styles/tokens.css, inlined below as TOKENS_CSS, so there is no second
// copy to drift. Everything after the palette (type ramp, radii, the button
// shape, card depth) is this app's own vocabulary. The app is an HTML string
// built in a Worker, so it cannot import an Astro component or stylesheet.
//
// IA: /generate is the only post-login home (repo picker + paste + confirm).
// All project management (list, visit, visibility, delete) lives under
// /projects and /projects/:owner/:repo — never inline on /generate, never in
// the profile dropdown (which is identity + nav links only).
import { MAX_SAVED_PROJECTS, MAX_STARTS_PER_DAY } from "./session";
// The one palette, shared with deepdoc.tech and /docs. Vite inlines it as a string.
import TOKENS_CSS from "../../styles/tokens.css?raw";

export type Theme = "dark" | "light";

/**
 * Styling for the standalone one-off pages (private site, 404, no docs yet,
 * stale site, failed build). One shell for all five, so every dead end on
 * cloud.deepdoc.tech still looks like the app: the brand bar, the same
 * ambient light, and one raised card with an icon that says what happened.
 * The palette here is a subset of the app's and is checked against
 * marketing by test-hosted-tokens.mjs like the main block.
 */
const MINI_PAGE_CSS = `
  ${TOKENS_CSS}
  :root { --shadow: var(--shadow-lift); }
  * { box-sizing: border-box; }
  html, body { margin: 0; }
  body { position: relative; min-height: 100vh; background: var(--surface); color: var(--ink);
    font-family: var(--font-sans); font-feature-settings: "ss01"; -webkit-font-smoothing: antialiased;
    display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 96px 24px 72px; }
  body::before { content: ''; position: absolute; left: 0; right: 0; top: 0; height: 520px; pointer-events: none;
    background-image: linear-gradient(var(--grid) 1px, transparent 1px), linear-gradient(90deg, var(--grid) 1px, transparent 1px);
    background-size: 14px 14px;
    -webkit-mask-image: radial-gradient(ellipse 62% 78% at 50% 0%, black 8%, transparent 70%);
    mask-image: radial-gradient(ellipse 62% 78% at 50% 0%, black 8%, transparent 70%); }
  .mini-bar { position: absolute; top: 0; left: 0; right: 0; z-index: 1; max-width: 1152px; height: 52px; margin: 0 auto;
    padding: 0 24px; display: flex; align-items: center; }
  .brand { display: flex; align-items: center; font-weight: 600; font-size: 1.2rem; letter-spacing: -0.015em;
    color: var(--ink); text-decoration: none; border-radius: 6px; }
  .brand:hover { opacity: 0.82; }
  .brand:focus-visible { outline: 2px solid var(--accent); outline-offset: 4px; }
  .dd-mark { display: block; flex-shrink: 0; width: 1.16em; height: 1.16em; margin-left: -0.33em; margin-right: 0.04em; transform: translateY(-0.05em); }
  .dd-mark .dd-front { fill: var(--accent); }
  .dd-mark .dd-echo { fill: none; stroke: var(--accent); stroke-width: 2; stroke-linecap: round; }
  .dd-mark .dd-echo-1 { opacity: 0.4; } .dd-mark .dd-echo-2 { opacity: 0.18; }
  .card { position: relative; z-index: 1; width: 100%; max-width: 440px; border: 1px solid var(--line-strong); border-radius: 20px;
    background: var(--card); padding: 30px 30px 28px; box-shadow: inset 0 1px 0 var(--edge), var(--shadow); }
  .mini-icon { width: 44px; height: 44px; border-radius: 12px; display: flex; align-items: center; justify-content: center;
    background: var(--surface-high); border: 1px solid var(--line-strong); color: var(--ink-muted); margin-bottom: 20px;
    box-shadow: inset 0 1px 0 var(--edge); }
  .mini-icon svg { width: 20px; height: 20px; }
  .mini-icon.is-danger { color: var(--danger); background: var(--danger-dim); }
  h1 { font-size: 22px; font-weight: 600; letter-spacing: -0.026em; line-height: 1.2; margin: 0 0 10px; }
  p { font-size: 14px; line-height: 1.65; color: var(--ink-muted); margin: 0 0 24px; max-width: 46ch; }
  code { font-family: var(--font-mono); font-size: 12.5px; color: var(--ink); padding: 1px 6px; border-radius: 6px;
    background: var(--surface-high); border: 1px solid var(--line); word-break: break-all; }
  .actions { display: flex; gap: 8px; flex-wrap: wrap; }
  .btn { display: inline-flex; align-items: center; justify-content: center; gap: 7px; height: 38px;
    border-radius: 8px; border: 1px solid transparent; cursor: pointer; padding: 0 16px; background: var(--solid);
    color: var(--solid-ink); box-shadow: var(--btn-shadow); font-family: var(--font-sans); font-size: 13.5px; font-weight: 600;
    letter-spacing: -0.008em; text-decoration: none; transition: background 0.15s cubic-bezier(0.22, 1, 0.36, 1); }
  .btn:hover { background: var(--solid-hover); }
  .btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .btn svg { width: 16px; height: 16px; }
  .btn.secondary { background: var(--card); color: var(--ink); border-color: var(--line-strong); box-shadow: inset 0 1px 0 var(--edge); }
  .btn.secondary:hover { background: var(--surface-high); }
  .err { white-space: pre-wrap; word-break: break-word; font-family: var(--font-mono); font-size: 12px;
    line-height: 1.55; margin: 0 0 24px; padding: 12px 14px; border-radius: 10px; color: var(--ink);
    background: var(--danger-dim); border: 1px solid color-mix(in oklab, var(--danger) 26%, transparent);
    max-height: 240px; overflow: auto; }
`;

// The brand mark, server-side. The client script carries its own copy in
// brandMarkHtml(); both mirror web/src/components/Logo.astro.
const BRAND_MARK_SVG = `<svg class="dd-mark" viewBox="0 0 48 48" fill="none" aria-hidden="true">
  <path class="dd-echo dd-echo-2" d="M14 9 H24 A15 15 0 0 1 24 39 H14" transform="translate(6 6)"></path>
  <path class="dd-echo dd-echo-1" d="M14 9 H24 A15 15 0 0 1 24 39 H14" transform="translate(3 3)"></path>
  <path class="dd-front" fill-rule="evenodd" d="M14 9 H24 A15 15 0 0 1 24 39 H14 Z M20 15 H24 A9 9 0 0 1 24 33 H20 Z"></path>
</svg>`;

const MINI_ICONS = {
  lock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>',
  compass: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2 5-5 2 2-5z"/></svg>',
  book: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 19.5V5a2 2 0 0 1 2-2h13v16H6.5A2.5 2.5 0 0 0 4 21.5v-2z"/><path d="M8 7h7"/><path d="M8 11h5"/></svg>',
  archive: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="5" rx="1.5"/><path d="M5 9v9a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9"/><path d="M10 13h4"/></svg>',
  alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 8v4.5"/><path d="M12 16h.01"/></svg>',
  github: '<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z"></path></svg>',
};

/** The shared shell for every standalone page. `inner` is trusted markup. */
function miniPage(theme: Theme, title: string, icon: string, inner: string, iconClass = ""): string {
  return `<!doctype html>
<html lang="en" data-theme="${theme}">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>${title} — DeepDoc</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
<style>${MINI_PAGE_CSS}</style>
</head>
<body>
  <header class="mini-bar"><a class="brand" href="/" aria-label="DeepDoc Cloud">${BRAND_MARK_SVG}eepDoc</a></header>
  <main class="card">
    <div class="mini-icon${iconClass ? " " + iconClass : ""}">${icon}</div>
    ${inner}
  </main>
</body>
</html>`;
}

/**
 * Theme preference, shared with deepdoc.tech.
 *
 * localStorage is scoped per hostname, so the marketing site's toggle could
 * never reach cloud.deepdoc.tech — pick light over there, click through, and
 * you were slammed back into dark. A cookie on .deepdoc.tech is the only
 * channel that spans both. Read server-side here, which also means the theme
 * is correct in the very first byte: no inline no-flash script needed.
 */
export function readTheme(cookies: { get(name: string): { value: string } | undefined }): Theme {
  return cookies.get("dd_theme")?.value === "light" ? "light" : "dark";
}

export function tryPageHtml(theme: Theme = "dark"): string {
  return `<!doctype html>
<html lang="en" data-theme="${theme}">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>DeepDoc Cloud — generate docs from a GitHub repo</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700;9..40,800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
<style>
  ${TOKENS_CSS}
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    position: relative; min-height: 100vh; background: var(--surface); color: var(--ink);
    font-family: var(--font-sans); font-feature-settings: "ss01";
    font-size: 14px; line-height: 1.5;
    display: flex; flex-direction: column;
    -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale;
    text-rendering: optimizeLegibility;
  }
  a { color: inherit; }
  h1, h2, h3, p { margin: 0; }
  img { max-width: 100%; }
  ::selection { background: var(--accent-dim); color: var(--ink); }
  #content { flex: 1; display: flex; flex-direction: column; min-height: 60vh; }

  /* Texture: a fine pixel grid fading out within the first screen, the same
     one deepdoc.tech's hero sits on. The film grain is body::after in the
     shared tokens. Absolute, not fixed: it belongs to the top of the page. */
  body::before { content: ''; position: absolute; left: 0; right: 0; top: 0; height: 560px;
    pointer-events: none; z-index: 0;
    background-image: linear-gradient(var(--grid) 1px, transparent 1px), linear-gradient(90deg, var(--grid) 1px, transparent 1px);
    background-size: 14px 14px;
    -webkit-mask-image: radial-gradient(ellipse 62% 78% at 50% 0%, black 8%, transparent 70%);
    mask-image: radial-gradient(ellipse 62% 78% at 50% 0%, black 8%, transparent 70%); }
  #notice-slot, #content { position: relative; z-index: 1; }

  /* Two widths, deliberately independent.

     --w-bar is the app bar's, and it is constant: it matches
     deepdoc.tech's Header.astro (max-w-6xl + px-6) so the bar is the one
     thing that never moves as you navigate. It used to read --w-page, which
     meant the whole navbar visibly narrowed to 736px on /generate and the
     project detail page while staying 1152px on /projects — the bar
     disagreeing with itself between routes.

     --w-page is the content column's, and it does change: the signed-in
     task screens are a reading column, the gallery and project lists are
     grids that want the full width. The render functions set the attribute. */
  body { --w-bar: 1152px; --w-page: 1152px; }
  body[data-view="app"] { --w-page: 736px; }
  .page { width: 100%; max-width: var(--w-page); margin: 0 auto; padding: 0 24px 96px; }
  /* On the task screens the page keeps the bar's full width and the reading
     column is left-aligned inside it, rather than the page itself shrinking
     and re-centering. Both matter: the app bar stays put between routes, and
     the brand mark still sits directly above the page title instead of the
     heading floating in from the left edge of a narrower column. */
  body[data-view="app"] .page { max-width: var(--w-bar); }
  body[data-view="app"] .page > * { max-width: var(--w-page); }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
  @keyframes rise { from { transform: translateY(6px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
  @keyframes shimmer { to { transform: translateX(100%); } }
  @keyframes sweep { from { transform: translateX(-100%); } to { transform: translateX(250%); } }
  @keyframes breathe { 0%, 100% { opacity: 0.75; transform: translate(-50%, -54%) scale(0.96); } 50% { opacity: 1; transform: translate(-50%, -54%) scale(1.04); } }
  @keyframes ping { 0% { box-shadow: 0 0 0 0 var(--accent-line); } 100% { box-shadow: 0 0 0 7px transparent; } }

  /* ── Type ramp — fixed steps. Negative tracking above 18px is what stops
     large text looking like scaled-up body copy. Mono is reserved for things
     that are literally code (a pasted URL, the site address in a preview
     window); repo names render in the sans. ─────────────────────────── */
  .t-eyebrow { font-size: 12px; font-weight: 500; letter-spacing: 0.01em; color: var(--ink-faint); }
  .t-display { font-size: 32px; font-weight: 600; letter-spacing: -0.032em; line-height: 1.1; }
  .t-sub { font-size: 14px; line-height: 1.6; color: var(--ink-muted); max-width: 62ch; }
  .sub { color: var(--ink-muted); font-size: 13.5px; line-height: 1.6; }
  code, .mono { font-family: var(--font-mono); }
  .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden;
    clip: rect(0 0 0 0); white-space: nowrap; border: 0; }

  /* ── App bar — same 52px blurred recipe and brand sizing as deepdoc.tech's
     Header.astro/Logo.astro, so switching domains reads as one product.
     Duplicated (not imported) because these are plain .ts endpoints; keep
     in sync by hand if either changes.

     The slot itself is the sticky element. .appbar used to be the sticky
     one, but its containing block was this 52px slot, so it scrolled away
     with the page and never actually stuck. ───────────────────────────── */
  /* Both slots ship empty and fill only after /api/me resolves. Reserving
     the height here keeps the page from jumping 52px on boot. */
  #appbar-slot { position: sticky; top: 0; z-index: 10; min-height: 52px; border-bottom: 1px solid var(--line); }
  #appbar-slot:has(.appbar) { border-bottom: none; }
  .appbar { border-bottom: 1px solid var(--line);
    background: color-mix(in oklab, var(--surface) 76%, transparent);
    backdrop-filter: blur(20px) saturate(1.5); -webkit-backdrop-filter: blur(20px) saturate(1.5); }
  .appbar-inner { max-width: var(--w-bar); margin: 0 auto; height: 52px; padding: 0 24px;
    display: flex; align-items: center; justify-content: space-between; gap: 16px; }
  .brand { font-family: var(--font-sans); font-weight: 600; font-size: 1.2rem; text-decoration: none;
    letter-spacing: -0.015em; color: var(--ink); display: flex; align-items: center; cursor: pointer;
    border-radius: var(--r-xs); transition: opacity 0.15s var(--ease); }
  .brand:hover { opacity: 0.82; }
  .brand:focus-visible { outline: 2px solid var(--accent); outline-offset: 4px; }
  .dd-mark { display: block; flex-shrink: 0; width: 1.16em; height: 1.16em; margin-left: -0.33em; margin-right: 0.04em; transform: translateY(-0.05em); }
  .dd-mark .dd-front { fill: var(--accent); }
  .dd-mark .dd-echo { fill: none; stroke: var(--accent); stroke-width: 2; stroke-linecap: round; }
  .dd-mark .dd-echo-1 { opacity: 0.4; } .dd-mark .dd-echo-2 { opacity: 0.18; }
  .bar-tools { display: flex; align-items: center; gap: 6px; }
  .bar-link { padding: 6px 10px; border-radius: var(--r-sm); font-size: 14px; font-weight: 500; color: var(--ink-muted);
    text-decoration: none; transition: color 0.15s var(--ease); }
  .bar-link:hover { color: var(--ink); }
  /* 32px hit area, muted until hover — matches Header.astro's toggle. */
  .theme-toggle { display: flex; align-items: center; justify-content: center; width: 32px; height: 32px;
    border-radius: var(--r-sm); border: 1px solid transparent; background: transparent; cursor: pointer;
    color: var(--ink-muted); transition: color 0.15s var(--ease), background 0.15s var(--ease); }
  .theme-toggle:hover { color: var(--ink); background: var(--hover); }
  .theme-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .account-wrap { position: relative; }
  .account-chip { display: flex; align-items: center; gap: 8px; background: transparent;
    border: 1px solid transparent; border-radius: 999px; padding: 3px 9px 3px 3px; color: var(--ink);
    font-family: var(--font-sans); font-size: 13px; font-weight: 500; letter-spacing: -0.005em;
    height: 34px; cursor: pointer; transition: background 0.15s var(--ease), border-color 0.15s var(--ease); }
  .account-chip:hover { background: var(--hover); border-color: var(--line); }
  .account-chip[aria-expanded="true"] { background: var(--hover); border-color: var(--line-strong); }
  .account-chip:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .account-chip img { width: 26px; height: 26px; border-radius: 50%; box-shadow: 0 0 0 1px var(--line-strong); }
  .account-chip .chev { width: 14px; height: 14px; color: var(--ink-faint); transition: transform 0.2s var(--ease); }
  .account-chip[aria-expanded="true"] .chev { transform: rotate(180deg); }

  /* ── Profile dropdown — identity and navigation only. Project rows and
     project actions deliberately never appear here; they live on /projects
     and the detail page. ───────────────────────────────────────────── */
  .profile-dd { position: absolute; right: 0; top: 44px; width: 252px; background: var(--card);
    border: 1px solid var(--line-strong); border-radius: var(--r-lg); padding: 6px;
    box-shadow: inset 0 1px 0 var(--edge), var(--shadow-pop); z-index: 15; transform-origin: top right;
    animation: rise 0.16s var(--ease); }
  .profile-dd-head { display: flex; align-items: center; gap: 11px; padding: 10px 10px 12px;
    margin-bottom: 6px; border-bottom: 1px solid var(--line); }
  .profile-dd-head img { width: 38px; height: 38px; border-radius: 50%; box-shadow: 0 0 0 1px var(--line-strong); }
  .profile-dd-head .nm { font-size: 14px; font-weight: 600; letter-spacing: -0.012em; }
  .profile-dd-head .qt { font-size: 12px; color: var(--ink-faint); margin-top: 1px; }
  .profile-dd-link { display: flex; align-items: center; justify-content: space-between; gap: 8px;
    padding: 9px 10px; font-size: 13.5px; color: var(--ink); text-decoration: none; cursor: pointer;
    border-radius: var(--r-sm); background: none; border: none; width: 100%; text-align: left;
    font-family: var(--font-sans); transition: background 0.12s var(--ease); }
  .profile-dd-link:hover { background: var(--hover); }
  .profile-dd-link:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .profile-dd-link .count { font-size: 12px; color: var(--ink-faint); min-width: 20px; height: 20px; padding: 0 6px;
    border-radius: 999px; background: var(--surface-high); display: inline-flex; align-items: center; justify-content: center; }
  .profile-dd-sep { height: 1px; background: var(--line); margin: 6px 0; }

  /* ── Buttons — one shape, three intents, three sizes. Every interactive
     control on these screens is built from this and nothing else. The
     solid button carries a lit top edge so it reads as a pressable object
     rather than a flat rectangle. ─────────────────────────────────────── */
  button { font-family: var(--font-sans); }
  .btn { display: inline-flex; align-items: center; justify-content: center; gap: 7px;
    height: 36px; padding: 0 16px; border-radius: var(--r-sm); border: 1px solid transparent;
    background: var(--solid); color: var(--solid-ink); box-shadow: var(--btn-shadow);
    font-size: 13.5px; font-weight: 600; letter-spacing: -0.008em; cursor: pointer; white-space: nowrap; text-decoration: none;
    transition: background 0.15s var(--ease), border-color 0.15s var(--ease), box-shadow 0.15s var(--ease), color 0.15s var(--ease), transform 0.1s var(--ease); }
  .btn:hover:not(:disabled) { background: var(--solid-hover); }
  .btn:active:not(:disabled) { transform: scale(0.985); }
  .btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .btn:disabled { opacity: 0.32; cursor: not-allowed; box-shadow: none; }
  .btn svg { flex-shrink: 0; }
  .btn.secondary { background: var(--card); color: var(--ink); border-color: var(--line-strong);
    box-shadow: inset 0 1px 0 var(--edge), var(--shadow-sm); }
  .btn.secondary:hover:not(:disabled) { background: var(--card-hover); border-color: color-mix(in oklab, var(--line-strong) 100%, var(--ink) 18%); }
  .btn.ghost { background: transparent; color: var(--ink-muted); border-color: var(--line-strong); box-shadow: none; }
  .btn.ghost:hover:not(:disabled) { color: var(--ink); background: var(--hover); }
  .btn.full { width: 100%; }
  .btn.small { height: 30px; padding: 0 12px; font-size: 12.5px; }
  .btn.large { height: 46px; padding: 0 20px; font-size: 14.5px; border-radius: var(--r-md); }
  .btn-spinner { display: inline-block; width: 7px; height: 7px; border-radius: 50%;
    background: currentColor; animation: pulse 1.2s ease-in-out infinite; }
  /* Destructive and tertiary actions are text, not filled controls. A
     delete button styled like a primary action is a trap. */
  .link-danger, .link-quiet { background: none; border: none; padding: 4px 2px; cursor: pointer;
    font-family: var(--font-sans); font-size: 13px; border-radius: var(--r-xs);
    transition: color 0.12s var(--ease); }
  .link-danger { color: var(--ink-muted); }
  .link-danger:hover { color: var(--danger); }
  .link-quiet { color: var(--ink-muted); }
  .link-quiet:hover { color: var(--ink); }
  .link-danger:focus-visible, .link-quiet:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .danger-confirm { display: flex; align-items: center; gap: 14px; font-size: 13px; color: var(--ink-muted); animation: rise 0.16s var(--ease); }
  .danger-confirm .link-danger { color: var(--danger); font-weight: 600; }

  /* ── Inputs ─────────────────────────────────────────────────────────── */
  input {
    width: 100%; height: 42px; padding: 0 14px; border-radius: var(--r-md);
    border: 1px solid var(--line-strong); background: var(--card); color: var(--ink);
    font-family: var(--font-sans); font-size: 14px; letter-spacing: -0.005em;
    box-shadow: inset 0 1px 0 var(--edge), var(--shadow-sm);
    outline: none; transition: border-color 0.15s var(--ease), box-shadow 0.15s var(--ease), background 0.15s var(--ease);
  }
  input.mono { font-family: var(--font-mono); font-size: 13px; }
  input::placeholder { color: var(--ink-faint); }
  input:hover { border-color: color-mix(in oklab, var(--line-strong) 100%, var(--ink) 14%); }
  input:focus { border-color: var(--accent); box-shadow: 0 0 0 4px var(--accent-dim); }
  /* Search field with a leading glyph. The icon is decorative; the input
     keeps its own accessible name. */
  .field-search { position: relative; }
  .field-search svg { position: absolute; left: 14px; top: 50%; transform: translateY(-50%);
    width: 15px; height: 15px; color: var(--ink-faint); pointer-events: none; }
  .field-search input { padding-left: 38px; }
  /* A keyboard hint, not code — sans, not mono. */
  .kbd { display: inline-flex; align-items: center; justify-content: center; min-width: 22px; height: 22px;
    padding: 0 6px; border-radius: 6px; border: 1px solid var(--line-strong); background: var(--surface-high);
    font-size: 11.5px; font-weight: 500; color: var(--ink-muted); box-shadow: inset 0 -1px 0 var(--line); }

  /* ── Page furniture ─────────────────────────────────────────────────── */
  .page-head { display: flex; align-items: flex-end; justify-content: space-between;
    gap: 24px; flex-wrap: wrap; padding: 56px 0 28px; }
  .page-head .t-sub { margin-top: 8px; }
  .back-link { display: inline-flex; align-items: center; gap: 6px; font-size: 13px;
    color: var(--ink-muted); text-decoration: none; margin: 34px 0 0; cursor: pointer;
    border-radius: var(--r-xs); transition: color 0.12s var(--ease), gap 0.15s var(--ease); }
  .back-link:hover { color: var(--ink); gap: 8px; }
  .back-link:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
  /* Empty states teach the next action; they don't decorate the absence. */
  .empty-state { text-align: center; padding: 64px 20px; display: flex; flex-direction: column; align-items: center; }
  .empty-icon { width: 44px; height: 44px; border-radius: 12px; display: flex; align-items: center; justify-content: center;
    background: var(--card); border: 1px solid var(--line-strong); color: var(--ink-muted); margin-bottom: 18px;
    box-shadow: inset 0 1px 0 var(--edge), var(--shadow-card); }
  .empty-icon svg { width: 20px; height: 20px; }
  .empty-icon.is-live { color: var(--accent); }
  .empty-state h2 { font-size: 17px; font-weight: 600; letter-spacing: -0.015em; margin: 0 0 8px; }
  .empty-state p { font-size: 14px; color: var(--ink-muted); margin: 0 auto 24px; max-width: 44ch; line-height: 1.6; }
  .error-box { color: var(--danger); font-size: 13px; line-height: 1.6; background: var(--danger-dim);
    border: 1px solid color-mix(in oklab, var(--danger) 30%, transparent); border-radius: var(--r-md);
    padding: 13px 15px; margin-top: 16px; white-space: pre-wrap; }
  /* Loading placeholders shaped like the content they replace, so the page
     doesn't reflow when data lands. */
  .skel { position: relative; overflow: hidden; border-radius: var(--r-xs); background: var(--surface-high); }
  .skel::after { content: ''; position: absolute; inset: 0; transform: translateX(-100%);
    background: linear-gradient(90deg, transparent, var(--hover), transparent); animation: shimmer 1.5s infinite; }

  /* ── Sign-in (unauthenticated) ───────────────────────────────────────
     Not a pitch page: deepdoc.tech's landing already sells the product.
     This is the gate, over a quiet backdrop. */
  .modal-veil { position: fixed; inset: 0; background: color-mix(in oklab, var(--surface) 64%, transparent);
    backdrop-filter: blur(10px) saturate(1.2); -webkit-backdrop-filter: blur(10px) saturate(1.2);
    display: flex; align-items: center; justify-content: center; padding: 24px; z-index: 20;
    animation: fade 0.2s var(--ease); }
  @keyframes fade { from { opacity: 0; } to { opacity: 1; } }
  .modal { position: relative; overflow: hidden; width: 100%; max-width: 432px; background: var(--card);
    border: 1px solid var(--line-strong); border-radius: var(--r-xl); padding: 30px 28px 26px;
    box-shadow: inset 0 1px 0 var(--edge), var(--shadow-lift); text-align: center;
    animation: rise 0.24s var(--ease); }
  .modal::before { content: ''; position: absolute; left: 0; right: 0; top: 0; height: 220px; pointer-events: none;
    background-image: linear-gradient(var(--grid) 1px, transparent 1px), linear-gradient(90deg, var(--grid) 1px, transparent 1px);
    background-size: 14px 14px;
    -webkit-mask-image: radial-gradient(60% 80% at 50% 0%, black 0%, transparent 72%);
    mask-image: radial-gradient(60% 80% at 50% 0%, black 0%, transparent 72%); }
  .modal > * { position: relative; }
  .modal h1 { font-size: 23px; font-weight: 600; letter-spacing: -0.028em; margin: 0 0 9px; }
  .modal p.modal-sub { font-size: 13.5px; line-height: 1.65; color: var(--ink-muted); margin: 0 auto; max-width: 36ch; }
  .modal p.modal-quota { font-size: 12.5px; color: var(--ink-faint); margin-top: 10px; }
  .modal-icon-wrap { position: relative; height: 92px; display: flex; align-items: center; justify-content: center; margin-bottom: 10px; }
  .modal-dot-grid {
    position: absolute; inset: 0;
    background-image: radial-gradient(circle, var(--line-strong) 1.3px, transparent 1.5px);
    background-size: 16px 16px;
    -webkit-mask-image: radial-gradient(ellipse 60% 70% at 50% 50%, black 10%, transparent 75%);
    mask-image: radial-gradient(ellipse 60% 70% at 50% 50%, black 10%, transparent 75%);
  }
  .modal-icon-badge {
    position: relative; width: 64px; height: 64px; border-radius: 18px;
    background: var(--surface-high); display: flex; align-items: center; justify-content: center;
    color: var(--ink); box-shadow: inset 0 1px 0 var(--edge), 0 0 0 1px var(--line-strong), var(--shadow-pop);
  }
  .modal-icon-badge svg { width: 30px; height: 30px; }
  /* The three promises sit in one inset list with hairlines, rather than
     three free-floating rows each with a tinted icon tile. */
  .modal-features { margin: 24px 0 22px; text-align: left; border: 1px solid var(--line);
    border-radius: var(--r-lg); background: color-mix(in oklab, var(--surface) 55%, var(--card)); padding: 2px 14px; }
  .modal-feature { display: flex; align-items: flex-start; gap: 12px; padding: 12px 0; }
  .modal-feature + .modal-feature { border-top: 1px solid var(--line); }
  .modal-feature-icon { flex-shrink: 0; width: 28px; height: 28px; border-radius: var(--r-sm);
    background: var(--surface-high); border: 1px solid var(--line); display: flex; align-items: center; justify-content: center; color: var(--ink-muted); }
  .modal-feature-icon svg { width: 15px; height: 15px; }
  .modal-feature-title { font-size: 13.5px; font-weight: 600; letter-spacing: -0.01em; color: var(--ink); margin: 0 0 2px; }
  .modal-feature-desc { font-size: 12.5px; color: var(--ink-muted); line-height: 1.5; margin: 0; }

  /* Status dot, shared by the project cards and the detail page. Colour is
     the whole indicator; the text label sits beside it. */
  .pr-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; background: var(--ink-faint); }
  .pr-dot.done { background: var(--accent); }
  .pr-dot.failed { background: var(--danger); }
  .pr-dot.building { background: var(--accent); animation: pulse 1.4s ease-in-out infinite; }
  /* Status as a small chip: the one place a build state is named in words. */
  .status-text { display: inline-flex; align-items: center; gap: 6px; height: 22px; padding: 0 9px 0 8px;
    border-radius: 999px; border: 1px solid var(--line-strong); background: var(--surface-high);
    font-size: 11.5px; font-weight: 500; color: var(--ink-muted); white-space: nowrap; }
  .status-text .sdot { width: 6px; height: 6px; border-radius: 50%; background: var(--ink-faint); }
  .status-text.done { color: var(--ink); }
  .status-text.done .sdot { background: var(--accent); box-shadow: 0 0 0 3px var(--accent-dim); }
  .status-text.building { color: var(--ink); }
  .status-text.building .sdot { background: var(--accent); animation: ping 1.4s var(--ease) infinite; }
  .status-text.failed { color: var(--danger); background: var(--danger-dim); border-color: color-mix(in oklab, var(--danger) 30%, transparent); }
  .status-text.failed .sdot { background: var(--danger); }

  /* Language, with GitHub's own colour for it. A tiny dot, so a page of
     repositories gets some real colour without any of it being the accent. */
  .lang { display: inline-flex; align-items: center; gap: 6px; }
  .lang-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; background: var(--lang, var(--ink-faint));
    box-shadow: inset 0 0 0 1px rgba(0,0,0,0.18); }
  /* Owner avatars. Only ever GitHub's own avatar host (see safeAvatar);
     anything else falls back to a monogram tile. */
  .av { flex-shrink: 0; object-fit: cover; background: var(--surface-high); box-shadow: 0 0 0 1px var(--line-strong); }
  .av-fallback { display: inline-flex; align-items: center; justify-content: center; color: var(--ink-muted);
    font-weight: 600; text-transform: uppercase; }

  /* ── /projects/:owner/:repo ─────────────────────────────────────────── */
  .proj-head { display: flex; align-items: center; justify-content: space-between; gap: 20px;
    padding: 22px 0 0; flex-wrap: wrap; }
  .proj-id { display: flex; align-items: center; gap: 15px; min-width: 0; }
  .proj-id .av { width: 48px; height: 48px; border-radius: 13px; font-size: 19px; }
  .title-block { min-width: 0; }
  .proj-head .title-block h1 { font-size: 26px; font-weight: 600; letter-spacing: -0.03em; line-height: 1.15; margin: 0 0 7px;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .title-block h1 .g-owner { color: var(--ink-faint); font-weight: 400; }
  .proj-meta-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: 12.5px; color: var(--ink-faint); }
  .meta-sep { width: 3px; height: 3px; border-radius: 50%; background: var(--ink-faint); opacity: 0.7; }
  .proj-actions { display: flex; gap: 8px; }
  /* The generated site is what the project *is*, so show it — in a browser
     window, the same frame deepdoc.tech's hero uses — and make it the way in. */
  .detail-preview { position: relative; display: block; margin: 28px 0 0; border: 1px solid var(--line-strong);
    border-radius: var(--r-lg); overflow: hidden; background: var(--card); color: inherit; text-decoration: none;
    box-shadow: inset 0 1px 0 var(--edge), var(--shadow-lift);
    transition: border-color 0.2s var(--ease), transform 0.25s var(--ease), box-shadow 0.25s var(--ease); }
  a.detail-preview:hover { border-color: color-mix(in oklab, var(--line-strong) 100%, var(--ink) 16%); transform: translateY(-2px); }
  .detail-preview:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
  .win-bar { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 12px; height: 40px; padding: 0 14px;
    border-bottom: 1px solid var(--line); background: color-mix(in oklab, var(--surface-high) 55%, var(--card)); }
  .win-dots { display: flex; gap: 7px; }
  .win-dots i { width: 10px; height: 10px; border-radius: 50%; background: var(--line-strong); }
  .win-url { display: inline-flex; align-items: center; gap: 7px; max-width: 100%; min-width: 0; height: 24px; padding: 0 12px;
    border-radius: 7px; background: var(--surface); border: 1px solid var(--line); color: var(--ink-faint);
    font-family: var(--font-mono); font-size: 11.5px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  .win-url svg { width: 11px; height: 11px; flex-shrink: 0; }
  .win-open { justify-self: end; display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: var(--ink-muted);
    transition: color 0.15s var(--ease); }
  .win-open svg { width: 13px; height: 13px; }
  a.detail-preview:hover .win-open { color: var(--ink); }
  .win-body { position: relative; aspect-ratio: 16 / 10; background: var(--surface-high); overflow: hidden; }
  .win-body img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; object-position: top center; display: block;
    transition: transform 0.7s var(--ease), opacity 0.4s var(--ease); }
  a.detail-preview:hover .win-body img { transform: scale(1.012); }
  .detail-preview.is-empty .win-body { aspect-ratio: 16 / 7; display: flex; align-items: center; justify-content: center;
    text-align: center; padding: 24px; background: var(--card); }
  .detail-preview.is-empty .shot-wire { opacity: 0.55; }
  .detail-preview.is-empty p { position: relative; font-size: 13.5px; color: var(--ink-muted); margin: 0; max-width: 36ch; line-height: 1.6;
    padding: 10px 16px; border-radius: var(--r-md); background: color-mix(in oklab, var(--card) 85%, transparent);
    border: 1px solid var(--line); backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px); }
  /* Both project settings on one quiet bar rather than two labelled
     sections with a bordered danger zone. The two-step confirm is what
     prevents the accident; the box around it was decoration. */
  .detail-actions { display: flex; align-items: center; justify-content: space-between; gap: 16px;
    flex-wrap: wrap; margin-top: 16px; padding: 10px 12px 10px 10px; border: 1px solid var(--line);
    border-radius: var(--r-lg); background: var(--card); box-shadow: inset 0 1px 0 var(--edge); }
  .detail-actions .vis-cluster { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .detail-actions .vis-hint { margin: 0; }

  /* ── Visibility — a real segmented control, not two loose pills ────── */
  .vis-group { display: inline-flex; align-items: center; gap: 2px; padding: 3px;
    border-radius: var(--r-md); background: var(--seg-track); border: 1px solid var(--line); }
  .vis-pill { appearance: none; display: inline-flex; align-items: center; gap: 6px; height: 28px; padding: 0 13px;
    border-radius: var(--r-xs); border: 1px solid transparent; background: transparent; color: var(--ink-muted);
    font-family: var(--font-sans); font-size: 12.5px; font-weight: 500; letter-spacing: -0.005em;
    cursor: pointer; transition: color 0.15s var(--ease), background 0.15s var(--ease); }
  .vis-pill svg { width: 13px; height: 13px; }
  .vis-pill:hover:not(.active) { color: var(--ink); }
  .vis-pill.active { background: var(--seg-thumb); color: var(--ink);
    border-color: var(--line-strong); box-shadow: inset 0 1px 0 var(--edge), var(--shadow-sm); }
  .vis-pill:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .vis-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
  .vis-hint { font-size: 12.5px; color: var(--ink-muted); margin-top: 10px; line-height: 1.55; }

  /* ── /generate — the only post-login home ───────────────────────────── */
  /* One panel: the search field is its header and the list its body, so
     the picker reads as a single object rather than a field floating over
     a separate scrollbox. */
  .picker { border: 1px solid var(--line-strong); border-radius: var(--r-lg); background: var(--card);
    box-shadow: inset 0 1px 0 var(--edge), var(--shadow-card); overflow: hidden;
    transition: border-color 0.15s var(--ease), box-shadow 0.15s var(--ease); }
  .picker:has(input:focus) { border-color: var(--accent-line); box-shadow: 0 0 0 4px var(--accent-dim), var(--shadow-card); }
  .picker .field-search input { height: 48px; border: none; border-bottom: 1px solid var(--line); border-radius: 0;
    background: transparent; box-shadow: none; padding-left: 42px; }
  .picker .field-search svg { left: 16px; }
  .picker-foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 16px;
    border-top: 1px solid var(--line); font-size: 12px; color: var(--ink-faint); }
  .picker-foot:empty { display: none; }
  /* A picker, not a scrollbox of raw rows: padded track, rounded rows, hover
     surface, and a tinted ring on the selection. */
  .repo-list { max-height: 360px; overflow-y: auto; overscroll-behavior: contain;
    padding: 6px; scrollbar-width: thin; scrollbar-color: var(--line-strong) transparent; }
  .repo-empty { padding: 18px 14px; font-size: 13px; color: var(--ink-muted); line-height: 1.6; }
  /* Real <button> elements, not clickable divs: keyboard focus, Enter/Space
     activation and a focus ring all come for free. */
  .repo-item { display: block; width: 100%; text-align: left; border: none; background: transparent;
    font-family: var(--font-sans); color: inherit; padding: 11px 12px; border-radius: var(--r-sm);
    cursor: pointer; transition: background 0.1s var(--ease), box-shadow 0.12s var(--ease); }
  .repo-item:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  /* filterRepos() toggles the the hidden property, and the author-level
     display: block above outranks the UA's [hidden] rule. Without this the
     search box stops filtering. */
  .repo-item[hidden] { display: none; }
  .repo-item:hover { background: var(--hover); }
  .repo-item.selected { background: var(--accent-dim); box-shadow: inset 0 0 0 1px var(--accent-line); }
  .repo-item .top-line { display: flex; align-items: center; gap: 10px; font-size: 14px;
    font-weight: 500; letter-spacing: -0.01em; }
  .repo-item .rname, .repo-item .desc { display: block; }
  .repo-item .rname { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .repo-item .rname .g-owner { color: var(--ink-faint); font-weight: 400; }
  .repo-item .priv, .repo-item .lang { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 400;
    color: var(--ink-faint); flex-shrink: 0; }
  .repo-item .priv svg { width: 11px; height: 11px; }
  .repo-item .desc { display: block; color: var(--ink-muted); font-size: 12.5px; margin-top: 3px;
    line-height: 1.45; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .proj-tag { font-size: 11px; font-weight: 500; padding: 2px 8px; border-radius: 999px;
    border: 1px solid var(--line-strong); color: var(--ink-muted); margin-left: auto; flex-shrink: 0; }
  .proj-tag.done { color: var(--accent); border-color: var(--accent-line); background: var(--accent-dim); }
  .proj-tag.failed { color: var(--danger); border-color: color-mix(in oklab, var(--danger) 30%, transparent); background: var(--danger-dim); }
  .divider { display: flex; align-items: center; gap: 14px; color: var(--ink-faint); font-size: 12.5px; margin: 30px 0 16px; }
  .divider::before, .divider::after { content: ''; flex: 1; height: 1px; background: var(--line); }
  /* Lifts off the page right where you made the choice. Not pinned to the
     viewport, which just reads as further away on a tall screen. */
  .confirm-panel { margin-top: 14px; border: 1px solid var(--line-strong); border-radius: var(--r-lg);
    padding: 18px; background: var(--card); box-shadow: inset 0 1px 0 var(--edge), var(--shadow-pop);
    animation: rise 0.18s var(--ease); }
  .confirm-panel .who { font-size: 14.5px; font-weight: 500; letter-spacing: -0.012em; margin-bottom: 16px; }
  .confirm-panel .who strong { font-weight: 600; }
  .confirm-note { font-size: 12px; color: var(--ink-faint); text-align: center; margin-top: 10px; }

  /* ── Generating — the longest-dwell screen in the product. No fake
     percentage: the backend has no honest completion signal inside a
     stage, so the job here is to look alive and set expectations. The
     sweep along the top edge is motion, not progress; it stops on any
     terminal state. ──────────────────────────────────────────────────── */
  .gen-wrap { position: relative; flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 56px 24px 96px; }
  .gen-halo { position: absolute; left: 50%; top: 50%; width: min(760px, 100%); height: 520px; pointer-events: none;
    background-image: linear-gradient(var(--grid) 1px, transparent 1px), linear-gradient(90deg, var(--grid) 1px, transparent 1px);
    background-size: 14px 14px;
    -webkit-mask-image: radial-gradient(closest-side, black 0%, transparent 100%);
    mask-image: radial-gradient(closest-side, black 0%, transparent 100%);
    transform: translate(-50%, -54%); animation: breathe 7s ease-in-out infinite; }
  .gen-card { position: relative; width: 100%; max-width: 480px; border: 1px solid var(--line-strong); border-radius: var(--r-xl);
    background: var(--card); box-shadow: inset 0 1px 0 var(--edge), var(--shadow-lift); overflow: hidden; animation: rise 0.3s var(--ease); }
  .gen-progress { position: relative; height: 2px; overflow: hidden; background: var(--line); }
  .gen-progress::after { content: ''; position: absolute; top: 0; bottom: 0; left: 0; width: 40%;
    background: linear-gradient(90deg, transparent, var(--accent), transparent); animation: sweep 1.9s var(--ease) infinite; }
  .gen-card.is-stopped .gen-progress::after { animation: none; opacity: 0; }
  .gen-card.is-done .gen-progress { background: var(--accent); }
  .gen-card.is-done .gen-progress::after { animation: none; opacity: 0; }
  .gen-repo { display: flex; align-items: center; gap: 13px; padding: 20px 22px 18px; border-bottom: 1px solid var(--line); }
  .gen-repo .av { width: 38px; height: 38px; border-radius: 11px; font-size: 15px; }
  .gen-id { flex: 1; min-width: 0; }
  .gen-kicker { font-size: 12px; color: var(--ink-faint); margin-bottom: 1px; }
  .gen-repo-name { font-size: 15px; font-weight: 600; letter-spacing: -0.015em; color: var(--ink);
    min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .gen-repo-name .g-owner { color: var(--ink-faint); font-weight: 400; }
  /* Tabular figures so ticking seconds don't shift the layout. */
  .gen-elapsed { font-size: 26px; font-weight: 500; color: var(--ink); font-variant-numeric: tabular-nums;
    letter-spacing: -0.035em; flex-shrink: 0; }
  .gen-col { width: 100%; text-align: left; padding: 10px 22px 8px; }
  .gen-col #result-slot:not(:empty), .gen-col #error-slot:not(:empty) { padding-bottom: 10px; }
  .gen-note { display: flex; align-items: center; gap: 8px; font-size: 12.5px; line-height: 1.6; color: var(--ink-muted); margin: 0;
    padding: 13px 22px 15px; border-top: 1px solid var(--line); background: color-mix(in oklab, var(--surface) 35%, var(--card)); }
  .gen-note svg { width: 14px; height: 14px; color: var(--ink-faint); flex-shrink: 0; }
  .stage-row { position: relative; padding: 11px 0; }
  /* A rail joining the dots, so three stages read as one sequence. */
  .stage-row:not(:last-child)::before { content: ''; position: absolute; left: 8.5px; top: 31px; bottom: -11px;
    width: 1px; background: var(--line-strong); }
  .stage-row.done:not(:last-child)::before { background: var(--accent); opacity: 0.45; }
  .stage-head { display: flex; align-items: center; gap: 13px; }
  /* A ring rather than a bare dot, so a finished stage can hold a tick and a
     pending one reads as an empty slot instead of a dimmer dot. */
  .stage-dot { position: relative; z-index: 1; width: 18px; height: 18px; border-radius: 50%;
    border: 1.5px solid var(--line-strong); background: var(--card); flex-shrink: 0;
    display: flex; align-items: center; justify-content: center;
    transition: background 0.25s var(--ease), border-color 0.25s var(--ease); }
  .stage-row.active .stage-dot { border-color: var(--accent); animation: ping 1.6s var(--ease) infinite; }
  .stage-row.active .stage-dot::after { content: ''; width: 7px; height: 7px; border-radius: 50%; background: var(--accent); }
  .stage-row.done .stage-dot { background: var(--accent); border-color: var(--accent); }
  /* A drawn tick: crisper than a glyph, and independent of font fallback. */
  .stage-row.done .stage-dot::after { content: ''; width: 7px; height: 4px; margin-top: -2px;
    border-left: 1.7px solid var(--accent-ink); border-bottom: 1.7px solid var(--accent-ink); transform: rotate(-45deg); }
  .stage-label { font-size: 14px; color: var(--ink-faint); flex: 1; transition: color 0.25s var(--ease); }
  .stage-row.active .stage-label { color: var(--ink); font-weight: 500; }
  .stage-row.done .stage-label { color: var(--ink-muted); }
  .stage-cap { display: none; font-size: 12.5px; color: var(--ink-muted); margin: 3px 0 0 31px; line-height: 1.5; }
  .stage-row.active .stage-cap { display: block; animation: rise 0.3s var(--ease); }
  .gen-actions { display: flex; gap: 8px; margin-top: 14px; }

  /* ── The ask — a centered question and one field, the whole hero of the
     public gallery. The field both filters the examples below and accepts a
     pasted GitHub link. ──────────────────────────────────────────────── */
  .ask { padding: 80px 0 52px; text-align: center; display: flex; flex-direction: column; align-items: center; }
  .ask-eyebrow { display: inline-flex; align-items: center; gap: 8px; height: 28px; padding: 0 12px 0 10px; margin-bottom: 22px;
    border-radius: 999px; border: 1px solid var(--line-strong); background: color-mix(in oklab, var(--card) 72%, transparent);
    backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px); box-shadow: inset 0 1px 0 var(--edge);
    font-size: 12.5px; font-weight: 500; color: var(--ink-muted); animation: rise 0.4s var(--ease) both; }
  .ask-eyebrow .live { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 0 3px var(--accent-dim); }
  /* The question is the only large type on the page, and it gets the room to
     be that. A faint top-to-bottom fade on the ink keeps 50px of text from
     reading as a shout. */
  .ask h1 { font-size: clamp(32px, 4.6vw, 52px); font-weight: 600; letter-spacing: -0.04em; line-height: 1.04;
    max-width: 17ch; margin: 0 auto; text-wrap: balance;
    background: linear-gradient(180deg, var(--ink) 40%, color-mix(in oklab, var(--ink) 74%, var(--surface)));
    -webkit-background-clip: text; background-clip: text; color: transparent;
    animation: rise 0.45s 0.04s var(--ease) both; }
  .ask-lede { font-size: 15.5px; line-height: 1.6; color: var(--ink-muted); max-width: 50ch; margin: 18px auto 0;
    text-wrap: balance; animation: rise 0.45s 0.08s var(--ease) both; }
  .ask-field { position: relative; width: 100%; max-width: 560px; margin: 32px auto 0; animation: rise 0.45s 0.12s var(--ease) both; }
  .ask-field > svg { position: absolute; left: 18px; top: 50%; transform: translateY(-50%);
    width: 17px; height: 17px; color: var(--ink-faint); pointer-events: none; }
  .ask-field input { height: 56px; padding-left: 48px; padding-right: 56px; border-radius: 16px;
    font-size: 15px; box-shadow: inset 0 1px 0 var(--edge), var(--shadow-pop); }
  .ask-field input:focus { box-shadow: 0 0 0 5px var(--accent-dim), var(--shadow-pop); }
  .ask-field .kbd { position: absolute; right: 16px; top: 50%; transform: translateY(-50%); pointer-events: none;
    transition: opacity 0.15s var(--ease); }
  .ask-field input:focus ~ .kbd, .ask-field input:not(:placeholder-shown) ~ .kbd { opacity: 0; }
  .ask-note { max-width: 560px; margin: 14px auto 0; font-size: 13px; color: var(--ink-muted); }
  #ask-slot { width: 100%; }
  /* The answer slot under the field: either "this repo already exists, go
     read it" or "nothing here matches, want it generated". Always carries an
     action — the state it replaced was a sentence with nothing to click. */
  .ask-hit { display: flex; align-items: center; justify-content: space-between; gap: 14px;
    max-width: 560px; margin: 14px auto 0; padding: 11px 12px 11px 16px; text-align: left;
    border: 1px solid var(--accent-line); background: color-mix(in oklab, var(--card) 88%, var(--accent));
    border-radius: var(--r-md); box-shadow: var(--shadow-card); animation: rise 0.16s var(--ease); }
  .ask-hit .ask-hit-text { min-width: 0; }
  .ask-hit span { display: block; font-size: 13.5px; font-weight: 500; letter-spacing: -0.01em; min-width: 0;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ask-hit .ask-hit-why { font-weight: 400; font-size: 12.5px; color: var(--ink-muted); margin-top: 2px; }

  /* Section label above a grid: what the grid is, and how much of it. */
  .section-head { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; margin: 0 0 16px; }
  .section-head h2 { font-size: 14px; font-weight: 600; letter-spacing: -0.01em; }
  .section-head span { font-size: 12.5px; color: var(--ink-faint); }

  /* ── Card grid — the public gallery and /projects are the same grid.
     Gallery cards carry a real screenshot of the generated site, because on
     the gallery the screenshot IS the pitch. /projects cards deliberately
     carry none: on your own list the name and build state are what you scan
     for. ─────────────────────────────────────────────────────────────── */
  /* grid-auto-rows: 1fr is what makes every card the same height. Without it
     the rows auto-size, so a row holding a repo with a description stood
     tall while every row of description-less repos below it collapsed — the
     grid looked like two different card designs. .card-desc is clamped to
     two lines, so the tallest card is bounded and one verbose description
     can't inflate the whole grid.

     330px: at 1152px that settles into three columns, instead of four
     cramped ones. min(100%, …) keeps a single narrow column from
     overflowing a phone. */
  .card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 330px), 1fr));
    grid-auto-rows: 1fr; gap: 16px; }
  /* The floor holds the grid's shape when a whole screen of repos happens to
     have no description — grid-auto-rows equalises the cards against each
     other, this stops them equalising short. */
  .card { position: relative; display: flex; flex-direction: column; min-height: 150px; border: 1px solid var(--line);
    border-radius: var(--r-lg); background: var(--card); box-shadow: inset 0 1px 0 var(--edge), var(--shadow-card);
    text-decoration: none; color: inherit; cursor: pointer;
    padding: 18px 18px 16px;
    transition: border-color 0.2s var(--ease), transform 0.2s var(--ease), box-shadow 0.2s var(--ease), background 0.2s var(--ease); }
  .card:hover { border-color: var(--line-strong); background: var(--card-hover); transform: translateY(-3px);
    box-shadow: inset 0 1px 0 var(--edge), var(--shadow-pop); }
  .card:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
  /* The grid filter toggles the hidden property, and the author-level display
     above outranks the UA's [hidden] rule. */
  .card[hidden] { display: none; }
  /* Screenshot cards: the image sits in an inset frame with a smaller radius
     (outer radius minus the 6px gap), the nested-corner detail that keeps a
     picture inside a card from looking pasted on. A wireframe of a docs page
     sits under the image, so a slow or cold thumbnail reads as a page that
     is loading rather than an empty box. */
  .card.has-shot { padding: 6px; }
  .card-shot { position: relative; aspect-ratio: 16 / 9; border-radius: 9px; overflow: hidden;
    background: var(--surface-high); box-shadow: inset 0 0 0 1px var(--line); isolation: isolate; flex-shrink: 0; }
  .shot-wire { position: absolute; inset: 0; color: var(--ink); }
  .shot-wire svg { display: block; width: 100%; height: 100%; }
  .gallery-shot { width: 100%; height: 100%; object-fit: cover; object-position: top center; display: block; }
  .card-shot .gallery-shot { position: absolute; inset: 0; opacity: 0;
    transition: opacity 0.45s var(--ease), transform 0.7s var(--ease); }
  .card-shot .gallery-shot.is-in { opacity: 1; }
  .card-shot::after { content: ''; position: absolute; inset: 0; border-radius: inherit; pointer-events: none; z-index: 2;
    box-shadow: inset 0 0 0 1px var(--line); }
  .card:hover .card-shot .gallery-shot { transform: scale(1.035); }
  .card.has-shot .card-body { padding: 14px 10px 0; }
  .card.has-shot .card-foot { padding: 0 10px 8px; }
  .card-body { display: flex; flex-direction: column; flex: 1; min-width: 0; }
  .card-id { display: flex; align-items: center; gap: 9px; min-width: 0; }
  .card-id .av { width: 20px; height: 20px; border-radius: 6px; font-size: 10px; }
  .card-title { font-size: 15px; font-weight: 600; letter-spacing: -0.018em; color: var(--ink); min-width: 0;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .card-title .g-owner { color: var(--ink-faint); font-weight: 400; }
  .card-desc { font-size: 13px; line-height: 1.55; color: var(--ink-muted); margin-top: 7px;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .card-foot { display: flex; align-items: center; gap: 14px; margin-top: auto; padding-top: 14px; }
  .card-metric { display: inline-flex; align-items: center; gap: 5px; font-size: 12px;
    color: var(--ink-faint); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .card-metric svg { width: 12px; height: 12px; flex-shrink: 0; }
  /* The affordance that says "this opens". Fills with ink on card hover. */
  .card-go { margin-left: auto; width: 30px; height: 30px; border-radius: 50%; flex-shrink: 0;
    display: flex; align-items: center; justify-content: center; background: var(--surface-high);
    border: 1px solid var(--line); color: var(--ink-muted);
    transition: background 0.2s var(--ease), color 0.2s var(--ease), border-color 0.2s var(--ease), transform 0.2s var(--ease); }
  .card:hover .card-go { background: var(--solid); border-color: var(--solid); color: var(--solid-ink); transform: translateX(2px); }
  /* /projects cards: build state first, visibility beside it. */
  .card-top { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 14px; }
  .card-vis { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: var(--ink-faint); }
  .card-vis svg { width: 12px; height: 12px; }
  /* The one card that starts something rather than opening something. Accent
     stays a state colour: a border and the plus glyph mark this card as the
     distinguished one. It used to carry a lime gradient wash, which made the
     loudest thing on the page a card that isn't the page's subject. */
  .card-new { border-color: var(--accent-line); }
  .card-new:hover { border-color: var(--accent); }
  .card-plus { width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center;
    justify-content: center; background: var(--accent-dim); border: 1px solid var(--accent-line);
    color: var(--accent); margin-bottom: 14px; flex-shrink: 0; }
  .card-new .card-go { background: var(--accent-dim); border-color: var(--accent-line); color: var(--accent); }
  .card-new:hover .card-go { background: var(--accent); border-color: var(--accent); color: var(--accent-ink); }
  /* In the screenshot grid the lead card gets a frame of its own: an empty
     page with the plus at its centre, so it lines up with its neighbours. */
  .new-shot { display: flex; align-items: center; justify-content: center; background: var(--surface); }
  .new-shot::before { content: ''; position: absolute; inset: 0;
    background-image: radial-gradient(circle, var(--line-strong) 1px, transparent 1.3px); background-size: 16px 16px;
    -webkit-mask-image: radial-gradient(ellipse 55% 65% at 50% 50%, black 5%, transparent 75%);
    mask-image: radial-gradient(ellipse 55% 65% at 50% 50%, black 5%, transparent 75%); }
  .new-shot::after { box-shadow: inset 0 0 0 1px var(--line-strong); }
  .new-shot .card-plus { position: relative; width: 48px; height: 48px; margin: 0; z-index: 1;
    box-shadow: 0 0 0 6px var(--accent-dim); transition: transform 0.25s var(--ease); }
  .new-shot .card-plus svg { width: 20px; height: 20px; }
  .card-new:hover .new-shot .card-plus { transform: scale(1.06); }
  /* At quota there is nothing to start, so the lead card states why instead of
     offering an action that would only be refused. */
  .card-new.is-blocked { background: none; box-shadow: none; border-style: dashed; border-color: var(--line-strong); cursor: default; }
  .card-new.is-blocked:hover { transform: none; border-color: var(--line-strong); }
  .card-new.is-blocked .card-plus { background: none; border-color: var(--line-strong); color: var(--ink-faint); }

  /* Saved-site allowance, shown as a meter beside the /projects title. Ink,
     not accent: a quota is not a state. */
  .quota { min-width: 188px; padding: 11px 14px 12px; border: 1px solid var(--line); border-radius: var(--r-md);
    background: var(--card); box-shadow: inset 0 1px 0 var(--edge); }
  .quota-row { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; font-size: 12px; color: var(--ink-muted); margin-bottom: 8px; }
  .quota-row strong { font-weight: 600; color: var(--ink); font-variant-numeric: tabular-nums; }
  .quota-bar { height: 4px; border-radius: 999px; background: var(--surface-high); overflow: hidden; }
  .quota-bar span { display: block; height: 100%; border-radius: inherit; background: var(--ink-muted); }
  .quota.is-full .quota-bar span { background: var(--ink); }

  .cloud-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap;
    margin-top: 88px; padding: 24px 0 8px; border-top: 1px solid var(--line);
    font-size: 12.5px; color: var(--ink-faint); }
  .cloud-footer .brand { font-size: 1rem; color: var(--ink-muted); }
  .cloud-footer-links { display: flex; gap: 22px; flex-wrap: wrap; }
  .cloud-footer-links a { color: var(--ink-faint); text-decoration: none; transition: color 0.12s var(--ease); }
  .cloud-footer-links a:hover { color: var(--ink); }

  /* Site-wide notice (generation paused). Calm, in the page flow below the app
     bar, never a modal: people can still browse every existing site. */
  #notice-slot:empty { display: none; }
  .notice { max-width: var(--w-page, 736px); margin: 16px auto 0; padding: 12px 16px; width: calc(100% - 48px);
    border: 1px solid var(--line-strong); border-radius: var(--r-md); background: var(--card);
    box-shadow: inset 0 1px 0 var(--edge), var(--shadow-card);
    display: flex; gap: 12px; align-items: flex-start; }
  .notice-dot { flex: none; width: 8px; height: 8px; margin-top: 7px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 0 3px var(--accent-dim); }
  .notice strong { display: block; font-weight: 600; color: var(--ink); }
  .notice span { color: var(--ink-muted); font-size: 14px; line-height: 1.5; }

  @media (max-width: 640px) {
    .page-head { padding: 38px 0 22px; }
    .t-display { font-size: 26px; }
    .proj-head .title-block h1 { font-size: 21px; }
    .proj-id .av { width: 40px; height: 40px; border-radius: 11px; }
    .ask { padding: 52px 0 32px; }
    .ask-lede { font-size: 14.5px; }
    .ask-field input { height: 52px; padding-right: 16px; font-size: 14.5px; }
    .ask-field .kbd { display: none; }
    .quota { width: 100%; }
    .win-bar { grid-template-columns: auto 1fr; }
    .win-open { display: none; }
    .gen-elapsed { font-size: 22px; }
    body::after { display: none; }
  }
  /* Motion is decoration everywhere on these screens, so it goes entirely
     for people who ask. State is still carried by colour and text. */
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation-duration: 0.01ms !important; animation-iteration-count: 1 !important;
      transition-duration: 0.01ms !important; }
    .gen-progress::after { display: none; }
  }
</style>
</head>
<body>
  <div id="appbar-slot"></div>
  <div id="notice-slot"></div>
  <div id="content"></div>
  <div id="modal-slot"></div>
  <script>
    const state = {
      me: null, projects: [], quota: null, repos: null, selected: null, visibility: 'private',
      genStart: null, genTimer: null, ddOpen: false,
    };
    const GITHUB_ICON_SVG = '<svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z"></path></svg>';
    // Sign-in modal feature icons — minimal 24x24 outline set (Lucide-style),
    // shared by signInModalHtml below.
    const SHIELD_CHECK_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2 4 5v6c0 5 3.5 9.5 8 11 4.5-1.5 8-6 8-11V5z"/><path d="m9 12 2 2 4-4"/></svg>';
    const GLOBE_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15 15 0 0 1 0 20 15 15 0 0 1 0-20z"/></svg>';
    const HISTORY_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 1 0 2.64-6.36L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/></svg>';
    // Guards against a second POST /api/generate while one is in flight.
    // Disabling the submit button alone wasn't enough: regenerateProject()
    // runs from the project-detail page, which had no #generate-submit-btn, so
    // the lookup was null and two quick clicks fired two requests. The server
    // couldn't catch it either, because job status is null during container
    // cold-start. Two containers for one repo means the first bills untracked.
    // Reset on every route change and whenever a build reaches a terminal
    // state, or the guard would outlive the submit and disable Retry.
    let startInFlight = false;

    const ARROW_ICON = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14"/><path d="m13 6 6 6-6 6"/></svg>';
    const PLUS_ICON = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14"/><path d="M5 12h14"/></svg>';
    const SEARCH_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.2-3.2"/></svg>';
    const STAR_ICON = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="m12 2 2.9 6.6 7.1.6-5.4 4.7 1.7 7-6.3-3.9-6.3 3.9 1.7-7L2 9.2l7.1-.6z"/></svg>';
    const CHEVRON_ICON = '<svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';
    const LOCK_ICON = '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>';
    const EYE_ICON = '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>';
    const EXTERNAL_ICON = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 17 17 7"/><path d="M8 7h9v9"/></svg>';
    const ALERT_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 8v4.5"/><path d="M12 16h.01"/></svg>';
    const CLOCK_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>';
    const BOOK_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 19.5V5a2 2 0 0 1 2-2h13v16H6.5A2.5 2.5 0 0 0 4 21.5v-2z"/><path d="M8 7h7"/><path d="M8 11h5"/></svg>';

    // A docs page drawn in outline: top bar, sidebar, title, paragraphs, a
    // code block, an on-this-page column. Sits under every screenshot so a
    // slow or cold thumbnail reads as a page loading, not an empty box; also
    // the backdrop of the detail page's no-preview state. currentColor plus
    // opacities, so it follows the theme with no colours of its own.
    const WIRE_SVG = '<svg viewBox="0 0 320 180" preserveAspectRatio="xMidYMin slice" fill="currentColor" aria-hidden="true">'
      + '<rect width="320" height="16" opacity="0.04"/>'
      + '<rect x="10" y="5.5" width="26" height="5" rx="2.5" opacity="0.14"/>'
      + '<rect x="230" y="4.5" width="64" height="7" rx="3.5" opacity="0.07"/>'
      + '<rect y="16" width="64" height="164" opacity="0.025"/>'
      + '<rect x="10" y="27" width="34" height="3.5" rx="1.75" opacity="0.13"/>'
      + '<rect x="10" y="37" width="42" height="3.5" rx="1.75" opacity="0.08"/>'
      + '<rect x="10" y="47" width="30" height="3.5" rx="1.75" opacity="0.08"/>'
      + '<rect x="10" y="57" width="38" height="3.5" rx="1.75" opacity="0.08"/>'
      + '<rect x="10" y="73" width="28" height="3.5" rx="1.75" opacity="0.13"/>'
      + '<rect x="10" y="83" width="40" height="3.5" rx="1.75" opacity="0.08"/>'
      + '<rect x="10" y="93" width="33" height="3.5" rx="1.75" opacity="0.08"/>'
      + '<rect x="84" y="30" width="112" height="9" rx="3" opacity="0.16"/>'
      + '<rect x="84" y="48" width="150" height="3.5" rx="1.75" opacity="0.08"/>'
      + '<rect x="84" y="56" width="138" height="3.5" rx="1.75" opacity="0.08"/>'
      + '<rect x="84" y="64" width="96" height="3.5" rx="1.75" opacity="0.08"/>'
      + '<rect x="84" y="78" width="150" height="40" rx="4" opacity="0.045"/>'
      + '<rect x="92" y="87" width="70" height="3" rx="1.5" opacity="0.1"/>'
      + '<rect x="92" y="95" width="98" height="3" rx="1.5" opacity="0.1"/>'
      + '<rect x="92" y="103" width="54" height="3" rx="1.5" opacity="0.1"/>'
      + '<rect x="84" y="130" width="146" height="3.5" rx="1.75" opacity="0.08"/>'
      + '<rect x="84" y="138" width="120" height="3.5" rx="1.75" opacity="0.08"/>'
      + '<rect x="256" y="30" width="40" height="3.5" rx="1.75" opacity="0.1"/>'
      + '<rect x="256" y="40" width="32" height="3" rx="1.5" opacity="0.06"/>'
      + '<rect x="256" y="48" width="36" height="3" rx="1.5" opacity="0.06"/>'
      + '<rect x="256" y="56" width="28" height="3" rx="1.5" opacity="0.06"/>'
      + '</svg>';

    // GitHub's own colour for each language — a small dot beside the name
    // gives a grid of repositories real colour without any of it being the
    // accent. Unknown languages fall back to the faint ink.
    const LANG_COLORS = {
      'Python': '#3572A5', 'JavaScript': '#F1E05A', 'TypeScript': '#3178C6', 'Go': '#00ADD8', 'PHP': '#4F5D95',
      'Vue': '#41B883', 'Rust': '#DEA584', 'Java': '#B07219', 'Ruby': '#701516', 'C++': '#F34B7D', 'C': '#555555',
      'C#': '#178600', 'Shell': '#89E051', 'HTML': '#E34C26', 'CSS': '#663399', 'SCSS': '#C6538C', 'Swift': '#F05138',
      'Kotlin': '#A97BFF', 'Dart': '#00B4AB', 'Astro': '#FF5A03', 'Svelte': '#FF3E00', 'Elixir': '#6E4A7E',
      'Scala': '#C22D40', 'Lua': '#000080', 'HCL': '#844FBA', 'Jupyter Notebook': '#DA5B0B', 'MDX': '#FCB32C',
      'Objective-C': '#438EFF', 'Haskell': '#5E5086', 'Clojure': '#DB5855', 'Zig': '#EC915C', 'Nix': '#7E7EFF',
      'Dockerfile': '#384D54', 'Makefile': '#427819', 'Perl': '#0298C3', 'R': '#198CE7', 'Julia': '#A270BA',
    };
    function langHtml(lang, cls) {
      if (!lang) return '';
      const color = Object.prototype.hasOwnProperty.call(LANG_COLORS, lang) ? LANG_COLORS[lang] : '';
      return '<span class="lang' + (cls ? ' ' + cls : '') + '"><span class="lang-dot"'
        + (color ? ' style="--lang:' + color + '"' : '') + '></span>' + escapeHtml(lang) + '</span>';
    }

    // Owner avatars come from GitHub metadata that is mostly fetched
    // server-side, but a project row can fall back to a client-supplied value,
    // and the gallery is public. Only GitHub's own avatar host is rendered;
    // anything else becomes a monogram, so no row can make every visitor's
    // browser fetch an arbitrary URL.
    function safeAvatar(url) {
      const s = String(url || '');
      return s.indexOf('https://avatars.githubusercontent.com/') === 0 ? s : '';
    }
    function avatarHtml(url, owner) {
      const safe = safeAvatar(url);
      if (safe) return '<img class="av" src="' + escapeHtml(safe) + '" alt="" loading="lazy" decoding="async" />';
      return '<span class="av av-fallback" aria-hidden="true">' + escapeHtml(String(owner || '?').charAt(0)) + '</span>';
    }

    // "1.2k" style compaction for star counts — the raw integer reads as
    // noise once a repo clears four digits.
    function formatCount(n) {
      if (n == null) return '';
      return n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n);
    }

    const STAGES = ['cloning', 'generating', 'building'];
    const STAGE_LABEL = { cloning: 'Cloning repository', generating: 'Generating documentation', building: 'Building your site' };

    // Everything below builds markup with innerHTML, so any value that came
    // from GitHub (repo descriptions) or from the backend (error strings) has
    // to go through here first.
    function escapeHtml(v) {
      return String(v == null ? '' : v)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    // Rendered whenever a fetch we depend on fails. Without one of these the
    // affected view just sits on its loading text forever.
    function errorBoxHtml(message, retryFn) {
      return \`
        <div class="empty-state">
          <div class="empty-icon">\${ALERT_ICON}</div>
          <h2>Something went wrong</h2>
          <p>\${escapeHtml(message)}</p>
          \${retryFn ? \`<button class="btn" onclick="\${retryFn}">Try again</button>\` : ''}
        </div>\`;
    }

    async function main() {
      // If this throws unguarded the page stays permanently blank — the three
      // body slots ship empty and nothing else ever writes to them.
      try {
        const res = await fetch('/api/me');
        if (!res.ok) throw new Error('me ' + res.status);
        state.me = await res.json();
        state.paused = !!(state.me && state.me.generationPaused);
        renderNotice();
      } catch (err) {
        document.getElementById('content').innerHTML =
          errorBoxHtml("Couldn't reach the server. Check your connection and try again.", 'location.reload()');
        return;
      }
      if (!state.me || !state.me.authenticated) {
        // The server only serves this SPA shell to a logged-out visitor at
        // /{owner}/{repo}/ when that job is genuinely still in progress (a
        // finished/public site is served directly from R2 before this code
        // ever runs, and a done/failed job with no site shows a separate
        // static stalePageHtml() page, not this shell) — so unconditionally
        // dropping every logged-out visitor into the gallery here, ignoring
        // the URL entirely, meant visiting a specific repo mid-generation
        // (or a gallery card's own iframe preview loading that same URL)
        // showed the full gallery recursively instead of that repo's state.
        const pathMatch = window.location.pathname.match(/^\\/([\\w.-]+)\\/([\\w.-]+)\\/?$/);
        if (pathMatch) {
          renderPublicInProgress(pathMatch[1], pathMatch[2]);
        } else {
          renderLoggedOut();
        }
        return;
      }
      await refreshProjects();

      const pathMatch = window.location.pathname.match(/^\\/([\\w.-]+)\\/([\\w.-]+)\\/?$/);
      if (pathMatch) {
        const [, owner, repo] = pathMatch;
        const inFlight = state.projects.find(
          p => p.owner.toLowerCase() === owner.toLowerCase() && p.repo.toLowerCase() === repo.toLowerCase()
            && p.status !== 'done' && p.status !== 'failed'
        );
        if (inFlight) {
          renderGenerating({
            owner: inFlight.owner, repo: inFlight.repo,
            description: inFlight.description, language: inFlight.language,
            avatarUrl: inFlight.avatarUrl || state.me.avatarUrl,
            createdAt: inFlight.createdAt,
          });
          poll(inFlight.jobId, inFlight.owner, inFlight.repo);
          return;
        }
      }
      route();
    }

    function route() {
      // Any navigation means no submit is in flight any more. Without this the
      // guard set by startJob() stays true for the rest of the page's life, so
      // Retry after a failed build and the Generate button after "Back to
      // generate" would both silently do nothing.
      startInFlight = false;
      renderAppBar();
      const path = window.location.pathname;
      const projMatch = path.match(/^\\/projects\\/([\\w.-]+)\\/([\\w.-]+)\\/?$/);
      if (projMatch) return renderProjectDetail(projMatch[1], projMatch[2]);
      if (path === '/projects') return renderProjects();
      if (path === '/generate') return renderGenerate();
      // Any other path (typically '/', including the bare domain) — land on
      // the sensible default: your projects if you have any, otherwise the
      // generate flow. Rewrite the URL so the address bar matches the view.
      //
      // If the projects load *failed* we cannot tell "no projects" from "we
      // don't know", and silently dropping someone into /generate is how this
      // reads as "my projects were deleted". Show the error instead.
      if (state.projectsError) {
        history.replaceState({}, '', '/projects');
        return renderProjects();
      }
      const target = state.projects.length ? '/projects' : '/generate';
      history.replaceState({}, '', target);
      return target === '/projects' ? renderProjects() : renderGenerate();
    }
    function nav(e, path) { if (e) e.preventDefault(); closeDropdown(); history.pushState({}, '', path); route(); return false; }
    window.addEventListener('popstate', () => { if (state.me && state.me.authenticated) route(); });

    // ── App bar + profile dropdown (identity + nav links only) ───────
    // One calm notice, on every screen, whenever new generations are paused.
    // String concatenation on purpose: this whole script lives in a TS template
    // literal, so no backticks or dollar-brace sequences may appear here.
    function renderNotice() {
      const slot = document.getElementById('notice-slot');
      if (!slot) return;
      if (!state.paused) { slot.innerHTML = ''; return; }
      slot.innerHTML = '<div class="notice" role="status"><span class="notice-dot"></span><div>'
        + '<strong>New generations are paused for now</strong>'
        + '<span>We are making DeepDoc smoother and faster. Docs that already exist stay available, and generation will be back soon.</span>'
        + '</div></div>';
    }

    function renderAppBar() {
      const slot = document.getElementById('appbar-slot');
      if (!state.me || !state.me.authenticated) { slot.innerHTML = ''; return; }
      slot.innerHTML = \`
        <header class="appbar">
          <div class="appbar-inner">
            <a class="brand" href="/" onclick="return nav(event,'/')">\${brandMarkHtml()}</a>
            <div class="bar-tools">
              <a class="bar-link" href="https://deepdoc.tech/docs" target="_blank" rel="noopener">Docs</a>
              \${themeToggleHtml()}
              <div class="account-wrap">
                <button class="account-chip" aria-haspopup="menu" aria-expanded="\${state.ddOpen ? 'true' : 'false'}"
                        onclick="event.stopPropagation(); toggleDropdown()">
                  <img src="\${escapeHtml(safeAvatar(state.me.avatarUrl))}" alt="" /><span>\${escapeHtml(state.me.login || '')}</span>\${CHEVRON_ICON}
                </button>
                <div id="profile-dd"></div>
              </div>
            </div>
          </div>
        </header>\`;
      if (state.ddOpen) renderDropdown();
    }

    function renderDropdown() {
      const q = state.quota || {};
      const projCount = state.projects.length;
      document.getElementById('profile-dd').innerHTML = \`
        <div class="profile-dd" role="menu" onclick="event.stopPropagation()">
          <div class="profile-dd-head">
            <img src="\${escapeHtml(safeAvatar(state.me.avatarUrl))}" alt="" />
            <div>
              <div class="nm">\${escapeHtml(state.me.login || '')}</div>
              <div class="qt">\${q.unlimited ? 'Unlimited projects' : (q.savedProjects ?? 0) + ' of ' + (q.maxSavedProjects ?? '?') + ' saved'}</div>
            </div>
          </div>
          <a class="profile-dd-link" role="menuitem" href="/projects" onclick="nav(event,'/projects')"><span>Projects</span><span class="count">\${projCount}</span></a>
          <a class="profile-dd-link" role="menuitem" href="/generate" onclick="nav(event,'/generate')"><span>New docs site</span></a>
          <div class="profile-dd-sep"></div>
          <button class="profile-dd-link" role="menuitem" onclick="logout()">Log out</button>
        </div>\`;
    }
    function syncChipExpanded() {
      const chip = document.querySelector('.account-chip');
      if (chip) chip.setAttribute('aria-expanded', state.ddOpen ? 'true' : 'false');
    }
    function toggleDropdown() {
      state.ddOpen = !state.ddOpen;
      if (state.ddOpen) { renderDropdown(); document.addEventListener('click', closeDropdownOnce); document.addEventListener('keydown', closeDropdownOnEscape); }
      else closeDropdown();
      syncChipExpanded();
    }
    function closeDropdown() {
      state.ddOpen = false;
      const el = document.getElementById('profile-dd');
      if (el) el.innerHTML = '';
      syncChipExpanded();
      document.removeEventListener('click', closeDropdownOnce);
      document.removeEventListener('keydown', closeDropdownOnEscape);
    }
    function closeDropdownOnce() { closeDropdown(); }
    function closeDropdownOnEscape(e) { if (e.key === 'Escape') closeDropdown(); }

    // Theme toggle — same sun/moon affordance as deepdoc.tech's Header.astro.
    // Writes the shared dd_theme cookie so the choice follows the visitor back
    // to the marketing site, and vice versa. No localStorage here: the cookie
    // is the cross-subdomain channel and the server already reads it, so
    // there's nothing to rehydrate on the client.
    const SUN_ICON = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M2 12h2M20 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>';
    const MOON_ICON = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';

    function currentTheme() {
      return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
    }
    function thumbUrlFor(owner, repo, createdAt, theme) {
      return '/api/thumb/' + encodeURIComponent(owner) + '/' + encodeURIComponent(repo)
        + '?v=' + encodeURIComponent(String(createdAt || 0)) + '&t=' + theme;
    }
    // Swap every gallery thumbnail to the other theme's variant in place. The
    // screenshots are of real docs sites, which have their own light and dark
    // renderings — showing a blazing white preview inside a dark gallery was
    // the thing that looked wrong. data-owner/-repo/-created carry what the
    // URL needs so this doesn't have to re-fetch /api/examples.
    function retintGalleryThumbs(theme) {
      document.querySelectorAll('.gallery-shot[data-owner]').forEach((img) => {
        img.src = thumbUrlFor(img.dataset.owner, img.dataset.repo, img.dataset.created, theme);
      });
    }
    function themeToggleHtml() {
      const isLight = currentTheme() === 'light';
      return \`<button class="theme-toggle" type="button" onclick="toggleTheme()"
        aria-label="Switch to \${isLight ? 'dark' : 'light'} mode">\${isLight ? MOON_ICON : SUN_ICON}</button>\`;
    }
    function toggleTheme() {
      const next = currentTheme() === 'light' ? 'dark' : 'light';
      document.documentElement.setAttribute('data-theme', next);
      document.cookie = 'dd_theme=' + next + ';path=/;max-age=31536000;samesite=lax'
        + (location.hostname.endsWith('deepdoc.tech') ? ';domain=.deepdoc.tech;secure' : '');
      // Re-render just the bar so the icon flips; everything else is CSS vars.
      if (state.me && state.me.authenticated) renderAppBar();
      else {
        const btn = document.querySelector('.theme-toggle');
        if (btn) btn.outerHTML = themeToggleHtml();
      }
      // Screenshots aren't CSS — they need the other variant fetched.
      retintGalleryThumbs(next);
    }

    // Brand mark — duplicated from web/src/components/Logo.astro (the Worker
    // can't import an Astro component) so both domains read as one product.
    function brandMarkHtml() {
      return \`<svg class="dd-mark" viewBox="0 0 48 48" fill="none" aria-hidden="true">
          <path class="dd-echo dd-echo-2" d="M14 9 H24 A15 15 0 0 1 24 39 H14" transform="translate(6 6)"></path>
          <path class="dd-echo dd-echo-1" d="M14 9 H24 A15 15 0 0 1 24 39 H14" transform="translate(3 3)"></path>
          <path class="dd-front" fill-rule="evenodd" d="M14 9 H24 A15 15 0 0 1 24 39 H14 Z M20 15 H24 A9 9 0 0 1 24 33 H20 Z"></path>
        </svg>eepDoc\`;
    }

    // ── Public gallery (unauthenticated root) — show real generated docs
    // before ever asking for GitHub access, for people skeptical about
    // signing in cold. deepdoc.tech's "Try the Demo" CTA sends people
    // straight here now (see index.astro) instead of opening its own
    // sign-in modal. The modal only appears once someone actually clicks
    // "New docs site" — see renderPublicGallery below.
    async function renderLoggedOut() {
      document.body.dataset.view = 'wide';
      document.getElementById('appbar-slot').innerHTML = \`
        <header class="appbar"><div class="appbar-inner">
          <a class="brand" href="https://deepdoc.tech" aria-label="DeepDoc home">\${brandMarkHtml()}</a>
          <div class="bar-tools">
            <a class="bar-link" href="https://deepdoc.tech/docs" target="_blank" rel="noopener">Docs</a>
            \${themeToggleHtml()}
            <button class="btn small" onclick="openSignInFromGallery()">New docs site</button>
          </div>
        </div></header>\`;
      document.getElementById('modal-slot').innerHTML = '';
      const data = await fetch('/api/examples').then(r => r.json()).catch(() => ({ examples: [] }));
      renderPublicGallery(data.examples || []);
    }

    // A logged-out visitor hitting /{owner}/{repo}/ directly while that
    // job is still running (or embedded as a gallery card's own iframe
    // preview) — no sign-in needed to see this, the repo is already public.
    // No live polling here on purpose: an unauthenticated visitor has no
    // job_id to poll (there's no public status-by-repo endpoint), so this
    // is a static message with a manual refresh rather than new plumbing
    // for what's a fairly rare thing to land on directly.
    function renderPublicInProgress(owner, repo) {
      document.body.dataset.view = 'wide';
      document.getElementById('appbar-slot').innerHTML = \`
        <header class="appbar"><div class="appbar-inner">
          <a class="brand" href="/" aria-label="DeepDoc Cloud">\${brandMarkHtml()}</a>
          <div class="bar-tools">
            <a class="bar-link" href="https://deepdoc.tech/docs" target="_blank" rel="noopener">Docs</a>
            \${themeToggleHtml()}
            <button class="btn small secondary" onclick="location.href='/'">See all examples</button>
          </div>
        </div></header>\`;
      document.getElementById('modal-slot').innerHTML = '';
      document.getElementById('content').innerHTML = \`
        <div class="page">
          <div class="empty-state" style="padding-top:112px;">
            <div class="empty-icon is-live">\${CLOCK_ICON}</div>
            <h2>\${escapeHtml(owner)}/\${escapeHtml(repo)} is still being generated</h2>
            <p>Larger repositories can take a few minutes. Check back shortly.</p>
            <button class="btn" onclick="location.reload()">Refresh</button>
          </div>
        </div>\`;
    }

    function openSignInFromGallery() {
      document.getElementById('modal-slot').innerHTML = signInModalHtml('/auth/github', true);
    }

    // The one card in either grid that starts something instead of opening
    // something. Title/desc are literals from call sites, not user data.
    // withShot: in the screenshot grid the card gets a frame of its own (an
    // empty page with the plus at its centre) so it lines up with the
    // screenshot cards beside it.
    function newCardHtml(title, desc, onclickExpr, href, id, withShot) {
      if (withShot) {
        return \`
        <a class="card card-new has-shot"\${id ? ' id="' + id + '"' : ''} href="\${href}" onclick="\${onclickExpr}">
          <div class="card-shot new-shot"><div class="card-plus">\${PLUS_ICON}</div></div>
          <div class="card-body">
            <div class="card-title">\${title}</div>
            <div class="card-desc">\${desc}</div>
          </div>
          <div class="card-foot"><span class="card-go">\${ARROW_ICON}</span></div>
        </a>\`;
      }
      return \`
        <a class="card card-new"\${id ? ' id="' + id + '"' : ''} href="\${href}" onclick="\${onclickExpr}">
          <div class="card-body">
            <div class="card-plus">\${PLUS_ICON}</div>
            <div class="card-title">\${title}</div>
            <div class="card-desc">\${desc}</div>
          </div>
          <div class="card-foot"><span class="card-go">\${ARROW_ICON}</span></div>
        </a>\`;
    }

    // Carry a URL pasted before sign-in through OAuth, so the visitor doesn't
    // have to find and paste it again. renderGenerate() consumes it once.
    // Called with '' when there is no specific repo to carry (the "nothing
    // matched your search" case) — store nothing rather than an empty key.
    function startFromGallery(url) {
      try {
        if (url) localStorage.setItem('dd_pending_repo', url);
      } catch (err) {}
      openSignInFromGallery();
    }
    function consumePendingRepo() {
      let pending = null;
      try {
        pending = localStorage.getItem('dd_pending_repo');
        if (pending) localStorage.removeItem('dd_pending_repo');
      } catch (err) { return; }
      if (!pending) return;
      const el = document.getElementById('paste-url');
      if (!el) return;
      el.value = pending;
      onPasteInput();
    }

    // One field does both jobs: filter the examples, and recognise a named
    // repository — a pasted github.com link or bare "owner/repo" — as
    // "generate this one instead".
    //
    // Every outcome offers something to click. Typing a query that matched
    // nothing used to end in a flat sentence, which is the one moment we know
    // the visitor wants a repo we haven't documented — so that is exactly
    // where the offer to generate belongs.
    function setLeadCardHidden(hidden) {
      const lead = document.getElementById('gallery-lead-card');
      if (lead) lead.hidden = hidden;
    }
    function onGallerySearch(value) {
      const raw = String(value || '').trim();
      const needle = raw.toLowerCase();
      setLeadCardHidden(false);
      let shown = 0;
      document.querySelectorAll('#gallery-grid .card[data-name]').forEach((el) => {
        const match = !needle || (el.dataset.name || '').includes(needle);
        el.hidden = !match;
        if (match) shown++;
      });
      const slot = document.getElementById('ask-slot');
      if (!slot) return;
      const parsed = parseRepoRef(raw);
      if (parsed) {
        const name = parsed.owner + '/' + parsed.repo;
        // Hand the generate flow a canonical URL, never the raw shorthand:
        // the server's own parseGithubRepoUrl requires a real github.com URL,
        // so "owner/repo" typed here has to be expanded before it travels.
        const canonical = 'https://github.com/' + parsed.owner + '/' + parsed.repo;
        // No claim about whether this repo has already been documented: the
        // gallery only holds the most recent public sites, so "not documented
        // yet" would be a guess we never checked, and it can be wrong (the
        // repo may belong to another user's site, which surfaces as a 409).
        // The repo name and the button say enough.
        slot.innerHTML = \`
          <div class="ask-hit">
            <div class="ask-hit-text">
              <span>\${escapeHtml(name)}</span>
            </div>
            <button class="btn small" onclick="startFromGallery('\${escapeHtml(canonical)}')">Generate docs</button>
          </div>\`;
      } else if (needle && shown === 0) {
        // Free text, nothing matched. There is no repo to prefill, so send
        // them to the generate flow to name one themselves. The lead card
        // makes the same offer, so hide it while this panel is up rather than
        // showing the visitor the same button twice in one glance.
        setLeadCardHidden(true);
        slot.innerHTML = \`
          <div class="ask-hit">
            <div class="ask-hit-text">
              <span>No examples match "\${escapeHtml(raw)}"</span>
              <span class="ask-hit-why">Start a new site for any repository instead.</span>
            </div>
            <button class="btn small" onclick="startFromGallery('')">New docs site</button>
          </div>\`;
      } else {
        slot.innerHTML = '';
      }
    }

    function renderPublicGallery(examples) {
      document.body.dataset.view = 'wide';
      // Description / owner / repo all come from GitHub and this grid is served
      // to unauthenticated visitors, so every one of them is escaped: a public
      // repo whose description contained markup was a stored-XSS vector, and an
      // apostrophe in the URL used to break out of the old onclick attribute.
      const cards = examples.map((e) => {
        const siteUrl = '/' + encodeURIComponent(e.owner) + '/' + encodeURIComponent(e.repo) + '/';
        const safeOwner = escapeHtml(e.owner);
        const safeRepo = escapeHtml(e.repo);
        const haystack = escapeHtml(
          (e.owner + '/' + e.repo + ' ' + (e.description || '') + ' ' + (e.language || '')).toLowerCase()
        );
        // The screenshot is decorative (the name is right beneath it), so the
        // alt is empty. It fades in over the wireframe once it has loaded,
        // and if it fails the wireframe simply stays.
        const shot = thumbUrlFor(e.owner, e.repo, e.createdAt, currentTheme());
        return \`
        <a class="card has-shot" href="\${escapeHtml(siteUrl)}" data-name="\${haystack}">
          <div class="card-shot">
            <div class="shot-wire">\${WIRE_SVG}</div>
            <img class="gallery-shot" src="\${escapeHtml(shot)}" alt="" width="1280" height="800" loading="lazy" decoding="async"
                 data-owner="\${safeOwner}" data-repo="\${safeRepo}" data-created="\${escapeHtml(String(e.createdAt || 0))}"
                 onload="this.classList.add('is-in')" onerror="this.remove()" />
          </div>
          <div class="card-body">
            <div class="card-id">\${avatarHtml(e.avatarUrl, e.owner)}<div class="card-title"><span class="g-owner">\${safeOwner}/</span>\${safeRepo}</div></div>
            \${e.description ? '<div class="card-desc">' + escapeHtml(e.description) + '</div>' : ''}
          </div>
          <!-- Language and stars only. The generation date was a third metric
               that told a visitor nothing about the repository they are
               choosing between. -->
          <div class="card-foot">
            \${langHtml(e.language, 'card-metric')}
            \${e.stars != null ? '<span class="card-metric star">' + STAR_ICON + formatCount(e.stars) + '</span>' : ''}
            <span class="card-go">\${ARROW_ICON}</span>
          </div>
        </a>\`;
      }).join('');
      const n = examples.length;
      document.getElementById('content').innerHTML = \`
        <div class="page">
          <div class="ask">
            <div class="ask-eyebrow"><span class="live" aria-hidden="true"></span>\${n ? n + ' public docs ' + (n === 1 ? 'site' : 'sites') + ', generated from source' : 'Docs generated from source'}</div>
            <h1>Which repository would you like documented?</h1>
            <p class="ask-lede">Every site below was written by DeepDoc from a real GitHub repository. Open one to see what you get, or paste a link to make your own.</p>
            <div class="ask-field">
              \${SEARCH_ICON}
              <input id="gallery-search" placeholder="Search repositories, or paste a GitHub link"
                     aria-label="Search the examples, or paste a GitHub repository link"
                     oninput="onGallerySearch(this.value)" />
              <span class="kbd" aria-hidden="true">/</span>
            </div>
            <div id="ask-slot">\${examples.length ? '' :
              '<p class="ask-note">Nothing has been shared publicly yet. Be the first.</p>'}</div>
          </div>
          \${n ? '<div class="section-head"><h2>Recently generated</h2><span>Public sites, newest first</span></div>' : ''}
          <div class="card-grid" id="gallery-grid">
            \${newCardHtml('New docs site', 'Point DeepDoc at any public GitHub repository.',
                          'openSignInFromGallery(); return false;', '#', 'gallery-lead-card', true)}
            \${cards}
          </div>
          <footer class="cloud-footer">
            <a class="brand" href="https://deepdoc.tech" aria-label="DeepDoc home">\${brandMarkHtml()}</a>
            <nav class="cloud-footer-links">
              <a href="https://deepdoc.tech">Home</a>
              <a href="https://deepdoc.tech/docs">Docs</a>
              <a href="https://github.com/Pranav322/deepdoc" target="_blank" rel="noreferrer">GitHub</a>
              <a href="https://pypi.org/project/deepdoc/" target="_blank" rel="noreferrer">PyPI</a>
            </nav>
          </footer>
        </div>\`;
      bindSlashToSearch();
    }

    // "/" jumps to the gallery's search field, the convention every docs site
    // and code host uses. Bound once; it no-ops on screens without the field
    // and never steals the key from something you are typing into.
    let slashBound = false;
    function bindSlashToSearch() {
      if (slashBound) return;
      slashBound = true;
      document.addEventListener('keydown', (e) => {
        if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return;
        const t = e.target;
        const tag = t && t.tagName ? t.tagName.toLowerCase() : '';
        if (tag === 'input' || tag === 'textarea' || (t && t.isContentEditable)) return;
        const field = document.getElementById('gallery-search');
        if (!field) return;
        e.preventDefault();
        field.focus();
      });
    }

    // Shared between the auto-popup here and (in spirit — index.astro keeps
    // its own copy since it's a separate rendering system) the marketing
    // site's "Try now" trigger. dismissible is false here — there's
    // nothing else to do on this domain unauthenticated — but kept
    // parameterized in case that changes.
    function signInModalHtml(authHref, dismissible) {
      return \`
        <div class="modal-veil" \${dismissible ? "onclick=\\"if(event.target===this) this.remove()\\"" : ''}>
          <div class="modal" role="dialog" aria-modal="true" aria-labelledby="signin-title">
            <div class="modal-icon-wrap">
              <div class="modal-dot-grid"></div>
              <div class="modal-icon-badge">\${GITHUB_ICON_SVG}</div>
            </div>
            <h1 id="signin-title">Sign in with GitHub</h1>
            <p class="modal-sub">DeepDoc needs read access to clone the repository you pick and generate its documentation. That is all it is used for.</p>
            <!-- The allowance is stated here rather than discovered as a 400
                 on someone's third repository. Numbers come from
                 session.ts's own constants, so the copy can't drift from the
                 limit the server actually enforces. -->
            <p class="modal-sub modal-quota">Free accounts include ${MAX_SAVED_PROJECTS} documentation sites, and ${MAX_STARTS_PER_DAY} builds a day.</p>
            <div class="modal-features">
              <div class="modal-feature">
                <div class="modal-feature-icon">\${SHIELD_CHECK_ICON}</div>
                <div>
                  <p class="modal-feature-title">Nothing is posted or changed</p>
                  <p class="modal-feature-desc">We view your code, we don't modify it.</p>
                </div>
              </div>
              <div class="modal-feature">
                <div class="modal-feature-icon">\${GLOBE_ICON}</div>
                <div>
                  <p class="modal-feature-title">Generated sites are private by default</p>
                  <p class="modal-feature-desc">You choose if to make one public.</p>
                </div>
              </div>
              <div class="modal-feature">
                <div class="modal-feature-icon">\${HISTORY_ICON}</div>
                <div>
                  <p class="modal-feature-title">You're in control</p>
                  <p class="modal-feature-desc">You can revoke access from GitHub at any time.</p>
                </div>
              </div>
            </div>
            <button class="btn full large" onclick="startGithubAuth(this,'\${authHref}')">\${GITHUB_ICON_SVG}Continue with GitHub</button>
          </div>
        </div>\`;
    }

    // GitHub OAuth is a real page navigation, so there's no "restore" path —
    // the loading state just shows until the browser unloads for /auth/github.
    function startGithubAuth(btn, authHref) {
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="btn-spinner"></span>Redirecting…';
      }
      location.href = authHref;
    }

    async function logout() {
      await fetch('/api/logout', { method: 'POST' });
      window.location.href = '/';
    }

    // Returns false when the load failed so callers can avoid rendering a
    // misleading "No projects yet" over what is really a network error.
    async function refreshProjects() {
      try {
        const res = await fetch('/api/projects');
        if (!res.ok) throw new Error('projects ' + res.status);
        const data = await res.json();
        state.projects = Array.isArray(data.projects) ? data.projects : [];
        state.quota = data.quota || null;
        state.projectsError = false;
        return true;
      } catch (err) {
        state.projects = [];
        state.quota = null;
        state.projectsError = true;
        return false;
      }
    }

    async function reloadProjects() {
      await refreshProjects();
      route();
    }

    // ── /projects — click-through list, no per-row buttons ───────────
    function renderProjects() {
      document.body.dataset.view = 'wide';
      const q = state.quota;
      const atQuota = q && q.maxSavedProjects != null && q.savedProjects >= q.maxSavedProjects;

      // A failed /api/projects used to fall through to "No projects yet",
      // telling the user their work was gone when it was a network error.
      if (state.projectsError) {
        document.getElementById('content').innerHTML = \`
          <div class="page">
            <div class="page-head"><h1 class="t-display">Projects</h1></div>
            \${errorBoxHtml("We couldn't load your projects. They are still there; this is a connection problem.", 'reloadProjects()')}
          </div>\`;
        return;
      }

      // No thumbnails here, deliberately: on your own list the name and the
      // build state are what you scan for, and a wall of screenshots of sites
      // you already know is noise. The public gallery is the opposite case,
      // where the screenshot IS the pitch.
      const cards = state.projects.map(p => {
        // The owner is almost always you, so showing it on every card is noise.
        // Surface it only when it isn't, which is when it disambiguates.
        const mine = state.me && state.me.login
          && p.owner.toLowerCase() === state.me.login.toLowerCase();
        const isPublic = p.visibility === 'public';
        return \`
        <a class="card" href="/projects/\${encodeURIComponent(p.owner)}/\${encodeURIComponent(p.repo)}"
           onclick="return nav(event,'/projects/\${escapeHtml(p.owner)}/\${escapeHtml(p.repo)}')">
          <div class="card-top">
            \${statusPill(p.status)}
            <span class="card-vis">\${isPublic ? EYE_ICON + 'Public' : LOCK_ICON + 'Private'}</span>
          </div>
          <div class="card-body">
            <div class="card-title">\${mine ? '' : '<span class="g-owner">' + escapeHtml(p.owner) + '/</span>'}\${escapeHtml(p.repo)}</div>
            \${p.description ? '<div class="card-desc">' + escapeHtml(p.description) + '</div>' : ''}
          </div>
          <div class="card-foot">
            \${langHtml(p.language, 'card-metric')}
            \${p.stars != null ? '<span class="card-metric star">' + STAR_ICON + formatCount(p.stars) + '</span>' : ''}
            \${p.createdAt ? '<span class="card-metric">' + escapeHtml(shortAge(p.createdAt)) + '</span>' : ''}
            <span class="card-go">\${ARROW_ICON}</span>
          </div>
        </a>\`;
      }).join('');

      // At quota the lead card states why rather than offering an action that
      // would only be refused on arrival.
      const lead = atQuota
        ? \`<div class="card card-new is-blocked">
             <div class="card-body">
               <div class="card-plus">\${PLUS_ICON}</div>
               <div class="card-title">At your project limit</div>
               <div class="card-desc">Delete one of the projects here to free a slot.</div>
             </div>
             <div class="card-foot">
               <span class="card-metric">\${q.savedProjects} of \${q.maxSavedProjects} used</span>
             </div>
           </div>\`
        : newCardHtml('New docs site', 'Point DeepDoc at one of your repositories.',
                      "return nav(event,'/generate')", '/generate');

      const n = state.projects.length;
      // The allowance as a meter beside the title, so "how many more can I
      // make" is answered before anyone reaches the limit card.
      const hasCap = q && !q.unlimited && q.maxSavedProjects != null;
      const used = hasCap ? Math.min(q.savedProjects || 0, q.maxSavedProjects) : 0;
      const pct = hasCap && q.maxSavedProjects > 0 ? Math.round((used / q.maxSavedProjects) * 100) : 0;
      const quotaHtml = hasCap
        ? \`<div class="quota\${atQuota ? ' is-full' : ''}" role="img" aria-label="\${used} of \${q.maxSavedProjects} sites used">
             <div class="quota-row"><span>Sites</span><span><strong>\${used}</strong> of \${q.maxSavedProjects}</span></div>
             <div class="quota-bar"><span style="width:\${pct}%"></span></div>
           </div>\`
        : '';
      document.getElementById('content').innerHTML = \`
        <div class="page">
          <div class="page-head">
            <div>
              <h1 class="t-display">Projects</h1>
              <p class="t-sub">\${n
                ? n + ' documentation ' + (n === 1 ? 'site' : 'sites') + ' generated from your repositories.'
                : 'Nothing generated yet. Start with the card below.'}</p>
            </div>
            \${quotaHtml}
          </div>
          <div class="card-grid">\${lead}\${cards}</div>
        </div>\`;
    }

    // One owner for status -> label/class, so the list, the detail page and any
    // future surface can't disagree about what "building" looks like.
    const STATUS_META = {
      done:       { label: 'Ready',    cls: 'done' },
      failed:     { label: 'Failed',   cls: 'failed' },
      queued:     { label: 'Queued',   cls: 'building' },
      cloning:    { label: 'Cloning',  cls: 'building' },
      generating: { label: 'Generating', cls: 'building' },
      building:   { label: 'Building', cls: 'building' },
    };
    function statusPill(status) {
      const m = STATUS_META[status] || { label: status || 'unknown', cls: '' };
      return \`<span class="status-text \${m.cls}"><span class="sdot"></span>\${escapeHtml(m.label)}</span>\`;
    }
    // Terse age for the list: "3d", "now". The long form stays on the detail
    // page, where there is room for a sentence.
    function shortAge(ts) {
      const mins = Math.floor((Date.now() - ts) / 60000);
      if (mins < 2) return 'now';
      if (mins < 60) return mins + 'm';
      const hrs = Math.floor(mins / 60);
      if (hrs < 24) return hrs + 'h';
      const days = Math.floor(hrs / 24);
      if (days < 365) return days + 'd';
      return Math.floor(days / 365) + 'y';
    }


    // No footer on the signed-in screens. It was added to fill dead space,
    // which is the wrong reason — this is a tool, and empty space is allowed
    // to stay empty. The public gallery keeps its own, since that page is a
    // marketing surface and does need a way onward.

    // ── /projects/:owner/:repo — the only place project actions live ─
    function renderProjectDetail(owner, repo) {
      document.body.dataset.view = 'app';
      const p = state.projects.find(x => x.owner.toLowerCase() === owner.toLowerCase() && x.repo.toLowerCase() === repo.toLowerCase());
      // Deep-linking here used to bounce silently to /projects. If the list
      // simply failed to load that reads as "my project vanished", so say
      // which of the two actually happened.
      if (!p) {
        document.getElementById('content').innerHTML = \`
          <div class="page">
            <a class="back-link" href="/projects" onclick="return nav(event,'/projects')">← Back to projects</a>
            \${state.projectsError
              ? errorBoxHtml("Couldn't load your projects, so we can't show this one. It hasn't gone anywhere.", 'reloadProjects()')
              : \`<div class="empty-state">
                   <div class="empty-icon">\${ALERT_ICON}</div>
                   <h2>Project not found</h2>
                   <p><span class="mono">\${escapeHtml(owner + '/' + repo)}</span> is not in your projects.</p>
                   <button class="btn" onclick="nav(event,'/projects')">See your projects</button>
                 </div>\`}
          </div>\`;
        return;
      }
      const isDone = p.status === 'done';
      const createdStr = p.createdAt ? new Date(p.createdAt).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '';
      const safeOwner = escapeHtml(p.owner);
      const safeRepo = escapeHtml(p.repo);
      // The page used to be a mono h1 over two tiny labels, then whitespace —
      // nothing about the docs it had actually produced. Now that thumbnails
      // exist, show the thing the project *is*, and make it the way in.
      // The address bar shows where the site actually lives, in mono because
      // it is literally a URL — the same window frame as deepdoc.tech's hero.
      const sitePath = '/' + encodeURIComponent(p.owner) + '/' + encodeURIComponent(p.repo) + '/';
      const showShot = isDone && p.visibility === 'public';
      const winBar = \`
            <div class="win-bar">
              <span class="win-dots" aria-hidden="true"><i></i><i></i><i></i></span>
              <span class="win-url">\${LOCK_ICON}\${escapeHtml(location.host + '/' + p.owner + '/' + p.repo)}</span>
              \${showShot ? '<span class="win-open">Open' + EXTERNAL_ICON + '</span>' : '<span></span>'}
            </div>\`;
      const previewHtml = showShot
        ? \`<a class="detail-preview" href="\${sitePath}" target="_blank" rel="noreferrer">
             \${winBar}
             <div class="win-body">
               <div class="shot-wire">\${WIRE_SVG}</div>
               <img class="gallery-shot" src="\${escapeHtml(thumbUrlFor(p.owner, p.repo, p.createdAt, currentTheme()))}"
                    alt="Preview of the documentation generated for \${escapeHtml(p.owner + '/' + p.repo)}"
                    data-owner="\${safeOwner}" data-repo="\${safeRepo}" data-created="\${escapeHtml(String(p.createdAt || 0))}"
                    width="1280" height="800" loading="eager" decoding="async" onerror="this.remove()" />
             </div>
           </a>\`
        : \`<div class="detail-preview is-empty">
             \${winBar}
             <div class="win-body">
               <div class="shot-wire">\${WIRE_SVG}</div>
               \${isDone
                 ? '<p>This site is private, so there is no shared preview. Open it to view.</p>'
                 : p.status === 'failed'
                   ? '<p>The last build failed, so there is nothing to preview yet.</p>'
                   : '<p>Building. The preview appears once this finishes.</p>'}
             </div>
           </div>\`;
      document.getElementById('content').innerHTML = \`
        <div class="page">
          <a class="back-link" href="/projects" onclick="return nav(event,'/projects')">← Back to projects</a>
          <div id="detail-error-slot"></div>
          <div class="proj-head">
            <div class="proj-id">
              \${avatarHtml(p.avatarUrl, p.owner)}
              <div class="title-block">
                <h1><span class="g-owner">\${safeOwner}/</span>\${safeRepo}</h1>
                <div class="proj-meta-row">
                  \${statusPill(p.status)}
                  \${p.language ? langHtml(p.language) : ''}
                  \${p.stars != null ? '<span class="lang">' + STAR_ICON.replace('<svg ', '<svg width="12" height="12" ') + formatCount(p.stars) + '</span>' : ''}
                  \${createdStr ? '<span class="meta-sep" aria-hidden="true"></span><span>' + escapeHtml(createdStr) + '</span>' : ''}
                </div>
              </div>
            </div>
            <div class="proj-actions">
              <button id="regenerate-btn" class="btn secondary" onclick="regenerateProject('\${safeOwner}','\${safeRepo}')">Regenerate</button>
              <button class="btn" \${isDone ? '' : 'disabled'} onclick="window.open('\${sitePath}', '_blank')">Visit site\${EXTERNAL_ICON}</button>
            </div>
          </div>

          \${previewHtml}

          <!-- Two labelled sections, a redundant "who can see this", an
               explanatory sentence and a boxed danger zone were four pieces of
               chrome around two controls. The pills state their own meaning. -->
          <div class="detail-actions">
            <div class="vis-group" role="group" aria-label="Site visibility">
              <button type="button" class="vis-pill \${p.visibility !== 'public' ? 'active' : ''}" aria-pressed="\${p.visibility !== 'public'}" onclick="setProjectVisibility('\${safeOwner}','\${safeRepo}','private')">\${LOCK_ICON}Private</button>
              <button type="button" class="vis-pill \${p.visibility === 'public' ? 'active' : ''}" aria-pressed="\${p.visibility === 'public'}" onclick="setProjectVisibility('\${safeOwner}','\${safeRepo}','public')">\${EYE_ICON}Public</button>
            </div>
            <div id="danger-slot">\${dangerBoxHtml(p.owner, p.repo)}</div>
          </div>
          <div id="error-slot"></div>
        </div>\`;
    }

    function regenerateProject(owner, repo) {
      const p = state.projects.find(x => x.owner.toLowerCase() === owner.toLowerCase() && x.repo.toLowerCase() === repo.toLowerCase());
      startJob({
        owner, repo,
        description: p?.description, language: p?.language, avatarUrl: p?.avatarUrl,
        visibility: p?.visibility || 'private',
      });
    }

    // A plain destructive link rather than a bordered "danger zone" panel with
    // a heading and a caption. The two-step confirm is what actually prevents
    // the accident; the box was decoration around it.
    function dangerBoxHtml(owner, repo) {
      return \`<button class="link-danger" onclick="confirmDeleteStep('\${owner}','\${repo}')">Delete project</button>\`;
    }
    function confirmDeleteStep(owner, repo) {
      document.getElementById('danger-slot').innerHTML = \`
        <div class="danger-confirm">
          <span>Delete permanently?</span>
          <button class="link-quiet" onclick="document.getElementById('danger-slot').innerHTML=dangerBoxHtml('\${owner}','\${repo}')">Cancel</button>
          <button class="link-danger" onclick="deleteProject('\${owner}','\${repo}')">Delete</button>
        </div>\`;
    }

    // Surfaces a failure inline on the detail page instead of silently
    // pretending the mutation worked.
    function showDetailError(message) {
      const slot = document.getElementById('detail-error-slot');
      if (slot) slot.innerHTML = \`<div class="error-box">\${escapeHtml(message)}</div>\`;
    }

    async function setProjectVisibility(owner, repo, visibility) {
      try {
        const res = await fetch('/api/projects/' + owner + '/' + repo + '/visibility', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ visibility }),
        });
        // Previously unchecked — a rejected change still re-rendered with the
        // new pill selected, so the UI disagreed with the server.
        if (!res.ok) throw new Error('visibility ' + res.status);
      } catch (err) {
        showDetailError("Couldn't change visibility. Nothing was saved — try again.");
        return;
      }
      await refreshProjects();
      renderProjectDetail(owner, repo);
    }

    async function deleteProject(owner, repo) {
      try {
        const res = await fetch('/api/projects/' + owner + '/' + repo, { method: 'DELETE' });
        // Previously unchecked — a failed DELETE still navigated to /projects,
        // so a project that still exists looked deleted until the next reload.
        if (!res.ok) throw new Error('delete ' + res.status);
      } catch (err) {
        showDetailError("Couldn't delete this project. It's still there — try again.");
        return;
      }
      await refreshProjects();
      nav(null, '/projects');
    }

    // ── /generate — the only post-login home ─────────────────────────
    function renderGenerate() {
      document.body.dataset.view = 'app';
      state.selected = null;
      state.visibility = 'private';
      const q = state.quota;
      const atQuota = q && q.maxSavedProjects != null && q.savedProjects >= q.maxSavedProjects;

      if (atQuota) {
        document.getElementById('content').innerHTML = \`
          <div class="page">
            <div class="page-head"><h1 class="t-display">New docs site</h1></div>
            <div class="empty-state">
              <div class="empty-icon">\${BOOK_ICON}</div>
              <h2>You are at your project limit</h2>
              <p>Delete a project to free a slot, then come back here.</p>
              <button class="btn" onclick="nav(event,'/projects')">Go to projects</button>
            </div>
          </div>\`;
        return;
      }

      if (state.paused) {
        document.getElementById('content').innerHTML = \`
          <div class="page">
            <div class="page-head"><h1 class="t-display">New docs site</h1></div>
            <div class="empty-state">
              <div class="empty-icon">\${CLOCK_ICON}</div>
              <h2>Generation is paused for now</h2>
              <p>We are making DeepDoc smoother and faster, so new sites cannot be generated right now. Your existing docs are untouched. Please check back soon.</p>
              <button class="btn" onclick="nav(event,'/projects')">Go to projects</button>
            </div>
          </div>\`;
        return;
      }

      document.getElementById('content').innerHTML = \`
        <div class="page">
          <div class="page-head">
            <div>
              <h1 class="t-display">New docs site</h1>
              <p class="t-sub">Pick a repository. DeepDoc reads the source and builds a site you can share.</p>
            </div>
          </div>
          <div class="picker">
            <div class="field-search">
              \${SEARCH_ICON}
              <input id="repo-filter" placeholder="Search your repositories" aria-label="Search your repositories" oninput="filterRepos(this.value)" />
            </div>
            <div class="repo-list" id="repo-list" role="listbox" aria-label="Your repositories">\${repoSkeletonHtml()}</div>
          </div>
          <div id="confirm-slot"></div>
          <div class="divider">or paste a public repository URL</div>
          <input id="paste-url" class="mono" placeholder="https://github.com/owner/repo" aria-label="Public repository URL" oninput="onPasteInput()" />
          <div id="paste-confirm-slot"></div>
          <div id="error-slot"></div>
        </div>\`;
      loadRepos();
      // A link pasted on the public gallery before signing in.
      consumePendingRepo();
    }

    function repoSkeletonHtml() {
      let out = '';
      for (let i = 0; i < 6; i++) {
        const w = [58, 44, 66, 39, 52, 47][i];
        out += '<div style="padding:11px 12px;">'
          + '<div class="skel" style="height:11px;width:' + w + '%;"></div>'
          + '<div class="skel" style="height:9px;width:' + (w + 18) + '%;margin-top:7px;opacity:0.55;"></div>'
          + '</div>';
      }
      return out;
    }

    function visHintText(v) {
      return v === 'public'
        ? 'Anyone with the link can view the generated documentation.'
        : 'Only you can view it. You can make it public at any time.';
    }
    function visChoiceHtml() {
      return \`
        <div class="vis-row">
          <div class="vis-group" role="group" aria-label="Visibility">
            <button type="button" class="vis-pill \${state.visibility === 'private' ? 'active' : ''}" aria-pressed="\${state.visibility === 'private'}" onclick="pickVis('private')">\${LOCK_ICON}Private</button>
            <button type="button" class="vis-pill \${state.visibility === 'public' ? 'active' : ''}" aria-pressed="\${state.visibility === 'public'}" onclick="pickVis('public')">\${EYE_ICON}Public</button>
          </div>
        </div>
        <div class="vis-hint">\${visHintText(state.visibility)}</div>\`;
    }
    function pickVis(v) {
      state.visibility = v;
      if (state.selected) selectRepo(state.selected);
      else renderPasteConfirm();
    }

    async function loadRepos() {
      const list = document.getElementById('repo-list');
      try {
        const res = await fetch('/api/repos');
        if (!res.ok) throw new Error('repos ' + res.status);
        const repos = await res.json();
        // An expired GitHub token returns an error *object*, not an array.
        // Without this check repos.length is undefined, renderRepoList draws
        // nothing, and "Loading your repos…" stays on screen forever.
        if (!Array.isArray(repos)) throw new Error('repos payload not an array');
        state.repos = repos;
        renderRepoList(state.repos);
      } catch (err) {
        state.repos = [];
        if (list) {
          list.innerHTML = \`<div class="repo-empty">We couldn't load your repositories. <a onclick="loadRepos()" style="color:var(--accent);cursor:pointer;">Retry</a>, or paste a public repository URL below.</div>\`;
        }
      }
    }

    // Look up whether a repo already has a project — drives both the list
    // badge and which action the confirm panel offers (generate vs. view vs.
    // regenerate). Case-insensitive to match the backend's own comparisons.
    function findProject(owner, repo) {
      return state.projects.find(
        p => p.owner.toLowerCase() === owner.toLowerCase() && p.repo.toLowerCase() === repo.toLowerCase()
      ) || null;
    }
    function parseGithubUrlClient(url) {
      try {
        const u = new URL(url);
        if (u.hostname !== 'github.com') return null;
        const parts = u.pathname.split('/').filter(Boolean);
        if (parts.length < 2) return null;
        return { owner: parts[0], repo: parts[1].replace(/\\.git$/, '') };
      } catch { return null; }
    }
    // The gallery search field accepts what people actually type, which is as
    // often "owner/repo" as a full link. Deliberately separate from
    // parseGithubUrlClient: that one backs /generate's paste field, whose
    // value is POSTed verbatim as repo_url and must stay a real URL the
    // server's parseGithubRepoUrl will accept.
    function parseRepoRef(raw) {
      const s = String(raw || '').trim();
      if (!s) return null;
      const fromUrl = parseGithubUrlClient(s);
      if (fromUrl) return fromUrl;
      // GitHub allows letters, digits, dot, dash and underscore in both an
      // owner and a repo name, and nothing else — so this rejects free-text
      // queries that merely contain a slash.
      const m = s.match(/^([\\w.-]+)\\/([\\w.-]+?)(?:\\.git)?$/);
      return m ? { owner: m[1], repo: m[2] } : null;
    }
    function projectTagHtml(existing) {
      if (!existing) return '';
      if (existing.status === 'done') return '<span class="proj-tag done">Generated</span>';
      if (existing.status === 'failed') return '<span class="proj-tag failed">Failed</span>';
      return '<span class="proj-tag">Generating</span>';
    }
    // The confirm panel's action depends on whether this repo already has a
    // project: done → go view it (never re-offer "Generate"), in-progress →
    // go watch it, failed → offer "Regenerate", new → plain "Generate".
    function confirmPanelHtml(titleHtml, existing, generateFn) {
      if (existing && existing.status === 'done') {
        return \`
          <div class="confirm-panel">
            <div class="who">\${titleHtml}</div>
            <p class="sub" style="margin:0 0 16px;">You have already generated documentation for this repository.</p>
            <button class="btn full" onclick="nav(event,'/projects/\${existing.owner}/\${existing.repo}')">View project →</button>
          </div>\`;
      }
      if (existing && existing.status !== 'failed') {
        return \`
          <div class="confirm-panel">
            <div class="who">\${titleHtml}</div>
            <p class="sub" style="margin:0 0 16px;">This one is already generating.</p>
            <button class="btn full" onclick="location.href='/\${existing.owner}/\${existing.repo}/'">View progress →</button>
          </div>\`;
      }
      const isRegenerate = !!existing; // only 'failed' reaches here
      return \`
        <div class="confirm-panel">
          <div class="who">\${titleHtml}</div>
          \${visChoiceHtml()}
          <button id="generate-submit-btn" class="btn full large" style="margin-top:18px" onclick="\${generateFn}()">\${isRegenerate ? 'Regenerate' : 'Generate'}</button>
          <p class="confirm-note">Usually 2 to 5 minutes. You can close the tab while it runs.</p>
        </div>\`;
    }

    function renderRepoList(repos) {
      const list = document.getElementById('repo-list');
      if (!list) return;
      if (!repos.length) { list.innerHTML = '<div class="repo-empty">No repositories found.</div>'; return; }
      list.innerHTML = repos.map(r => {
        const isSelected = state.selected && state.selected.owner === r.owner && state.selected.repo === r.repo;
        const existing = findProject(r.owner, r.repo);
        // /api/repos is owner-affiliation only, so the owner is almost always
        // you. Surface it only when it isn't, which is when it disambiguates.
        const mineRepo = state.me && state.me.login
          && String(r.owner).toLowerCase() === String(state.me.login).toLowerCase();
        return \`
          <button type="button" role="option" aria-selected="\${isSelected}" class="repo-item\${isSelected ? ' selected' : ''}" data-name="\${escapeHtml(String(r.fullName || '').toLowerCase())}" onclick="selectRepoByName('\${escapeHtml(r.owner)}','\${escapeHtml(r.repo)}')">
            <span class="top-line">
              <span class="rname">\${mineRepo ? '' : '<span class="g-owner">' + escapeHtml(r.owner) + '/</span>'}\${escapeHtml(r.repo)}</span>
              \${r.private ? '<span class="priv">' + LOCK_ICON + 'Private</span>' : ''}
              \${langHtml(r.language)}
              \${projectTagHtml(existing)}
            </span>
            \${r.description ? '<span class="desc">' + escapeHtml(r.description) + '</span>' : ''}
          </button>\`;
      }).join('');
    }

    // Look the repo back up by name rather than embedding a JSON blob in an
    // onclick attribute — a description containing a quote could previously
    // break out of that attribute.
    function selectRepoByName(owner, repo) {
      const r = (state.repos || []).find(x => x.owner === owner && x.repo === repo);
      if (r) selectRepo(r);
    }

    // Filter by toggling rows instead of rebuilding the list. Re-rendering
    // innerHTML on every keystroke reset the 280px scroller to the top while
    // the user was still typing.
    function filterRepos(q) {
      const list = document.getElementById('repo-list');
      if (!list) return;
      const needle = String(q || '').trim().toLowerCase();
      let shown = 0;
      list.querySelectorAll('.repo-item').forEach(el => {
        const match = !needle || (el.dataset.name || '').includes(needle);
        el.hidden = !match;
        if (match) shown++;
      });
      let empty = list.querySelector('.repo-empty');
      if (!shown) {
        if (!empty) {
          empty = document.createElement('div');
          empty.className = 'repo-empty';
          list.appendChild(empty);
        }
        empty.textContent = 'No repositories match that search.';
        empty.hidden = false;
      } else if (empty) {
        empty.hidden = true;
      }
    }

    function selectRepo(repo) {
      state.selected = repo;
      document.getElementById('paste-url').value = '';
      document.getElementById('paste-confirm-slot').innerHTML = '';
      renderRepoList(state.repos);
      const existing = findProject(repo.owner, repo.repo);
      document.getElementById('confirm-slot').innerHTML = confirmPanelHtml(
        'Generate docs for <strong>' + repo.fullName + '</strong>', existing, 'confirmGenerate'
      );
    }

    function onPasteInput() {
      const url = document.getElementById('paste-url').value.trim();
      if (!url) { document.getElementById('paste-confirm-slot').innerHTML = ''; return; }
      state.selected = null;
      document.getElementById('confirm-slot').innerHTML = '';
      renderRepoList(state.repos || []);
      renderPasteConfirm();
    }
    function renderPasteConfirm() {
      const url = document.getElementById('paste-url').value.trim();
      const parsed = parseGithubUrlClient(url);
      const existing = parsed ? findProject(parsed.owner, parsed.repo) : null;
      const title = parsed ? 'Generate docs for <strong>' + parsed.owner + '/' + parsed.repo + '</strong>' : 'Generate docs for this repo';
      document.getElementById('paste-confirm-slot').innerHTML = confirmPanelHtml(title, existing, 'generateFromPaste');
    }

    function confirmGenerate() {
      const r = state.selected;
      startJob({ owner: r.owner, repo: r.repo, description: r.description, language: r.language, avatarUrl: r.avatarUrl, stars: r.stars, visibility: state.visibility });
    }

    function generateFromPaste() {
      const url = document.getElementById('paste-url').value.trim();
      if (!url) return;
      startJob({ repo_url: url, visibility: state.visibility });
    }

    async function startJob(body) {
      if (startInFlight) return;
      startInFlight = true;
      const errSlot = document.getElementById('error-slot');
      if (errSlot) errSlot.innerHTML = '';
      // Either screen's submit control.
      const btn = document.getElementById('generate-submit-btn') || document.getElementById('regenerate-btn');
      const originalBtnHtml = btn ? btn.innerHTML : null;
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="btn-spinner"></span>Generating…';
      }
      let res, data;
      try {
        res = await fetch('/api/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        data = await res.json();
      } catch {
        startInFlight = false;
        if (btn) { btn.disabled = false; btn.innerHTML = originalBtnHtml; }
        if (errSlot) errSlot.innerHTML = '<div class="error-box">Network error — try again.</div>';
        return;
      }
      if (!res.ok) {
        startInFlight = false;
        if (btn) { btn.disabled = false; btn.innerHTML = originalBtnHtml; }
        if (errSlot) errSlot.innerHTML = '<div class="error-box">' + escapeHtml((data && data.error) || 'unknown error') + '</div>';
        return;
      }
      // Deliberately left true on success: we are navigating to the progress
      // screen, and nothing on the way there should be able to enqueue again.
      history.pushState({}, '', '/' + data.owner + '/' + data.repo + '/');
      renderGenerating({
        owner: data.owner,
        repo: data.repo,
        description: body.description || null,
        language: body.language || null,
        avatarUrl: body.avatarUrl || state.me.avatarUrl,
        createdAt: data.createdAt,
      });
      poll(data.job_id, data.owner, data.repo);
    }

    function retryJob(owner, repo) {
      const info = state.currentGenInfo || {};
      startJob({ owner, repo, description: info.description, language: info.language, avatarUrl: info.avatarUrl });
    }

    // ── Generating screen — honest stage list, no fake percentage ────
    function stopGenTimer() {
      if (state.genTimer) { clearInterval(state.genTimer); state.genTimer = null; }
    }

    // One honest line about what each stage is doing, shown only under the
    // active one. Static copy: there is no live sub-progress to report.
    const STAGE_CAPTION = {
      cloning: 'Fetching the repository from GitHub.',
      generating: 'Mapping the code, planning pages, then writing each from the source.',
      building: 'Compiling a static site you can open and share.',
    };
    // 'done' marks every stage finished (the moment before the redirect).
    function renderStageList(currentStage) {
      const list = document.getElementById('stage-list');
      if (!list) return;
      const currentIdx = currentStage === 'done' ? STAGES.length : STAGES.indexOf(currentStage);
      list.innerHTML = STAGES.map((s, i) => {
        const cls = i < currentIdx ? 'done' : (i === currentIdx ? 'active' : '');
        return \`
          <div class="stage-row \${cls}">
            <div class="stage-head"><span class="stage-dot"></span><span class="stage-label">\${STAGE_LABEL[s]}</span></div>
            <div class="stage-cap">\${STAGE_CAPTION[s]}</div>
          </div>\`;
      }).join('');
    }
    // The sweep along the card's top edge is motion, not progress; it has
    // to stop the moment nothing is running any more.
    function setGenCardState(cls) {
      const card = document.querySelector('.gen-card');
      if (card && card.classList) card.classList.add(cls);
    }

    function renderGenerating(info) {
      document.body.dataset.view = 'app';
      renderAppBar();
      state.currentGenInfo = info;
      state.currentStage = 'cloning';
      // info.createdAt is the real server-side job-creation timestamp (D1
      // projects.created_at) — using it instead of Date.now() means the
      // elapsed timer survives a page refresh instead of resetting to 0:00.
      state.genStart = info.createdAt || Date.now();
      stopGenTimer();
      // This is the longest-dwell screen in the product and it used to be a
      // 13px mono repo name floating in the middle of an empty page, with a
      // left-aligned timer that didn't line up with anything. Given there is
      // deliberately no percentage (the backend has no honest completion
      // signal), the job here is to look alive and set expectations.
      document.getElementById('content').innerHTML = \`
        <div class="gen-wrap">
          <div class="gen-halo" aria-hidden="true"></div>
          <div class="gen-card">
            <div class="gen-progress" aria-hidden="true"></div>
            <div class="gen-repo">
              \${avatarHtml(info.avatarUrl, info.owner)}
              <div class="gen-id">
                <div class="gen-kicker">Generating documentation</div>
                <div class="gen-repo-name"><span class="g-owner">\${escapeHtml(info.owner)}/</span>\${escapeHtml(info.repo)}</div>
              </div>
              <div class="gen-elapsed" id="gen-elapsed" aria-label="Elapsed time">0:00</div>
            </div>
          <div class="gen-col">
            <div id="stage-list"></div>
            <div id="result-slot"></div>
            <!-- startJob() writes failures into #error-slot. This screen used
                 to omit it, so the "Retry" button on a failed generation hit
                 a null element and did nothing — and it failed predictably,
                 because a failed start still consumes one of the two daily
                 starts, so the retry usually 429s. -->
            <div id="error-slot"></div>
          </div>
            <p class="gen-note">\${CLOCK_ICON}Usually 2 to 5 minutes. Safe to close this tab; the build keeps going.</p>
          </div>
        </div>\`;
      renderStageList('cloning');
      updateElapsed();
      state.genTimer = setInterval(updateElapsed, 1000);
    }

    function updateElapsed() {
      const el = document.getElementById('gen-elapsed');
      if (!el || !state.genStart) return;
      const s = Math.floor((Date.now() - state.genStart) / 1000);
      // The word "elapsed" moved into the label beneath the number.
      const m = Math.floor(s / 60);
      const rem = String(s % 60).padStart(2, '0');
      el.textContent = m + ':' + rem;
    }

    // Consecutive poll failures. Lives outside poll() so a manual retry can
    // reset it, and so backoff survives across scheduled attempts.
    let pollFails = 0;
    const POLL_BASE_MS = 2000;
    const POLL_MAX_FAILS = 5;

    function pollDelayMs() {
      // Exponential backoff on failure so a flapping network or a cold
      // backend isn't hammered every 2s indefinitely.
      return Math.min(POLL_BASE_MS * Math.pow(2, pollFails), 15000);
    }

    function showPollProblem(jobId, owner, repo, message) {
      const slot = document.getElementById('result-slot');
      if (!slot) return;
      setGenCardState('is-stopped');
      slot.innerHTML = \`
        <div class="error-box">\${escapeHtml(message)}</div>
        <div class="gen-actions">
          <button class="btn" onclick="resumePoll('\${owner}','\${repo}','\${jobId}')">Try again</button>
          <button class="btn ghost" onclick="backToGenerate()">Back to generate</button>
        </div>\`;
    }

    function resumePoll(owner, repo, jobId) {
      pollFails = 0;
      const slot = document.getElementById('result-slot');
      if (slot) slot.innerHTML = '';
      const card = document.querySelector('.gen-card');
      if (card && card.classList) card.classList.remove('is-stopped');
      // Resume the elapsed counter (stopGenTimer ran when we gave up).
      stopGenTimer();
      updateElapsed();
      state.genTimer = setInterval(updateElapsed, 1000);
      poll(jobId, owner, repo);
    }

    async function poll(jobId, owner, repo) {
      // Page navigated away — stop cleanly rather than leaking a timer.
      if (!document.getElementById('stage-list')) return;

      let data;
      try {
        const res = await fetch('/api/status/' + jobId);
        // A 401 means the session expired mid-generation. Previously this fell
        // through to res.json(), leaving data.status undefined — neither 'done'
        // nor 'failed' — so the poll rescheduled forever and the user stared at
        // a frozen stage list with a ticking elapsed timer. The build itself is
        // unaffected, so say that rather than implying it died.
        if (res.status === 401) {
          stopGenTimer();
          showPollProblem(jobId, owner, repo,
            'Your session expired, so we stopped tracking progress. The build itself is still running — sign in again to pick it back up.');
          return;
        }
        if (!res.ok) throw new Error('status ' + res.status);
        data = await res.json();
        if (!data || typeof data.status !== 'string') throw new Error('malformed status payload');
        pollFails = 0;
      } catch (err) {
        pollFails++;
        if (pollFails >= POLL_MAX_FAILS) {
          stopGenTimer();
          showPollProblem(jobId, owner, repo,
            "Lost contact with the build after several attempts. It may still be running — reload this page to check on it.");
          return;
        }
        setTimeout(() => poll(jobId, owner, repo), pollDelayMs());
        return;
      }

      // Re-check: an await gives the user time to navigate away.
      if (!document.getElementById('stage-list')) return;

      if (data.status === 'done') {
        stopGenTimer();
        setGenCardState('is-done');
        renderStageList('done');
        setTimeout(() => { window.location.href = '/' + owner + '/' + repo + '/'; }, 700);
        return;
      }
      if (data.status === 'failed') {
        stopGenTimer();
        setGenCardState('is-stopped');
        // Terminal state, and Retry runs without a route change — release the
        // submit guard here or the Retry button below is inert.
        startInFlight = false;
        document.getElementById('result-slot').innerHTML = \`
          <div class="error-box">Generation failed.\\n\${escapeHtml(data.error || '')}</div>
          <div class="gen-actions">
            <button class="btn" onclick="retryJob('\${owner}','\${repo}')">Retry</button>
            <button class="btn ghost" onclick="backToGenerate()">Back to generate</button>
          </div>
        \`;
        return;
      }
      state.currentStage = data.status;
      renderStageList(data.status);
      setTimeout(() => poll(jobId, owner, repo), POLL_BASE_MS);
    }

    async function backToGenerate() {
      stopGenTimer();
      history.pushState({}, '', '/generate');
      await refreshProjects();
      route();
    }

    // Last resort. The three body slots ship empty, so any error that escapes
    // to the top leaves a blank dark page with no explanation — the single
    // most common way this app "felt broken". If nothing has painted yet, say
    // something. Never overwrite a screen that did render.
    function renderFatal() {
      const content = document.getElementById('content');
      if (!content || content.children.length || content.textContent.trim()) return;
      content.innerHTML = errorBoxHtml('Something went wrong loading the page.', 'location.reload()');
    }
    window.addEventListener('unhandledrejection', renderFatal);
    window.addEventListener('error', renderFatal);

    main().catch(renderFatal);
  </script>
</body>
</html>`;
}

// Shown when someone hits a private site they don't own (or aren't signed in
// for). Never leaks any of the real content. `authed` = the viewer has a valid
// session but simply isn't the owner (so signing in again won't help them).
export function privateSitePage(owner: string, repo: string, authed: boolean, theme: Theme = "dark"): string {
  const name = `<code>${escapeHtmlServer(owner)}/${escapeHtmlServer(repo)}</code>`;
  const body = authed
    ? `<p>The documentation for ${name} is private, and it isn't yours to view.</p>
       <div class="actions"><a class="btn" href="/projects">Go to your projects</a></div>`
    : `<p>The documentation for ${name} is private. If it's yours, sign in to view it.</p>
       <div class="actions"><a class="btn" href="/auth/github">${MINI_ICONS.github}Sign in with GitHub</a>
       <a class="btn secondary" href="/">Browse public docs</a></div>`;
  return miniPage(theme, "Private documentation", MINI_ICONS.lock, `<h1>This documentation is private</h1>${body}`);
}

// Any other path on cloud.deepdoc.tech that matches no route (a mistyped URL, an
// old bookmark). Astro's built-in 404 is an unstyled page with no way out.
export function genericNotFoundPage(theme: Theme = "dark"): string {
  return miniPage(theme, "Page not found", MINI_ICONS.compass, `
    <h1>We could not find that page</h1>
    <p>The link may be mistyped or out of date. Your docs and projects are safe.</p>
    <div class="actions"><a class="btn" href="/">Go to DeepDoc</a></div>`);
}

// A vanity URL nobody has generated. A bare "Not found" string was the one page
// a visitor could land on with no explanation and no way out.
export function notFoundSitePage(owner: string, repo: string, paused: boolean, theme: Theme = "dark"): string {
  const o = escapeHtmlServer(owner);
  const r = escapeHtmlServer(repo);
  const note = paused
    ? "New generations are paused for now while we make DeepDoc smoother and faster, so this one cannot be created yet. Please check back soon."
    : "Nobody has generated docs for this repository yet.";
  return miniPage(theme, "No docs here yet", MINI_ICONS.book, `
    <h1>No docs here yet</h1>
    <p><code>${o}/${r}</code> has no generated site. ${note}</p>
    <div class="actions"><a class="btn" href="/">Browse existing docs</a></div>`);
}

// Shown when a repo's record says "done" but the actual generated files are
// gone (e.g. a runner restart happened before this site's content made it to
// R2) — plain and honest instead of silently falling back to the dashboard.
export function stalePageHtml(owner: string, repo: string, theme: Theme = "dark"): string {
  const detail = `/projects/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`;
  return miniPage(theme, "Site unavailable", MINI_ICONS.archive, `
    <h1>This site is no longer available</h1>
    <p><code>${escapeHtmlServer(owner)}/${escapeHtmlServer(repo)}</code> was generated successfully, but the underlying files are gone. This happens after a backend restart on an older build; regenerating fixes it for good.</p>
    <div class="actions"><a class="btn" href="${escapeHtmlServer(detail)}">Regenerate</a></div>`);
}

// Minimal server-side HTML escaper for untrusted strings interpolated into the
// static mini-pages (owner/repo from the URL, a runner error message). The
// client script has its own escapeHtml; this is the server-render equivalent.
function escapeHtmlServer(v: string): string {
  return String(v ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Shown when a repo's job actually FAILED (status.json status === "failed").
// Previously these were served the stalePageHtml "generated successfully but
// files are gone" screen, which is untrue for a failed job and misleadingly
// offered a plain "Regenerate" as if it had once worked. This states the
// failure honestly and surfaces the runner's error. Only reached after the
// visibility gate, so showing the error is within the same trust boundary as
// the site content itself.
export function failedPageHtml(
  owner: string,
  repo: string,
  error: string | null,
  theme: Theme = "dark",
): string {
  const detail = error && error.trim()
    ? `<pre class="err">${escapeHtmlServer(error.trim())}</pre>`
    : `<p>The last generation run did not complete. Regenerating may fix it.</p>`;
  const projectUrl = `/projects/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`;
  return miniPage(theme, "Generation failed", MINI_ICONS.alert, `
    <h1>Documentation generation failed</h1>
    <p><code>${escapeHtmlServer(owner)}/${escapeHtmlServer(repo)}</code> could not be generated.</p>
    ${detail}
    <div class="actions"><a class="btn" href="${escapeHtmlServer(projectUrl)}">Regenerate</a></div>`, "is-danger");
}
