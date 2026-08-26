# Universal DeepWiki-Quality Content Roadmap

> **For Hermes:** This is a planning-only roadmap. Do not begin implementation until the user selects Slice C1 and approves its detailed implementation brief.

**Goal:** Make DeepDoc generate useful, honest documentation for any text-based repository and DeepWiki-quality architecture content for large repositories where stronger structural/semantic evidence is available.

**Architecture:** Keep existing language parsers, framework detectors, Slice A bounded planning, and Slice B boundary refinement. Add a product-owned RepositoryModel / SourceIndex beneath them. Every repo receives universal structural facts from files, manifests, workspaces, builds, and runtime configuration. Language packs, framework packs, and optional semantic providers progressively enrich the same normalized model.

**Non-goals:** Do not replace existing Python/JS/TS/Vue/Go/PHP parsers with a weak generic parser. Do not require LSP or SCIP for baseline documentation. Do not make visible line citations a prerequisite; retain internal fact/evidence provenance from the beginning.

---

## Slice C0 — Benchmark Contract and Capability Vocabulary

**Purpose:** Establish what “DeepWiki-quality” means before changing production behavior.

**Deliverables:**
- Checked-in benchmark catalog with pinned revisions/licenses/configuration for Vue core, React, VS Code, a React app, a Vue app, Rust/Cargo, Java/Spring, and .NET.
- Gold architecture contracts: required pages, expected workspace/build/runtime anchors, expected subsystem hierarchy, and reader tasks.
- Capability vocabulary: `inventory`, `structural`, `resolved_static`, `semantic_verified`, plus explicit `unsupported`, `skipped`, `failed`, and `coarse_accounted` states.
- Benchmark scorecard rejects empty or incomplete gold data rather than returning a perfect score.

**Acceptance:** A benchmark cannot pass merely because pages exist; it must evaluate expected architecture/build/runtime anchors and explicit source accounting.

---

## Slice C1 — SourceIndex Foundation and Universal Safe Intake

**Purpose:** Ensure every safe text/config/source file is visible to DeepDoc, persist facts incrementally, and retain existing behavior through a compatibility projection.

**Deliverables:**
- Versioned `.deepdoc/index/` SourceIndex backed by SQLite metadata/relationships plus content-addressed source blobs.
- `FileRecord`, `Entity`, `Relationship`, `Evidence`, `Capability`, and diagnostics contracts.
- Universal discovery with binary, generated, vendored, redacted, and oversized states.
- Unknown readable files become structural inventory records rather than silently disappearing.
- Existing `ParsedFile`/`RepoScan` remain supported through a `RepoScanProjection`; no immediate planner rewrite.
- Incremental cache keys include source hash, extractor version, and configuration digest.

**Acceptance:** Existing supported-language fixture output remains equivalent under the compatibility projection; every scanned file has an explicit disposition.

---

## Slice C2 — Workspace, Package, Build, and Runtime Starting Points

**Purpose:** Discover the real architecture anchors of every repository before source-level semantic analysis.

**This slice explicitly includes `pom.xml` and analogous starting-point files.**

**Deliverables:**
- `WorkspaceGraph`: repository, workspace, package/module/project, dependency, export, alias, and generated-source nodes.
- `BuildRuntimeGraph`: scripts, build targets, CI jobs, deploy units, processes, entry points, config modes, and artifact outputs.
- Manifest adapters for:
  - Node: `package.json`, npm/Yarn/pnpm workspaces, `pnpm-workspace.yaml`, Turbo, Nx, Lerna, `tsconfig` references/paths.
  - Java/Kotlin: root/module `pom.xml`, `settings.gradle`, `build.gradle`, `build.gradle.kts`.
  - Rust: `Cargo.toml`, Cargo workspace members, features, binaries.
  - .NET: `.sln`, `.csproj`, `.fsproj`.
  - Go: `go.mod`, `go.work`.
  - Python: `pyproject.toml`, package roots, dependency/config tools.
  - Ruby/PHP: `Gemfile`, `composer.json`.
- Deterministic planning-unit seed from workspace/package/module topology, with Slice B evidence used only to refine ambiguous membership.

**Acceptance:** A multi-module Maven project, pnpm monorepo, Cargo workspace, and .NET solution each yield correct package/module topology without requiring a language semantic adapter.

---

## Slice C3 — Universal Structural Language Packs

**Purpose:** Add useful syntax-level structure across languages without requiring compiler/toolchain semantics.

