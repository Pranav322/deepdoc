"""V2 prompt templates — page-type-specific with mandatory diagrams + file references
+ cross-page linking + dependency-driven navigation.

Every prompt enforces:
1. Mermaid diagrams wherever relevant (class, sequence, flowchart, ER)
2. File path in backticks whenever a function/class/type is mentioned
3. Developer-first, detailed documentation
4. Cross-page links using the sitemap provided in each prompt
5. Dependency-driven linking — link to pages that cover imported modules
"""

# ─────────────────────────────────────────────────────────────────────────────
# Shared system prompt
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_V2 = """\
You are a senior documentation engineer writing developer-focused documentation \
for a software project. Your goal is interconnected, navigable documentation — \
not isolated pages.

HARD RULES (never skip any of these):
1. **Mermaid diagrams**: Include at least one Mermaid diagram per page where it adds value. \
Use the right type: flowchart for flows, classDiagram for class relationships, \
sequenceDiagram for request/response flows, erDiagram for data models. \
Wrap in ```mermaid code blocks. For flowchart/graph nodes, quote labels with special \
characters using `A["label (with parens)"]`. For sequence diagrams, use \
`participant A as Label`, not flowchart node syntax. For classDiagram and \
stateDiagram-v2, use simple identifiers for class/state names and keep display \
labels free of flowchart-only syntax.
2. **File references**: EVERY time you mention a function, class, method, type, or constant, \
include the file path in backticks like: `getUserById()` (`src/services/userService.ts:42`). \
Never mention code without saying where it lives. Only reference file paths that exist in \
the source context — never invent paths.
3. **Developer perspective**: Write for a dev who just joined the team. Be specific, practical, \
and detailed. No generic filler.
4. **Code examples**: Include realistic code snippets showing actual usage, not toy examples.
5. **Edge cases**: Mention gotchas, error handling, and non-obvious behavior.
6. **Business logic depth**: Document ALL conditional branches, feature flags, guard clauses, \
and validation checks you find in the source code. If a handler checks `is_block`, `is_two_fa`, \
a Redis feature flag, or any other conditional — document it explicitly. Name the flag/field, \
explain when each branch triggers, and what the user-facing behavior is. Do NOT gloss over \
branching logic — every `if/else` in a handler is a business rule that developers need to know about.
7. **Helper functions**: When the source calls utility functions (e.g., `create_token()`, \
`sync_cart()`, `getAddresses()`, `data_sanitization()`), explain what they do, where they live, \
and what they return. If helper source is provided in the "Resolved Helper Functions" section, \
use it to give accurate descriptions. Document SQL queries or ORM patterns you see.
8. **Evidence hierarchy & uncertainty**: Runtime/source evidence is authoritative. \
If "Internal Docs Context" or README/design summaries are provided, use them only to enrich \
high-level explanation and onboarding context — never let them override code truth. \
If the evidence is partial, say so plainly instead of inventing exact paths, payloads, \
feature flags, auth modes, health endpoints, or deployment topology.
9. **Cross-page links**: This is a LINKED documentation site. Whenever you mention a concept, \
module, service, API, or feature that is documented in another page, you MUST link to it using \
standard Markdown: `[Page Title](/page-slug)`. \
Every prompt includes a sitemap of all available pages — use it. \
If a page is listed in "Dependency Links", you MUST link to it at least once where it is \
first mentioned. Think of each page as part of a wiki, not a standalone document.
10. **Fumadocs UI components**: This documentation site runs on Fumadocs. Use its rich \
JSX components to make pages beautiful and scannable. Never use `:::type` admonition syntax.

**Callouts** — for tips, warnings, notes, gotchas:
```
<Callout>This behaviour changed in v2.</Callout>
<Callout type="warn">Running this in production will drop all existing sessions.</Callout>
<Callout type="info">Use batch processing for large datasets — it's 10x faster.</Callout>
<Callout>This module is auto-generated. Do not edit manually.</Callout>
<Callout>All three environment variables must be set before starting.</Callout>
```

**Steps** — for setup guides, workflows, any ordered procedure (use instead of a numbered list):
```
<Steps>
  <Step>
    <h3>Install dependencies</h3>
    Run `npm install` from the project root.
  </Step>
  <Step>
    <h3>Configure environment</h3>
    Copy `.env.example` to `.env` and fill in `DATABASE_URL` and `JWT_SECRET`.
  </Step>
  <Step>
    <h3>Start the server</h3>
    Run `npm run dev`. The API will be available at `http://localhost:3000`.
  </Step>
</Steps>
```

**Tabs** — for showing the same concept in multiple languages or environments:
```
<Tabs items={['Node.js', 'Python']}>
  <Tab value="Node.js">
    ```javascript
    const client = new ApiClient({ apiKey: process.env.API_KEY });
    ```
  </Tab>
  <Tab value="Python">
    ```python
    client = ApiClient(api_key=os.environ["API_KEY"])
    ```
  </Tab>
</Tabs>
```

**Cards** — for feature overviews, linking to related pages, listing capabilities. \
Use at the end of overview/architecture pages to create a visual navigation grid:
```
<Cards>
  <Card title="Authentication" href="/auth">
    JWT-based auth with refresh token rotation.
  </Card>
  <Card title="Database Layer" href="/database">
    PostgreSQL schema and migration strategy.
  </Card>
</Cards>
```

**Accordion** — for FAQ sections, detailed option references, or collapsible details:
```
<Accordions type="single">
  <Accordion title="Why does the worker restart every 30 seconds?">
    The heartbeat timeout is set in `config/worker.yaml`. Increase `heartbeat_interval`
    to reduce restarts on slow jobs.
  </Accordion>
</Accordions>
```

**When to use each**:
- Use `<Steps>` for ANY setup, installation, or ordered workflow — never a numbered list.
- Inside `<Step>`, use HTML headings like `<h3>Install dependencies</h3>`, not markdown headings like `### Install dependencies`.
- Use `<Cards>` at the end of overview and architecture pages to link to sub-pages.
- Use `<Tabs>` when showing the same thing in multiple languages, environments, or configs.
- Use `<Accordions>` and `<Accordion>` for reference material with many options or a FAQ section.
- Use callouts (`<Callout>`, `<Callout type="warn">`, etc.) liberally — they draw the eye to important info.

11. **Grounded snippets over invented examples**: When showing code in documentation, \
prefer quoting short, targeted snippets verbatim from the provided source evidence. \
Use the exact function signatures, variable names, constants, and branching terms from \
the source files. Only write synthetic examples when the source does not already demonstrate \
the behavior — and label synthetic code clearly (e.g. "Example usage:") so developers know \
it is not a direct quote. Never paraphrase a function signature or invent import paths.
12. **Constants, types, and state values**: When the evidence contains enums, status \
constants, type definitions, config schemas, or state machine values that affect behavior \
or contracts, document them explicitly. Surface valid values, default states, and \
transition rules where they appear in the source. Do not dump every constant — only those \
that affect runtime behavior, API contracts, or integration interfaces.
13. **Environment variables and config knobs**: When the evidence shows `os.environ`, \
`os.getenv`, `process.env`, or framework config lookups, document the actual variable \
names, whether they are required, their defaults if visible, and what behavior they gate. \
Render them in a table where there are 3+ variables. Do not invent env vars not present \
in the evidence.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Shared cross-linking footer added to every prompt
# ─────────────────────────────────────────────────────────────────────────────

CROSS_LINK_SECTION = """\

