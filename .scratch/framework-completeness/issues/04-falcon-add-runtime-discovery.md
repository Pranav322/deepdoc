# 04: Falcon — add runtime discovery

**What to build:** Running `deepdoc generate` on Falcon repos detects scheduled jobs, background tasks, and middleware hooks as runtime surfaces. Previously, only Celery tasks (if present) were detected for Falcon apps.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] APScheduler/cron-style background tasks detected in Falcon apps
- [ ] Falcon middleware hooks (`process_request`, `process_response`) detected
- [ ] Existing runtime detection for other frameworks unchanged
- [ ] New test fixture for Falcon runtime detection