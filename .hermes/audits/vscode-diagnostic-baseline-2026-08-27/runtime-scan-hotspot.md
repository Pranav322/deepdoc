# Runtime-Scan Hotspot — Source-Backed Finding

## Conclusion

The apparent stall at:

```text
Scanning for setup/deploy/test artifacts...
```

is not primarily artifact discovery. `deepdoc/planner/engine.py` prints that one status line and then runs all three operations without intermediate progress output:

1. `discover_artifacts()` — recorded prior VS Code duration: **4.956666624999343 seconds**.
2. `discover_runtime_surfaces()` — recorded prior VS Code duration: **856.018724208001 seconds / 14.27 minutes**.
3. `discover_config_impacts()` — recorded prior VS Code duration: **3.116961875002744 seconds**.

The status line is therefore misleading during the runtime scan.

## Live retry evidence

On 2026-08-27, the retry process was observed as:

```text
PID 1471
cwd: /Users/apple/personal/delete/vscode
command: .../deepdoc -v -s generate --clean --yes
state: R+ (actively running)
CPU: approximately 97–99.5% of one core
physical footprint sample: approximately 869.8 MB
```

This is a CPU-bound algorithmic hotspot, not an LLM wait, deadlock, or Kimi/Azure rate-limit event. Changing the LLM model does not change this phase.

## Likely algorithmic cause

`deepdoc/scanner/runtime.py:4-30` invokes multiple framework-specific runtime detectors over the full `file_contents` mapping. Then `_link_runtime_workflows()`:

- builds regex patterns for every discovered task/scheduler;
- checks every repository file against every discovered task-name candidate;
- for candidate files, loops over every runtime task and scheduler again and executes regex searches.

On the prior VS Code scan, the detector produced **79 runtime tasks**. The target contains **12,843 parsed source files / 148,276,780 source bytes**. Embedded Copilot fixtures and prompt/code examples create false runtime/framework signals, making this work both noisy and expensive.

## Required fix direction — do not implement until Claude brief is approved

1. Emit distinct progress/timing messages for artifacts, runtime, and config impacts.
2. Add source-role filtering: prompt corpora, fixtures, examples, tests, generated/vendor material must not create product runtime tasks by default.
3. Gate each runtime detector by language plus strong framework/manifest evidence; do not run Celery/Django/Laravel/Go/Node scans indiscriminately across all files.
4. Build candidate-file indexes once from discriminative markers; do not use a files × tasks × regex sweep for workflow linking.
5. Require a bounded work/candidate cap with a coverage/degradation diagnostic for very large repositories.
6. Add a VS Code-scale synthetic regression fixture and telemetry assertion that records runtime scan work/time without requiring a live model.

## Acceptance criterion

A VS Code benchmark must report separate artifact/runtime/config phase durations; runtime discovery must not invent application-runtime tasks from embedded examples, and its work must remain bounded independently of the number of generic task names detected.
