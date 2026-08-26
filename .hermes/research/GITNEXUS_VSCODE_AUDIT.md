# GitNexus on VS Code — Completeness and Suitability Audit

**Audit date:** 2026-08-23  
**VS Code revision:** `47c287090a4f2432f67876b9861666cd7c5eafc1`  
**GitNexus package:** `1.6.9`  
**GitNexus source audited:** `aac7515d2a8c50a1f8f923c6fb77218b333560d6`  
**Machine:** macOS, 10 logical CPUs, 16 GiB RAM  

## Executive verdict

**GitNexus 1.6.9 is not acceptable unchanged as DeepDoc's sole production semantic backend for VS Code-scale repositories.** It successfully constructs a large and useful graph, and its ordinary static relationships are good enough to make it valuable infrastructure. However, the audited run is not a complete graph of VS Code, misses important source through broad ignore rules, does not recover several architecture-defining runtime relationships, produces weak global process/community labels, and failed a one-file incremental update badly enough to hit the 16 GiB database ceiling and make a later query segfault.

**Recommendation:** Do not discard GitNexus and rebuild every parser/resolver immediately. Its 16-language parsing and static resolution substrate is too substantial to reproduce cheaply. But do not integrate the current public binary as a trusted black box either. Proceed only if the commercial arrangement permits a supported fork or upstream fixes for the blockers below, plus a stable graph export and machine-readable coverage. Re-run this audit after those fixes. If Akon Labs will not support those requirements, build DeepDoc's semantic engine itself.

In short:

> **Keep GitNexus as a candidate foundation, not as an accepted backend. It is a conditional go after remediation, and a no-go as currently shipped.**

## 1. Method

The audit did not equate successful process exit with graph completeness. It measured:

1. Pinned repository inventory and source-language composition.
2. Files excluded by size, ignore rules, and parser support.
3. A full GitNexus index with the file-size threshold raised to 16 MiB.
4. Node and edge distributions.
5. Representative graph relationships for DI, commands, extension points, RPC, language features, and startup.
6. Community labels and process traces.
7. Search behavior for architecture queries.
8. One reversible dirty-working-tree incremental change.
9. Database, disk, memory, and mutation behavior.

All temporary source changes were restored after the incremental test. The audit clone was disposable and remains outside the DeepDoc repository.

## 2. VS Code baseline

At the pinned revision:

- 18,131 tracked files
- 13,200 recognized programming-language source files
- 159,838,479 source bytes (~152.4 MiB)
- 12,555 `.ts` files
- 266 `.tsx`
- 138 `.js`
- 88 Rust
- 75 Python
- 23 C/C++ source/header files
- 16 C#
- 7 Java
- 5 Ruby
- 4 Go
- 3 PHP
- 1 Dart
- 1 Swift

### Large source files

- 9 recognized source files exceed 512 KiB.
- 2 exceed 1 MiB.
- 1 exceeds 8 MiB by 96 bytes.
- None exceed GitNexus's hard 32 MiB Tree-sitter ceiling.

The largest is an 8.39 MiB generated colorization performance fixture. A material file, `src/vscode-dts/vscode.d.ts`, is ~742 KiB and is also independently excluded by GitNexus's blanket `.d.ts` rule.

## 3. Full index result

Command:

```bash
env GITNEXUS_VERBOSE=1 \
  npx -y gitnexus@1.6.9 analyze /tmp/vscode-gitnexus-audit \
  --force --max-file-size 16384
```

Observed result:

```text
Repository indexed successfully (1740.4s)
298,902 nodes | 1,171,744 edges | 13,833 clusters | 300 flows
```

Measured by `/usr/bin/time -l`:

- wall time: 1,743.26 seconds (~29m 3s including wrapper)
- maximum resident set size: 3,851,403,264 bytes (~3.59 GiB)
- no swaps
- persisted `.gitnexus` directory after the clean run: ~3.5 GiB
- embeddings: 0
- FTS: reported available in finalized metadata

### Large-file behavior

Raising the threshold admitted the 8.39 MiB fixture into the worker workload, but it exhausted the cumulative timeout budget and was quarantined. The index continued with one quarantined file. This omission is likely benign because the file is generated performance data, but it proves that raising the byte limit does not guarantee parsing.

### Node distribution

