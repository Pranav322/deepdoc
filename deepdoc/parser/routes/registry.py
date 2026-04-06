"""Framework registration map for route detection."""

from __future__ import annotations

from .base import RegisteredRouteDetector
from .django import DETECTOR as DJANGO_DETECTOR
from .express import DETECTOR as EXPRESS_DETECTOR
from .falcon import DETECTOR as FALCON_DETECTOR
from .fastify import DETECTOR as FASTIFY_DETECTOR
from .go import DETECTOR as GO_DETECTOR
from .laravel import DETECTOR as LARAVEL_DETECTOR
from .nestjs import DETECTOR as NESTJS_DETECTOR

ROUTE_DETECTOR_REGISTRY: dict[str, tuple[RegisteredRouteDetector, ...]] = {
    "javascript": (
        EXPRESS_DETECTOR,
        FASTIFY_DETECTOR,
        NESTJS_DETECTOR,
    ),
    "typescript": (
        EXPRESS_DETECTOR,
        FASTIFY_DETECTOR,
        NESTJS_DETECTOR,
    ),
    "vue": (
        EXPRESS_DETECTOR,
        FASTIFY_DETECTOR,
    ),
    "python": (
        FALCON_DETECTOR,
        DJANGO_DETECTOR,
    ),
    "go": (GO_DETECTOR,),
    "php": (LARAVEL_DETECTOR,),
}


def get_detectors(language: str) -> tuple[RegisteredRouteDetector, ...]:
    return ROUTE_DETECTOR_REGISTRY.get(language, ())
