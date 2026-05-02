"""Bucket-type prompt templates for the v2 bucket planner."""

from .system import CROSS_LINK_SECTION

FEATURE_BUCKET_V2 = """\
Generate **feature documentation** for a business workflow / feature area.

Page: {title}
Description: {page_description}
Bucket type: feature
Required sections: {required_sections}
Required diagrams: {required_diagrams}
Coverage targets: {coverage_targets}

Source files and their contents:
{source_context}
""" + CROSS_LINK_SECTION + """

Write comprehensive feature documentation following this mandatory outline:

# {title}

## Overview
What this feature does, why it exists, and its business purpose. \
Link to the architecture page and related features from the sitemap.

## Files Covered
Include a summary table of all source files relevant to this feature. Columns: \
File Path, Role (handler/service/model/validator/task/config), Key Symbols, \
and a one-line Responsibility. Sort by role importance (handlers first, then services, \
then models, then utilities). Skip this section only if the feature has fewer than 3 files.

## Main Workflows
Step-by-step explanation of the primary workflows in this feature. \
Include a **Mermaid flowchart** for the main flow. \
For each step that involves another module or service, link to that page.
If a workflow path is only partially evidenced, say which part is inferred vs directly grounded.

## Participating Endpoints
List all API endpoints involved in this feature. For each:
- Method + path
- What it does in the context of this feature
- Link to the endpoint's API reference page from the sitemap

## Core Helpers & Business Rules
Key functions, classes, and validation rules. For each:
- What it does and why
- File path (always!)
- Important parameters and return values
- Code example showing real usage
- ALL conditional logic inside the function — document every feature flag, \
guard clause, and branching path. If a function checks Redis keys, config flags, \
user state (is_block, is_two_fa, is_exclusive), or request parameters to change \
behavior, document each branch explicitly.

If "Resolved Helper Functions" are provided in the source context, use their actual \
implementation to describe behavior accurately rather than guessing.

## State Transitions
How data/entity state changes through this feature. \
Include a **Mermaid state diagram** if applicable.

## Integrations Involved
External systems this feature talks to. For each:
- What integration and why
- Link to the integration's page from the sitemap if one exists

## Configuration & Environment
Config flags, feature toggles, env vars that affect this feature.
Do not invent env vars or flags that are not present in the evidence.

## Edge Cases & Failure Modes
Non-obvious behavior, error scenarios, race conditions, known limitations.

## Diagrams
Include all required diagrams: {required_diagrams}. \
Every diagram must be Mermaid and must reference actual code artifacts.

## Quick Reference
Include a compact reference table of the most important public functions, classes, \
and handlers in this feature. Columns: Symbol, File Path, Signature or Key Args, \
and What It Does (one line). This is for quick scanning — keep it concise. \
Include 5-15 entries, prioritizing handlers, service functions, and key validators.

## Constants, Enums & Status Values
If the evidence contains enums, status constants, state machine values, or important \
type definitions that affect this feature's behavior, list them here with their valid \
values and what each value means. Skip this section if no such constants exist in the evidence.

## See Also
Related feature, endpoint, and integration pages from the sitemap.

Reference EVERY file path. Link to related pages throughout. Be deep and specific.
"""


