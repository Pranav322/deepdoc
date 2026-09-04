# Claude Code Brief — DD-001/DD-002 Runtime Scan Stabilization

## Autonomous-run contract

You are implementing a scoped production fix in an isolated Git worktree. Read this entire brief, then **verify every referenced seam against the live worktree**. The brief is evidence-backed but not authoritative over the code.

You must complete the task autonomously. Do **not** stop for a checkpoint or ask whether to proceed. If a stated seam differs, record the discrepancy in your final report, choose the smallest evidence-backed correction, and continue.

Use strict TDD: write one failing regression test, run it and observe the expected failure, write the minimal implementation, rerun it green, then proceed to the next behavior. Do not write production code before the corresponding test is red.

## Goal

Fix the large-repository runtime-scan performance/correctness defect documented as DeepDoc issues DD-001 and DD-002:

- runtime discovery is hidden behind the misleading `Scanning for setup/deploy/test artifacts...` label;
- it consumes excessive CPU on VS Code-scale repositories;
- low-trust fixtures/examples and embedded code snippets create false product runtime/framework evidence;
- workflow linking is likely doing excessive file × task-name × regex work.

## Required starting investigation

Before editing production code:

1. Read:
   - `AGENTS.md`
   - `deepdoc/CONCEPTS.md`
   - `.hermes/ISSUE_LEDGER.md` (DD-001/DD-002)
   - `.hermes/audits/vscode-diagnostic-baseline-2026-08-27/runtime-scan-hotspot.md`
   - `deepdoc/planner/engine.py` around `run_phase2_scans()`
   - `deepdoc/scanner/runtime.py`
   - `deepdoc/source_metadata.py`
   - `tests/test_runtime_scan.py`
   - `tests/test_scan_telemetry.py`
2. Verify the previous VS Code telemetry in the audit rather than assuming it is current code behavior.
3. Establish a fast synthetic repro that proves the unwanted behavior. It must not require running the full VS Code repository.
4. State the root-cause confirmation in your final report. If evidence disproves any claimed cause, report that precisely.

## Scope

### In scope

- `deepdoc/scanner/runtime.py`
- call site/progress output in `deepdoc/planner/engine.py`
- reuse/integration of existing source-kind metadata
- focused regression tests
- minimal supporting helpers only if the actual code requires them

### Out of scope — do not build now

- Azure/Kimi retry/rate-limit behavior (DD-003)
- SourceIndex/RepositoryModel (DD-005)
- workspace/package topology (DD-006)
- new language packs (DD-007)
- broad framework overlays/hierarchy (DD-008/DD-009)
- citation UI (DD-011)
- redesigning unrelated parsers or the planner
- modifying `.hermes/` files
- touching pre-existing user changes in `AGENTS.md`, `CHANGELOG.md`, `README.md`, `deepdoc/cli.py`, or `deepdoc/llm/client.py` unless a direct behavior change makes it unavoidable; if unavoidable, explain it and keep it minimal.

## Relevant live-code clues — verify, do not trust blindly

- `run_phase2_scans()` currently prints one artifact message and then calls artifact discovery, `discover_runtime_surfaces()`, and config-impact discovery before printing their combined result.
- `RepoScan` already contains `source_kind_by_file`.
- `deepdoc/source_metadata.py` exposes `classify_source_kind()` and `is_low_trust_source_kind()`.
- `discover_runtime_surfaces()` currently receives parsed files, full file contents, and endpoints but apparently not source-kind data.
- `_link_runtime_workflows()` constructs task/scheduler patterns and loops over repository file contents.

## Behavior to preserve

Do not solve this by turning runtime detection off.

Valid product runtime evidence must still be detected for supported language ecosystems. Existing runtime tests must remain meaningful. The fix must distinguish product source from low-trust material and distinguish a file’s real language from code-looking strings embedded in another language’s prompt/test data.

## Required implementation properties

1. **Reuse source-kind metadata.** Do not introduce a parallel path classifier.
2. **Language/evidence gate framework detectors.** A TypeScript prompt containing Python code must not become a Python Celery/Django runtime surface. A fixture should not become product runtime architecture.
3. **Bound workflow linking.** Use a deterministic eligible-file/candidate index or equivalent evidence-based approach. Avoid scanning every task regex against every file when not needed.
4. **Maintain deterministic output ordering.**
5. **Expose progress.** Users must see distinct artifact, runtime-surface, and config-impact work rather than a misleading single label.
6. **Preserve public compatibility.** If you add arguments to direct scanner helpers, use compatible defaults unless you prove every caller migrates safely.

## TDD requirements

Add or extend tests that prove, at minimum:

1. Low-trust fixture/example runtime-like code does not create product runtime tasks/links.
2. Embedded foreign-language snippets in a product-language prompt/example do not trigger the foreign language’s runtime detector.
3. A real product runtime case remains detected.
4. A deterministic synthetic large corpus demonstrates that low-trust/noncandidate files do not participate in workflow-linking work. Prefer instrumentation/observable candidate counts over a fragile time assertion.
5. Phase status/timing output is distinct enough to identify runtime work.

For every new regression behavior:

```text
write test → run it red → minimal code → run it green
```

Record the actual RED failure and GREEN result in the final report.

## Mandatory commands

Use the repository virtual environment:

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/apple/tss/codegen/codewiki/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_runtime_scan.py tests/test_scan_telemetry.py
PYTHONDONTWRITEBYTECODE=1 /Users/apple/tss/codegen/codewiki/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_framework_support.py
PYTHONDONTWRITEBYTECODE=1 /Users/apple/tss/codegen/codewiki/.venv/bin/python -m pytest -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 /Users/apple/tss/codegen/codewiki/.venv/bin/python -m compileall -q deepdoc
```

Run focused RED/GREEN commands as well; do not merely run the final suite.

## Git safety

- Work only in the supplied isolated worktree.
- Never reset, clean, force-push, or modify main.
- Do not commit `.hermes/`.
- Make one scoped local commit after all verification passes, with a message such as:

```text
fix: bound runtime discovery for large repositories
```

## Final response format

Return all of the following:

1. Root-cause confirmation with exact code evidence.
2. Any discrepancy found versus this brief.
3. Tests added and the actual RED then GREEN command/results.
4. Implementation summary and files changed.
5. Full verification commands/results.
6. Commit SHA.
7. Remaining limitation or follow-up issue IDs, if any.
