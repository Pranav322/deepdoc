# 01: Fix Go/PHP entry point detection

**What to build:** Running `deepdoc generate` on Go and PHP repos correctly identifies `main.go`/`app.go`/`server.go`/`app.php`/`index.php`/`server.php` as entry points. Previously, `rstrip()` character-set misuse silently dropped them, degrading the planner's understanding of project structure.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] `app.go`, `app.php`, `main.go`, `index.php` all detected as entry points
- [ ] Existing Python/JS entry-point detection unchanged
- [ ] Test covers all 5 languages