ENDPOINT_BUCKET_V2 = """\
Generate **API reference documentation** for a family of related endpoints.

This page covers multiple endpoints in one group. Use markdown tables and fenced \
code blocks for parameters, request bodies, response fields, and examples. \
Do NOT use JSX field components.

Page: {title}
Description: {page_description}
Bucket type: endpoint
Required sections: {required_sections}
Required diagrams: {required_diagrams}

Endpoints in this bundle:
{endpoints_detail}

Handler source code and evidence:
{source_context}

{openapi_context}
""" + CROSS_LINK_SECTION + """

Ground this page in the provided route evidence and handler code only. If a path, auth mode,
health endpoint, payload field, or side effect is not present in the evidence, state uncertainty
instead of asserting it.

Write comprehensive endpoint family documentation:

# {title}

## Overview
What this API resource handles and who uses it. \
Include a **Mermaid sequence diagram** showing the typical request lifecycle \
(client → middleware → handler → service → DB → response). \
Link to the auth/middleware page from the sitemap.

## Authentication
What auth is required. Reference the exact middleware and link to the auth page in the sitemap.

---

## Endpoints

For EACH endpoint, use this structure (repeat for every endpoint in the family):

### `METHOD /path/to/endpoint`

**Handler**: `handlerFunction()` (`file/path.ts:line`)

One sentence on what this endpoint does.

#### Parameters

Use a markdown table like this (adapt it to the real fields and types):

| Location | Name | Type | Required | Description |
|----------|------|------|----------|-------------|
| path | id | string | yes | Resource ID |
| query | status | string | no | Filter by status |
| body | name | string | yes | Resource name |

If the request body is nested, add a short nested bullet list or subsection below the table.

#### Response

Use a markdown table for success response fields:

| Field | Type | Description |
|-------|------|-------------|
| id | string | Unique resource ID |
| status | string | Current status |

Then show a realistic request + response example:
```
```bash
curl https://api.example.com/v1/resource/123 \\
  -H "Authorization: Bearer $TOKEN"
```

```json
{{ "id": "res_123", "status": "active" }}
```
```

#### Errors
| Status | Condition |
|--------|-----------|
| 400 | ... |
| 401 | Unauthorized |
| 404 | Resource not found |

---

## Execution Flow
Step-by-step walkthrough of what happens internally when a request is processed. \
Reference exact function names and file paths throughout. Document ALL conditional \
branches — feature flags, user state checks (blocked, 2FA, subscription), platform- \
specific behavior, and error guards. Every `if/else` is a business rule.

## State Changes & Side Effects
What database records, cache keys, or queues are modified. \
Background jobs or webhooks triggered. Reference exact functions. \
Include async tasks (Celery), analytics events, cache invalidations, and \
any Redis feature flag checks that gate behavior.

## Constants, Enums & Status Values
If endpoints in this family use status enums, type constants, role values, or \
state machine transitions, list them with their valid values. Document what each \
value means and which endpoint paths produce or consume them. Skip if none appear \
in the evidence.

## See Also
Related endpoint, feature, and integration pages from the sitemap.

Reference EVERY file path. Be specific and use real field names from the source code.
"""


INTEGRATION_BUCKET_V2 = """\
Generate **integration documentation** for an external system.

Page: {title}
Description: {page_description}
Bucket type: integration
Required sections: {required_sections}
Required diagrams: {required_diagrams}
Coverage targets: {coverage_targets}

Source files and evidence:
{source_context}
""" + CROSS_LINK_SECTION + """

Write comprehensive integration documentation following this mandatory outline:

# {title}

## What This Integration Does
Purpose and business role of this external system. Why the codebase talks to it.

## Where It Enters the Codebase
Main entry points — which files and functions initiate communication with this system. \
Include file paths for every client, adapter, wrapper, or SDK usage.

## Participating Features & Endpoints
Which business features and API endpoints use this integration. \
Link to each from the sitemap.

## Request/Response or Message Flow
Include a **Mermaid sequence diagram** showing the typical interaction pattern. \
Document payload structures, headers, authentication. \
If the evidence contains request/response type definitions, schemas, or payload shapes, \
include them as grounded code snippets or tables. Show the actual field names and types \
from the source, not invented examples.

## Auth & Configuration
How to set up credentials, API keys, base URLs. \
Environment variables and config files involved. \
Link to the Setup page from the sitemap.

## Retry, Reconciliation & Failure Handling
What happens when the external system is down or returns errors. \
Retry logic, circuit breakers, fallback behavior, reconciliation jobs.

## Operational Gotchas
Rate limits, timeouts, payload size limits, version-specific quirks, \
known failure modes, monitoring/alerting requirements.

## Diagrams
Include all required diagrams. Show how this integration fits into the \
broader system architecture.

## See Also
Related feature and endpoint pages from the sitemap.

Reference EVERY file path. Be specific about actual payloads and error handling.
"""


