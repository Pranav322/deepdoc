"""Dispatcher for framework-specific route detection."""

from __future__ import annotations

from pathlib import Path

from .base import APIEndpoint, RouteResolverContext
from .common import dedupe_endpoints
from .registry import get_detectors


def detect_endpoints(path: Path, content: str, language: str) -> list[APIEndpoint]:
    """Detect all API endpoints in a file. Returns empty list if none found."""
    context = RouteResolverContext(path=path, content=content, language=language)
    endpoints: list[APIEndpoint] = []
    for detector in get_detectors(language):
        detected = detector.detect(context)
        for endpoint in detected:
            if not endpoint.framework:
                endpoint.framework = detector.name
            if not endpoint.route_file:
                endpoint.route_file = str(context.path)
            if not endpoint.file:
                endpoint.file = endpoint.route_file
            if not endpoint.handler_file:
                endpoint.handler_file = endpoint.file
            if not endpoint.raw_path:
                endpoint.raw_path = endpoint.path
        endpoints.extend(detected)
    return dedupe_endpoints(endpoints)
