-- Schema of D1 `deepdoc-hosted-db`, dumped from the remote database.
-- The original lived in the deleted web/hosted/ and was lost; AGENTS.md
-- still pointed at it. Regenerate with:
--   wrangler d1 execute deepdoc-hosted-db --remote --json \
--     --command "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"
-- Seed a local D1 with:
--   wrangler d1 execute deepdoc-hosted-db --local --file=schema.sql

CREATE TABLE oauth_states (
  state TEXT PRIMARY KEY,
  created_at INTEGER NOT NULL
);
CREATE TABLE owner_repo_jobs (
  owner TEXT NOT NULL,
  repo TEXT NOT NULL,
  job_id TEXT NOT NULL, visibility TEXT NOT NULL DEFAULT 'public', owner_login TEXT,
  PRIMARY KEY (owner, repo)
);
CREATE TABLE projects (
  user_login TEXT NOT NULL,
  owner TEXT NOT NULL,
  repo TEXT NOT NULL,
  job_id TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  description TEXT,
  language TEXT,
  avatar_url TEXT, visibility TEXT NOT NULL DEFAULT 'public', stars INTEGER,
  PRIMARY KEY (user_login, owner, repo)
);
CREATE TABLE rate_limit_starts (
  user_login TEXT NOT NULL,
  started_at INTEGER NOT NULL
);
CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  login TEXT NOT NULL,
  github_id INTEGER NOT NULL,
  avatar_url TEXT NOT NULL,
  token TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE INDEX idx_rate_limit_user_time ON rate_limit_starts(user_login, started_at);
