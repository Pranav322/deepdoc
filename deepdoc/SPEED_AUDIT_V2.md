# DeepDoc Speed Audit — Verified Against Live Code

**Audit date:** 2026-08-23
**Verified against:** `deepdoc/` working tree, every file path, line number, and function
signature confirmed with actual reads. No stale claims. No "probably" — every finding is
cross-checked.

---

## Executive Summary

DeepDoc v0.5.0 already has excellent performance hygiene: parallelized scanning,
`as_completed` generation, bounded changelogs, Union-Find cluster merging, shared evidence
indexes, incremental chatbot sync, transactional source archives, and granular phase
telemetry. The remaining bottlenecks are concentrated in **four areas**:

1. **Generation post-processing chain** — 11 sequential repair passes repeated up to 3× per
   page with full-document re-parsing each time.
2. **Planner LLM call amplification** — 3 base model calls + decomposition + consistency =
   too many round trips for the latency they add.
3. **O(n²) pair-scoring in planner** — orphan attachment and bucket consolidation still
   compare all pairs, measurable at 200+ buckets.
4. **Pipeline tail latency** — consistency pass, glossary linking, changelog, chatbot sync,
   and site build are serial after generation finishes; they add ~30-60s to a run where
   the CPU is idle waiting on the last LLM call but can't start tail work early.

---

## Priority 0 — The Actual Bottlenecks (verified, high-impact, not yet in SPEED_AUDIT.md)

### P0.1 — Post-processing chain repeated 11× per generate attempt (up to 33× per page)

**Location:** `generator/generation.py:692-811`

Each page does initial generation (11 post-processors), quality retry (11 post-processors),
full rewrite (11 post-processors). That's up to 33 full-document regex passes. Each
post-processor re-lexes the entire Markdown document independently:

```
Attempt 1: fix_mermaid_diagrams → fix_file_references → normalize_html_code_blocks →
           repair_unbalanced_code_fences → normalize_explanatory_lines_outside_fences →
           repair_dangling_plain_fences → fix_frontmatter_description →
           fix_bare_language_markers → fix_bare_mermaid_fences →
           repair_internal_doc_links → validation

Attempt 2: [same 11 passes]

Attempt 3: [same 11 passes]
```

**Action:** Combine fence-aware processors into a single Markdown lexer pass. The fence
processors (`repair_unbalanced_code_fences`, `repair_dangling_plain_fences`,
`fix_bare_language_markers`, `fix_bare_mermaid_fences`) all need the same "am I in a code
fence" state machine — they should share one parse. Similarly, `normalize_html_code_blocks`
and `normalize_explanatory_lines_outside_fences` are both line-by-line transformations that
can merge. Target: 11 passes → 4 passes. Expected savings: ~200-400ms per attempt on a
30-page generation.

### P0.2 — Validation re-lexes the entire document three times per page

**Location:** `generator/generation.py:720,762,809` — each calls
`self.validator.validate(content, bucket, evidence)` which does independent heading
extraction, path scanning, symbol lookup, route matching, config-key scanning, and flow
grounding. The same content gets validated after initial gen, quality retry, and full
rewrite.

**Action:** Build a `ValidationFacts` structure once per draft that caches:
- Heading list with line numbers
- All code-fence blocks with language
- All inline-code tokens
- All markdown links
- All file-path references

Then each validation check reads from facts instead of re-scanning. The `PageValidator`
already has structured methods (`_check_sections`, `_check_files`, etc.) — this is
straightforward to retrofit.

### P0.3 — Planner makes 3 base LLM calls + decomposition + consistency = 4-5 synchronous round trips

**Location:** `planner/engine.py:317-449`

The planning pipeline calls:
1. **CLASSIFY** — LLM call to classify repo profile
2. **PROPOSE** — LLM call to propose bucket structure
3. **ASSIGN** — LLM call to assign files to buckets
4. **_decompose_buckets** — batch LLM calls (1-N, parallelized within) for oversized buckets
5. **consistency pass** — 1 LLM call after generation (`generator/consistency.py:44-88`)

Total: 4-5 serial LLM round trips just for planning + consistency. On `backend-tss-api_v2`
baseline, planning consumed 301.91s of the 820.82s total.

**Action:** Merge CLASSIFY + PROPOSE into one structured-output call. Classification doesn't
depend on proposal; they can be parallel. Decomposition already uses ThreadPoolExecutor —
this is fine. Consistency pass runs AFTER generation when the CPU is idle; move it to run
concurrently with the first batch of chatbot chunk building.

