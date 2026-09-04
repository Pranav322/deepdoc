# Handoff — DD-001 JS Runtime Semantic Binding Decision

**Date:** 2026-08-27  
**Status:** blocked pending user decision; no merge, no PR, no production checkout modification.

## What is genuinely fixed on the local feature branch

Branch:

```text
fix/runtime-scan-stabilization
base: 8d45e5a82487d37a2a4adbf622ffbff1a0cc4b22
latest: 083ea39 fix: gate JS runtime jobs on syntax-level call evidence
```

- The hidden runtime-surface phase's original VS Code cost was independently measured at
  `856.018724208001s`; the branch reduced phase-only runtime to roughly 3.8–4.0 seconds on
  `/Users/apple/personal/delete/vscode`.
- Low-trust test/fixture/example/generated source is excluded from runtime evidence.
- Foreign-language snippets in TypeScript prompts do not trigger Python detectors.
- Queue code inside TypeScript template literals no longer creates JS runtime jobs, including
  when the same file has a real top-level BullMQ import.
- Local commits are unmerged. User approval is required before any PR/merge.

## The final acceptance failure

The syntax-aware implementation still uses a **file-level** queue-library gate. This test emits
false jobs on `083ea39`:

```ts
import { Queue } from "bullmq";
const realQueue = new Queue("real");
const codec = { process(_name: string) {} };
codec.process("not-a-queue-job");
const webWorker = new Worker("browser-worker");
```

Observed result:

```text
('not-a-queue-job', 'queue_process', 'not-a-queue-job')
('browser-worker', 'Worker', 'browser-worker')
```

Thus actual syntax parsing alone is insufficient; it needs binding from the call receiver or
constructor to the imported queue-library symbol. A raw-regex fourth patch is prohibited.

## Decision required from the user

1. **Recommended:** add bounded JS/TS symbol binding for queue import aliases and locally
   constructed queue/client variables, preserving real BullMQ/AMQP/Agenda docs while rejecting
   unrelated same-file methods/Workers.
2. **Conservative alternative:** fail closed for generic JS queue task inference pending C3/C6
   semantic infrastructure. This guarantees no false facts but loses valid JS queue docs.
3. Accept the current file-level heuristic (not recommended; it knowingly emits false facts).

## Records

- Canonical status: `.hermes/ISSUE_LEDGER.md` → DD-001/DD-002.
- Original hotspot evidence: `.hermes/audits/vscode-diagnostic-baseline-2026-08-27/runtime-scan-hotspot.md`
- Final boundary reproduction and decision trade-offs:
  `.hermes/audits/vscode-diagnostic-baseline-2026-08-27/js-runtime-symbol-binding-boundary.md`
- Reproducible real-source phase probe:
  `.hermes/audits/vscode-diagnostic-baseline-2026-08-27/runtime_phase_probe.py`
- Claude briefs retained under `.hermes/briefs/`.
