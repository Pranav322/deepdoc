"""Maps file extensions → parser functions."""

from __future__ import annotations

from pathlib import Path

from .base import ParsedFile
from .go_parser import parse_go
from .java_parser import parse_java
from .js_ts_parser import parse_js_ts
from .php_parser import parse_php
from .python_parser import parse_python
from .rust_parser import parse_rust
from .vue_parser import parse_vue

# extension → (language_name, parser_function)
_REGISTRY: dict[str, tuple[str, callable]] = {
    ".py": ("python", parse_python),
    ".js": ("javascript", parse_js_ts),
    ".jsx": ("javascript", parse_js_ts),
    ".ts": ("typescript", parse_js_ts),
    ".tsx": ("typescript", parse_js_ts),
    ".mjs": ("javascript", parse_js_ts),
    ".cjs": ("javascript", parse_js_ts),
    ".go": ("go", parse_go),
    ".php": ("php", parse_php),
    ".vue": ("vue", parse_vue),
    ".java": ("java", parse_java),
    ".rs": ("rust", parse_rust),
}


def supported_extensions() -> set[str]:
    return set(_REGISTRY.keys())


def language_for_extension(ext: str) -> str:
    """Language name for a file extension, or "" when unsupported."""
    entry = _REGISTRY.get(ext.lower())
    return entry[0] if entry else ""


def parse_file(path: Path, content: str | None = None) -> ParsedFile | None:
    """Parse a source file. Returns None if extension not supported."""
    ext = path.suffix.lower()
    if ext not in _REGISTRY:
        return None
    language, parser_fn = _REGISTRY[ext]
    cached_content = content
    try:
        if cached_content is None:
            cached_content = path.read_text(encoding="utf-8", errors="replace")
        return parser_fn(path, cached_content, language)
    except Exception:
        # Graceful degradation — return minimal parsed file
        if cached_content is None:
            try:
                cached_content = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                cached_content = ""
        return ParsedFile(
            path=path, language=language, raw_content=cached_content[:12000]
        )
