// Ported verbatim from web/hosted/src/try_page.ts as part of the Astro
// unification — server-rendered HTML+vanilla-JS strings, called from thin
// Astro pages under src/pages/cloud/. All internal fetch()/nav() calls use
// root-relative paths (/api/me, /generate, ...) matching the clean external
// URL that src/middleware.ts's hostname rewrite preserves — nothing here
// needed to change to work through that rewrite.
//
// This is its own visual identity from deepdoc.tech's marketing site — same
// brand accent (#C2FF4D) for continuity, but its own tinted neutral scale,
// restrained accent usage, and editorial/technical layout. Do not
// reintroduce the old "borrow the marketing card recipe verbatim" approach —
// this app now owns its design system (see docs/HOSTED_UI_SPEC.md).
//
// IA: /generate is the only post-login home (repo picker + paste + confirm).
// All project management (list, visit, visibility, delete) lives under
// /projects and /projects/:owner/:repo — never inline on /generate, never in
// the profile dropdown (which is identity + nav links only).
export function tryPageHtml(): string {
  return `<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>DeepDoc Cloud — generate docs from a GitHub repo</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700;9..40,800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
<style>
  :root {
    --surface: oklch(16% 0.008 250); --surface-raised: oklch(20% 0.009 250); --surface-high: oklch(25% 0.011 250);
    --ink: oklch(93% 0.004 250); --ink-muted: oklch(64% 0.012 250); --ink-faint: oklch(42% 0.012 250);
    --line: oklch(45% 0.012 250 / 22%); --line-strong: oklch(55% 0.014 250 / 34%);
    --accent: #C2FF4D; --accent-ink: oklch(16% 0.008 250); --accent-dim: rgba(194,255,77,0.08); --accent-line: rgba(194,255,77,0.3);
    --danger: #ff6b6b; --danger-dim: rgba(255,107,107,0.08);
    --font-sans: 'DM Sans', ui-sans-serif, system-ui, sans-serif;
    --font-mono: 'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace;
    --shadow-lift: 0 24px 60px -20px rgba(0,0,0,0.6);
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    min-height: 100vh; background: var(--surface); color: var(--ink);
    font-family: var(--font-sans); display: flex; flex-direction: column;
    -webkit-font-smoothing: antialiased;
  }
  a { color: inherit; }
  #content { flex: 1; display: flex; flex-direction: column; }
  .wrap { width: 100%; max-width: 880px; margin: 0 auto; padding: 0 28px; }
  .wrap-narrow { width: 100%; max-width: 560px; margin: 0 auto; padding: 0 28px 40px; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }

  /* ── App bar — byte-for-byte the same recipe as deepdoc.tech's
     Header.astro/Logo.astro (same container width, same brand-mark sizing/
     spacing, same font-size) so switching domains reads as one product, not
     two. Duplicated here (not imported) since these are plain .ts endpoints,
     not .astro components — keep in sync with Header.astro/Logo.astro by
     hand if either changes. ───────────────────────────────────────────── */
  .appbar { position: sticky; top: 0; z-index: 10; border-bottom: 1px solid var(--line); background: color-mix(in oklab, var(--surface) 86%, transparent); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px); flex-shrink: 0; }
  .appbar-inner { max-width: 1152px; margin: 0 auto; height: 52px; padding: 0 24px; display: flex; align-items: center; justify-content: space-between; }
  .brand { font-family: var(--font-sans); font-weight: 600; font-size: 1.2rem; text-decoration: none; letter-spacing: -0.015em; color: var(--ink); display: flex; align-items: center; cursor: pointer; }
  .dd-mark { display: block; flex-shrink: 0; width: 1.16em; height: 1.16em; margin-left: -0.33em; margin-right: 0.04em; transform: translateY(-0.05em); }
  .dd-mark .dd-front { fill: var(--accent); }
  .dd-mark .dd-echo { fill: none; stroke: var(--accent); stroke-width: 2; stroke-linecap: round; }
  .dd-mark .dd-echo-1 { opacity: 0.4; } .dd-mark .dd-echo-2 { opacity: 0.18; }
  .account-chip { display: flex; align-items: center; gap: 8px; background: transparent; border: 1px solid var(--line-strong); border-radius: 999px; padding: 4px 12px 4px 4px; color: var(--ink); font-family: var(--font-sans); font-size: 13px; font-weight: 500; height: auto; cursor: pointer; transition: border-color 0.15s; }
  .account-chip:hover { border-color: var(--ink-faint); }
  .account-chip img { width: 24px; height: 24px; border-radius: 50%; }
  .account-wrap { position: relative; }

  /* ── Profile dropdown — identity + nav only, no project rows ──────── */
  .profile-dd { position: absolute; right: 0; top: 44px; width: 230px; background: var(--surface-high); border: 1px solid var(--line-strong); border-radius: 12px; padding: 14px; box-shadow: var(--shadow-lift); z-index: 15; }
  .profile-dd-head { display: flex; align-items: center; gap: 10px; padding-bottom: 12px; margin-bottom: 10px; border-bottom: 1px solid var(--line); }
  .profile-dd-head img { width: 34px; height: 34px; border-radius: 50%; }
  .profile-dd-head .nm { font-size: 13.5px; font-weight: 600; }
  .profile-dd-head .qt { font-size: 10.5px; color: var(--ink-faint); font-family: var(--font-mono); }
  .profile-dd-link { display: flex; align-items: center; justify-content: space-between; padding: 9px 2px; font-size: 13px; color: var(--ink); text-decoration: none; cursor: pointer; border-radius: 6px; background: none; border: none; width: 100%; text-align: left; font-family: var(--font-sans); }
  .profile-dd-link:hover { background: var(--surface); }
  .profile-dd-link .count { font-family: var(--font-mono); font-size: 11.5px; color: var(--ink-faint); }
  .profile-dd-link.muted { color: var(--ink-muted); }

  /* ── Buttons / inputs (shared) ───────────────────────────────────── */
  button { font-family: var(--font-sans); }
  .btn { height: 42px; border-radius: 8px; border: none; cursor: pointer; padding: 0 18px; background: var(--accent); color: var(--accent-ink); font-size: 14px; font-weight: 600; transition: opacity 0.15s, transform 0.1s; }
  .btn:hover:not(:disabled) { opacity: 0.88; }
  .btn:active:not(:disabled) { transform: scale(0.98); }
  .btn:disabled { opacity: 0.35; cursor: not-allowed; }
  .btn-spinner { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: currentColor; animation: pulse 1.2s ease-in-out infinite; }
  .btn.secondary { background: var(--surface-high); color: var(--ink); border: 1px solid var(--line-strong); }
  .btn.ghost { background: transparent; color: var(--ink-muted); border: 1px solid var(--line-strong); }
  .btn.full { width: 100%; }
  .btn.small { height: 34px; padding: 0 13px; font-size: 12.5px; }
  .btn.danger-outline { background: transparent; border: 1px solid rgba(255,107,107,0.4); color: var(--danger); height: 36px; padding: 0 14px; font-size: 12.5px; }
  input {
    width: 100%; padding: 12px 14px; border-radius: 8px; border: 1px solid var(--line-strong);
    background: var(--surface); color: var(--ink); font-family: var(--font-mono); font-size: 13px;
    outline: none; transition: border-color 0.15s;
  }
  input::placeholder { color: var(--ink-faint); }
  input:focus { border-color: var(--accent); }
  code, .mono { font-family: var(--font-mono); }

  /* ── Sign-in popup (unauthenticated root) ────────────────────────────
     Not a full pitch page — deepdoc.tech's own landing page already sells
     the product. This pops up over a quiet, mostly-empty backdrop (same
     header, no marketing copy) and can't be dismissed without signing in —
     there's nothing else to do on this domain unauthenticated. */
  .modal-veil { position: fixed; inset: 0; background: rgba(6,6,9,0.7); backdrop-filter: blur(3px); display: flex; align-items: center; justify-content: center; padding: 24px; z-index: 20; }
  .modal { width: 100%; max-width: 440px; background: var(--surface-raised); border: 1px solid var(--line-strong); border-radius: 20px; padding: 36px 32px 32px; box-shadow: var(--shadow-lift); text-align: center; animation: confirm-rise 0.18s ease-out; }
  .modal h1 { font-size: 25px; font-weight: 800; letter-spacing: -0.02em; margin: 0 0 10px; }
  .modal p.modal-sub { font-size: 13.5px; line-height: 1.7; color: var(--ink-muted); margin: 0; }
  .modal-icon-wrap { position: relative; height: 104px; display: flex; align-items: center; justify-content: center; margin-bottom: 6px; }
  .modal-dot-grid {
    position: absolute; inset: 0;
    background-image: radial-gradient(circle, var(--line-strong) 1.5px, transparent 1.5px);
    background-size: 18px 18px;
    -webkit-mask-image: radial-gradient(ellipse 65% 70% at 50% 50%, black 15%, transparent 78%);
    mask-image: radial-gradient(ellipse 65% 70% at 50% 50%, black 15%, transparent 78%);
  }
  .modal-icon-badge {
    position: relative; width: 76px; height: 76px; border-radius: 50%;
    background: #0d1117; display: flex; align-items: center; justify-content: center;
    box-shadow: 0 0 0 1px var(--line-strong), 0 0 30px 6px rgba(194,255,77,0.32);
  }
  .modal-icon-badge svg { width: 38px; height: 38px; color: #fff; }
  .modal-divider { height: 1px; background: var(--line); margin: 24px 0 6px; }
  .modal-features { display: flex; flex-direction: column; margin: 0 0 24px; text-align: left; }
  .modal-feature { display: flex; align-items: flex-start; gap: 14px; padding: 16px 0; border-bottom: 1px solid var(--line); }
  .modal-feature:last-child { border-bottom: none; }
  .modal-feature-icon { flex-shrink: 0; width: 40px; height: 40px; border-radius: 10px; background: var(--accent-dim); border: 1px solid var(--accent-line); display: flex; align-items: center; justify-content: center; color: var(--accent); }
  .modal-feature-icon svg { width: 20px; height: 20px; }
  .modal-feature-title { font-size: 14.5px; font-weight: 700; color: var(--ink); margin: 0 0 3px; }
  .modal-feature-desc { font-size: 12.5px; color: var(--ink-muted); line-height: 1.5; margin: 0; }
  .modal .btn.full { height: 54px; font-size: 15px; font-weight: 700; border-radius: 12px; }

  /* ── Section headers (shared across authed views) ──────────────── */
  .page-head { display: flex; align-items: baseline; justify-content: space-between; padding: 40px 0 24px; flex-wrap: wrap; gap: 12px; }
  .page-head h1 { font-size: 22px; font-weight: 700; letter-spacing: -0.02em; margin: 0; }
  .empty-state { text-align: center; padding: 80px 20px; }
  .empty-state h2 { font-size: 17px; font-weight: 600; margin: 0 0 8px; }
  .empty-state p { font-size: 13.5px; color: var(--ink-muted); margin: 0 0 24px; }
  .back-link { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--ink-muted); text-decoration: none; margin: 28px 0 4px; cursor: pointer; }
  .back-link:hover { color: var(--ink); }

  /* ── Public gallery (logged-out root) — grid of real generated docs,
     shown instead of an immediate sign-in wall. The card's main visual is a
     LIVE preview of the real generated site's homepage (an iframe pointed
     at the same /{owner}/{repo}/ this app already serves, scaled down —
     no separate screenshot pipeline needed, and it's always current), not
     an avatar. A subtle 3D tilt on mousemove — plain CSS transform +
     mousemove math, the same effect a framer-motion card gives you, no
     React/framer-motion dependency needed for it. */
  .gallery-heading { font-size: 15px; font-weight: 500; color: var(--ink-muted); letter-spacing: -0.01em; margin: 0; }
  .gallery-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 18px; }
  .gallery-card { position: relative; border-radius: 14px; cursor: pointer; transition: transform 0.08s ease-out; will-change: transform; }
  /* Border beam — a light trail that travels around the card's edge on
     hover. Not a mask trick (mask-composite: exclude turned out to be too
     fragile across browsers to get right) — instead the classic, robust
     version: a full-bleed rotating conic-gradient sits behind the card
     (::before), and the real content lives in an inner box
     (.gallery-card-surface) inset by exactly the border's thickness via
     margin, so only that thin margin gap reveals the gradient underneath.
     No mask/clip-path involved. */
  .gallery-card::before {
    content: '';
    position: absolute;
    inset: 0;
    border-radius: inherit;
    background: conic-gradient(from var(--beam-angle, 0deg), transparent 0%, transparent 78%, var(--accent) 90%, transparent 100%);
    opacity: 0;
    transition: opacity 0.2s;
  }
  .gallery-card:hover::before { opacity: 1; animation: gallery-beam 2.2s linear infinite; }
  @property --beam-angle {
    syntax: '<angle>';
    inherits: false;
    initial-value: 0deg;
  }
  @keyframes gallery-beam { to { --beam-angle: 360deg; } }
  @media (prefers-reduced-motion: reduce) {
    .gallery-card:hover::before { animation: none; opacity: 0.6; }
  }
  .gallery-card-surface { position: relative; z-index: 1; margin: 1.5px; border: 1px solid var(--line-strong); border-radius: 12.5px; background: var(--surface-raised); overflow: hidden; transition: border-color 0.12s; }
  .gallery-card:hover .gallery-card-surface { border-color: transparent; }
  .gallery-preview { position: relative; height: 150px; overflow: hidden; background: var(--surface-high); pointer-events: none; }
  .gallery-preview-inner { width: 400%; height: 400%; transform: scale(0.25); transform-origin: top left; }
  .gallery-preview-inner iframe { width: 100%; height: 100%; border: none; display: block; opacity: 0; transition: opacity 0.35s ease; }
  .gallery-preview-inner iframe.loaded { opacity: 1; }
  .gallery-avatar-fallback { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; font-family: var(--font-sans); font-weight: 700; font-size: 28px; color: rgba(255,255,255,0.9); }
  .gallery-body { padding: 12px 16px 16px; min-width: 0; }
  .gallery-name { font-family: var(--font-mono); font-size: 13.5px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .gallery-desc { font-size: 12.5px; color: var(--ink-muted); margin-top: 6px; line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .gallery-lang { font-family: var(--font-mono); font-size: 10.5px; color: var(--ink-faint); margin-top: 8px; }

  /* ── /projects — click-through rows, no per-row buttons ──────────── */
  .proj-row { display: flex; align-items: center; gap: 14px; padding: 17px 14px; margin: 0 -14px; border-bottom: 1px solid var(--line); cursor: pointer; border-radius: 8px; transition: background 0.12s; }
  .proj-row:hover { background: var(--surface-raised); }
  .proj-row:last-child { border-bottom: none; }
  .proj-row .name { font-family: var(--font-mono); font-size: 13.5px; font-weight: 500; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .vis-badge { font-size: 11px; color: var(--ink-faint); font-family: var(--font-mono); }
  .row-chev { color: var(--ink-faint); font-size: 14px; }
  .status-text { font-size: 12px; color: var(--ink-faint); display: flex; align-items: center; gap: 6px; white-space: nowrap; }
  .status-text .sdot { width: 6px; height: 6px; border-radius: 50%; background: var(--ink-faint); }
  .status-text.done { color: var(--ink-muted); } .status-text.done .sdot { background: var(--accent); }
  .status-text.building .sdot { background: var(--accent); animation: pulse 1.2s ease-in-out infinite; }
  .status-text.failed { color: var(--danger); } .status-text.failed .sdot { background: var(--danger); }

  /* ── /projects/:owner/:repo — the only place project actions live ── */
  .proj-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 8px 0 8px; flex-wrap: wrap; }
  .proj-head .title-block h1 { font-size: 21px; font-weight: 700; letter-spacing: -0.02em; margin: 0 0 6px; font-family: var(--font-mono); }
  .proj-meta-row { font-size: 12.5px; color: var(--ink-faint); display: flex; gap: 14px; }
  .section-title { font-family: var(--font-mono); font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--ink-faint); margin: 36px 0 14px; }
  .danger-box { border: 1px solid rgba(255,107,107,0.28); border-radius: 10px; padding: 16px 18px; display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
  .danger-box .lbl { font-size: 13px; color: var(--ink-muted); }
  .danger-box .lbl strong { color: var(--ink); display: block; font-size: 13.5px; margin-bottom: 2px; }

  /* ── /generate — the only post-login home ─────────────────────────── */
  .step-label { font-family: var(--font-mono); font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--ink-faint); margin: 8px 0 12px; }
  .repo-list { max-height: 280px; overflow-y: auto; border: 1px solid var(--line-strong); border-radius: 10px; margin-top: 10px; }
  .repo-item { padding: 12px 14px; cursor: pointer; border-bottom: 1px solid var(--line); transition: background 0.1s; }
  .repo-item:hover { background: var(--surface-high); }
  .repo-item:last-child { border-bottom: none; }
  .repo-item.selected { background: var(--accent-dim); box-shadow: inset 2px 0 0 var(--accent); }
  .repo-item .top-line { display: flex; align-items: center; gap: 8px; font-family: var(--font-mono); font-size: 12.5px; }
  .repo-item .priv { color: var(--ink-faint); font-size: 10px; }
  .repo-item .lang { font-family: var(--font-mono); font-size: 10px; color: var(--ink-faint); }
  .proj-tag { font-family: var(--font-mono); font-size: 10px; padding: 2px 7px; border-radius: 999px; border: 1px solid var(--line-strong); margin-left: auto; }
  .proj-tag.done { color: var(--accent); border-color: var(--accent-line); background: var(--accent-dim); }
  .proj-tag.failed { color: var(--danger); border-color: rgba(255,107,107,0.3); background: var(--danger-dim); }
  .proj-tag.building { color: var(--ink-muted); }
  .repo-item .desc { color: var(--ink-muted); font-size: 11.5px; margin-top: 3px; }
  .divider { display: flex; align-items: center; gap: 12px; color: var(--ink-faint); font-size: 11.5px; font-family: var(--font-mono); margin: 24px 0; }
  .divider::before, .divider::after { content: ''; flex: 1; height: 1px; background: var(--line); }
  .vis-group { display: flex; align-items: center; gap: 8px; }
  .vis-label { font-family: var(--font-mono); font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--ink-faint); margin-right: 2px; }
  .vis-pill { height: auto; padding: 6px 13px; font-size: 12px; border-radius: 999px; background: transparent; border: 1px solid var(--line-strong); color: var(--ink-muted); font-family: var(--font-mono); cursor: pointer; }
  .vis-pill.active { background: var(--accent-dim); border-color: var(--accent-line); color: var(--accent); }
  .vis-hint { font-size: 11.5px; color: var(--ink-faint); margin-top: 8px; line-height: 1.5; }
  /* An elevated card right where you picked a repo/URL — not pinned to the
     viewport edge (that just made it read as further away on a tall screen),
     just a clear lift off the page surface with a quick rise-in. */
  .confirm-panel {
    margin-top: 14px; border: 1px solid var(--line-strong); border-radius: 14px; padding: 20px;
    background: var(--surface-raised); box-shadow: var(--shadow-lift);
    animation: confirm-rise 0.16s ease-out;
  }
  @keyframes confirm-rise { from { transform: translateY(8px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
  .confirm-panel .who { font-family: var(--font-mono); font-size: 13px; margin-bottom: 14px; }
  .error-box { color: var(--danger); font-size: 13px; background: var(--danger-dim); border: 1px solid rgba(255,107,107,0.25); border-radius: 10px; padding: 13px; margin-top: 16px; white-space: pre-wrap; }

  /* ── Generating screen — honest stage list, no fake percentage ────── */
  .gen-wrap { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 60px 24px 70px; text-align: center; }
  .gen-repo { font-family: var(--font-mono); font-size: 13px; color: var(--ink-muted); margin-bottom: 26px; display: flex; align-items: center; gap: 10px; }
  .gen-repo img { width: 22px; height: 22px; border-radius: 50%; }
  .gen-elapsed { font-family: var(--font-mono); font-size: 12.5px; color: var(--ink-faint); margin-bottom: 24px; }
  .gen-col { width: 100%; max-width: 420px; text-align: left; }
  .stage-row { border-bottom: 1px solid var(--line); padding: 14px 2px; }
  .stage-row:last-child { border-bottom: none; }
  .stage-head { display: flex; align-items: center; gap: 11px; }
  .stage-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--line-strong); flex-shrink: 0; }
  .stage-row.active .stage-dot { background: var(--accent); box-shadow: 0 0 8px rgba(194,255,77,0.5); animation: pulse 1.2s ease-in-out infinite; }
  .stage-row.done .stage-dot { background: var(--accent); }
  .stage-label { font-size: 14px; color: var(--ink-muted); flex: 1; }
  .stage-row.active .stage-label, .stage-row.done .stage-label { color: var(--ink); font-weight: 500; }
  .gen-result { margin-top: 26px; }

  .sub { color: var(--ink-muted); font-size: 13.5px; line-height: 1.7; }
</style>
</head>
<body>
  <div id="appbar-slot"></div>
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
    const STAGES = ['cloning', 'generating', 'building'];
    const STAGE_LABEL = { cloning: 'Cloning repository', generating: 'Generating documentation', building: 'Building your site' };

    async function main() {
      state.me = await fetch('/api/me').then(r => r.json());
      if (!state.me.authenticated) { renderLoggedOut(); return; }
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
      renderAppBar();
      const path = window.location.pathname;
      const projMatch = path.match(/^\\/projects\\/([\\w.-]+)\\/([\\w.-]+)\\/?$/);
      if (projMatch) return renderProjectDetail(projMatch[1], projMatch[2]);
      if (path === '/projects') return renderProjects();
      if (path === '/generate') return renderGenerate();
      // Any other path (typically '/', including the bare domain) — land on
      // the sensible default: your projects if you have any, otherwise the
      // generate flow. Rewrite the URL so the address bar matches the view.
      const target = state.projects.length ? '/projects' : '/generate';
      history.replaceState({}, '', target);
      return target === '/projects' ? renderProjects() : renderGenerate();
    }
    function nav(e, path) { if (e) e.preventDefault(); closeDropdown(); history.pushState({}, '', path); route(); return false; }
    window.addEventListener('popstate', () => { if (state.me && state.me.authenticated) route(); });

    // ── App bar + profile dropdown (identity + nav links only) ───────
    function renderAppBar() {
      const slot = document.getElementById('appbar-slot');
      if (!state.me || !state.me.authenticated) { slot.innerHTML = ''; return; }
      const q = state.quota || {};
      const quotaLine = q.unlimited ? 'unlimited' : \`\${q.savedProjects ?? 0}\${q.maxSavedProjects != null ? '/' + q.maxSavedProjects : ''} saved\`;
      slot.innerHTML = \`
        <header class="appbar">
          <div class="appbar-inner">
            <a class="brand" onclick="return nav(event,'/')">\${brandMarkHtml()}</a>
            <div class="account-wrap">
              <button class="account-chip" onclick="event.stopPropagation(); toggleDropdown()">
                <img src="\${state.me.avatarUrl}" alt="" /><span>\${state.me.login}</span>
              </button>
              <div id="profile-dd"></div>
            </div>
          </div>
        </header>\`;
      if (state.ddOpen) renderDropdown();
    }

    function renderDropdown() {
      const q = state.quota || {};
      const projCount = state.projects.length;
      document.getElementById('profile-dd').innerHTML = \`
        <div class="profile-dd" onclick="event.stopPropagation()">
          <div class="profile-dd-head">
            <img src="\${state.me.avatarUrl}" alt="" />
            <div><div class="nm">\${state.me.login}</div><div class="qt">\${q.unlimited ? 'unlimited' : (q.savedProjects ?? 0) + '/' + (q.maxSavedProjects ?? '?') + ' saved'}</div></div>
          </div>
          <a class="profile-dd-link" onclick="nav(event,'/projects')"><span>Projects</span><span class="count">\${projCount} ›</span></a>
          <button class="btn ghost full" style="height:34px;font-size:12.5px;margin-top:10px;" onclick="logout()">Log out</button>
        </div>\`;
    }
    function toggleDropdown() {
      state.ddOpen = !state.ddOpen;
      if (state.ddOpen) { renderDropdown(); document.addEventListener('click', closeDropdownOnce); document.addEventListener('keydown', closeDropdownOnEscape); }
      else closeDropdown();
    }
    function closeDropdown() {
      state.ddOpen = false;
      const el = document.getElementById('profile-dd');
      if (el) el.innerHTML = '';
      document.removeEventListener('click', closeDropdownOnce);
      document.removeEventListener('keydown', closeDropdownOnEscape);
    }
    function closeDropdownOnce() { closeDropdown(); }
    function closeDropdownOnEscape(e) { if (e.key === 'Escape') closeDropdown(); }

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
    // "Generate your own" — see renderPublicGallery below.
    async function renderLoggedOut() {
      document.getElementById('appbar-slot').innerHTML = \`
        <header class="appbar"><div class="appbar-inner">
          <span class="brand">\${brandMarkHtml()}</span>
          <button class="btn" onclick="openSignInFromGallery()">Generate your own</button>
        </div></header>\`;
      document.getElementById('modal-slot').innerHTML = '';
      const data = await fetch('/api/examples').then(r => r.json()).catch(() => ({ examples: [] }));
      renderPublicGallery(data.examples || []);
    }

    function openSignInFromGallery() {
      document.getElementById('modal-slot').innerHTML = signInModalHtml('/auth/github', true);
    }

    // Deterministic hue + initial, shown behind the live preview iframe as
    // a backdrop (in case the iframe is slow, still building, or fails) —
    // never a flat blank box while the real preview loads.
    function fallbackHue(owner) {
      let hash = 0;
      for (let i = 0; i < owner.length; i++) hash = (hash * 31 + owner.charCodeAt(i)) | 0;
      return Math.abs(hash) % 360;
    }

    function renderPublicGallery(examples) {
      if (!examples.length) {
        document.getElementById('content').innerHTML = \`
          <div class="wrap">
            <div class="page-head"><h1 class="gallery-heading">Previously generated by others</h1></div>
            <div class="empty-state">
              <h2>No public docs yet</h2>
              <p>Nothing's been shared publicly so far — check back soon, or be the first.</p>
              <button class="btn" onclick="openSignInFromGallery()">Generate your own</button>
            </div>
          </div>\`;
        return;
      }
      const cards = examples.map(e => {
        const hue = fallbackHue(e.owner);
        const initial = (e.owner[0] || '?').toUpperCase();
        const siteUrl = '/' + e.owner + '/' + e.repo + '/';
        return \`
        <div class="gallery-card" onclick="location.href='\${siteUrl}'">
          <div class="gallery-card-surface">
            <div class="gallery-preview" style="background: hsl(\${hue}, 55%, 32%);">
              <div class="gallery-avatar-fallback">\${initial}</div>
              <div class="gallery-preview-inner">
                <iframe src="\${siteUrl}" loading="lazy" tabindex="-1" title="Preview of \${e.owner}/\${e.repo} docs" onload="this.classList.add('loaded')"></iframe>
              </div>
            </div>
            <div class="gallery-body">
              <div class="gallery-name">\${e.owner}/\${e.repo}</div>
              \${e.description ? '<div class="gallery-desc">' + e.description + '</div>' : ''}
              \${e.language ? '<div class="gallery-lang">' + e.language + '</div>' : ''}
            </div>
          </div>
        </div>\`;
      }).join('');
      document.getElementById('content').innerHTML = \`
        <div class="wrap">
          <div class="page-head">
            <h1 class="gallery-heading">Previously generated by others</h1>
          </div>
          <div class="gallery-grid">\${cards}</div>
        </div>\`;
      attachTilt();
    }

    // Subtle 3D tilt on mousemove — plain CSS transform + a bit of math,
    // the same effect a framer-motion card gives you without needing
    // React/framer-motion in this codebase.
    function attachTilt() {
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
      document.querySelectorAll('.gallery-card').forEach((card) => {
        card.addEventListener('mousemove', (e) => {
          const rect = card.getBoundingClientRect();
          const x = (e.clientX - rect.left) / rect.width - 0.5;
          const y = (e.clientY - rect.top) / rect.height - 0.5;
          card.style.transform = 'perspective(700px) rotateX(' + (-y * 7).toFixed(2) + 'deg) rotateY(' + (x * 7).toFixed(2) + 'deg) translateY(-2px)';
        });
        card.addEventListener('mouseleave', () => { card.style.transform = ''; });
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
          <div class="modal">
            <div class="modal-icon-wrap">
              <div class="modal-dot-grid"></div>
              <div class="modal-icon-badge">\${GITHUB_ICON_SVG}</div>
            </div>
            <h1>Sign in with GitHub</h1>
            <p class="modal-sub">DeepDoc needs read access to clone the repo you pick and generate its docs. We only use it for that.</p>
            <div class="modal-divider"></div>
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
            <button class="btn full" style="display:flex;align-items:center;justify-content:center;gap:10px;" onclick="startGithubAuth(this,'\${authHref}')">\${GITHUB_ICON_SVG}Continue with GitHub</button>
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

    async function refreshProjects() {
      const data = await fetch('/api/projects').then(r => r.json());
      state.projects = data.projects || [];
      state.quota = data.quota || null;
    }

    // ── /projects — click-through list, no per-row buttons ───────────
    function renderProjects() {
      const q = state.quota;
      const atQuota = q && q.maxSavedProjects != null && q.savedProjects >= q.maxSavedProjects;
      const genBtn = \`<button class="btn" \${atQuota ? 'disabled title="At your project limit — delete one to free a slot"' : ''} onclick="nav(event,'/generate')">Generate new</button>\`;

      if (!state.projects.length) {
        document.getElementById('content').innerHTML = \`
          <div class="wrap">
            <div class="page-head"><h1>Projects</h1></div>
            <div class="empty-state">
              <h2>No projects yet</h2>
              <p>Generate documentation from any GitHub repo in under a minute.</p>
              \${genBtn}
            </div>
          </div>\`;
        return;
      }
      const rows = state.projects.map(p => \`
        <div class="proj-row" onclick="nav(event,'/projects/\${p.owner}/\${p.repo}')">
          <span class="name">\${p.owner}/\${p.repo}</span>
          <span class="vis-badge">\${p.visibility === 'public' ? 'public' : 'private'}</span>
          <span class="status-text \${p.status === 'done' ? 'done' : p.status === 'building' || p.status === 'generating' || p.status === 'cloning' || p.status === 'queued' ? 'building' : p.status === 'failed' ? 'failed' : ''}"><span class="sdot"></span>\${p.status}</span>
          <span class="row-chev">›</span>
        </div>\`).join('');
      document.getElementById('content').innerHTML = \`
        <div class="wrap">
          <div class="page-head"><h1>Projects</h1>\${genBtn}</div>
          <div>\${rows}</div>
        </div>\`;
    }

    // ── /projects/:owner/:repo — the only place project actions live ─
    function renderProjectDetail(owner, repo) {
      const p = state.projects.find(x => x.owner.toLowerCase() === owner.toLowerCase() && x.repo.toLowerCase() === repo.toLowerCase());
      if (!p) { nav(null, '/projects'); return; }
      const isDone = p.status === 'done';
      const createdStr = p.createdAt ? new Date(p.createdAt).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '';
      document.getElementById('content').innerHTML = \`
        <div class="wrap-narrow" style="max-width:600px;">
          <a class="back-link" onclick="nav(event,'/projects')">← Back to projects</a>
          <div class="proj-head" style="margin-top:10px;">
            <div class="title-block">
              <h1>\${p.owner}/\${p.repo}</h1>
              <div class="proj-meta-row"><span class="status-text \${p.status === 'done' ? 'done' : p.status === 'failed' ? 'failed' : 'building'}"><span class="sdot"></span>\${p.status}</span>\${createdStr ? '<span>generated ' + createdStr + '</span>' : ''}</div>
            </div>
            <div style="display:flex; gap:8px;">
              <button class="btn secondary" onclick="regenerateProject('\${p.owner}','\${p.repo}')">Regenerate</button>
              <button class="btn" \${isDone ? '' : 'disabled'} onclick="window.open('/\${p.owner}/\${p.repo}/', '_blank')">Visit site ↗</button>
            </div>
          </div>

          <div class="section-title">Visibility</div>
          <div class="vis-group">
            <span class="vis-label">Who can see this</span>
            <button type="button" class="vis-pill \${p.visibility !== 'public' ? 'active' : ''}" onclick="setProjectVisibility('\${p.owner}','\${p.repo}','private')">🔒 Private</button>
            <button type="button" class="vis-pill \${p.visibility === 'public' ? 'active' : ''}" onclick="setProjectVisibility('\${p.owner}','\${p.repo}','public')">🌐 Public</button>
          </div>
          <div class="vis-hint">\${p.visibility === 'public' ? 'Public — anyone with the link can view the generated docs.' : 'Private — only you can view them. You can make it public anytime.'}</div>

          <div class="section-title">Danger zone</div>
          <div id="danger-slot">\${dangerBoxHtml(p.owner, p.repo)}</div>
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

    function dangerBoxHtml(owner, repo) {
      return \`
        <div class="danger-box">
          <div class="lbl"><strong>Delete this project</strong>Removes it from your dashboard. This can't be undone.</div>
          <button class="btn danger-outline" onclick="confirmDeleteStep('\${owner}','\${repo}')">Delete</button>
        </div>\`;
    }
    function confirmDeleteStep(owner, repo) {
      document.getElementById('danger-slot').innerHTML = \`
        <div class="danger-box">
          <div class="lbl"><strong>Delete this project</strong>This can't be undone.</div>
          <div style="display:flex; gap:8px;">
            <button class="btn ghost small" onclick="document.getElementById('danger-slot').innerHTML=dangerBoxHtml('\${owner}','\${repo}')">Cancel</button>
            <button class="btn danger-outline" onclick="deleteProject('\${owner}','\${repo}')">Confirm delete?</button>
          </div>
        </div>\`;
    }

    async function setProjectVisibility(owner, repo, visibility) {
      await fetch('/api/projects/' + owner + '/' + repo + '/visibility', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ visibility }),
      });
      await refreshProjects();
      renderProjectDetail(owner, repo);
    }

    async function deleteProject(owner, repo) {
      await fetch('/api/projects/' + owner + '/' + repo, { method: 'DELETE' });
      await refreshProjects();
      nav(null, '/projects');
    }

    // ── /generate — the only post-login home ─────────────────────────
    function renderGenerate() {
      state.selected = null;
      state.visibility = 'private';
      const q = state.quota;
      const atQuota = q && q.maxSavedProjects != null && q.savedProjects >= q.maxSavedProjects;

      if (atQuota) {
        document.getElementById('content').innerHTML = \`
          <div class="wrap-narrow">
            <div class="page-head"><h1>Generate a doc site</h1></div>
            <p class="sub">You're at your project limit. Delete one from <a onclick="nav(event,'/projects')" style="color:var(--accent);cursor:pointer;">Projects</a> first, then come back here.</p>
          </div>\`;
        return;
      }

      document.getElementById('content').innerHTML = \`
        <div class="wrap-narrow">
          <div class="page-head"><h1>Generate a doc site</h1></div>
          <div class="step-label">Pick a repo</div>
          <input id="repo-filter" placeholder="Search your repos…" oninput="filterRepos(this.value)" />
          <div class="repo-list" id="repo-list">Loading your repos…</div>
          <div id="confirm-slot"></div>
          <div class="divider">or paste a public repo URL</div>
          <input id="paste-url" placeholder="https://github.com/owner/repo" oninput="onPasteInput()" />
          <div id="paste-confirm-slot"></div>
          <div id="error-slot"></div>
        </div>\`;
      loadRepos();
    }

    function visHintText(v) {
      return v === 'public'
        ? 'Public — anyone with the link can view the generated docs.'
        : 'Private — only you can view them. You can make it public anytime.';
    }
    function visChoiceHtml() {
      return \`
        <div class="vis-group">
          <span class="vis-label">Visibility</span>
          <button type="button" class="vis-pill \${state.visibility === 'private' ? 'active' : ''}" onclick="pickVis('private')">🔒 Private</button>
          <button type="button" class="vis-pill \${state.visibility === 'public' ? 'active' : ''}" onclick="pickVis('public')">🌐 Public</button>
        </div>
        <div class="vis-hint">\${visHintText(state.visibility)}</div>\`;
    }
    function pickVis(v) {
      state.visibility = v;
      if (state.selected) selectRepo(state.selected);
      else renderPasteConfirm();
    }

    async function loadRepos() {
      state.repos = await fetch('/api/repos').then(r => r.json());
      renderRepoList(state.repos);
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
    function projectTagHtml(existing) {
      if (!existing) return '';
      if (existing.status === 'done') return '<span class="proj-tag done">Generated</span>';
      if (existing.status === 'failed') return '<span class="proj-tag failed">Failed</span>';
      return '<span class="proj-tag building">Generating…</span>';
    }
    // The confirm panel's action depends on whether this repo already has a
    // project: done → go view it (never re-offer "Generate"), in-progress →
    // go watch it, failed → offer "Regenerate", new → plain "Generate".
    function confirmPanelHtml(titleHtml, existing, generateFn) {
      if (existing && existing.status === 'done') {
        return \`
          <div class="confirm-panel">
            <div class="who">\${titleHtml}</div>
            <p class="sub" style="margin:0 0 16px;">You've already generated docs for this repo.</p>
            <button class="btn full" onclick="nav(event,'/projects/\${existing.owner}/\${existing.repo}')">View project →</button>
          </div>\`;
      }
      if (existing && existing.status !== 'failed') {
        return \`
          <div class="confirm-panel">
            <div class="who">\${titleHtml}</div>
            <p class="sub" style="margin:0 0 16px;">This one's already generating.</p>
            <button class="btn full" onclick="location.href='/\${existing.owner}/\${existing.repo}/'">View progress →</button>
          </div>\`;
      }
      const isRegenerate = !!existing; // only 'failed' reaches here
      return \`
        <div class="confirm-panel">
          <div class="who">\${titleHtml}</div>
          \${visChoiceHtml()}
          <button id="generate-submit-btn" class="btn full" style="margin-top:16px" onclick="\${generateFn}()">\${isRegenerate ? 'Regenerate' : 'Generate'}</button>
        </div>\`;
    }

    function renderRepoList(repos) {
      const list = document.getElementById('repo-list');
      if (!list) return;
      if (!repos.length) { list.textContent = 'No repos found.'; return; }
      list.innerHTML = repos.map(r => {
        const isSelected = state.selected && state.selected.owner === r.owner && state.selected.repo === r.repo;
        const existing = findProject(r.owner, r.repo);
        return \`
          <div class="repo-item\${isSelected ? ' selected' : ''}" onclick='selectRepo(\${JSON.stringify(r)})'>
            <div class="top-line">
              \${r.fullName}
              \${r.private ? '<span class="priv">private</span>' : ''}
              \${r.language ? '<span class="lang">' + r.language + '</span>' : ''}
              \${projectTagHtml(existing)}
            </div>
            \${r.description ? '<div class="desc">' + r.description + '</div>' : ''}
          </div>\`;
      }).join('');
    }

    function filterRepos(q) {
      if (!state.repos) return;
      const needle = q.toLowerCase();
      renderRepoList(state.repos.filter(r => r.fullName.toLowerCase().includes(needle)));
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
      startJob({ owner: r.owner, repo: r.repo, description: r.description, language: r.language, avatarUrl: r.avatarUrl, visibility: state.visibility });
    }

    function generateFromPaste() {
      const url = document.getElementById('paste-url').value.trim();
      if (!url) return;
      startJob({ repo_url: url, visibility: state.visibility });
    }

    async function startJob(body) {
      const errSlot = document.getElementById('error-slot');
      if (errSlot) errSlot.innerHTML = '';
      const btn = document.getElementById('generate-submit-btn');
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
        if (btn) { btn.disabled = false; btn.innerHTML = originalBtnHtml; }
        if (errSlot) errSlot.innerHTML = '<div class="error-box">Network error — try again.</div>';
        return;
      }
      if (!res.ok) {
        if (btn) { btn.disabled = false; btn.innerHTML = originalBtnHtml; }
        if (errSlot) errSlot.innerHTML = '<div class="error-box">' + (data.error || 'unknown error') + '</div>';
        return;
      }
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

    function renderStageList(currentStage) {
      const list = document.getElementById('stage-list');
      if (!list) return;
      const currentIdx = STAGES.indexOf(currentStage);
      list.innerHTML = STAGES.map((s, i) => {
        const cls = i < currentIdx ? 'done' : (i === currentIdx ? 'active' : '');
        return \`
          <div class="stage-row \${cls}">
            <div class="stage-head"><span class="stage-dot"></span><span class="stage-label">\${STAGE_LABEL[s]}</span></div>
          </div>\`;
      }).join('');
    }

    function renderGenerating(info) {
      renderAppBar();
      state.currentGenInfo = info;
      state.currentStage = 'cloning';
      // info.createdAt is the real server-side job-creation timestamp (D1
      // projects.created_at) — using it instead of Date.now() means the
      // elapsed timer survives a page refresh instead of resetting to 0:00.
      state.genStart = info.createdAt || Date.now();
      stopGenTimer();
      document.getElementById('content').innerHTML = \`
        <div class="gen-wrap">
          <div class="gen-repo">
            <img src="\${info.avatarUrl}" alt="" />
            <span>\${info.owner}/\${info.repo}</span>
          </div>
          <div class="gen-col">
            <div class="gen-elapsed" id="gen-elapsed">0:00 elapsed</div>
            <div id="stage-list"></div>
            <div id="result-slot"></div>
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
      const m = Math.floor(s / 60);
      const rem = String(s % 60).padStart(2, '0');
      el.textContent = m + ':' + rem + ' elapsed';
    }

    async function poll(jobId, owner, repo) {
      const res = await fetch('/api/status/' + jobId);
      const data = await res.json();
      const stageList = document.getElementById('stage-list');
      if (!stageList) return; // page already re-rendered elsewhere

      if (data.status === 'done') {
        stopGenTimer();
        setTimeout(() => { window.location.href = '/' + owner + '/' + repo + '/'; }, 700);
        return;
      }
      if (data.status === 'failed') {
        stopGenTimer();
        document.getElementById('result-slot').innerHTML = \`
          <div class="error-box">Generation failed.\\n\${data.error || ''}</div>
          <div style="display:flex; gap:8px; margin-top:12px;">
            <button class="btn" onclick="retryJob('\${owner}','\${repo}')">Retry</button>
            <button class="btn ghost" onclick="backToGenerate()">Back to generate</button>
          </div>
        \`;
        return;
      }
      state.currentStage = data.status;
      renderStageList(data.status);
      setTimeout(() => poll(jobId, owner, repo), 2000);
    }

    async function backToGenerate() {
      stopGenTimer();
      history.pushState({}, '', '/generate');
      await refreshProjects();
      route();
    }

    main();
  </script>
</body>
</html>`;
}

