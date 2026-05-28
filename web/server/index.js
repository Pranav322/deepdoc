'use strict';

require('dotenv').config();

const express = require('express');
const path = require('path');
const fs = require('fs');
const { createJob, getJob, setStatus, readLogs, clearJob } = require('./jobs');
const { enqueue, queueDepth } = require('./queue');
const { runJob } = require('./worker');

const app = express();
const DATA_DIR = process.env.DATA_DIR || '/data';
const PORT = process.env.PORT || 3001;

// ── SSE: /:owner/:repo/_status ─────────────────────────────────────────────
// No jobId needed — one job per repo, state is on disk.
app.get('/:owner/:repo/_status', (req, res) => {
  const { owner, repo } = req.params;
  const job = getJob(owner, repo);
  if (!job) return res.status(404).json({ error: 'No job found for this repo.' });

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');
  res.flushHeaders();

  let sent = 0;

  const flush = () => {
    const logs = readLogs(owner, repo);
    while (sent < logs.length) {
      res.write(`data: ${JSON.stringify({ log: logs[sent++] })}\n\n`);
    }
    const current = getJob(owner, repo);
    if (current?.status === 'done') {
      res.write(`data: ${JSON.stringify({ status: 'done' })}\n\n`);
      clearInterval(timer);
      res.end();
    } else if (current?.status === 'error') {
      res.write(`data: ${JSON.stringify({ status: 'error' })}\n\n`);
      clearInterval(timer);
      res.end();
    }
  };

  const timer = setInterval(flush, 400);
  flush();
  req.on('close', () => clearInterval(timer));
});

// ── Main: /:owner/:repo ────────────────────────────────────────────────────
app.get('/:owner/:repo', (req, res) => {
  const { owner, repo } = req.params;

  if (!/^[a-zA-Z0-9_.-]+$/.test(owner) || !/^[a-zA-Z0-9_.-]+$/.test(repo)) {
    return res.status(400).send('Invalid owner or repo name.');
  }

  // Block common bot probes (WordPress, PHP, env scanners, etc.)
  const BLOCKED = ['wp-admin', 'wp-login.php', 'phpMyAdmin', '.env', 'admin', 'shell'];
  if (BLOCKED.includes(owner) || BLOCKED.includes(repo) || repo.endsWith('.php')) {
    return res.status(404).send('Not found.');
  }

  const outDir = path.join(DATA_DIR, owner, repo, 'site', 'out');
  const indexFile = path.join(outDir, 'index.html');
  const force = 'force' in req.query;

  // ── ?force — wipe everything and restart regardless of current state ───
  if (force) {
    clearJob(owner, repo);
    fs.rmSync(outDir, { recursive: true, force: true });
    // Old worker detects generation mismatch and self-aborts
  }

  // ── Already built → serve docs ──────────────────────────────────────────
  if (!force && fs.existsSync(indexFile)) {
    return res.sendFile(indexFile);
  }

  const job = getJob(owner, repo);

  // ── Locked: job is running → show same progress page (any tab, any reload) ──
  if (job && job.status === 'running') {
    return res.send(progressPage(owner, repo));
  }

  // ── Previous attempt errored → allow retry (clear old state) ────────────
  if (job && job.status === 'error') {
    clearJob(owner, repo);
  }

  // ── Start new job ────────────────────────────────────────────────────────
  const generation = createJob(owner, repo);
  const { pending } = queueDepth();
  enqueue(() => runJob(owner, repo, generation));

  res.send(progressPage(owner, repo, pending));
});

// ── Static files: /:owner/:repo/* ─────────────────────────────────────────
app.use('/:owner/:repo', (req, res, next) => {
  const { owner, repo } = req.params;
  const outDir = path.join(DATA_DIR, owner, repo, 'site', 'out');
  if (!fs.existsSync(outDir)) return next();
  express.static(outDir, { index: 'index.html', fallthrough: true })(req, res, next);
});

// ── Health ─────────────────────────────────────────────────────────────────
app.get('/_health', (_req, res) => res.json({ ok: true, ...queueDepth() }));

app.listen(PORT, () => {
  console.log(`deepdoc-server listening on :${PORT}`);
  console.log(`DATA_DIR=${DATA_DIR}`);
});