---

## Documentation Sitemap (for cross-linking)
Use these to link to other pages wherever relevant. Syntax: `[Title](/slug)`

{sitemap_context}

{dependency_links}
"""


# ─────────────────────────────────────────────────────────────────────────────
# Page-type prompts
# ─────────────────────────────────────────────────────────────────────────────

OVERVIEW_V2 = """\
Generate the **project overview and system guide** page.

Page: {title}
Project: {project_name}
Description: {page_description}
Languages: {languages}
Frameworks: {frameworks}
Required sections: {required_sections}
Required diagrams: {required_diagrams}
Coverage targets: {coverage_targets}

Repository-wide architecture and source evidence:
{source_context}
""" + CROSS_LINK_SECTION + """

Write the single best starting page for a new internal developer. This page must explain
the system from start to finish, not just introduce it. It should help someone understand:
- what the system does
- how requests and background work flow through it
- which major subsystems own which responsibilities
- which integrations matter
- where data lives
- how to get productive quickly
- which pages to read next for deeper detail

Assume this is the first page most people will read.
Use "Internal Docs Context" only as supporting architectural/onboarding context. If repo docs
and code differ, follow the code and say the docs appear outdated rather than picking one silently.

# {title}

Short tagline (1 sentence) describing what the project does.

## What This Does
2-3 specific sentences on the system's purpose, scope, and who/what it serves.

## Architecture Overview
Include a **Mermaid flowchart** showing the high-level architecture:
- Major components/services
- How they communicate
- External dependencies (databases, APIs, queues)

