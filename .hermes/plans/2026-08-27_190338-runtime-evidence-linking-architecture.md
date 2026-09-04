# Runtime Dispatch Evidence & Bounded Linking Implementation Plan

> **For Hermes:** Execute directly in `fix/runtime-evidence-linking` with strict vertical RED → GREEN slices. Do not merge, push, open a PR, or run the canonical VS Code benchmark without fresh independent review and Pranav’s approval.

**Goal:** Replace DeepDoc’s raw runtime workflow linker with language-aware dispatch evidence and a bounded canonical-target resolver that fixes DD-013–DD-017 without repository-specific exceptions.

**Architecture:** Existing task/scheduler discovery remains intact. A product-owned `DispatchEvidence` contract carries only syntax/role-proven dispatches from each language extractor. A shared resolver canonicalizes aliases, rejects ambiguous one-to-one task/queue targets instead of fanning them out, and uses the same evidence index for scheduler endpoint links. Signal broadcasts are explicit semantics, not a fallback.

**Tech stack:** Python 3.10+, `ast`, Tree-sitter JavaScript/TypeScript/PHP already bundled by the project, pytest.

**Starting branch:** `fix/runtime-evidence-linking` at `4dd8b9fefa7c6d55ff58a93823121b76b2770f5f`, a fresh worktree rooted at the preserved rejected branch.

---

## Non-negotiable contracts