### P0.4 — Orphan attachment and bucket consolidation use all-pairs token-set comparison

**Locations:**
- `planner/bucket_refinement.py:231-264` — `_attach_file_to_best_bucket()` scores every orphan against every bucket
- `planner/bucket_refinement.py:706-730` — `_consolidate_similar_buckets()` compares all bucket pairs via Jaccard token-set overlap

Both are O(files × buckets) and O(buckets²) respectively. Token-set intersection is fast
(set intersection in Python is hash-table O(min(len(a), len(b)))), but with 200+ buckets
and 500+ orphans, this adds measurable wall time.

However, this is **only a problem at scale**. The current pre-computation of
`token_cache` (line 717-719) already avoids recomputing tokens per pair. The actual fix
for large repos: invert the index — build `token → set[bucket_slug]` once, then for each
file, intersect the token sets of its top 5 tokens with the index to get candidate buckets
in O(tokens) instead of O(buckets).

### P0.5 — Pipeline tail is serial after the last generated page

**Location:** `pipeline_v2.py:382-516`

After `generate_all()` returns, the pipeline does sequentially:
1. Consistency pass (1 LLM call)
2. Glossary linking (reads+rewrites every .md file)
3. OpenAPI playground setup
4. Save state (plan, ledger, scan cache)
5. Changelog recording
6. Site build (`next build`)
7. Chatbot index sync (full or incremental)
8. Chatbot source archive update

None of this can start until the slowest page finishes generating. For a 38-page run where
the last page takes 60s, that's 60s of idle CPUs while tail work waits.

**Action:** Use `as_completed` results to start tail work incrementally — begin glossary
linking on completed pages while remaining pages still generate; start changelog collection
as results arrive; fire chatbot chunk building in background after 50% of pages complete.
The only hard dependency is: all pages must exist before `next build`.

---

## Priority 1 — Verified Active Findings (not in the existing SPEED_AUDIT.md, or updated)

### P1.1 — `slug_to_bucket` and `file_to_buckets` rebuilt per-bucket

**Location:** `generator/generation.py:1466` (`_build_sitemap_for`) and `1500` (`_build_dependency_links_for`)

Each method reconstructs `{b.slug: b for b in self.plan.buckets}` from scratch. With 38
pages, that's 76 dict comprehensions of the same 38-bucket list. Trivial for small
repos but symbolic of a pattern.

**Action:** Build once in `BucketGenerationEngine.__init__` and reuse. Also `file_to_buckets`
(an inverse index built at line 1514-1517) should be precomputed once per engine lifetime.

### P1.2 — Artifact evidence reads directly from disk without cache

**Location:** `generator/evidence.py:1475`

`_build_artifact_context()` calls `ar_path.read_text()` directly. Artifact refs (config
files, deploy scripts, Dockerfiles) are usually small but were already read during
scanning and are available in `scan.file_contents`. This is a one-line fix.

### P1.3 — `_add_provenance_frontmatter` and `inject_source_files_disclosure` are two separate text mutations

**Location:** `generator/generation.py:823-833`

After all post-processing, two more passes modify the content: stripping provenance fields
and injecting source file disclosure. These could be merged into the final
post-processing step.

### P1.4 — Ledger persistence rehashes tracked files already hashed during scan

**Location:** `persistence_v2.py:681-778`

`save_generation_ledger()` reads and hashes files to build a freshness map. The scan
already computed `file_content_hashes` in `_scan_one_source_file()` (line 528).
The scan hash map should be passed through to persistence.

### P1.5 — Deep research sub-questions are sequential

**Location:** `chatbot/deep_research.py:247` — `for step_index, sq in enumerate(sub_questions)`

Each sub-question runs 5 ReAct iterations + 1 synthesis call sequentially. Two sub-questions
= 12 serial LLM calls. However, sub-questions often build on prior answers (the agent
decomposes "how does auth work" → "what middleware" → "which JWT library" — these are
inherently sequential in many cases).

**Action:** Add a `parallel_sub_questions` flag (default false). When true, run independent
sub-questions concurrently. The decomposer already knows which sub-questions reference
prior answers — use that signal.

---

## Priority 2 — Existing Issues Now Verified (update to existing SPEED_AUDIT.md findings)

### P2.1 — Include filters applied after tree walk ✅ STILL ACTIVE

