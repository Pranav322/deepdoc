"""Modular route detection package."""

from .base import APIEndpoint, RegisteredRouteDetector, RouteResolverContext
from .detector import detect_endpoints
from .registry import ROUTE_DETECTOR_REGISTRY, get_detectors
from .repo_resolver import resolve_repo_endpoints

__all__ = [
    "APIEndpoint",
    "RegisteredRouteDetector",
    "RouteResolverContext",
    "ROUTE_DETECTOR_REGISTRY",
    "detect_endpoints",
    "resolve_repo_endpoints",
    "get_detectors",
]
