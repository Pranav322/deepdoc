# Claude Code Follow-up Brief — DD-001 Residual JS Queue False Positives

## Autonomous-run contract

Work only in the existing isolated worktree/feature branch. Verify all details against the live code. Do not ask for a checkpoint. Use strict TDD: prove each behavior RED before production code, then make it GREEN. Make one scoped local commit; do not touch main, `.hermes/`, AGENTS.md, README.md, changelog, or unrelated files.

## Why this follow-up exists

The first DD-001 fix passed full tests and removed the files × task-name performance multiplier. A real read-only runtime-only probe against the official VS Code checkout then verified a **99.49% runtime-phase reduction**:

```text
Before: 856.018724208001s, 79 runtime tasks
After:    4.378843s,  7 runtime tasks, 108 link candidates
```

The remaining seven tasks are still false. They were independently traced to generic product TypeScript methods:

```text
lineProcessor.process(...)
replyProcessor.process(...)
Iterable.consume(...)
clientCustomizationsDiff.consume(...)
builder.consume(...)
```

They were emitted by `_discover_js_runtime()` as `runtime_kind="js_worker"`, `decorator="queue_process"` because its generic `.(process|consume)(...)` regex has no queue-library evidence requirement.

The same real VS Code corpus was searched for queue ecosystem evidence and returned **zero** matches for:

```text
bullmq
bull
bee-queue
kue
agenda
```

Generic `new Worker(...)`, `.process(...)`, and `.consume(...)` are not sufficient evidence of a queue job. Browser/Node workers and ordinary domain methods must not become queue/runtime architecture facts.

## Scope

### In scope

- `deepdoc/scanner/runtime.py` JavaScript queue-worker/Agenda evidence gating only.
- Focused tests in `tests/test_runtime_scan.py`.
- Any minimal existing-seam helper needed to keep the implementation clear and deterministic.

### Out of scope

- No changes to source-role filter, Python/PHP/Go scanners, topology, planner, LLMs, rate limits, database scanner, logging, docs, AGENTS.md, or broad parser architecture.
- Do not delete the dead `_discover_nestjs_runtime()` function in this task.
- Do not add a new third-party dependency.

## Required behavior

1. Treat a generic JS/TS `new Worker(...)`, `.process(...)`, or `.consume(...)` as **non-queue** unless the file has strong local evidence of the relevant queue ecosystem.
2. Preserve valid queue detection in existing tests. The current positive JS test contains `require('bullmq')` plus `new Worker('orders-sync', ...)` and must remain detected.
3. Preserve genuine Agenda detection, but require appropriate Agenda-specific evidence rather than a bare method-name coincidence.
4. Keep output deterministic and runtime scanning bounded.
5. Reuse/extend existing scanner patterns; do not invent a broad framework detector.

## TDD acceptance tests

Add tests that are RED on the current branch and GREEN after the fix:

1. Product TypeScript with generic `.process(...)` and `.consume(...)`, no queue import, yields no `js_worker` task.
2. Product TypeScript with generic `new Worker(...)`, no queue import, yields no `js_worker` task.
3. Existing BullMQ positive case remains detected; keep its explicit import/require evidence clear in test input.
4. Existing Agenda positive case remains detected only with explicit Agenda evidence.

Run each new test RED first. Report the expected failure and green result.

## Required verification

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/apple/tss/codegen/codewiki/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_runtime_scan.py tests/test_scan_telemetry.py
PYTHONDONTWRITEBYTECODE=1 /Users/apple/tss/codegen/codewiki/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_framework_support.py
PYTHONDONTWRITEBYTECODE=1 /Users/apple/tss/codegen/codewiki/.venv/bin/python -m pytest -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 /Users/apple/tss/codegen/codewiki/.venv/bin/python -m compileall -q deepdoc
```

## Real VS Code validation

Do **not** run a full LLM generation. Run a read-only runtime-only probe or give Hermes the exact code path to rerun. The final acceptance condition is:

```text
Official VS Code configured source corpus:
12,843 supported files / 148,276,780 bytes (or explain a genuine input-count difference)
0 runtime tasks
0 schedulers
0 realtime consumers
runtime time remains bounded and materially below the old 856s baseline
```

## Git / final report

- First inspect the current branch, which already contains commits `b591e45` and `5a30cd0`.
- Make one new scoped local commit only after all tests pass.
- Final report: root-cause confirmation, RED/GREEN evidence, files changed, exact tests/results, commit SHA, and remaining limitations.
