# DeepDoc Product Completion Plan

**Status:** Active planning document

**Current release baseline:** `v0.5.5`

**Purpose:** Define how DeepDoc becomes the most trustworthy repository
documentation product for any safe text-based repository without claiming
semantic knowledge the available evidence cannot prove.

## Product Promise

DeepDoc will accept any safe text-based repository and produce the best
documentation that its available evidence can support.

"Any repository" does not mean every language receives identical semantic
depth on day one. It means every discovered file is visible, classified, and
honestly represented. A repository never becomes silently invisible because a
language, framework, build system, or toolchain is unsupported.

DeepDoc must distinguish:

| Capability | Product behavior |
|---|---|
| Deeply supported ecosystem | Source-grounded architecture docs, symbols, routes, calls, runtime/database/integration facts, citations, and capability disclosure |
| Syntax-supported ecosystem | Symbols, imports, file inventory, and explicitly limited relationships |
| Inventory-only ecosystem | File, source-role, language, package/workspace, and coverage visibility without invented semantic claims |
| Unknown or opaque text | Inventory only, labeled unknown; no architecture, runtime, or call claims |
| Broken build or missing toolchain | AST and file evidence continue; semantic-index enrichment degrades gracefully |

The product goal is not prose volume. The product goal is high factual claim
precision, clear coverage disclosure, useful navigation, and fast answers to
real developer questions.

## Non-Negotiable Evidence Rules

1. A file must be discovered before it can be claimed about.
2. A material claim must have structured evidence or be labeled as inference.
3. Comments, strings, tests, fixtures, examples, generated output, and copied
   snippets cannot establish production architecture/runtime facts.
4. A call edge requires a proven call site plus a bounded resolution path.
5. A route-to-handler claim requires framework evidence plus handler resolution.
6. A runtime fact requires parser-valid executable syntax plus framework/API
   binding proof and eligible source/document role.
7. A build/toolchain failure may reduce capability, never trigger plausible
   invented fallback claims.
8. Generated output must never overwrite authored repository content by default.
9. Every generated page must expose its source evidence to readers.
10. Product claims of superiority require reproducible benchmark evidence.

## Current State: v0.5.5

### Universal Product Foundation: Complete

The following architecture and product-safety work is merged in `main`.

| Area | Current state |
|---|---|
| Repository inventory | Every discovered file has a role, language/capability state, and coverage visibility |
| Unsupported languages | Visible as `inventory_only`; no silent dropping |
| Persistent analysis | SQLite persistent index plus content-addressed source store |
| Scale | 55K-file polyglot scan validated in approximately 42 seconds; resource guards and partial-scan reporting exist |
| Output safety | Default `deepdoc-docs/` and `deepdoc-site/`; ownership manifests; non-destructive clean/update; authored collision refusal |
| Authored docs | MkDocs/Zensical and Docusaurus detection; authored docs are secondary evidence; AI/built/generated docs are excluded from factual evidence |
| Navigation | Recursive parent/child Fumadocs tree; parent remains reachable when final child disappears |
| Claim integrity | Claim invalidity propagates to validation, ledger, sync/deploy state, and page provenance |
| Citations | Reader-visible source citations; commit-pinned GitHub links when remote/commit are known; safe around YAML and code fences |
| Runtime facts | Fail-closed parser/binding evidence; document roles excluded; JS/TS, Python, PHP, Go, and Vue hardened against known false positives |
| Product regression | FastAPI-shaped end-to-end product gate plus optional shallow real-FastAPI smoke script |
| Benchmarks | Adversarial and framework corpus with structural/evidence assertions |

### Current Language and Framework Matrix

