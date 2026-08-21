# 03: FastAPI — fix spurious mock-patch endpoint + add runtime discovery

**What to build:** Running `deepdoc generate` on FastAPI repos no longer produces phantom API endpoints from `@mock.patch("billing.charge")` decorators. FastAPI startup/shutdown lifecycle hooks and background tasks are discovered and appear in runtime-surface documentation. Previously, every test file with a decorator was scanned as a potential FastAPI route, and no FastAPI runtime surfaces were detected.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] `@mock.patch("module.fn")` no longer produces a phantom `PATCH 'module.fn'` endpoint
- [ ] `@app.on_event("startup"/"shutdown")` hooks detected as runtime surfaces
- [ ] `BackgroundTasks` usage detected
- [ ] Existing FastAPI route detection continues to work
- [ ] New test fixture for FastAPI runtime detection