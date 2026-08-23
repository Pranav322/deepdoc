# DeepDoc Coverage-Fix Brief — Phase 1 bug/correctness fixes ONLY

> **Read this fully, then VERIFY every seam by opening the actual files.** The code is the
> source of truth — line numbers below were captured from the current working tree and may
> drift, so `grep`/read the real file before editing. For execution flows, invariants, and
> cross-file relationships use **`CONCEPTS.md`** (the exhaustive semantic map). Follow the
> repo-root **`AGENTS.md`** rules — in particular, if you change CLI output behavior or
> routing semantics you must update `AGENTS.md` and `README.md` in the same task.

---

## Context — what this brief fixes, and what it deliberately does NOT

This brief executes the *bug/correctness* findings of `COVERAGE_AUDIT.md` against the
**current** tree. The audit is dated 2026-08-16 and has already been partially executed —
`git log` will show work landed after it. **Do NOT re-fix what is already done:**

### ✅ Already fixed — verify, do not touch
- **FastAPI "open" detector gate.** The `"@" not in content` clause is **gone** from
  `parser/routes/fastapi.py:30-35`; the gate now requires `fastapi`/`APIRouter`/`add_api_route`.
  Confirm it is absent; do not re-add.
- **Entry-point `rstrip` character-set bug.** `planner/engine.py:738-741` now uses
  `Path(fname).stem` plus an explicit name set, not `fname.rstrip(".py.ts.js.go.php")`. Confirm.
- **Go and PHP call-graph edges.** `call_graph.py:455-458` dispatches to real
  `_extract_go_calls` (`:1301`) and `_extract_php_calls` (`:1338`). Confirm present.

### 🚫 Out of scope (explicitly ejected — do NOT build)
- Hierarchical / per-service planning (the scale wall). Not this task.
- Consuming the monorepo `file_services` signal, or broadening service detection. Not this task.
- New language parsers, call-graph extension to other languages, or a generic fallback
  source-reader. Not this task.
- Flask or other new frameworks; new fixture apps. Not this task.
- Cost / affordability model; the MCP server. Not this task.

Work on a **feature branch** (this repo is a git worktree; check current branch and the
`main` `AGENTS.md` may be several commits ahead of your checkout — branch from the current
checkout, do not force a rebase).

---

## Summary of the 8 tasks

1. Surface coverage in the CLI.
2. Globally de-duplicate top-level bucket slugs (remove the hard abort).
3. Size/binary/generated guards on the main scan.
4. Fix the O(N²) prompt-fit loop.
5. Framework-priority arbitration in `dedupe_endpoints`.
6. NestJS route-path composition; verify/fix Laravel.
7. Close residual FastAPI phantom endpoints + make `publication_ready` authoritative.
8. Guard for zero / unsupported-only source repos.

---

## Task 1 — Surface coverage in the CLI (highest value)

**Why:** silent degradation. DeepDoc can document 5% of a repo and report success. Add an
honest coverage summary so a partially-invisible repo is surfaced, not silently shipped.

**Seams (verify):**
- `cli.py` — the `generate` command handler and its completion output.
- `persistence_v2.py` — the plan persists `orphaned_files`; read how it's loaded.
- `v2_models.py` — `DocPlan.orphaned_files`, `RepoScan` source counters.
- Track how many files were actually read/parsed vs. skipped (extension/binary/size) during
  the scan so the report is real, not reconstructed.

**Do:**
- After `generate` (and `update`), print:
  - total source files scanned;
  - files documented (rolled into a bucket page) vs. orphaned/skipped;
  - a **coverage %**;
  - an explicit **warning listing any unsupported languages/extensions encountered**
    (e.g. `.java`, `.rs`, `.cs` present but not parsed) so a polyglot repo is visibly partial.
- Existing data already lands on `DocPlan`/`RepoScan` — prefer surfacing it over new large
  computations. No behavioral change to generation itself.
- Keep it on `stderr`/a dedicated section so it does not corrupt any machine-readable stdout.

**AGENTS.md compliance:** this changes CLI output → update `AGENTS.md` and `README.md`.