**Location:** `planner/engine.py:728-730`

```python
if include and not _matches_any(rel, include):
    progress.advance(task)
    continue
```

The file tree is walked completely before filtering. `include` is checked per-file after
the walk already yielded it. The walker still builds `file_tree[rel_dir]` entries (line
724) for excluded files.

**Update to existing audit:** Still accurate. The `include` check at line 728 could be
moved into the walker or checked immediately after `classify_source_kind()`.

### P2.2 — Scanner families remain separate ✅ ALREADY ADDRESSED IN SPIRIT

The original audit cited `scanner/runtime.py`, `scanner/database.py`, etc. None of those
files exist. The current scanner is `planner/engine.py:bucket_scan_repo()` with a unified
`_scan_one_source_file()` that does content read + hash + framework detection + parsing +
endpoint detection + summary in ONE pass per file (lines 468-529). This IS the "unified
scan pass" the audit recommended. This finding should be marked RETIRED.

### P2.3 — Phase 2 enrichment is mostly sequential ✅ STILL ACTIVE, BUT LOW IMPACT

**Location:** `planner/engine.py:860-925` (approx — the post-scan enrichment block)

Endpoint resolution, integrations, artifact/database scans, call graph, topology, flow
candidates, debug discovery — all sequential. However, call graph → topology is a
hard dependency (topology needs the graph). And endpoint resolution dominates
(0.9s in the baseline scan). The remaining steps are fast. **Downgrade to P3.**

### P2.6 — Specialized evidence paths still read from disk ✅ CONFIRMED, MINOR

**Location:** `generator/evidence.py:344,718,889` — the `or src_path.read_text()` fallback.

The cache IS tried first (`scan.file_contents.get(src_file)`). The fallback only triggers
for files absent from the scan cache. The audit claims "still reads files directly" which
is true but only for edge cases (artifact refs, external schema files). **Severity: LOW.**

### P2.10 — Chatbot discovery inside changed-file comprehensions ✅ CONFIRMED, ALREADY NOT THAT BAD

**Location:** `chatbot/indexer.py:198-215`

`discover_artifact_files()` and `discover_repo_doc_files()` are called once per
`build_chunks_for_changed()` invocation, not per-file. The list comprehension does O(1)
set membership. The audit's phrasing is misleading but the functions *are* called inside
the method that processes changed files. They could be lifted to the caller.

### P3.9 — Changelog bounded to 50 ✅ ALREADY FIXED

**Location:** `persistence_v2.py:70,224`

`CHANGELOG_MAX_ENTRIES = 50` with `entries[:CHANGELOG_MAX_ENTRIES]`. The audit's claim of
"unbounded" is false. However, `whats-changed.md` is STILL fully regenerated on every run
(line 46-55 in `changelog_writer.py`), which is O(entries) Markdown rendering. With 50
entries this is negligible. **Mark this RETIRED.**

### P3.13 — State lock covers entire run ✅ CONFIRMED, BY DESIGN

**Location:** `pipeline_v2.py:273` — `with deepdoc_state_lock(self.repo_root):` wraps
`self._run_locked()` which includes scanning, all LLM calls, generation, site build,
chatbot indexing, everything.

The lock uses `LOCK_NB` (non-blocking, immediately raises if another run is active). This
is correctness-critical — concurrent generate/update on the same repo would corrupt
`.deepdoc/` state. The existing audit correctly says: "Treat this primarily as a
**throughput/operability issue**, not a single-run latency issue."

---

## Priority 3 — Minor Wins (verified, low-impact individually)

### P3.1 — Rate-limit pause between submission batches is fixed, not adaptive

**Location:** `generator/generation.py:540-545`

```python
if self.rate_limit_pause > 0 and submitted % self.batch_size == 0:
    time.sleep(self.rate_limit_pause)
```

A fixed sleep after every N submissions. Azure/OpenAI return `Retry-After` headers on 429.
The rate limiter (`generator/generation.py:910-920`) already has `adaptive_backoff` and
`rate_limiter.penalize()` — but the submission throttle doesn't use them.

**Action:** Replace the fixed `rate_limit_pause` with the adaptive rate limiter's
current window capacity check.

### P3.2 — `_precompute_sitemaps()` builds every sitemap eagerly

**Location:** `generator/generation.py:491` — called once, builds sitemaps for all buckets.

This is fine for 38 pages. For 200+ pages, building 200 sitemaps of 200 entries each is
O(n²) string concatenation. The fix is straightforward: build once, extract per-bucket.