SYSTEM_BUCKET_V2 = """\
Generate **system documentation** for a cross-cutting concern or architectural component.

Page: {title}
Description: {page_description}
Bucket type: system
Required sections: {required_sections}
Required diagrams: {required_diagrams}

Source files and evidence:
{source_context}
""" + CROSS_LINK_SECTION + """

Write comprehensive system documentation following this mandatory outline:

# {title}

## Overview
What this system component does and its role in the architecture. \
Link to the architecture overview and related system pages from the sitemap.

## Files Covered
Include a summary table of all source files relevant to this system component. Columns: \
File Path, Role, Key Symbols, and Responsibility (one line). Sort by importance. \
Skip this section only if the component has fewer than 3 files.

## Architecture & Design
Include a **Mermaid diagram** showing how this component fits into the system. \
Explain key design decisions and patterns used.

## Key Components
For each important class, function, or module:
- What it does
- File path (always!)
- Public interface / API
- Configuration options
- Code example
- Which features/endpoints use this component — link to their pages

## Configuration
Environment variables, config files, settings that control this component.

## How Other Components Use This
Cross-references to features, endpoints, and integrations that depend on this. \
Link to their pages from the sitemap.

## Edge Cases & Failure Modes
What can go wrong, how errors are handled, known limitations.

## Diagrams
Include all required diagrams: {required_diagrams}. Use Mermaid.

## Quick Reference
Include a compact reference table of the most important public functions, classes, \
and interfaces in this component. Columns: Symbol, File Path, Signature or Key Args, \
and What It Does (one line). Include 5-15 entries.

## See Also
Related system, feature, and integration pages.

Reference EVERY file path. This is foundational documentation — be thorough.
"""


DATABASE_SYSTEM_V2 = """\
Generate **database and schema documentation** for the data model layer.

Page: {title}
Description: {page_description}
Bucket type: system (database)
Required sections: {required_sections}
Required diagrams: {required_diagrams}

ORM/Schema files and their contents:
{source_context}
""" + CROSS_LINK_SECTION + """

Write comprehensive database documentation following this mandatory outline:

# {title}

## Overview
What database(s) the project uses, the ORM/migration framework, and the overall \
data modelling approach. Link to the architecture page from the sitemap.

## Entity-Relationship Diagram
Include a **Mermaid erDiagram** showing ALL tables/models, their key columns, and \
relationships (one-to-one, one-to-many, many-to-many). This is the single most \
important artefact on this page — make it complete.

## Tables / Models

For EACH model or table (sorted by importance):

### `ModelName` (`path/to/model.py:line`)

| Column / Field | Type | Constraints | Description |
|---------------|------|-------------|-------------|
| id | PK / UUID | NOT NULL | Primary key |
| ... | ... | ... | ... |

**Relationships:**
- `belongs_to` User (FK: user_id)
- `has_many` OrderItems

**Indexes:** list any declared indexes or unique constraints.

**Used by:** link to the feature and endpoint pages that read/write this model.

## Relationships Summary
A concise table or prose summary of every FK / M2M relationship in the schema. \
Include a **Mermaid classDiagram** if the ER diagram is very large.

## Migrations
How migrations are managed. Reference migration files. Note any manual or data \
migrations. Link to setup docs for running migrations.

## Query Patterns & Performance
Notable query patterns, N+1 risks, heavy joins, denormalisation choices. \
Reference the caching page from the sitemap if it exists.

## Configuration
Database connection settings, env vars, connection pooling, read replicas. \
Link to the Setup page from the sitemap.

## See Also
Related architecture, feature, and endpoint pages from the sitemap.

Reference EVERY file path. Include actual column types and constraints from the code.
"""


DATABASE_OVERVIEW_V2 = """\
Generate the **database overview page** for the data model layer.

Page: {title}
Description: {page_description}
Bucket type: system (database overview)
Required sections: {required_sections}
Required diagrams: {required_diagrams}

ORM/Schema files and their contents:
{source_context}
""" + CROSS_LINK_SECTION + """

Write the top-level database map for the repository.

# {title}

## Overview
Summarize the storage systems, ORM/schema technologies, and the overall data-model strategy.

## Schema Group Index
List every database subgroup page, what it owns, and when a developer should read it.

## High-Level ER Diagram
Include a **Mermaid erDiagram** that shows the major groups and cross-group relationships.

## Cross-Group Relationships
Explain the important foreign-key or logical relationships that cross subgroup boundaries.

## Migrations & Query Patterns
Summarize migration strategy and link to any deeper migrations/query page if present.

## Configuration
Document connection/configuration knobs that affect the data layer.

## See Also
Link to subgroup pages, architecture, runtime, and feature pages that depend on the data layer.

This page is a map and index. Do not try to fully document every table here if subgroup pages exist.
"""


