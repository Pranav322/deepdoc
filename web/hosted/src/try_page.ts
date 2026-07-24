// Server-rendered by the Worker (not Astro) so auth cookies + API calls stay
// same-origin. This is its own visual identity from deepdoc.tech's marketing
// site — same brand accent (#C2FF4D) for continuity, but its own tinted
// neutral scale, restrained accent usage, and editorial/technical layout.
// Do not reintroduce the old "borrow the marketing card recipe verbatim"
// approach — this app now owns its design system (see docs/HOSTED_UI_SPEC.md).
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

  /* ── App bar — matches deepdoc.tech's Header.astro recipe so both
     domains read as one product: same 52px sticky bar, same blur, same
     brand mark (see web/src/components/Logo.astro, duplicated here since
     the Worker can't import an Astro component). ─────────────────────── */
  .appbar { position: sticky; top: 0; z-index: 10; border-bottom: 1px solid var(--line); background: color-mix(in oklab, var(--surface) 86%, transparent); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px); flex-shrink: 0; }
  .appbar-inner { max-width: 880px; margin: 0 auto; height: 52px; padding: 0 24px; display: flex; align-items: center; justify-content: space-between; }
  .brand { font-family: var(--font-sans); font-weight: 600; font-size: 1.15rem; text-decoration: none; letter-spacing: -0.015em; color: var(--ink); display: flex; align-items: center; cursor: pointer; }
  .dd-mark { display: block; flex-shrink: 0; width: 1.16em; height: 1.16em; margin-right: 0.04em; transform: translateY(-0.05em); }
  .dd-mark .dd-front { fill: var(--accent); }
  .dd-mark .dd-echo { fill: none; stroke: var(--accent); stroke-width: 2; stroke-linecap: round; }
  .dd-mark .dd-echo-1 { opacity: 0.4; } .dd-mark .dd-echo-2 { opacity: 0.18; }
  .cloud-tag { font-family: var(--font-mono); font-size: 10.5px; color: var(--ink-faint); border: 1px solid var(--line-strong); border-radius: 999px; padding: 2px 8px; margin-left: 10px; text-transform: uppercase; letter-spacing: 0.04em; }
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

  /* ── Sign-in prompt (unauthenticated root) ───────────────────────────
     No hero, no marketing copy — deepdoc.tech's own landing page already
     sells the product; this is just the gate you hit on the way in from
     its "Try it free" CTA. */
  .signin-wrap { flex: 1; display: flex; align-items: center; justify-content: center; padding: 40px 24px; }
  .signin-card { width: 100%; max-width: 400px; text-align: center; }
  .signin-card h1 { font-size: 22px; font-weight: 700; letter-spacing: -0.02em; margin: 0 0 10px; }
  .signin-card p { font-size: 13.5px; line-height: 1.7; color: var(--ink-muted); margin: 0 0 22px; }
  .signin-card ul { text-align: left; margin: 0 0 26px; padding-left: 18px; font-size: 13px; color: var(--ink-muted); line-height: 1.8; }

  /* ── Section headers (shared across authed views) ──────────────── */
  .page-head { display: flex; align-items: baseline; justify-content: space-between; padding: 40px 0 24px; flex-wrap: wrap; gap: 12px; }
  .page-head h1 { font-size: 22px; font-weight: 700; letter-spacing: -0.02em; margin: 0; }
  .empty-state { text-align: center; padding: 80px 20px; }
  .empty-state h2 { font-size: 17px; font-weight: 600; margin: 0 0 8px; }
  .empty-state p { font-size: 13.5px; color: var(--ink-muted); margin: 0 0 24px; }
  .back-link { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--ink-muted); text-decoration: none; margin: 28px 0 4px; cursor: pointer; }
  .back-link:hover { color: var(--ink); }

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
  .stage-row { border-bottom: 1px solid var(--line); padding: 14px 2px; cursor: pointer; }
  .stage-row:last-child { border-bottom: none; }
  .stage-head { display: flex; align-items: center; gap: 11px; }
  .stage-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--line-strong); flex-shrink: 0; }
  .stage-row.active .stage-dot { background: var(--accent); box-shadow: 0 0 8px rgba(194,255,77,0.5); animation: pulse 1.2s ease-in-out infinite; }
  .stage-row.done .stage-dot { background: var(--accent); }
  .stage-label { font-size: 14px; color: var(--ink-muted); flex: 1; }
  .stage-row.active .stage-label, .stage-row.done .stage-label { color: var(--ink); font-weight: 500; }
  .stage-chev { color: var(--ink-faint); font-size: 11px; transition: transform 0.15s; }
  .stage-row.expanded .stage-chev { transform: rotate(90deg); }
  .stage-detail { max-height: 0; overflow: hidden; transition: max-height 0.2s ease; }
  .stage-row.expanded .stage-detail { max-height: 160px; margin: 10px 0 2px 19px; }
  .stage-detail ul { margin: 0; padding-left: 16px; font-size: 12.5px; color: var(--ink-muted); line-height: 1.85; }
  .gen-result { margin-top: 26px; }

  .sub { color: var(--ink-muted); font-size: 13.5px; line-height: 1.7; }
