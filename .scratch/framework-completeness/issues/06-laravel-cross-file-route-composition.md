# 06: Laravel — add cross-file route composition

**What to build:** Running `deepdoc generate` on Laravel repos produces correctly-composed API routes when `Route::prefix('admin')->group(base_path('routes/admin.php'))` delegates to a separate file. Previously, multi-file prefix composition was not resolved, producing incorrectly-pathed endpoints.

**Blocked by:** 02 (PHP call graph must exist for verification)

**Status:** ready-for-agent

- [ ] `Route::group()` with `base_path()` delegation resolves prefix to child file
- [ ] `Route::prefix('v1')->group(fn)` within the same file continues to work
- [ ] Existing Laravel route detection unchanged
- [ ] New test for cross-file Laravel route composition