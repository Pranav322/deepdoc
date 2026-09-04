# DeepDoc Handoff — VS Code Diagnostic Baseline and Universal Roadmap

**Date:** 2026-08-27

## Goal

Build DeepDoc into a universal, DeepWiki-class documentation platform for large repositories. The immediate user priority is **content quality and universal repository understanding**, not visible source-citation UI.

## Non-negotiable operating rules

- Claude Code performs all production implementation using `--model opus`; a no-tool local probe verified this resolves to `canonicalModel: claude-opus-5`.
- Hermes does investigation, briefs, independent verification, and adversarial review only; it does not write production code.
- Work happens in isolated feature branches/worktrees.
- Pranav approves before any PR/merge.
- Pranav runs canonical VS Code before/after benchmarks.
- Read `.hermes/ISSUE_LEDGER.md` first; it is the canonical unresolved-work record.

## Current benchmark state

A VS Code diagnostic run against official `microsoft/vscode` commit `222818cc1d871f299b909604ea267e955182d2a4` was captured under:

```text
.hermes/audits/vscode-diagnostic-baseline-2026-08-27/
```

The run is **not a canonical quality baseline**. It ended with `KeyboardInterrupt` after confirming:

- four Azure/Kimi rate-limit failures, with auto-plan fallback;
- fixture/prompt/example contamination causing false Express/FastAPI/Vue/SQLAlchemy/product-runtime signals;
- a hidden runtime-surface scan that took 856.018724208001 seconds (14.27 minutes) on the prior run;
- arbitrary `core/part-*` planner splitting because no workspace/package roots exist;
- unsupported non-TS languages are unparsed/unaccounted structurally.

A retry using a different LLM model was active during this handoff. Its local scan performance is independent of LLM model selection; capture its outcome as a separate audit record when it stops.

## Current open work

Read the full ledger for acceptance criteria. Immediate ordering:

1. **DD-001** Runtime-scan performance and misleading phase display.
2. **DD-002** Fixture/prompt/example contamination and false architecture facts.
3. **DD-003** Rate-limit handling must not silently yield mixed fallback plans.
4. **DD-004** Benchmark contract and non-empty gold/evaluation gates.
5. **DD-005–DD-010** Universal SourceIndex, manifest/workspace topology, language packs, framework overlays, hierarchy synthesis, and optional semantic providers.
6. **DD-011** Visible citations are deliberately deferred by user; retain internal provenance from the SourceIndex work.

## Existing planning artifacts

- `.hermes/plans/2026-08-26_181229-universal-deepwiki-content-roadmap.md` — approved conceptual C0–C6 sequence.
- `.hermes/audits/vscode-diagnostic-baseline-2026-08-27/runtime-scan-hotspot.md` — source-backed diagnosis of the first immediate performance bug.

## Next safe action

Before any coding brief, re-verify the live tree and current VS Code telemetry. The first Claude brief should isolate DD-001/DD-002/DD-003 as a small benchmark-reliability stabilization effort, with red regression tests and no broad SourceIndex rewrite bundled into it.

## What must not be forgotten

- Do not hide unsupported languages with excludes to make coverage look better.
- Do not call a rate-limited/fallback run a quality benchmark.
- Do not infer actual VS Code product frameworks from test fixtures, prompts, code snippets, or generated data.
- Do not remove current specialized language/framework parsers; universal SourceIndex work wraps and normalizes them.
- `pom.xml`, Cargo, package/workspace manifests, Gradle, `.sln`, etc. are C2 first-class architecture starting points.
- Keep `.hermes/` artifacts out of commits unless Pranav explicitly asks otherwise.
