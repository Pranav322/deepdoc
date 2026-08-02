"""upload_site_to_r2 overwrites a prefix that is serving live traffic, and now
deletes from it. Both behaviours are worth pinning:

  * assets must be written before HTML, or a visitor mid-rebuild gets new HTML
    referencing chunks that do not exist yet
  * files the previous build left behind must be removed, or deleted pages stay
    reachable forever
  * a sweep failure must never fail the build
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hosted-runner"))


class FakeR2:
    """Minimal stand-in for the boto3 S3 client surface pipeline.py uses."""

    def __init__(self, existing: list[str] | None = None, page_size: int = 1000):
        self.objects: dict[str, bytes] = {k: b"old" for k in (existing or [])}
        self.put_order: list[str] = []
        self.deleted: list[str] = []
        self.page_size = page_size
        self.list_calls = 0
        self.fail_list = False

    def put_object(self, Bucket, Key, Body, ContentType):  # noqa: N803
        self.objects[Key] = Body
        self.put_order.append(Key)

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):  # noqa: N803
        if self.fail_list:
            raise RuntimeError("R2 list blew up")
        self.list_calls += 1
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        start = int(ContinuationToken) if ContinuationToken else 0
        page = keys[start : start + self.page_size]
        nxt = start + self.page_size
        out = {"Contents": [{"Key": k} for k in page], "IsTruncated": nxt < len(keys)}
        if out["IsTruncated"]:
            out["NextContinuationToken"] = str(nxt)
        return out

    def delete_objects(self, Bucket, Delete):  # noqa: N803
        for o in Delete["Objects"]:
            self.deleted.append(o["Key"])
            self.objects.pop(o["Key"], None)


@pytest.fixture()
def site(tmp_path: Path) -> Path:
    out = tmp_path / "site"
    (out / "_next" / "static").mkdir(parents=True)
    (out / "index.html").write_text("<html>new</html>")
    (out / "guide").mkdir()
    (out / "guide" / "index.html").write_text("<html>guide</html>")
    (out / "_next" / "static" / "chunk.abc123.js").write_text("console.log(1)")
    (out / "styles.css").write_text("body{}")
    return out


def _upload(client, site_out: Path, log: list):
    import pipeline

    orig = pipeline._r2_client
    pipeline._r2_client = lambda: client
    try:
        pipeline.upload_site_to_r2("Acme", "Widgets", site_out, log)
    finally:
        pipeline._r2_client = orig


def test_assets_are_uploaded_before_html(site: Path):
    client = FakeR2()
    _upload(client, site, [])
    html = [i for i, k in enumerate(client.put_order) if k.endswith(".html")]
    assets = [i for i, k in enumerate(client.put_order) if not k.endswith(".html")]
    assert assets and html
    assert max(assets) < min(html), f"HTML written before assets: {client.put_order}"


def test_prefix_is_lowercased(site: Path):
    client = FakeR2()
    _upload(client, site, [])
    assert all(k.startswith("acme/widgets/") for k in client.put_order)


def test_previous_build_leftovers_are_removed(site: Path):
    client = FakeR2(existing=[
        "acme/widgets/removed-page/index.html",           # page deleted between builds
        "acme/widgets/_next/static/chunk.OLD999.js",      # superseded chunk
    ])
    log: list = []
    _upload(client, site, log)
    assert "acme/widgets/removed-page/index.html" in client.deleted
    assert "acme/widgets/_next/static/chunk.OLD999.js" in client.deleted
    assert any("removed 2 stale" in line for line in log)


def test_current_build_files_are_never_deleted(site: Path):
    client = FakeR2(existing=["acme/widgets/index.html"])  # same key, new content
    _upload(client, site, [])
    assert "acme/widgets/index.html" not in client.deleted
    assert client.objects["acme/widgets/index.html"] == b"<html>new</html>"


def test_other_projects_are_untouched(site: Path):
    client = FakeR2(existing=["other/project/index.html"])
    _upload(client, site, [])
    assert client.deleted == []
    assert "other/project/index.html" in client.objects


def test_sweep_paginates_beyond_one_page(site: Path):
    stale = [f"acme/widgets/old/{i}.html" for i in range(1205)]
    client = FakeR2(existing=stale, page_size=1000)
    _upload(client, site, [])
    assert len(client.deleted) == 1205, "pagination dropped the tail of the listing"
    assert client.list_calls >= 2


def test_sweep_failure_does_not_fail_the_build(site: Path):
    client = FakeR2(existing=["acme/widgets/gone.html"])
    client.fail_list = True
    log: list = []
    _upload(client, site, log)  # must not raise
    assert any("sweep failed" in line for line in log)
    assert any("uploaded" in line for line in log)
