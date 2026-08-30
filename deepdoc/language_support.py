"""Language support registry — single source of truth for extension → language
mappings, parsers, call-graph extractors, route detectors, ORM detectors, and
runtime detectors.

This unifies the two previously separate extension maps:
  - ``parser/registry.py::_REGISTRY``  (extension → (language, parser_fn))
  - ``planner/engine.py::ext_to_lang`` (extension → language_name)

Slice 1 preserves backward compatibility — ``parser/registry.py`` is unchanged
and the scan loop's behaviour is identical, just sourced from this registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from pathlib import Path
    from .parser.base import ParsedFile

# ---------------------------------------------------------------------------
# Language support descriptor
# ---------------------------------------------------------------------------


@dataclass
class LanguageSupport:
    """What we know about a language and how we analyse it.

    Every file extension maps to exactly one ``LanguageSupport`` entry.
    Entries for unsupported languages exist but have ``parser_fn=None``,
    ``route_detectors=()``, and so on.
    """

    language: str
    extensions: list[str]
    parser_fn: Callable[[Path, str, str], Any] | None = None
    route_detectors: tuple[Any, ...] = ()

    @property
    def is_supported(self) -> bool:
        return self.parser_fn is not None


# ---------------------------------------------------------------------------
# Default registry — matches the existing parser + route + call-graph landscape
# ---------------------------------------------------------------------------


def _build_default_registry() -> dict[str, LanguageSupport]:
    """Construct a registry from the currently registered parsers and detectors.

    Returns a dict mapping *lowered* extension → ``LanguageSupport``.
    The registry is built at import time so callers always see the latest
    state of the route-detector and parser modules.

    Every extension in ``parser/registry.py::_REGISTRY`` maps to the same
    (language_name, parser_function) pair.  Every route detector in
    ``parser/routes/registry.py::ROUTE_DETECTOR_REGISTRY`` is attached to
    the matching language entry.

    Language-support entries are shared across extensions that belong to the
    same language (e.g. ``.js``, ``.jsx``, ``.mjs``, ``.cjs`` all point to
    the same ``LanguageSupport`` instance).
    """
    from .parser.registry import _REGISTRY
    from .parser.routes.registry import ROUTE_DETECTOR_REGISTRY

    # Build one LanguageSupport per unique language
    by_language: dict[str, LanguageSupport] = {}

    for ext, (lang, parser_fn) in _REGISTRY.items():
        if lang not in by_language:
            by_language[lang] = LanguageSupport(
                language=lang,
                extensions=[],
                parser_fn=parser_fn,
                route_detectors=ROUTE_DETECTOR_REGISTRY.get(lang, ()),
            )
        by_language[lang].extensions.append(ext)

    registry: dict[str, LanguageSupport] = {}
    for entry in by_language.values():
        for ext in entry.extensions:
            registry[ext] = entry

    return registry


# Module-level cache — populated on first access
_language_support_registry: dict[str, LanguageSupport] | None = None


def get_language_support_registry() -> dict[str, LanguageSupport]:
    """Return the extension → LanguageSupport registry.

    Built lazily so that downstream tests that mock route detectors or parsers
    still see the live state.
    """
    global _language_support_registry
    if _language_support_registry is None:
        _language_support_registry = _build_default_registry()
    return _language_support_registry


def get_language_support(ext: str) -> LanguageSupport | None:
    """Look up support for a single extension."""
    return get_language_support_registry().get(ext.lower())


def supported_extensions_from_registry() -> set[str]:
    """Return all extensions with parser support."""
    return {
        ext
        for ext, support in get_language_support_registry().items()
        if support.is_supported
    }


def language_name_for_extension(ext: str) -> str:
    """Return the language name for an extension, or the extension itself.

    This is the canonical replacement for ``ext_to_lang.get(ext, '')``.
    """
    support = get_language_support(ext)
    if support is not None:
        return support.language
    return ext.lstrip(".") if ext else ""


__all__ = [
    "LanguageSupport",
    "get_language_support_registry",
    "get_language_support",
    "supported_extensions_from_registry",
    "language_name_for_extension",
]