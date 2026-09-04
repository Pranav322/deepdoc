# DD-001/DD-002 Round-Two Direct Implementation

**Date:** 2026-08-27  
**Branch:** `fix/runtime-scan-stabilization`  
**Base:** `8d45e5a82487d37a2a4adbf622ffbff1a0cc4b22`  
**Implementation heads:** `25689491155484674c36355e0694b7549d8eda83` (`fix: harden runtime evidence binding`) and `4dd8b9fefa7c6d55ff58a93823121b76b2770f5f` (`fix: reject shadowed commonjs loader bindings`)  
**Status:** verification pending — not approved for push, PR, or merge.

## Why direct implementation

Pranav explicitly authorized direct Hermes implementation after the first final adversarial review rejected the earlier isolated branch and the Claude provider/session path could not safely complete the final correction. This did not relax review or merge safeguards.

## Reproduced blockers and corrections

1. **Shared word-run cartesian linking**
   - Old failure: `queue-N-sync` tasks could all land in the `sync` index bucket; 251 tasks × 257 `sync.delay(...)` files produced 64,507 checks.
   - Correction: exact, grammar-specific indexes for delay/apply_async, signal send, PHP static/direct/event dispatch, plus a separate exact quoted queue-literal index.
   - Regression: `test_dispatch_index_does_not_collide_shared_word_runs`.

2. **Duplicate same-name signal handlers**
   - Old failure: patterns/tokens keyed by name meant `handle(post_save)` and `handle(post_delete)` could overwrite each other based on input order.
   - Correction: task patterns are owned by task object identity; trigger indexes independently route `.send(...)` evidence.
   - Regression: `test_duplicate_signal_task_names_keep_own_trigger_links`.

3. **Whitespace in valid JS queue calls**
   - Old failure: cheap prefilter rejected `queue.process ('job', handler)` before Tree-sitter binding.
   - Correction: whitespace-tolerant call-shape regex remains only a candidate gate; API role binding remains authoritative.
   - Regression: `test_js_queue_worker_accepts_whitespace_before_process_call`.

4. **Raw JS scheduler/realtime evidence**
   - Old failure: raw JS/TS/Vue scheduler/realtime scans could treat template strings/comments as node-cron or Socket.IO code.
   - Correction: JS runtime discovery now returns workers, schedulers, and consumers from one Tree-sitter/bounded-intrafile binding pass. Python raw crontab/Django Channels detection is isolated to Python source.
   - Regressions: template-text negative, named Socket.IO server, default Socket.IO factory, direct `require('socket.io')(server)` factory, per-file node-cron naming.

5. **State semantics**
   - Correction: `ENGINE_FINGERPRINT` bumped from v1 to `planning_units_namespaced_routes_semantic_boundaries_runtime_evidence_v2`, so saved plans produced under old runtime evidence semantics trigger a full replan.
   - Regression: `test_engine_fingerprint_records_runtime_evidence_contract` plus existing mismatch/full-replan test.

6. **Shadowed CommonJS loader hardening**
   - Follow-up finding during final local adversarial review: a local parameter or declaration named `require` could be treated as Node's global loader and manufacture a bound Socket.IO consumer.
   - Correction: loader recognition now requires an unshadowed `require` identifier; declaration scope handling correctly gives named function/class declarations their enclosing lexical scope.
   - Regressions: `test_js_shadowed_require_is_not_runtime_evidence` and `test_js_function_named_require_is_not_runtime_evidence`, with unshadowed direct-factory controls retained.

## Local evidence

- Tight runtime regression file: **42 passed**.
- Full suite, project venv: **643 passed, 3 skipped** in 17.57s.
- Python 3.14 project compileall and Python 3.11 compileall/py_compile: passed.
- `git diff --check`: passed.
- Baseline-aware Ruff comparison: **no new diagnostics**; it resolved 34 legacy `runtime.py` F405 wildcard-import diagnostics. Legacy scanner re-export lint remains baseline debt.
- Fresh in-memory adversarial replay:
  - shared-suffix case: 257 candidate files / **0** task checks;
  - 251 no-word-cron tasks plus 257 unrelated markers: 258 candidate files / **1** task check;
  - same-name signal handlers retained independent links;
  - template/generic JS produced no fake scheduler/consumer; direct bound Socket.IO factory produced exactly one Socket.IO consumer.

## Pending acceptance

The first fresh review batch was stopped as stale after the loader-shadow correction advanced the worktree. A replacement two-review batch `deleg_809597cb` is reviewing exact head `4dd8b9fefa7c6d55ff58a93823121b76b2770f5f`. Its verdicts are required before DD-001/DD-002 can leave `verification`; no push, PR, merge, or canonical full VS Code benchmark certification is authorized yet.