Link to each component's dedicated documentation page from the sitemap above \
wherever you describe it.

## End-to-End Runtime Flow
Explain the main request or processing lifecycle from entry point to completion.
If the system has multiple major flows, cover the most important 2-4 flows.
Include a **Mermaid sequence diagram** or flowchart for the primary flow.
Tie each step back to the actual files and related pages.

## Major Subsystems
Describe the major internal areas of the system as a map:
- what each subsystem owns
- which files or modules anchor it
- which integrations or data models it depends on
- which page to read for the deep dive

## Key Files To Know First
Include a table of the 8-15 most important files a new developer should be aware of. \
For each file, show: file path, role (e.g. entry point, router, core service, config), \
and a one-line summary of what it does. Sort by importance, not alphabetically. \
This table should help someone know where to look first when debugging or extending the system.

## Tech Stack
List the actual technologies, frameworks, runtime model, storage, messaging, and deployment
tools where detectable. If a framework is clearly central, say how it shapes the architecture.

## Project Structure
Map the directory layout to what each part does. Reference actual directories. \
For each major section, link to its documentation page from the sitemap.

## Data, State, And Integrations
Summarize:
- the key models or persistent state
- important caches, queues, or scheduled jobs
- background workers, cron tasks, or async job processors and when they run
- external systems and what role they play

Link to the relevant database, integration, and operations pages from the sitemap.

## Key Concepts And Gotchas
The 3-7 most important things a new dev must understand. For each:
- Reference the actual files that implement it
- Link to the relevant documentation page from the sitemap
- Mention non-obvious behavior or operational gotchas where relevant

## Getting Started
Use a `<Steps>` component (not a numbered list) for the installation and run steps. \
Infer from config files. Link to the Setup page from the sitemap if it exists.

## How To Read This Docs Set
Tell a new joiner which pages to read next, in order, depending on their goal:
- understanding architecture
- working on runtime/API behavior
- working on integrations
- working on data models
- local setup and debugging

## Explore the Docs
End the page with a `<Cards>` block that links to the most important pages \
from the sitemap. Each `<Card>` must have a `title`, an `href` (the `/slug`), \
and a 1-sentence description.

Be detailed and specific. Reference actual file paths everywhere. \
This overview is the entry point and must feel substantial, architectural, and actionable.
"""


ARCHITECTURE_V2 = """\
Generate an **architecture deep-dive** page.

Page: {title}
Description: {page_description}

Source files and their symbols:
{source_context}
""" + CROSS_LINK_SECTION + """

Write detailed architecture documentation:

# {title}

## System Design
Include a **Mermaid diagram** showing the system architecture (flowchart or C4-style). \
Label each component. Where a component is documented in another page, link to it.

## Component Breakdown
For each major component:
- What it does
- Key files (with paths)
- Public interfaces
- Dependencies — link to pages that document those dependencies

Include a **class diagram** or **module dependency diagram** (Mermaid) showing relationships.

## Data Flow
How data moves through the system. Include a **sequence diagram** for the most important flow. \
Link to pages that implement each step.

## Design Decisions
Notable patterns, trade-offs, or architectural choices. Why things are structured this way.

## Error Handling Strategy
How errors propagate through the system. Reference error handling files.

Reference file paths for EVERY function, class, and module mentioned. \
Link to related pages throughout.
"""


GUIDE_V2 = """\
Generate a **developer guide** page.

Page: {title}
Description: {page_description}

Source files and their symbols:
{source_context}
""" + CROSS_LINK_SECTION + """

Write a detailed guide:

# {title}

## Overview
What this part of the system does and why it matters. \
Link to related pages (architecture, API reference, modules) from the sitemap above.

## How It Works
Step-by-step explanation with a **Mermaid flowchart or sequence diagram** showing the flow. \
For each step that touches another documented module, link to that module's page.

## Key Components
For each important function/class:
- What it does
- Parameters / inputs
- Return values / outputs
- File location (always!)
- Code example
- Links to related pages where this component is used or depends on

## Configuration
Any config options, environment variables, or settings that affect behavior. \
Link to the Setup page if it exists.

## Common Patterns
How to use this in practice. Show realistic code examples. \
Reference other pages where patterns from this module are used.

## Gotchas & Edge Cases
Things that might trip up a developer. Non-obvious behavior, limitations.

## See Also
List 3-5 related pages from the sitemap with one-line descriptions of how they relate.

Be thorough and reference every file path. Link generously throughout.
"""


MODULE_V2 = """\
Generate **module documentation** for a group of related files.

Page: {title}
Description: {page_description}

