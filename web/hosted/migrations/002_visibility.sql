-- Adds per-site visibility + site ownership.
-- Existing rows backfill to 'public' to preserve already-shared links; NEW
-- generations write 'private' explicitly at the application layer (schema.sql's
-- column default is 'private' for fresh installs — the divergence is deliberate).
ALTER TABLE projects ADD COLUMN visibility TEXT NOT NULL DEFAULT 'public';
ALTER TABLE owner_repo_jobs ADD COLUMN visibility TEXT NOT NULL DEFAULT 'public';
ALTER TABLE owner_repo_jobs ADD COLUMN owner_login TEXT;

-- The DeepDoc user who owns each existing repo site, from the projects table.
UPDATE owner_repo_jobs SET owner_login = (
  SELECT p.user_login FROM projects p
  WHERE LOWER(p.owner) = LOWER(owner_repo_jobs.owner)
    AND LOWER(p.repo)  = LOWER(owner_repo_jobs.repo)
  ORDER BY p.created_at DESC LIMIT 1
);
