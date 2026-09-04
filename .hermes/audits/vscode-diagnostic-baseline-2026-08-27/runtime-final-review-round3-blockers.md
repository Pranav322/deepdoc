# DD-001/DD-002 Final Review — Round 3 Architectural Blockers

**Date:** 2026-08-27  
**Reviewed branch head:** `4dd8b9fefa7c6d55ff58a93823121b76b2770f5f`  
**Base:** `8d45e5a82487d37a2a4adbf622ffbff1a0cc4b22`  
**Verdict:** **BLOCKED** — no push, PR, merge, or main-checkout change permitted.

## Independent review status

Two fresh read-only reviewers independently blocked the exact committed head. Their review batch was `deleg_809597cb`. All actionable findings below were independently replayed locally before this record was written.

## Confirmed blockers

### DD-013 — Ambiguous runtime target names can recreate task cartesian work

- **Observed:** 251 `RuntimeTask(name="sync")` records and 257 `sync.delay(...)` files produced **64,507** task checks (251 × 257).
- **Root cause:** the exact dispatch key bucket still contains every same-name task; selecting a target therefore expands into every ambiguous task instance.
- **Why this is architectural:** a dispatch spelling alone cannot determine which of many equal-name task records it names. Linking all is unbounded; choosing one silently invents certainty. The replacement needs a canonical target/evidence node or explicit ambiguity fail-closed policy, not another list filter.

### DD-014 — Generic workflow linking is still raw-text and language-agnostic

- **Observed:** a real Python `sync_orders` task accepted producer evidence from TypeScript `this.sync_orders.delay(120)`, a JS comment, and a JS template literal.
- **Root cause:** `_link_runtime_workflows()` consumes every eligible file’s raw text with dispatch regexes. JS runtime discovery became structural, but JS producer/workflow linking did not.
- **Marker drift:** `DISPATCH_TARGET_RE` accepts valid whitespace around member dots, while `DISPATCH_MARKER_RE` rejects it. `sync . delay(...)`, `post_save . send(...)`, and `queue . add("---", {})` silently lose links.
- **Required design direction:** language-specific syntax/role-bound dispatch evidence must feed the common linker; the marker must be the same evidence extraction operation, not a weaker parallel regex.

### DD-015 — Scheduler endpoint linking remains endpoint-file × scheduler work

- **Observed:** 251 schedulers and 257 publication-ready endpoint-owning files with no matching target resulted in **64,507** scheduler-pattern searches.
- **Root cause:** every endpoint-owning file loops through every scheduler pattern independently of extracted targets.
- **Required design direction:** scheduler endpoint linking needs the same target-evidence/index contract as task linking, or a bounded source-ownership relation; it cannot remain a global sweep.

### DD-016 — Laravel FQCN dispatches cannot link to discovered runtime tasks

- **Observed:** Laravel discovery emits `RuntimeTask(name="SyncOrders")`, but `App\\Jobs\\SyncOrders::dispatch(...)`, `dispatch(App\\Jobs\\SyncOrders::class)`, `dispatch(new App\\Jobs\\SyncOrders(...))`, and `event(new App\\Events\\OrderShipped(...))` left both discovered tasks with empty producer files.
- **Root cause:** typed extraction preserves the qualified target while Laravel discovery exposes only its short class-name identity; leading-root namespace syntax is not extracted either.
- **Required design direction:** canonical target aliases must explicitly model qualified and short Laravel names with collision/ambiguity behavior rather than implicit suffix matching.

### DD-017 — JS binder declaration/scope and member-alias model is incomplete

- **Observed:** runtime evidence was falsely created when `require` was shadowed by a nested `var`, named function expression, named class expression, or TypeScript `import_alias`. Conversely, safe member aliases such as `const Worker = require("bullmq").Worker` and `const Server = require("socket.io").Server` lost valid evidence.
- **Root cause:** the binder’s declaration vocabulary/scope model does not yet encode function/class expressions, TypeScript import aliases, or JavaScript `var` function scope; its value resolver does not represent member extraction from a literal module load.
- **Required design direction:** expand the bounded intrafile binder’s declaration and role graph, with fail-closed dynamic cases and TDD coverage for lexical scope plus member aliases.

## Still confirmed good

- Endpoint publication-ready boundary held in review.
- No secrets/injection/unsafe deserialization/security concerns were found in the branch diff.
- No `AGENTS.md` diff remained.
- The earlier direct correctness improvements are real for their covered shapes; they are insufficient as a universal release guarantee because the broader linking model remains unbounded/raw.

## Required decision

This is past the skill’s rule-of-three threshold: repeated micro-fixes are exposing one shared architecture problem. Do **not** add another local patch until the user approves a bounded replacement design:

1. product-owned `DispatchEvidence` / canonical-target contract emitted by language-aware extractors;
2. target ambiguity policy that never fans one spelling into every duplicate task record;
3. shared bounded task/scheduler endpoint linker over evidence/indexes;
4. expanded scoped JS binder role/declaration model;
5. alias-aware Laravel target normalization with explicit collision behavior.

The proposed work remains DeepDoc-owned; no GitNexus or external semantic service is required.
