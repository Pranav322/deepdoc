# Handoff — DD-001 Dispatch Index Blocked on Opus Limit

**Branch:** `fix/runtime-scan-stabilization`, clean at committed `b7ef353` plus prior commits. Unmerged.

## What is good

Runtime phase on the user’s VS Code rerun completed in **4.37s** with 8,415 product files, 4,428 low-trust files skipped, 108 dispatch candidates, and zero runtime tasks/schedulers. Hermes’s temporary CPU-heavy benchmark scripts were stopped and must not be rerun during the user’s benchmark.

## What remains

`b7ef353` has an `unindexed_tasks` fallback that revives candidate-files × tasks work for no-word triggers such as NestJS `@Cron('* * * * *')`.

A first uncommitted correction was rejected because it broke valid punctuation-only queue linkage:

```js
new Worker('---', handler)
queue.add('---', {})
```

It was restored. The next design must index raw quoted queue names separately for `queue.add`, while skipping unmatchable no-word generic/trigger tokens.

## Blocker

Claude Opus session limit reset is 20:50 IST. Do not use another model or manually modify production code. Await user decision on an automatic post-reset retry or manual resume.