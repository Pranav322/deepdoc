"""Word counting for the page-length validity gate (validation.py).

`_count_words` guards `validation.py:148`'s `word_count < 100` check, which is
one of the few conditions that sets `is_valid = False`. A page failing it burns
a quality retry *and* a full rewrite, so undercounting is expensive in LLM spend
as well as wrong.
"""

from __future__ import annotations

from deepdoc.generator.validation import _count_words

_GATE = 100  # mirrors validation.py:148


def test_english_matches_plain_split():
    """Purely additive for whitespace-separated text — English is unchanged."""
    for text in (
        "the quick brown fox jumps over the lazy dog",
        "One.\n\nTwo three\tfour.\n",
        "hyphenated-word and code_identifier and path/to/file.py",
        "",
    ):
        assert _count_words(text) == len(text.split()), text


def test_japanese_clears_the_gate():
    """Regression: split() returns 1 for spaceless Japanese, failing the gate."""
    text = "これはテストです。日本語のドキュメントを生成します。" * 8
    assert len(text.split()) < _GATE          # what the old code saw
    assert _count_words(text) >= _GATE        # what it should see


def test_chinese_clears_the_gate():
    text = "这是一个测试。我们生成中文文档。" * 10
    assert len(text.split()) < _GATE
    assert _count_words(text) >= _GATE


def test_mixed_content_counts_both_scripts():
    """Identifiers and paths stay untranslated, so real pages are mixed."""
    text = "認証は src/auth/login.py で処理されます"
    # 3 whitespace tokens + the CJK/kana characters around them
    assert _count_words(text) > len(text.split())


def test_korean_is_not_double_counted():
    """Hangul is space-separated, so it must not get the CJK bonus."""
    text = "이것은 한국어 문서입니다"
    assert _count_words(text) == len(text.split())
