# DeepDoc Coverage Audit — "Will this work on an arbitrary repo?"

Audited against the working tree on 2026-08-16. Every claim below carries a
`file:line` reference and was verified by reading the code, not the docs.

The question this answers: **can DeepDoc document VS Code, or a polyglot
monorepo, or an arbitrary GitHub repo — and if not, what specifically stops it?**

---

## Executive answer

DeepDoc today is a **high-quality tool for small-to-medium, single-service,
Python/JS/TS repositories.** It degrades in three distinct ways, and only one of
them is a true wall:

| Dimension | Verdict |
|---|---|
| **Language** | Hard cliff. 6 languages parse; only 2 get a call graph. Everything else is invisible. |
| **Framework** | Wide but very uneven. Detector depth ranges 68→440 lines. Two frameworks emit *wrong* routes. |
| **Monorepo** | Detected, then **thrown away**. The signal is computed, persisted, and never read. |
| **Scale** | **Hard architectural wall.** Planning requires the whole repo inventory in one prompt. |

The single most important finding: **the blocker for large repos is not language
support. It is that planning is single-prompt and whole-repo.** Fixing languages
without fixing planning will not make VS Code work.

The second most important finding: **most degradation is silent.** A repo can be
80% ignored and the run still reports success.

---

## 1. Language coverage — a hard cliff, with a clean seam

### What is supported

`parser/registry.py:16-27` maps exactly 10 extensions:

```
.py → python      .js .jsx .mjs .cjs → javascript
.ts .tsx → typescript                .go → go
.php → php                           .vue → vue
```

All parsers are **tree-sitter** based (`python_parser.py:15-20`,
`js_ts_parser.py:15-20`, `go_parser.py:17-19`, `php_parser.py:15-19`); `.vue`
extracts the `<script>` block and delegates to the JS/TS parser
(`vue_parser.py:1-13`). All five grammars are hard dependencies
(`pyproject.toml:27-32`). Each parser has a `_TS_AVAILABLE` guard with a regex
degradation path.

### The cliff: call graph is Python + JS/TS only

`call_graph.py:396-400` builds edges only for `python` and
`javascript`/`typescript` (plus a Vue special-case at `:577`). **Go and PHP have
parsers and route detectors but produce zero call-graph edges.**

This matters more than it looks. `planner/topology.py:96-97`:

```python
if not cg or not repo_files:
    return _empty_map()
```

…with the docstring stating callers "fall back gracefully (flat repos keep the
existing heuristic flow)."

So a **Go or Laravel repo silently drops out of topology-driven planning** — the
headline feature since 1.9.0 — back to the older heuristic planner. It does not
crash. It just organizes pages noticeably worse, and nobody is told.

### Support tiers

| Tier | Languages | What you get |
|---|---|---|
| **A — full** | Python, JS/TS, Vue | Parse + call graph + topology clustering + routes |
| **B — degraded** | Go, PHP | Parse + routes, but **no call graph** → heuristic planning only |
| **C — invisible** | Java, C#, Rust, Ruby, Kotlin, Swift, C/C++, Scala, Elixir | Not parsed |

### The good news: the seam is clean

Adding a language is genuinely cheap for the *parsing* layer: add a
`tree-sitter-X` dependency, write one parser module, add one line to the
`_REGISTRY` dict. tree-sitter ships maintained grammars for Java, Rust, Ruby,
C#, Kotlin, and C++ — all pip-installable.

The expensive part is **call-graph support**, which is where quality actually
comes from.

---

## 2. Framework coverage — wide, uneven, and sometimes wrong

`parser/routes/registry.py:16-36` is a clean language-keyed registry with
**multiple detectors per language**, so a Python repo runs Falcon + Django +
FastAPI detectors together. That design is right.

### Depth is very uneven

Detector size, in lines:

```
django   440  ██████████████████
go       349  ██████████████
falcon   214  █████████
fastapi  148  ██████
fastify  145  ██████
laravel  138  █████
express  121  █████
nestjs    68  ███
```

Cross-file resolution is where composed route paths get built
(`repo_resolver.py`, 1,545 lines). Mentions per framework:

```
go 83 · django 46 · fastify 31 · fastapi 12 · falcon 11 · express 7
nestjs 0 · laravel 0
```

### The sharp edge: NestJS and Laravel get *wrong* routes, not missing ones

