"""Shared constants for the chatbot module."""

from __future__ import annotations

STOPWORD_TOKENS: frozenset[str] = frozenset({
    "a", "an", "and", "any", "are", "can", "does", "first", "for", "from",
    "handle", "handled", "how", "in", "is", "it", "its", "of", "or", "repo",
    "repository", "show", "that", "the", "this", "to", "use", "what", "went",
    "where", "who", "which", "with", "work",
})

DOC_SUFFIXES: frozenset[str] = frozenset({".md", ".mdx", ".txt", ".rst", ".adoc", ".ipynb"})

CODE_WORKSPACE_SUFFIXES: frozenset[str] = frozenset({
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".php", ".java", ".rb",
    ".rs", ".vue", ".svelte", ".html", ".css", ".scss", ".sass",
})

CODE_WORKSPACE_CONFIG_NAMES: frozenset[str] = frozenset({
    ".env", ".env.example", "docker-compose.yml", "docker-compose.yaml",
    "package.json", "pyproject.toml", "requirements.txt", "composer.json",
    "go.mod", "cargo.toml", "gemfile",
})

CODE_WORKSPACE_CONFIG_SUFFIXES: frozenset[str] = frozenset({
    ".json", ".toml", ".yaml", ".yml", ".ini", ".cfg",
})
