"""Tests for citation injection, false-positive file refs, and claim-status propagation — Slice 14."""

from __future__ import annotations

from deepdoc.generator.claims import _is_false_positive_file_ref, ClaimExtractor, Claim
from deepdoc.generator.post_processors import inject_source_citations


class TestFalsePositiveFileRefs:
    def test_ip_address_is_false_positive(self):
        assert _is_false_positive_file_ref("127.0.0.1")

    def test_bare_number_is_false_positive(self):
        assert _is_false_positive_file_ref("13")

    def test_url_is_false_positive(self):
        assert _is_false_positive_file_ref("https://example.com")

    def test_version_like_is_false_positive(self):
        assert _is_false_positive_file_ref("3.14")
        assert _is_false_positive_file_ref("1.0")

    def test_ipv6_like_is_false_positive(self):
        assert _is_false_positive_file_ref("2001:db8:1")

    def test_numeric_range_is_false_positive(self):
        assert _is_false_positive_file_ref("1-76")

    def test_real_file_path_is_not_false_positive(self):
        assert not _is_false_positive_file_ref("src/main.py")
        assert not _is_false_positive_file_ref("docs/en/mkdocs.yml")
        assert not _is_false_positive_file_ref("scripts/docs.py")

    def test_hostname_and_port_are_false_positives(self):
        assert _is_false_positive_file_ref("localhost")
        assert _is_false_positive_file_ref("api.internal")
        assert _is_false_positive_file_ref("example.com")
        assert _is_false_positive_file_ref("[::1]")

    def test_file_with_version_is_not_false_positive(self):
        assert not _is_false_positive_file_ref("fastapi/__init__.py")
        assert not _is_false_positive_file_ref("deepdoc/cli.py")


class TestClaimExtractorFalsePositives:
    def test_ip_addr_not_a_file_ref(self):
        md = "The server runs on `127.0.0.1:8000` by default."
        claims = ClaimExtractor().extract(md)
        file_refs = [c for c in claims if c.claim_type == "file_ref"]
        assert len(file_refs) == 0

    def test_numbered_step_not_a_file_ref(self):
        md = "Follow step `13` for the next action."
        claims = ClaimExtractor().extract(md)
        file_refs = [c for c in claims if c.claim_type == "file_ref"]
        assert len(file_refs) == 0

    def test_real_file_still_captured(self):
        md = "Defined in `src/main.py:42` and handles the request."
        claims = ClaimExtractor().extract(md)
        file_refs = [c for c in claims if c.claim_type == "file_ref"]
        assert len(file_refs) == 1

    def test_localhost_port_not_a_file_ref(self):
        claims = ClaimExtractor().extract("Open `localhost:3000` in a browser.")
        assert not [c for c in claims if c.claim_type == "file_ref"]

    def test_hostname_port_not_a_file_ref(self):
        claims = ClaimExtractor().extract("Use `api.internal:8080` for the API.")
        assert not [c for c in claims if c.claim_type == "file_ref"]


class TestCitationInjection:
    def test_known_path_becomes_linked_citation(self):
        content = "The build script lives in `scripts/docs.py:208`."
        result = inject_source_citations(content, {"scripts/docs.py"})
        assert "`scripts/docs.py:208`" in result

    def test_known_path_with_commit(self):
        content = "See `src/main.py:42` for details."
        result = inject_source_citations(
            content,
            {"src/main.py"},
            git_remote="https://github.com/fastapi/fastapi",
            commit_sha="abc1234",
        )
        assert "github.com/fastapi/fastapi/blob/abc1234/src/main.py#L42" in result
        assert "`src/main.py:42`" in result

    def test_unknown_commit_renders_plain(self):
        content = "Defined in `src/main.py:42`."
        result = inject_source_citations(
            content,
            {"src/main.py"},
            git_remote="https://github.com/fastapi/fastapi",
            commit_sha="unknown",
        )
        assert "`src/main.py:42`" in result
        assert "github.com" not in result

    def test_hallucinated_path_unchanged(self):
        content = "Defined in `nonexistent/path.py:99`."
        result = inject_source_citations(content, {"src/main.py"})
        assert "`nonexistent/path.py:99`" in result

    def test_multiple_citations_in_page(self):
        content = (
            "The build uses `scripts/docs.py:208`. "
            "Configuration lives in `docs/en/mkdocs.yml:1`."
        )
        result = inject_source_citations(
            content,
            {"scripts/docs.py", "docs/en/mkdocs.yml"},
            git_remote="https://github.com/foo/bar",
            commit_sha="xyz",
        )
        assert result.count("github.com") == 2

    def test_local_repo_no_github(self):
        content = "Handler at `fastapi/exceptions.py:17`."
        result = inject_source_citations(
            content,
            {"fastapi/exceptions.py"},
            git_remote="",
            commit_sha="abc1234",
        )
        assert "`fastapi/exceptions.py:17`" in result
        assert "github.com" not in result

    def test_citation_skips_frontmatter_and_fenced_code(self):
        content = """---
description: `src/main.py:42`
---

Use `src/main.py:42` in prose.

```text
`src/main.py:42`
```
"""
        result = inject_source_citations(
            content,
            {"src/main.py"},
            git_remote="https://github.com/acme/repo.git",
            commit_sha="abc1234",
        )
        assert "description: `src/main.py:42`" in result
        assert result.count("github.com/acme/repo/blob/abc1234/src/main.py#L42") == 1
        assert "```text\n`src/main.py:42`\n```" in result

    def test_ssh_remote_is_normalized(self):
        result = inject_source_citations(
            "See `src/main.py:42`.",
            {"src/main.py"},
            git_remote="git@github.com:acme/repo.git",
            commit_sha="abc1234",
        )
        assert "https://github.com/acme/repo/blob/abc1234/src/main.py#L42" in result

    def test_existing_citation_is_not_nested(self):
        content = "[`src/main.py:42`](https://github.com/acme/repo/blob/abc/src/main.py#L42)"
        result = inject_source_citations(content, {"src/main.py"}, commit_sha="abc")
        assert result == content