// Shown when someone hits a private site they don't own (or aren't signed in
// for). Never leaks any of the real content. `authed` = the viewer has a valid
// session but simply isn't the owner (so signing in again won't help them).
export function privateSitePage(owner: string, repo: string, authed: boolean): string {
  const body = authed
    ? `<p>The documentation for <code>${owner}/${repo}</code> is private, and it isn't yours to view.</p>
       <button class="btn" onclick="location.href='/projects'">Go to your projects</button>`
    : `<p>The documentation for <code>${owner}/${repo}</code> is private. If it's yours, sign in to view it.</p>
       <button class="btn" onclick="location.href='/auth/github'">Sign in with GitHub</button>`;
  return `<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Private documentation — DeepDoc</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
<style>
  :root {
    --surface: oklch(16% 0.008 250); --surface-raised: oklch(20% 0.009 250);
    --ink: oklch(93% 0.004 250); --ink-muted: oklch(64% 0.012 250);
    --line-strong: oklch(55% 0.014 250 / 34%); --accent: #C2FF4D; --accent-ink: oklch(16% 0.008 250);
    --font-sans: 'DM Sans', -apple-system, sans-serif; --font-mono: 'JetBrains Mono', ui-monospace, monospace;
  }
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; background: var(--surface); color: var(--ink); font-family: var(--font-sans); display: flex; align-items: center; justify-content: center; padding: 40px 24px; }
  .card { width: 100%; max-width: 460px; border: 1px solid var(--line-strong); border-radius: 16px; background: var(--surface-raised); padding: 32px; box-shadow: 0 24px 60px -20px rgba(0,0,0,0.6); }
  h1 { font-size: 18px; font-weight: 700; margin: 0 0 10px; letter-spacing: -0.01em; }
  p { font-size: 13.5px; line-height: 1.7; color: var(--ink-muted); margin: 0 0 22px; }
  code { font-family: var(--font-mono); color: var(--ink); }
  .btn { height: 40px; border-radius: 8px; border: none; cursor: pointer; padding: 0 16px; background: var(--accent); color: var(--accent-ink); font-family: var(--font-sans); font-size: 13.5px; font-weight: 600; }
</style>
</head>
<body>
  <div class="card">
    <h1>This documentation is private</h1>
    ${body}
  </div>
</body>
</html>`;
}