Source files and their contents:
{source_context}
""" + CROSS_LINK_SECTION + """

Write module documentation:

# {title}

## Overview
What this module/directory does and its role in the larger system. \
Link to the architecture page and any other pages that provide context.

Include a **Mermaid class diagram** showing the key classes/interfaces and their relationships. \
If classes reference types from other modules, note the dependency.

## Public API
For each exported function, class, method, or type:

### `functionName()` (`path/to/file.ts:line`)
- **Purpose**: what it does
- **Parameters**: name, type, description
- **Returns**: type and description
- **Used by**: link to pages that use this function (check the dependency links above)
- **Example**:
```
// realistic usage
```

## Internal Architecture
How the internals work. Include a **Mermaid diagram** if the module has complex internal flow.

## Dependencies
What this module depends on — link to pages from the sitemap that document those dependencies. \
What depends on this module — link to pages that import from here.

## Testing
How to test this module. Reference test files if they exist.

## See Also
Related pages from the sitemap that a developer reading this page should visit next.

Every function and class MUST include its file path. Link to dependency pages throughout.
"""


API_REFERENCE_V2 = """\
Generate **API reference documentation** for a group of endpoints.

Page: {title}
Description: {page_description}
Resource group: {resource_group}

Endpoints:
{endpoints_detail}

Handler source code:
{source_context}

{openapi_context}
""" + CROSS_LINK_SECTION + """

Write comprehensive API documentation:

# {title}

## Overview
What this API resource handles. Include a **Mermaid sequence diagram** showing a typical \
request flow (client → middleware → handler → database → response). \
Link to the middleware, models, and service pages from the sitemap where referenced.

## Authentication
Infer from middleware. Note if endpoints are public or require auth. \
Link to the auth/middleware documentation page if it exists in the sitemap.

## Endpoints

For EACH endpoint:

### `METHOD /path`
**Handler**: `handlerFunction()` (`file/path.ts:line`)

**Description**: What this endpoint does.

**Path Parameters**:
| Param | Type | Description |
|-------|------|-------------|

**Query Parameters** (if GET):
| Param | Type | Default | Description |
|-------|------|---------|-------------|

**Request Body** (if POST/PUT/PATCH):
```json
{{
  "field": "type — description"
}}
```

**Response** `200 OK`:
```json
{{
  "example": "response"
}}
```

**Error Responses**:
| Status | Description |
|--------|-------------|
| 400 | Bad request — when/why |
| 404 | Not found — when/why |

**Middleware**: list any auth/validation middleware — link to middleware page if in sitemap

---

## Data Models
Include a **Mermaid ER diagram** showing the data models used by these endpoints. \
Link to the database/models documentation page from the sitemap.

## See Also
Link to related API pages and module pages from the sitemap.

Be specific. Use the actual handler code to infer request/response shapes.
"""


SETUP_V2 = """\
Generate a **setup and installation guide**.

Page: {title}
Description: {page_description}

Config and setup files:
{source_context}
""" + CROSS_LINK_SECTION + """

Write a practical setup guide:

# {title}

## Prerequisites
What needs to be installed before starting. Be specific with versions.

## Installation
Step-by-step setup instructions. Infer from package.json, pyproject.toml, go.mod, etc.

## Configuration
Include a **Mermaid flowchart** showing the configuration flow if there are multiple steps \
or environment-dependent configs.

### Environment Variables
| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
(fill from .env.example or config files)

## Running Locally
Commands to start the project. Different modes (dev, test, prod) if applicable.

## Running with Docker
If Dockerfile exists, show docker commands.

## Verification
How to verify the setup is working correctly. \
Link to relevant module or API pages from the sitemap to explore next.

## Next Steps
After setup, link to 3-4 key pages from the sitemap a developer should read first.

Reference every config file by its path.
"""


DEPLOYMENT_V2 = """\
Generate **deployment documentation**.

Page: {title}
Description: {page_description}

Source files:
{source_context}
""" + CROSS_LINK_SECTION + """

Write deployment docs:

Do not invent deployment topology, orchestrators, health endpoints, or environment-specific
behavior that are not evidenced in the provided files. If the repo only partially documents
deployment, say what is explicit vs uncertain.

# {title}

## Deployment Architecture
Include a **Mermaid diagram** showing the deployment topology (services, databases, CDN, etc.)

## CI/CD Pipeline
Describe the pipeline. Include a **Mermaid flowchart** showing the stages.

## Build Process
How to build for production. Reference Dockerfile, build scripts, etc. \
Link to the Setup page from the sitemap.

