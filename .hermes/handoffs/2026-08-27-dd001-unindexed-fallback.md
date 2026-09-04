# Handoff — DD-001 Unindexed Dispatch Fallback

The `b7ef353` indexed-linking follow-up is partially correct but rejected pending one boundedness defect.

- Current bad path: a task with any no-word trigger enters `unindexed_tasks`, then every marker candidate checks it.
- Verified replay: 251 tasks × 257 unrelated marker files = 64,507 task checks.
- Real producer: NestJS `@Cron('* * * * *')` can supply the no-word trigger.
- Correct model: index usable task-name/trigger tokens individually; skip no-word tokens because the existing word-boundary regex cannot match them; never fall back to all candidate files.

The user has a live VS Code run. Hermes CPU-heavy comparison scripts were stopped; do not run further whole-corpus benchmarks. Use only focused tests until the user’s run is over.

Next: Claude Opus applies the narrow TDD repair from `.hermes/briefs/DD-001-unindexed-dispatch-fallback-claude-brief.md`, then independent review replays all blockers.