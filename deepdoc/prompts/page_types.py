"""Page-type prompt templates (overview, architecture, guide, module, api_reference, setup, deployment, integration)."""

from .system import CROSS_LINK_SECTION

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
