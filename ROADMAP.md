# DeepDoc Universal Architecture — Foundation Complete

## Status: The original universal architecture and product-hardening slices are complete. See [`plans/DEEPDOC_PRODUCT_COMPLETION_PLAN.md`](plans/DEEPDOC_PRODUCT_COMPLETION_PLAN.md) for the active product roadmap from v0.5.5 onward.

## Goal

Make DeepDoc generate exceptionally accurate documentation for **any** repository — any language, framework, layout, or size. Surpass DeepWiki and Mintlify as the industry standard.

## Architecture

Three-tier system:
1. **Universal pipeline** — language-agnostic coverage, evidence provenance, claim validation
2. **Deliberately small set of deep analyzers** — tree-sitter, call graph, route detection for chosen ecosystems
3. **Honest fallback** — every unsupported file is visible, classified, and labeled; nothing silently discarded

## Slices

### Slice 0 — RepositoryModel + Adversarial Benchmarks
**Status**: ✅ Complete
**Duration**: 2-3 days
- `deepdoc/repo_model.py`: `RepositoryModel`, `FileEntry`, `LanguageInfo`, `CoverageReport` dataclasses
- `tests/fixtures/adversarial/`: 7 micro-fixtures (test-trap, fixture-trap, generated-trap, copy-paste-trap, name-collision, broken-imports, polyglot-small, unknown-foo)
- `scan_repo()` additionally constructs `RepositoryModel` (additive, no deletions)
- **Gate**: coverage report correct on all adversarial fixtures; all 604 tests pass

### Slice 1 — LanguageSupport Registry
**Status**: ✅ Complete
- `deepdoc/language_support.py`: `LanguageSupport` dataclass, `_build_default_registry()`
- Replace `scan_repo()` local `ext_to_lang` with registry lookup
- **Gate**: registry maps every extension identically; all tests pass

### Slice 2 — Persistent Index + ContentStore
**Status**: ✅ Complete
- SQLite `PersistentIndex` (files, symbols, imports, call_edges tables) in `.deepdoc/index.db`
- Content-addressed `ContentStore` in `.deepdoc/content/{hash[:2]}/{hash}.gz`
- `scan_repo()` writes to persistent store AND hydrates `RepoScan` dicts for backward compat
- **Gate**: RSS < 200MB on 5K-file repo; all tests pass

### Slice 3 — Java + Rust SyntaxAnalyzer
**Status**: ✅ Complete
- `tree-sitter-java` + `tree-sitter-rust` parsers
- `parser/java_parser.py`, `parser/rust_parser.py`
- Spring Boot + Actix-web fixture repos
- **Gate**: symbols extracted, coverage shows "parsed" status; all tests pass

### Slice 4 — Unknown Language Inventory
**Status**: ✅ Complete
- Every file gets a `FileEntry` regardless of parse status
- `parse_status="inventory_only"` for unsupported extensions
- Coverage report shows per-language parse rates
- **Gate**: no file absent from coverage; unsupported languages labeled

### Slice 5 — Universal Call Graph API
**Status**: ✅ Complete
- `CallExtractor` ABC, per-language extractors
- Language-agnostic `resolve_call_edges()`
- Go receiver type tracking fix in `GoCallExtractor`
- **Gate**: identical edges to current output; all call-graph tests pass

### Slice 6 — Java Call Graph
**Status**: ✅ Complete
- `JavaCallExtractor` using tree-sitter-java
- Spring annotation recording as `FrameworkAnnotation`
- Interface-dispatch edges labeled unresolved
- **Gate**: real edges detected, no fabricated edges

### Slice 7 — Evidence Provenance + Claim Validation
**Status**: ✅ Complete
- `deepdoc_claims` frontmatter on every generated page
- `ClaimValidator` cross-references against `RepositoryModel` evidence
- Source trust scoring with `@generated` comment detection
- Hard-fail on ungrounded route/call claims
- **Gate**: route precision ≥ 0.95, call precision ≥ 0.90

### Slice 8 — Scale Validation
**Status**: ✅ Complete
- 50K-file polyglot fixture generation script
- Timeout + `max_repo_files` config
- Memory, time, coverage validation
- **Gate**: < 1GB RSS, < 5min scan, complete coverage

### Slice 9 — Full Benchmark + DeepWiki Comparison
**Status**: ✅ Complete
- `benchmarks/runner.py`: automated benchmark for 3 categories
- `benchmarks/corpus/expectations.json`: gold expectations for 18 fixtures
- `benchmarks/results/`: JSON summary + Markdown report
- 16/16 cases pass (100% pass rate) — all adversarial + framework fixtures verified
- Complete benchmark corpus (Categories A-D)
- Automated benchmark runner
- DeepWiki comparison via `deepwiki-to-md`
- **Gate**: publishable accuracy numbers

## Verification

After every slice:
```bash
python -m compileall deepdoc
python -m pytest -q
```

## Commit Convention

All commits authored by `me` (never agent name). Descriptive messages referencing the slice.