**Verify:** run `deepdoc generate` on a small mixed repo (e.g. a Python project with a stray
`.java` file) and confirm the coverage panel and the unsupported-language warning print
correctly, and that no existing test asserting CLI output breaks (update those tests).

---

## Task 2 — Globally de-duplicate top-level bucket slugs

**Why:** `validate_plan_contract` hard-aborts on duplicate slugs/output paths
(`COVERAGE_AUDIT.md` §3). Monorepos (two `auth` modules) sharply raise the odds. No
global uniquify exists today.

**Seams (verify):**
- `plan_contract.py:42-57` — `validate_plan_contract` raises `PlanContractError` on
  duplicate slug **or** duplicate output writer.
- `planner/heuristics.py:843` — `_unique_slug(base_slug, existing_slugs)` already exists but
  is called **only** for endpoint-family buckets (`:959`). Top-level LLM-proposed bucket
  slugs are never globally uniquified.

**Do:** uniquify the **entire** bucket slug namespace before `validate_plan_contract` runs
(preferred), i.e. apply `_unique_slug` (or an equivalent) to every LLM-proposed top-level
slug against a growing set of used slugs. Do **not** remove the unique-slug invariant from
`validate_plan_contract` — keep it as the final guard. If you choose instead to make the
contract uniquify rather than abort, keep the exception for genuinely unrecoverable states.

**Verify:** unit test proving two buckets proposing `auth` (e.g. simulated proposal) yield
`auth` and `auth-2` and pass the contract; `python3 -m pytest -q` green.

---

## Task 3 — Size/binary/generated guards on the main scan

**Why:** the main scan has no size or binary guard. A vendored/minified/generated 5MB file
that escapes `exclude` gets escalated to **extra LLM clustering** (`cluster_giant_file`)
instead of being ignored — costs money and can pollute planning.

**Seams (verify):**
- `planner/engine.py:42-43` — `giant_file_threshold` (default 2000 lines), `max_pages`.
- `planner/engine.py:467` `_scan_one_source_file` — the read/parse entry; add guards here.
- `planner/engine.py:968` — `cluster_giant_file` import; the escalation path to avoid.
- Existing `_DEEPDOC_GENERATED` excludes (`engine.py:562-570`) already handle `.deepdoc`,
  `site`, docs output — extend the *principle*, don't rely only on user `exclude`.

**Do:**
- Add per-file **binary detection** (e.g. NUL bytes in the first chunk) → treat as
  non-documentable, skip reading/parsing, count in the skip report (Task 1).
- Add a **size cap** (new config `scan.max_source_bytes`, default e.g. 1MB, verify a sane
  default) → skip oversized files instead of LLM-clustering them. Skips count in Task 1.
- Detect **generated/minified/vendored** signals (`*.min.*`, `dist/`, `build/`,
  `node_modules/`, lockfiles already likely excluded) → skip, do not cluster.
- Ensure skipped files do **not** enter the unresolved inventory fed to the ASSIGN prompt
  (that inventory is what hits the context ceiling).

**Verify:** test with a synthetic repo containing a binary blob and a 3MB `.ts`; confirm
both are skipped, not clustered, and appear in the coverage report.

---

## Task 4 — Fix the O(N²) prompt-fit loop

**Why:** `token_budget.py:242-258` re-renders and re-counts the **entire** prompt once per
candidate optional record → O(N²) for N records on large inventories.

**Seams (verify):**
- `llm/token_budget.py:242-258` — the per-record `candidate = dict(sections)`,
  `render_prompt(candidate)`, `count_message_tokens(...)` loop.

**Do:** make it incremental — count each record's token add-on **once**, accumulate, and
accept records while the running total stays under `maximum_input`, preserving the current
ordering (accept-first, then stop) and omission semantics (rejected records still land in
`omitted`). Do not re-render the whole prompt per record except where a single final pass is
unavoidable for exactness.

**Verify:** behavior-preserving on a fixed seed (same set of accepted/rejected records as
before) plus a timing sanity check on a large optional inventory.

---

## Task 5 — Framework-priority arbitration in `dedupe_endpoints`