NestJS and Laravel have **zero** presence in `repo_resolver.py`. NestJS paths are
composed from `@Controller('users')` + `@Get(':id')` across modules. A 68-line
per-file detector with no prefix composition will emit partial or incorrect
paths rather than declining to emit them.

**Wrong output is worse than no output** — it produces confidently incorrect API
documentation. This is the highest-severity correctness issue in the audit.

### On the Django-vs-FastAPI worry

The instinct was directionally right, though not for the reason assumed. FastAPI
is genuinely implemented (148 lines, real detector), not a stub. But Django has
~3× the detector code and ~4× the cross-file resolution logic. And
`tests/fixtures/frameworks/` contains apps for **django, go, falcon, fastify,
vue, express** — with **no fastapi, nestjs, or laravel fixture app**. FastAPI has
unit-level coverage in `test_framework_support.py` and `test_route_registry.py`,
but no end-to-end fixture repo the way Django has.

### Notable absences

- **Flask** — absent from the registry entirely. Arguably the most significant
  single gap in the Python ecosystem.
- Spring Boot, Rails, ASP.NET, Phoenix, Axum, Ktor — absent (follows from the
  language tier-C list).
- Go is the exception that proves the design works: `go_parser.py:7` covers
  Gin, Echo, Fiber, Chi, and net/http through the API detector.

---

## 3. Monorepo support — built, then discarded

This is the most surprising finding, and the cheapest to fix.

### Detection exists and is real

`config.py:66` ships a `services: []` key documented as "optional monorepo
service roots, e.g. `["services/auth", "apps/api"]`".

`planner/engine.py:900-950` implements `_detect_service_boundaries()`: it honors
configured roots, and otherwise auto-detects by scanning for marker files.

### But it is never used

`service_boundaries` and `file_services` are:
- computed in `engine.py:900-950`
- stored on `RepoScan` (`v2_models.py:166-167`)
- persisted (`persistence_v2.py:547-548,670`)
- **read by nothing** in planning, topology, nav shaping, bucket ownership,
  slug generation, or generation

An exhaustive search for consumers outside `engine.py` returns only the model
definition and the persistence layer. The monorepo signal is computed and
thrown away.

### Detection is also narrow

Auto-detection only looks under three hardcoded parent directories —
`services/`, `apps/`, `packages/` (`engine.py:931`) — at a maximum depth of 2,
using six markers: `pyproject.toml`, `package.json`, `go.mod`, `composer.json`,
`manage.py`, `Dockerfile`.

Not recognized: `Cargo.toml`, `pom.xml`, `build.gradle`, `*.csproj`, `Gemfile`,
`mix.exs`, `BUILD.bazel`, and — critically — **no workspace manifests at all**
(`pnpm-workspace.yaml`, `turbo.json`, `nx.json`, `lerna.json`, `go.work`, Cargo
workspace members). A monorepo laid out as `src/`, `libs/`, `modules/`, `cmd/`,
or flat gets **zero** detected services.

### A concrete predicted failure: slug collision

Bucket slugs come from the **LLM's proposal** (`heuristics.py:185`), not from
file paths. A uniquifier exists — `_unique_slug` (`heuristics.py:843`) — but is
called **only** for endpoint-family buckets (`:959`). Top-level LLM-proposed
slugs are never globally de-duplicated.

`plan_contract.py:28-53` then hard-raises on duplicate slugs or duplicate output
paths, aborting before any page is generated.

So: a monorepo where two services each contain an `auth` or `utils` module can
lead the planner to propose two buckets with the same slug → **hard abort**.
This is a latent bug for any repo; monorepos sharply raise the odds.

---

## 4. Scale — the real wall

### The architectural ceiling

`llm/token_budget.py:233-239`:

```python
if input_tokens > maximum_input:
    raise ModelCapabilityError(
        f"{step_name} required inventory exceeds the resolved model budget "
        f"({input_tokens:,} input tokens > {maximum_input:,} available). ..."
    )
```

There is no chunking, no hierarchical planning, no fallback. All three planner
steps route through this — classify (`engine.py:83`), propose (`:256`), assign
(`:334`).

And in ASSIGN, the file inventory is a **required** section
(`engine.py:339-341`), built as one line per unresolved file
(`engine.py:310`):

```python
all_files_str = "\n".join(f"- {f}" for f in unresolved_files)
```

