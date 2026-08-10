"""
The cache-busting stamp on asset URLs.

This exists because of a real outage. `/assets` is served with
`max-age=14400` and no revalidation, and a deploy changed the grouping rules
without changing the `?v=3` that asked for them. Returning students got new
HTML against a four-hour-old copy of the JavaScript, the two disagreed about
what an option group id looks like, and the calendar rendered nothing at all.

So the stamp is derived from the files rather than typed, and these tests pin
the two properties that matter: it changes when an asset changes, and every
template that references an asset carries it.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

import main
import static_version


@pytest.fixture(autouse=True)
def _fresh_stamp():
    """The stamp is memoised per process, so tests reset it."""
    static_version._stamp = None
    yield
    static_version._stamp = None


def test_the_stamp_is_stable_while_the_assets_are():
    assert static_version.asset_version() == static_version.asset_version()


def test_changing_an_asset_changes_the_stamp(tmp_path, monkeypatch):
    """
    The whole point. A deploy that edits a script has to change the URL that
    asks for it, or a cached copy of the old one survives the deploy.
    """
    assets = tmp_path / "assets" / "js"
    assets.mkdir(parents=True)
    script = assets / "calendar-utils.js"
    script.write_text("const a = 1;")
    monkeypatch.setattr(static_version, "ASSETS_DIR", tmp_path / "assets")

    before = static_version._compute()
    script.write_text("const a = 2;")
    after = static_version._compute()

    assert before != after


def test_renaming_an_asset_changes_the_stamp(tmp_path, monkeypatch):
    assets = tmp_path / "assets" / "js"
    assets.mkdir(parents=True)
    (assets / "one.js").write_text("const a = 1;")
    monkeypatch.setattr(static_version, "ASSETS_DIR", tmp_path / "assets")
    before = static_version._compute()

    (assets / "one.js").rename(assets / "two.js")

    assert static_version._compute() != before


def test_an_unversioned_file_does_not_churn_the_stamp(tmp_path, monkeypatch):
    """Audio and icons are never referenced with a stamp, so they do not move it."""
    assets = tmp_path / "assets"
    (assets / "js").mkdir(parents=True)
    (assets / "js" / "one.js").write_text("const a = 1;")
    monkeypatch.setattr(static_version, "ASSETS_DIR", assets)
    before = static_version._compute()

    (assets / "amazin.mp3").write_bytes(b"not really audio")

    assert static_version._compute() == before


def test_a_missing_assets_directory_does_not_stop_the_server(tmp_path, monkeypatch):
    monkeypatch.setattr(static_version, "ASSETS_DIR", tmp_path / "nothing-here")

    assert static_version.asset_version() == "dev"


ASSET_URL = re.compile(r'/assets/(?:js|css)/[a-z-]+\.(?:js|css)(\?v=[a-z0-9]+)?')


@pytest.mark.parametrize("path", ["/calendar", "/explore"])
def test_every_asset_a_page_asks_for_is_stamped(path):
    """
    A single unstamped script is enough to reproduce the outage, so this
    asserts over whatever the page happens to reference rather than a list
    someone has to remember to update.
    """
    with TestClient(main.app) as client:
        html = client.get(path).text

    referenced = ASSET_URL.findall(html)
    assert referenced, f"{path} references no local assets, which cannot be right"
    assert all(referenced), f"{path} asks for an asset with no version stamp"
