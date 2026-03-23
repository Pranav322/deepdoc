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
Wrap in ```mermaid code blocks. Always quote labels that contain special characters \
(parentheses, brackets, colons, slashes) using double quotes: A["label (with parens)"].
2. **File references**: EVERY time you mention a function, class, method, type, or constant, \
include the file path in backticks like: `getUserById()` (`src/services/userService.ts:42`). \
Never mention code without saying where it lives. Only reference file paths that exist in \
the source context — never invent paths.
3. **Developer perspective**: Write for a dev who just joined the team. Be specific, practical, \
and detailed. No generic filler.
4. **Code examples**: Include realistic code snippets showing actual usage, not toy examples.
5. **Edge cases**: Mention gotchas, error handling, and non-obvious behavior.
6. **Cross-page links**: This is a LINKED documentation site. Whenever you mention a concept, \
module, service, API, or feature that is documented in another page, you MUST link to it using \
standard Markdown: `[Page Title](page-slug.md)`. \
Every prompt includes a sitemap of all available pages — use it. \
If a page is listed in "Dependency Links", you MUST link to it at least once where it is \
first mentioned. Think of each page as part of a wiki, not a standalone document.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Shared cross-linking footer added to every prompt
# ─────────────────────────────────────────────────────────────────────────────

CROSS_LINK_SECTION = """\

---

## Documentation Sitemap (for cross-linking)
Use these to link to other pages wherever relevant. Syntax: `[Title](slug.md)`

{sitemap_context}

{dependency_links}
"""


# ─────────────────────────────────────────────────────────────────────────────
# Page-type prompts
# ─────────────────────────────────────────────────────────────────────────────

OVERVIEW_V2 = """\
Generate the **project overview** page for: {project_name}

Description: {description}
Languages: {languages}
Frameworks: {frameworks}

Source files for context:
{source_context}
""" + CROSS_LINK_SECTION + """

Write a comprehensive overview with these sections:

# {project_name}

## What This Does
2-3 sentences on the project's purpose. Be specific, not vague.

## Architecture Overview
Include a **Mermaid flowchart** showing the high-level architecture:
- Major components/services
- How they communicate
- External dependencies (databases, APIs, queues)

Link to each component's dedicated documentation page from the sitemap above \
wherever you describe it.

## Tech Stack
List the actual technologies with versions where detectable.

## Project Structure
Map the directory layout to what each part does. Reference actual directories. \
For each major section, link to its documentation page from the sitemap.

## Key Concepts
The 3-5 most important things a new dev must understand. For each:
- Reference the actual files that implement it
- Link to the relevant documentation page from the sitemap

## Getting Started
Practical steps to clone, install, configure, and run. Infer from config files. \
Link to the Setup page from the sitemap if it exists.

Be detailed and specific. Reference actual file paths everywhere. \
This overview is the entry point — make sure every major feature links to its deep-dive page.
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

## Main Workflows
Step-by-step explanation of the primary workflows in this feature. \
Include a **Mermaid flowchart** for the main flow. \
For each step that involves another module or service, link to that page.

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

## State Transitions
How data/entity state changes through this feature. \
Include a **Mermaid state diagram** if applicable.

## Integrations Involved
External systems this feature talks to. For each:
- What integration and why
- Link to the integration's page from the sitemap if one exists

## Configuration & Environment
Config flags, feature toggles, env vars that affect this feature.

## Edge Cases & Failure Modes
Non-obvious behavior, error scenarios, race conditions, known limitations.

## Diagrams
Include all required diagrams: {required_diagrams}. \
Every diagram must be Mermaid and must reference actual code artifacts.

## See Also
Related feature, endpoint, and integration pages from the sitemap.

Reference EVERY file path. Link to related pages throughout. Be deep and specific.
"""


ENDPOINT_BUCKET_V2 = """\
Generate **endpoint documentation** for an API endpoint or endpoint family.

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

Write comprehensive endpoint documentation following this mandatory outline:

# {title}

## Route Overview
Summary of what this endpoint family handles. Include a **Mermaid sequence diagram** \
showing the typical request lifecycle (client → middleware → handler → service → DB → response).

## Authentication & Validation
What auth is required. What validation runs. \
Link to the middleware/auth page from the sitemap.

## Endpoints Detail

For EACH endpoint:

### `METHOD /path`
**Handler**: `handlerFunction()` (`file/path.ts:line`)

**Description**: What this endpoint does.

**Parameters**:
| Param | In | Type | Required | Description |
|-------|----|------|----------|-------------|

**Request Body** (if applicable):
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
| Status | Condition | Description |
|--------|-----------|-------------|

## Execution Flow
Step-by-step what happens when the request is processed. Reference actual functions and files.

## Downstream Calls
What other services, models, or external systems are called. \
Link to their documentation pages.

## Integrations Touched
External systems involved (payments, warehouses, delivery, etc.). \
Link to integration pages from the sitemap.

## State Changes
What database records, caches, or queues are modified.

## Async Side Effects
Background jobs, queue tasks, notifications triggered by this endpoint.

## Diagrams
Include all required diagrams. Use Mermaid. Reference actual code.

## See Also
Related endpoint, feature, and integration pages.

Reference EVERY file path. Be specific about request/response shapes.
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
Document payload structures, headers, authentication.

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

Write a complete single-endpoint reference page following this mandatory outline:

# {title}

## Summary
One-sentence description of what this endpoint does. Include the HTTP method and full path.

| Property | Value |
|----------|-------|
| Method | `GET/POST/PUT/DELETE` |
| Path | `/api/v1/...` |
| Auth | Required/Public |
| Rate Limit | ... |

## Request

### Path Parameters
| Param | Type | Required | Description |
|-------|------|----------|-------------|

### Query Parameters
| Param | Type | Default | Description |
|-------|------|---------|-------------|

### Request Body
```json
{{
  "field": "type — description"
}}
```

### Headers
| Header | Required | Description |
|--------|----------|-------------|

## Handler Flow
Include a **Mermaid sequence diagram** showing the full request lifecycle:
client → middleware → handler → service layer → database → response.
Reference the exact handler function and file path.

## Validation
What validations run on the request (schema validation, auth checks, business rules). \
Reference exact validator functions and files.

## Response

### Success Response `200 OK`
```json
{{
  "example": "response structure"
}}
```

### Error Responses
| Status | Code | Condition | Description |
|--------|------|-----------|-------------|

## Side Effects
What happens beyond the response: database writes, cache updates, events emitted, \
queue jobs dispatched, webhooks sent. Reference exact functions and files.

## Related Endpoints
Link to other endpoint_ref pages for related endpoints (same resource family). \
Link to the parent endpoint bucket page for the full family overview.

Reference EVERY file path. Use the actual handler function names from the source code.
"""


# New bucket-type mapping
BUCKET_TYPE_PROMPTS = {
    "system": SYSTEM_BUCKET_V2,
    "feature": FEATURE_BUCKET_V2,
    "endpoint": ENDPOINT_BUCKET_V2,
    "endpoint_ref": ENDPOINT_REF_V2,
    "integration": INTEGRATION_BUCKET_V2,
    "database": DATABASE_SYSTEM_V2,
}


def get_prompt_for_page_type(page_type: str) -> str:
    """Return the appropriate prompt template for a page type.

    Works for both legacy page_type values AND new bucket_type values.
    Also supports sub-type hints: e.g. slug containing 'database' or 'model'
    routes to the dedicated DATABASE_SYSTEM_V2 template.
    """
    # Try bucket type first, then legacy page type, then default to guide
    return BUCKET_TYPE_PROMPTS.get(page_type, PAGE_TYPE_PROMPTS.get(page_type, GUIDE_V2))