| Target | Current capability | Framework/product depth |
|---|---|---|
| Python | Deep | Django, DRF, FastAPI, Falcon; Celery, Django signals, Channels, Django runtime/database evidence |
| JavaScript | Deep | Express, Fastify, NestJS; queue/scheduler/realtime runtime evidence |
| TypeScript / TSX | Deep | Express, Fastify, NestJS; decorators, types, runtime evidence |
| Go | Deep | `net/http`, Gin, Echo, Fiber, Chi; goroutines and scheduler runtime evidence |
| PHP | Deep | Laravel routes, jobs, listeners, events, schedules, parser-backed dispatch evidence |
| Vue | Enhanced | SFC scripts, components, props, emits, slots, router/store/composable evidence |
| Java | Semantic-medium | Symbols, annotations, imports, AST call extraction; no Spring MVC/DI semantic layer yet |
| Rust | Syntax-only | Symbols, traits, impls, attributes, imports; no route/call/runtime layer yet |

Current deep route-capable backend framework targets:

```text
Django
Django REST Framework
FastAPI
Falcon
Express
Fastify
NestJS
net/http
Gin
Echo
Fiber
Chi
Laravel
```

## Completion Strategy

The roadmap is intentionally evidence-first and sequential. New ecosystem
support is never added merely because a grammar exists. Each phase has a
measurable completion gate.

### Phase 1: Current-Support Confidence Audit

**Why first:** v0.5.5 has strong foundational tests, but current framework
depth must be measured against real repositories before semantic indexing or
additional language expansion changes the problem surface.

#### Work

1. Build a version-pinned, scan-only real-repository corpus for:
   - FastAPI
   - Django / DRF
   - Express
   - Fastify
   - NestJS
   - Gin or Chi
   - Laravel
   - Vue
2. Add gold structural facts for each repository:
   - workspace roots
   - source-role labels
   - representative routes and handlers
   - runtime facts
   - expected absent facts
   - known integration/data boundaries
3. Measure:
   - parse rate
   - coverage completeness
   - route precision and recall
   - route-to-handler resolution rate
   - call-edge precision/recall sample
   - runtime fact precision
   - source-role false positives
   - claim precision after optional generation runs
   - scan time, memory, index size
4. Fix only P0/P1 factual errors discovered by this corpus.

#### Gate

```text
No known P1 false-positive route, runtime, or source-role fact remains in the
real-repository corpus.
```

#### Do Not Do

Do not broadly refactor working detectors. A measured defect must justify a
change.

### Phase 2: SCIP Feasibility Spike

**Targets:** TypeScript and Java.

**Purpose:** Decide whether semantic indexes measurably improve accuracy enough
to justify their toolchain and operational cost.

#### Hypothesis

AST plus import-evidence-gated resolution is safe but conservative. A semantic
index can improve:

```text
definitions
references
re-exports
aliases
overloads
type relationships
interface implementations
monorepo symbol identity
call-target candidates
```

#### What SCIP Does Not Prove

SCIP does not independently prove runtime behavior, dependency injection,
reflection, framework dispatch, queue execution, or service-to-service network
calls. DeepDoc framework analysis remains mandatory.

#### Spike Questions

For TypeScript and Java, test healthy, missing-dependency, and broken-build
projects.

| Question | Required answer |
|---|---|
| Can the indexer run automatically? | Exact dependency/toolchain requirements |
| What failure modes occur? | Missing node_modules, Maven/Gradle failures, custom aliases, monorepos |
| What facts are available? | Definitions, references, implementations, types, symbol ranges |
| What improves? | Measured resolution accuracy versus AST-only baseline |
| What does it cost? | Index time, peak memory, disk size, cache invalidation scope |
| Can fallback work? | AST-only output remains safe and useful when indexing fails |

#### Gate

Ship a semantic-index provider only if it improves measured TypeScript/Java
symbol or call resolution materially while preserving the no-toolchain fallback.

#### Decision Outcomes

| Result | Next action |
|---|---|
| TypeScript reliable, Java unreliable | Ship TypeScript provider only |
| Both reliable | Build shared `SemanticIndexProvider` abstraction |
| Both fragile | Do not ship SCIP; deepen AST/framework analysis instead |
| Framework errors dominate results | Harden the specific framework detector before SCIP |

### Phase 3: Semantic Index Productization

Only begins after Phase 2 passes its gate.

#### Work

