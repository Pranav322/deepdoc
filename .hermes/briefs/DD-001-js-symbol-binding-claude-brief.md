# Claude Code Brief — DD-001 Bounded JS/TS/Vue Queue Symbol Binding

## User-approved decision

The user selected **Option A: bounded import/variable symbol binding now**.

This is **not a VS Code-specific patch**. VS Code is the adversarial benchmark that exposed a universal JS/TS/Vue correctness problem. The implementation must work for any supported JavaScript, TypeScript, or Vue repository and must not contain repository names, path exceptions, or benchmark-specific conditions.

## Autonomous-run contract

Work only in the existing isolated feature worktree/branch. Start by verifying all seams against the live code; this brief is evidence-backed but not authoritative. Use strict **RED → GREEN** vertical TDD. Do not edit `.hermes/`, `AGENTS.md`, README, config, user checkouts, `~/.claude` memory, or any out-of-scope file. Make one scoped local commit only after required tests and the actual `/Users/apple/personal/delete/vscode` read-only probe pass. Do not merge, push, or open a PR.

## Current branch context

```text
branch: fix/runtime-scan-stabilization
base:   8d45e5a82487d37a2a4adbf622ffbff1a0cc4b22
current head: 083ea39 fix: gate JS runtime jobs on syntax-level call evidence
```

The branch has already fixed:

- runtime-scan performance multiplier (VS Code phase falls from 856.018724208001s to ~4s);
- low-trust file/runtime contamination;
- embedded template-string queue examples;
- generic JS methods when no queue library appears in the file.

It is still **not acceptable** because it treats every executable `.process()`, `.consume()`, and `new Worker()` in any file that imports a queue library as a queue fact.

## Tight, already-proven RED repro

At current `083ea39`, this emits two false jobs:

```ts
import { Queue } from "bullmq";
const realQueue = new Queue("real");
const codec = { process(_name: string) {} };
codec.process("not-a-queue-job");
const webWorker = new Worker("browser-worker");
```

Observed current output:

```text
('not-a-queue-job', 'queue_process', 'not-a-queue-job')
('browser-worker', 'Worker', 'browser-worker')
```

The current design has syntax evidence but only a **file-level module gate**:

```text
queue-library import anywhere in file
  + executable generic JS call anywhere in file
  → false queue task
```

## Goal: universal, bounded intrafile binding

Implement a **per-file, syntax-backed binding resolver** for only known queue-runtime APIs. It must prove a candidate call/constructor is linked to a known queue-library symbol. This is a small structural extractor for all JS/TS/Vue repos, not whole-program type inference.

### Required semantic contract

A queue runtime fact is permitted only if its specific callee or receiver resolves in the same source file to a supported library binding or a value derived from one.

#### Queue packages / behaviors

| Package family | Valid evidence | Permitted fact |
|---|---|---|
| BullMQ | import/require binding of `Worker` (including alias) | `new <bound Worker>("queue", ...)` |
| Bull | default/named import/require binding, then local `new <bound constructor>(...)` | `<bound queue variable>.process(...)` |
| AMQP | `amqplib` / `amqp-connection-manager` import binding, then local connection/channel derivation | `<bound channel>.consume(...)` |
| Agenda | Agenda import/require binding, then local `new <bound Agenda>(...)` | `<bound agenda instance>.define(...)` / `.every(...)` |

### Safety/correctness rules

1. **No variable-name heuristic.** `queue`, `channel`, `worker`, or `agenda` names alone are not evidence.
2. **No file-level import gate.** A real package import does not automatically authorize every same-file method/constructor.
3. **Aliases matter.** `Worker as BullWorker`, default imports, named imports, and simple `require()` assignments must bind correctly.
4. **Track only bounded local flows.** Support straight-line/local declarator and assignment flows required by real queue APIs. Do not add cross-file analysis, arbitrary interprocedural inference, LSP/SCIP, or a general type checker.
5. **Scope/shadow safety.** A local/nested symbol that shadows an imported queue alias must not be treated as the imported binding. Use syntax scope information or safely fail closed if the resolver cannot prove identity.
6. **Template literals/comments/quoted examples never bind symbols or create calls.** Preserve the existing protection.
7. **Vue:** bind only inside the real `<script>` block(s) already supported by the scanner; do not raw-scan SFC markup.
8. **Fail closed.** Missing/unusable Tree-sitter evidence, unmodelled dynamic flows, or unresolved aliases must yield no JS runtime fact.
9. **Performance:** retain cheap raw prefiltering before Tree-sitter. Do not parse all JS files unnecessarily. Preserve deterministic ordering and existing scan stats.
10. **No benchmark-specific conditions.** No VS Code names, paths, source text, or special-case outputs in production code/tests.

