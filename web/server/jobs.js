'use strict';

// File-based job state — survives server restarts, shared across tabs.
// One job per repo at a time. State lives at /data/:owner/:repo/.deepdoc-job.json
// Logs live at /data/:owner/:repo/.deepdoc-job.log

const fs = require('fs');
const path = require('path');

const DATA_DIR = process.env.DATA_DIR || '/data';

function repoDir(owner, repo)  { return path.join(DATA_DIR, owner, repo); }
function statePath(owner, repo) { return path.join(repoDir(owner, repo), '.deepdoc-job.json'); }
function logPath(owner, repo)   { return path.join(repoDir(owner, repo), '.deepdoc-job.log'); }

function createJob(owner, repo) {
  const dir = repoDir(owner, repo);
  fs.mkdirSync(dir, { recursive: true });
  const state = { owner, repo, status: 'running', startedAt: Date.now() };
  fs.writeFileSync(statePath(owner, repo), JSON.stringify(state));
  fs.writeFileSync(logPath(owner, repo), ''); // clear old log
  return state;
}

function getJob(owner, repo) {
  try {
    const p = statePath(owner, repo);
    if (!fs.existsSync(p)) return null;
    return JSON.parse(fs.readFileSync(p, 'utf-8'));
  } catch { return null; }
}

function setStatus(owner, repo, status) {
  try {
    const p = statePath(owner, repo);
    const state = JSON.parse(fs.readFileSync(p, 'utf-8'));
    state.status = status;
    fs.writeFileSync(p, JSON.stringify(state));
  } catch {}
}

function addLog(owner, repo, msg) {
  const line = (msg || '').trim();
  if (!line) return;
  try {
    fs.appendFileSync(logPath(owner, repo), line + '\n');
  } catch {}
}

function readLogs(owner, repo) {
  try {
    return fs.readFileSync(logPath(owner, repo), 'utf-8')
      .split('\n').filter(l => l.trim());
  } catch { return []; }
}

function clearJob(owner, repo) {
  try { fs.unlinkSync(statePath(owner, repo)); } catch {}
  try { fs.unlinkSync(logPath(owner, repo)); } catch {}
}

module.exports = { createJob, getJob, setStatus, addLog, readLogs, clearJob };
