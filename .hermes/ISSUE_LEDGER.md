# DeepDoc Issue Ledger

> **Canonical open-work record for `/Users/apple/tss/codegen/codewiki`.**
>
> Read this ledger before starting, planning, delegating, reviewing, or declaring any DeepDoc work complete. A newer task never removes an existing issue. Only independently verified evidence may close an issue. `deferred-by-user` requires explicit user direction and remains visible.

## Operating rules

1. **Every discovered bug/gap gets an ID** before implementation discussion moves on.
2. **No silent deferral:** an issue may be deferred only with the user's explicit approval and recorded rationale.
3. **No agent self-report closure:** Claude implementation claims are insufficient. Closure requires independent diff inspection, targeted regression evidence, full relevant suite, and where applicable a real benchmark run.
4. **Implementation policy:** production changes normally use Claude Code with `--model opus` and independent Hermes verification. On 2026-08-27, Pranav explicitly authorized Hermes to directly implement the narrow DD-001/DD-002 round-two redesign after a Claude provider/session constraint; it remains isolated and requires the same independent review and explicit merge approval.
5. **Merge policy:** Pranav reviews and explicitly approves before PR creation/merge. No auto-merge.
6. **Benchmark ownership:** Pranav runs the canonical VS Code before/after benchmarks. Preserve raw logs under `.hermes/audits/`.
7. **Continuity:** every substantive work block creates/updates a handoff under `.hermes/handoffs/` and references this ledger’s active IDs.

## Status vocabulary

| Status | Meaning |
|---|---|
| `open` | Confirmed issue; no approved implementation started. |
| `reproducing` | Tight regression loop being established. |
| `planned` | Design/brief is approved and ready for Claude. |
| `Claude implementing` | Claude Opus 5 is editing an isolated branch/worktree. |
| `verification` | Implementation exists; independent review/tests/benchmark evidence pending. |
| `blocked` | Cannot proceed; blocker and required decision are recorded. |
| `deferred-by-user` | Explicitly deferred; still must appear in open-work reports. |
| `closed` | Independently verified with evidence linked below. |

## Current priority order

### DD-001 — Runtime-surface scan is pathological and hidden behind the artifact progress label