DATABASE_GROUP_V2 = """\
Generate a **complete database subgroup page** for one bounded part of the schema.

Page: {title}
Description: {page_description}
Bucket type: system (database group)
Required sections: {required_sections}
Required diagrams: {required_diagrams}

ORM/Schema files and their contents:
{source_context}
""" + CROSS_LINK_SECTION + """

Write a complete, deeply grounded page for this subgroup only.

# {title}

## Overview
Explain what this schema group owns and how it fits into the larger data model.

## Models / Tables
For EACH assigned model or table, document fields, types, constraints, relationships, and indexes.

## Relationship Diagram
Include a **complete Mermaid erDiagram or classDiagram** for this subgroup.

## Used By
Explain which features, endpoints, runtime jobs, or GraphQL interfaces read/write this subgroup.

## External Relationships
List relationships to models documented on other subgroup pages and link to them.

## Query Patterns & Performance
Document notable query behavior, joins, caches, denormalisation, or hotspots visible in the evidence.

## See Also
Link back to the database overview and any related feature/runtime/interface pages.

This page must be complete for its assigned subgroup; do not defer core model detail to other pages.
"""


RUNTIME_SYSTEM_V2 = """\
Generate **runtime and background-jobs documentation** for asynchronous processing.

Page: {title}
Description: {page_description}
Bucket type: system (runtime)
Required sections: {required_sections}
Required diagrams: {required_diagrams}

Runtime/source evidence:
{source_context}
""" + CROSS_LINK_SECTION + """

# {title}

## Overview
Explain the runtime surfaces covered here and why they matter operationally.

## Runtime Surfaces
Document the detected tasks, schedulers, queues, and realtime consumers with exact file references.

## Execution Map
Include a **Mermaid flowchart or sequence diagram** showing how requests or schedules trigger background/realtime work.

## Operational Notes
Document retries, schedules, failure modes, idempotency hints, and ownership boundaries visible in the evidence.

## See Also
Link to related feature, endpoint, database, and setup pages.
"""


GRAPHQL_SYSTEM_V2 = """\
Generate **GraphQL interface documentation** grounded in schema and resolver code.

Page: {title}
Description: {page_description}
Bucket type: interface (GraphQL)
Required sections: {required_sections}
Required diagrams: {required_diagrams}

Source files and evidence:
{source_context}
""" + CROSS_LINK_SECTION + """

# {title}

## Overview
Explain what GraphQL surfaces exist and how they relate to the rest of the repository.

## Schema Roots
Document query, mutation, and schema root types with exact file references.

## Resolvers & Mutations
Explain resolver or mutation behavior, linked helpers, and related data/runtime surfaces.

## Data Dependencies
Link to the database or feature pages that own the underlying models and workflows.

## See Also
Link to related API, database, runtime, and feature pages.
"""