## Environment Configuration
Production-specific configuration. What changes between environments. \
Link to the Setup page for base configuration details.

## Monitoring & Health Checks
How to verify the deployment is healthy.

## Rollback
How to rollback if something goes wrong.

## See Also
Link to Setup, Architecture, and any other relevant pages from the sitemap.

Reference all config and deployment file paths.
"""


INTEGRATION_V2 = """\
Generate **integration documentation** for external service connections.

Page: {title}
Description: {page_description}

Source files:
{source_context}
""" + CROSS_LINK_SECTION + """

Write integration docs:

# {title}

## Overview
What external services/APIs this integrates with and why. \
Link to related module and API pages from the sitemap.

## Connection Flow
Include a **Mermaid sequence diagram** showing the integration flow.

## Configuration
What credentials, URLs, and settings are needed. Link to Setup page from the sitemap.

## API Client
Document the client code used to talk to the external service. Reference file paths.

## Error Handling
How errors from the external service are handled. Retry logic, fallbacks.

## Testing
How to test this integration (mocks, test environments).

## See Also
Link to related pages from the sitemap.

Reference every file path. Link to relevant pages throughout.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Update prompt (for incremental updates)
# ─────────────────────────────────────────────────────────────────────────────

UPDATE_PAGE_V2 = """\
A documentation page needs to be updated because source files changed.

Page: {title} ({page_type})
Description: {page_description}

Previous documentation:
{previous_doc}

Changed files and their new content:
{changed_files_context}

All source files for this page (for full context):
{full_source_context}

Documentation sitemap (for cross-linking):
{sitemap_context}

{dependency_links}

Rules:
1. Preserve sections that are still accurate
2. Update sections affected by the changed files
3. Add documentation for new symbols/endpoints
4. Remove documentation for deleted symbols/endpoints
5. Update ALL Mermaid diagrams if the changes affect the flow
6. Ensure all file path references are still correct
7. Every function/class mentioned MUST have its file path
8. Maintain all cross-page links — update any that may be affected by the changes
9. Add new cross-page links where relevant based on the sitemap

Output the complete updated Markdown page.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Bucket-type prompts (v2 bucket planner)
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# Prompt selector
# ─────────────────────────────────────────────────────────────────────────────

# Legacy page-type mapping
PAGE_TYPE_PROMPTS = {
    "overview": OVERVIEW_V2,
    "architecture": ARCHITECTURE_V2,
    "guide": GUIDE_V2,
    "module": MODULE_V2,
    "api_reference": API_REFERENCE_V2,
    "setup": SETUP_V2,
    "deployment": DEPLOYMENT_V2,
    "integration": INTEGRATION_V2,
}

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


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint Ref (individual per-endpoint reference page)
# ─────────────────────────────────────────────────────────────────────────────

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


# Prompt style templates — keyed by prompt_style hint, NOT by bucket_type
PROMPT_STYLE_TEMPLATES = {
    "system": SYSTEM_BUCKET_V2,
    "feature": FEATURE_BUCKET_V2,
    "endpoint": ENDPOINT_BUCKET_V2,
    "endpoint_ref": ENDPOINT_REF_V2,
    "integration": INTEGRATION_BUCKET_V2,
    "database": DATABASE_SYSTEM_V2,
    "training": TRAINING_BUCKET_V2,
    "architecture_component": ARCHITECTURE_COMPONENT_V2,
    "data_pipeline": DATA_PIPELINE_V2,
    "research_context": RESEARCH_CONTEXT_V2,
    "general": GUIDE_V2,
}

# Legacy alias for backward compatibility
BUCKET_TYPE_PROMPTS = PROMPT_STYLE_TEMPLATES


def get_prompt_for_bucket(bucket) -> str:
    """Select writing-guidance template based on generation_hints.prompt_style.

    Works with DocBucket objects or anything with a generation_hints dict.
    """
    hints = getattr(bucket, "generation_hints", {}) or {}
    if hints.get("is_introduction_page"):
        return OVERVIEW_V2
    style = hints.get("prompt_style", "general")
    return PROMPT_STYLE_TEMPLATES.get(style, PROMPT_STYLE_TEMPLATES["general"])


def get_prompt_for_page_type(page_type: str) -> str:
    """Legacy compat — select template by page_type string.

    Falls back through: PROMPT_STYLE_TEMPLATES → PAGE_TYPE_PROMPTS → GUIDE_V2.
    """
    return PROMPT_STYLE_TEMPLATES.get(
        page_type, PAGE_TYPE_PROMPTS.get(page_type, GUIDE_V2)
    )
