# DeepDoc CLI Performance Audit

This document contains a verified performance audit of the `deepdoc` CLI codebase, superseding or supplementing prior documentation. It is restricted to the Python CLI logic and omits the web dashboard and VS Code extension.

## 0. General Context
The main bottlenecks in this pipeline involve heavy I/O (files repeatedly parsed and scanned without batching), inefficient sequential processing, and repeated LLM calls during Generation and planning phases. The issues below outline the major performance defects.

## 1. Scanner and Planner Inefficiencies

### 1.1 Unbatched `RepoScan` Processing (P2.2)
**Locations:** `scanner/runtime.py`, `scanner/database.py`, `scanner/integrations.py`, `scanner/artifacts.py`
**Issue:** Various detector families (runtime types, database schemas, integrations, and artifacts) loop independently over the entire set of loaded `file_contents`. For a large repository, this means iterating through hundreds of file strings multiple times, searching with distinct sets of regexes.
**Resolution Needed:** Construct a unified scan pass or a per-file signal record so that content strings are processed exactly once and shared by all scanner families.

### 1.2 Topology Cluster Merging is Pairwise (P3.4)
**Location:** `planner/topology.py:328-372`
**Issue:** `_merge_proto_clusters` merges clusters pairwise based on Jaccard overlap and cross-calls. With many small entry points, this approach approaches quadratic performance $O(n^2)$.
**Resolution Needed:** Refactor to use a Union-Find (Disjoint-Set) data structure or block merges via inverted indices on cross-edges.

### 1.3 Repeated Pairwise Scoring (P3.6)
**Location:** `planner/bucket_refinement.py:230-323, 665-700`
**Issue:** When attaching orphans and consolidating buckets, unassigned files are scored repeatedly against every bucket. Bucket consolidation also evaluates all pairs of buckets.
**Resolution Needed:** Defer orphan attachment and utilize inverted text-to-bucket or token-to-bucket indices to block candidates early instead of all-pairs comparisons.

### 1.4 Late Filter Application (P2.1)
**Location:** `planner/engine.py:383-425, 453-460`
**Issue:** The file walker traverses the full non-excluded tree and executes path checks/progress. Only afterwards does it reject files that don't match the `include` filter.
**Resolution Needed:** Apply include filters earlier during tree walking.

## 2. Generation, Post-processing, and LLM Deficiencies

### 2.1 Batch Generation Executor (P1.4)
**Location:** `generator/generation.py:465-543`
**Issue:** Page generation is orchestrated in batches using `ThreadPoolExecutor`. The pipeline waits for the slowest request in a batch before spinning up the next batch. This results in heavy idle time.
**Resolution Needed:** Switch to a persistent, rolling worker pool that immediately picks up new tasks as existing workers finish.

### 2.2 Uncached `slug_to_bucket` Precomputations (P2.8)
**Location:** `generator/generation.py:1466-1532`
**Issue:** Lookups like `slug_to_bucket` and `file_to_buckets` are completely rebuilt via dictionary comprehensions for *every single planned page* during generation iteration.
**Resolution Needed:** Precompute these structures once inside `BucketGenerationEngine.__init__`.

### 2.3 `read_text` Rereads and Reruns (P2.6)
**Location:** `generator/evidence.py:247-259, 634-656, 1565-1642`
**Issue:** While standard code evidence caches `scan.file_contents`, specialized DB and schema routines dynamically fallback to `src_path.read_text()` or `ar_path.read_text()` rather than reusing the cache effectively.
**Resolution Needed:** Route all schema and specialized content extraction back to the original cached `file_contents`.

### 2.4 Glossary Linking O(N^2) (P3.11)
**Location:** `pipeline_v2.py:1549-1588` (And `_apply_glossary_links`)
**Issue:** Glossary linking iterates through every generated file attempting string replacement, regardless of whether a page was modified.
**Resolution Needed:** Process only newly generated/changed pages unless the domain-glossary itself changed.

### 2.5 Validation Full-Document Redundancy (P2.7)
**Location:** `generator/validation.py`, `generator/post_processors.py`, `generator/generation.py`
**Issue:** Post-processors (Mermaid fixing, markdown fixing) and validators parse and iterate through entire documents sequentially for every single rewrite/repair pass.
**Resolution Needed:** Abstract into a `ValidationFacts` schema populated once per draft to bypass repeated parsing.

## 3. Persistence and Chatbot Inefficiencies

### 3.1 Unbounded Changelog Appending (P3.9)
**Location:** `changelog_writer.py`, `persistence_v2.py:212-224`
**Issue:** Changelogs append their history, load all previous entries, and rewrite `whats-changed.md` synchronously. This file will infinitely grow.
**Resolution Needed:** Render only a bounded, rolling recent history window.

### 3.2 Sequential Corpora Sync (P2.12)
**Location:** `chatbot/indexer.py:54-111`
**Issue:** The chatbot index builds seven distinct corpora sequentially, stalling embedding processes against SQLite writers.
**Resolution Needed:** Parallelize construction of corpora chunks before funneling embeddings into a bounded queue.

### 3.3 Overarching Run Locks (P3.13)
**Location:** `pipeline_v2.py:307-309`
**Issue:** `deepdoc_state_lock` covers the entirety of `_run_locked` encompassing network requests, LLM execution, generation, indexing, and site copying.
**Resolution Needed:** Downsize the atomic lock to specifically guard mutating writes at the end of the pipeline.

### 3.4 Deep Research Subquestions are Sequential (P2.14)
**Location:** `chatbot/deep_research.py:194-223, 496-575`
**Issue:** The agent spins through multi-step ReAct questions completely sequentially.
**Resolution Needed:** Parallelize the independent subquestion tools utilizing bounded concurrency.

### 3.5 Duplicate List Comprehensions per file (P2.10)
**Location:** `chatbot/indexer.py:203`
**Issue:** `discover_artifact_files()` and `discover_repo_doc_files()` exist within changed-file list comprehensions. They execute a full discovery per modified file.
**Resolution Needed:** Pre-evaluate these discoveries into a set, and perform a fast `O(1)` membership check instead.
