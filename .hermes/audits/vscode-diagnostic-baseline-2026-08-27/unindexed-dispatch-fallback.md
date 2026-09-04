# DD-001 Unindexed Dispatch Fallback — Final Review Rejection

**Reviewed head:** `b7ef353` after the indexed-linking follow-up.

The common-case indexed linking and endpoint publication boundary are improvements, but this head is not accepted yet.

## Independent RED replay

```text
251 RuntimeTask(name='task_N', triggers=['* * * * *'])
257 product files containing unrelated.delay(payload)
_link_runtime_workflows(...).task_checks = 64,507
```

Cause: `runtime.py` places a whole task in `unindexed_tasks` when any token has no word run, then seeds every candidate file with that list. NestJS `@Cron('* * * * *')` can produce the real trigger form. The fallback therefore restores DD-001's candidate-files × tasks multiplier.

## Required correction

Index each usable token independently. Do not use an all-candidate fallback. A no-word token cannot meet the retained `\b{trigger}.send(` exact pattern, so skipping it is fail-closed and preserves observable valid grammar. Preserve indexable task-name dispatches on the same task.

No merge/PR is authorized. No further whole-corpus benchmark is authorized while the user runs VS Code.