// ── Progress page ──────────────────────────────────────────────────────────
function progressPage(owner, repo, queuePos = 0) {
  const repoLabel = `${owner}/${repo}`;
  // SSE URL has no jobId — just owner/repo, reads from disk
  const statusUrl = `/${owner}/${repo}/_status`;
  const queueNote = queuePos > 0
    ? `<p class="queue">⏳ ${queuePos} job${queuePos > 1 ? 's' : ''} ahead of you in queue</p>`
    : '';

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Indexing ${repoLabel} — DeepDoc</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #0d1117; color: #e6edf3;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      min-height: 100vh; display: flex; flex-direction: column;
      align-items: center; justify-content: center; padding: 2rem;
    }
    .card {
      width: 100%; max-width: 720px; background: #161b22;
      border: 1px solid #30363d; border-radius: 12px; padding: 2rem;
    }
    .header { display: flex; align-items: center; gap: 1rem; margin-bottom: 1.5rem; }
    .spinner {
      width: 28px; height: 28px; border: 3px solid #30363d;
      border-top-color: #58a6ff; border-radius: 50%;
      animation: spin 0.8s linear infinite; flex-shrink: 0;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .header h1 { font-size: 1.1rem; font-weight: 600; }
    .header p  { font-size: 0.8rem; color: #8b949e; margin-top: 2px; }
    .repo-badge {
      display: inline-flex; align-items: center; gap: 6px;
      background: #21262d; border: 1px solid #30363d; border-radius: 6px;
      padding: 4px 10px; font-size: 0.875rem; color: #58a6ff;
      font-family: 'SF Mono', monospace; margin-bottom: 1.25rem;
    }
    .queue { font-size: 0.8rem; color: #d29922; margin-bottom: 1rem; }
    .stage-list { display: flex; flex-direction: column; gap: 6px; margin-bottom: 1.5rem; }
    .stage { display: flex; align-items: center; gap: 10px; font-size: 0.85rem; color: #8b949e; }
    .stage.active { color: #e6edf3; }
    .stage.done   { color: #3fb950; }
    .stage-icon   { width: 18px; text-align: center; }
    .log-box {
      background: #010409; border: 1px solid #21262d; border-radius: 8px;
      padding: 1rem; height: 220px; overflow-y: auto;
      font-family: 'SF Mono', 'Fira Mono', monospace;
      font-size: 0.75rem; line-height: 1.6;
    }
    .log-line { color: #8b949e; white-space: pre-wrap; word-break: break-all; }
    .log-line.error { color: #f85149; }
    .log-line.done  { color: #3fb950; }
    .eta { font-size: 0.75rem; color: #8b949e; margin-top: 0.75rem; text-align: right; }
    .error-msg {
      margin-top: 1rem; padding: 0.75rem 1rem; background: #1c1212;
      border: 1px solid #6e2020; border-radius: 6px;
      font-size: 0.85rem; color: #f85149;
    }
    .retry-btn {
      margin-top: 1rem; padding: 0.5rem 1.25rem; background: #21262d;
      border: 1px solid #30363d; border-radius: 6px; color: #e6edf3;
      font-size: 0.85rem; cursor: pointer;
    }
    .retry-btn:hover { background: #30363d; }
  </style>
</head>
<body>
  <div class="card">
    <div class="header">
      <div class="spinner" id="spinner"></div>
      <div>
        <h1>Generating documentation</h1>
        <p>Sit tight — this usually takes 3–8 minutes</p>
      </div>
    </div>

    <div class="repo-badge">
      <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
        <path d="M2 2.5A2.5 2.5 0 0 1 4.5 0h8.75a.75.75 0 0 1 .75.75v12.5a.75.75 0 0 1-.75.75h-2.5a.75.75 0 0 1 0-1.5h1.75v-2h-8a1 1 0 0 0-.714 1.7.75.75 0 1 1-1.072 1.05A2.495 2.495 0 0 1 2 11.5Zm10.5-1h-8a1 1 0 0 0-1 1v6.708A2.486 2.486 0 0 1 4.5 9h8Z"/>
      </svg>
      ${repoLabel}
    </div>

    ${queueNote}

    <div class="stage-list">
      <div class="stage" id="stage-clone"><span class="stage-icon">○</span> Cloning repository</div>
      <div class="stage" id="stage-generate"><span class="stage-icon">○</span> Scanning code &amp; generating docs with AI</div>
      <div class="stage" id="stage-build"><span class="stage-icon">○</span> Building static site</div>
    </div>

    <div class="log-box" id="log"></div>
    <p class="eta" id="eta">Starting job...</p>
  </div>

  <script>
    const statusUrl = ${JSON.stringify(statusUrl)};
    const logBox = document.getElementById('log');
    const eta = document.getElementById('eta');
    const spinner = document.getElementById('spinner');
    const startTime = Date.now();

    function setStage(key, state) {
      const map = { clone: 'stage-clone', generate: 'stage-generate', build: 'stage-build' };
      const el = document.getElementById(map[key]);
      if (!el) return;
      el.className = 'stage ' + state;
      el.querySelector('.stage-icon').textContent =
        state === 'done' ? '✓' : state === 'active' ? '▶' : '○';
    }

    function appendLog(line) {
      const div = document.createElement('div');
      div.className = 'log-line' +
        (line.includes('[error]') ? ' error' : line.includes('[done]') ? ' done' : '');
      div.textContent = line;
      logBox.appendChild(div);
      logBox.scrollTop = logBox.scrollHeight;

      if (line.includes('[clone]'))    setStage('clone',    line.includes('Done') ? 'done' : 'active');
      if (line.includes('[generate]')) setStage('generate', line.includes('Done') ? 'done' : 'active');
      if (line.includes('[build]'))    setStage('build',    line.includes('Done') ? 'done' : 'active');
      if (line.includes('[done]'))     setStage('build', 'done');
    }

    const clock = setInterval(() => {
      const s = Math.floor((Date.now() - startTime) / 1000);
      eta.textContent = \`Elapsed: \${Math.floor(s/60)}m \${s%60}s\`;
    }, 1000);

    const es = new EventSource(statusUrl);

    es.onmessage = (e) => {
      const data = JSON.parse(e.data);
      if (data.log) appendLog(data.log);
      if (data.status === 'done') {
        es.close(); clearInterval(clock);
        spinner.style.borderTopColor = '#3fb950';
        spinner.style.animation = 'none';
        eta.textContent = 'Done! Redirecting...';
        setTimeout(() => { window.location.reload(); }, 1200);
      }
      if (data.status === 'error') {
        es.close(); clearInterval(clock);
        spinner.style.borderTopColor = '#f85149';
        spinner.style.animation = 'none';
        eta.textContent = 'Generation failed.';
        const errEl = document.createElement('div');
        errEl.className = 'error-msg';
        errEl.textContent = 'Generation failed. Reload the page to retry.';
        const btn = document.createElement('button');
        btn.className = 'retry-btn';
        btn.textContent = 'Retry';
        btn.onclick = () => window.location.reload();
        errEl.appendChild(document.createElement('br'));
        errEl.appendChild(btn);
        document.querySelector('.card').appendChild(errEl);
      }
    };
  </script>
</body>
</html>`;
}