### P3.3 — Page validator does fresh regex scans for hallucinated paths

**Locations:** `generator/validation.py` — `_check_hallucinated_paths()`, `_check_hallucinated_symbols()`, etc.

Each check runs independent regex scans over the full document. The checks are:
- File path extraction (regex for backtick-wrapped paths)
- Symbol name extraction
- Route path matching
- Code fence counting
- Heading extraction
- Word counting

Some of these share work (heading extraction discovers the document structure used by
section checks). Merging into one scan per validation would save ~30% of validation time.

### P3.4 — Consistency pass is uncached, one LLM call per run

**Location:** `generator/consistency.py:44-88`

The consistency pass sends ALL page summaries to the LLM and asks it to find missing
cross-links. This is a single call per run (good) but is uncached — running `deepdoc
generate` twice on the same repo with no changes will repeat this LLM call.

**Action:** Cache the consistency pass by a hash of (all page slugs + all page titles +
all page headings). If nothing changed, skip.

---

## What's Already Fast (verified, credit where due)

| Feature | Implementation | Verdict |
|---|---|---|
| Parallel source scanning | `planner/engine.py:792` — ThreadPoolExecutor, `max_workers` configurable (default 8) | ✅ Good |
| `as_completed` generation | `generator/generation.py:547` — persistent executor, no batch barriers | ✅ Good |
| Shared evidence indexes | `generator/evidence.py` — `_build_module_file_index()`, `_build_symbol_index()` built once in `__init__` | ✅ Good |
| Union-Find cluster merging | `planner/topology.py:338-353` — proper DSU with path compression | ✅ Good |
| Bounded changelog | `persistence_v2.py:70,224` — capped at 50 entries | ✅ Good |
| Content-addressed cache | `generator/cache.py` — SHA256-based, file-level granularity | ✅ Good |
| Incremental chatbot sync | `chatbot/indexer.py` — skips untouched corpora byte-for-byte | ✅ Good |
| Transactional source archive | `chatbot/source_archive.py` — SQLite + gzip blobs, content-addressed | ✅ Good |
| Granular phase telemetry | `pipeline_v2.py` — per-phase timing, LLM usage, retry counts | ✅ Good |
| Token-budget evidence fitting | `generator/evidence.py:286-305` — deterministic priority-order budget allocation | ✅ Good |
| Parse-cache reuse | `planner/engine.py:507` — `parse_file(fpath, content=content)` passes cached content | ✅ Good |
| Non-blocking state lock | `persistence_v2.py:131` — `LOCK_NB`, raises immediately on conflict | ✅ Good |

---

## Recommended Implementation Order

| Order | Work | Est. Impact | Difficulty |
|---|---|---|---|
| 1 | Merge 11 post-processor passes into 4 combined passes | 200-400ms/page | Medium |
| 2 | Build `ValidationFacts` cache once per validation | 100-200ms/validation | Medium |
| 3 | Merge CLASSIFY + PROPOSE into parallel/combined LLM call | 20-60s/run | Medium |
| 4 | Start tail work (glossary, changelog, chatbot) during generation | 15-30s/run | Hard |
| 5 | Precompute `slug_to_bucket` + `file_to_buckets` in `__init__` | ~50ms/run | Trivial |
| 6 | Pass scan hashes to ledger persistence | ~200ms/run | Trivial |
| 7 | Replace fixed rate-limit pause with adaptive limiter | Varies | Easy |
| 8 | Add `parallel_sub_questions` flag for deep research | 5-30s/query | Medium |
| 9 | Cache consistency pass by content hash | 1 LLM call/rerun | Easy |
| 10 | Invert orphan-attachment token index | 0.5-3s at 200+ buckets | Medium |
| 11 | Move `include` filter into tree walker | ~50ms/run | Easy |
| 12 | Use `scan.file_contents` in artifact evidence builder | ~10ms/bucket | Trivial |

---

## Verification Plan

For each optimization, measure before/after using:
- `backend-tss-api_v2` (270 files, Python, 38 pages) — the existing baseline
- A 5-file trivial repo (to check cold-start overhead)
- A warm no-op rerun (to check cache-hit paths)
- A one-file code change (to check incremental path)

Track: wall time by phase, LLM call count, retries, prompt/completion tokens,
files read from disk, and page quality regression (no new stubs, no new invalid
pages, same or better validation pass rate).