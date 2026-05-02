"""Prompt template for incremental page updates."""

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
