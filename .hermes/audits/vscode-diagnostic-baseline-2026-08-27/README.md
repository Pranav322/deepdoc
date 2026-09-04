# VS Code Diagnostic Baseline Audit — 2026-08-27

## Status

**Not a canonical content benchmark.** The run was terminated with `KeyboardInterrupt` after planner degradation from Azure/Kimi rate limits and source-role false positives.

No production code was changed by this audit.

## Source snapshot

| Field | Value |
|---|---|
| Target checkout | `/Users/apple/personal/delete/vscode` |
| Origin | `https://github.com/microsoft/vscode.git` |
| VS Code commit | `222818cc1d871f299b909604ea267e955182d2a4` |
| DeepDoc commit | `8d45e5a82487d37a2a4adbf622ffbff1a0cc4b22` |
| Command | `.venv/bin/deepdoc generate --clean --yes` |
| Run ID | `6d5ee83ef9ea4c26bc01351ddd6b76be` |
| Started | `2026-08-27T05:23:02.873617+00:00` |
| Finished | `2026-08-27T08:10:48.363041+00:00` |
| Recorded status | `failed` — `KeyboardInterrupt` |
| Recorded total seconds | `10065.478642` |

## Immutable raw evidence

- `raw/performance-runs.jsonl` — exact DeepDoc persisted telemetry copy.
- `raw/.deepdoc.yaml` — exact run configuration copy; SHA-256 at capture: `a1eaf234d0b58ca0a19aeec6c758a37e94a5ab096a89766c9e05861d1606692c`.
- `raw/run.lock` — empty after process exit.
- `visible-terminal-excerpt.md` — source-marked transcript excerpt captured from the user-provided terminal output.

The original live terminal PTY was no longer accessible after the process exited, so a complete raw stdout transcript could not be recovered. This audit does **not** fabricate missing terminal output; the exact machine-readable telemetry and configuration were preserved instead.

## Persisted telemetry highlights

| Metric | Value |
|---|---:|
| Files discovered | 17,043 |
| Source files read / parsed | 12,843 / 12,843 |
| Source bytes read | 148,276,780 |
| LLM calls | 225 |
| LLM failures | 4 (`RateLimitError`) |
| Model | `azure/Kimi-K2.6` |
| Rate-limit wait seconds | 16,026.434254672004 |
| First failed prompt sizes | 106,443; 110,106; 101,532; 106,906 tokens |
| Planner assign total / ambiguous | 1,465 / 1,396 |
| Classify file summaries omitted | 902 |

## Confirmed diagnostic findings

1. **Rate-limit degradation:** Four Azure/Kimi calls failed with `RateLimitError`. The planner logged `Classification failed — falling back to auto-plan`, so this run mixed normal LLM plans with deterministic fallback plans.
2. **Source-role contamination:** The VS Code profile claimed `uses_express`, `uses_fastapi`, and `uses_vue`; actual FastAPI/Express signals are present in Copilot fixtures, embedded prompt/code-example strings, and simulation data rather than representing VS Code product architecture.
3. **False database architecture:** The run reported `39 model file(s), 130 model(s), ORM: sqlalchemy`. The current detector searches raw content with language-agnostic patterns including `class ... Base`, `Column(`, and `relationship(`; it can match embedded examples. The target checkout has no actual exact `sqlalchemy` import match in source search.
4. **No topology anchors:** `services: []` and no workspace/package graph caused the large repository to become recursively split `core/part-*` planning units instead of actual VS Code subsystems.
5. **Unbounded page setting:** `max_pages: 0` means unlimited per-unit planning, so this run could create an excessive number of pages.
6. **Unsupported languages remain a material coverage gap:** Rust, C++, C#, Java, Ruby, C, Clojure, Dart, Groovy, Objective-C/Objective-C++, R, and Swift were reported as present but unparsed.

## Interpretation

This is a valuable **failure/diagnostic baseline**, not a trustworthy DeepWiki-quality artifact baseline. Preserve it to validate that future universal SourceIndex, source-role classification, workspace topology, retry/degraded-run handling, and multi-language work remove these failure modes.

## Next action

Do not retroactively edit this audit. Future implementation must be delegated to Claude Code with `--model opus` (verified to resolve to `claude-opus-5`), followed by independent verification and review before any merge.