**Why:** multiple detectors can claim the same route and, because
`dedupe_endpoints` is exact-match on `method:path:line`, two surviving **conflicting**
endpoints (same route, different resolved path) both reach downstream docs.

**Seams (verify):**
- `parser/routes/common.py:10-20` — exact-match `dedupe_endpoints`.
- `parser/routes/registry.py` — per-language detector lists + order.
- `source_metadata.py:31-40` — `FRAMEWORK_PRIORITIES` (django 90, fastapi 85, falcon 100,
  nestjs 10, …). Currently used only for per-file primary-framework labeling; extend it.

**Do:** when two detectors claim the same `(method, line)` (or same route) but produce
different paths, keep the higher-priority framework's claim instead of emitting both.
Implement arbitration **inside** `dedupe_endpoints` (or a callee it invokes) so every
caller benefits. Preserve exact dedupe for identical claims.

**Hygiene (optional, same task):** add a required `gate` predicate to
`RegisteredRouteDetector` (`parser/routes/base.py`) so every framework declares an explicit,
reviewable trigger instead of hand-rolling substring checks (see FastAPI's current inline
gate). This is a safe refactor only if it does not change detector output.

**Verify:** a unit test with two detectors emitting the same `(method,line)` but
`/users` vs `/api/users` where the lower-priority one is Flask-like → only the higher-priority
path survives. Existing suite green.

---

## Task 6 — NestJS route-path composition; verify/fix Laravel

**Why:** `COVERAGE_AUDIT.md` §2: NestJS / Laravel can emit **wrong** paths (worse than no
output). The NestJS seam now exists but is shallow.

**Seams (verify):**
- `parser/routes/repo_resolver.py:285-299` — `_resolve_nestjs_endpoint`: currently only
  resolves the handler **import** via `js_index`. It does **not** compose the
  `@Controller('users')` module prefix with the `@Get(':id')` handler suffix → paths still
  emitted as the per-file detector left them.
- `parser/routes/repo_resolver.py:96-97,110-111` — dispatcher branches for `nestjs` /
  `laravel`.
- `parser/routes/nestjs.py` and `parser/routes/laravel.py` — what each per-file detector
  emits (including whether it already carries controller/route metadata to compose).
- `parser/routes/common.py:124-129` — `join_route_path` for safe composition.

**Do:**
- **NestJS:** compose the module `@Controller('prefix')` (and any module-level imports /
  child modules) with the handler `@Get/@Post/:param` to produce `/prefix/:id`-style paths.
  Reuse `join_route_path`. Only emit a path when the segments are confidently resolvable.
- **Laravel:** read `_resolve_laravel_endpoints` and verify whether `Route::prefix`,
  route groups, and controller-route binding compose correctly. If it cannot compose a given
  path confidently, **decline to emit it** rather than emit a partial/incorrect one.
- **Rule for both:** if composition is uncertain, omit the endpoint from published routes
  instead of guessing — *wrong output is worse than no output*.

**Verify:** hand-built fixture modules for NestJS (controller + handler) and a small Laravel
routes file; assert the composed paths are correct and that unresolvable cases are omitted,
not fabricated. No fixture apps are required by this task — call the resolver functions
directly with synthetic content.

---

## Task 7 — Residual FastAPI phantom endpoints + authoritative `publication_ready`

**Why:** the open gate is fixed, but `FASTAPI_DECORATOR_ROUTE` matches
`@(\w+)\.(get|post|put|patch|...)` — so a file that legitimately imports FastAPI **and** uses
`@mock.patch(...)` still emits a phantom `PATCH <import-string>`. Separately, phantom/weak
endpoints leak into planning because the consequential paths read raw `api_endpoints`
instead of the filtered `published_api_endpoints`.

**Seams (verify):**
- `parser/routes/fastapi.py:17-26` — the regexes.
- `source_metadata.py:177-211` — `endpoint_publication_decision` already rejects
  non-`/` paths and low-trust sources; it is advisory today.
- `v2_models.py:170-172` — `published_api_endpoints` filtered accessor, currently used at
  only ~3 sites.
- Consumers that read **raw** `api_endpoints`: `planner/engine.py` (multiple),
  `planner/heuristics.py:275` (`endpoint_files` → `excluded_files`), `generator/evidence.py`,
  `chatbot/chunker.py`, `pipeline_v2.py`.

