# DD-001 Final Verification Failure — JS Symbol-Binding Boundary

**Date:** 2026-08-27  
**Branch:** `fix/runtime-scan-stabilization`  
**Latest local implementation:** `083ea39` (`fix: gate JS runtime jobs on syntax-level call evidence`)  
**Status:** blocked pending explicit semantic-design decision; not merged.

## What has been independently verified

The branch resolves the original two failures:

1. **Runtime performance multiplier**: real VS Code phase-only scan reduced from
   `856.018724208001s` to about 3.8–4.0 seconds on the same configured corpus.
2. **Embedded prompt/example contamination**: template literals that contain queue code no
   longer produce runtime jobs, including a file with a real top-level BullMQ import plus a
   quoted code example.

The runtime implementation is now Tree-sitter aware: it extracts executable import and
call/new-expression nodes instead of interpreting raw template strings as code.

## New final acceptance test — fails

A product TypeScript file with a genuine **unrelated** BullMQ import and ordinary executable
methods still yields false runtime jobs:

```ts
import { Queue } from "bullmq";
const realQueue = new Queue("real");
const codec = { process(_name: string) {} };
codec.process("not-a-queue-job");
const webWorker = new Worker("browser-worker");
```

Independent direct result from the current feature branch:

```text
[
  ('not-a-queue-job', 'queue_process', 'not-a-queue-job'),
  ('browser-worker', 'Worker', 'browser-worker')
]
```

Neither is a queue job. The source of the defect is now exact:

```text
file-level queue-library import
  + executable generic method / generic Worker constructor
  ≠ queue runtime fact
```

`deepdoc/scanner/runtime.py` gates the entire file with
`_js_imports_any(evidence.imports, JS_QUEUE_MODULES)` and then accepts every executable
`new Worker`, `.process`, or `.consume` call in that file. It lacks symbol binding between:

- imported `Worker` / `Queue` / AMQP types;
- variables constructed from or assigned those imports; and
- the specific receiver/callee of a candidate call.

## Why no fourth heuristic was applied

Three focused implementation iterations have uncovered progressively deeper semantics:

1. language/source-role filtering and bounded linking;
2. raw library evidence gate;
3. Tree-sitter executable-syntax evidence.

A fourth text-pattern tweak would be knowingly unsound. The next change must choose an
explicit semantic contract.

## Decision options

### A. Precise JS symbol binding (**recommended**)

Build a bounded JS/TS runtime evidence resolver that tracks only queue-specific import aliases
and local construction/assignment flows, then accepts a candidate only when its receiver or
constructor resolves to an imported queue-library symbol.

- Preserves real BullMQ/AMQP/Agenda detection.
- Eliminates `codec.process` and browser `new Worker` contamination even in a file that imports
  BullMQ.
- Reuses Tree-sitter AST evidence; does not need a whole-program type checker.
- Larger but principled follow-up slice with exact tests.

### B. Fail closed for JS queue runtime inference

Disable generic JS `new Worker`, `.process`, and `.consume` task inference entirely until the
universal semantic layer (C3/C6) is implemented.

- Maximally truthful today.
- Drops valid JS queue documentation temporarily.
- Keeps the original VS Code performance fix and all non-JS runtime detection.

### C. Accept the file-level heuristic

Not recommended. It knowingly produces false architecture facts, violating the DeepDoc goal.

## Required next verification, regardless of chosen design

- Current counterexample must emit no tasks.
- Real BullMQ `Worker`, AMQP `channel.consume`, and Agenda positive cases must remain detected
  if option A is selected.
- The real source probe must stay near the current ~4-second runtime and report zero VS Code
  queue tasks.
- Full test suite and independent review must pass before user review/merge.