- Method: 102,798
- Property: 67,729
- Function: 39,644
- Const: 30,004
- File: 13,586
- Class: 13,360
- Interface: 13,075
- persisted Community nodes: 11,970
- Folder: 3,568
- Section: 2,129
- Process: 300
- plus Struct, Module, Impl, Enum, Trait, Macro and other nodes

The command summary reported 13,833 clusters, while the persisted graph query returned 11,970 Community nodes. This discrepancy must be explained before DeepDoc treats headline cluster counts as persisted facts.

### Edge distribution

- CALLS: 365,884
- ACCESSES: 293,477
- IMPORTS: 112,542
- HAS_METHOD: 104,923
- DEFINES: 94,723
- MEMBER_OF: 74,216
- HAS_PROPERTY: 65,946
- CONTAINS: 19,265
- METHOD_OVERRIDES: 14,634
- METHOD_IMPLEMENTS: 12,938
- EXTENDS: 6,164
- IMPLEMENTS: 5,358
- STEP_IN_PROCESS: 1,647
- HANDLES_ROUTE: 15

These figures prove that GitNexus extracted a substantial semantic graph. They do not prove every edge is correct or every relevant source file is represented.

## 4. Inventory completeness

Comparing `git ls-files` against persisted GitNexus File nodes:

- tracked files indexed: 13,586 / 18,131 = **74.93%**
- recognized source files indexed: 11,220 / 13,200 = **85.00%**
- tracked files absent: 4,545
- recognized source files absent: 1,980

Therefore the result is not a complete repository graph.

### Material missing source

Representative absent files:

- `src/vscode-dts/vscode.d.ts`
- `src/vs/base/parts/ipc/common/ipc.ts`
- `src/vs/platform/log/common/log.ts`
- `src/vs/workbench/contrib/output/common/outputChannelModel.ts`
- `cli/src/bin/code/main.rs`
- `build/gulpfile.ts`
- `.eslint-plugin-local/code-layering.ts`

### Causes

GitNexus's default ignore logic matches generic directory names anywhere in a path. Material collisions include:

- 217 supported-language files under directories named `parts`
- 255 supported-language files under `build`
- 25 under `log`
- 6 under `logs`
- 12 under `output`
- 7 under `env`
- 2 under `bin`
- 109 supported-language files under dot-prefixed paths
- 231 TypeScript declaration files excluded after other rules

Important consequences:

- `src/vs/base/parts/**` contains core IPC, sandbox, request and worker primitives.
- `src/vs/platform/log/**` is production logging architecture.
- `src/vs/workbench/contrib/output/**` is a real feature subsystem.
- `cli/src/bin/**` contains Rust executable entry points.
- `build/**` is executable build, packaging, signing and release logic.
- `.eslint-plugin-local/**` defines enforced architectural constraints.
- `src/vscode-dts/**` contains the public/proposed extension API contract.

The raised file-size threshold does not recover paths excluded by these rules.

### Non-code semantic gaps

GitNexus creates File nodes for many admitted non-code files, but does not generally parse them semantically:

- ~1,419 JSON/JSONC files
- ~471 YAML/YML files
- ~415 CSS-family files
- HTML/templates beyond narrow URL extraction
- shell, PowerShell and batch build scripts

This matters in VS Code because extension `package.json` contribution points, activation events, commands, menus, configuration schemas, product metadata, CI, language grammars, themes and build orchestration are architecture—not incidental assets.

## 5. Semantic edge quality

A curated source-grounded oracle set covered command services, DI, extension points, main-thread/ext-host RPC, language-provider registration and startup.

### Strong results

GitNexus correctly resolved ordinary static relationships such as:

- `CommandService IMPLEMENTS ICommandService` across files, confidence 0.85.
- `MainThreadCommands IMPLEMENTS MainThreadCommandsShape`, confidence 0.85.
- Imported calls from `CommandService` into commands, lifecycle and async utilities.
- `CommandService.executeCommand → CommandService._tryExecuteCommand`.
- `MainThreadCommands.$registerCommand → CommandsRegistry.registerCommand`.
- Method implementation and override relationships.
- `menusExtensionPoint.ts → ExtensionsRegistry.registerExtensionPoint` as an imported call.

These are meaningful strengths. The graph is far ahead of a regex-only call graph.

### Missing or incomplete architecture-defining relations

