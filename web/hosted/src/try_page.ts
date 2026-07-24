// Server-rendered by the Worker (not Astro) so auth cookies + API calls stay
// same-origin during local validation — in production this page is served
// from the same Cloudflare route as the marketing site, so nothing changes
// when we wire it up for real. Every color/shadow/radius below is copied
// verbatim from web/src/styles/global.css (.feat-card corner-glow recipe,
// .hero-window shadow, the primary CTA button recipe from index.astro) —
// do not invent new visual treatments here, reuse what the main site already
// has so this page doesn't read as a bolted-on separate app.
export function tryPageHtml(): string {
  return `<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Try DeepDoc — generate docs from a GitHub repo</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
<style>
  :root {
    --color-ink: #F0EFEA; --color-ink-muted: #7E7D76; --color-ink-faint: #44433C;
    --color-surface: #09090D; --color-surface-raised: #10101A; --color-surface-high: #181820;
    --color-line: rgba(255,255,255,0.06); --color-line-strong: rgba(255,255,255,0.11);
    --color-accent: #C2FF4D; --color-accent-dim: rgba(194,255,77,0.09);
    --font-sans: 'DM Sans', ui-sans-serif, system-ui, sans-serif;
    --font-mono: 'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; background: var(--color-surface); color: var(--color-ink);
    font-family: var(--font-sans); display: flex; flex-direction: column;
  }
  #content { flex: 1; display: flex; align-items: center; justify-content: center; padding: 40px 24px; }
  /* Persistent top bar (logged-in views only) */
  .appbar { border-bottom: 1px solid var(--color-line); background: color-mix(in oklab, var(--color-surface-raised) 60%, var(--color-surface)); }
  .appbar-inner { max-width: 1000px; margin: 0 auto; height: 56px; padding: 0 20px; display: flex; align-items: center; justify-content: space-between; }
  .brand { font-family: var(--font-mono); font-weight: 600; font-size: 15px; color: var(--color-ink); text-decoration: none; letter-spacing: -0.01em; }
  .brand .dot { color: var(--color-accent); }
  .account-chip { display: flex; align-items: center; gap: 8px; height: auto; background: transparent; border: 1px solid var(--color-line-strong); border-radius: 999px; padding: 3px 12px 3px 3px; color: var(--color-ink); font-family: var(--font-sans); font-size: 13px; font-weight: 500; }
  .account-chip img { width: 26px; height: 26px; border-radius: 50%; }
  /* Account view */
  .account-head { display: flex; align-items: center; gap: 14px; margin-bottom: 6px; }
  .account-avatar { width: 52px; height: 52px; border-radius: 50%; border: 1px solid var(--color-line-strong); }
  .account-name { font-size: 18px; font-weight: 700; }
  .account-sub { font-size: 12.5px; color: var(--color-ink-muted); font-family: var(--font-mono); margin-top: 2px; }
  .account-stat { display: flex; align-items: center; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid var(--color-line); font-size: 13.5px; color: var(--color-ink-muted); }
  .account-stat strong { color: var(--color-ink); font-family: var(--font-mono); }
  /* Visibility choice pills (generate flow) */
  .vis-group { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
  .vis-label { font-family: var(--font-mono); font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--color-ink-faint); margin-right: 2px; }
  .vis-pill { height: auto; padding: 5px 12px; font-size: 12px; border-radius: 999px; background: var(--color-surface); border: 1px solid var(--color-line-strong); color: var(--color-ink-muted); font-family: var(--font-mono); }
  .vis-pill.active { background: var(--color-accent-dim); border-color: rgba(194,255,77,0.4); color: var(--color-accent); }
  .vis-hint { font-size: 11.5px; color: var(--color-ink-muted); margin-bottom: 12px; line-height: 1.5; }
  /* Per-project visibility toggle badge */
  .proj-vis { height: auto; padding: 3px 10px; font-size: 10.5px; border-radius: 999px; font-family: var(--font-mono); border: 1px solid var(--color-line-strong); background: var(--color-surface-high); }
  .proj-vis.priv { color: var(--color-ink-muted); }
  .proj-vis.pub { color: var(--color-accent); border-color: rgba(194,255,77,0.35); background: var(--color-accent-dim); }
  /* Card recipe = .feat-card from global.css */
  .card {
    width: 100%; max-width: 560px; border-radius: 20px;
    border: 1px solid var(--color-line-strong);
    background:
      radial-gradient(120% 90% at 100% 0%, color-mix(in srgb, var(--color-accent) 5%, transparent) 0%, transparent 55%),
      color-mix(in oklab, var(--color-surface-raised) 55%, var(--color-surface));
    box-shadow: 0 0 0 1px rgba(194, 255, 77, 0.05), 0 30px 90px rgba(0, 0, 0, 0.52);
    padding: 34px;
  }
  h1 { font-family: var(--font-sans); font-size: 20px; font-weight: 700; letter-spacing: -0.02em; margin: 0 0 8px; color: var(--color-ink); }
  h2 { font-size: 13px; margin: 26px 0 10px; color: var(--color-ink-muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.07em; }
  p.sub { color: var(--color-ink-muted); font-size: 13.5px; margin: 0 0 26px; line-height: 1.75; }
  input {
    width: 100%; padding: 11px 13px; border-radius: 8px; border: 1px solid var(--color-line-strong);
    background: var(--color-surface); color: var(--color-ink); font-family: var(--font-mono); font-size: 13px;
    margin-bottom: 10px; outline: none; transition: border-color 0.15s;
  }
  input:focus { border-color: var(--color-accent); }
  /* Button recipe = primary CTA from index.astro (rounded-lg, mono font, opacity hover) */
  button {
    height: 40px; border-radius: 8px; border: none; cursor: pointer; padding: 0 16px;
    background: var(--color-accent); color: var(--color-surface);
    font-family: var(--font-mono); font-size: 13px; font-weight: 500;
    transition: opacity 0.15s;
  }
  button:hover:not(:disabled) { opacity: 0.88; }
  button.secondary { background: var(--color-surface-high); color: var(--color-ink); border: 1px solid var(--color-line-strong); }
  button.danger { height: auto; background: transparent; color: #ff6b6b; border: 1px solid rgba(255,107,107,0.35); padding: 6px 10px; font-size: 11.5px; }
  button:disabled { opacity: 0.4; cursor: not-allowed; }
  button.full { width: 100%; }
  a.ghlink { color: var(--color-accent); text-decoration: none; }
  .badge { display: inline-block; font-family: var(--font-mono); font-size: 11px; color: var(--color-ink-muted); }
  .header-row { display: flex; align-items: center; gap: 10px; margin-bottom: 22px; }
  .header-row img { width: 34px; height: 34px; border-radius: 50%; border: 1px solid var(--color-line-strong); }
  .quota { margin-left: auto; font-family: var(--font-mono); font-size: 11px; color: var(--color-ink-muted); }
  .project-row {
    display: flex; align-items: center; gap: 10px; padding: 13px; border: 1px solid var(--color-line);
    border-radius: 12px; margin-bottom: 8px; font-size: 13px;
  }
  .project-row .name { font-family: var(--font-mono); flex: 1; }
  .project-row .pill, .repo-item .pill {
    font-family: var(--font-mono); font-size: 10px; padding: 3px 9px; border-radius: 999px;
    background: var(--color-accent-dim); color: var(--color-accent);
  }
  .repo-list { max-height: 260px; overflow-y: auto; border: 1px solid var(--color-line-strong); border-radius: 10px; margin-bottom: 12px; }
  .repo-item { padding: 10px 13px; cursor: pointer; border-bottom: 1px solid var(--color-line); transition: background 0.1s; }
  .repo-item:hover { background: var(--color-surface-high); }
  .repo-item:last-child { border-bottom: none; }
  .repo-item.selected { background: var(--color-accent-dim); box-shadow: inset 2px 0 0 var(--color-accent); }
  .repo-item .top-line { display: flex; align-items: center; gap: 8px; font-family: var(--font-mono); font-size: 12.5px; }
  .repo-item .priv { color: var(--color-ink-faint); font-size: 10px; }
  .repo-item .desc { color: var(--color-ink-muted); font-size: 11.5px; margin-top: 3px; }
  .divider { text-align: center; color: var(--color-ink-faint); font-size: 12px; margin: 16px 0; }
  .confirm-bar {
    display: flex; align-items: center; gap: 10px; padding: 14px; border-radius: 12px;
    background: var(--color-accent-dim); border: 1px solid rgba(194,255,77,0.2); margin-bottom: 14px;
  }
  .confirm-bar .who { font-family: var(--font-mono); font-size: 13px; flex: 1; }
  .repo-card {
    display: flex; align-items: flex-start; gap: 14px; padding: 18px; border-radius: 12px;
    border: 1px solid var(--color-line-strong); background: var(--color-surface); margin-bottom: 22px;
  }
  .repo-card img { width: 44px; height: 44px; border-radius: 50%; border: 1px solid var(--color-line-strong); }
  .repo-card .title { font-family: var(--font-mono); font-size: 15px; font-weight: 600; }
  .repo-card .desc { color: var(--color-ink-muted); font-size: 13px; margin-top: 5px; line-height: 1.5; }
  .repo-card .meta { display: flex; gap: 8px; margin-top: 10px; }
  .progress-stage { display: flex; align-items: center; gap: 10px; font-size: 13.5px; color: var(--color-ink-muted); margin-bottom: 6px; }
  .progress-stage.active { color: var(--color-ink); }
  .progress-stage .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--color-line-strong); flex-shrink: 0; }
  .progress-stage.active .dot { background: var(--color-accent); box-shadow: 0 0 8px rgba(194,255,77,0.5); animation: pulse 1.2s ease-in-out infinite; }
  .progress-stage.done .dot { background: var(--color-accent); box-shadow: none; animation: none; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
  .error-box { color: #ff8a8a; font-size: 13px; background: rgba(255,107,107,0.08); border: 1px solid rgba(255,107,107,0.25); border-radius: 10px; padding: 12px; margin-top: 16px; white-space: pre-wrap; }
</style>
</head>
<body>
  <header id="appbar" class="appbar" style="display:none"></header>
  <div id="content"><div class="card" id="app">Loading…</div></div>
  <script>
    const state = { me: null, projects: [], quota: null, repos: null, selected: null, visibility: 'private' };
    const STAGES = ['cloning', 'generating', 'building'];
    const STAGE_LABEL = { cloning: 'Cloning repository', generating: 'Generating documentation', building: 'Building your site' };

    async function main() {
      state.me = await fetch('/api/me').then(r => r.json());
      renderAppBar();
      if (!state.me.authenticated) return renderLoggedOut();
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

    // SPA nav — pushState + re-render, so back/forward and the header links work
    // without a full reload. route() only handles the logged-in views.
    function route() {
      renderAppBar();
      if (window.location.pathname === '/account') return renderAccount();
      return renderLoggedIn();
    }
    function nav(e, path) { if (e) e.preventDefault(); history.pushState({}, '', path); route(); return false; }
    window.addEventListener('popstate', () => { if (state.me && state.me.authenticated) route(); });

    function renderAppBar() {
      const bar = document.getElementById('appbar');
      if (!state.me || !state.me.authenticated) { bar.style.display = 'none'; bar.innerHTML = ''; return; }
      bar.style.display = 'block';
      bar.innerHTML = \`
        <div class="appbar-inner">
          <a class="brand" href="/try" onclick="return nav(event,'/try')"><span class="dot">D</span>eepDoc</a>
          <button class="account-chip" onclick="nav(event,'/account')">
            <img src="\${state.me.avatarUrl}" alt="" /><span>\${state.me.login}</span>
          </button>
        </div>\`;
    }

    function renderAccount() {
      if (!state.me || !state.me.authenticated) { renderLoggedOut(); return; }
      const q = state.quota || {};
      document.getElementById('app').innerHTML = \`
        <div class="account-head">
          <img class="account-avatar" src="\${state.me.avatarUrl}" alt="" />
          <div>
            <div class="account-name">\${state.me.login}</div>
            <div class="account-sub">@\${state.me.login} · signed in with GitHub</div>
          </div>
        </div>
        <h2>Usage\${q.unlimited ? ' · <span style="color:var(--color-accent)">unlimited</span>' : ''}</h2>
        <div class="account-stat"><span>Saved projects</span><strong>\${q.savedProjects ?? 0}\${q.maxSavedProjects != null ? ' / ' + q.maxSavedProjects : ''}</strong></div>
        <div class="account-stat"><span>Generations today</span><strong>\${q.startsInWindow ?? 0}\${q.maxStartsPerDay != null ? ' / ' + q.maxStartsPerDay : ''}</strong></div>
        <div style="display:flex; gap:10px; margin-top:24px;">
          <button onclick="logout()">Log out</button>
          <button class="secondary" onclick="nav(event,'/try')">Back to projects</button>
        </div>
      \`;
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

    function renderLoggedOut() {
      document.getElementById('app').innerHTML = \`
        <h1>Try DeepDoc</h1>
        <p class="sub">Sign in with GitHub, pick a repo (yours, public or private — or paste any public URL), and watch DeepDoc generate real docs from it. No CLI needed.</p>
        <button class="full" onclick="location.href='/auth/github'">Sign in with GitHub</button>
      \`;
    }

    function visHintText(v) {
      return v === 'public'
        ? 'Public — anyone with the link can view the generated docs.'
        : 'Private — only you can view them. You can make it public anytime.';
    }
    function visChoiceHtml() {
      return \`
        <div style="width:100%">
          <div class="vis-group">
            <span class="vis-label">Who can see these docs?</span>
            <button type="button" class="vis-pill \${state.visibility === 'private' ? 'active' : ''}" onclick="pickVis('private')">🔒 Private</button>
            <button type="button" class="vis-pill \${state.visibility === 'public' ? 'active' : ''}" onclick="pickVis('public')">🌐 Public</button>
          </div>
          <div class="vis-hint">\${visHintText(state.visibility)}</div>
        </div>\`;
    }
    function pickVis(v) {
      state.visibility = v;
      document.querySelectorAll('.vis-pill').forEach(el => {
        el.classList.toggle('active', el.textContent.trim().toLowerCase().includes(v));
      });
      document.querySelectorAll('.vis-hint').forEach(el => { el.textContent = visHintText(v); });
    }

    function renderLoggedIn() {
      state.selected = null;
      state.visibility = 'private';
      const q = state.quota;
      const atQuota = q && q.maxSavedProjects != null && q.savedProjects >= q.maxSavedProjects;
      const projectsHtml = state.projects.length
        ? state.projects.map(p => \`
            <div class="project-row">
              <span class="name">\${p.owner}/\${p.repo}</span>
              <button class="proj-vis \${p.visibility === 'public' ? 'pub' : 'priv'}" title="Click to toggle visibility"
                onclick="toggleVisibility('\${p.owner}','\${p.repo}','\${p.visibility || 'private'}')">
                \${p.visibility === 'public' ? 'Public' : 'Private'}
              </button>
              <span class="pill">\${p.status}</span>
              \${p.status === 'done' ? \`<a class="ghlink" href="/\${p.owner}/\${p.repo}/" target="_blank" title="If it does not load right away, wait a couple of minutes and try again">Open →</a>\` : ''}
              <button class="danger" onclick="deleteProject('\${p.owner}','\${p.repo}')">Delete</button>
            </div>\`).join('')
        : '<p class="sub" style="margin-bottom:8px">No projects yet.</p>';

      document.getElementById('app').innerHTML = \`
        <h1>Your projects</h1>
        <p class="sub" style="margin-bottom:14px">Generate documentation from a GitHub repo. New docs are private by default — only you can see them until you make them public.</p>
        \${projectsHtml}
        <h2>Generate new</h2>
        \${atQuota
          ? '<p class="sub">You are at your project limit — delete one above to generate another.</p>'
          : \`
            <input id="repo-filter" placeholder="Search your repos…" oninput="filterRepos(this.value)" />
            <div class="repo-list" id="repo-list">Loading your repos…</div>
            <div id="confirm-slot"></div>
            <div class="divider">— or —</div>
            <input id="paste-url" placeholder="https://github.com/owner/repo (any public repo)" />
            \${visChoiceHtml()}
            <button class="full secondary" id="paste-go" onclick="generateFromPaste()">Generate from URL</button>
            <div id="error-slot"></div>
          \`}
      \`;
      if (!atQuota) loadRepos();
    }

    async function toggleVisibility(owner, repo, current) {
      const next = current === 'public' ? 'private' : 'public';
      await fetch('/api/projects/' + owner + '/' + repo + '/visibility', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ visibility: next }),
      });
      await refreshProjects();
      renderLoggedIn();
    }

    async function loadRepos() {
      state.repos = await fetch('/api/repos').then(r => r.json());
      renderRepoList(state.repos);
    }

    function renderRepoList(repos) {
      const list = document.getElementById('repo-list');
      if (!list) return;
      if (!repos.length) { list.textContent = 'No repos found.'; return; }
      list.innerHTML = repos.map(r => {
        const isSelected = state.selected && state.selected.owner === r.owner && state.selected.repo === r.repo;
        return \`
          <div class="repo-item\${isSelected ? ' selected' : ''}" onclick='selectRepo(\${JSON.stringify(r)})'>
            <div class="top-line">
              \${r.fullName}
              \${r.private ? '<span class="priv">private</span>' : ''}
              \${r.language ? '<span class="pill">' + r.language + '</span>' : ''}
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
      // A private GitHub repo almost never wants public docs — default the
      // choice to private either way, but this keeps it obvious.
      renderRepoList(state.repos);
      document.getElementById('confirm-slot').innerHTML = \`
        <div class="confirm-bar" style="flex-wrap:wrap; gap:12px;">
          <span class="who">Generate docs for <strong>\${repo.fullName}</strong>?</span>
          \${visChoiceHtml()}
          <button onclick="confirmGenerate()">Generate</button>
        </div>
      \`;
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
      // Move the URL bar to the repo's real destination now — the progress
      // view renders there, and once done a real navigation to this same
      // URL serves the actual generated site (no separate "click to open").
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

    function renderGenerating(info) {
      state.currentGenInfo = info;
      document.getElementById('app').innerHTML = \`
        <h1>Generating your docs</h1>
        <p class="sub">This runs the real DeepDoc pipeline against your repo — usually a few minutes.</p>
        <div class="repo-card">
          <img src="\${info.avatarUrl}" alt="" />
          <div>
            <div class="title">\${info.owner}/\${info.repo}</div>
            \${info.description ? '<div class="desc">' + info.description + '</div>' : ''}
            \${info.language ? '<div class="meta"><span class="pill">' + info.language + '</span></div>' : ''}
          </div>
        </div>
        <div id="stage-list"></div>
        <div id="result-slot"></div>
      \`;
      renderStages('cloning');
    }

    function renderStages(currentStage) {
      const list = document.getElementById('stage-list');
      if (!list) return;
      const currentIdx = STAGES.indexOf(currentStage);
      list.innerHTML = STAGES.map((s, i) => {
        const cls = i < currentIdx ? 'done' : (i === currentIdx ? 'active' : '');
        return '<div class="progress-stage ' + cls + '"><span class="dot"></span>' + STAGE_LABEL[s] + (i === currentIdx ? '…' : '') + '</div>';
      }).join('');
    }

    async function poll(jobId, owner, repo) {
      const res = await fetch('/api/status/' + jobId);
      const data = await res.json();
      const stageList = document.getElementById('stage-list');
      if (!stageList) return; // page already re-rendered elsewhere

      if (data.status === 'done') {
        renderStages('building');
        document.querySelectorAll('.progress-stage').forEach(el => el.classList.add('done'));
        document.getElementById('result-slot').innerHTML = '<div class="confirm-bar" style="margin-top:16px"><span class="who">Docs ready — opening…</span></div><p class="sub" style="margin-top:10px;margin-bottom:0">If it does not load right away, wait a couple of minutes and open the link again.</p>';
        // Real navigation to the same URL the progress view is already on —
        // the Worker now proxies the finished static site at this path.
        setTimeout(() => { window.location.href = '/' + owner + '/' + repo + '/'; }, 700);
        return;
      }
      if (data.status === 'failed') {
        document.getElementById('result-slot').innerHTML = \`
          <div class="error-box">Generation failed.\\n\${data.error || ''}</div>
          <div style="display:flex; gap:8px; margin-top:10px;">
            <button onclick="retryJob('\${owner}','\${repo}')">Retry</button>
            <button class="secondary" onclick="backToProjects()">Back to projects</button>
          </div>
        \`;
        return;
      }
      renderStages(data.status);
      setTimeout(() => poll(jobId, owner, repo), 2000);
    }

    async function backToProjects() {
      history.pushState({}, '', '/try');
      await refreshProjects();
      renderLoggedIn();
    }

    async function deleteProject(owner, repo) {
      await fetch('/api/projects/' + owner + '/' + repo, { method: 'DELETE' });
      await refreshProjects();
      renderLoggedIn();
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
       <button onclick="location.href='/try'">Go to your dashboard</button>`
    : `<p>The documentation for <code>${owner}/${repo}</code> is private. If it's yours, sign in to view it.</p>
       <button onclick="location.href='/auth/github'">Sign in with GitHub</button>`;
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
    --surface: #09090D; --surface-raised: #10101A; --ink: #F0EFEA; --ink-muted: #9A988E;
    --line-strong: rgba(255,255,255,0.16); --accent: #C2FF4D;
    --font-sans: 'DM Sans', -apple-system, sans-serif; --font-mono: 'JetBrains Mono', ui-monospace, monospace;
  }
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; background: var(--surface); color: var(--ink); font-family: var(--font-sans); display: flex; align-items: center; justify-content: center; padding: 40px 24px; }
  .card { width: 100%; max-width: 480px; border: 1px solid var(--line-strong); border-radius: 20px; background: var(--surface-raised); padding: 34px; box-shadow: 0 0 0 1px rgba(194,255,77,0.05), 0 30px 90px rgba(0,0,0,0.52); }
  h1 { font-size: 19px; font-weight: 700; margin: 0 0 10px; }
  p { font-size: 13.5px; line-height: 1.7; color: var(--ink-muted); margin: 0 0 22px; }
  code { font-family: var(--font-mono); color: var(--ink); }
  button { height: 40px; border-radius: 8px; border: none; cursor: pointer; padding: 0 16px; background: var(--accent); color: var(--surface); font-family: var(--font-mono); font-size: 13px; font-weight: 500; }
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
    --surface: #09090D; --surface-raised: #10101A; --ink: #F0EFEA; --ink-muted: #9A988E;
    --line-strong: rgba(255,255,255,0.16); --accent: #C2FF4D;
    --font-sans: 'DM Sans', -apple-system, sans-serif; --font-mono: 'JetBrains Mono', ui-monospace, monospace;
  }
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; background: var(--surface); color: var(--ink); font-family: var(--font-sans); display: flex; align-items: center; justify-content: center; padding: 40px 24px; }
  .card { width: 100%; max-width: 480px; border: 1px solid var(--line-strong); border-radius: 20px; background: var(--surface-raised); padding: 34px; box-shadow: 0 0 0 1px rgba(194,255,77,0.05), 0 30px 90px rgba(0,0,0,0.52); }
  h1 { font-size: 19px; font-weight: 700; margin: 0 0 10px; }
  p { font-size: 13.5px; line-height: 1.7; color: var(--ink-muted); margin: 0 0 22px; }
  code { font-family: var(--font-mono); color: var(--ink); }
  button { height: 40px; border-radius: 8px; border: none; cursor: pointer; padding: 0 16px; background: var(--accent); color: var(--surface); font-family: var(--font-mono); font-size: 13px; font-weight: 500; }
</style>
</head>
<body>
  <div class="card">
    <h1>This site is no longer available</h1>
    <p><code>${owner}/${repo}</code> was generated successfully, but the underlying files are gone — this happens after a backend restart on an older build. Regenerating will fix it for good going forward.</p>
    <button onclick="location.href='/try'">Regenerate</button>
  </div>
</body>
</html>`;
}
