"""V2 prompt templates — facade re-exporting from deepdoc.prompts sub-package.

All prompt constants and selector functions now live in deepdoc/prompts/.
This module re-exports everything for backward compatibility.
"""

from deepdoc.prompts import *  # noqa: F401, F403
from deepdoc.prompts import (
    SYSTEM_V2,
    CROSS_LINK_SECTION,
    UPDATE_PAGE_V2,
    OVERVIEW_V2,
    ARCHITECTURE_V2,
    GUIDE_V2,
    MODULE_V2,
    API_REFERENCE_V2,
    SETUP_V2,
    DEPLOYMENT_V2,
    INTEGRATION_V2,
    PAGE_TYPE_PROMPTS,
    SYSTEM_BUCKET_V2,
    FEATURE_BUCKET_V2,
    ENDPOINT_BUCKET_V2,
    INTEGRATION_BUCKET_V2,
    DATABASE_SYSTEM_V2,
    DATABASE_OVERVIEW_V2,
    DATABASE_GROUP_V2,
    RUNTIME_SYSTEM_V2,
    GRAPHQL_SYSTEM_V2,
    ENDPOINT_REF_V2,
    TRAINING_BUCKET_V2,
    ARCHITECTURE_COMPONENT_V2,
    DATA_PIPELINE_V2,
    RESEARCH_CONTEXT_V2,
    START_HERE_INDEX_V2,
    DOMAIN_GLOSSARY_V2,
    DEBUG_RUNBOOK_V2,
    START_HERE_SETUP_V2,
    PROMPT_STYLE_TEMPLATES,
    BUCKET_TYPE_PROMPTS,
    get_prompt_for_bucket,
    get_prompt_for_page_type,
)
