"""DEFAULT_CONFIG must stay in sync with the fallbacks written in code.

Two failure modes this guards against:

* A key read as ``cfg.get("x", FALLBACK)`` but absent from ``DEFAULT_CONFIG``
  works, yet never appears in ``deepdoc config show`` — so nobody can discover
  it. (``batch_size`` was in this state despite being documented in the README.)
* A key present in both, where the two values disagree. ``load_config`` always
  merges over ``DEFAULT_CONFIG``, so the fallback is unreachable in production
  and only bites unit tests passing a bare dict — silently applying a different
  threshold than the shipped one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from deepdoc.config import DEFAULT_CONFIG

_ROOT = Path(__file__).resolve().parents[1] / "deepdoc"

# (config key, module, literal fallback written at the call site)
_DOCUMENTED_FALLBACKS = [
    ("batch_size", "generator/generation.py", 10),
    ("max_files_per_bucket", "planner/bucket_refinement.py", 25),
    ("max_flow_files", "planner/specializations.py", 45),
    ("max_flow_symbols", "planner/specializations.py", 80),
    ("consistency_pass", "generator/consistency.py", True),
    ("decompose_threshold", "planner/bucket_refinement.py", 7),
    ("consolidation_similarity_threshold", "planner/bucket_refinement.py", 0.55),
    ("consolidation_similarity_threshold", "planner/heuristics.py", 0.55),
]


@pytest.mark.parametrize("key,module,fallback", _DOCUMENTED_FALLBACKS)
def test_default_matches_the_in_code_fallback(key, module, fallback):
    assert key in DEFAULT_CONFIG, f"{key} is read in code but missing from DEFAULT_CONFIG"
    assert DEFAULT_CONFIG[key] == fallback, (
        f"{key}: DEFAULT_CONFIG says {DEFAULT_CONFIG[key]!r} but "
        f"{module} falls back to {fallback!r}"
    )


@pytest.mark.parametrize("key,module,fallback", _DOCUMENTED_FALLBACKS)
def test_the_fallback_literal_is_still_what_the_source_says(key, module, fallback):
    """Catches someone editing the call site without touching the default."""
    source = (_ROOT / module).read_text()
    match = re.search(rf'\.get\(\s*"{re.escape(key)}"\s*,\s*([^)\s,]+)', source)
    assert match, f"no `.get(\"{key}\", ...)` call found in {module}"
    literal = match.group(1)

    # The fallback may be a module-level constant (e.g. BATCH_SIZE) rather than
    # a literal; resolve it so the comparison is against the real value.
    if literal.isidentifier() and literal not in ("True", "False", "None"):
        const = re.search(rf"^{re.escape(literal)}\s*=\s*(.+)$", source, re.M)
        assert const, f"{module}: cannot resolve constant {literal}"
        literal = const.group(1).split("#")[0].strip()

    assert literal in (repr(fallback), str(fallback)), (
        f"{module} now falls back to {literal}, not {fallback!r} — "
        f"update DEFAULT_CONFIG[{key!r}] to match"
    )


def test_frameworks_is_declared_like_languages():
    """Both are descriptive-only prompt context; they should look alike."""
    assert DEFAULT_CONFIG["frameworks"] == []
    assert isinstance(DEFAULT_CONFIG["languages"], list)


def test_llm_api_version_is_declared():
    """`deepdoc init --provider azure` writes it and client.py tells users to
    set it, so it has to exist in the schema."""
    assert DEFAULT_CONFIG["llm"]["api_version"] == ""


def test_empty_api_version_sends_no_kwarg():
    """Declaring the key must not change Azure behaviour.

    `.get()` returns None when absent but "" when declared; both consumers
    guard with `if self.api_version:` so an empty string is skipped exactly
    like None.
    """
    source = (_ROOT / "llm" / "client.py").read_text()
    assert source.count("if self.api_version:") == 2


# ── the duplicated chatbot schema must not rot apart again ────────────────────


def _flat(d: dict, prefix: str = "") -> set[str]:
    keys = set()
    for key, value in d.items():
        keys.add(prefix + key)
        if isinstance(value, dict):
            keys |= _flat(value, f"{prefix}{key}.")
    return keys


def test_the_two_chatbot_schemas_declare_the_same_keys():
    """`chatbot` is declared in config.py AND chatbot/settings.py.

    Their only divergence was eight `rate_limits` keys that existed solely in
    config.py and were never read — the tell that they were never implemented.
    Pin the two together so the next divergence is caught immediately.
    """
    from deepdoc.chatbot.settings import DEFAULT_CHATBOT_CONFIG

    assert _flat(DEFAULT_CONFIG["chatbot"]) == _flat(DEFAULT_CHATBOT_CONFIG)


@pytest.mark.parametrize("path", [
    ("include_feature_pages",),
    ("github_pages",),
    ("chatbot", "vector_store"),
    ("chatbot", "answer", "rate_limits"),
    ("chatbot", "embeddings", "rate_limits"),
    ("compatibility", "deprecated_version_warning", "minimum_version"),
    ("compatibility", "deprecated_version_warning", "upgrade_command"),
])
def test_removed_keys_stay_removed(path):
    """Guards against a dead key being reintroduced by a merge."""
    node = DEFAULT_CONFIG
    for part in path[:-1]:
        node = node.get(part, {})
    assert path[-1] not in node, f"{'.'.join(path)} is dead — it should not be back"


def test_the_live_rate_limits_block_survives():
    """Only `llm.rate_limits` was ever wired (llm/client.py) — keep it."""
    assert set(DEFAULT_CONFIG["llm"]["rate_limits"]) == {
        "max_concurrency", "requests_per_minute", "tokens_per_minute", "adaptive_backoff",
    }


def test_an_old_config_containing_removed_keys_still_loads():
    """Existing .deepdoc.yaml files contain these; they must be inert, not fatal."""
    from deepdoc.config import _deep_merge

    stale = {
        "github_pages": {"enabled": True, "branch": "gh-pages"},
        "include_feature_pages": False,
        "chatbot": {"vector_store": {"kind": "faiss"}},
    }
    merged = _deep_merge(dict(DEFAULT_CONFIG), stale)
    assert merged["output_dir"] == DEFAULT_CONFIG["output_dir"]
    assert merged["github_pages"]["enabled"] is True  # carried, simply unread