**Do:**
- Tighten FastAPI: only treat a decorator as a route when the receiver is a known router/app
  object (e.g. declared `app`/`router`/`APIRouter`), or validate the emitted path begins with
  `/` (import strings don't). The existing `publication_ready` checks already reject
  non-`/` paths — make them authoritative for the phantom class.
- **Authoritative filter:** switch the consequential consumers above from raw
  `api_endpoints` to `published_api_endpoints` so rejected/phantom endpoints cannot inflate
  planning inventory, `endpoint_files`, evidence, or the chatbot chunker. Keep raw only for
  diagnostics/telemetry. Audit each call site and confirm you are not dropping legitimate
  endpoints (verify what `endpoint_publication_decision` considers publishable).

**Verify:** a file with `@mock.patch("myapp.services.billing.charge")` in a codebase that
also uses FastAPI produces **no** `PATCH myapp.services.billing.charge` endpoint in the
`endpoint_files`/planning inventory; a real `@app.post("/orders")` still survives end to end.

---

## Task 8 — Guard for zero / unsupported-only source repos

**Why:** pointing DeepDoc at an empty or unsupported-only repo most likely reaches planning
with an empty inventory and fails with an opaque `PlanContractError` (`COVERAGE_AUDIT.md`
Addendum I — flagged as not confirmed, so make it confirmed and clean).

**Seams (verify):**
- `planner/engine.py` — the scan → plan entry; where the file inventory is finalized.
- `plan_contract.py` — `validate_plan_contract` (the current unexplained failure path).

**Do:** add an explicit, runnable guard after scanning: if zero supported source files were
read (vs. only unsupported/binary/overflow files), raise a clear, actionable error naming the
supported languages (python/javascript/typescript/go/php/vue) and pointing to the
unsupported-extension report from Task 1. Distinguish "empty repo" from
"repo has files but none are supported" in the message.

**Verify:** `deepdoc generate` on an empty dir and on a dir containing only a `.java` file →
clear errors, no traceback, no `PlanContractError`; suite green.

---

## Task 9 — `languages:` config: wire it up OR document as descriptive-only

**Why:** `config.py:64` ships `languages: [...]` but it only fills a prompt string
(`generator/generation.py:220-226`). Adding `"java"` today changes one sentence and nothing
else — a misleading config surface.

**Seams (verify):** `config.py:64`, `generator/generation.py:220-226`.

**Do (recommended, minimal):** document it as **descriptive-only** — update the config
docstring and `README.md` so users know it does not broaden scanning, and remove any
expectation that it gates behavior. Do **not** silently rewiring it into a scan gate in this
task (that's breadth work). If you find it already consulted elsewhere, note that in your
report.

---

## Cross-cutting requirements

- **Branch:** new feature branch off the current checkout. Commit logically per task.
- **AGENTS.md / README.md:** update if you change CLI output (Task 1), routing semantics
  (Tasks 5-7), or config surface (Task 9) — per root `AGENTS.md`.
- **Tests:** add focused unit tests for each task (mock at the established seams — the
  chatbot/planner tests show the convention). Do not regress the suite.

## Verification (must do, don't skip)

1. `python3 -m pytest -q` — full suite green.
2. Manual smoke: `deepdoc generate` on a small Python/JS repo **and** on a synthetic mixed
   repo (a `.java` file present) → confirm the Task 1 coverage panel + unsupported-language
   warning print, no slug abort, and phantom `PATCH` endpoints absent.
3. Confirm you did **not** re-touch the three already-fixed items, and did **not** build any
   out-of-scope breadth (no hierarchical planner, no new parsers, no Flask, no MCP).
4. `claude auth status` → confirm `loggedIn: true` before running.

---

## Please report back
- Exact list of files created/changed per task.
- Any discrepancy between this brief and the real code (names, line refs, config keys) —
  flag it, don't silently "fix" it.
- Which of the "already fixed" items you confirmed, and confirmation the out-of-scope list
  was not touched.
- Test output summary and the coverage-panel smoke result.