ENDPOINT_REF_V2 = """\
Generate a **single-endpoint API reference page** for one specific API endpoint.

Write this as a narrative endpoint reference page that can stand on its own in MDX.
If the provided sitemap includes a canonical `/api/...` page, treat that interactive \
OpenAPI page as the primary reference and use this page to explain the handler flow, \
validation, side effects, and implementation details.

Page: {title}
Description: {page_description}
Bucket type: endpoint_ref
Required sections: {required_sections}
Required diagrams: {required_diagrams}

Endpoint details:
{endpoints_detail}

Handler source code and evidence:
{source_context}

{openapi_context}
""" + CROSS_LINK_SECTION + """

Write the page body directly — do NOT emit YAML frontmatter or interactive API JSX components.
Only assert route shapes, auth modes, validation rules, response fields, side effects, and
health/ops claims that are explicitly supported by the provided evidence. If evidence is partial,
say so clearly.

## Overview
One paragraph describing what this endpoint does, when to use it, and any important \
behavioral notes. Reference the handler function and its file path. \
Link to the auth/middleware page if auth is required.

## Handler Flow
Include a **Mermaid sequence diagram** showing the exact request lifecycle:
client → middleware → validation → handler → service → DB → response.
Reference the exact handler function name and file path (`handlerName()` in `path/to/file.ts:42`).

## Parameters

Document parameters with a markdown table:

| Location | Name | Type | Required | Description |
|----------|------|------|----------|-------------|
| path | id | string | yes | Unique resource identifier |
| query | page | integer | no | Page number |

If the body schema is nested, add a short subsection for nested properties below the table.

## Response

Document the success response with a markdown table:

| Field | Type | Description |
|-------|------|-------------|
| id | string | Unique identifier of the created resource |
| status | string | Current status |

After the response field table, include a realistic request and response example:
```
```bash
curl -X POST https://api.example.com/v1/orders \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{{"product_id": "prod_123", "quantity": 2}}'
```

```json
{{
  "id": "ord_abc",
  "status": "pending",
  "total": 2999
}}
```
```

## Business Logic & Branching
Document EVERY conditional branch in the handler. For each `if/else` or guard clause:
- What condition is checked (feature flag, user state, request field)
- What happens in each branch
- What error is raised or what alternate flow is triggered
Include feature flags (e.g., Redis flags, config toggles), user state checks (blocked, \
2FA enabled, subscription tier), and any version/platform-specific behavior. \
If the handler calls helper functions, explain what each helper does using the resolved \
helper source if available.

If the handler uses status enums, role constants, or type values that determine behavior, \
list the valid values and what each means for this endpoint's response or side effects.

## Validation
What validations run (schema validation, auth checks, business rules). \
Reference exact validator functions and files. Document the specific validation logic — \
not just "validates email" but "uses `email_validation()` from `utils/hooks.py` which \
checks format via regex".

## Side Effects
Database writes, cache updates, events, queue jobs, or webhooks triggered by this endpoint. \
Reference exact functions and files. Include async tasks (Celery jobs), analytics events \
(Facebook events, tracking pixels), and cache invalidations.

## Error Responses
Use a clean table:
| Status | Condition |
|--------|-----------|
| 400 | ... |
| 401 | ... |
| 404 | ... |

## Related Endpoints
Link to other endpoint_ref pages for related endpoints (same resource family). \
Link to the parent endpoint bucket page for the full family overview.

Reference EVERY file path. Use the actual handler function names from the source code.
"""


TRAINING_BUCKET_V2 = """\
Generate **training pipeline documentation** for a specific training component.

Page: {title}
Description: {page_description}
Required sections: {required_sections}
Required diagrams: {required_diagrams}

Source files and evidence:
{source_context}
""" + CROSS_LINK_SECTION + """

Write comprehensive training documentation following this mandatory outline:

# {title}

## Overview
What this training component does, its role in the training pipeline, and when it runs.

## Training Loop
Include a **Mermaid flowchart** showing the training flow. Cover forward pass, \
loss computation, backward pass, optimizer step, and any hooks.

## Hyperparameters & Configuration
All configurable parameters with defaults, ranges, and effects. Use a markdown table.

## Data Flow
Include a **Mermaid diagram** showing data movement: dataset → dataloader → \
model → loss → optimizer. Reference exact file paths.

## Implementation Details
For each key function/class: what it does, file path, signature, and important \
internal mechanics. Include code examples from the actual source.

## Distributed Training
If applicable: how this component works in multi-GPU/multi-node settings. \
Communication patterns, gradient synchronization, data parallelism.

## Checkpointing & Recovery
How state is saved and restored. Checkpoint format, resume logic.

## Performance Notes
Known bottlenecks, optimization tips, memory usage patterns.

## See Also
Related training, model, and evaluation pages.

Reference EVERY file path. Include all required diagrams: {required_diagrams}.
"""


