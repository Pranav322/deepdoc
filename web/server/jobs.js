'use strict';

// In-memory job store. Restarts clear it — users just re-trigger.
const jobs = new Map();           // jobId  → job object
const repoJobs = new Map();       // owner/repo → jobId  (dedup)

function createJob(owner, repo) {
  const id = `${owner}-${repo}-${Date.now()}`;
  jobs.set(id, { id, owner, repo, status: 'pending', logs: [] });
  repoJobs.set(`${owner}/${repo}`, id);
  return id;
}

function getJob(id) {
  return jobs.get(id) || null;
}

function getJobForRepo(owner, repo) {
  const id = repoJobs.get(`${owner}/${repo}`);
  return id ? jobs.get(id) : null;
}

function addLog(id, msg) {
  const job = jobs.get(id);
  if (!job) return;
  const line = msg.trim();
  if (line) job.logs.push(line);
}

function setStatus(id, status) {
  const job = jobs.get(id);
  if (job) job.status = status;
}

function clearRepo(owner, repo) {
  const key = `${owner}/${repo}`;
  const id = repoJobs.get(key);
  if (id) jobs.delete(id);
  repoJobs.delete(key);
}

module.exports = { createJob, getJob, getJobForRepo, addLog, setStatus, clearRepo };
