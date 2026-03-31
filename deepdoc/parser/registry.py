"""Maps file extensions → parser functions."""

from __future__ import annotations

from pathlib import Path

from .base import ParsedFile
from .python_parser import parse_python
from .js_ts_parser import parse_js_ts
from .go_parser import parse_go
from .php_parser import parse_php
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
}


def supported_extensions() -> set[str]:
    return set(_REGISTRY.keys())


def parse_file(path: Path) -> ParsedFile | None:
    """Parse a source file. Returns None if extension not supported."""
    ext = path.suffix.lower()
    if ext not in _REGISTRY:
        return None
    language, parser_fn = _REGISTRY[ext]
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        return parser_fn(path, content, language)
    except Exception:
        # Graceful degradation — return minimal parsed file
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            content = ""
        return ParsedFile(path=path, language=language, raw_content=content[:5000])