ARCHITECTURE_COMPONENT_V2 = """\
Generate **component deep-dive documentation** for a specific architectural component.

Page: {title}
Description: {page_description}
Required sections: {required_sections}
Required diagrams: {required_diagrams}

Source files and evidence:
{source_context}
""" + CROSS_LINK_SECTION + """

Write comprehensive component documentation following this mandatory outline:

# {title}

## Overview
What this component is, why it exists, and its role in the system. \
One paragraph, precise.

## Files Covered
Include a summary table of all source files in this component. Columns: \
File Path, Role, Key Symbols, and Responsibility (one line). Skip if fewer than 3 files.

## Design & Purpose
Include a **Mermaid diagram** (class, flowchart, or sequence — whichever fits best) \
showing this component's structure or data flow. Explain key design decisions.

## Implementation Details
For each important class/function:
- Exact file path and line number
- Signature and parameters
- Internal mechanics — how it actually works, not just what it does
- Code examples from the real source

## Public Interface
The API surface that other components use. Parameters, return types, exceptions.

## Internal Mechanics
Algorithms, data structures, state management. The details someone would need \
to modify this component.

## How It's Used
Which other components depend on this one. Link to their pages. \
Show call patterns with brief code snippets.

## Configuration
Settings that affect this component's behavior.

## Performance Considerations
Complexity, memory usage, known hotspots, optimization opportunities.

## See Also
Related component, feature, and system pages.

Reference EVERY file path. Include all required diagrams: {required_diagrams}.
"""


DATA_PIPELINE_V2 = """\
Generate **data pipeline documentation** for a specific pipeline stage or data component.

Page: {title}
Description: {page_description}
Required sections: {required_sections}
Required diagrams: {required_diagrams}

Source files and evidence:
{source_context}
""" + CROSS_LINK_SECTION + """

Write comprehensive pipeline documentation following this mandatory outline:

# {title}

## Overview
What this pipeline stage does, its inputs and outputs, and where it fits in the \
overall data flow.

## Input / Output Schema
Describe the data format entering and leaving this stage. Use tables or code \
blocks for schema definitions.

## Processing Logic
Include a **Mermaid flowchart** showing the transform steps. For each step: \
what it does, which function handles it (with file path), and error conditions.

## Error Handling & Recovery
What happens when input is malformed, when external sources fail, retry logic, \
dead letter handling.

## Configuration
Tunable parameters: batch sizes, parallelism, timeouts, feature flags.

## Monitoring & Observability
Metrics emitted, log patterns, how to debug pipeline failures.

## See Also
Related pipeline stages, data model pages, and integration pages.

Reference EVERY file path. Include all required diagrams: {required_diagrams}.
"""


RESEARCH_CONTEXT_V2 = """\
Generate **research context documentation** from repository notes, READMEs, glossaries, and experiment documents.

Page: {title}
Description: {page_description}
Required sections: {required_sections}
Required diagrams: {required_diagrams}

Source files and evidence:
{source_context}
""" + CROSS_LINK_SECTION + """

Write a grounded documentation page using only the supplied repository context.

# {title}

## Overview
What this context page covers and why it matters to understanding the repository.

## Key Findings or Terms
Summarize the main ideas, experiments, glossary entries, or design decisions from the source material.

## Timeline / References
List the relevant notes, markdown files, notebooks, or changelog entries with exact file paths.

## Relevance to the Codebase
Explain which model, training, evaluation, runtime, or architecture pages this context informs.

## See Also
Link to related architecture, training, evaluation, or glossary pages.

Reference EVERY file path. Do not invent history or experiments that are not present in the source material.
"""


START_HERE_INDEX_V2 = """
You are writing the **"Start Here"** landing page for a developer who has just joined the team
and is opening this documentation for the very first time.

They have ZERO prior knowledge of this codebase. Your job is to give them a confident
orientation in 5 minutes of reading so they can navigate the rest of the docs on their own.

Repository evidence:
{source_context}

Sitemap context:
{sitemap_context}

Dependency and sibling links:
{dependency_links}

Required sections from the planner:
{required_sections}

Required diagrams from the planner:
{required_diagrams}

Coverage targets:
{coverage_targets}

## Required sections (write all of them)

### What This Service Does
One plain-English paragraph. What problem does this service solve? Who depends on it?
What would break if it went down?

### Who Uses This Service
Bullet list: other internal services, frontend clients, external APIs, and human operators.
Link each to its documentation page if it appears in the sitemap.

### Technology At a Glance
A brief table: Language, Framework, Primary DB, Cache/Queue, Key integrations.
Derive only from evidence — no invented entries.

### How to Get Running Locally
Reference the Setup page with a `<Callout>`:
```mdx
<Callout type="info">
  See [Local Setup](/local-development-setup) for the complete step-by-step guide, including all required
  environment variables and service dependencies.
</Callout>
```

### Reading Order for Different Roles
A `<Tabs>` block with tabs for at least: Backend Developer, DevOps/Infra, and New Tech Lead.
Each tab lists 4–6 documentation pages in the order they should be read, with brief (one-line)
explanations of why each page matters for that role.

### Architecture in One Diagram
A Mermaid flowchart showing the top-level components (HTTP layer → business layer → data layer)
and the 2–3 most important external integrations. Keep it readable — max 12 nodes.

### The 5 Files Every Developer Must Know
List exactly 5 files (use real paths from evidence). For each file: what it does, why it matters,
and what will go wrong if you touch it carelessly.

### Day-1 Questions to Ask Your Team
A short bullet list (5–8 items) of questions that are NOT answerable from code alone:
deployment topology, on-call rotation, external credentials, data retention policies, etc.

## Hard rules
- Never invent file paths, endpoint URLs, or integration names not present in evidence.
- All file references must use backtick paths.
- Every concept that has a documentation page must be linked the first time it appears.
- Do NOT duplicate setup instructions — link to the Setup page instead.
- Write in second person ("you will", "your first step").
- Tone: warm, direct, practical. Not corporate.
"""

