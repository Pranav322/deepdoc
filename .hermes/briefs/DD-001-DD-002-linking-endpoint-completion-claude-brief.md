# DD-001/DD-002 Completion — Bounded Runtime Linking and Published Endpoints

## Must verify live first
Work only in `/Users/apple/tss/codegen/codewiki-worktrees/runtime-scan-stabilization` on `fix/runtime-scan-stabilization`. Its current head is `4c6708f`; inspect it and the base before editing. This is an autonomous TDD task: do not stop for checkpoints. Do not merge, push, reset, or clean. Commit only scoped production source/tests. Do not edit `.hermes`, AGENTS.md, README, config, the VS Code checkout, or `~/.claude`.

Keep the already-correct JS/TS/Vue queue API-role binding untouched unless a test proves this task requires a minimal integration adjustment.

## Two confirmed root causes

1. `deepdoc/scanner/runtime.py::_link_runtime_workflows()` filters with `DISPATCH_MARKER_RE`, but then loops **every** runtime task for every marker-bearing file. On the current head, a tight replay with 251 tasks and 257 unrelated `.delay(` files makes 64,507 token checks (251 × 257). That recreates the DD-001 files × tasks multiplier.

2. `run_phase2_scans()` passes raw `scan.api_endpoints` into runtime discovery, even though `RepoScan.published_api_endpoints` exists. `discover_runtime_surfaces()` / `_link_runtime_workflows()` also accepts an unpublished endpoint unchecked. A product `send_invoice.delay()` was linked to `GET /test-only` with `publication_ready=False`. That leaks a test-only route into generated runtime evidence (DD-002).

## Required behavior

### A. Bounded task linking
Replace the marker-file × all-task loop with an indexed/target-extraction design. It must be bounded by file content plus actual extracted dispatch targets/matches, not by all detected runtime task names for every marker-bearing file.

Preserve all existing task-link grammar and deterministic output:
- `task.delay(...)`, `task.apply_async(...)`
- `Task::dispatch(...)`, `dispatch(Task...)`, `dispatch(new Task...)`
- `event(new Task...)`
- `queue.add('Task', ...)`
- trigger `.send(...)`

Use exact task-pattern verification after an indexed candidate lookup if needed; do not replace correctness with a raw broad heuristic. Preserve scheduler endpoint-link behavior. Unrelated marker calls must not cause task-count-proportional work.

### B. Publication boundary
An endpoint whose `publication_ready` is false must never be attached to `RuntimeTask.linked_endpoints` or `RuntimeScheduler.linked_endpoints`, including direct callers of `discover_runtime_surfaces()`. Preserve real publication-ready endpoint links. Prefer the canonical published endpoint projection at the engine seam and fail closed defensively at the runtime boundary.

## Strict RED → GREEN
Before source changes, add focused regression tests and run them to an expected RED state:
1. A marker-heavy nonmatching corpus with many runtime tasks must prove task-link work does not scale as candidate files × unrelated task count. Choose an observable bounded-work assertion that fails against current head, not a flaky timing-only check.
2. A product dispatch associated with `publication_ready=False` must produce no linked endpoint; a matching `publication_ready=True` endpoint must still link.
3. Retain/add behavior coverage for every task-link grammar above and deterministic ordering.

Then implement only the minimal correction. Do not weaken existing tests, remove current API-role tests, or hide the repro by changing fixtures.

## Verification
Run with `/Users/apple/tss/codegen/codewiki/.venv/bin/python`:
- focused runtime/telemetry tests;
- the exact red repro now green;
- full `pytest -q` without piping through tail/head;
- compile checks, including `python3.11` syntax compilation;
- Ruff, distinguishing pre-existing from added-line findings;
- `/Users/apple/tss/codegen/codewiki/.hermes/audits/vscode-diagnostic-baseline-2026-08-27/runtime_phase_probe.py /Users/apple/personal/delete/vscode` using the feature worktree on `PYTHONPATH`.

Report exact commands/results, files changed, commit hash, and any deliberate fail-closed limitations.