1. **Dependency injection is not represented as a semantic injection edge in the inspected path.** Constructor decorators such as `@IExtensionService` become property/access facts, but the queried graph did not expose the expected `INJECTS` relationship.
2. **Service registration remains a generic call.** `registerSingleton(ICommandService, CommandService, Delayed)` is visible as a call to `registerSingleton`, but the graph query does not directly expose a service-token → implementation → lifecycle binding.
3. **Extension-point registration is syntactically visible but not fully modeled.** The call to `registerExtensionPoint` exists, but the semantic contract (`commands`, schema, handler flow) is not a first-class graph relation.
4. **RPC shape methods are resolved, but concrete cross-process endpoints are not joined.** `ExtHostCommands.registerCommand` calls protocol method `$registerCommand`, but no direct semantic relation connects it to concrete `MainThreadCommands.$registerCommand`.
5. **Main-thread command execution delegation was absent in the direct query.** The expected `$executeCommand → CommandService.executeCommand` relationship did not appear.
6. **Public API delegation was misresolved.** `vscode.languages.registerCompletionItemProvider` in `extHost.api.impl.ts` produced a same-name self-file edge rather than the expected call to `ExtHostLanguageFeatures.registerCompletionItemProvider`.
7. **Completion provider registration did not connect to the registry's `register` method.** The graph captured property access and protocol/interface edges but not the key runtime registration relationship.
8. **Proxy acquisition was not semantically linked.** Constructor calls to `getProxy(MainContext/ExtHostContext...)` were not surfaced as directional RPC endpoint relationships.

These are exactly the relationships a DeepWiki-class architecture explanation needs. They require framework/convention enrichers above generic TypeScript resolution.

### False/weak relationships observed

- Same-name wrapper calls such as `registerCompletionItemProvider → registerCompletionItemProvider` within `extHost.api.impl.ts` at confidence 0.53.
- Repeated identical local call edges in some queried methods.
- Generic terminal targets such as `Node`, `_hashFn`, `Get`, `Trace`, and `_throwIfStrict` dominate process output.

## 6. Communities

The graph persisted 11,970 Community nodes with 2,240 unique labels.

Most frequent labels:

- `Browser`: 3,326 communities
- `Node`: 1,346
- `Vscode-node`: 310
- `Test`: 186
- `Electron-main`: 177
- `Electron-browser`: 173
- `AgentHost`: 123

Useful domain labels do appear, including `LanguageFeatures`, `AgentHost`, `TsServer`, `Tunnels`, `VoiceClient`, `GhostText` and others. However:

- Communities are far too numerous and flat to form a documentation hierarchy directly.
- Labels are heavily duplicated and often reflect folder/platform names rather than subsystem intent.
- Important parent domains—base, platform, editor, workbench services, workbench contributions, extension API/host, remote server, built-in extensions, sessions, build/tooling—are not delivered as a coherent hierarchy.
- Missing `parts`, `log`, declarations and manifest semantics distort clustering.

Conclusion: communities are useful raw partition signals, not publishable doc units.

## 7. Process quality

The index persisted the configured maximum of 300 processes, containing 1,647 process steps.

Distribution shows low global usefulness:

- 189 unique labels among 300 processes.
- 77 start with `Run`.
- 76 start with `Constructor`.
- 26 start with `Dispose`.
- Common terminals include `IsMonitoring` (37), `_hashFn` (21), `Node` (21), `Get` (21), `_throwIfStrict` (21), and `Trace` (21).

Representative output included repeated:

```text
Run → _hashFn
Run → Node
Constructor → Uri
```

Queries for:

- `extension command registration`
- `completion provider registration language features`
- `Electron main workbench startup`

returned relevant symbol definitions but no matching process records. The process search for command/extension/workbench primarily surfaced editor command internals, not the expected extension-host command or startup flows.

Conclusion: GitNexus processes are useful exploration hints but are not adequate as DeepDoc's ready-to-publish workflow model. DeepDoc would need documentation-oriented entry detection, RPC/DI/registration overlays, meaningful effect tails and scoped on-demand tracing.

## 8. Incremental update test

A reversible exported sentinel function was appended to:

```text
src/vs/base/common/arrays.ts
```

Then plain `gitnexus analyze` was run.

### Result