- **Priority:** P0 — benchmark-blocking performance and correctness defect
- **Status:** `blocked`
- **Evidence:** `.hermes/audits/vscode-diagnostic-baseline-2026-08-27/runtime-scan-hotspot.md`; `.hermes/plans/2026-08-27-dd001-runtime-scan-stabilization.md`; `.hermes/audits/vscode-diagnostic-baseline-2026-08-27/runtime-linking-and-endpoint-blockers.md`
- **Observed on:** official `microsoft/vscode` commit `222818cc1d871f299b909604ea267e955182d2a4`
- **Confirmed facts:** prior telemetry recorded `scan.artifacts=4.956666624999343s`, `scan.runtime=856.018724208001s`, and `scan.config_impacts=3.116961875002744s`; UI prints only one label before all three. VS Code scan had 12,843 parsed files, 148,276,780 source bytes, and 79 detected runtime tasks.
- **Tight root-cause repro (2026-08-27):** Claude Opus 5 reproduced the issue against a deterministic 201-file / 1.27 MB corpus with only one real Celery task. The old scanner emitted 501 tasks (500 false TypeScript/fixture tasks), performed 41,004 full-content name probes, reached the task × regex sweep for all 201 files, had a 704,907 worst-case regex-search bound, and took 29.01 seconds. At 101 files / 0.64 MB it took 7.36 seconds; growth is materially superlinear.
- **Root cause:** runtime discovery treats raw content as language-agnostic executable evidence, allowing embedded Python snippets and low-trust fixture content to create task candidates. `_link_runtime_workflows()` then scans each repository file against every discovered task name and task regex family, amplifying the false candidate count into a files × tasks × patterns CPU multiplier.
- **Implementation branch:** `fix/runtime-scan-stabilization`, isolated worktree `/Users/apple/tss/codegen/codewiki-worktrees/runtime-scan-stabilization`, base `8d45e5a82487d37a2a4adbf622ffbff1a0cc4b22`, Claude launch verified as `claude-opus-5` with `--effort max`.
- **Real VS Code phase-only validation (2026-08-27):** against the same configured source corpus (12,843 files / 148,276,780 bytes), first fix measured `runtime_seconds=4.378843` versus the old `856.018724208001` (195.49× faster; 99.49% reduction). It correctly skipped 4,428 low-trust files and limited task-link work to 108 candidates. However, it still emitted 7 false `js_worker` tasks from generic product TypeScript `.process()`/`.consume()` calls. A direct repository search found no BullMQ/Bull/Bee-Queue/Kue/Agenda queue-library usage; therefore zero queue-runtime tasks are expected after the JS evidence follow-up.
- **Current blocker:** Fresh exact-head review `deleg_809597cb` rejected `4dd8b9fefa7c6d55ff58a93823121b76b2770f5f`, and Hermes reproduced each material claim. The remaining defect is architectural: duplicate-name task buckets, scheduler endpoint linking, and raw cross-language workflow regexes can still form cartesian work or false evidence. Do not add another local patch until an evidence/index/ambiguity redesign is approved. Evidence: `.hermes/audits/vscode-diagnostic-baseline-2026-08-27/runtime-final-review-round3-blockers.md`.
- **Required outcome:** granular phase progress; source-role/framework/language/**syntax-level queue-library** gating; indexed candidate selection; deterministic VS Code-scale regression coverage; no invented product runtime tasks from examples, template strings, or generic JS methods.
- **Blocks:** trustworthy large-repo runtime evidence and practical VS Code benchmark duration.

### DD-002 — Test fixtures, prompt corpora, and embedded examples contaminate product architecture facts

- **Priority:** P0 — generated-doc correctness defect
- **Status:** `open`
- **Evidence:** `.hermes/audits/vscode-diagnostic-baseline-2026-08-27/README.md`, `visible-terminal-excerpt.md`
- **Observed symptoms:** VS Code was classified with `uses_express`, `uses_fastapi`, and `uses_vue`; scanner reported `39 model file(s), 130 model(s), ORM: sqlalchemy` despite non-product examples/fixtures causing the signals.
- **Verified source seam:** `deepdoc/scanner/database.py` applies language-agnostic raw-content patterns such as `class ... Base`, `Column(`, and `relationship(`. Existing path exclusions do not cover all prompt/example source files.
- **Required outcome:** product/test/fixture/example/prompt/generated/vendor role classification; source-role-aware detector contracts; language-aware high-confidence framework/ORM evidence; explicit structural accounting rather than false architecture claims.
- **Relationship:** DD-002 is required for DD-001 runtime candidate quality and all later universal documentation quality.
- **Current slice:** Runtime endpoint publication remains protected on the isolated branch: engine passes published endpoints and linker defensively rejects `publication_ready=False`. JS/TS/Vue scheduler/realtime discovery is structural, but raw workflow linking still lets JS comments/templates/generic APIs become product task producer evidence. Runtime DD-002 is blocked pending the shared evidence-linking redesign; broad database/framework provenance remains `open`. See `.hermes/audits/vscode-diagnostic-baseline-2026-08-27/runtime-final-review-round3-blockers.md`.

### DD-003 — LLM rate limits silently degrade planning into auto-plan output

- **Priority:** P0 — benchmark validity and content-quality defect
- **Status:** `open`
- **Evidence:** `.hermes/audits/vscode-diagnostic-baseline-2026-08-27/raw/performance-runs.jsonl`, `visible-terminal-excerpt.md`
- **Observed facts:** diagnostic run made 225 LLM calls; four `azure/Kimi-K2.6` calls failed with `RateLimitError`; classification fell back to auto-plan. Telemetry recorded 16,026.434254672004 rate-limit wait seconds. Some failed prompts were above 100k tokens.
- **Required outcome:** distinguish retryable provider throttling from semantic/planning failure; bounded backoff/retry; provider/concurrency/token-budget diagnostics; run-level degraded/invalid state; no silently mixed normal/fallback benchmark accepted as canonical.
- **Acceptance:** fixture/provider-fake tests prove all rate-limit branches; benchmark metadata visibly records any fallback/degradation.

### DD-004 — Benchmark harness cannot yet prove DeepWiki-quality output

- **Priority:** P1 — product-proof gap
- **Status:** `planned`
- **Evidence:** `.hermes/plans/2026-08-26_181229-universal-deepwiki-content-roadmap.md` (Slice C0); audit README above.
- **Current gap:** benchmark scorecard can reward incomplete/empty gold data and does not sufficiently score package/workspace, build/runtime, hierarchy, factual claims, or reader success.
- **Required outcome:** pinned benchmark catalog and gold contracts for Vue core, React, VS Code, real Vue/React apps, Rust/Cargo, Java/Spring, and .NET; non-empty-gold guard; quality, coverage, cost/time, and human task gates.

### DD-005 — Repository facts are not persistent, normalized, or universally accounted for

- **Priority:** P1 — foundation for universal support
- **Status:** `planned`
- **Evidence:** universal roadmap Slice C1; historical planner/source audit.
- **Current gap:** facts are scattered across `RepoScan`, parsed files, call graph, routes, runtime, artifact, and framework records. Unsupported readable files are structurally invisible rather than explicitly modeled.
- **Required outcome:** versioned `SourceIndex` / `RepositoryModel` with `FileRecord`, `Entity`, `Relationship`, `Evidence`, `Capability`, diagnostics, source hash/extractor provenance, and `RepoScan` compatibility projection.

### DD-006 — Workspace/package/build/runtime starting points are not first-class architecture evidence

- **Priority:** P1 — large-repo hierarchy blocker
- **Status:** `planned`
- **Evidence:** universal roadmap Slice C2.
- **Current symptom:** VS Code becomes arbitrary recursive `core/part-*` planning units because `services: []` and no package/workspace graph supplies semantic roots.
- **Required outcome:** `WorkspaceGraph` and `BuildRuntimeGraph` adapters for Node workspaces, pnpm/Yarn/npm/Turbo/Nx/Lerna, TS references/aliases, Maven/Gradle (`pom.xml` included), Cargo, .NET solutions/projects, Go modules/workspaces, Python package roots, Gemfile, and composer metadata.

### DD-007 — Unsupported languages are present but unparsed and undocumented

- **Priority:** P1 — universal product-coverage blocker
- **Status:** `planned`
- **Evidence:** VS Code diagnostic audit; universal roadmap Slice C3.
- **Observed VS Code examples:** Rust, C/C++, C#, Java, Ruby, Clojure, Dart, Groovy, Objective-C/Objective-C++, R, and Swift were reported unsupported.
- **Required outcome:** universal safe text/config fallback; Tree-sitter `LanguagePack` contract; structural entities/ranges/imports where grammars exist; explicit capability/coverage states; initial structural packs for Rust, Java, Kotlin, C#, and C/C++.

### DD-008 — Existing JS/TS/Vue analysis lacks product-specific architecture depth for benchmark targets

- **Priority:** P1 — DeepWiki-content gap
- **Status:** `planned`
- **Evidence:** universal roadmap Slice C4.
- **Required outcome:** framework packs that contribute normalized evidence rather than separate planner paths: Electron/VS Code processes, IPC, extension contributions/commands/activation; React workspace/renderer/JSX/hooks/context/state/router facts; Vue SFC compiler spans/template components/router/Pinia/SSR/HMR facts. Preserve and normalize existing Python/Node/PHP/Go enrichers.

### DD-009 — Wiki generation lacks durable bottom-up subsystem hierarchy

- **Priority:** P1 — DeepWiki-content gap
- **Status:** `planned`
- **Evidence:** universal roadmap Slice C5.
- **Current gap:** planning units make bounded pages possible but do not by themselves create a coherent repo → workspace/package → subsystem → runtime/build → implementation hierarchy.
- **Required outcome:** deterministic `PackageCard`, `ComponentCard`, `BuildTargetCard`, `RuntimeSurfaceCard`, and `SubsystemCard`; bounded global synthesis; one coherent architecture/navigation map without a whole-repository prompt.

### DD-010 — Compiler-backed semantic precision is absent for many ecosystems

- **Priority:** P2 — progressive quality upgrade
- **Status:** `planned`
- **Evidence:** universal roadmap Slice C6.
- **Required outcome:** optional, sandboxed/cached SCIP ingestion and bounded LSP/semantic providers. Providers must enrich evidence when available and never block structural documentation or silently upgrade heuristic facts.

### DD-011 — DeepWiki-style visible source citations are deferred, not forgotten

- **Priority:** P2 — trust/product polish after content foundation
- **Status:** `deferred-by-user`
- **Decision:** user explicitly chose content/universal repository understanding before visible citations.
- **Required later outcome:** evidence-first validated source chips/links, commit-pinned source references, and claim support validation. Internal provenance remains required in DD-005 even while visible citation UI is deferred.

### DD-012 — Verbose benchmark logging floods disk with repeated debug and prompt bodies

- **Priority:** P1 — operational observability, benchmark hygiene, and local-source privacy concern
- **Status:** `open`
- **Evidence:** live run log `/Users/apple/personal/delete/vscode/logs.log`, inspected 2026-08-27.
- **Observed facts:** the file reached `156,910,105` bytes while the VS Code run was active. Its terminal formatting uses carriage-return progress records, making ordinary line reads misleading. More importantly, `-v` logging repeatedly emits LiteLLM model-cost-map diagnostics and `token_counter` prompt/context bodies containing large source/symbol excerpts, often duplicated by library and application loggers.
- **Impact:** benchmark evidence becomes difficult to inspect/archive, incurs unnecessary local I/O, and retains more repository source/prompt content than a phase-level operational log needs.
- **Required outcome:** investigate logging configuration and duplication; retain structured phase/model/retry metadata while suppressing raw prompt/content bodies by default (including verbose benchmark runs unless an explicit unsafe diagnostics mode is selected); add redaction/size regression coverage.
- **Scope decision:** do not bundle this with DD-001's runtime algorithm fix. First establish the exact logger/configuration ownership and a tight output regression test.

### DD-013 — Ambiguous runtime target names can recreate files × tasks work

- **Priority:** P0 — DD-001 release blocker
- **Status:** `blocked`
- **Evidence:** `runtime-final-review-round3-blockers.md`.
- **Observed:** 251 same-name `sync` tasks and 257 `sync.delay(...)` producers produced 64,507 task checks.
- **Required outcome:** canonical target/evidence representation with ambiguity fail-closed or a bounded target abstraction; never expand one ambiguous spelling across every task record.

### DD-014 — Workflow linking still uses raw cross-language dispatch text

- **Priority:** P0 — DD-001/DD-002 release blocker
- **Status:** `blocked`
- **Evidence:** `runtime-final-review-round3-blockers.md`.
- **Observed:** JS comments/template literals/generic method calls linked real Python tasks; separate marker grammar missed valid whitespace dispatch syntax.
- **Required outcome:** language-aware dispatch evidence shared with the linker; no raw JS/TS/Vue workflow facts and no marker/extractor grammar drift.

### DD-015 — Scheduler endpoint linking remains an endpoint-file × scheduler sweep

- **Priority:** P0 — DD-001 release blocker
- **Status:** `blocked`
- **Evidence:** `runtime-final-review-round3-blockers.md`.
- **Observed:** 251 schedulers and 257 endpoint files yielded 64,507 irrelevant scheduler-pattern checks.
- **Required outcome:** evidence-indexed scheduler endpoint linking or bounded source ownership; scan telemetry must expose its work.

### DD-016 — Laravel FQCN dispatches lack canonical target aliases

- **Priority:** P0 — runtime workflow correctness blocker
- **Status:** `blocked`
- **Evidence:** `runtime-final-review-round3-blockers.md`.
- **Observed:** namespaced Laravel dispatch syntax cannot link to short-name discovered job/event records.
- **Required outcome:** explicit qualified/short target alias policy with collision handling, including leading-root namespaces.

### DD-017 — JS binder misses scope forms and safe module-member aliases

- **Priority:** P0 — runtime evidence correctness blocker
- **Status:** `blocked`
- **Evidence:** `runtime-final-review-round3-blockers.md`.
- **Observed:** shadowed `require` via nested var/named function or class expressions/TS import aliases creates false facts; `require('bullmq').Worker` and `require('socket.io').Server` lose safe facts.
- **Required outcome:** bounded intrafile declaration/scope model (including var and expression names) plus literal-module member extraction; dynamic flows remain fail-closed.

## Closed foundations / context

| Item | Status | Verification context |
|---|---|---|
| Slice A bounded planning units | closed | merged before this ledger; planner split/retry/page-cap invariants were independently verified. |
| Slice B conservative semantic ownership | closed | merged before this ledger; isolation/privacy/ownership regressions were independently verified. |

## Linked artifacts

- Universal roadmap: `.hermes/plans/2026-08-26_181229-universal-deepwiki-content-roadmap.md`
- VS Code diagnostic baseline: `.hermes/audits/vscode-diagnostic-baseline-2026-08-27/README.md`
- Runtime hotspot: `.hermes/audits/vscode-diagnostic-baseline-2026-08-27/runtime-scan-hotspot.md`
- Raw telemetry/config: `.hermes/audits/vscode-diagnostic-baseline-2026-08-27/raw/`

## Update template

```markdown
### DD-NNN — Short title
- **Priority:** P0/P1/P2
- **Status:** open/reproducing/planned/Claude implementing/verification/blocked/deferred-by-user/closed
- **Evidence:** audit, test, log, or reproducible command
- **Impact:** what breaks or becomes untrustworthy
- **Required outcome:** observable completion condition
- **Verification:** command/result/benchmark evidence when closed
- **Dependencies / decision:** related IDs and any explicit user choice
```
