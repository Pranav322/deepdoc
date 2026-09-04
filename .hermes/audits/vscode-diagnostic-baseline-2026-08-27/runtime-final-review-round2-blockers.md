# DD-001/DD-002 Runtime Final Review — Round 2 Blockers

**Date:** 2026-08-27  
**Feature branch:** `fix/runtime-scan-stabilization`  
**Reviewed code head:** `e2e028ab30248ec8419c4a2d090ba92944b73fd5`  
**Current descendant:** `f28e04c2836d61ec13626d7b34d111fc35edc9f2` (only removes an out-of-scope `AGENTS.md` line; production code is identical)

## Verdict

**Blocked. Do not merge, push, or call DD-001/DD-002 runtime work complete.**

The previously accepted endpoint publication boundary holds, but the final adversarial review found four universal runtime-inference blockers. Hermes independently replayed every one using ephemeral in-memory probes; no VS Code scan was started.

## Reproduced blockers

### 1. DD-001 — word-run dispatch index can recreate files × tasks work

`_dispatch_index_keys()` indexes only the first and last word runs. Distinct task names `queue-0-sync` through `queue-250-sync` all share `sync`.

- 251 tasks
- 257 files containing `sync.delay(payload)`
- observed: `link_candidate_files=257`, `link_task_checks=64507` (= 251 × 257)
- no task actually matched, but every one was regex-verified

This invalidates the universal boundedness claim.

### 2. DD-001 — duplicate task names lose trigger semantics depending on list order

`task_patterns` and `task_tokens` are keyed only by task name. Two distinct Django signal tasks named `handle`, with triggers `post_save` and `post_delete`, collapse.

- create `[post_save, post_delete]`: `post_save.send(...)` links neither
- reverse `[post_delete, post_save]`: the same producer links both

The implementation is order-dependent and breaks valid `.send` linkage.

### 3. DD-001 — whitespace-tolerant JS queue calls are discarded by the prefilter

The JS prefilter requires literal `.process(` / `.consume(`. A valid Bull call:

```js
const q = new Bull("emails");
q.process ("send-digest", handler);
```

produces no worker, even though parsing/binding should support the whitespace.

### 4. DD-002 runtime sub-slice — raw JS scheduler/realtime scanners bypass structural evidence

`_discover_schedulers()` and `_discover_realtime_consumers()` receive raw JS/TS/Vue source outside `js_bound_calls`.

- a TypeScript template literal containing `cron.schedule("* * * * *", work)` emits a `node_cron` scheduler;
- a template literal containing `socket.io` and `io.on("connection")` emits a `socket_io` consumer.

This violates the source-syntax/API-role contract: non-executable text can still become product runtime architecture evidence.

## Confirmed working behavior

- Engine passes `scan.published_api_endpoints` to runtime discovery.
- Runtime linker also excludes `publication_ready=False` defensively.
- A focused endpoint probe retained `POST /visible` and excluded `GET /hidden`.
- Low-trust fixture and embedded foreign-language probes did not create Python runtime tasks.
- Unique-task grammars, punctuation queue `queue.add('---')`, and no-word Nest cron task indexing remain functional.
- No credential, injection, or external-scope security issue was found.

## Required redesign direction

Do not add another generic word-run workaround. The next correction needs:

1. **Grammar-specific exact dispatch indexes**, keyed by the exact syntax each grammar can name, rather than leading/trailing word fragments.
2. **Task-identity-specific pattern/token ownership**, so same-name tasks with different triggers do not overwrite each other.
3. A whitespace-tolerant, still-cheap JS prefilter before tree-sitter binding.
4. JS scheduler/realtime evidence routed through structural import/binding/API-role analysis, with raw Python-only detectors kept separate.

This is now a coherent but larger runtime-linking redesign, not the original tiny fallback fix.