Only `endpoints` is optional/trimmable.

**Estimated threshold** (assumptions stated): at ~15 tokens per path line, on a
128k-context model with `maximum_input` ≈ 105k after output reserve and safety
margin, and with `proposed_buckets` plus the template consuming part of the
budget — planning hard-fails somewhere in the **low thousands to ~7,000
unresolved files**. The P1.9 deterministic pre-assignment
(`heuristics.py:259`) reduces the count by resolving unambiguous files first,
which helps but does not change the order of magnitude.

VS Code (~10k+ TS files) is past this. The Linux kernel is far past it.

### A second-order scale bug

`token_budget.py:242-256` fits optional sections by re-rendering the **entire
prompt and re-counting all tokens once per candidate record**. For N optional
records that is O(N²) character processing. On a large repo, `fit_prompt_sections`
becomes slow *before* it fails.

### No size or binary guard on the main scan

Size and binary guards exist **only** in the chatbot path
(`source_archive.py:339`, `docs_summary.py:246`, `indexer.py:604`). The main
scan (`planner/engine.py`) has neither. Worse, large files are not skipped —
files over `giant_file_lines` (default 2000, `engine.py:43`) are escalated to
**extra LLM clustering work** via `cluster_giant_file`. A vendored or generated
5MB `.ts` file that escapes the exclude list costs money rather than being
ignored.

### Cost extrapolation

Measured baseline (`SPEED_AUDIT.md`): a **270-file** repo took **820.82s**, 61
LLM calls, and **2,212,671 prompt tokens**. Generation scales with page count
(O(pages) calls); planning is O(1) calls but O(n) tokens — until it hits the
ceiling above and fails outright.

---

## 5. Silent degradation — the trust problem

`orphaned_files` is tracked on `DocPlan`, persisted
(`persistence_v2.py:277,344`), and scored in `benchmark_v2.py:640-651`.

It is **never surfaced in the CLI** — searching `deepdoc/cli.py` for "orphan" or
"coverage" returns nothing.

Consequence: DeepDoc can document 20% of a repository and report success. A user
pointing it at a Java/Python hybrid gets docs for the Python half and no
indication the other half was invisible.

### What does gate a page

Only three conditions set `is_valid = False` (`validation.py:134,173,379`):
1. word count < 100
2. unresolved placeholder sections
3. hallucinated file paths above a per-bucket-type threshold

Roughly twenty other checks are warning-only. Hallucinated *paths* do gate,
which is better than the docs imply — but nothing catches a page that is
factually wrong while citing real paths.

---

## 6. Recommendations — ordered by leverage

### Tier 1 — cheap, high impact (days)

1. **Surface coverage in the CLI.** Print documented/skipped/orphaned file
   counts and a coverage %, plus an explicit warning listing unsupported
   languages encountered. Turns silent degradation into an informed decision.
   *Nothing new needs computing — the data already exists.*
2. **Consume the monorepo signal.** `file_services` is already computed. Feed it
   into nav sections, bucket ownership, and slug namespacing. This is the single
   best effort-to-value item in the audit.
3. **Fix the slug-collision abort.** Apply the existing `_unique_slug` globally
   before `validate_plan_contract`, or have the contract uniquify rather than
   abort. Removes a hard failure mode.