DOMAIN_GLOSSARY_V2 = """
You are writing the **Domain Glossary** — a reference page that translates the codebase's
internal vocabulary into plain English for developers who are new to this business domain.

This page is one of the most valuable pages in the entire documentation set. A new engineer
who does not know what "Vinculum", "soul_artist", "exclusive_user", or "TSS money" means will
be blocked from understanding any other page until they read this one.

Repository evidence:
{source_context}

OpenAPI and interface context:
{openapi_context}

Sitemap context:
{sitemap_context}

Dependency and sibling links:
{dependency_links}

Required sections from the planner:
{required_sections}

Required diagrams from the planner:
{required_diagrams}

Coverage targets:
{coverage_targets}

## Required sections (write all of them)

### How to Use This Glossary
Two sentences: what this page covers and how it relates to the rest of the docs.

### Domain Terms (A–Z or grouped by domain)
For EVERY non-obvious term found in the evidence — model names, field names that carry
business meaning, status codes, enum values, feature-flag names, integration names,
internal system names — write an entry in this format:

**`TermName`** *(source: `path/to/file.py` line N)*
> Plain-English definition. What does this term mean in this business context?
> How does it relate to other terms? Link to the documentation page where it is most
> relevant.

Group entries by domain if there are more than 15 terms (e.g., Orders, Users, Inventory,
Payments, Integrations).

### Status Codes and State Machines
For every status field (order_status, refund_status, return_status, etc.) found in evidence:
- Table with columns: Status Value | Meaning | Next Valid Statuses | Triggering Event
- A Mermaid state diagram if the state machine has more than 3 states.

### Integration Name Map
A table mapping internal code names to their real-world counterparts:
| Code Name | Real System | What It Does |
Link each to its integration documentation page.

### Abbreviations and Acronyms
Any abbreviations used in the codebase that are NOT self-evident.

## Hard rules
- ONLY document terms that appear in the evidence (code, models, constants, config).
- Do not invent definitions — derive everything from field names, docstrings, comments, and usage context.
- If a term's meaning is unclear from evidence, say so explicitly: *"Exact meaning unclear from static analysis — ask the team."*
- Every term should link to its most relevant documentation page.
- File references must use backtick paths.
"""

