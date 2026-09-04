# DD-001 Runtime Scan Stabilization Plan

> **Implementation policy:** Claude Code on `claude-opus-5` performs all production edits. Hermes does not edit production code; it verifies root cause, reviews the diff, and reruns tests independently.

**Goal:** Make large-repository runtime-surface discovery accurate, bounded, and observable without weakening valid Python/JS/TS/Go/PHP runtime detection.

**Scope:** DD-001 and the runtime-specific portion of DD-002 only.

**Out of scope:** DD-003 rate-limit/retry behavior; SourceIndex; workspace topology; language packs; broad framework rearchitecture; visible citations.

## Verified baseline facts

- `deepdoc/planner/engine.py` prints one `Scanning for setup/deploy/test artifacts...` line and then runs artifacts, runtime discovery, and config impacts without intermediate progress.
- VS Code telemetry at commit `222818cc1d871f299b909604ea267e955182d2a4` recorded:
  - `scan.artifacts`: `4.956666624999343s`
  - `scan.runtime`: `856.018724208001s` (14.27 minutes)
  - `scan.config_impacts`: `3.116961875002744s`
- The VS Code scan had 12,843 parsed source files, 148,276,780 source bytes, and 79 detected runtime tasks.
- `discover_runtime_surfaces()` calls multiple framework/runtime discoverers across all `file_contents`, then `_link_runtime_workflows()` scans candidate names and regex patterns across repository files.
- Existing `source_kind_by_file`, `classify_source_kind()`, and `is_low_trust_source_kind()` exist but runtime discovery does not currently consume them.
- The prior scan falsely produced product runtime/framework/database facts from fixture/prompt/example content.

## Root-cause confirmation gate

Claude must first verify the live tree and establish a tight deterministic regression loop. It must not assume the audit is complete truth.

The confirmation evidence must show:

1. the user-visible phase label spans artifact/runtime/config work;
2. a low-trust fixture/example or embedded foreign-language example can currently create an inappropriate runtime candidate or force unnecessary detector/linker work;
3. valid product runtime detection remains a behavior worth preserving;
4. the expensive behavior is algorithmic, not caused by the LLM provider.

If live code materially differs, Claude must state the discrepancy and use the smallest evidence-backed correction—not start a broad redesign.

## Implementation direction to validate, not blindly copy

1. Reuse the existing `source_kind_by_file` and `is_low_trust_source_kind()` seam; do not create a second source-kind system.
2. Pass source-kind/language evidence into runtime discovery while preserving backward-compatible direct callers where appropriate.
3. Gate framework-specific runtime detectors by actual parsed language and high-confidence local evidence. Do not infer Python runtime behavior from Python snippets inside TypeScript prompt strings.
4. Exclude low-trust fixture/test/example/generated inputs from **product runtime architecture** discovery by default.
5. Avoid a files × task-names × regex sweep for workflow linking. Build deterministic, bounded candidate indexes and only search relevant eligible product files.
6. Emit distinct operator progress messages/timings for artifacts, runtime surfaces, and config impacts.
7. Preserve real product runtime behavior with tests; do not “fix” speed by deleting all runtime detection.

## Likely files (Claude must verify)

- `deepdoc/planner/engine.py`
- `deepdoc/scanner/runtime.py`
- `deepdoc/source_metadata.py` only if a genuinely missing generic path category is proven
- `tests/test_runtime_scan.py`
- `tests/test_scan_telemetry.py`
- possibly a focused new scan regression test file

## Mandatory TDD acceptance cases

1. **RED:** a low-trust fixture/example with runtime-looking content does not become a product runtime task after the fix; it must fail under the old behavior.
2. **RED:** a TypeScript/JavaScript prompt/example containing Python framework syntax does not trigger Python runtime discovery; it must fail under the old behavior if the live implementation reproduces it.
3. **RED:** a valid product runtime example in each affected existing detector family remains discoverable.
4. **RED:** a deterministic large synthetic corpus proves low-trust files do not enter the expensive runtime workflow-linking candidate set. Do not use fragile wall-clock assertions as the sole performance test.
5. **RED:** phase output or phase-level telemetry distinguishes artifacts, runtime, and config impacts.

Each test must be run and observed failing before its matching production change is written.

## Required verification

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/apple/tss/codegen/codewiki/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_runtime_scan.py tests/test_scan_telemetry.py
PYTHONDONTWRITEBYTECODE=1 /Users/apple/tss/codegen/codewiki/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_framework_support.py
PYTHONDONTWRITEBYTECODE=1 /Users/apple/tss/codegen/codewiki/.venv/bin/python -m pytest -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 /Users/apple/tss/codegen/codewiki/.venv/bin/python -m compileall -q deepdoc
```

## Completion requirements

- One scoped local commit on an isolated branch.
- No changes to user-modified files from main (`AGENTS.md`, `CHANGELOG.md`, `README.md`, `deepdoc/cli.py`, `deepdoc/llm/client.py`) unless independently required and explicitly justified.
- No `.hermes/` files committed.
- Claude final report includes confirmation evidence, RED/GREEN commands/results, files changed, commit SHA, and any unresolved limitation.
- Hermes then independently verifies the actual diff and test claims before DD-001/DD-002 move to `verification` or `closed`.