4. **Add size and binary guards to the main scan**, and skip (don't LLM-cluster)
   generated/minified files.

### Tier 2 — correctness (1–2 weeks)

5. **Fix NestJS and Laravel route composition.** Wrong API docs are worse than
   absent ones. Add both to `repo_resolver.py`, or make them decline to emit
   paths they cannot compose.
6. **Add Flask.** Largest single framework gap; the registry seam makes it a
   contained change.
7. **Broaden service detection.** Add workspace manifests (`pnpm-workspace.yaml`,
   `turbo.json`, `nx.json`, `go.work`, Cargo workspaces) and more markers
   (`Cargo.toml`, `pom.xml`, `build.gradle`, `*.csproj`, `Gemfile`). Stop
   restricting to `services/|apps/|packages/`.
8. **Fixture apps for FastAPI, NestJS, Laravel** to match the six that exist.

### Tier 3 — the real unlock: hierarchical planning (weeks)

9. **Break the single-prompt planning ceiling.** This is what makes VS Code and
   large monorepos possible. Plan per service/subtree, then merge:
   - partition the repo (by detected service boundary, else by top-level
     directory) into planning units that each fit the budget;
   - run classify/propose/assign **per unit**;
   - merge into one `DocPlan` with service-namespaced slugs;
   - keep `validate_plan_contract` as the final global gate.

   This reuses the existing planner unchanged and makes repo size bounded by
   *unit* size rather than total size. It also makes item 2 load-bearing rather
   than cosmetic — which is why 2 should come first.

10. **Fix the O(N²) fit loop** (`token_budget.py:242-256`) — incremental token
    accounting instead of full re-render per record.

### Tier 4 — language breadth (ongoing)

11. **Add languages by tier.** Parsing is cheap (one module + one registry
    entry + one dependency). Prioritize by target audience: Java, Ruby, Rust,
    C#. But note that without call-graph support they land in Tier B — parsed
    but heuristically planned.
12. **Extend the call graph beyond Python/JS-TS.** This is where documentation
    quality actually comes from, and is the difference between Tier B and
    Tier A. Higher effort than parsing; do it for the languages that matter
    most rather than all at once.
13. **Consider a generic fallback parser** — symbol extraction via tree-sitter
    for any grammar, no call graph. Converts Tier C (invisible) into a weak
    Tier B for a long tail of languages at low marginal cost.

---

## Appendix — how to read this

Precedence when docs disagree: **code > `AGENTS.md` > `CLAUDE.md`**. Verified
drift found during this audit: root `CLAUDE.md` describes an MkDocs site builder,
but the canonical builder is `build_next_from_plan`
(`site/builder/next_builder.py`), called from `pipeline_v2.py:1664`.
`pyproject.toml:47` independently confirms: "The generated site is now Next.js +
Fumadocs."

---

# Addendum — Gap Audit

The first pass covered the areas that drove the headline findings. This addendum
closes the remaining scope, and changes one strategic conclusion materially.

## A. The single most important finding: generation needs only source

`generator/generation.py:253-262` puts every evidence section into
`required_sections`, but each one except source is passed with an `or ""`
fallback:

```python
required_sections={
    "source_context":   full_source,
    "flow_context":     evidence.flow_context or "",
    "endpoints_detail": evidence.endpoints_detail or "",
    "openapi_context":  openapi_context or "",
    "sitemap_context":  sitemap_context or "",
    "dependency_links": dependency_links or "",
    ...
}
```

**Only `full_source` carries mandatory content.** Missing flows, endpoints, and
OpenAPI degrade to empty strings; the page still generates.

**Therefore the deterministic layer is an accelerator for page *generation*, not
a prerequisite.** Determinism is only load-bearing at the *planning* layer —
deciding which files group into which page.

This substantially cheapens broad language support. See §F.

## B. What actually happens to a `.java` / `.rs` file

`planner/engine.py:722-725`:

```python
if fpath.suffix.lower() not in extensions:
    file_tree[rel_dir].append(fname)
    progress.advance(task)
    continue
```

The file is added to the directory tree — so its **name** reaches the planner —
but it is never read, never parsed, never enters `file_contents`, and never
reaches `source_work`. Its **contents are never sent to the LLM**.

So DeepDoc cannot document Java/Rust/Ruby/C# code today. It can only note that
such files exist. Combined with §A, the fix is far smaller than writing parsers.

Note: `extensions = supported_extensions()` (`engine.py:553`) comes from the
**parser registry**, not from config.

## C. The `languages:` config key is cosmetic

`config.py:64` ships `languages: [python, javascript, typescript, go, php, vue]`.
Its only functional use is `generator/generation.py:220-224`, where it fills a
prompt template variable:

```python
languages=", ".join(k for k in (self.cfg.get("languages") or ["python", "javascript"])),
```

It does **not** gate scanning. Adding `"java"` to `.deepdoc.yaml` today changes
one sentence in the prompt and nothing else. This is a misleading config surface
and should either be wired up or documented as descriptive-only.

## D. Non-HTTP entry points barely exist

`planner/flow_candidates.py` defines exactly three `entry_kind` values:
`endpoint_family` (:134), `runtime_task` (:230), `runtime_scheduler` (:296).

There is **no CLI-command, library-public-API, or plugin/extension-activation
entry kind.** A filename heuristic (`scan.entry_points`) still seeds topology
(`topology.py:159`) and start-here injection (`bucket_injection.py:97`), but
flow *tracing* only fires for HTTP endpoints, background tasks, and schedulers.

Consequence: **VS Code, CLI tools, compilers, and libraries get structural pages
but no behavioral flow modeling and no sequence diagrams.** That is a large
share of GitHub.

Minor related bug: the entry-point fallback at `engine.py:738` uses
`fname.lower().rstrip(".py.ts.js.go.php")`. `rstrip` takes a *character set*, so
`app.go` and `app.php` both reduce to `"a"` and never match. `app.py`/`app.ts`/
`app.js` are saved only because `ENTRY_POINT_NAMES` (`planner/common.py:59-77`)
lists them explicitly. Net effect: `app.go` and `app.php` are silently missed.

## E. Multi-framework: better than expected

`v2_models.py:140,160` carries `frameworks_detected: list[str]` and
`file_frameworks: dict[str, list[str]]`. There is **no singular repo-level
framework field**, so a Django + Express + Go monorepo is structurally sound at
the scan layer. This refutes a concern raised in the main audit.

Corroborating the NestJS finding: `source_metadata.py:31-40` sets
`FRAMEWORK_PRIORITIES` with `nestjs: 10` against `falcon: 100`, `django: 90`,
`fastapi: 85`. The maintainers already encode NestJS as low-confidence.

## F. Extensibility is asymmetric

Measured, outside `parser/` (in `scanner/`, `planner/`, `generator/`):

| Knowledge | Leakage |
|---|---|
| File-extension literals | **3 occurrences** (`topology.py` ×2, `engine.py` ×1) — clean |
| Django-specific logic | **9 files** — `validation.py`, `specializations.py`, `scanner/common.py`, `evidence.py`, `runtime.py`, `planner/common.py`, `database.py`, `bucket_injection.py`, `heuristics.py` |

So: **adding a language is architecturally clean; adding a framework is not.**
Shipping Flask means auditing those nine files for Django-shaped assumptions,
not just writing a detector.

## G. Caps and cost ceiling

- `max_pages: 0` (`config.py:16`) — **no page cap by default**.
- `max_files_per_bucket` default **25** (`bucket_refinement.py:520`), enforced by
  LLM-driven decomposition with a second pass (`:638-649`).
- `deepdoc/planner/budget_fit.py` **does not exist**, despite `CLAUDE.md` listing
  it as the deterministic end-of-planning gate. (Third confirmed `CLAUDE.md`
  staleness, after the MkDocs builder and the P2.9 status.)

Extrapolating the measured baseline (270 files → 38 planned pages, 61 LLM calls,
2.21M prompt tokens, 820s), and assuming pages scale with files at
`max_files_per_bucket = 25`:

| Repo size | Est. buckets | Est. LLM calls | Est. prompt tokens |
|---|---|---|---|
| 270 (measured) | 38 | 61 | 2.2M |
| 1,000 | ~140 | ~230 | ~8M |
| 10,000 | ~1,400 | ~2,300 | ~80M |

These are order-of-magnitude only. In practice the run never reaches the 10k row
— planning hard-fails first (main audit §4). The point stands that **cost is
linear and unbounded**: nothing caps total spend.

## H. Resume exists

`generator/generation.py:500-503` checkpoints the manifest every
`manifest_checkpoint_pages` (default 10) or `manifest_checkpoint_seconds`
(default 15.0), and `_checkpoint_manifest` (`:1600-1601`) is documented as
existing "so a cancelled run can resume". Page-level resume is therefore real —
a long run that dies does not restart from zero.

Not verified: whether resume is robust across a *plan* change, or only across
identical re-runs.

## I. Not verified

- No explicit zero-supported-source-file guard was found. An empty or
  unsupported-only repo most likely reaches planning with an empty inventory and
  trips `validate_plan_contract` (no introduction bucket) — but I did not confirm
  the actual failure mode by execution.
- Monorepo nav grouping behavior was not traced end-to-end.
- Per-parser feature parity (does `go_parser` extract as much as
  `python_parser`?) was not compared symbol-by-symbol.

---

## Revised recommendation

§A + §B together change the priority order. The cheapest large win is no longer
"write more parsers":

**Add a generic fallback source reader.** Read files of unknown extension (with
size/binary guards), skip parsing entirely, group them by directory, and pass
them as `source_context`. Because generation only requires source (§A), this
produces genuinely useful documentation for Java, Rust, Ruby, C#, Kotlin, and
Swift **without writing a single new parser**.

It lands those languages in a new tier — call it **Tier B-minus**: no call
graph, no routes, directory-based grouping, but real prose documentation of real
code. That is a dramatically better default than today's behavior, where those
files are invisible.

Proper tree-sitter parsers and call-graph support then become a *quality*
upgrade per language, prioritized by audience, rather than the entry ticket.

---

# Addendum 2 — Is there a limit on *how many* languages / frameworks?

Short answer: **no numeric cap, but three real limits — and the third is a bug.**

## Hard caps: none

Nothing truncates or limits `scan.languages` or `frameworks_detected`. Both are
joined unbounded into planner prompts (`engine.py:51-53`) and evidence
(`evidence.py:1882-1888`). The practical ceiling is what the registries support:
**6 languages** (`parser/registry.py`) and **8 frameworks**
(`parser/routes/registry.py`).

## Limit 1 — detection cost is O(files × detectors-for-that-language)

`detector.py:14-30` runs **every** registered detector for a file's language and
concatenates the results:

```python
for detector in get_detectors(language):
    detected = detector.detect(context)
    ...
endpoints.extend(detected)
return dedupe_endpoints(endpoints)
```

Current detectors per language: Python **3** (falcon, django, fastapi),
JS/TS **3** (express, fastify, nestjs), Vue **2**, Go **1**, PHP **1**.

So every Python file is regex-scanned three times. This is bounded and cheap
today, but it scales linearly with frameworks *per language* — adding Flask,
Sanic, and Tornado would mean six passes over every Python file.

## Limit 2 — there is no conflict resolution between detectors

Dedupe is exact-match on `method:path:line` (`common.py:15`). Two detectors that
claim the same route but resolve the path differently (one applying a router
prefix, one not) produce **two surviving, conflicting endpoints**.

`FRAMEWORK_PRIORITIES` does **not** help here. Its only use is
`select_primary_framework()` (`source_metadata.py:213-221`), which labels a
*file's* primary framework. It never arbitrates competing endpoint claims.

## Limit 3 — detector gates are uneven, and FastAPI's is effectively open

Detectors self-gate on content substrings, but the quality varies sharply.

Falcon is tight (`falcon.py:25`):
```python
if "falcon" not in content.lower() and "add_route" not in content:
    return []
```

FastAPI is effectively open (`fastapi.py:30`):
```python
if "fastapi" not in content.lower() and "APIRouter" not in content \
   and "@" not in content and "add_api_route" not in content:
    return []
```

It bails only when **all four** are absent — and one clause is `"@" not in
content`. Any Python file containing any decorator passes the gate and gets
fully scanned. `FASTAPI_DECORATOR_ROUTE` then matches
`@(\w+)\.(get|post|put|patch|delete|head|options|api_route|websocket)\(` — and
`patch` is in that verb list.

**Reproduced** against the real detector:

```
input:  @mock.patch("myapp.services.billing.charge")
        @mock.patch("myapp.db.session.get")

output: PATCH 'myapp.services.billing.charge'  framework=fastapi line=4
        PATCH 'myapp.db.session.get'           framework=fastapi line=8
```

Every Python repo using `unittest.mock` generates phantom FastAPI endpoints
whose "paths" are Python import strings.

### Why it partly doesn't matter, and why it still does

`endpoint_publication_decision` (`source_metadata.py:177-211`) correctly rejects
these on two independent grounds — low-trust source kind (`non_product_source`)
and a path not starting with `/` (`invalid_path`). So they do **not** reach
published API documentation.

But the flag is advisory. `engine.py:825` appends the endpoint to
`api_endpoints` **regardless**, storing `publication_ready` as metadata. The
filtered accessor `published_api_endpoints` (`v2_models.py:170-172`) is used at
only **three** sites (`evidence.py:1947`, `benchmark_v2.py:506`, and itself),
while raw `api_endpoints` is read by planning (`engine.py:1095,1105,1140,1182`),
endpoint bucket building (`heuristics.py:275`), evidence assembly
(`evidence.py:179,1263,1320`), the chatbot chunker (`chunker.py:480`), and
`pipeline_v2.py:673,812,1655`.

The consequential path is `heuristics.py:273-277`, which builds `endpoint_files`
from raw endpoints and folds it into `excluded_files`:

```
@mock.patch  →  phantom endpoint  →  endpoint_files  →  excluded_files
             →  test file pushed into the LLM's unresolved inventory
             →  wasted planning tokens + worse ownership assignment
```

That inventory is exactly what hits the context-window ceiling (main audit §4),
so this bug **directly worsens the scale limit**.

## Recommendations

1. **Tighten the FastAPI gate** — drop the `"@" not in content` clause; require
   `fastapi`, `APIRouter`, or `add_api_route`. One-line fix, removes the whole
   false-positive class.
2. **Make `publication_ready` authoritative** — have planning, bucket building,
   evidence, and the chatbot chunker consume `published_api_endpoints` rather
   than raw `api_endpoints`. Keep raw only for diagnostics.
3. **Add framework-priority arbitration** to `dedupe_endpoints` — when two
   detectors claim the same `(method, line)` with different paths, keep the
   higher-priority framework's claim instead of emitting both.
4. **Standardize detector gates.** Give `RegisteredRouteDetector` a required
   `gate` predicate so every new framework declares an explicit, reviewable
   trigger rather than hand-rolling a substring check. This is the change that
   makes "many frameworks" safe to scale.

---

# Addendum 3 — Anchor case: shopware/shopware (real run)

A production hosted run against `shopware/shopware` is the clearest real-world
confirmation of this audit. Pulled from the live job on 2026-08-17.

- **job_id:** `162a3e68cbe0`  ·  **owner:** `laluka-osk`  ·  **visibility:** private
- **status: `failed`**
- **Coverage: 416 / 8,603 source files documented — 5%.**
- **Failure:** `deepdoc deploy` refused the build —
  `generation has 1 failed page(s)` and `stub docs present: core`.

The runner log's own coverage panel:

```
Source files: 416/8603 documented (5%)
  Uncovered:
    src/Administration/Resources/app/administration/eslint-rules/core-rules/*.js
    src/Administration/.../deprecation-rules/*.js
    ... (thousands more)
```

## What it confirms, point by point

1. **Scale wall (main audit §4).** 8,603 files is far past the single-prompt
   planning ceiling. The run did not produce a coherent plan over the whole
   repo; it documented a 5% slice and failed the quality gate on the rest. This
   is exactly the "VS Code-scale monorepo" failure the audit predicted, on a
   real repository.

2. **Silent-degradation is real, and extreme (§5).** 95% of the repo was
   uncovered. Nothing in the pipeline treated 5% coverage as a problem — only
   `deepdoc deploy`'s independent quality gate (1 failed page + a `core` stub)
   stopped a 5%-complete site from shipping as if finished. Without that gate
   this ships looking done. Coverage is still never surfaced as a first-class
   signal.

3. **Monorepo signal wasted (§3).** shopware is a large multi-surface repo
   (`src/Core`, `src/Administration`, `src/Storefront`, …) — precisely the case
   `file_services` was built for and precisely where it is ignored. Per-service
   planning is what would let each surface fit the planning budget.

4. **Polyglot dilution (§1).** The uncovered list is dominated by
   `src/Administration/.../*.js` (JS tooling/ESLint rules) alongside the PHP
   core. Mixed PHP + JS with no cross-language call graph fragments topology and
   pushes most files toward the heuristic/orphan path.

## Bug found and fixed while investigating this

The hosted app served a **failed** job the `stalePageHtml` screen — copy that
reads *"was generated successfully, but the underlying files are gone"* and
offers a plain Regenerate. For `shopware/shopware` that was actively false: the
job failed, it never generated successfully.

Root cause: `cloud/[owner]/[repo]/[...path].ts` collapsed `done`-with-missing-
files and `failed` into one terminal branch. Fixed by adding
`failedPageHtml(owner, repo, error, theme)` (`lib/hosted/page_html.ts`) and
routing `result.status === "failed"` to it, so a failed job now shows an honest
failure page with the runner's error instead of a false success. `stalePageHtml`
is now reserved for its true case (status `done`, files evicted).

## Takeaway

shopware/shopware is the anchor argument for the roadmap's Tier 3 item
(hierarchical, per-service planning). It is not slow — it is structurally
unbuildable as a single planning unit today, and it fails in exactly the way the
static audit predicted.
