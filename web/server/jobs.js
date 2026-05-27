'use strict';

const fs = require('fs');
const path = require('path');

const DATA_DIR = process.env.DATA_DIR || '/data';

function repoDir(owner, repo)   { return path.join(DATA_DIR, owner, repo); }
function statePath(owner, repo) { return path.join(repoDir(owner, repo), '.deepdoc-job.json'); }
function logPath(owner, repo)   { return path.join(repoDir(owner, repo), '.deepdoc-job.log'); }

function createJob(owner, repo) {
  const dir = repoDir(owner, repo);
  fs.mkdirSync(dir, { recursive: true });
  const generation = Date.now(); // unique ID — increments on every force restart
  const state = { owner, repo, status: 'running', startedAt: generation, generation };
  fs.writeFileSync(statePath(owner, repo), JSON.stringify(state));
  fs.writeFileSync(logPath(owner, repo), '');
  return generation;
}

function getJob(owner, repo) {
  try {
    const p = statePath(owner, repo);
    if (!fs.existsSync(p)) return null;
    return JSON.parse(fs.readFileSync(p, 'utf-8'));
  } catch { return null; }
}

function setStatus(owner, repo, status, generation) {
  try {
    const p = statePath(owner, repo);
    const state = JSON.parse(fs.readFileSync(p, 'utf-8'));
    // Stale worker — a force restart happened, don't overwrite new job's state
    if (state.generation !== generation) return false;
    state.status = status;
    fs.writeFileSync(p, JSON.stringify(state));
    return true;
  } catch { return false; }
}

function addLog(owner, repo, msg, generation) {
  const line = (msg || '').trim();
  if (!line) return;
  try {
    // Only write if generation still matches (prevent stale workers polluting new job log)
    if (generation !== undefined) {
      const state = getJob(owner, repo);
      if (!state || state.generation !== generation) return;
    }
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
