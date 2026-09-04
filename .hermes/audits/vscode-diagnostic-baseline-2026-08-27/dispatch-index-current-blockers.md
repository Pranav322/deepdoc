# DD-001 Dispatch Index — Current Blockers and Restore

**Last reviewed committed head:** `b7ef353` on `fix/runtime-scan-stabilization`.

## Accepted, pending full independent final review

- Source-role/language gates and separate runtime progress labels.
- JS/TS/Vue intrafile import binding and typed queue API roles.
- Endpoint publication boundary commits: engine uses `published_api_endpoints`; runtime linking rejects `publication_ready=False` directly.
- Common-case dispatch target index and `link_task_checks` observability.

## Rejected uncommitted repair

The first attempt to remove `unindexed_tasks` correctly fixed its cron-trigger multiplier, but introduced a regression:

```text
new Worker('---', handler)
queue.add('---', {})
```

The original `queue.add` grammar can validly link this punctuation-only queue name because its word boundary is before `queue`, not the task name. The attempted word-run-only index produced no producer link. The uncommitted source/test changes were restored to `b7ef353` after verification.

## Claude availability blocker

The required Opus session hit its provider limit at 2026-08-27 17:28 IST. CLI reports reset at **20:50 IST**. Do not substitute another model or manually implement production code. A future Opus correction must:

1. remove all-candidate `unindexed_tasks` fallback;
2. retain indexable name/trigger linkage;
3. add a separate exact raw queue-name index for the `queue.add('literal')` grammar, including punctuation-only names;
4. keep no whole-VS-Code benchmark while the user’s benchmark is active.

No merge/PR is authorized.