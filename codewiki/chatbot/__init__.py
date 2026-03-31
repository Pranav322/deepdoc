"""Chatbot support for CodeWiki."""

from .indexer import ChatbotIndexer
from .service import ChatbotQueryService, create_fastapi_app
from .settings import chatbot_enabled

__all__ = [
    "ChatbotIndexer",
    "ChatbotQueryService",
    "chatbot_enabled",
    "create_fastapi_app",
]