1. No raw JS/TS/Vue regex can create producer/workflow evidence. Comments, template literals, generic `.delay`, `.process`, `.consume`, `.add`, and `.on` are not evidence.
2. One direct dispatch spelling with more than one indistinguishable task/queue target is **ambiguous** and produces no per-task link. It must not expand to all matches.
3. Explicit broadcast signal semantics may fan out only through signal evidence; this is tracked separately from ambiguous direct dispatches.
4. Scheduler endpoint links are evidence-indexed; no endpoint-owning-file × all-schedulers sweep.
5. PHP FQCN and short class names are aliases only under an explicit collision policy. Leading `\` normalizes away; short alias matching is allowed only when unique.
6. JS CommonJS bindings require an unshadowed global `require` plus a literal requested module. Dynamic loads remain fail-closed.
7. Engine semantics change again: bump `ENGINE_FINGERPRINT` to a new v3 runtime-evidence identifier.
8. Preserve endpoint `publication_ready=False` defensive filtering and low-trust source exclusion.

## Target files

- Modify: `deepdoc/scanner/common.py`
  - Add `DispatchEvidence` and any small enum/string-contract fields needed by the resolver.
  - Add `RuntimeScan.dispatch_evidence` and bounded, observable link counters.
- Modify: `deepdoc/scanner/runtime.py`
  - Replace `DISPATCH_MARKER_RE` / raw `_link_runtime_workflows()` matching with evidence collection and target-index resolution.
  - Add Python AST evidence extraction, invoke PHP structural helper, and use JS bound calls for queue producer evidence.
  - Normalize target aliases, enforce ambiguity policy, and index scheduler endpoint links.
- Modify: `deepdoc/parser/php_parser.py`
  - Add a Tree-sitter-backed PHP dispatch helper for static dispatch, `dispatch(...)`, `event(...)`, class constants, `new`, FQCN, and leading-root names.
- Modify: `deepdoc/parser/js_ts_parser.py`
  - Complete declaration tracking for function/class expressions, `var` function scope, TypeScript `import_alias`, and literal-module member extraction (`require('x').Member`).
- Modify: `deepdoc/persistence_v2.py`
  - Bump `ENGINE_FINGERPRINT` to v3 runtime-evidence semantics.
- Modify: `tests/test_runtime_scan.py`
  - Add all RED regressions and preserve existing worker/scheduler/endpoint contracts.
- Modify: `tests/test_smart_update.py`
  - Assert the new fingerprint contract and mismatch → full replan behavior.

## Vertical execution slices

### Task 1: Establish evidence/ambiguity resolver contract

**Objective:** Make ambiguity and boundedness first-class before adding more extractors.

1. Add failing tests for:
   - 251 same-name `sync` tasks + 257 `sync.delay(...)` producers → zero task checks/links and an ambiguity counter.
   - 251 schedulers + 257 endpoint files without matching evidence → zero scheduler checks.
   - explicit signal broadcast behavior remains deterministic.
2. Add `DispatchEvidence` and resolver/index scaffolding with manual evidence fixtures.
3. Run only the new tests until RED then GREEN.
4. Commit scoped model/resolver slice.

### Task 2: Python AST evidence and scheduler indexing

**Objective:** Remove raw Python workflow regex dependency while preserving valid syntax.

1. Add failing tests for:
   - `sync . delay(...)`, `apply_async`, and `post_save . send(...)`;
   - Python comments/strings not becoming evidence;
   - endpoint links only when AST dispatch evidence exists;
   - scheduler endpoint links using evidence rather than global sweep.
2. Implement AST traversal over executable `ast.Call` nodes and emit canonical Python/signal evidence.
3. Feed it into the shared resolver and telemetry.
4. Run focused runtime/telemetry tests and commit.

### Task 3: Structural PHP FQCN dispatch evidence

**Objective:** Preserve actual Laravel workflow syntax without suffix heuristics.

1. Add failing tests for all of:
   - `\App\Jobs\SyncOrders::dispatch(...)`;
   - `dispatch(\App\Jobs\SyncOrders::class)`;
   - `dispatch(new App\Jobs\SyncOrders(...))`;
   - `event(new \App\Events\OrderShipped(...))`.
2. Add Tree-sitter PHP dispatch extraction and canonical aliases (full normalized form + terminal class name).
3. Resolve short alias only when a unique discovered target owns it; test collision fail-closed behavior.
4. Run focused PHP/runtime tests and commit.

### Task 4: JS binder scope/member completion and bounded queue producer evidence

**Objective:** Ensure JS evidence is syntax/role-proven with both recall and false-positive protection.

1. Add failing tests for:
   - nested `var require`, named function/class expressions, and TS `import require = ...` shadows;
   - `require('bullmq').Worker`, `require('socket.io').Server`, and `require('node-cron').schedule` aliases;
   - bound BullMQ/Bull queue `.add('literal')` producer evidence;
   - generic `getQueue().add`, comments, templates, dynamic requires, and arbitrary nested calls remaining non-evidence.
2. Extend bounded intrafile binder declaration/scope and member-extraction rules.
3. Emit JS queue-producer `DispatchEvidence` only for verified library/API roles.
4. Run focused JS/runtime tests and commit.

### Task 5: Integrate, fingerprint, and verify

**Objective:** Remove obsolete raw linker paths and prove the complete replacement.

1. Integrate dispatch evidence collection into `discover_runtime_surfaces`; retain low-trust/language gates and endpoint publication filtering.
2. Bump fingerprint to v3 and add its RED/GREEN contract test.
3. Run:
   - `tests/test_runtime_scan.py`
   - `tests/test_scan_telemetry.py`
   - `tests/test_framework_support.py`
   - `tests/test_smart_update.py`
   - full suite under project venv
   - `compileall` under project Python and Python 3.11
   - baseline-aware Ruff comparison and `git diff --check`.
4. Independently replay 251×257 task and scheduler cases, JS false-positive cases, PHP FQCN, and scope matrix.
5. Commit integration slice.

## Acceptance criteria

- No direct task dispatch duplicates produce files × all-tasks work; ambiguity is explicit and bounded.
- No scheduler endpoint sweep is possible without matching evidence.
- No JS/TS/Vue raw text can produce producer linkage.
- Valid Python whitespace spellings, Laravel qualified spellings, and role-proven JS queue APIs link correctly.
- CommonJS scope and member aliases behave correctly; dynamic/unproven values fail closed.
- Low-trust source and unpublished endpoints remain excluded.
- `ENGINE_FINGERPRINT` changes from v2.
- Full test suite passes, no new lint diagnostics, fresh complete-branch adversarial review passes, and Pranav explicitly approves before merge.

## Risks and explicit trade-offs

- Ambiguous direct targets intentionally lose a link rather than inventing one or enumerating every same-name task. This is an honesty/performance contract.
- Signal broadcast is the only intentional multi-target relation and must be visibly counted.
- The design adds a small internal evidence model, not a whole-repository semantic index or GitNexus dependency.
- Existing rejected branch remains intact for comparison; new work stays in `fix/runtime-evidence-linking`.
