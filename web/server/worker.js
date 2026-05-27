'use strict';

const { execSync, spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const { addLog, setStatus } = require('./jobs');

const DATA_DIR = process.env.DATA_DIR || '/data';

async function runJob(jobId, owner, repo) {
  const repoDir = path.join(DATA_DIR, owner, repo);
  const siteDir = path.join(repoDir, 'site');

  setStatus(jobId, 'running');

  try {
    // ── 1. Clone or pull ─────────────────────────────────────────────
    addLog(jobId, `[clone] Fetching github.com/${owner}/${repo}...`);
    fs.mkdirSync(path.join(DATA_DIR, owner), { recursive: true });

    if (fs.existsSync(path.join(repoDir, '.git'))) {
      addLog(jobId, '[clone] Repo exists — pulling latest...');
      execSync(`git -C ${repoDir} pull --ff-only`, { stdio: 'pipe' });
    } else {
      execSync(
        `git clone --depth 1 https://github.com/${owner}/${repo} ${repoDir}`,
        { stdio: 'pipe', timeout: 120_000 }
      );
    }
    addLog(jobId, '[clone] Done.');

    // ── 2. Write .deepdoc.yaml ────────────────────────────────────────
    addLog(jobId, '[config] Writing .deepdoc.yaml...');
    const yaml = [
      `project:`,
      `  name: ${repo}`,
      `  repo_url: https://github.com/${owner}/${repo}`,
      `llm:`,
      `  provider: azure`,
      `  model: ${process.env.AZURE_MODEL || 'azure/gpt-5.1'}`,
      `  api_key_env: AZURE_API_KEY`,
      `  base_url: ${process.env.AZURE_API_BASE || ''}`,
      `  api_version: ${process.env.AZURE_API_VERSION || '2025-07-01-preview'}`,
    ].join('\n');
    fs.writeFileSync(path.join(repoDir, '.deepdoc.yaml'), yaml + '\n');

    // ── 3. deepdoc generate ───────────────────────────────────────────
    addLog(jobId, '[generate] Scanning codebase and generating docs...');
    addLog(jobId, '[generate] This takes 3-8 minutes depending on repo size.');
    await run('deepdoc', ['generate', '--clean', '--yes'], repoDir, jobId);
    addLog(jobId, '[generate] Done.');

    // ── 4. npm install ────────────────────────────────────────────────
    addLog(jobId, '[build] Installing Next.js dependencies...');
    await run('npm', ['install', '--prefer-offline', '--no-audit', '--no-fund'], siteDir, jobId);

    // ── 5. next build (static export) ────────────────────────────────
    addLog(jobId, '[build] Building static site...');
    await run('npm', ['run', 'build'], siteDir, jobId, {
      DEEPDOC_SITE_BASE_PATH: `${owner}/${repo}`,
    });
    addLog(jobId, '[build] Done.');

    setStatus(jobId, 'done');
    addLog(jobId, `[done] Docs ready at /${owner}/${repo}`);
  } catch (err) {
    addLog(jobId, `[error] ${err.message}`);
    setStatus(jobId, 'error');
  }
}

function run(cmd, args, cwd, jobId, extraEnv = {}) {
  return new Promise((resolve, reject) => {
    const proc = spawn(cmd, args, {
      cwd,
      env: { ...process.env, ...extraEnv },
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    proc.stdout.on('data', (d) => {
      d.toString().split('\n').forEach((line) => addLog(jobId, line));
    });
    proc.stderr.on('data', (d) => {
      d.toString().split('\n').forEach((line) => addLog(jobId, line));
    });
    proc.on('close', (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${cmd} exited with code ${code}`));
    });
    proc.on('error', reject);
  });
}

module.exports = { runJob };
