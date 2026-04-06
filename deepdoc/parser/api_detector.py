"""Compatibility facade for modular route detection."""

from __future__ import annotations

from .routes import (
    ROUTE_DETECTOR_REGISTRY,
    APIEndpoint,
    RegisteredRouteDetector,
    RouteResolverContext,
    detect_endpoints,
    get_detectors,
)

__all__ = [
    "APIEndpoint",
    "ROUTE_DETECTOR_REGISTRY",
    "RegisteredRouteDetector",
    "RouteResolverContext",
    "detect_endpoints",
    "get_detectors",
]