## Existing reuse seams — verify before editing

| Concern | Reuse seam |
|---|---|
| executable JS/TS syntax nodes | `deepdoc/parser/js_ts_parser.py::js_syntax_evidence`, `JsEvidence`, `JsCall`, `_grammar_for` |
| Vue script extraction | `deepdoc/parser/vue_parser.py::_extract_script_block` |
| runtime aggregation/dedup | `deepdoc/scanner/runtime.py::_discover_js_runtime`, `_dedupe_runtime_tasks`, `_dedupe_schedulers` |
| source-role/language gate | `deepdoc/scanner/runtime.py::discover_runtime_surfaces` and `deepdoc/source_metadata.py` |
| current positive/negative tests | `tests/test_runtime_scan.py` |

You may evolve the parser helper into a small binding/evidence representation if that is cleaner, but do not create a parallel raw lexer or a general JavaScript semantic subsystem.

## Mandatory TDD tracer bullets

Use real `parse_file()` / Tree-sitter input where relevant. Every new behavior must be red before its implementation.

### RED 1 — exact current failure

The exact `Queue` + unrelated `codec.process()` + browser `new Worker()` fixture above must emit no JS runtime tasks after the fix. Confirm it currently fails with two tasks first.

### RED 2 — import alias and shadowing

A valid aliased BullMQ Worker must be detected:

```ts
import { Worker as BullWorker } from "bullmq";
new BullWorker("orders", handler);
```

But a browser/local `Worker` in a nested/shadowed scope must not be attributed to BullMQ. Pick syntactically valid shadowing that proves scope behavior.

### RED 3 — legitimate package-specific local flows

- Bull queue constructor → bound variable `.process(...)` remains detected.
- AMQP connection/client → bound channel `.consume(...)` remains detected.
- Agenda constructor → bound instance `.define()` / `.every()` remains detected.

If current positive fixtures do not accurately model a package API, correct the fixtures and detector contract rather than preserving a false positive just to keep a test green.

### RED 4 — prompt/template and Vue regression

Keep both existing template-literal negatives green and preserve a positive Vue `<script setup lang="ts">` queue case only when the receiver is genuinely bound.

## Scope

### In scope

- `deepdoc/parser/js_ts_parser.py`
- `deepdoc/scanner/runtime.py`
- `tests/test_runtime_scan.py`
- Only necessary parser tests if a small test file already exists for that parser

### Out of scope

- no LSP/SCIP, TypeScript compiler API, whole-repo module graph, global type checker, or SourceIndex rewrite;
- no broad Python/PHP/Go/NestJS/database/framework work;
- no change to LLM planning, provider, log verbosity, benchmark harness, or universal roadmap;
- no repository-specific special case;
- no code/agent memory/files outside the feature worktree except reading the existing `.hermes` brief/audit.

## Mandatory verification

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/apple/tss/codegen/codewiki/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_runtime_scan.py tests/test_scan_telemetry.py
PYTHONDONTWRITEBYTECODE=1 /Users/apple/tss/codegen/codewiki/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_framework_support.py
PYTHONDONTWRITEBYTECODE=1 /Users/apple/tss/codegen/codewiki/.venv/bin/python -m pytest -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 /Users/apple/tss/codegen/codewiki/.venv/bin/python -m compileall -q deepdoc
```

Run the exact actual-user-checkout probe only:

```bash
nice -n 10 env PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=/Users/apple/tss/codegen/codewiki-worktrees/runtime-scan-stabilization \
  /Users/apple/tss/codegen/codewiki/.venv/bin/python \
  /Users/apple/tss/codegen/codewiki/.hermes/audits/vscode-diagnostic-baseline-2026-08-27/runtime_phase_probe.py \
  /Users/apple/personal/delete/vscode
```

It must retain zero VS Code queue tasks/schedulers/realtime consumers and remain materially below 856.018724208001 seconds. Do not use `/Users/apple/personal/vscode` or another checkout.

## Final report

State exact RED evidence, the binding design, files changed, commit SHA, all test/probe outputs, precision limitations, and whether any requested binding was intentionally not modelled. Do not claim merge or user approval.
