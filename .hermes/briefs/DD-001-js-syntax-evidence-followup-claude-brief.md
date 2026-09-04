# Claude Code Follow-up Brief — DD-001 Syntax-Level JS Runtime Evidence

## Autonomous-run contract

Work only in the existing isolated feature worktree and inspect the live code before changes. This is the third and final targeted correction to DD-001/DD-002 runtime evidence. Use strict **RED → GREEN** TDD. Do not edit `.hermes/`, `AGENTS.md`, README, changelog, the user’s VS Code checkout, `~/.claude` memory, configuration, or any out-of-scope file. Make one scoped local commit only after all required tests pass.

## Current branch state — verify, do not trust blindly

```text
branch: fix/runtime-scan-stabilization
base:   8d45e5a82487d37a2a4adbf622ffbff1a0cc4b22
commits already on branch:
  b591e45  bound runtime discovery
  5a30cd0  lint imports
  42485bb  raw queue-library evidence gate
```

The current branch correctly makes the actual user benchmark target zero-task:

```text
/Users/apple/personal/delete/vscode
12,843 files / 148,276,780 bytes
runtime_seconds=3.810387
runtime_tasks=0
```

That is necessary but **not sufficient**. An adversarial product-TypeScript fixture exposes remaining prompt contamination.

## Proven root cause

At `42485bb`, `_js_imports_any()` applies `JS_MODULE_RE` to raw file content. Thus an embedded template literal can supply both apparent library evidence and apparent queue calls.

This exact product source currently emits false tasks:

```ts
// src/prompts/queue_examples.ts
import { Queue } from "bullmq";
const realQueue = new Queue("real");
export const EXAMPLE = `
  new Worker("fake-example", async job => job);
  queue.process("also-fake", handler);
`;
```

The current scanner emits `fake-example` and `also-fake`, even though both are embedded example text. This proves that AST import evidence alone is insufficient if regex task extraction still scans raw content.

Independent Claude Opus confirmation established:

- `deepdoc/parser/js_ts_parser.py::parse_js_ts()` uses Tree-sitter when available.
- Actual `import_declaration` / `import_statement` nodes populate `ParsedFile.imports` and do **not** include import-looking text inside template literals.
- Tree-sitter is a required, non-optional project dependency.
- Existing raw fallback is fail-open for prompt text and must not be used as runtime evidence when Tree-sitter is unavailable.

## Required architecture

Use **syntax-level, executable JS evidence** for queue/Agenda detection.

### Required behavior

1. Parse only the already prefiltered JS/TS candidate files with the existing Tree-sitter JS/TS support (or expose/reuse a minimal helper from `deepdoc/parser/js_ts_parser.py`).
2. Collect only actual import/require syntax and actual executable `new_expression` / `call_expression` nodes. Do not scan template-literal/comment/string content as executable code.
3. Match `new Worker(...)`, `.process(...)`, `.consume(...)`, `agenda.define(...)`, and `agenda.every(...)` only against those executable expression spans.
4. Require actual queue-library evidence for generic queue shapes:
   - `bullmq`, `bull`, `bee-queue`, `kue`, `amqplib`, `amqp-connection-manager`.
   - `agenda`, `@hokify/agenda` for Agenda.
5. Preserve valid actual queue behavior: BullMQ, AMQP consume, and Agenda must stay detected.
6. If Tree-sitter evidence is unavailable or parsing is unusable, fail **closed** for JS runtime jobs rather than falling back to raw-content matching. Truthfulness is more important than unsupported-environment recall.
7. Keep source-role/language filters, deterministic order, and candidate-linking bounds intact.
8. Preserve Vue safely: either use the existing parser if it gives actual executable spans, or fail closed for JS queue inference rather than raw scanning a Vue SFC. Do not silently reintroduce a text-only path.

## Scope

### In scope

- `deepdoc/scanner/runtime.py`
- Minimal parser helper only if necessary, preferably `deepdoc/parser/js_ts_parser.py`
- `tests/test_runtime_scan.py`

### Explicitly out of scope

- no SourceIndex/RepositoryModel redesign;
- no changes to Python/PHP/Go/realtime/scanners, planner orchestration, LLMs, logs, config, universal roadmap, or dead NestJS function;
- no new dependency;
- no generic lexer implementation when existing Tree-sitter already supplies syntax nodes.

## TDD — mandatory vertical cycles

### RED 1: template-only fake queue source

Use real `parse_file()`/Tree-sitter (not a hand-filled `ParsedFile`) on a TypeScript product prompt whose template literal contains BullMQ import + `new Worker` + `.process`. It must fail before the fix because it emits false tasks, then pass with no JS worker tasks.

### RED 2: actual BullMQ import plus embedded fake example

Use the exact fixture above: actual `import { Queue } from "bullmq";` at top level, but queue-shaped calls only inside a template literal. It must fail before the fix and then emit no JS worker tasks. This prevents an import-only gate from being accepted.

### GREEN positive cases

Keep or improve tests proving:

- a real `require('bullmq')` with a real `new Worker('orders-sync', ...)` / `queue.process(...)` is detected;
- a real `import amqplib from 'amqplib'` with actual `channel.consume('orders-sync', ...)` is detected;
- real Agenda import + actual `agenda.define/every` is detected;
- ordinary `.process/.consume`, browser/Node `new Worker`, and Agenda-lookalike methods without evidence remain absent.

Run each new RED test alone and show the expected false-task failure before implementation. Then run it green before proceeding to the next test.

## Required verification

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/apple/tss/codegen/codewiki/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_runtime_scan.py tests/test_scan_telemetry.py
PYTHONDONTWRITEBYTECODE=1 /Users/apple/tss/codegen/codewiki/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_framework_support.py
PYTHONDONTWRITEBYTECODE=1 /Users/apple/tss/codegen/codewiki/.venv/bin/python -m pytest -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 /Users/apple/tss/codegen/codewiki/.venv/bin/python -m compileall -q deepdoc
```

### Real acceptance benchmark

Use the actual user benchmark checkout only:

```text
/Users/apple/personal/delete/vscode
```

Run this read-only probe from the feature worktree (it does no LLM call and writes no target files):

```bash
nice -n 10 env PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=/Users/apple/tss/codegen/codewiki-worktrees/runtime-scan-stabilization \
  /Users/apple/tss/codegen/codewiki/.venv/bin/python \
  /Users/apple/tss/codegen/codewiki/.hermes/audits/vscode-diagnostic-baseline-2026-08-27/runtime_phase_probe.py \
  /Users/apple/personal/delete/vscode
```

Required final output:

```text
files_selected=12,843
source_bytes=148,276,780
runtime_tasks=0
runtime_schedulers=0
realtime_consumers=0
runtime_seconds materially below old 856.018724208001 seconds
```

If the corpus changed, explain with direct evidence; do not substitute `/Users/apple/personal/vscode` or another clone.

## Final report

Report the exact RED failure evidence, all green test results, files changed, model, commit SHA, and explicit remaining limitations. Do not modify external agent memory or claim the work is merged.
