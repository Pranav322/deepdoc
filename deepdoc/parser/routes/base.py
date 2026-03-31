"""Shared models and detector contracts for route detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class APIEndpoint:
    """A detected API endpoint / route."""

    method: str  # GET, POST, PUT, DELETE, PATCH, etc.
    path: str  # /api/v2/users/:id
    handler: str = ""  # function name or controller method
    file: str = ""  # source file path
    route_file: str = ""  # file that registered the route
    handler_file: str = ""  # file that implements the handler when known
    line: int = 0  # line number
    description: str = ""  # inline comment or docstring
    middleware: list[str] = field(default_factory=list)
    request_body: str = ""  # inferred from decorators/types
    response_type: str = ""  # inferred from return type
    raw_path: str = ""  # unresolved route expression or child path
    framework: str = ""  # detector/framework that emitted this endpoint
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def display_method(self) -> str:
        return self.method.upper()

    @property
    def unique_key(self) -> str:
        return f"{self.method.upper()} {self.path}"


@dataclass
class RouteResolverContext:
    """Normalized inputs and seams for framework-specific route detectors."""

    path: Path
    content: str
    language: str
    resolver_state: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


RouteDetector = Callable[[RouteResolverContext], list[APIEndpoint]]


@dataclass(frozen=True)
class RegisteredRouteDetector:
    """Named detector entry used by the orchestrator registry."""

    name: str
    detect: RouteDetector
