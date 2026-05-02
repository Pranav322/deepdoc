"""Prompt selector functions and lookup dictionaries."""

from .page_types import (
    OVERVIEW_V2,
    ARCHITECTURE_V2,
    GUIDE_V2,
    MODULE_V2,
    API_REFERENCE_V2,
    SETUP_V2,
    DEPLOYMENT_V2,
    INTEGRATION_V2,
    PAGE_TYPE_PROMPTS,
)
from .bucket_types import (
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
)

PROMPT_STYLE_TEMPLATES = {
    "system": SYSTEM_BUCKET_V2,
    "feature": FEATURE_BUCKET_V2,
    "endpoint": ENDPOINT_BUCKET_V2,
    "endpoint_ref": ENDPOINT_REF_V2,
    "integration": INTEGRATION_BUCKET_V2,
    "database": DATABASE_SYSTEM_V2,
    "database_overview": DATABASE_OVERVIEW_V2,
    "database_group": DATABASE_GROUP_V2,
    "runtime": RUNTIME_SYSTEM_V2,
    "runtime_overview": RUNTIME_SYSTEM_V2,
    "graphql": GRAPHQL_SYSTEM_V2,
    "training": TRAINING_BUCKET_V2,
    "architecture_component": ARCHITECTURE_COMPONENT_V2,
    "data_pipeline": DATA_PIPELINE_V2,
    "research_context": RESEARCH_CONTEXT_V2,
    "start_here_index": START_HERE_INDEX_V2,
    "domain_glossary": DOMAIN_GLOSSARY_V2,
    "debug_runbook": DEBUG_RUNBOOK_V2,
    "start_here_setup": START_HERE_SETUP_V2,
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