</style>
</head>
<body>
  <div id="appbar-slot"></div>
  <div id="content"></div>
  <script>
    const state = {
      me: null, projects: [], quota: null, repos: null, selected: null, visibility: 'private',
      genStart: null, genTimer: null, expandedStage: null, ddOpen: false,
    };
    const STAGES = ['cloning', 'generating', 'building'];
    const STAGE_LABEL = { cloning: 'Cloning repository', generating: 'Generating documentation', building: 'Building your site' };
    const STAGE_DETAIL = {
      cloning: ['Pulling the repository down over your GitHub token'],
      generating: [
        'Tracing the call graph and clustering related code',
        'Naming domain clusters, planning page structure',
        'Writing pages grounded in the actual code',
      ],
      building: ['Assembling the static site', 'Wiring up navigation and search'],
    };

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
        </svg>eepDoc<span class="cloud-tag">cloud</span>\`;
    }

    // ── Sign-in prompt (unauthenticated root) — no hero, no marketing copy.
    // deepdoc.tech's own landing page is the pitch; its "Try it free" CTA
    // sends people straight here, so this is just the gate, not a second
    // sales pitch.
    function renderLoggedOut() {
      document.getElementById('appbar-slot').innerHTML = \`
        <header class="appbar"><div class="appbar-inner">
          <span class="brand">\${brandMarkHtml()}</span>
        </div></header>\`;
      document.getElementById('content').innerHTML = \`
        <div class="signin-wrap">
          <div class="signin-card">
            <h1>Sign in to generate docs</h1>
            <p>DeepDoc needs read access to clone the repo you pick and generate its docs. We only use it for that.</p>
            <ul>
              <li>Nothing is posted or changed in your GitHub account</li>
              <li>Generated sites are private by default — you choose if to make one public</li>
              <li>You can revoke access from GitHub at any time</li>
            </ul>
            <button class="btn full" onclick="location.href='/auth/github'">Continue with GitHub</button>
          </div>
        </div>\`;
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
          <button class="btn full" style="margin-top:16px" onclick="\${generateFn}()">\${isRegenerate ? 'Regenerate' : 'Generate'}</button>
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
      const res = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
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

    function stageDetailHtml(stage) {
      const items = STAGE_DETAIL[stage] || [];
      return '<ul>' + items.map(t => '<li>' + t + '</li>').join('') + '</ul>';
    }

    function renderStageList(currentStage) {
      const list = document.getElementById('stage-list');
      if (!list) return;
      const currentIdx = STAGES.indexOf(currentStage);
      list.innerHTML = STAGES.map((s, i) => {
        const cls = i < currentIdx ? 'done' : (i === currentIdx ? 'active' : '');
        const isExpanded = state.expandedStage === s || (state.expandedStage === null && i === currentIdx);
        return \`
          <div class="stage-row \${cls} \${isExpanded ? 'expanded' : ''}" onclick="toggleStage('\${s}')">
            <div class="stage-head"><span class="stage-dot"></span><span class="stage-label">\${STAGE_LABEL[s]}</span><span class="stage-chev">▸</span></div>
            <div class="stage-detail">\${stageDetailHtml(s)}</div>
          </div>\`;
      }).join('');
    }
    function toggleStage(s) {
      state.expandedStage = state.expandedStage === s ? '__none__' : s;
      renderStageList(state.currentStage || 'cloning');
    }

    function renderGenerating(info) {
      renderAppBar();
      state.currentGenInfo = info;
      state.currentStage = 'cloning';
      state.expandedStage = null;
      state.genStart = Date.now();
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
