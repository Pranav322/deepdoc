# Handoff — DD-001/DD-002 Runtime Stabilization Blocked in Final Review

**Branch:** `fix/runtime-scan-stabilization` at `f28e04c`; clean and unmerged.  
**Important:** no push, PR, merge, or main-checkout change occurred.

## What was verified before the block

- Runtime-phase probe improved from `856.018724208001s` to roughly `4.24–4.38s` on the VS Code corpus. This is a phase-only measurement, not a final end-to-end benchmark.
- Endpoint publication boundary is correct: engine supplies `published_api_endpoints`, and linker rejects `publication_ready=False` defensively.
- Narrow manual correction removed `unindexed_tasks` and preserved `queue.add('---')`; 632 tests passed before final review.

## Why final review blocked the branch

Independent review plus Hermes replay proved four remaining universal defects:

1. Word-run index collision: 251 `queue-N-sync` tasks × 257 `sync.delay()` files = 64,507 task checks.
2. Duplicate same-name signal tasks overwrite trigger patterns/tokens, making `post_save.send()` linkage order-dependent.
3. JS prefilter rejects legal whitespace in `.process (` / `.consume (`.
4. Raw JS/TS/Vue scheduler/realtime regexes can treat template literals/comments as executable node-cron/socket.io evidence.

Full evidence: `.hermes/audits/vscode-diagnostic-baseline-2026-08-27/runtime-final-review-round2-blockers.md`.

## Next safe action

Do not patch one symptom at a time. Agree on a bounded redesign:

- grammar-specific exact dispatch-target indexes;
- task-identity pattern/token ownership;
- whitespace-tolerant JS prefilter;
- structural JS scheduler/realtime binding, with Python raw detectors separated.

Then write RED tests for all four behaviors, implement in isolated worktree, rerun full suite, conduct fresh adversarial review, and require user approval before merge.
