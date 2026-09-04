# DD-001 Follow-up — Remove the Unindexed-Task Fallback

## Live-state requirement
Work only in `/Users/apple/tss/codegen/codewiki-worktrees/runtime-scan-stabilization` on `fix/runtime-scan-stabilization`. Inspect current HEAD and the live implementation first. This is an autonomous, narrow TDD repair. Do not merge, push, reset, clean, edit `.hermes`, AGENTS.md, README, config, the VS Code checkout, or `~/.claude`. Commit only scoped source/tests.

## Confirmed RED defect on current head
The just-added dispatch index contains `unindexed_tasks`: if **any** task token lacks a word run, it checks that task against every `DISPATCH_MARKER_RE` candidate file.

Tight replay:
- 251 tasks named `task_0` … `task_250`, each with trigger `"* * * * *"`;
- 257 unrelated files containing `unrelated.delay(payload)`;
- `_link_runtime_workflows()` returns `task_checks=64,507` (`251 × 257`).

This is a real DeepDoc shape: NestJS `@Cron('* * * * *')` creates `RuntimeTask(name=handler, triggers=[cron_expr])`.

## Root cause / required correction
The exact pre-existing trigger pattern is `\b{trigger}\.send\s*\(`. A token with no word run cannot satisfy that pattern because its leading `\b` cannot be true. It must therefore **not** put the whole task in an all-candidates fallback.

Build index entries independently per task token:
- retain every indexable task name and indexable trigger;
- silently skip only tokens with no possible word-boundary match;
- if a task has no indexable token at all, fail closed (no per-candidate fallback);
- preserve exact pattern verification, deterministic order, all existing dispatch grammar, and normal links through an indexable task name.

Do not broaden extraction, add raw heuristics, or alter the accepted JS queue API-role logic.

## Strict RED → GREEN
Before production edits, add/run a focused regression that fails on current head and asserts:
1. many tasks carrying unindexable cron triggers plus many unrelated `.delay(` marker files produce no task-count-proportional `link_task_checks`;
2. an indexable task name on the same task still links at its real `task_name.delay(...)` producer;
3. actual NestJS cron discovery (or a minimal direct RuntimeTask seam if more precise) establishes the realistic token shape.

After the minimal fix, run focused runtime tests, full `pytest -q`, compile checks including Python 3.11, and baseline-aware Ruff. **Do not run any whole-VS-Code benchmark or synthetic full-corpus timing script**: the user has an active benchmark. Report exact commands/results and commit hash.