// Shown when a repo's record says "done" but the actual generated files are
// gone (e.g. a runner restart happened before this site's content made it to
// R2) — plain and honest instead of silently falling back to the dashboard.
export function stalePageHtml(owner: string, repo: string): string {
  return `<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Site unavailable — DeepDoc</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
<style>
  :root {
    --surface: oklch(16% 0.008 250); --surface-raised: oklch(20% 0.009 250);
    --ink: oklch(93% 0.004 250); --ink-muted: oklch(64% 0.012 250);
    --line-strong: oklch(55% 0.014 250 / 34%); --accent: #C2FF4D; --accent-ink: oklch(16% 0.008 250);
    --font-sans: 'DM Sans', -apple-system, sans-serif; --font-mono: 'JetBrains Mono', ui-monospace, monospace;
  }
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; background: var(--surface); color: var(--ink); font-family: var(--font-sans); display: flex; align-items: center; justify-content: center; padding: 40px 24px; }
  .card { width: 100%; max-width: 460px; border: 1px solid var(--line-strong); border-radius: 16px; background: var(--surface-raised); padding: 32px; box-shadow: 0 24px 60px -20px rgba(0,0,0,0.6); }
  h1 { font-size: 18px; font-weight: 700; margin: 0 0 10px; letter-spacing: -0.01em; }
  p { font-size: 13.5px; line-height: 1.7; color: var(--ink-muted); margin: 0 0 22px; }
  code { font-family: var(--font-mono); color: var(--ink); }
  .btn { height: 40px; border-radius: 8px; border: none; cursor: pointer; padding: 0 16px; background: var(--accent); color: var(--accent-ink); font-family: var(--font-sans); font-size: 13.5px; font-weight: 600; }
</style>
</head>
<body>
  <div class="card">
    <h1>This site is no longer available</h1>
    <p><code>${owner}/${repo}</code> was generated successfully, but the underlying files are gone — this happens after a backend restart on an older build. Regenerating will fix it for good going forward.</p>
    <button class="btn" onclick="location.href='/projects/${owner}/${repo}'">Regenerate</button>
  </div>
</body>
</html>`;
}
