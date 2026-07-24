CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  login TEXT NOT NULL,
  github_id INTEGER NOT NULL,
  avatar_url TEXT NOT NULL,
  token TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);

CREATE TABLE oauth_states (
  state TEXT PRIMARY KEY,
  created_at INTEGER NOT NULL
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
  avatar_url TEXT,
  visibility TEXT NOT NULL DEFAULT 'private',
  PRIMARY KEY (user_login, owner, repo)
);

CREATE TABLE rate_limit_starts (
  user_login TEXT NOT NULL,
  started_at INTEGER NOT NULL
);
CREATE INDEX idx_rate_limit_user_time ON rate_limit_starts(user_login, started_at);

CREATE TABLE owner_repo_jobs (
  owner TEXT NOT NULL,
  repo TEXT NOT NULL,
  job_id TEXT NOT NULL,
  visibility TEXT NOT NULL DEFAULT 'private',
  owner_login TEXT,
  PRIMARY KEY (owner, repo)
);