1. Add an optional `SemanticIndexProvider` interface.
2. Store index metadata and fingerprints in `.deepdoc/`.
3. Define capability levels:

```text
AST-only
semantic-index available
semantic-index degraded
semantic-index unavailable
```

4. Use semantic facts only when provider output is valid and current.
5. Preserve AST-based call/import fallback on every failure path.
6. Expose index provenance and degradation in coverage/page evidence.
7. Add incremental invalidation keyed by workspace, lockfile, source hash, and
   indexer version.

#### Gate

```text
Semantic-index-backed claims have higher measured precision than AST-only claims,
and a failed index cannot make a repository less documented or less safe.
```

### Phase 4: Deepen Java into a Full Spring Ecosystem

Java currently has parser and AST call support. Before claiming full Java
support, add Spring-specific evidence.

#### Work

```text
Spring MVC route annotations
Spring WebFlux routes
controller -> service -> repository evidence
dependency injection registration/provenance
Spring Boot entrypoints
JPA entities/repositories
scheduled jobs
Kafka/RabbitMQ listener evidence
Maven and Gradle workspace/target discovery
```

#### Gate

```text
Spring route precision/recall and controller/service/repository evidence meet
the same benchmark threshold as current deep backend ecosystems.
```

### Phase 5: C# and ASP.NET Core

#### Work

```text
C# syntax and symbols
using/module resolution
ASP.NET controller attributes
minimal APIs: MapGet, MapPost, MapGroup
dependency injection: AddScoped, AddSingleton, AddTransient
Entity Framework models
BackgroundService and IHostedService runtime evidence
solution/project/workspace discovery
```

#### Gate

```text
No route, DI, or background-service claim is emitted without parser or semantic
evidence. ASP.NET real-repo benchmark meets deep-support thresholds.
```

### Phase 6: Ruby and Rails

#### Work

```text
Ruby parser and module/class/method model
require and require_relative resolution
Rails routes: resources, namespace, scope, custom verbs
ActiveRecord models and associations
controllers, concerns, service objects
ActiveJob and Sidekiq runtime evidence
ActionCable consumers
Rake tasks and scheduler evidence
Bundler/workspace discovery
```

#### Gate

```text
Rails routes, models, jobs, and ActionCable claims are benchmarked against real
repositories with the same fail-closed contract as existing runtime evidence.
```

### Phase 7: Cross-Language Protocol and Service Graphs

**Primary target:** Protobuf and gRPC.

#### Work

1. Parse `.proto` packages, messages, services, and methods.
2. Identify generated client/server bindings using import and build evidence.
3. Link only exact package/service/method identities across languages.
4. Surface:

```text
client -> protobuf method -> server handler -> implementation
```

5. Add OpenAPI cross-service links where exact operation identities exist.
6. Never create a cross-language edge from matching names alone.

#### Gate

```text
Every cross-language edge is anchored by a shared protocol identity and local
binding evidence. No name-only link is allowed.
```

### Phase 8: Deepen Rust and JVM Family Support

#### Rust

```text
Actix, Axum, Rocket routes
Tokio tasks and runtime evidence
Cargo workspaces
trait/impl-aware call candidates
SQLx/Diesel data evidence
```

#### Kotlin

```text
Leverage Java/Spring semantic and route infrastructure
Kotlin symbols, coroutines, Spring annotations
Gradle multi-module evidence
```

#### Gate

```text
Rust and Kotlin move from syntax-supported to semantic-medium or deep only when
their framework benchmark corpus proves factual accuracy.
```

### Phase 9: Additional Ecosystem Expansion

Priority is driven by customer demand and benchmark readiness, not grammar
availability alone.

| Candidate | Target depth | Main challenge |
|---|---|---|
| Swift / Vapor | Syntax then routes | Toolchain availability |
| Dart server frameworks | Syntax then routes | Smaller backend ecosystem |
| Scala / Play / Akka | JVM reuse | Complex implicits/runtime model |
| Elixir / Phoenix | Syntax, routes, processes | Distinct concurrency model |
| C/C++ | Syntax, CMake, symbols | Preprocessor, headers, templates |
| Terraform / Helm | Infrastructure evidence | Declarative dependency graph |
| SQL / dbt | Data lineage | Cross-file/query semantics |

