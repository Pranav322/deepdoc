"""Tests for hierarchical navigation shaping — Slice 13."""

from __future__ import annotations

from pathlib import Path

from deepdoc.v2_models import DocBucket, DocPlan
from deepdoc.planner.nav_shaping import (
    _build_nav_items,
    _short_display_title,
    _slug_to_title,
)


def _bucket(slug, title, parent_slug=None, section="Core", hints=None):
    return DocBucket(
        bucket_type="feature",
        title=title,
        slug=slug,
        section=section,
        description="",
        parent_slug=parent_slug,
        generation_hints=hints or {},
    )


class TestBuildNavItems:
    def test_flat_list_returns_flat(self):
        slugs = ["intro", "auth", "routing"]
        b = {s: _bucket(s, s.title()) for s in slugs}
        items = _build_nav_items(slugs, b, {}, {})
        assert items == slugs

    def test_parent_with_children_becomes_group(self):
        buckets = {
            "security": _bucket("security", "Security"),
            "security-oauth": _bucket("security-oauth", "Security OAuth", parent_slug="security"),
            "security-apikey": _bucket("security-apikey", "Security API Key", parent_slug="security"),
        }
        items = _build_nav_items(
            ["security", "security-oauth", "security-apikey"], buckets, {}, {}
        )
        assert len(items) == 1
        assert isinstance(items[0], dict)
        assert items[0]["parent_slug"] == "security"
        assert set(items[0]["children"]) == {"security-oauth", "security-apikey"}

    def test_mixed_parent_and_orphan_pages(self):
        buckets = {
            "intro": _bucket("intro", "Introduction"),
            "auth": _bucket("auth", "Auth"),
            "auth-login": _bucket("auth-login", "Auth Login", parent_slug="auth"),
            "routing": _bucket("routing", "Routing"),
        }
        items = _build_nav_items(
            ["intro", "auth", "auth-login", "routing"], buckets, {}, {}
        )
        assert "intro" in items
        assert "routing" in items
        groups = [i for i in items if isinstance(i, dict)]
        assert len(groups) == 1
        assert groups[0]["parent_slug"] == "auth"

    def test_no_parent_in_slugs_stays_flat(self):
        buckets = {
            "auth": _bucket("auth", "Auth"),
            "auth-login": _bucket("auth-login", "Auth Login", parent_slug="auth"),
        }
        items = _build_nav_items(["auth-login"], buckets, {}, {})
        assert items == ["auth-login"]

    def test_multiple_parent_groups(self):
        buckets = {
            "api": _bucket("api", "API"),
            "api-users": _bucket("api-users", "API Users", parent_slug="api"),
            "api-orders": _bucket("api-orders", "API Orders", parent_slug="api"),
            "ops": _bucket("ops", "Operations"),
            "ops-cd": _bucket("ops-cd", "Ops CD", parent_slug="ops"),
        }
        items = _build_nav_items(
            ["api", "api-users", "api-orders", "ops", "ops-cd"], buckets, {}, {}
        )
        groups = [i for i in items if isinstance(i, dict)]
        assert len(groups) == 2
        parent_slugs = {g["parent_slug"] for g in groups}
        assert parent_slugs == {"api", "ops"}


class TestShortDisplayTitle:
    def test_short_title_kept(self):
        b = _bucket("auth", "Auth System")
        assert _short_display_title("auth", b) == "Auth System"

    def test_long_title_with_overview_suffix(self):
        b = _bucket("doc-translation", "Documentation Translation Automation Overview")
        result = _short_display_title("doc-translation", b)
        assert "Documentation" in result
        assert len(result) > 0

    def test_long_title_with_pipeline_suffix(self):
        b = _bucket("ci-cd", "CI, Quality Gates, and Dependency Automation")
        result = _short_display_title("ci-cd", b)
        assert "CI" in result
        assert len(result) > 0

    def test_four_words_kept(self):
        b = _bucket("routing", "HTTP and WebSocket Route Registration")
        assert _short_display_title("routing", b) == b.title


class TestSlugToTitle:
    def test_basic(self):
        assert _slug_to_title("my-page") == "My Page"

    def test_multi_word(self):
        assert _slug_to_title("database-schema") == "Database Schema"