DEBUG_RUNBOOK_V2 = """
You are writing the **Debugging & Observability** runbook — a practical guide for when
things go wrong in production or development.

This page is for developers who need to diagnose a live issue RIGHT NOW. Write it like
a runbook, not a tutorial. Be direct, specific, and operational.

Repository evidence:
{source_context}

OpenAPI and interface context:
{openapi_context}

Sitemap context:
{sitemap_context}

Dependency and sibling links:
{dependency_links}

Required sections from the planner:
{required_sections}

Required diagrams from the planner:
{required_diagrams}

Coverage targets:
{coverage_targets}

## Required sections (write all of them)

### Quick Diagnostic Checklist
A numbered checklist of the first 5–8 things to check when something is broken.
Base this entirely on the observability signals in the evidence (health endpoints,
log levels, queue state, Redis keys, monitoring hooks).

### Health Endpoints
For every health/readiness endpoint found in evidence:
- Path, what it checks, expected response, what a failure means.
- Example curl command.

### Log Locations and What to Look For
For each major subsystem (API layer, background tasks, database, cache):
- Where logs are written (from evidence — don't invent).
- Log level used for errors vs. warnings vs. info.
- Key log message patterns to grep for when debugging that subsystem.
- Any structured fields logged (request_id, user_id, order_id, etc.).

### Background Task Debugging
For each Celery queue or Node.js scheduler found in evidence:
- Queue name and what tasks it processes.
- How to check if a task is stuck (e.g., Flower URL, Redis queue key).
- How to manually retry or cancel a task.
- Common failure reasons for this queue.

### Cache and Redis Key Reference
For every Redis key pattern found in evidence:
- Key pattern (with variable parts noted as `{{variable}}`).
- What it stores, TTL if detectable.
- When it is set/invalidated.
- How to inspect or flush it for debugging.

### Common Failure Modes
For each major feature area documented in evidence, describe:
- The most common failure mode.
- Its symptom (what the user sees, what the logs show).
- The root cause pattern.
- The fix.

Format as a `<Accordions>` component, one accordion per failure mode.

### Exception Handling Map
For each distinct exception type handled in the codebase (from evidence):
- Where it is raised and where it is caught.
- What HTTP status / user-facing response it produces.
- Whether it is retried or logged.

### Monitoring and Metrics
If monitoring hooks (Prometheus, NewRelic, Sentry, etc.) are found in evidence:
- What metrics/events are instrumented.
- Where to find dashboards (if config files reveal URLs or endpoint names).
- Key alerts and what they mean.

## Hard rules
- Every command, path, key, and endpoint must come from evidence. Never invent.
- If something cannot be determined from static analysis (e.g., dashboard URLs),
  say: *"Check with the team — not determinable from source."*
- Use `<Callout type="warn">` for anything that could cause data loss if done wrong.
- Write in imperative second person ("Run this", "Check this key", "If you see X, do Y").
- Include at least one Mermaid sequence or flowchart diagram showing the debug flow for
  the most common production issue.
"""

START_HERE_SETUP_V2 = """
You are writing the **Local Development Setup** guide — the definitive step-by-step
guide for getting this service running on a new developer machine.

This page must be complete enough that a developer with no prior context can follow it
from a clean machine to a running local environment WITHOUT asking anyone for help.

Repository evidence:
{source_context}

OpenAPI and interface context:
{openapi_context}

Sitemap context:
{sitemap_context}

Dependency and sibling links:
{dependency_links}

Required sections from the planner:
{required_sections}

Required diagrams from the planner:
{required_diagrams}

Coverage targets:
{coverage_targets}

## Required sections (write all of them)

### Prerequisites
Table: Tool | Required Version | Install Command. Include only tools evidenced in the codebase.

### Clone and Install
Exact commands for cloning, installing dependencies, and setting up the virtual environment
or node_modules. Use `<Steps>` component.

### Environment Variables
For EVERY environment variable referenced in the codebase (from .env.example, os.environ,
process.env, settings files):

A table with columns: Variable | Required | Default | Description | Example Value

Then a full `.env.example` block the developer can copy-paste and fill in.

### Database Setup
Step-by-step: create DB, run migrations, load fixtures/seeds if applicable.
Include exact commands from evidence.

### External Service Dependencies
For each integration (from evidence): what it needs locally (mock, local instance, or real
credentials), and how to set it up. Be honest if something requires real credentials.

### Starting the Service
Exact command(s) to start the server, background workers, and any required sidecars.
Use `<Steps>` and note expected output so the developer knows it worked.

### Verifying It Works
2–3 test requests or health checks to confirm the service is running correctly.
Include exact curl or browser instructions.

### Troubleshooting Common Setup Issues
`<Accordions>` with the top 5 setup failure modes and their fixes.
Derive from evidence: missing env vars, migration failures, dependency conflicts, port conflicts.

## Hard rules
- ONLY include commands and variables that are evidenced.
- Never invent env var names, migration commands, or service names.
- If an exact command is not determinable, write a placeholder and note: *"Confirm with team."*
- All file references use backtick paths.
"""