### Phase 10: Complete Repository and Workspace Model

DeepDoc must represent large monorepos without relying on arbitrary directory
or token grouping.

#### Work

```text
package manager and workspace discovery
build targets and deployables
package ownership boundaries
service dependency graph
shared library identification
workspace-local semantic index caches
partial and scoped scan guarantees
content-addressed artifact evidence
resource profiles: fast, standard, deep
```

#### Gate

```text
100K+ file repositories produce complete coverage reports, bounded analysis,
and explicit partial/degraded capability reporting without whole-repo prompts.
```

### Phase 11: Documentation Experience and Human Ownership

Generated docs must coexist with human-authored docs and provide a safe editing
experience.

#### Work

```text
explicit authored-page ownership metadata
never-touch rules for handcrafted pages
page-level generated/handwritten/shared status
safe edit or overlay workflow for generated pages
reviewable documentation change sets
page diff previews before regeneration
human-approved claim corrections
feedback loop from corrections into benchmarks
```

#### Gate

```text
Handcrafted pages cannot be overwritten by generate, update, clean, or deploy
without an explicit owner-approved action.
```

### Phase 12: Chatbot Evidence Productization

The chatbot must meet the same proof standard as generated pages.

#### Work

```text
claim-level evidence in answers
runtime/call/route source citations
explicit unknown and degraded answers
semantic-index retrieval enrichment when available
cross-language protocol traces
answer evaluation corpus tied to repository facts
```

#### Gate

```text
Chatbot citation precision, evidence recall, and abstention precision meet
published thresholds across supported and unsupported repository cases.
```

### Phase 13: Continuous Benchmark and Competitive Proof

Benchmarks are a permanent product system, not a one-time release artifact.

#### Corpus Layers

```text
Adversarial micro-fixtures
Supported framework fixtures
Polyglot monorepos
Version-pinned real open-source repositories
Enterprise-shaped private evaluation corpus
Large scale repositories
Broken/missing-toolchain repositories
```

#### Required Metrics

```text
claim precision and recall
evidence traceability
route-to-handler precision/recall
call-edge precision/recall
source-role precision
unsupported-language honesty
workspace boundary accuracy
runtime fact precision
incremental correctness
scan/index/generation resource usage
developer task success and time-to-answer
```

#### Competitive Method

Compare DeepDoc with DeepWiki and relevant documentation products only using
reproducible structural/evidence metrics. Do not claim superiority based on
page count, prose length, or subjective screenshots.

#### Gate

```text
Public product claims are backed by version-pinned benchmark reports and
documented methodology.
```

## Release and Quality Gates

Every meaningful release must satisfy:

```text
full test suite
compileall
package build
output-safety regressions
FastAPI product gate
runtime evidence regressions
scale profile where affected
benchmark corpus appropriate to changed capability
no invalid generated pages in release validation
```

Changes affecting a persisted format, ownership contract, evidence semantics,
routes, or runtime facts must update:

```text
AGENTS.md
README.md when user-visible behavior changes
CHANGELOG.md for release behavior
engine fingerprint where update compatibility requires it
relevant benchmark expectations
```

## Decision Framework

Before each phase, answer these questions:

1. What exact factual claim becomes newly possible?
2. What structured evidence proves that claim?
3. What false-positive example proves the boundary is fail-closed?
4. What happens when parser/index/toolchain data is absent or broken?
5. Which benchmark metric must improve for this work to ship?
6. Does this deepen current support or add broad but shallow support?
7. Is there a smaller product-safe vertical slice?

If any answer is missing, run a bounded spike rather than shipping a broad
feature.

## Immediate Next Action

Plan and execute **Phase 1: Current-Support Confidence Audit** followed by
**Phase 2: SCIP Feasibility Spike**. Do not begin broad new-language expansion
until those phases provide measured evidence for the next priority.