- Wall time: **2,025.24 seconds (~33m 45s)**—slower than the full 29-minute rebuild.
- Maximum RSS: ~3.06 GiB.
- GitNexus reverted from the full run's explicit 16 MiB threshold to its default 512 KiB threshold.
- It classified the update as `changed=2, added=1, deleted=22`.
- It expanded one source edit to **7,055 transitive importers** within BFS depth ≤4.
- LadybugDB repeatedly failed manual WAL checkpointing because the default **16 GiB maximum database size** was reached.
- `.gitnexus` grew from ~3.5 GiB after the full run to ~6.1 GiB after the incremental attempt.
- A subsequent Cypher query for the sentinel crashed with **SIGSEGV (exit 139)**.
- `gitnexus status` still reported the repository as up-to-date because the Git commit had not changed.
- Metadata retained the previous successful index timestamp/commit rather than proving the dirty-worktree update was safely committed.

The temporary sentinel and GitNexus edits to `AGENTS.md`/`CLAUDE.md` were restored afterward.

### Interpretation

This incremental behavior is a production blocker:

1. Analysis policy is not persisted or automatically reused. Changing the max-file setting between runs creates false deletions.
2. A highly imported foundational utility can expand incremental scope to most of a monorepo, eliminating expected speed gains.
3. Database sizing/checkpoint behavior can fail at VS Code scale.
4. The run did not return a clear nonzero failure through the observed wrapper despite checkpoint failures.
5. Read safety after the failed update is questionable because a query segfaulted.
6. Commit-only status is insufficient for dirty-worktree freshness.

A production integration must pin every policy on every run, use staged/atomic graph replacement, provide explicit success receipts, validate post-write graph counts, account for working-tree dirtiness, and recover from checkpoint failure without exposing a potentially unhealthy database.

## 9. Repository mutation behavior

A normal `gitnexus analyze` modified the target repository by:

- appending a large GitNexus instruction block to tracked `AGENTS.md`;
- creating `CLAUDE.md`;
- creating `.gitnexus/` state.

The audit command did not request skill generation. DeepDoc must not permit an indexing sidecar to mutate user-authored instruction files by default. Commercial integration needs an explicit no-mutation mode or must run against an isolated mirror/worktree and copy only graph output back.

## 10. Decision matrix

### Use current GitNexus binary unchanged as sole backend

**NO-GO.** It fails inventory completeness, important convention-level semantics, documentation-quality process output, safe incremental performance, and post-failure database reliability on this audit.

### Throw GitNexus away and build everything in DeepDoc now

**Not recommended yet.** The successful full run produced a rich 16-language graph with hundreds of thousands of resolved static relations. Rebuilding its parser/provider/resolution substrate would be a very large effort and would duplicate demonstrated value.

### Recommended path: licensed, remediated GitNexus foundation

Proceed with GitNexus only if the commercial agreement permits either upstream fixes or a supported fork and provides a stable export contract. Required blockers:

1. Replace broad basename ignores with anchored/context-sensitive rules.
2. Support repository-owned `.d.ts` files.
3. Make dot-path inclusion configurable despite `glob dot:false`.
4. Emit machine-readable per-file disposition: indexed, ignored rule, oversized, unsupported, parse failure, quarantine.
5. Persist and enforce analysis policy across full and incremental runs.
6. Fix incremental changed-set explosion or add safe thresholds that deliberately escalate to a staged full rebuild.
7. Make DB max size adaptive/preflighted and checkpoint failure fatal.
8. Guarantee atomic last-known-good graph after failed updates.
9. Fix the observed post-update query crash.
10. Provide no-mutation indexing mode.
11. Add semantic enrichers/contracts for DI registrations, extension points, RPC proxy pairs, contribution manifests and process boundaries.
12. Provide scoped process tracing beyond the capped global top 300.
13. Explain and reconcile headline versus persisted community counts.

After these fixes, repeat the pinned VS Code audit and require:

- ≥98% inclusion of intended first-party source after explicit exclusions;
- 100% accounted file disposition;
- curated architecture-edge recall high enough for documentation (target ≥90% on agreed oracle set) without high-confidence false edges;
- recognized startup/extension-host/language-feature processes;
- one-file incremental update materially faster than full rebuild or an explicit, safe staged-full escalation;
- no DB corruption/segfault;
- no repository-content mutation;
- stable export and successful DeepDoc import.

## Final answer

GitNexus demonstrates that the difficult 16-language semantic core is worth reusing, but the current release does **not** create a complete or sufficiently trustworthy VS Code architecture graph. The best path is not "blindly keep" or "immediately rebuild everything": it is **license GitNexus only with remediation rights/support, make the above fixes, and re-audit**. If those conditions cannot be obtained, DeepDoc should build its own graph engine because integrating the current binary would make completeness and incremental correctness claims we cannot defend.