**Deliverables:**
- `LanguagePack` contract: matchers, Tree-sitter grammar/query pack, custom lowering where needed, capabilities, version, diagnostics.
- Generic Tree-sitter extraction into common entities: module/package declarations, classes/interfaces/traits/structs, functions/methods, imports/includes, exports/public APIs, annotations/decorators, and source ranges.
- `VirtualDocument` mapping for embedded formats such as Vue, Svelte, Astro, HTML templates, and script blocks so facts point back to original source spans.
- Existing Python/JS/TS/Vue/Go/PHP parsers migrate behind the pack contract and retain their specialized behavior.
- Initial structural language additions: Rust, Java, Kotlin, C#, C/C++.

**Acceptance:** Unsupported-language repositories become structurally documented; no syntax-level relationship is described as a resolved call or type relationship.

---

## Slice C4 — Framework and Product Architecture Overlays

**Purpose:** Turn generic repository structure into meaningful product architecture for priority ecosystems.

**Deliverables:**
- `FrameworkPack` contract that emits facts into the same RepositoryModel and never owns its own planner/generator path.
- Priority overlays:
  1. Electron + VS Code extension architecture: main/workbench/shared/extension-host process roles, IPC, contributions, commands, activation events, build targets.
  2. React: package/renderer boundaries, JSX component relations, hooks, context, router/data-loading/state facts where deterministic.
  3. Vue: compiler-SFC mapping, template component references, Router, Pinia/store, SSR/HMR facts.
  4. Normalize and preserve Python/Django/FastAPI/Falcon, Express/Fastify/NestJS, Laravel, and Go runtime/route facts.
- Build/runtime/process facts remain distinct relationship kinds from source calls.

**Acceptance:** VS Code, React, and Vue benchmark fixtures expose architecture-specific facts that cannot be inferred from directory names alone.

---

## Slice C5 — Bottom-Up Hierarchical Wiki Synthesis

**Purpose:** Generate one coherent repository wiki from bounded facts, not disconnected per-unit pages.

**Deliverables:**
- Deterministic `PackageCard`, `ComponentCard`, `BuildTargetCard`, `RuntimeSurfaceCard`, and `SubsystemCard` summaries.
- Bounded synthesis hierarchy:
  `file → module → package → subsystem → repository architecture`.
- Repository overview consumes validated child cards rather than raw repository inventory.
- Existing Slice A/B local isolation remains: unit prompts get local facts plus bounded aggregate remote relationships, never remote raw paths/symbols/edges.
- Page contracts distinguish architecture overview, workspace/package, subsystem, runtime/build, flow, and implementation pages.

**Acceptance:** DeepDoc produces expected top-level hierarchy for Vue, React, and VS Code benchmark targets without a whole-repo prompt.

---

## Slice C6 — Optional Precision Providers and Benchmark-Gated Expansion

**Purpose:** Upgrade high-value ecosystems from structural to compiler-backed semantic documentation without making providers mandatory.

**Deliverables:**
- `SemanticProvider` contract with capability probing, sandboxing, time/memory limits, caching, and build/lockfile freshness checks.
- Optional SCIP ingestion when a compatible index is present or deterministically generated.
- Optional bounded LSP adapters only where useful and available; failure never blocks baseline docs.
- Semantic precedence rules: compiler/SCIP-backed facts outrank AST structural facts, which outrank heuristics; all evidence remains retained.
- Benchmark-gated language depth: Rust/Cargo, Java/Kotlin/Spring, C#/.NET, then Ruby/Rails, C/C++, Swift, Dart, Scala, Elixir, and others based on real demand.

**Acceptance:** Provider failure degrades only to structural docs; benchmark release gates require architecture correctness, source accounting, graph quality, content task success, cost/time bounds, and non-empty gold data.

---

## What `pom.xml` Means in This Design

`pom.xml` is not merely a config file. In Slice C2 it becomes an architectural starting point:

- parent/child Maven module hierarchy;
- `groupId`, `artifactId`, version, packaging;
- inter-module dependencies;
- plugins and build lifecycle;
- compiler/test/package/spring-boot targets;
- source/test roots;
- active profiles and configuration modes.

That information seeds package/module cards and planning units before Java source parsing begins. A Java parser later enriches those module facts; it does not replace them.

---

## Invariants Across All Slices

- Preserve existing per-language parsers and framework detectors as specialized packs.
- Preserve Slice A bounded prompts/split-retry/page caps and Slice B conservative ownership.
- No silent file loss: every file is semantic, structural, skipped-with-reason, unsupported, generated/vendor, or coarse-accounted.
- Do not present heuristic edges as verified runtime/call relationships.
- Keep global extraction and bounded local planning separate.
- Use incremental invalidation, not full reanalysis for ordinary changes.
- No large-repo marketing claim until benchmark gates pass for each named target.

---

## User Review Gates

1. Approve the C0/C1/C2 architecture before implementation begins.
2. Review actual generated Vue/React/VS Code benchmark wikis after C5 before a public parity claim.
3. Approve each semantic-provider/language expansion only after benchmark evidence is reviewed.
