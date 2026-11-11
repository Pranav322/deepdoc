"""Doc-ish words in a *source* file name must not make it a doc.

classify_source_kind matched "notes"/"history"/"readme"/... as substrings of any
file name, so src/app/api/notes.py (a FastAPI router) and order_history.py were
tagged "docs" and lost code priority in evidence and chatbot ranking.
"""
from __future__ import annotations

import pytest

from deepdoc.source_metadata import classify_source_kind


@pytest.mark.parametrize(
    "path",
    [
        "src/app/api/notes.py",
        "orders/order_history.py",
        "app/Http/Controllers/ReleaseNotesController.php",
        "internal/glossary/glossary.go",
        "src/changelog.ts",
    ],
)
def test_source_files_with_doc_words_stay_product(path: str) -> None:
    assert classify_source_kind(path) == "product"


@pytest.mark.parametrize(
    "path",
    ["NOTES.md", "release-notes.mdx", "HISTORY.rst", "docs/anything.py", "README.txt"],
)
def test_prose_files_are_still_docs(path: str) -> None:
    assert classify_source_kind(path) == "docs"
